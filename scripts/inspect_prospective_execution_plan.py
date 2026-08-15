"""唯讀輸出 prospective formal simulation 的單一執行計畫。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Mapping, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_execution_plan import (  # noqa: E402
    ProspectiveExecutionPlanError,
    build_prospective_execution_plan,
    write_immutable_execution_plan,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", required=True, help="owner-supplied ISO timestamp with timezone")
    parser.add_argument("--output", type=Path, help="optional create-only JSON report path")
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        plan = build_prospective_execution_plan(now=now)
        file_hash = write_immutable_execution_plan(args.output, plan) if args.output else None
    except (ValueError, OSError, ProspectiveExecutionPlanError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "prospective-formal-execution-plan.v1",
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "read_only": True,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    safety = cast(Mapping[str, object], plan["safety"])
    stages = cast(list[object], plan["stages"])
    print(
        json.dumps(
            {
                "schema_version": plan["schema_version"],
                "status": plan["status"],
                "current_blockers": plan["current_blockers"],
                "stage_count": len(stages),
                "read_only": safety["read_only"],
                "formal_oos_allowed": safety["formal_oos_allowed"],
                "heavy_rebuild_launch_allowed": safety["heavy_rebuild_launch_allowed"],
                "promotion_eligible": safety["promotion_eligible"],
                "plan_hash": plan["plan_hash"],
                "plan_file_hash": file_hash,
                "secret_values_emitted": safety["secret_values_emitted"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
