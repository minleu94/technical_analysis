"""Fixture/staging-only official TWSE／TPEX prospective PIT capture。

這個入口要求呼叫端注入官方 endpoint 的 raw JSON bytes 與 source metadata；不
自動下載、不讀取 ``companies.csv``、不註冊 scheduler，也不觸碰任何 BALDR
formal path。``--preactivation-staging`` 只供 activation 前驗證 source／schema
與 lineage；實際 daily capture 不帶這個旗標，會要求 clock 已到達 activation day。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.prospective_formal_clock import (  # noqa: E402
    ProspectiveFormalClockError,
    canonical_json,
    load_clock_manifest,
    load_clock_manifest_for_capture,
)
from data_module.prospective_official_pit_source import (  # noqa: E402
    OfficialProspectivePITCapture,
    ProspectiveOfficialPITSourceError,
    build_official_first_seen_capture,
)
from data_module.prospective_pit_sector_membership import (  # noqa: E402
    PIT_SECTOR_MEMBERSHIP_RESULT_SCHEMA_VERSION,
    ProspectivePitSectorMembershipError,
    capture_prospective_pit_sector_membership,
)


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


def _read_json(path: Path, field_name: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{field_name} JSON is unreadable") from error


def _read_symbols(path: Path) -> tuple[str, ...]:
    value = _read_json(path, "symbols")
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("symbols JSON must be a non-empty text array")
    return tuple(value)


def _read_source_metadata(path: Path) -> tuple[dict[str, str], dict[str, str], dict[str, datetime]]:
    value = _read_json(path, "source metadata")
    if not isinstance(value, dict) or not value:
        raise ValueError("source metadata JSON must be a non-empty object")
    license_ids: dict[str, str] = {}
    license_urls: dict[str, str] = {}
    publication_at: dict[str, datetime] = {}
    for market, item in value.items():
        if not isinstance(market, str) or not isinstance(item, dict):
            raise ValueError("source metadata entries must be objects")
        license_id = item.get("license_id")
        license_url = item.get("license_url")
        publication = item.get("publication_at")
        if (
            not isinstance(license_id, str)
            or not license_id.strip()
            or not isinstance(license_url, str)
            or not license_url.strip()
            or not isinstance(publication, str)
            or not publication.strip()
        ):
            raise ValueError(f"source metadata for {market} is incomplete")
        license_ids[market] = license_id
        license_urls[market] = license_url
        publication_at[market] = _parse_datetime(
            publication,
            f"publication_at[{market}]",
        )
    return license_ids, license_urls, publication_at


def _read_raw_sources(args: argparse.Namespace) -> dict[str, bytes]:
    paths = {
        "twse": args.twse_raw_json,
        "tpex": args.tpex_raw_json,
        "emerging": args.emerging_raw_json,
    }
    raw_payloads: dict[str, bytes] = {}
    for market, path in paths.items():
        if path is None:
            continue
        if "companies.csv" in str(path).casefold():
            raise ValueError("companies.csv cannot be used as prospective PIT input")
        try:
            raw_payloads[market] = path.read_bytes()
        except OSError as error:
            raise ValueError(f"{market} raw JSON is unreadable") from error
    if not raw_payloads:
        raise ValueError("at least one official raw JSON input is required")
    return raw_payloads


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixture/staging-only official TWSE/TPEX prospective PIT capture。"
    )
    parser.add_argument("--fixture-only", action="store_true", required=True)
    parser.add_argument("--preactivation-staging", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--decision-timestamp", required=True)
    parser.add_argument("--available-at", required=True)
    parser.add_argument("--effective-from", required=True)
    parser.add_argument("--symbols-json", type=Path, required=True)
    parser.add_argument("--source-metadata-json", type=Path, required=True)
    parser.add_argument("--twse-raw-json", type=Path)
    parser.add_argument("--tpex-raw-json", type=Path)
    parser.add_argument("--emerging-raw-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _write_staging_package(
    output: Path,
    *,
    clock_id: str,
    clock_manifest_hash: str,
    universe_hash: str,
    planned_decision_timestamp: str,
    capture: OfficialProspectivePITCapture,
) -> None:
    if not output.parent.exists():
        raise ValueError("staging output parent directory must already exist")
    payload = {
        "schema_version": "prospective-official-company-basic-pit-staging.v1",
        "status": "staged",
        "formal_consumer_compatible": False,
        "historical_backfill_claimed": False,
        "clock_id": clock_id,
        "clock_manifest_hash": clock_manifest_hash,
        "universe_hash": universe_hash,
        "planned_decision_timestamp": planned_decision_timestamp,
        "source_registry": list(capture.source_registry),
        "rows": list(capture.rows),
        "expected_symbols": list(capture.expected_symbols),
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(payload).encode("utf-8"))
    except FileExistsError as error:
        raise ValueError("staging output already exists") from error


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        now = _parse_datetime(args.now, "--now")
        clock = (
            load_clock_manifest(args.clock_manifest, now=now)
            if args.preactivation_staging
            else load_clock_manifest_for_capture(args.clock_manifest, now=now)
        )
        raw_payloads = _read_raw_sources(args)
        license_ids, license_urls, publication_at = _read_source_metadata(
            args.source_metadata_json
        )
        official_capture: OfficialProspectivePITCapture = (
            build_official_first_seen_capture(
                raw_payloads=raw_payloads,
                license_ids=license_ids,
                license_urls=license_urls,
                publication_at=publication_at,
                expected_symbols=_read_symbols(args.symbols_json),
                clock_id=clock.clock_id,
                clock_manifest_hash=clock.manifest_hash,
                universe_hash=str(clock.payload["universe_hash"]),
                available_at=_parse_datetime(args.available_at, "--available-at"),
                effective_from=_parse_date(args.effective_from, "--effective-from"),
                now=now,
            )
        )
        if args.preactivation_staging:
            _write_staging_package(
                args.output,
                clock_id=clock.clock_id,
                clock_manifest_hash=clock.manifest_hash,
                universe_hash=str(clock.payload["universe_hash"]),
                planned_decision_timestamp=args.decision_timestamp,
                capture=official_capture,
            )
            payload = official_capture.to_dict()
            payload["status"] = "staged"
            payload["staging_package_path"] = str(args.output.resolve())
        else:
            result = capture_prospective_pit_sector_membership(
                clock=clock,
                output_path=args.output,
                decision_timestamp=args.decision_timestamp,
                now=now,
                rows=official_capture.rows,
                source_registry=official_capture.source_registry,
                expected_symbols=official_capture.expected_symbols,
            )
            payload = result.to_dict()
            payload["official_source_capture"] = official_capture.to_dict()
        payload["fixture_only"] = True
        payload["preactivation_staging"] = args.preactivation_staging
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ProspectiveFormalClockError,
        ProspectiveOfficialPITSourceError,
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
