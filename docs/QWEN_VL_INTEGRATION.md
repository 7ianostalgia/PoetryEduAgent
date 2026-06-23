# Qwen2.5-VL 图片审核

Qwen2.5-VL-7B-Instruct 负责观察 Kolors 实际生成的图片。它只报告看见的内容，不根据 Prompt 推断图片“应该”包含什么。

## 运行配置

```bash
VISION_MODEL=/absolute/path/to/Qwen2.5-VL-7B-Instruct
VISION_CONDA_ENV=poetryedu-qwen-vl
OUTPUT_DIR=/absolute/path/to/poetry_edu_outputs
```

客户端通过独立子进程运行：

```text
conda run --no-capture-output
  -n poetryedu-qwen-vl
  python -m backend.model_clients.qwen_vl_worker
```

## 输入保护

- 图片路径必须位于 `OUTPUT_DIR`；
- 文件必须真实存在；
- 每次只审核一张图片；
- `max_pixels` 不超过 `1280 × 28 × 28`；
- 输出 token 上限为 1024，gpu 工作流使用更短的观察报告。

## 固定观察字段

gpu 工作流要求简短中文文本：

```text
人物数量=1；
单一古代诗人=是；
明月=有；
床前地面月光=有；
古代床榻=无；
现代物品=无；
真实冰霜或雪=无；
人工照明=无；
画面概述=夜深人静，一人临窗；
问题=缺少古代床榻；
修改建议=加入结构清晰的木质床榻
```

选择短文本而不是让视觉模型直接拼装复杂 JSON，可以降低转义和截断风险。

## 确定性解析

后端将固定字段转换为结构化审核：

```text
person_count
key_elements_detected
missing_elements
possible_errors
pass
revision_advice
```

关键判断值只接受：

- `是` / `否`；
- `有` / `无`。

字段缺失、人物数量无法解析或出现模糊值时，审核采用失败关闭：

```text
vision_pass = false
```

系统不会因为图片生成成功就默认视觉审核通过。

## 当前硬约束

示范诗词的图片门禁检查：

- 只出现一名古代诗人；
- 窗外有明月；
- 床前地面有明确月光；
- 画面存在古代木质床榻；
- 不出现现代物品；
- 不出现真实冰霜或雪；
- 不出现灯笼、油灯、蜡烛等人工照明。

## 纠偏关系

视觉审核失败后，原始观察文本和结构化问题交给 Prompt 修正 Agent。修正 Agent 不修改课堂资源，只重写图像支路的 `standard_prompt_json`。

重绘后再次执行 Qwen-VL 审核，并以最终图片结果参与双门禁。

## 冒烟验证

```bash
OUTPUT_DIR=/absolute/path/to/poetry_edu_outputs \
VISION_MODEL=/absolute/path/to/Qwen2.5-VL-7B-Instruct \
python scripts/smoke_qwen_vl.py --image /absolute/path/to/image.png
```

相关文档：[Kolors](KOLORS_INTEGRATION.md) · [gpu 工作流](GPU_WORKFLOW.md)
