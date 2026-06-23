#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.storage.db import connect_target, initialize_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化或升级 PoetryEdu SQLite 表结构")
    parser.add_argument("path", nargs="?", default="data/poetry_edu.db")
    args = parser.parse_args()
    path = Path(args.path)
    with connect_target(path) as conn:
        initialize_schema(conn)
        conn.commit()
    print(f"数据库表结构已就绪：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
