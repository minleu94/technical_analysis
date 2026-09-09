"""Capture and normalize a bounded official TWSE/TPEX calendar candidate.

The command accepts manually downloaded official JSON fixtures and can fill
missing annual/monthly responses only after ``--confirm-network``.  It writes
one create-only candidate artifact under the operating-system TEMP directory.
The artifact is suitable for ``plan_prospective_formal_clock.py`` but is never
a formal clock input by itself.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.official_calendar_bundle import (  # noqa: E402
    CapturedCalendarResponse,
    OfficialCalendarBundleError,
    build_official_calendar_bundle,
    fetch_network_responses,
    load_fixture_response,
    write_candidate_bundle,
    write_raw_response_evidence,
)
from data_module.prospective_formal_clock import payload_hash  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--twse-fixture",
        type=Path,
        action="append",
        default=[],
        help="已從官方 TWSE endpoint 保存的年度 JSON；可重複指定。",
    )
    parser.add_argument(
        "--tpex-fixture",
        type=Path,
        action="append",
        default=[],
        help="已從官方 TPEX mktCalendar 保存的月度 JSON；可重複指定。",
    )
    parser.add_argument(
        "--confirm-network",
        action="store_true",
        help="明確允許對缺少的官方年度／月份各發出一次 bounded GET。",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--raw-output-dir",
        type=Path,
        help="保存當次 exact HTTP bytes/metadata 的 TEMP 目錄；省略時使用 <output stem>_raw。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        start_date = _parse_date(args.start_date, "--start-date")
        end_date = _parse_date(args.end_date, "--end-date")
        required_years = set(range(start_date.year, end_date.year + 1))
        required_months = _months_in_range(start_date, end_date)

        twse_fixture_map = _load_fixtures(args.twse_fixture, kind="twse")
        tpex_fixture_map = _load_fixtures(args.tpex_fixture, kind="tpex")
        twse: dict[int, CapturedCalendarResponse] = {
            int(key): value for key, value in twse_fixture_map.items()
        }
        tpex: dict[str, CapturedCalendarResponse] = {
            str(key): value for key, value in tpex_fixture_map.items()
        }
        missing_years = required_years - set(twse)
        missing_months = required_months - set(tpex)

        fetched = False
        if missing_years or missing_months:
            if not args.confirm_network:
                _print_blocked(
                    "缺少官方日曆回應；未帶 --confirm-network，因此不發網路請求。",
                    missing_years=sorted(missing_years),
                    missing_months=sorted(missing_months),
                )
                return 1
            fetched_twse, fetched_tpex = fetch_network_responses(
                years=missing_years,
                months=missing_months,
            )
            twse.update(fetched_twse)
            tpex.update(fetched_tpex)
            fetched = bool(fetched_twse or fetched_tpex)

        if not twse or not tpex:
            raise OfficialCalendarBundleError(
                "at least one TWSE fixture/response and one TPEX fixture/response are required"
            )
        fixture_used = bool(args.twse_fixture or args.tpex_fixture)
        capture_mode = (
            "mixed" if fetched and fixture_used else "bounded_network" if fetched else "fixture_only"
        )
        bundle = build_official_calendar_bundle(
            start_date=start_date,
            end_date=end_date,
            twse_responses={
                year: twse[year] for year in sorted(required_years)
            },
            tpex_responses={
                month: tpex[month] for month in sorted(required_months)
            },
            capture_mode=capture_mode,
            network_enabled=fetched,
            captured_at=datetime.now(timezone.utc),
        )
        output_path = args.output.expanduser().resolve()
        if output_path.exists():
            raise OfficialCalendarBundleError(
                "candidate bundle output already exists; choose a new path"
            )
        raw_output_dir = (
            args.raw_output_dir
            if args.raw_output_dir is not None
            else output_path.with_name(f"{output_path.stem}_raw")
        )
        raw_evidence = write_raw_response_evidence(
            raw_output_dir,
            {
                **{f"twse:{year}": response for year, response in twse.items()},
                **{f"tpex:{month}": response for month, response in tpex.items()},
            },
        )
        raw_manifest_path = Path(str(raw_evidence["manifest_path"])).resolve()
        bundle["raw_evidence"] = {
            "schema_version": raw_evidence["schema_version"],
            "manifest_path": os.path.relpath(
                raw_manifest_path,
                start=output_path.parent,
            ).replace("\\", "/"),
            "manifest_file_hash": raw_evidence["manifest_file_hash"],
            "manifest_hash": raw_evidence["manifest_hash"],
            "entry_count": raw_evidence["entry_count"],
        }
        bundle_body = dict(bundle)
        bundle_body.pop("bundle_hash", None)
        bundle["bundle_hash"] = payload_hash(bundle_body)
        file_hash = write_candidate_bundle(args.output, bundle)
    except (OSError, ValueError, OfficialCalendarBundleError) as error:
        _print_blocked(f"{type(error).__name__}: {error}")
        return 2

    print(
        json.dumps(
            {
                "status": "candidate_captured",
                "schema_version": bundle["schema_version"],
                "range": bundle["range"],
                "capture_mode": bundle["capture_mode"],
                "network_enabled": bundle["network_enabled"],
                "bundle_hash": bundle["bundle_hash"],
                "file_hash": file_hash,
                "raw_evidence": bundle["raw_evidence"],
                "candidate_only": True,
                "formal_clock_created": False,
                "formal_oos_allowed": False,
                "production_scheduler_allowed": False,
                "broker_order_allowed": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _load_fixtures(
    paths: Sequence[Path],
    *,
    kind: str,
) -> dict[str | int, CapturedCalendarResponse]:
    result: dict[str | int, CapturedCalendarResponse] = {}
    for path in paths:
        response = load_fixture_response(path, kind=kind)
        key: str | int = int(response.key) if kind == "twse" else response.key
        if key in result:
            raise OfficialCalendarBundleError(
                f"duplicate {kind} fixture identity: {response.key}"
            )
        result[key] = response
    return result


def _parse_date(value: str, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise OfficialCalendarBundleError(
            f"{field_name} must be YYYY-MM-DD"
        ) from error
    if parsed.isoformat() != value:
        raise OfficialCalendarBundleError(f"{field_name} must be YYYY-MM-DD")
    return parsed


def _months_in_range(start_date: date, end_date: date) -> set[str]:
    result: set[str] = set()
    current = date(start_date.year, start_date.month, 1)
    last = date(end_date.year, end_date.month, 1)
    while current <= last:
        result.add(current.strftime("%Y%m"))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return result


def _print_blocked(
    message: str,
    *,
    missing_years: Sequence[int] = (),
    missing_months: Sequence[str] = (),
) -> None:
    print(
        json.dumps(
            {
                "status": "blocked",
                "reason": message,
                "missing_twse_years": list(missing_years),
                "missing_tpex_months": list(missing_months),
                "candidate_only": True,
                "formal_clock_created": False,
                "formal_oos_allowed": False,
                "production_scheduler_allowed": False,
                "broker_order_allowed": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
