#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.storage.db import migrate_legacy_database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy poem knowledge into data/poetry_edu.db."
    )
    parser.add_argument("--source", required=True, help="Legacy SQLite database path.")
    parser.add_argument(
        "--target",
        default="data/poetry_edu.db",
        help="Target SQLite database path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing the target database.",
    )
    args = parser.parse_args()

    report = migrate_legacy_database(
        Path(args.source),
        Path(args.target),
        dry_run=args.dry_run,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
