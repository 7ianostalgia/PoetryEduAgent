const API = {
  createJob: "/api/learning/jobs",
  jobs: (role, limit, offset) => `/api/learning/jobs?role=${encodeURIComponent(role)}&limit=${limit}&offset=${offset}`,
  job: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}`,
  result: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}/result`,
  agents: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}/agents`,
  events: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}/events/stream`,
  feedback: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}/feedback`,
  package: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}/package.zip`,
  quiz: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}/quiz`,
  report: (jobId) => `/api/learning/jobs/${encodeURIComponent(jobId)}/report`,
  image: (path) => `/api/image?path=${encodeURIComponent(path)}`,
};

const gradeMap = {
  primary: ["一年级", "二年级", "三年级", "四年级", "五年级", "六年级"],
  junior: ["初一", "初二", "初三"],
};

// 保留清晰的阶段映射，便于后端新增阶段时维护。
const stageCardIndex = {
  queued: "poem_analysis",
  analyzing: "poem_analysis",
  text_stage: "text_resources",
  generating_resources: "text_resources",
  generating_quiz: "text_resources",
  image_generation: "kolors",
  vision_review: "vision_reviewer",
  image_correction: "image_prompt",
  deepseek_review: "text_reviewer",
  local_review_d2: "text_reviewer",
  completed: "final_gate",
};

const feedbackModules = {
  classroom_intro: "课堂导入",
  teaching_goals: "教学目标",
  teaching_key_difficulties: "教学重难点",
  layered_explanations: "分层讲解",
  guided_questions: "问题链",
  classroom_activities: "课堂活动",
  quiz: "学生测评题",
};

const state = {
  role: "teacher",
  page: "input",
  activeJobId: null,
  generationToken: 0,
  pollTimer: null,
  eventSource: null,
  result: null,
  questions: [],
  report: null,
  historyOffset: 0,
  historyLimit: 8,
};

const dom = {
  pages: [...document.querySelectorAll(".page")],
  roleButtons: [...document.querySelectorAll(".role-switch button[data-role]")],
  stepbar: document.querySelector("#stepbar"),
  stage: document.querySelector("#stage"),
  grade: document.querySelector("#grade"),
  form: document.querySelector("#learning-form"),
  agentCards: [...document.querySelectorAll(".agent-card[data-agent-id]")],
  progressBar: document.querySelector("#progress-bar"),
  progressText: document.querySelector("#job-progress"),
  statusText: document.querySelector("#job-status-text"),
  jobIdText: document.querySelector("#job-id-text"),
  quizForm: document.querySelector("#quiz-form"),
  toast: document.querySelector("#toast"),
  feedbackDialog: document.querySelector("#feedback-dialog"),
};

let toastTimer;
const safeText = (value, fallback = "") => typeof value === "string" && value.trim() ? value.trim() : fallback;
const asList = (value) => Array.isArray(value) ? value.filter(Boolean) : value ? [value] : [];

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function prettyJson(value) {
  try { return JSON.stringify(value ?? {}, null, 2); } catch { return String(value ?? ""); }
}

function showToast(message) {
  dom.toast.textContent = message;
  dom.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => dom.toast.classList.remove("show"), 3300);
}

async function requestJson(url, options = {}, timeout = 12000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = body.detail?.message || body.detail || `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : prettyJson(detail));
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

function workflowSteps() {
  return state.role === "teacher" ? ["输入学情", "Agent 协同", "教师资源包"] : ["输入学情", "Agent 协同", "学习内容", "学习报告"];
}

function renderStepbar() {
  const pageIndex = { input: 0, processing: 1, teacher: 2, student: 2, report: 3, history: -1 }[state.page] ?? 0;
  dom.stepbar.innerHTML = pageIndex < 0 ? "<b class=\"active\">历史任务</b>" : workflowSteps().map((label, index, items) => {
    const className = index === pageIndex ? "active" : index < pageIndex ? "done" : "";
    return `<b class="${className}">${index + 1}. ${label}</b>${index < items.length - 1 ? "<i>→</i>" : ""}`;
  }).join("");
}

function showPage(page) {
  state.page = page;
  const id = { input: "view-input", processing: "view-processing", teacher: "view-teacher-result", student: "view-student-result", report: "view-report", history: "view-history" }[page];
  dom.pages.forEach((element) => element.classList.toggle("active", element.id === id));
  renderStepbar();
  scrollTo({ top: 0, behavior: "smooth" });
}

function renderRoleCopy() {
  const teacher = state.role === "teacher";
  document.querySelector("#hero-title").innerHTML = teacher ? "从一首诗，生成一堂<br /><em>可直接使用的课</em>" : "跟着一首诗，完成一次<br /><em>有反馈的诗词学习</em>";
  document.querySelector("#hero-description").textContent = teacher
    ? "面向教师的备课工作台：生成可直接使用的教学资源，并提供可追溯的审核结论。"
    : "面向学生的诗词学习空间：读原诗、看图、学字词、做测评，得到专属学习报告。";
  document.querySelector("#role-goals").innerHTML = (teacher
    ? ["备课内容可直接使用", "按模块反馈重做", "文字与图片双审核"]
    : ["原诗与字词卡", "答题后即时讲解", "生成学习建议"]).map((item) => `<span>✓ ${item}</span>`).join("");
  document.querySelector("#form-title").textContent = teacher ? "创建备课任务" : "创建诗词学习任务";
  document.querySelector("#level-label").textContent = teacher ? "班级学习水平" : "我的当前水平";
  document.querySelector("#weakness-label").textContent = teacher ? "重点教学目标" : "我想重点提升";
  document.querySelector("#requirements-label").textContent = teacher ? "补充备课要求" : "补充学习偏好";
  document.querySelector("#submit-label").textContent = teacher ? "开始生成教师资源包" : "开始我的诗词学习";
  document.querySelector("#resource-branch-note").textContent = teacher ? "面向教师的课堂资源与测评预览" : "面向学生的学习资源与四题测评";
  document.querySelector("#resource-agent-title").textContent = teacher ? "课堂资源 Agent" : "学生学习资源 Agent";
  document.querySelector("#resource-agent-description").textContent = teacher ? "生成教学目标、重难点、活动、讲解与测评" : "生成字词卡、阅读步骤、互动引导与测评";
  dom.roleButtons.forEach((button) => button.classList.toggle("active", button.dataset.role === state.role));
}

function populateGrades() {
  const grades = gradeMap[dom.stage.value] || gradeMap.primary;
  dom.grade.innerHTML = grades.map((grade) => `<option>${grade}</option>`).join("");
  dom.grade.value = dom.stage.value === "primary" ? "四年级" : "初一";
}

function getPayload() {
  return {
    poem_id: "jing-ye-si",
    poem: document.querySelector("#poem").value.trim(),
    role: state.role,
    custom_requirements: document.querySelector("#custom-requirements").value.trim(),
    student_profile: {
      grade: dom.grade.value,
      level: document.querySelector("#level").value,
      weakness: [...document.querySelectorAll("#weaknesses input:checked")].map((input) => input.value),
      goal: state.role === "teacher" ? "prepare_role_appropriate_poetry_lesson" : "understand_poetic_meaning_and_emotion",
      preferences: { needs_visual_support: true, audience_role: state.role },
    },
  };
}

function stopUpdates() {
  state.generationToken += 1;
  clearTimeout(state.pollTimer);
  state.eventSource?.close();
  state.eventSource = null;
}

function switchRole(role) {
  if (!["teacher", "student"].includes(role)) return;
  stopUpdates();
  state.role = role;
  state.activeJobId = null;
  state.result = null;
  renderRoleCopy();
  showPage("input");
}

function resetAgentCards() {
  dom.agentCards.forEach((card) => {
    card.classList.remove("running", "completed", "failed");
    card.querySelector(".agent-state span").textContent = "等待中";
    card.querySelector(".agent-popover header span").textContent = "等待中";
    card.querySelector(".agent-popover pre").textContent = "等待后端事件。该 Agent 尚未启动时不会提前显示为运行中。";
  });
}

function renderAgents(payload) {
  const agents = new Map(asList(payload?.agents).map((agent) => [agent.id || agent.agent_id, agent]));
  dom.agentCards.forEach((card) => {
    const agent = agents.get(card.dataset.agentId);
    if (!agent) return; // 第二支路没有后端事件时保持“等待中”。
    const status = agent.status || "waiting";
    card.classList.remove("running", "completed", "failed");
    if (["running", "completed", "failed"].includes(status)) card.classList.add(status);
    const label = { waiting: "等待中", queued: "等待中", running: "处理中", completed: "已完成", succeeded: "已完成", failed: "执行失败" }[status] || status;
    const state = card.querySelector(".agent-state span");
    state.textContent = label;
    if (status === "failed") state.textContent = "执行失败";
    card.querySelector(".agent-popover header span").textContent = label;
    const logs = asList(agent.logs || agent.events);
    card.querySelector(".agent-popover pre").textContent = agent.output != null
      ? prettyJson(agent.output)
      : logs.length ? logs.map((item) => `[${item.created_at ? new Date(item.created_at).toLocaleTimeString("zh-CN", { hour12: false }) : "--:--:--"}] ${item.message || item.stage || "状态更新"}`).join("\n")
        : "等待该 Agent 开始运行…";
  });
}

function renderSingleAgentEvent(event) {
  const id = event.agent_id || event.agent?.id || event.id;
  if (!id) return;
  const card = dom.agentCards.find((item) => item.dataset.agentId === id);
  if (!card) return;
  const status = event.status || (event.output != null ? "completed" : "running");
  if (status === "running") card.dataset.runningAt = String(Date.now());
  const elapsed = Date.now() - Number(card.dataset.runningAt || 0);
  if (status === "completed" && elapsed < 360) {
    setTimeout(
      () => renderAgents({ agents: [{ id, status, output: event.output, logs: [event] }] }),
      360 - Math.max(0, elapsed),
    );
    return;
  }
  renderAgents({ agents: [{ id, status, output: event.output, logs: [event] }] });
}

function renderJob(job) {
  const progress = Math.max(Number(dom.progressText.textContent.replace("%", "")) || 0, Math.min(100, Number(job.progress || 0)));
  dom.progressBar.style.width = `${progress}%`;
  dom.progressText.textContent = `${progress}%`;
  dom.statusText.textContent = safeText(job.message, job.stage === "queued" ? "任务已排队，等待 Agent 启动" : `正在执行 ${stageCardIndex[job.stage] || "智能体流程"}`)
    + (job.stage === "text_stage" ? "（本地模型通常需要 3～6 分钟）" : "");
  dom.jobIdText.textContent = state.activeJobId || job.job_id || "等待任务编号";
}

async function finishJob(token) {
  if (token !== state.generationToken) return;
  const result = await requestJson(API.result(state.activeJobId), {}, 20000);
  state.result = result;
  stopUpdates();
  renderResult(result);
}

function applyLivePayload(payload, token) {
  if (token !== state.generationToken || !payload) return;
  const job = payload.job || payload;
  if (job.stage || job.progress != null) renderJob(job);
  if (payload.agents) renderAgents(payload);
  if (payload.agent_id || payload.agent) renderSingleAgentEvent(payload);
  const stage = job.stage || payload.stage;
  if (stage === "completed" && !payload.agent_id) {
    finishJob(token).catch((error) => showToast(`读取结果失败：${error.message}`));
  }
  if (stage === "failed") {
    stopUpdates();
    dom.statusText.textContent = safeText(job.error || payload.error, "gpu 任务执行失败");
  }
}

function startSse(token) {
  if (!window.EventSource || token !== state.generationToken) return startPolling(token);
  const stream = new EventSource(API.events(state.activeJobId));
  state.eventSource = stream;
  let opened = false;
  stream.onopen = () => { opened = true; dom.statusText.textContent = "实时事件已连接，等待 Agent 更新"; };
  stream.onmessage = (message) => {
    try { applyLivePayload(JSON.parse(message.data), token); } catch { /* 忽略心跳文本 */ }
  };
  ["job", "agent", "progress", "completed", "failed"].forEach((name) => stream.addEventListener(name, (message) => {
    try { applyLivePayload(JSON.parse(message.data), token); } catch { /* 忽略非 JSON 事件 */ }
  }));
  stream.addEventListener("workflow_event", (message) => {
    try { applyLivePayload(JSON.parse(message.data), token); } catch { /* 忽略非 JSON 事件 */ }
  });
  stream.onerror = () => {
    stream.close();
    if (state.eventSource === stream) state.eventSource = null;
    if (token === state.generationToken) {
      dom.statusText.textContent = opened ? "实时连接中断，已切换轮询" : "实时通道不可用，已切换轮询";
      startPolling(token);
    }
  };
}

async function startPolling(token, failures = 0) {
  if (token !== state.generationToken || !state.activeJobId || state.eventSource) return;
  try {
    const [job, agents] = await Promise.all([requestJson(API.job(state.activeJobId)), requestJson(API.agents(state.activeJobId))]);
    if (token !== state.generationToken) return;
    renderJob(job);
    renderAgents(agents);
    if (job.stage === "completed") return finishJob(token);
    if (job.stage === "failed") return applyLivePayload(job, token);
    state.pollTimer = setTimeout(() => startPolling(token), 1400);
  } catch (error) {
    if (failures < 4) state.pollTimer = setTimeout(() => startPolling(token, failures + 1), 1800);
    else {
      dom.statusText.textContent = "gpu 任务连接失败";
      showToast("gpu 服务暂时无法连接；不会用 dev 结果替代");
    }
  }
}

function getResultParts(data) {
  const outputs = data.text_stage?.agent_outputs || data.agent_outputs || {};
  return {
    outputs,
    analysis: outputs.poem_analysis || data.poem_analysis || {},
    resources: outputs.learning_resources || data.learning_resources || {},
    quiz: outputs.quiz || data.quiz,
    decision: data.final_decision || data.final_review || {},
    vision: data.vision_review?.output || data.vision_review || {},
    textReview: data.text_review || {},
  };
}

function setDecision(element, decision) {
  const passed = decision.pass === true;
  element.className = `decision-badge ${passed ? "pass" : "fail"}`;
  element.textContent = passed ? "✓ 资源审核通过" : (typeof decision.pass === "boolean" ? "资源需教师复核" : "流程已完成");
}

function setGeneratedImage(element, path) {
  if (path) element.src = API.image(path); else element.removeAttribute("src");
}

function renderLayers(container, layered = {}, student = false) {
  const labels = student ? ["第一步 · 读懂", "第二步 · 想象", "第三步 · 品味"] : ["基础层", "进阶层", "拓展层"];
  container.innerHTML = ["basic", "medium", "advanced"].map((key, index) => `<div><b>${labels[index]}</b><br>${escapeHtml(safeText(layered[key], "暂无内容"))}</div>`).join("");
}

function listHtml(items, fallback = "暂无内容") {
  return asList(items).length ? asList(items).map((item) => {
    const text = typeof item === "string"
      ? item
      : item.name
        ? `${item.name}：${asList(item.procedure).join("；")}${item.purpose ? `（${item.purpose}）` : ""}`
        : item.title || item.content || prettyJson(item);
    return `<li>${escapeHtml(text)}</li>`;
  }).join("") : `<li>${fallback}</li>`;
}

function normalizeQuiz(data, parts = getResultParts(data)) {
  if (parts.quiz?.objective_questions) {
    return [
      ...parts.quiz.objective_questions.map((item) => ({ ...item, kind: "objective", id: item.id, question: item.question })),
      ...parts.quiz.subjective_questions.map((item) => ({ ...item, kind: "subjective", id: item.id, question: item.question })),
    ];
  }
  return asList(data.quiz).map((item) => ({
    id: item.question_id || item.id, kind: item.kind, question: item.prompt || item.question,
    options: Object.fromEntries(asList(item.options).map((option) => [option.label, option.text])),
    answer: item.answer, explanation: item.explanation,
  }));
}

function renderTeacher(data) {
  const parts = getResultParts(data);
  const resources = parts.resources;
  setDecision(document.querySelector("#teacher-decision"), parts.decision);
  setGeneratedImage(document.querySelector("#teacher-image"), data.image?.image_path || data.image_path);
  document.querySelector("#teacher-image-review").textContent = parts.vision.pass ? "课堂配图内容审核通过" : "课堂配图建议教师课前确认";
  document.querySelector("#teacher-intro").textContent = safeText(resources.classroom_intro, "暂未生成课堂导入。");
  document.querySelector("#teacher-objectives").innerHTML = listHtml(resources.teaching_goals || parts.analysis.teaching_focus);
  const keyDifficulties = resources.teaching_key_difficulties || {};
  const focusItems = [
    ...asList(keyDifficulties.key_points).map((item) => `重点：${item}`),
    ...asList(keyDifficulties.difficulties).map((item) => `难点：${item}`),
  ];
  document.querySelector("#teacher-focus").innerHTML = listHtml(focusItems.length ? focusItems : parts.analysis.teaching_focus);
  renderLayers(document.querySelector("#teacher-layers"), resources.layered_explanations);
  document.querySelector("#teacher-questions").innerHTML = listHtml(resources.guided_questions, "暂未生成问题链。");
  document.querySelector("#teacher-activities").innerHTML = listHtml(resources.classroom_activities || resources.activities || resources.activity_design);
  const quiz = normalizeQuiz(data, parts);
  document.querySelector("#teacher-quiz-preview").innerHTML = quiz.map((item, index) => `<p><b>${index + 1}. ${item.kind === "objective" ? "客观题" : "主观题"}</b> ${escapeHtml(item.question)}</p>`).join("") || "<p>暂无测评题。</p>";
  document.querySelector("#teacher-analysis-summary").textContent = `本资源围绕“${safeText(parts.analysis.emotion, "诗意理解与情感体会")}”组织课堂内容，并结合当前学段安排分层任务。`;
  document.querySelector("#teacher-analysis").textContent = prettyJson({ poem_analysis: parts.analysis, student_profile: data.student_profile });
  document.querySelector("#teacher-image-tech").textContent = prettyJson({
    image_generation: {
      seed: data.image?.seed,
      steps: data.image?.steps,
      guidance_scale: data.image?.guidance_scale,
      width: data.image?.width,
      height: data.image?.height,
    },
    vision_review: data.vision_review,
  });
  document.querySelector("#teacher-review-summary").textContent = parts.decision.pass ? "文字内容和课堂配图均已通过审核，可在教师确认后使用。" : "系统已完成审核，请教师重点复核标记项后使用。";
  document.querySelector("#teacher-audit-status").textContent = parts.decision.pass ? "通过" : "需要复核";
  document.querySelector("#teacher-text-status").textContent = parts.decision.text_pass === true ? "通过" : "需要复核";
  document.querySelector("#teacher-image-status").textContent = parts.decision.vision_pass === true ? "通过" : "需要复核";
  document.querySelector("#teacher-risk").textContent = parts.decision.pass
    ? "无明显问题"
    : asList(parts.decision.failed_parts).join("、") || "存在需要教师确认的内容";
  document.querySelector("#teacher-suggestion").textContent = parts.decision.pass
    ? "可直接用于课堂展示"
    : "建议教师检查标记项后再用于课堂";
  document.querySelector("#teacher-reviews").textContent = prettyJson({ text_review: parts.textReview, vision_review: data.vision_review, final_decision: parts.decision });
  showPage("teacher");
}

function poemText(data) {
  if (typeof data.poem === "string") return data.poem;
  if (Array.isArray(data.poem?.text)) return data.poem.text.join("\n");
  return state.payload?.poem || "";
}

function renderQuiz(questions) {
  state.questions = questions;
  dom.quizForm.innerHTML = questions.map((item, index) => item.kind === "objective"
    ? `<section class="quiz-card" data-question-id="${escapeHtml(item.id)}"><h4>${index + 1}. ${escapeHtml(item.question)}</h4><div class="option-grid">${Object.entries(item.options || {}).map(([label, text]) => `<label><input type="radio" name="${escapeHtml(item.id)}" value="${escapeHtml(label)}" required> ${escapeHtml(label)}. ${escapeHtml(text)}</label>`).join("")}</div><div class="answer-explanation" hidden></div></section>`
    : `<section class="quiz-card" data-question-id="${escapeHtml(item.id)}"><h4>${index + 1}. ${escapeHtml(item.question)}</h4><textarea name="${escapeHtml(item.id)}" rows="3" required placeholder="请结合诗句写出你的理解……"></textarea><div class="agent-feedback" hidden></div></section>`
  ).join("") + `<button class="primary-button" type="submit"><span>提交答案，生成学习报告</span><b>→</b></button>`;
}

function renderStudent(data) {
  const parts = getResultParts(data);
  setDecision(document.querySelector("#student-decision"), parts.decision);
  setGeneratedImage(document.querySelector("#student-image"), data.image?.image_path || data.image_path);
  document.querySelector("#student-poem").textContent = poemText(data);
  document.querySelector("#student-intro").textContent = safeText(parts.resources.classroom_intro, parts.analysis.plain_translation || "先朗读原诗，再观察画面中的景物和人物动作。");
  document.querySelector("#student-word-cards").innerHTML = asList(parts.analysis.word_notes).map((item) => `<i>${escapeHtml(item)}</i>`).join("") || "<i>结合诗句猜一猜重点字词</i>";
  const emotionTags = Array.isArray(parts.analysis.emotion_tags)
    ? parts.analysis.emotion_tags
    : String(parts.analysis.emotion || "").split(/[,，、；;]+/).map((item) => item.trim()).filter(Boolean);
  document.querySelector("#student-emotion-tags").innerHTML = emotionTags.map((item) => `<i>${escapeHtml(item)}</i>`).join("") || "<i>边读边感受</i>";
  document.querySelector("#student-image-guide").textContent = safeText(parts.resources.image_interaction_guide, `请在图中找一找：${asList(parts.analysis.imagery).join("、") || "诗里写到的景物"}。它们让你感到怎样的气氛？`);
  renderLayers(document.querySelector("#student-layers"), parts.resources.layered_explanations, true);
  document.querySelector("#student-guided-questions").innerHTML = listHtml(parts.resources.guided_questions, "从景物、动作和情感三个方向读一读。");
  renderQuiz(normalizeQuiz(data, parts));
  showPage("student");
}

function renderResult(result) {
  if (state.role === "teacher") renderTeacher(result); else renderStudent(result);
  showToast("Agent 流程已完成");
}

function renderReport(report) {
  state.report = report;
  const score = Math.max(0, Math.min(100, Math.round(Number(report.score ?? report.total_score ?? 0))));
  document.querySelector("#report-score").textContent = score;
  const details = asList(report.details || report.subjective_scores);
  const good = asList(report.mastered || report.strengths || report.mastered_points);
  const improve = asList(report.weak_points || report.needs_improvement);
  document.querySelector("#report-good").innerHTML = listHtml(good.length ? good : details.filter((item) => item.is_correct || Number(item.score) >= Number(item.max_score || item.total_score || 5) * 0.7).map((item) => item.feedback || item.question_id), score >= 60 ? "已完成本次学习任务。" : "认真完成了全部题目。");
  document.querySelector("#report-improve").innerHTML = listHtml(improve.length ? improve : details.filter((item) => item.is_correct === false || Number(item.score) < Number(item.max_score || item.total_score || 5) * 0.7).map((item) => item.feedback || item.question_id), "继续练习诗意概括与证据表达。");
  document.querySelector("#report-path").innerHTML = listHtml(report.next_learning_path || report.recommended_review || report.review_suggestions || report.summary, "重读原诗与字词卡，再看一次分层讲解。");
  details.filter((item) => (item.kind === "subjective" || item.question_id?.startsWith("sub"))).forEach((item) => {
    const box = dom.quizForm.querySelector(`[data-question-id="${CSS.escape(item.question_id)}"] .agent-feedback`);
    if (box) { box.hidden = false; box.textContent = `智能点评：${item.feedback || item.comment || "已完成点评"}`; }
  });
  showPage("report");
}

async function openHistory() {
  stopUpdates();
  showPage("history");
  document.querySelector("#history-title").textContent = `${state.role === "teacher" ? "教师" : "学生"}历史任务`;
  const list = document.querySelector("#history-list");
  list.innerHTML = "<p class=\"empty-state\">正在读取历史任务…</p>";
  try {
    const payload = await requestJson(API.jobs(state.role, state.historyLimit, state.historyOffset));
    const jobs = payload.items || payload.jobs || (Array.isArray(payload) ? payload : []);
    list.innerHTML = jobs.length ? jobs.map((job) => `<article class="history-card"><div><b>${escapeHtml(job.title || job.poem_title || job.poem_id || "古诗学习任务")}</b><span>${escapeHtml(job.created_at ? new Date(job.created_at).toLocaleString("zh-CN") : "")}</span><small>${escapeHtml(job.message || job.stage || job.status || "")}</small></div><button type="button" data-history-job="${escapeHtml(job.job_id || job.id)}" data-history-report="${state.role === "student" && Boolean(job.has_report || job.report_ready)}">${state.role === "student" && (job.has_report || job.report_ready) ? "打开报告" : "打开旧结果"}</button></article>`).join("") : "<p class=\"empty-state\">当前角色暂无历史任务。</p>";
    document.querySelector("#history-prev").disabled = state.historyOffset === 0;
    document.querySelector("#history-next").disabled = jobs.length < state.historyLimit;
    document.querySelector("#history-page").textContent = `第 ${Math.floor(state.historyOffset / state.historyLimit) + 1} 页`;
  } catch (error) {
    list.innerHTML = `<p class="empty-state">历史任务读取失败：${escapeHtml(error.message)}</p>`;
  }
}

async function openHistoricalJob(jobId, reportOnly) {
  stopUpdates();
  state.activeJobId = jobId;
  try {
    if (reportOnly) return renderReport(await requestJson(API.report(jobId)));
    const job = await requestJson(API.job(jobId));
    if (!["completed", "failed"].includes(job.stage)) {
      state.result = null;
      resetAgentCards();
      showPage("processing");
      renderJob(job);
      renderAgents(await requestJson(API.agents(jobId)));
      startSse(state.generationToken);
      return;
    }
    state.result = await requestJson(API.result(jobId), {}, 20000);
    renderResult(state.result);
  } catch (error) { showToast(`打开历史任务失败：${error.message}`); }
}

dom.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = getPayload();
  if (!payload.poem) return showToast("请先输入古诗文内容");
  stopUpdates();
  state.result = null;
  state.payload = payload;
  resetAgentCards();
  showPage("processing");
  dom.progressBar.style.width = "0%";
  dom.progressText.textContent = "0%";
  try {
    const job = await requestJson(API.createJob, { method: "POST", body: JSON.stringify(payload) });
    state.activeJobId = job.job_id || job.id;
    if (!state.activeJobId) throw new Error("后端响应缺少 job_id");
    renderJob({ ...job, stage: job.stage || job.status || "queued", progress: job.progress || 0, message: job.message || "任务已排队，等待 Agent 启动" });
    const queuedCard = dom.agentCards.find((card) => card.dataset.agentId === stageCardIndex.queued);
    if (queuedCard) queuedCard.querySelector(".agent-popover pre").textContent = "任务已进入队列，等待 Agent 事件。";
    const token = state.generationToken;
    startSse(token);
  } catch (error) {
    dom.statusText.textContent = "任务创建失败";
    showToast(`创建失败：${error.message}`);
  }
});

dom.quizForm.addEventListener("change", (event) => {
  if (event.target.type !== "radio") return;
  const item = state.questions.find((question) => question.id === event.target.name);
  const box = event.target.closest(".quiz-card")?.querySelector(".answer-explanation");
  if (!item || !box) return;
  const correct = String(event.target.value).toUpperCase() === String(item.answer || "").toUpperCase();
  box.hidden = false;
  box.className = `answer-explanation ${correct ? "correct" : "incorrect"}`;
  box.textContent = item.answer ? `${correct ? "回答正确。" : `正确答案是 ${item.answer}。`} ${item.explanation || ""}` : safeText(item.explanation, "已记录你的选择，提交后可在报告中查看评分。");
});

dom.quizForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const answers = [...new FormData(dom.quizForm).entries()].map(([question_id, answer]) => ({ question_id, answer: String(answer).trim() }));
  if (answers.length !== state.questions.length) return showToast("请完成全部题目后再提交");
  const button = dom.quizForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const response = await requestJson(API.quiz(state.activeJobId), { method: "POST", body: JSON.stringify({ answers }) }, 120000);
    renderReport(response.report || response);
  } catch (error) { showToast(`提交失败：${error.message}`); }
  finally { button.disabled = false; }
});

document.querySelectorAll(".feedback-trigger").forEach((button) => button.addEventListener("click", () => {
  const module = button.closest("[data-module]").dataset.module;
  document.querySelector("#feedback-module").innerHTML = Object.entries(feedbackModules).map(([value, label]) => `<option value="${value}" ${value === module ? "selected" : ""}>${label}</option>`).join("");
  dom.feedbackDialog.showModal();
}));

document.querySelector("#feedback-form").addEventListener("submit", async (event) => {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  const target_module = document.querySelector("#feedback-module").value;
  const feedback = document.querySelector("#feedback-text").value.trim();
  if (!feedback) return;
  try {
    const submit = document.querySelector("#feedback-submit");
    submit.disabled = true;
    submit.querySelector("span").textContent = "Agent 正在按反馈重做…";
    await requestJson(API.feedback(state.activeJobId), { method: "POST", body: JSON.stringify({ target_module, feedback }) }, 360000);
    dom.feedbackDialog.close();
    document.querySelector("#feedback-text").value = "";
    state.result = await requestJson(API.result(state.activeJobId), {}, 20000);
    renderTeacher(state.result);
    showToast(`${feedbackModules[target_module]}已根据教师反馈重新生成`);
  } catch (error) { showToast(`反馈提交失败：${error.message}`); }
  finally {
    const submit = document.querySelector("#feedback-submit");
    submit.disabled = false;
    submit.querySelector("span").textContent = "提交反馈并刷新模块";
  }
});

document.querySelector("#download-result").addEventListener("click", () => {
  if (state.activeJobId) window.location.assign(API.package(state.activeJobId));
});
document.querySelector("#history-button").addEventListener("click", () => { state.historyOffset = 0; openHistory(); });
document.querySelector("#history-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-history-job]");
  if (button) openHistoricalJob(button.dataset.historyJob, button.dataset.historyReport === "true");
});
document.querySelector("#history-prev").addEventListener("click", () => { state.historyOffset = Math.max(0, state.historyOffset - state.historyLimit); openHistory(); });
document.querySelector("#history-next").addEventListener("click", () => { state.historyOffset += state.historyLimit; openHistory(); });
document.querySelector("#history-back").addEventListener("click", () => showPage("input"));
document.querySelector("#back-to-study").addEventListener("click", () => showPage("student"));
dom.roleButtons.forEach((button) => button.addEventListener("click", () => switchRole(button.dataset.role)));
dom.stage.addEventListener("change", populateGrades);
document.querySelector("#brand-home").addEventListener("click", () => switchRole(state.role));
document.querySelector("#cancel-view-button").addEventListener("click", () => switchRole(state.role));
document.querySelectorAll(".restart-button").forEach((button) => button.addEventListener("click", () => switchRole(state.role)));

resetAgentCards();
populateGrades();
renderRoleCopy();
showPage("input");

requestJson("/api/health", {}, 3500).then((health) => {
  const runMode = health.run_mode;
  if (!["dev", "gpu"].includes(runMode)) throw new Error("后端返回了无效 RUN_MODE");
  const devMode = runMode === "dev";
  const badge = document.querySelector("#runtime-badge");
  badge.className = runMode;
  badge.textContent = devMode
    ? "dev 无卡演示"
    : health.deepseek_configured
      ? "gpu 模式 · DeepSeek-V4-Flash 在线"
      : "gpu 模式";
  document.querySelector("#runtime-note").textContent = devMode
    ? "当前为 dev 模式（无卡演示），不加载 GPU 模型或外部审核服务"
    : health.deepseek_configured
      ? "当前为 gpu 模式，文字审核使用 DeepSeek-V4-Flash"
      : "当前为 gpu 模式；DeepSeek-V4-Flash 未配置";
}).catch(() => {
  document.querySelector("#runtime-badge").textContent = "后端未连接";
  document.querySelector("#runtime-note").textContent = "无法连接 API，请检查服务是否启动";
});
