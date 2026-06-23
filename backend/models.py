from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LearningStage(str, Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    GENERATING_RESOURCES = "generating_resources"
    GENERATING_QUIZ = "generating_quiz"
    TEXT_STAGE = "text_stage"
    IMAGE_GENERATION = "image_generation"
    VISION_REVIEW = "vision_review"
    DEEPSEEK_REVIEW = "deepseek_review"
    LOCAL_REVIEW_D2 = "local_review_d2"
    IMAGE_CORRECTION = "image_correction"
    COMPLETED = "completed"
    FAILED = "failed"


class StudentProfileInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    grade: str = "七年级"
    level: Literal["basic", "medium", "advanced"] = "basic"
    weakness: list[str] = Field(
        default_factory=lambda: ["imagery_analysis", "emotion_summary"]
    )
    goal: str = "understand_poetic_meaning_and_emotion"
    preferences: dict[str, Any] = Field(
        default_factory=lambda: {"needs_visual_support": True}
    )


class CreateLearningJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poem_id: Literal["jing-ye-si"] = "jing-ye-si"
    poem: str = (
        "床前明月光，疑是地上霜。举头望明月，低头思故乡。"
    )
    role: Literal["teacher", "student"] = "student"
    custom_requirements: Annotated[str, Field(max_length=500)] = ""
    student_profile: StudentProfileInput = Field(
        default_factory=StudentProfileInput
    )


class LearningJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    poem_id: str
    role: Literal["teacher", "student"] = "student"
    stage: LearningStage
    progress: Annotated[int, Field(ge=0, le=100)]
    message: str
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class TeacherFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_module: Literal[
        "classroom_intro",
        "layered_explanations",
        "guided_questions",
        "teaching_goals",
        "teaching重点难点",
        "teaching_key_difficulties",
        "classroom_activities",
        "quiz",
    ]
    feedback: Annotated[str, Field(min_length=1, max_length=2000)]

    @field_validator("feedback")
    @classmethod
    def strip_feedback(cls, value: str) -> str:
        return value.strip()


class ChoiceOption(BaseModel):
    label: str
    text: str


class QuizQuestion(BaseModel):
    question_id: str
    kind: Literal["objective", "subjective"]
    prompt: str
    points: Annotated[int, Field(gt=0)]
    options: list[ChoiceOption] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def objective_questions_have_options(
        cls, value: list[ChoiceOption], info
    ) -> list[ChoiceOption]:
        kind = info.data.get("kind")
        if kind == "objective" and len(value) < 2:
            raise ValueError("objective questions require at least two options")
        if kind == "subjective" and value:
            raise ValueError("subjective questions cannot have options")
        return value


class PoemResource(BaseModel):
    poem_id: str
    title: str
    author: str
    dynasty: str
    text: list[str]
    pinyin: list[str]
    translation: str
    appreciation: str
    knowledge_points: list[str]
    learning_steps: list[str]


class LearningResult(BaseModel):
    job_id: str
    poem: PoemResource
    quiz: list[QuizQuestion]


class QuizAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    answer: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("answer")
    @classmethod
    def strip_answer(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("answer cannot be blank")
        return stripped


class QuizSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: Annotated[list[QuizAnswer], Field(min_length=4, max_length=4)]

    @field_validator("answers")
    @classmethod
    def question_ids_are_unique(
        cls, value: list[QuizAnswer]
    ) -> list[QuizAnswer]:
        ids = [answer.question_id for answer in value]
        if len(ids) != len(set(ids)):
            raise ValueError("question_id must be unique")
        return value


class QuestionReport(BaseModel):
    question_id: str
    kind: Literal["objective", "subjective"]
    score: int
    max_score: int
    is_correct: Optional[bool]
    feedback: str
    reference_answer: str


class QuizReport(BaseModel):
    job_id: str
    poem_id: str
    score: int
    max_score: int
    objective_correct: int
    objective_total: Literal[2] = 2
    subjective_completed: int
    subjective_total: Literal[2] = 2
    passed: bool
    summary: str
    details: list[QuestionReport]
    submitted_at: datetime = Field(default_factory=utc_now)


class LegacyCreateJobRequest(BaseModel):
    """Compatibility request for the repository's early API contract."""

    model_config = ConfigDict(extra="forbid")

    poem: Annotated[str, Field(min_length=1)]
    title: str = "静夜思"
    author: str = "李白"
    grade: str = "小学"

    @field_validator("poem")
    @classmethod
    def poem_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("poem cannot be blank")
        return stripped


class LegacyCreatedJob(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime


class LegacyJob(LegacyCreatedJob):
    updated_at: datetime
    error: Optional[str] = None


class LegacyLearningResult(BaseModel):
    job_id: str
    title: str
    author: str
    summary: str
    translation: str
    appreciation: list[str]
    knowledge_points: list[str]
    mode: Literal["dev"] = "dev"


class LegacyQuizQuestion(BaseModel):
    id: str
    type: Literal["single_choice"] = "single_choice"
    prompt: str
    options: list[str]
    answer: str
    explanation: str


class LegacyQuiz(BaseModel):
    job_id: str
    questions: list[LegacyQuizQuestion]
