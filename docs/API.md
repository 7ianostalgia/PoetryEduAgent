# API 接口

PoetryEduAgent 使用 FastAPI 提供任务式接口。默认基础地址为 `http://127.0.0.1:7860`，字段采用 `snake_case`，交互式文档位于 `/docs`。

## 接口总览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 服务状态 |
| `GET` | `/api/config` | 当前运行模式与公开访问地址 |
| `POST` | `/api/learning/jobs` | 创建教师或学生任务 |
| `GET` | `/api/learning/jobs` | 查询历史任务 |
| `GET` | `/api/learning/jobs/{job_id}` | 查询任务状态 |
| `GET` | `/api/learning/jobs/{job_id}/events` | 增量读取 Agent 事件 |
| `GET` | `/api/learning/jobs/{job_id}/events/stream` | SSE 实时事件流 |
| `GET` | `/api/learning/jobs/{job_id}/overview` | 获取结果分区入口 |
| `GET` | `/api/learning/jobs/{job_id}/agents` | 获取协同大盘节点 |
| `GET` | `/api/learning/jobs/{job_id}/result` | 获取完整结果 |
| `GET` | `/api/learning/jobs/{job_id}/rag` | 获取 RAG 证据 |
| `GET` | `/api/learning/jobs/{job_id}/text` | 获取文字资源与审核 |
| `GET` | `/api/learning/jobs/{job_id}/image-result` | 获取图片、Prompt 快照与纠偏记录 |
| `GET` | `/api/learning/jobs/{job_id}/reviews` | 获取文字、图片和最终门禁 |
| `GET` | `/api/learning/jobs/{job_id}/quiz` | 获取四题测评 |
| `POST` | `/api/learning/jobs/{job_id}/quiz` | 提交学生答案 |
| `GET` | `/api/learning/jobs/{job_id}/report` | 获取学习报告 |
| `POST` | `/api/learning/jobs/{job_id}/feedback` | 提交教师定向反馈 |
| `GET` | `/api/learning/jobs/{job_id}/package.zip` | 下载教师资源包 |
| `GET` | `/api/image` | 读取生成图片 |

## 健康检查

### `GET /api/health`

```json
{
  "status": "ok",
  "service": "PoetryEduAgent",
  "run_mode": "gpu",
  "deepseek_configured": true
}
```

`deepseek_configured` 只表示服务进程已读取 DeepSeek-V4-Flash Key，不代表最近一次审核一定使用了远程模型。实际结果以 `text_review.reviewer` 和 `fallback_used` 为准。

### `GET /api/config`

返回当前 `run_mode`、监听配置和公开访问地址，不返回密钥或模型路径。

## 创建任务

### `POST /api/learning/jobs`

```json
{
  "poem_id": "jing-ye-si",
  "poem": "床前明月光，疑是地上霜。举头望明月，低头思故乡。",
  "role": "teacher",
  "custom_requirements": "课堂导入控制在三分钟内，增加一组分层提问。",
  "student_profile": {
    "grade": "七年级",
    "level": "basic",
    "weakness": ["imagery_analysis", "emotion_summary"],
    "goal": "understand_poetic_meaning_and_emotion",
    "preferences": {
      "needs_visual_support": true
    }
  }
}
```

字段说明：

| 字段 | 约束 |
| --- | --- |
| `poem_id` | 当前公开请求模型固定为 `jing-ye-si` |
| `poem` | 古诗原文 |
| `role` | `teacher` 或 `student` |
| `custom_requirements` | 最多 500 字 |
| `student_profile.grade` | 年级文本 |
| `student_profile.level` | `basic`、`medium` 或 `advanced` |
| `student_profile.weakness` | 学习薄弱点数组 |
| `student_profile.goal` | 学习目标 |
| `student_profile.preferences` | 可扩展偏好对象 |

成功响应为 `202 Accepted`：

```json
{
  "job_id": "job_6834a00d21684d41",
  "poem_id": "jing-ye-si",
  "role": "teacher",
  "stage": "queued",
  "progress": 0,
  "message": "任务已创建",
  "created_at": "2026-06-22T08:00:00Z",
  "updated_at": "2026-06-22T08:00:00Z",
  "error": null
}
```

## 查询任务与历史

### `GET /api/learning/jobs`

查询参数：

- `role=teacher|student`：按角色筛选；
- `limit=1..100`：默认 20；
- `offset>=0`：默认 0。

结果按创建时间倒序，附带 `title`、`has_result` 和 `has_report`。

### `GET /api/learning/jobs/{job_id}`

返回当前阶段、进度、状态消息和错误。gpu 工作流阶段见 [Agent 与任务状态](AGENT_STATE.md)。

## Agent 事件

### `GET /api/learning/jobs/{job_id}/events`

参数：

- `after_id`：只读取该事件 ID 之后的记录；
- `limit`：1 至 500，默认 200。

```json
{
  "job_id": "job_xxx",
  "events": [
    {
      "id": 12,
      "stage": "image_generation",
      "agent_id": "kolors",
      "status": "completed",
      "message": "Kolors 初始图片已生成",
      "output": {
        "image_path": "/output/job_xxx/images/image.png"
      },
      "created_at": "2026-06-22T08:01:00+00:00"
    }
  ],
  "next_after_id": 12
}
```

### `GET /api/learning/jobs/{job_id}/events/stream`

返回 `text/event-stream`。客户端可发送 `Last-Event-ID` 断点续传；任务进入 `completed` 或 `failed` 且没有新事件后，流自动结束。

## Agent 大盘

### `GET /api/learning/jobs/{job_id}/agents`

返回八个生成阶段节点的 `waiting`、`running`、`completed` 或 `failed` 状态，以及最近日志和可公开结构化输出。

```json
{
  "job_id": "job_xxx",
  "stage": "vision_review",
  "progress": 65,
  "agents": [
    {
      "id": "prompt_compiler",
      "name": "Kolors Prompt 编译器",
      "branch": "image",
      "status": "completed",
      "logs": [],
      "output": {
        "zh_prompt": "古代中国室内夜晚……",
        "negative_prompt": "现代家具，真实冰霜……"
      }
    }
  ]
}
```

该接口不返回系统提示词、模型思维链、密钥或服务器私密日志。

## 结果查询

### `GET /api/learning/jobs/{job_id}/overview`

返回任务摘要、结果是否就绪、最终门禁和各结果分区 URL，适合前端按需加载。

### `GET /api/learning/jobs/{job_id}/result`

返回完整结果，主要字段包括：

```text
job_id
role
poem
student_profile
text_stage
image
prompt_snapshot
vision_review
text_review
final_decision
correction_history
```

任务未完成时返回 `409`；任务失败时返回 `500` 和整理后的错误信息。

### 分区接口

- `/rag`：本地知识检索结果与来源证据；
- `/text`：文本阶段结果与文字审核；
- `/image-result`：最终图片、Prompt 快照、视觉审核与纠偏历史；
- `/reviews`：文字、图片和最终双门禁；
- `/quiz`：当前任务的四道题。

## 图片读取

### `GET /api/image?path=<absolute_image_path>`

只允许读取 `OUTPUT_DIR` 内的 `.png`、`.jpg`、`.jpeg` 和 `.webp` 文件。越界路径或不存在的文件统一返回 `404`。

## 学生测评

### `POST /api/learning/jobs/{job_id}/quiz`

请求必须恰好包含当前任务的四个不重复题号：

```json
{
  "answers": [
    {"question_id": "obj_1", "answer": "A"},
    {"question_id": "obj_2", "answer": "D"},
    {"question_id": "subj_1", "answer": "月光照在地上，洁白得像霜。"},
    {"question_id": "subj_2", "answer": "动作变化把望月转向思乡。"}
  ]
}
```

客观题由规则判定，主观题由本地 Qwen 按 rubric 评分。响应包含：

```text
objective_score / objective_total
subjective_score / subjective_total
earned_score / max_score / score
subjective_scores
weak_points
diagnosis
next_steps
```

答案和报告会写入运行数据库。

### `GET /api/learning/jobs/{job_id}/report`

返回已生成的学习报告。尚未提交答案时返回 `409`。

## 教师反馈

### `POST /api/learning/jobs/{job_id}/feedback`

仅 `teacher` 任务可用。

```json
{
  "target_module": "classroom_intro",
  "feedback": "压缩到三分钟，并加入月夜联想。"
}
```

可修订模块：

```text
classroom_intro
layered_explanations
guided_questions
teaching_goals
teaching_key_difficulties
classroom_activities
quiz
```

资源修订 Agent 只替换目标模块，并保存教师原文、旧值、Agent 输入证据和新值。

## 教师资源包

### `GET /api/learning/jobs/{job_id}/package.zip`

仅 `teacher` 任务可用。压缩包包含：

```text
教师资源包.md
resources.json
quiz.json
review_summary.json
生成图片
```

## 错误响应

| 状态码 | 含义 |
| --- | --- |
| `400` | 非法 SSE `Last-Event-ID` |
| `403` | 角色无权访问教师功能 |
| `404` | 任务或图片不存在 |
| `409` | 结果、测评或报告尚未就绪 |
| `422` | 请求校验、题号或目标模块不合法 |
| `500` | gpu 任务执行失败 |
| `501` | 当前服务实现不支持该能力 |

错误响应至少包含 `detail`：

```json
{
  "detail": "learning job not found"
}
```

## 兼容接口

`/api/jobs`、`/api/jobs/{job_id}`、`/api/jobs/{job_id}/result` 和 `/api/jobs/{job_id}/quiz` 为早期客户端保留。新客户端应使用 `/api/learning/jobs` 系列接口。

## OpenAPI

- Schema：`GET /openapi.json`
- Swagger UI：`GET /docs`

示例请求位于 [`../data/examples/`](../data/examples/)。
