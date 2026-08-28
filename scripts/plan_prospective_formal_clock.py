"""唯讀選出下一個 prospective formal clock 候選日。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_clock_planner import (  # noqa: E402
    ProspectiveClockPlanningError,
    plan_next_prospective_clock,
)


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed


def _read_object(path: Path) -> dict[str, object]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("calendar evidence JSON is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("calendar evidence JSON root must be an object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", required=True)
    parser.add_argument("--owner-decision-timestamp", required=True)
    parser.add_argument("--calendar-evidence", type=Path, required=True)
    parser.add_argument("--minimum-preparation-days", type=int, default=1)
    parser.add_argument("--lookahead-days", type=int, default=31)
    parser.add_argument("--existing-clock-id", action="append", default=[])
    parser.add_argument("--clock-id-prefix", default="clock:prospective:")
    parser.add_argument("--output", type=Path)
    return parser


def _write_create_only(path: Path, payload: dict[str, object]) -> None:
    output = path.expanduser().resolve()
    if not output.parent.is_dir():
        raise ValueError("--output parent directory must already exist")
    try:
        with output.open("xb") as stream:
            stream.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                .encode("utf-8")
                + b"\n"
            )
    except FileExistsError as error:
        raise ValueError("--output already exists; planner is create-only") from error


def main(argv: Sequence[str] | None = None) -> int:
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    args = _parser().parse_args(argv)
    try:
        report = plan_next_prospective_clock(
            now=_parse_datetime(args.now, "--now"),
            owner_decision_timestamp=_parse_datetime(
                args.owner_decision_timestamp,
                "--owner-decision-timestamp",
            ),
            calendar_evidence=_read_object(args.calendar_evidence),
            minimum_preparation_days=args.minimum_preparation_days,
            lookahead_days=args.lookahead_days,
            existing_clock_ids=tuple(args.existing_clock_id),
            clock_id_prefix=args.clock_id_prefix,
        )
        if args.output is not None:
            _write_create_only(args.output, report)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ProspectiveClockPlanningError,
    ) as error:
        report = {
            "schema_version": "prospective-formal-clock-planning.v1",
            "status": "blocked",
            "read_only": True,
            "formal_clock_created": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "secret_values_emitted": False,
            "blockers": [f"{type(error).__name__}: {error}"],
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "candidate_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
