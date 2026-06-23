# PoetryEduAgent 文档

本目录面向使用者、开发者和项目评审，说明 PoetryEduAgent 的公开接口、系统架构、数据设计、模型接入方式与开发约定。

## 快速导航

| 文档 | 内容 |
| --- | --- |
| [API 接口](API.md) | 任务创建、事件流、结果查询、教师反馈、测评与错误响应 |
| [gpu 工作流](GPU_WORKFLOW.md) | 多 Agent 双分支流程、审查纠偏与双门禁 |
| [Agent 与任务状态](AGENT_STATE.md) | 逻辑 Agent、任务阶段、事件状态和数据边界 |
| [文本阶段](TEXT_STAGE.md) | Qwen 文本协调器的输入、结构化输出与语义护栏 |
| [数据库设计](DATABASE_SCHEMA.md) | 知识库、运行库、表结构与持久化关系 |
| [历史数据迁移](MIGRATION_MAPPING.md) | 旧 SQLite 资产的只读、可追溯迁移规则 |
| [模型调度](MODEL_MANAGER.md) | 单 GPU 调度、独立子进程、资源限制与失败处理 |
| [Qwen AWQ](QWEN_AWQ_INTEGRATION.md) | 文本模型请求、Schema 校验与本地审核 |
| [Kolors](KOLORS_INTEGRATION.md) | Prompt 编译、生图参数、输出与运行约束 |
| [Qwen-VL](QWEN_VL_INTEGRATION.md) | 图片观察、确定性门禁和纠偏输入 |
| [DeepSeek-V4-Flash](DEEPSEEK_REVIEW.md) | 独立文字审核、重试与本地 fallback |
| [开发指南](DEVELOPMENT.md) | 本地环境、测试、代码边界与提交检查 |

## 文档约定

- 中文是默认文档语言，模型名、API 字段和代码标识保留英文。
- 文档描述以当前 `main` 分支实现为准。
- “Agent”表示具有独立职责、输入和输出边界的业务节点，不必然对应独立模型进程。
- 服务器地址、密钥、运行日志和临时部署命令不属于公开架构文档。
- 具体请求与响应结构以 FastAPI 生成的 `/docs` 和 `/openapi.json` 为最终机器可读契约。
