"""從 V2.4 paper artifact 建立 V2.5 fail-closed health baseline。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.position_health_baseline_service import PositionHealthBaselineService


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a research-only position health baseline.")
    parser.add_argument("--paper-baseline", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    payload = PositionHealthBaselineService().build(args.paper_baseline)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output_path": str(output), "positions": len(payload["positions"]), "auto_action_allowed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
