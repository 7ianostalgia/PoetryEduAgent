# PoetryEduAgent 后端

后端基于 FastAPI，负责学习任务 API、多 Agent 工作流、模型子进程调用、SQLite/RAG、事件流和结果持久化。

## 架构

```text
API 请求
  ↓
GpuLearningService
  ↓
GpuLearningWorkflow
  ├─ SQLite / RAG
  ├─ Qwen2.5-14B-Instruct-AWQ
  ├─ Kolors
  ├─ Qwen2.5-VL
  ├─ DeepSeek-V4-Flash / Qwen fallback
  └─ 双门禁与纠偏
  ↓
SqliteLearningRepository
```

## 主要模块

| 目录 | 职责 |
| --- | --- |
| `agents/` | 文本阶段 Schema、语义护栏和 Kolors Prompt 编译 |
| `api/` | FastAPI 路由、SSE、图片与资源包响应 |
| `generation/` | Kolors 客户端和 worker |
| `model_clients/` | Qwen、DeepSeek-V4-Flash 和 Qwen-VL 接口 |
| `model_runtime/` | 模型命令计划、GPU lease 和运行抽象 |
| `orchestration/` | dev/gpu 异步任务服务与 gpu 工作流 |
| `rag/` | SQLite 诗词检索 |
| `storage/` | 数据库 Schema、迁移和仓库实现 |

## 启动

所有命令均从项目根目录执行。dev 模式：

```bash
bash scripts/setup_dev.sh
```

```bash
cp .env.example .env
```

```bash
bash scripts/start_dev.sh
```

gpu 模式：

```bash
bash scripts/setup_gpu.sh
```

```bash
bash scripts/start_gpu.sh
```

gpu 模式要求模型、数据库、输出路径与 DeepSeek-V4-Flash 配置通过启动前检查。配置项与手动安装方式见项目根目录 [README](../README.md)。

## 测试

```bash
.venv/bin/pytest
```

技术文档入口见 [`docs/README.md`](../docs/README.md)。
