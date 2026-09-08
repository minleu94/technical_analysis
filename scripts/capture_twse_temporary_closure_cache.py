"""Capture one explicit TWSE temporary market-closure announcement.

This command is intentionally separate from the annual holiday cache.  It
accepts only an official TWSE announcement URL and requires the response text
to mention both the requested date and an explicit closure statement.  It
creates a candidate-only immutable sidecar and never writes market, Formal,
Paper-ledger or broker data.
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

from data_module.official_phase3c_fetcher import safe_request  # noqa: E402
from data_module.official_trading_calendar_cache import (  # noqa: E402
    OfficialCalendarCacheError,
    build_twse_temporary_closure_cache,
    write_twse_temporary_closure_cache,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure-date", required=True, type=date.fromisoformat)
    parser.add_argument("--source-url", required=True)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="新的 immutable sidecar，必須位於 repository output 下。",
    )
    parser.add_argument(
        "--confirm-network",
        action="store_true",
        help="明確允許對指定 TWSE 官方公告發出一次 bounded GET。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_network:
        _print_blocked("未帶 --confirm-network；不發官方請求，也不建立 sidecar。")
        return 1
    output = args.output.expanduser().resolve()
    allowed_root = (ROOT / "output").resolve()
    try:
        output.relative_to(allowed_root)
    except ValueError:
        _print_blocked("sidecar output 必須位於 repository output 下。")
        return 2
    requested_at = datetime.now(timezone.utc)
    try:
        response = safe_request(
            args.source_url,
            timeout_seconds=10,
            max_attempts=1,
        )
        raw_response = getattr(response, "content", None)
        if not isinstance(raw_response, bytes) or not raw_response:
            raise OfficialCalendarCacheError(
                "official announcement did not expose non-empty response bytes"
            )
        captured_at = datetime.now(timezone.utc)
        response_url = getattr(response, "url", None)
        if not isinstance(response_url, str):
            response_url = None
        cache = build_twse_temporary_closure_cache(
            closure_date=args.closure_date,
            raw_response=raw_response,
            source_url=args.source_url,
            requested_at=requested_at,
            captured_at=captured_at,
            response_status=int(getattr(response, "status_code", 0)),
            response_headers=getattr(response, "headers", {}),
            response_url=response_url,
        )
        file_hash = write_twse_temporary_closure_cache(
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
                "status": "twse_temporary_closure_cache_captured",
                "path": str(output),
                "file_sha256": file_hash,
                "closure_date": cache["event"]["closure_date"],  # type: ignore[index]
                "source": cache["source"],  # type: ignore[index]
                "captured_at_utc": cache["captured_at_utc"],
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
