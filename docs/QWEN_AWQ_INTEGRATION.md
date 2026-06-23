# Qwen2.5-14B-Instruct-AWQ 文本模型

Qwen2.5-14B-Instruct-AWQ 是 PoetryEduAgent 的本地文本主模型，承担结构化文本生成、资源修正、主观题评分和 DeepSeek-V4-Flash fallback 审核。

## 运行配置

```bash
LOCAL_LLM_MODEL=/absolute/path/to/Qwen2.5-14B-Instruct-AWQ
QWEN_CONDA_ENV=poetryedu-qwen14b-awq
```

默认客户端通过以下子进程启动 worker：

```text
conda run --no-capture-output
  -n poetryedu-qwen14b-awq
  python -m backend.model_clients.qwen_awq_worker
```

请求通过 stdin 传入 JSON，worker 将最后一行 stdout 作为结构化结果返回。

## 主要任务

| `task_name` | 用途 |
| --- | --- |
| `complete_text_stage` | 学情诊断、诗句解析、角色化资源、四题测评和画面 JSON |
| `local_text_review` | DeepSeek-V4-Flash 不可用时执行文字审核 |
| `rewrite_text_resources_from_deepseek_feedback` | 根据审核意见修订文字资源 |
| `rewrite_image_prompt_from_vision_feedback` | 根据实际视觉问题修订画面 JSON |
| `quiz_feedback` | 按 rubric 评分主观题并生成学习建议 |

## 请求约束

`QwenTextRequest` 包含：

```text
task_name
system_prompt
user_prompt
output_schema
max_input_tokens
max_new_tokens
temperature
top_p
seed
```

保护范围：

- `max_input_tokens`：256 至 8192；
- `max_new_tokens`：64 至 2048；
- `temperature`：0 至 1；
- `top_p`：大于 0 且不超过 1；
- 每个任务必须提供非空 JSON Schema。

## 结构化输出

模型只允许返回 JSON 对象。worker 会：

1. 加载 AWQ 权重；
2. 检查模型配置与请求；
3. 执行推理；
4. 提取 JSON；
5. 根据请求 Schema 校验字段、类型和枚举；
6. 返回输出与推理指标。

解析失败或 Schema 不通过会明确报错，不会用缺省字段伪造成功结果。

## 批量接口

`run_batch()` 可以在一次 worker 生命周期中顺序执行多个文本请求，减少重复加载成本。当前完整文本阶段主要使用一次大 Schema 输出多个逻辑 Agent 结果。

## 资源释放

Qwen worker 在独立 Conda 子进程中运行。任务结束后进程退出，由操作系统释放 CUDA context；API 进程不长期持有模型。

相关文档：[文本阶段](TEXT_STAGE.md) · [模型调度](MODEL_MANAGER.md)
