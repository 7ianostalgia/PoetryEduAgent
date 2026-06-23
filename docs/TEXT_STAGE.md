# Qwen 文本阶段

文本阶段使用 Qwen2.5-14B-Instruct-AWQ，将古诗、学生画像和本地知识证据转换为可供教学资源支路与图像生成支路使用的结构化结果。

## 设计目标

在单张 GPU 环境下，重复加载同一个大语言模型会显著增加等待时间。因此当前实现采用一次模型加载完成多个逻辑 Agent 的职责，再通过严格 Schema 划分输出边界。

这是一种“单次推理、多职责输出”的工程实现；前端中的诗句解析、意象提取和课堂资源仍然是独立的业务节点。

## 输入

```text
古诗原文
+ 学生画像
+ SQLite / RAG 检索证据
+ 使用角色与补充要求
```

学生画像包含年级、能力水平、薄弱点、学习目标和偏好。教师端与学生端使用不同的资源生成约束：

- 教师端强调可评价目标、课堂问题链和可执行活动；
- 学生端强调适龄表达、分步理解和不直接泄露答案的思考提示。

## 输出结构

模型输出必须通过 `TEXT_STAGE_SCHEMA`，顶层包括：

| 字段 | 内容 |
| --- | --- |
| `student_diagnosis` | 当前水平、已掌握内容、薄弱点、推荐难度和资源策略 |
| `poem_analysis` | 释义、字词、意象、情感、原诗证据、手法和教学重点 |
| `learning_resources` | 分层讲解、导入、目标、重点难点、活动、问题链和画面 JSON |
| `quiz` | 两道客观题与两道带 rubric 的主观题 |
| `local_review` | 文本阶段内部的结构与风险初审 |

`learning_resources.standard_prompt_json` 是意象提取 Agent 的输出，只用于图像支路。课堂资源与画面 JSON 同批生成，但课堂资源 Agent 不读取该 JSON。

## 测评约束

- 题目 ID 固定为 `obj_1`、`obj_2`、`subj_1`、`subj_2`；
- 客观题必须有四个选项和唯一答案；
- 主观题必须提供参考答案、评分点和总分；
- 题目应对齐学生薄弱点，避免主要考查无关作者常识。

## 结构校验与语义护栏

JSON Schema 负责检查字段、类型、枚举和题目数量，但无法判断所有语义冲突。工作流会在 Schema 校验后执行确定性护栏：

- `emotion_evidence` 必须逐字来自原诗；
- 单幅图不能要求同一人物同时执行冲突动作；
- “疑是地上霜”应表现为月光联想，而非真实冰霜；
- 当前示范诗词的关键人物、床榻、明月和月光约束必须完整。

所有自动修正都会记录在 `guardrail_corrections`，不会静默覆盖模型输出。

## 后续使用

文本阶段结果分为两路：

- 图像路：`standard_prompt_json` → Prompt 编译 → Kolors → Qwen-VL；
- 文字路：诗句解析、学习资源与测评 → DeepSeek-V4-Flash / Qwen 文字审核。

文字审核前会移除 `standard_prompt_json`、`image_prompt` 和 `quality_prompts`，确保审核只评价文字教学内容。

相关文档：[gpu 工作流](GPU_WORKFLOW.md) · [Qwen AWQ](QWEN_AWQ_INTEGRATION.md)
