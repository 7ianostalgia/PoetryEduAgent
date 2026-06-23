# gpu 模型环境

gpu 模式使用主服务 `.venv` 和三个独立 Conda 模型环境。不要把三个模型的依赖安装进同一个 Python 环境。

## 依赖文件

| 环境 | 依赖文件 |
| --- | --- |
| 主服务与 dev 模式 | `requirements-dev.txt` |
| gpu 结构说明 | `requirements-gpu.txt`，不直接安装 |
| Qwen | `environments/qwen14b-awq.txt` |
| Kolors | `environments/kolors.txt` |
| Qwen-VL | `environments/qwen-vl.txt` |

推荐使用：

```bash
bash scripts/setup_gpu.sh
```

该脚本会创建或复用 `.venv` 和三个 Conda 环境，并将每份依赖安装到正确环境。

## 手动安装

### 主服务

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```

### Qwen2.5-14B-Instruct-AWQ

```bash
conda create -n poetryedu-qwen14b-awq python=3.10 -y
```

```bash
conda run -n poetryedu-qwen14b-awq python -m pip install -r environments/qwen14b-awq.txt
```

### Kolors

```bash
conda create -n poetryedu-kolors python=3.10 -y
```

```bash
conda run -n poetryedu-kolors python -m pip install -r environments/kolors.txt
```

### Qwen2.5-VL

```bash
conda create -n poetryedu-qwen-vl python=3.10 -y
```

```bash
conda run -n poetryedu-qwen-vl python -m pip install -r environments/qwen-vl.txt
```

## 已验证依赖组合

| 环境 | 关键版本 |
| --- | --- |
| 主服务 `.venv` | Python 3.10、FastAPI 0.138、Uvicorn 0.49、Pydantic 2.13、HTTPX 0.28、Pytest 8.4 |
| `poetryedu-qwen14b-awq` | PyTorch 2.3.1+cu121、Transformers 4.45.2、Accelerate 0.34.2、AutoAWQ 0.2.6 |
| `poetryedu-kolors` | PyTorch 2.1.0+cu121、Diffusers 0.30.3、Transformers 4.37.2、Accelerate 0.34.2 |
| `poetryedu-qwen-vl` | PyTorch 2.1.0+cu121、Transformers 4.49.0、Accelerate 0.34.2、qwen-vl-utils |

GPU 驱动和 CUDA 环境不同可能需要调整 PyTorch 安装来源，但三个模型环境必须继续隔离。

## 验证

```bash
.venv/bin/pytest
```

```bash
python scripts/smoke_text_stage.py
```

```bash
python scripts/smoke_kolors.py --size 768 --steps 20
```

```bash
python scripts/smoke_qwen_vl.py --image /absolute/path/to/image.png
```

相关文档：[模型调度](../docs/MODEL_MANAGER.md)
