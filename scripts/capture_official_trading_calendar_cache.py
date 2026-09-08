"""Capture one bounded TWSE annual calendar response into repo output.

The command is an explicit source-maintenance operation.  It performs one
official GET only after ``--confirm-network``, records the response bytes and
headers, and creates an immutable cache file under the repository ``output``
tree.  It never writes the market database, a formal clock, or a Paper ledger.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.official_phase3c_fetcher import safe_request  # noqa: E402
from data_module.official_trading_calendar_cache import (  # noqa: E402
    OfficialCalendarCacheError,
    TWSE_HOLIDAY_SCHEDULE_URL,
    build_twse_calendar_cache,
    write_twse_calendar_cache,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="新的 immutable cache 檔案，必須位於 repository output 下。",
    )
    parser.add_argument(
        "--confirm-network",
        action="store_true",
        help="明確允許對 TWSE 官方 annual holidaySchedule 發出一次 bounded GET。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_network:
        _print_blocked(
            "未帶 --confirm-network；不發官方請求，也不建立 cache。"
        )
        return 1

    output = args.output.expanduser().resolve()
    allowed_root = (ROOT / "output").resolve()
    try:
        output.relative_to(allowed_root)
    except ValueError:
        _print_blocked("cache output 必須位於 repository output 下。")
        return 2

    requested_at = datetime.now(timezone.utc)
    try:
        response = safe_request(
            TWSE_HOLIDAY_SCHEDULE_URL,
            params={"queryYear": str(args.year - 1911)},
            timeout_seconds=10,
            max_attempts=1,
        )
        raw_response = getattr(response, "content", None)
        if not isinstance(raw_response, bytes) or not raw_response:
            raise OfficialCalendarCacheError(
                "official response did not expose non-empty response bytes"
            )
        captured_at = datetime.now(timezone.utc)
        response_url = getattr(response, "url", None)
        if not isinstance(response_url, str):
            response_url = None
        cache = build_twse_calendar_cache(
            calendar_year=args.year,
            raw_response=raw_response,
            requested_at=requested_at,
            captured_at=captured_at,
            response_status=int(getattr(response, "status_code", 0)),
            response_headers=getattr(response, "headers", {}),
            response_url=response_url,
        )
        file_hash = write_twse_calendar_cache(
            output,
            cache,
            allowed_root=allowed_root,
        )
    except (OSError, RuntimeError, ValueError, OfficialCalendarCacheError) as error:
        _print_blocked(f"{type(error).__name__}: {error}")
        return 2

    print(
        json.dumps(
            {
                "status": "official_calendar_cache_captured",
                "path": str(output),
                "file_sha256": file_hash,
                "schema_version": cache["schema_version"],
                "calendar_year": cache["calendar_year"],
                "coverage": cache["coverage"],
                "source": cache["source"],
                "captured_at_utc": cache["captured_at_utc"],
                "expires_at_utc": cache["expires_at_utc"],
                "candidate_only": True,
                "formal_clock_created": False,
                "formal_paths_written": False,
                "market_db_written": False,
                "paper_ledger_written": False,
                "broker_order_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _print_blocked(reason: str) -> None:
    print(
        json.dumps(
            {
                "status": "blocked",
                "reason": reason,
                "candidate_only": True,
                "formal_clock_created": False,
                "formal_paths_written": False,
                "market_db_written": False,
                "paper_ledger_written": False,
                "broker_order_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
