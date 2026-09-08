"""唯讀抓取官方 PIT 分母所需的完整 source evidence。

預設只輸出 no-network preview。實際抓取必須帶
``--confirm-live-readonly``，且只會寫入 repository ``output`` 或 OS TEMP
下的 create-only candidate 目錄；不寫 DATA_ROOT、SQLite 或任何正式交易
資料。每個 response 的 completion timestamp 都在 ``read`` 完成後才記錄，
再交給 ``pit_prospective_denominator`` 重新解析與驗證。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.pit_prospective_denominator import (  # noqa: E402
    DATA_GOV_LICENSE_URL,
    PIT_PROSPECTIVE_DENOMINATOR_SCHEMA_VERSION,
    _SOURCE_CONTRACTS,
    build_prospective_pit_denominator,
)


MAX_BYTES = 16 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 60.0


def capture_live_denominator(
    *,
    output_dir: Path,
    coverage_start: date,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Any = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """抓取兩市場 JSON/CSV、data.gov metadata、Swagger 與授權文件。"""

    if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be in (0, {MAX_TIMEOUT_SECONDS}]")
    output = output_dir.expanduser().resolve()
    _require_output_root(output)
    selected_opener = opener or urlopen
    raw_json_payloads: dict[str, bytes] = {}
    raw_json_http: dict[str, dict[str, object]] = {}
    csv_payloads: dict[str, bytes] = {}
    csv_http: dict[str, dict[str, object]] = {}
    metadata_payloads: dict[str, bytes] = {}
    metadata_http: dict[str, dict[str, object]] = {}
    swagger_payloads: dict[str, bytes] = {}
    swagger_http: dict[str, dict[str, object]] = {}
    for market in ("twse", "tpex"):
        contract = _SOURCE_CONTRACTS[market]
        raw_json_payloads[market], raw_json_http[market] = _fetch_one(
            str(contract["endpoint_url"]),
            timeout_seconds=timeout_seconds,
            opener=selected_opener,
            kind=f"{market} official JSON",
        )
        csv_payloads[market], csv_http[market] = _fetch_one(
            str(contract["resource_url"]),
            timeout_seconds=timeout_seconds,
            opener=selected_opener,
            kind=f"{market} data.gov CSV",
        )
        metadata_payloads[market], metadata_http[market] = _fetch_one(
            str(contract["metadata_url"]),
            timeout_seconds=timeout_seconds,
            opener=selected_opener,
            kind=f"{market} data.gov metadata",
        )
        swagger_payloads[market], swagger_http[market] = _fetch_one(
            str(contract["swagger_url"]),
            timeout_seconds=timeout_seconds,
            opener=selected_opener,
            kind=f"{market} official Swagger",
        )
    license_payload, license_http = _fetch_one(
        DATA_GOV_LICENSE_URL,
        timeout_seconds=timeout_seconds,
        opener=selected_opener,
        kind="data.gov license",
    )
    observed_now = now if now is not None else datetime.now(timezone.utc)
    return build_prospective_pit_denominator(
        raw_json_payloads=raw_json_payloads,
        raw_json_http=raw_json_http,
        csv_payloads=csv_payloads,
        csv_http=csv_http,
        metadata_payloads=metadata_payloads,
        metadata_http=metadata_http,
        swagger_payloads=swagger_payloads,
        swagger_http=swagger_http,
        license_payload=license_payload,
        license_http=license_http,
        coverage_start=coverage_start,
        output_dir=output,
        now=observed_now,
    )


def _fetch_one(
    url: str,
    *,
    timeout_seconds: float,
    opener: Any,
    kind: str,
) -> tuple[bytes, dict[str, object]]:
    request = Request(
        url,
        headers={
            "User-Agent": "technical-analysis-pit-prospective-denominator/1.0",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        },
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_BYTES + 1)
            if not isinstance(body, bytes):
                body = bytes(body)
            if len(body) > MAX_BYTES:
                raise ValueError(f"{kind} exceeds bounded response size")
            # This timestamp intentionally follows the bounded read. It is the
            # first time the complete response was available to the producer.
            completed_at = datetime.now(timezone.utc).isoformat()
            status_value = getattr(response, "status", None)
            if status_value is None:
                status_value = response.getcode()
            headers = getattr(response, "headers", None)
            final_url = str(getattr(response, "geturl", lambda: url)() or url)
            content_type = str(headers.get("Content-Type") or "") if headers is not None else ""
            http_date = str(headers.get("Date") or "") if headers is not None else ""
            last_modified = str(headers.get("Last-Modified") or "") if headers is not None else ""
            return body, {
                "requested_url": url,
                "final_url": final_url,
                "http_status": int(status_value),
                "content_type": content_type,
                "http_date": http_date or None,
                "http_last_modified": last_modified or None,
                "captured_at": completed_at,
            }
    except HTTPError as error:
        raise RuntimeError(f"{kind} HTTP {error.code}") from error
    except Exception as error:
        raise RuntimeError(f"{kind} failed: {type(error).__name__}: {error}") from error


def _require_output_root(path: Path) -> None:
    repository_output = PROJECT_ROOT / "output"
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        path.relative_to(repository_output.resolve())
    except ValueError:
        try:
            path.relative_to(temp_root)
        except ValueError as error:
            raise ValueError("output directory must be under repository output or TEMP") from error


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("coverage start must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("coverage start must be YYYY-MM-DD")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--coverage-start", type=_parse_date, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--confirm-live-readonly", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_live_readonly:
        print(
            json.dumps(
                {
                    "schema_version": PIT_PROSPECTIVE_DENOMINATOR_SCHEMA_VERSION,
                    "status": "preview_no_network",
                    "coverage_start": args.coverage_start.isoformat(),
                    "confirmation_required": True,
                    "output_dir": str(args.output_dir.expanduser().resolve()),
                    "source_count": 2,
                    "license_url": DATA_GOV_LICENSE_URL,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    try:
        result = capture_live_denominator(
            output_dir=args.output_dir,
            coverage_start=args.coverage_start,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as error:  # noqa: BLE001 - bounded CLI reports typed blocker
        print(
            json.dumps(
                {"status": "blocked", "reason": str(error)[:300]},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "path": result.get("path"),
                "file_sha256": result.get("file_sha256"),
                "symbol_count": result.get("symbol_count"),
                "coverage_start": result.get("coverage_start"),
                "license_scope": result.get("license_scope"),
                "readback_verified": result.get("readback_verified"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
