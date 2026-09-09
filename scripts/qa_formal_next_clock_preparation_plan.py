"""建立下一個 Formal clock 的具體、唯讀 producer preparation plan。

所有日期、clock identity、候選 bundle、controlled target 與來源路徑都必須
由呼叫端明確提供。這個入口只讀檔案 metadata／hash 與明確日曆 bundle，不
抓行情、不建立 clock、不更新受控環境；即使依賴尚未齊全，也會保存帶有
精確 blocker 與 root 可審核命令的 create-only QA artifact。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_next_clock_preparation import (  # noqa: E402
    FORMAL_NEXT_CLOCK_PREPARATION_SCHEMA_VERSION,
    FormalNextClockPreparationError,
    build_formal_next_clock_preparation_plan,
    write_immutable_formal_next_clock_preparation_plan,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed", required=True)
    parser.add_argument("--activation-date", required=True)
    parser.add_argument("--planned-clock-id", required=True)
    parser.add_argument("--controlled-clock-root", type=Path, required=True)
    parser.add_argument("--clock-candidate-manifest", type=Path, required=True)
    parser.add_argument("--clock-planning-report", type=Path)
    parser.add_argument("--official-calendar-bundle", type=Path, required=True)
    parser.add_argument("--twse-calendar-cache", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--paper-snapshot-db", type=Path, required=True)
    parser.add_argument("--paper-fill-db", type=Path, required=True)
    parser.add_argument("--identity-manifest", type=Path, required=True)
    parser.add_argument("--prior-day-pit-operational", type=Path)
    parser.add_argument("--prior-day-pit-receipt", type=Path)
    parser.add_argument("--paper-schedule-source")
    parser.add_argument("--paper-schedule-time")
    parser.add_argument("--paper-schedule-timezone")
    parser.add_argument("--paper-schedule-taipei-equivalent")
    parser.add_argument("--owner-decision-id")
    parser.add_argument("--owner-decision-timestamp")
    parser.add_argument("--existing-calendar-capture-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed


def _parse_date(value: str, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    args = _parser().parse_args(argv)
    try:
        plan = build_formal_next_clock_preparation_plan(
            observed=_parse_datetime(args.observed, "--observed"),
            activation_date=_parse_date(args.activation_date, "--activation-date"),
            planned_clock_id=args.planned_clock_id,
            controlled_clock_root=args.controlled_clock_root,
            clock_candidate_manifest=args.clock_candidate_manifest,
            clock_planning_report=args.clock_planning_report,
            official_calendar_bundle=args.official_calendar_bundle,
            twse_calendar_cache=args.twse_calendar_cache,
            market_db=args.market_db,
            publication_root=args.publication_root,
            paper_snapshot_db=args.paper_snapshot_db,
            paper_fill_db=args.paper_fill_db,
            identity_manifest=args.identity_manifest,
            prior_day_pit_operational=args.prior_day_pit_operational,
            prior_day_pit_receipt=args.prior_day_pit_receipt,
            paper_schedule_evidence={
                "source": args.paper_schedule_source,
                "configured_time": args.paper_schedule_time,
                "configured_timezone": args.paper_schedule_timezone,
                "taipei_equivalent": args.paper_schedule_taipei_equivalent,
                "same_natural_day_retry": True,
            },
            owner_decision_id=args.owner_decision_id,
            owner_decision_timestamp=args.owner_decision_timestamp,
            existing_calendar_capture_root=args.existing_calendar_capture_root,
        )
        file_hash = write_immutable_formal_next_clock_preparation_plan(
            args.output,
            plan,
        )
    except (OSError, ValueError, FormalNextClockPreparationError) as error:
        print(
            json.dumps(
                {
                    "schema_version": FORMAL_NEXT_CLOCK_PREPARATION_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": f"{type(error).__name__}: {error}",
                    "read_only": True,
                    "formal_clock_created": False,
                    "formal_oos_allowed": False,
                    "writes_formal_controlled_paths": False,
                    "writes_market_database": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "schema_version": FORMAL_NEXT_CLOCK_PREPARATION_SCHEMA_VERSION,
                "status": plan["status"],
                "activation_trading_day": plan["activation_trading_day"],
                "blockers": plan["blockers"],
                "plan_hash": plan["plan_hash"],
                "file_hash": file_hash,
                "read_only": True,
                "formal_clock_created": False,
                "formal_oos_allowed": False,
                "writes_formal_controlled_paths": False,
                "writes_market_database": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
