# 开发指南

本文面向需要修改 PoetryEduAgent 代码、数据结构或工作流的开发者。安装和启动方式见项目根目录 [README](../README.md)，模型环境见 [`environments/README.md`](../environments/README.md)。

## 代码边界

```text
backend/
├── agents/          结构化文本、语义护栏与 Prompt 编译
├── api/             HTTP 协议、状态码、SSE 与文件响应
├── generation/      Kolors 客户端与 worker
├── model_clients/   Qwen、DeepSeek-V4-Flash、Qwen-VL 客户端
├── model_runtime/   模型计划、GPU lease 与运行抽象
├── orchestration/   任务服务、Agent 顺序、纠偏与双门禁
├── rag/             SQLite 检索
├── storage/         Schema、迁移与持久化仓库
└── utils/           通用校验
```

### API 层

- 只负责请求校验、权限、状态码和响应结构；
- 模型调用与工作流判断不得写进路由；
- 新接口使用 `/api/learning/jobs` 命名空间；
- 兼容接口只做协议转换，不承载新功能。

### 工作流层

- Agent 顺序、重试、纠偏次数和 fallback 由工作流统一管理；
- 每个可观察阶段通过 `WorkflowEvent` 产生持久化事件；
- `completed` 表示任务结束，不能替代双门禁 `pass`；
- 文字修正不得修改图像支路，Prompt 修正不得修改教学资源。

### 模型客户端

- 请求必须具备 JSON Schema 或固定输出协议；
- worker 非零退出、空输出和解析失败必须显式报错；
- Qwen、Kolors 和 Qwen-VL 使用独立子进程；
- 图片输入与生成输出必须限制在配置目录；
- API 进程不长期持有 GPU 模型。

### 数据层

- 业务代码通过仓库接口读写运行记录；
- Schema 初始化和升级必须幂等；
- JSON 字段统一以 UTF-8 文本保存；
- 旧库迁移只读源文件，并保留来源哈希、表名和主键；
- 新增持久化字段时，同步更新 Schema、仓库实现和测试。

## 配置边界

配置由 `backend/config.py` 和模型客户端从环境变量读取：

| 类别 | 变量 |
| --- | --- |
| 数据 | `POETRY_DB_PATH`、`POETRY_RUNTIME_DB_PATH`、`OUTPUT_DIR` |
| 本地模型 | `LOCAL_LLM_MODEL`、`KOLORS_MODEL`、`VISION_MODEL` |
| 文字审核 | `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` |
| 前端 | `FRONTEND_STATIC_DIR` |

代码不得依赖某台服务器的固定 IP、端口或临时目录。

## 测试策略

```bash
.venv/bin/pytest
```

自动化测试使用确定性替身验证控制流，不加载 GPU 模型或外部 API。覆盖范围包括：

- API 与 OpenAPI 契约；
- 状态机、SSE 和错误语义；
- SQLite Schema、迁移、检索和持久化；
- Prompt 编译与结构化输出校验；
- 模型客户端命令、超时和错误处理；
- 图像与文字纠偏；
- 教师反馈和学生答题评估；
- 前端关键结构。

gpu 模式验证与自动化测试分开执行：

```bash
python scripts/smoke_text_stage.py
```

```bash
python scripts/smoke_kolors.py --size 768 --steps 20
```

```bash
python scripts/smoke_qwen_vl.py --image /path/to/image.png
```

## 数据库变更

初始化或升级 Schema：

```bash
python scripts/initialize_database.py data/poetry_edu.db
```

迁移旧知识资产：

```bash
python scripts/migrate_database.py --source /path/to/legacy.db --dry-run
```

```bash
python scripts/migrate_database.py --source /path/to/legacy.db
```

数据库变更需要验证：

1. `PRAGMA integrity_check`；
2. 现有数据升级路径；
3. 来源追溯字段；
4. 重复执行的幂等性；
5. API 重启后的历史任务恢复。

## 提交要求

```bash
.venv/bin/pytest
```

```bash
git diff --check
```

```bash
git status --short
```

公开接口、Schema 或工作流语义变化时，需要同时更新：

- 对应测试；
- [`API.md`](API.md)；
- 相关架构文档；
- [`CHANGELOG.md`](../CHANGELOG.md)。

Markdown 文档中的链接必须使用仓库相对路径。

## 安全要求

- 日志不记录 API Key、完整环境变量或模型私密输入；
- `/api/image` 不能读取 `OUTPUT_DIR` 之外的文件；
- 教师包不得包含系统提示词、原始技术 Prompt 或服务器日志；
- 模型输出未经结构校验不得进入下一阶段；
- 前端不得将失败任务或 dev 结果伪装成 gpu 成功结果。
