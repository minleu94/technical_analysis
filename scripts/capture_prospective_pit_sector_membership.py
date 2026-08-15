"""Fixture-only capture CLI for prospective PIT sector membership.

CLI 不下載外部來源、不使用 companies.csv、不猜測 universe；rows、source registry
與 expected symbols 都必須由呼叫端明確提供，且輸出只寫指定的 `.json`／`.jsonl`／
`.jsonl.gz` path。正式 path 與 watcher 不在此 CLI 的權限範圍內。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.prospective_formal_clock import (  # noqa: E402
    ProspectiveFormalClockError,
    load_clock_manifest_for_capture,
)
from data_module.prospective_pit_sector_membership import (  # noqa: E402
    PIT_SECTOR_MEMBERSHIP_RESULT_SCHEMA_VERSION,
    ProspectivePitSectorMembershipError,
    capture_prospective_pit_sector_membership,
)


def _parse_now(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("--now must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include timezone")
    return parsed


def _read_array(path: Path, field_name: str) -> list[dict[str, object]]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field_name} JSON is unreadable") from error
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} JSON must be a non-empty array")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{field_name} JSON rows must be objects")
    return value


def _read_symbols(path: Path) -> tuple[str, ...]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("symbols JSON is unreadable") from error
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("symbols JSON must be a non-empty text array")
    return tuple(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixture-only capture of prospective PIT sector membership。"
    )
    parser.add_argument("--fixture-only", action="store_true", required=True)
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--decision-timestamp", required=True)
    parser.add_argument("--rows-json", type=Path, required=True)
    parser.add_argument("--source-registry-json", type=Path, required=True)
    parser.add_argument("--symbols-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        now = _parse_now(args.now)
        clock = load_clock_manifest_for_capture(args.clock_manifest, now=now)
        result = capture_prospective_pit_sector_membership(
            clock=clock,
            output_path=args.output,
            decision_timestamp=args.decision_timestamp,
            now=now,
            rows=_read_array(args.rows_json, "rows"),
            source_registry=_read_array(args.source_registry_json, "source_registry"),
            expected_symbols=_read_symbols(args.symbols_json),
        )
        payload = result.to_dict()
        payload["fixture_only"] = True
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ProspectiveFormalClockError,
        ProspectivePitSectorMembershipError,
    ) as error:
        print(
            json.dumps(
                {
                    "schema_version": PIT_SECTOR_MEMBERSHIP_RESULT_SCHEMA_VERSION,
                    "status": "blocked",
                    "fixture_only": True,
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                    "secret_values_emitted": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
