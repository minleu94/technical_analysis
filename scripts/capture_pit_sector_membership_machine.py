"""從官方 TWSE/TPEx OpenAPI 建立 current natural-day PIT sector candidate。

此 CLI 只在明確的 bounded live-readonly 模式抓取兩個官方 endpoint，將原始
response 與可重建的 first-seen source registry 寫到 TEMP，並由同一 consumer
重讀 raw custody 產生 machine receipt。它不寫 DATA_ROOT、正式 Formal path、
SQLite 或任何交易狀態。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.pit_sector_membership_machine import (  # noqa: E402
    MACHINE_PIT_CONSUMER_VERSION,
    MachinePITSourceError,
    build_machine_pit_publication,
    write_machine_pit_receipt,
)
from data_module.prospective_official_pit_source import (  # noqa: E402
    OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
)


CONFIRMATION = "capture-pit-sector-membership-machine"
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
MAX_ALLOWED_BYTES = 32 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 60.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="TEMP 下的全新輸出目錄；不會觸碰正式資料根目錄",
    )
    parser.add_argument(
        "--receipt-output",
        type=Path,
        help="machine receipt 輸出路徑；省略時寫入 output-dir/receipt.json",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="啟用 bounded 官方唯讀抓取",
    )
    parser.add_argument(
        "--confirm-live-readonly",
        action="store_true",
        help="確認只執行 bounded 官方唯讀抓取",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--expected-universe",
        type=Path,
        help="可選的 current symbol scope JSON（陣列或 {symbols:[...]}）；不會自動當歷史 universe",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if not args.live or not args.confirm_live_readonly:
            raise ValueError(
                "official PIT capture requires --live and "
                "--confirm-live-readonly"
            )
        max_bytes = _bounded_int(args.max_bytes, 1, MAX_ALLOWED_BYTES, "max_bytes")
        timeout_seconds = _bounded_timeout(args.timeout_seconds)
        output_dir = args.output_dir.expanduser().resolve()
        _require_temp_path(output_dir)
        if output_dir.exists():
            if not output_dir.is_dir() or any(output_dir.iterdir()):
                raise ValueError("output-dir must be a new empty TEMP directory")
        else:
            output_dir.mkdir(parents=True, exist_ok=False)
        expected_symbols = _read_expected_symbols(args.expected_universe)
        raw_payloads: dict[str, bytes] = {}
        http_metadata: dict[str, dict[str, object]] = {}
        for market, definition in (
            ("twse", OFFICIAL_COMPANY_SOURCE_DEFINITIONS["twse"]),
            ("tpex", OFFICIAL_COMPANY_SOURCE_DEFINITIONS["tpex"]),
        ):
            raw, response_metadata = _fetch_raw(
                definition.endpoint,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )
            raw_payloads[market] = raw
            http_metadata[market] = response_metadata
        captured_at = max(
            datetime.fromisoformat(str(item["captured_at"]))
            for item in http_metadata.values()
        )
        publication = build_machine_pit_publication(
            raw_payloads=raw_payloads,
            output_dir=output_dir,
            captured_at=captured_at,
            now=datetime.now(timezone.utc),
            expected_symbols=expected_symbols,
            http_metadata=http_metadata,
        )
        receipt_path = (
            args.receipt_output.expanduser().resolve()
            if args.receipt_output is not None
            else output_dir / "receipt.json"
        )
        _require_temp_path(receipt_path)
        receipt = write_machine_pit_receipt(
            publication.publication_path,
            receipt_path=receipt_path,
            now=datetime.now(timezone.utc),
        )
        print(
            json.dumps(
                {
                    "status": "machine_verified",
                    "consumer_version": MACHINE_PIT_CONSUMER_VERSION,
                    "publication": publication.to_dict(),
                    "receipt_path": str(receipt_path),
                    "receipt_file_hash": receipt["receipt_file_hash"],
                    "formal_oos_allowed": False,
                    "promotion_eligible": False,
                    "production_action_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        HTTPError,
        URLError,
        MachinePITSourceError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "formal_oos_allowed": False,
                    "promotion_eligible": False,
                    "production_action_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


def _fetch_raw(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
) -> tuple[bytes, dict[str, object]]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "technical-analysis-pit-machine-producer/1.0",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(max_bytes + 1)
        completed_at = datetime.now(timezone.utc)
        final_url = response.geturl()
        status = getattr(response, "status", None)
        headers = response.headers
    if len(body) > max_bytes:
        raise ValueError(f"official PIT response exceeds max_bytes: {url}")
    if not body:
        raise ValueError(f"official PIT response is empty: {url}")
    if not isinstance(final_url, str) or not final_url.strip():
        raise ValueError(f"official PIT response final URL is missing: {url}")
    if isinstance(status, bool) or not isinstance(status, int):
        raise ValueError(f"official PIT response HTTP status is missing: {url}")
    return body, {
        "requested_url": url,
        "final_url": final_url.strip(),
        "http_status": status,
        "content_type": str(headers.get("Content-Type") or "application/json"),
        "http_date": headers.get("Date"),
        "http_last_modified": headers.get("Last-Modified"),
        "captured_at": completed_at.isoformat(),
    }


def _read_expected_symbols(path: Path | None) -> tuple[str, ...] | None:
    if path is None:
        return None
    try:
        payload: Any = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("expected-universe JSON is unreadable") from error
    if isinstance(payload, dict):
        payload = payload.get("symbols")
    if not isinstance(payload, list):
        raise ValueError("expected-universe must be an array or object with symbols")
    values: list[str] = []
    for item in payload:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("expected-universe symbols must be non-empty text")
        values.append(item.strip())
    return tuple(values)


def _bounded_int(value: object, minimum: int, maximum: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be within {minimum}..{maximum}")
    return value


def _bounded_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("timeout-seconds must be numeric")
    timeout = float(value)
    if not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout-seconds must be within (0, 60]")
    return timeout


def _require_temp_path(path: Path) -> None:
    try:
        path.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as error:
        raise ValueError("PIT machine output must be under TEMP") from error


if __name__ == "__main__":
    raise SystemExit(main())
