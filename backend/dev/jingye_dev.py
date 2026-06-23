from __future__ import annotations

from backend.models import (
    ChoiceOption,
    LearningResult,
    PoemResource,
    QuestionReport,
    QuizQuestion,
    QuizReport,
    QuizSubmission,
)


POEM = PoemResource(
    poem_id="jing-ye-si",
    title="静夜思",
    author="李白",
    dynasty="唐",
    text=["床前明月光", "疑是地上霜", "举头望明月", "低头思故乡"],
    pinyin=[
        "chuáng qián míng yuè guāng",
        "yí shì dì shàng shuāng",
        "jǔ tóu wàng míng yuè",
        "dī tóu sī gù xiāng",
    ],
    translation=(
        "明亮的月光洒在床前，仿佛地上铺了一层白霜。诗人抬头望着明月，"
        "又低下头思念远方的故乡。"
    ),
    appreciation=(
        "诗歌以月光、白霜和抬头低头的动作构成清晰画面。"
        "“疑”写出夜间恍惚的感受，“举头”与“低头”则把望月和思乡自然连接起来。"
    ),
    knowledge_points=[
        "作者李白，唐代诗人。",
        "核心意象是明月，主题是羁旅中的思乡之情。",
        "“举头”与“低头”形成动作对照，推动情感转折。",
    ],
    learning_steps=[
        "朗读全诗，读准“床、疑、霜、举”的字音。",
        "结合月光如霜的画面理解前两句。",
        "抓住“举头、低头”体会诗人由望月转入思乡。",
        "有感情地背诵全诗。",
    ],
)


QUIZ = [
    QuizQuestion(
        question_id="objective-1",
        kind="objective",
        prompt="《静夜思》的作者是谁？",
        points=20,
        options=[
            ChoiceOption(label="A", text="李白"),
            ChoiceOption(label="B", text="杜甫"),
            ChoiceOption(label="C", text="王维"),
            ChoiceOption(label="D", text="孟浩然"),
        ],
    ),
    QuizQuestion(
        question_id="objective-2",
        kind="objective",
        prompt="诗中最能直接点明思乡情感的是哪一句？",
        points=20,
        options=[
            ChoiceOption(label="A", text="床前明月光"),
            ChoiceOption(label="B", text="疑是地上霜"),
            ChoiceOption(label="C", text="举头望明月"),
            ChoiceOption(label="D", text="低头思故乡"),
        ],
    ),
    QuizQuestion(
        question_id="subjective-1",
        kind="subjective",
        prompt="“疑是地上霜”描绘了怎样的画面？请简要回答。",
        points=30,
    ),
    QuizQuestion(
        question_id="subjective-2",
        kind="subjective",
        prompt="“举头”和“低头”两个动作表达了诗人怎样的情感变化？",
        points=30,
    ),
]


OBJECTIVE_ANSWERS = {
    "objective-1": ("A", "李白"),
    "objective-2": ("D", "低头思故乡"),
}

SUBJECTIVE_RULES = {
    "subjective-1": {
        "keywords": ("月光", "白霜", "地上"),
        "reference": "明亮的月光洒在地上，洁白得仿佛铺了一层霜。",
    },
    "subjective-2": {
        "keywords": ("明月", "故乡", "思乡"),
        "reference": "诗人先抬头望月，再低头思念故乡，表达由望月触发的思乡之情。",
    },
}


def build_learning_result(job_id: str) -> LearningResult:
    # The quiz shape is a product invariant: exactly 2 objective + 2 subjective.
    assert sum(question.kind == "objective" for question in QUIZ) == 2
    assert sum(question.kind == "subjective" for question in QUIZ) == 2
    return LearningResult(job_id=job_id, poem=POEM, quiz=QUIZ)


def grade_quiz(job_id: str, submission: QuizSubmission) -> QuizReport:
    expected_ids = {question.question_id for question in QUIZ}
    answers = {answer.question_id: answer.answer for answer in submission.answers}
    if set(answers) != expected_ids:
        missing = sorted(expected_ids - set(answers))
        unknown = sorted(set(answers) - expected_ids)
        parts = []
        if missing:
            parts.append(f"missing question_id: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown question_id: {', '.join(unknown)}")
        raise ValueError("; ".join(parts))

    question_by_id = {question.question_id: question for question in QUIZ}
    details: list[QuestionReport] = []
    objective_correct = 0
    subjective_completed = 0

    for question_id in ("objective-1", "objective-2"):
        answer = answers[question_id].strip()
        expected_label, expected_text = OBJECTIVE_ANSWERS[question_id]
        normalized = answer.upper()
        correct = normalized == expected_label or answer == expected_text
        score = question_by_id[question_id].points if correct else 0
        objective_correct += int(correct)
        details.append(
            QuestionReport(
                question_id=question_id,
                kind="objective",
                score=score,
                max_score=question_by_id[question_id].points,
                is_correct=correct,
                feedback="回答正确。" if correct else f"正确答案是 {expected_label}：{expected_text}。",
                reference_answer=f"{expected_label}：{expected_text}",
            )
        )

    for question_id in ("subjective-1", "subjective-2"):
        answer = answers[question_id]
        rule = SUBJECTIVE_RULES[question_id]
        matched = sum(keyword in answer for keyword in rule["keywords"])
        max_score = question_by_id[question_id].points
        score = round(max_score * matched / len(rule["keywords"]))
        subjective_completed += 1
        details.append(
            QuestionReport(
                question_id=question_id,
                kind="subjective",
                score=score,
                max_score=max_score,
                is_correct=None,
                feedback=(
                    "要点完整，表达清楚。"
                    if matched == len(rule["keywords"])
                    else f"已覆盖 {matched}/{len(rule['keywords'])} 个参考要点，可结合参考答案补充。"
                ),
                reference_answer=rule["reference"],
            )
        )

    total_score = sum(item.score for item in details)
    return QuizReport(
        job_id=job_id,
        poem_id=POEM.poem_id,
        score=total_score,
        max_score=100,
        objective_correct=objective_correct,
        subjective_completed=subjective_completed,
        passed=total_score >= 60,
        summary=(
            "学习目标已达成，建议继续练习有感情地背诵。"
            if total_score >= 60
            else "建议复习诗歌画面、作者和思乡主题后再次作答。"
        ),
        details=details,
    )
