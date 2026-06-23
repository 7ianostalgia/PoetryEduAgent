# 模型运行与单 GPU 调度

PoetryEduAgent 将 API 服务与模型推理解耦。Qwen、Kolors 和 Qwen-VL 在独立 Conda 环境与子进程中运行，避免依赖冲突，并通过工作流互斥保证单张 GPU 不被多个阶段同时占用。

## 模型与环境

| 模型键 | Conda 环境 | 路径变量 | 用途 |
| --- | --- | --- | --- |
| `qwen14b_awq` | `poetryedu-qwen14b-awq` | `LOCAL_LLM_MODEL` | 文本阶段、资源修正、主观题评分、本地审核 |
| `kolors` | `poetryedu-kolors` | `KOLORS_MODEL` | 古诗意境图生成 |
| `qwen_vl` | `poetryedu-qwen-vl` | `VISION_MODEL` | 实际图片观察与视觉审核 |

DeepSeek-V4-Flash 通过 HTTP API 调用，不占用本地 GPU。

## 两层运行机制

仓库中存在两个互补层次：

1. **gpu 业务客户端**：`QwenAwqClient`、`KolorsClient` 和 `QwenVisionClient` 负责启动对应 worker，并解析模型结果。

2. **`ModelManager` 调度抽象**：负责模型键、命令计划、请求限制、GPU lease、超时、取消和可观测快照。其 `DevRunner` 用于在 dev 测试中验证调度语义。

gpu 工作流还在 `GpuLearningWorkflow` 外层使用进程级互斥锁，确保整条任务按单卡能力顺序执行。

## 子进程模型

典型调用形式：

```text
API 进程
  └─ conda run -n <model-env> python -m <worker>
       ├─ 从 stdin 读取 JSON 请求
       ├─ 加载模型并执行推理
       ├─ 向 stdout 返回结构化结果
       └─ 进程退出并释放 CUDA context
```

这种方式牺牲了一部分模型重复加载时间，换取更清晰的依赖隔离和显存回收行为。

## 请求保护

`ModelRequest` 的调度保护包括：

- 文本输入不超过 8192 tokens；
- 单次输出不超过 2048 tokens；
- 输入与输出预算合计不超过 10000 tokens；
- 视觉像素不超过 1,572,864；
- Kolors 固定 `batch_size=1`；
- 每个阶段必须提供正数超时时间。

具体模型客户端还会执行自己的安全校验，例如 Qwen-VL 只能读取 `OUTPUT_DIR` 下的图片。

## GPU lease

`ModelManager.run()` 在调用 runner 前获取全局 GPU lease：

- 同一时刻仅有一个本地模型阶段处于 active 状态；
- 并发请求等待当前阶段结束；
- 等待超时抛出 `TimeoutError`；
- `snapshot()` 返回当前 lease、模型配置和历史事件；
- `cancel(request_id)` 向 runner 发送取消信号。

## 失败与 fallback

- worker 非零退出、输出为空或结果解析失败会明确抛错；
- Qwen 与 Qwen-VL 结果必须满足相应结构约束；
- DeepSeek-V4-Flash 审核失败不占用 GPU，随后由本地 Qwen 执行审核；
- Qwen-VL 字段缺失或判断值模糊时采用失败关闭，不猜测为通过；
- 图片纠偏最多执行一次，避免无限循环。

## 测试

```bash
pytest tests/test_model_manager.py -q
```

该测试验证命令规划、固定环境映射、单 GPU 互斥、请求限制、超时、取消接口和 DeepSeek-V4-Flash 失败后的本地 Qwen 路由。
