# DeepSeek-V4-Flash 文字审核

DeepSeek-V4-Flash 是 PoetryEduAgent 的独立文字教学质量审核模型。它不负责生成图片，也不参与 Qwen-VL 的视觉判断。

## 审核范围

输入包括：

- 古诗原文；
- 学生画像；
- SQLite / RAG 检索证据；
- 诗句解析；
- 教师端或学生端学习资源；
- 四道测评题及 rubric。

审核内容包括：

- 作者、朝代、原文和释义是否准确；
- 意象、情感和原诗证据是否一致；
- 分层讲解与学习活动是否适合学生画像；
- 问题链是否具有教学价值；
- 测评题、答案和 rubric 是否准确并对齐学习目标。

图像 Prompt、图片结果和视觉审核会在调用前移除。

## 配置

```bash
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

客户端调用兼容 OpenAI Chat Completions 格式的：

```text
POST {DEEPSEEK_BASE_URL}/chat/completions
```

请求使用 `response_format={"type":"json_object"}`，返回内容还必须通过项目定义的 JSON Schema。

## 输出

```json
{
  "reviewer": "deepseek-v4-flash",
  "review_result": "pass",
  "pass": true,
  "knowledge_issues": [],
  "quiz_issues": [],
  "teaching_issues": [],
  "required_actions": [],
  "review_summary": "文字教学资源通过审核",
  "fallback_used": false
}
```

工作流不会直接信任模型给出的 `pass`。后端会根据问题列表和 `required_actions` 重新规范化审核结果。

## 重试与 fallback

以下情况会触发 `DeepSeekReviewError`：

- Key 未配置；
- 请求超时或网络错误；
- HTTP 接口返回错误；
- 响应字段缺失；
- 内容不是可解析 JSON；
- JSON 不符合审核 Schema。

工作流先进行一次短重试。仍失败时，进入 `local_review_d2` 阶段，由 Qwen2.5-14B-Instruct-AWQ 按同一审核结构完成本地复核。

最终结果使用：

- `reviewer` 标明实际审核模型；
- `fallback_used` 标明是否使用本地 Qwen；
- `text_pass` 参与最终双门禁。

## 审核后修订

若 DeepSeek-V4-Flash 返回文字教学问题，资源修正 Agent 会接收：

- 原始诗词与学生画像；
- RAG 证据；
- 原诗句解析、学习资源和测评题；
- 问题分类与 `required_actions`。

修正范围仅限文字教学资源，不得修改图像 Prompt。修正后的结果会再次进入文字审核，避免未落实审核意见的内容被直接放行。

相关文档：[gpu 工作流](GPU_WORKFLOW.md) · [Qwen AWQ](QWEN_AWQ_INTEGRATION.md)
