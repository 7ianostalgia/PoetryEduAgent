# Kolors 图像生成

Kolors 负责将古诗意象的结构化画面描述转换为单张教学意境图。图像生成前先经过确定性 Prompt 编译，生成后再由 Qwen-VL 独立审核。

## 运行配置

```bash
KOLORS_MODEL=/absolute/path/to/Kolors-diffusers
KOLORS_CONDA_ENV=poetryedu-kolors
OUTPUT_DIR=/absolute/path/to/poetry_edu_outputs
```

客户端通过独立子进程运行：

```text
conda run --no-capture-output
  -n poetryedu-kolors
  python -m backend.generation.kolors_worker
```

## Prompt 编译

意象提取 Agent 先输出 `standard_prompt_json`：

```json
{
  "poem": "床前明月光，疑是地上霜。举头望明月，低头思故乡。",
  "explanation": "诗人在月夜由眼前月光联想到故乡。",
  "scene": "古代中国室内夜晚",
  "subject": "一名独处的唐代诗人",
  "action": "坐在古代木质床榻旁低头沉思",
  "composition": "中景单人构图",
  "visual_focus": ["诗人", "床榻", "明月", "床前月光"],
  "light": "冷白月光从窗外照入",
  "emotion": "安静、孤独、思乡",
  "style": "水墨写意",
  "avoid": ["现代家具", "真实冰霜"],
  "composition_constraints": ["画面中只出现一名人物"]
}
```

`KolorsPromptCompiler` 将其转换为：

- `zh_prompt`：120 至 220 字的连续中文画面指令；
- `negative_prompt`：去重后的禁止元素列表。

编译器会补充通用质量约束，并拒绝 JSON 字符串、字段标签或不安全长度直接进入生图 worker。

## 生成请求

`KolorsRequest` 支持：

```text
prompt
negative_prompt
output_dir
seed
width / height
steps
guidance_scale
batch_size
```

当前 gpu 工作流使用：

```text
seed=20260620
width=768
height=768
steps=20
guidance_scale=6.0
batch_size=1
```

请求保护：

- 宽高仅允许 512、768 或 1024；
- `steps` 为 1 至 50；
- `guidance_scale` 为 0 至 12；
- 单 GPU 环境固定 `batch_size=1`；
- 输出目录必须位于 `OUTPUT_DIR`。

## 输出

worker 返回：

```text
image_path
metadata_path
seed
metrics
```

图片记录会与 Prompt、负面 Prompt、随机种子和视觉审核结果一起写入 SQLite。

## 图片纠偏

若 Qwen-VL 判断图片缺少关键元素或出现错误元素：

1. Prompt 修正 Agent 读取原始画面 JSON 和视觉问题；
2. 生成新的 `standard_prompt_json`；
3. Prompt 编译器重新编译；
4. Kolors 最多重绘一次；
5. Qwen-VL 再次审核最终图片。

该限制用于避免无限生成循环。

## 冒烟验证

```bash
OUTPUT_DIR=/absolute/path/to/poetry_edu_outputs \
KOLORS_MODEL=/absolute/path/to/Kolors-diffusers \
python scripts/smoke_kolors.py --size 768 --steps 20
```

相关文档：[gpu 工作流](GPU_WORKFLOW.md) · [Qwen-VL](QWEN_VL_INTEGRATION.md)
