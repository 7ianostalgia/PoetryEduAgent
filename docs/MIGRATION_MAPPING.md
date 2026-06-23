# 旧 SQLite 知识迁移

`scripts/migrate_database.py` 用于将旧诗词数据库中的知识资产迁移到 PoetryEduAgent 的 `data/poetry_edu.db`。迁移过程只读源库，并为每条数据保留可追溯来源。

## 使用方式

先执行检查：

```bash
python scripts/migrate_database.py \
  --source /path/to/legacy.db \
  --dry-run
```

确认报告后写入目标库：

```bash
python scripts/migrate_database.py \
  --source /path/to/legacy.db \
  --target data/poetry_edu.db
```

命令输出 JSON 格式迁移报告。

## 迁移前检查

迁移器会：

1. 以 SQLite `mode=ro` 打开源库；
2. 执行 `PRAGMA integrity_check`；
3. 计算源文件 SHA256；
4. 检查可识别的知识表和运行表；
5. 在写入前初始化目标 Schema。

完整性检查不为 `ok` 时，迁移立即终止。

## `poems` 映射

源字段：

```text
title
author
dynasty
content
tags
```

写入目标：

- 规范化诗词记录写入 `poems`；
- 原始行写入 `legacy_raw`；
- 标签同时进入 `poems.tags_json`；
- 存在标签内容时，可生成 `poem_knowledge` 的 `tags` 记录。

诗词合并优先依据规范化全文，其次依据规范化标题与作者。

## `classroom_poems` 映射

课堂诗词先关联或创建规范化 `poems` 记录，再把以下字段写入 `poem_knowledge`：

| 源字段 | 知识类型 |
| --- | --- |
| `excerpt` | `excerpt` |
| `vernacular` | `translation` |
| `theme` | `theme` |
| `imagery_json` | `imagery` |
| `classroom_explanation` | `classroom_explanation` |
| `realistic_prompt` | `realistic_prompt` |
| `ink_prompt` | `ink_prompt` |
| `tags` | `tags` |

`grade_band` 和 `source_note` 作为每条知识记录的元数据保留。

## 来源追溯

迁移记录使用以下来源键：

```text
source_db_hash
source_table
source_pk
```

这些字段同时存在于规范化知识和 `legacy_raw` 中，可从检索结果反查旧库原始行。

## 幂等性

`legacy_raw` 和 `poem_knowledge` 使用来源键唯一约束。对同一源文件重复执行迁移不会重复插入原始行或知识记录。

## 迁移报告

每次真实迁移会在 `migration_runs` 中保存：

- 源文件路径和 SHA256；
- SQLite 完整性结果；
- 开始与完成时间；
- 扫描、插入和更新数量；
- 检测到但未作为知识迁移的运行表；
- 完整 JSON 报告。

相关文档：[数据库设计](DATABASE_SCHEMA.md)
