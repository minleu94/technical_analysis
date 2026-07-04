from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.corporate_action_policy import inspect_corporate_action_policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect V1.5 corporate action price policy.")
    parser.add_argument("--json-output", action="store_true", help="Emit JSON output. JSON is the default.")
    parser.add_argument("--markdown", action="store_true", help="Emit Markdown summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    inspection = inspect_corporate_action_policy()
    if args.markdown:
        print(inspection.to_markdown())
        return 0
    print(json.dumps(inspection.to_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
