"""唯讀抓取 MOPS 秒級季報公告，僅輸出至顯式 TEMP／shadow root。"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.config import TWStockConfig
from data_module.fundamental_statement_availability_sources import (
    STATEMENT_AVAILABILITY_COLUMNS,
)
from data_module.mops_ezsearch_statement_availability import (
    MOPS_MARKETS,
    MOPSQueryResult,
    MOPS_STATEMENT_ITEMS,
    build_statement_availability_artifact,
    query_mops_ezsearch,
)
from development_module.output_guard import validate_development_output_root


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--markets",
        default=",".join(MOPS_MARKETS),
        help="逗號分隔：sii,otc,rotc,pub",
    )
    parser.add_argument(
        "--items",
        default=",".join(MOPS_STATEMENT_ITEMS),
        help="逗號分隔：F26,F27,F28,F29",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--artifact-name", default="mops-statement-availability.json")
    parser.add_argument("--mapping-name", default="fundamental-statement-availability.csv")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument(
        "--query-retries",
        type=int,
        default=0,
        help="每個失敗 query 的額外重試次數（0–3）；每次仍保留 bounded error lineage",
    )
    parser.add_argument(
        "--query-window-days",
        type=int,
        default=31,
        help="每個 market/item query 的日期窗口（1–31 天）；遇到 MOPS 1000 列上限時請縮小",
    )
    args = parser.parse_args(argv)

    if args.end_date < args.start_date:
        parser.error("--end-date 不得早於 --start-date")
    if (args.end_date - args.start_date).days >= 31:
        parser.error("單次查詢最多 31 天，避免碰到 MOPS 1000 筆截斷上限")
    markets = _parse_choices(args.markets, set(MOPS_MARKETS), "markets")
    items = _parse_choices(args.items, set(MOPS_STATEMENT_ITEMS), "items")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds 必須大於 0")
    if not 0 <= args.query_retries <= 3:
        parser.error("--query-retries 必須介於 0 與 3 之間")
    if not 1 <= args.query_window_days <= 31:
        parser.error("--query-window-days 必須介於 1 與 31 之間")

    config = TWStockConfig()
    safe_root = validate_development_output_root(
        args.output_root,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    artifact_path = _safe_output_path(safe_root, args.artifact_name)
    mapping_path = _safe_output_path(safe_root, args.mapping_name)

    query_windows = _iter_date_windows(
        args.start_date,
        args.end_date,
        window_days=args.query_window_days,
    )
    with requests.Session() as session:
        results = tuple(
            _query_with_retries(
                session,
                market=market,
                announcement_item=item,
                start_date=query_start,
                end_date=query_end,
                timeout_seconds=args.timeout_seconds,
                max_retries=args.query_retries,
            )
            for market in markets
            for item in items
            for query_start, query_end in query_windows
        )

    captured_at = datetime.now(timezone.utc).isoformat()
    artifact = build_statement_availability_artifact(
        results,
        start_date=args.start_date,
        end_date=args.end_date,
        captured_at=captured_at,
    )
    safe_root.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with mapping_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATEMENT_AVAILABILITY_COLUMNS)
        writer.writeheader()
        writer.writerows(artifact["availability_projection"])

    summary = {
        "artifact_path": str(artifact_path),
        "mapping_path": str(mapping_path),
        "event_count": artifact["quality_summary"]["event_count"],
        "projection_count": artifact["quality_summary"]["projection_count"],
        "successful_query_count": artifact["quality_summary"]["successful_query_count"],
        "official_no_data_query_count": artifact["quality_summary"][
            "official_no_data_query_count"
        ],
        "failed_query_count": artifact["quality_summary"]["failed_query_count"],
        "status": (
            "ready"
            if artifact["quality_summary"]["failed_query_count"] == 0
            and artifact["quality_summary"]["successful_query_count"] > 0
            else "degraded"
            if artifact["quality_summary"]["successful_query_count"] > 0
            else "unavailable"
        ),
        "formal_oos_allowed": False,
        "formal_credit_authorized": False,
        "production_blend_alpha_bp": 0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if artifact["quality_summary"]["successful_query_count"] > 0 else 3


def _configure_utf8_stdio() -> None:
    """讓 Windows 主控台能輸出繁體中文說明與結構化結果。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # pytest capture streams 或 host-managed stream 可能不可重設編碼。
            continue


def _safe_query(
    session: requests.Session,
    *,
    market: str,
    announcement_item: str,
    start_date: date,
    end_date: date,
    timeout_seconds: int,
) -> MOPSQueryResult:
    try:
        return query_mops_ezsearch(
            session,
            market=market,
            announcement_item=announcement_item,
            start_date=start_date,
            end_date=end_date,
            timeout_seconds=timeout_seconds,
        )

    except (requests.RequestException, ValueError) as exc:
        error_code = (
            "network_timeout"
            if isinstance(exc, requests.Timeout)
            or "timeout" in type(exc).__name__.lower()
            or "timed out" in str(exc).lower()
            else "network_error"
            if isinstance(exc, requests.RequestException)
            else "invalid_response"
        )
        material = json.dumps(
            {
                "market": market,
                "announcement_item": announcement_item,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "error_code": error_code,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return MOPSQueryResult(
            market=market,
            announcement_item=announcement_item,
            rows=(),
            response_sha256=sha256(material.encode("utf-8")).hexdigest(),
            source_status="error",
            error_code=error_code,
            query_start_date=start_date,
            query_end_date=end_date,
        )


def _query_with_retries(
    session: requests.Session,
    *,
    market: str,
    announcement_item: str,
    start_date: date,
    end_date: date,
    timeout_seconds: int,
    max_retries: int,
) -> MOPSQueryResult:
    if not 0 <= max_retries <= 3:
        raise ValueError("max_retries must be between 0 and 3")
    retry_errors: list[str] = []
    last_result: MOPSQueryResult | None = None
    for attempt in range(max_retries + 1):
        result = _safe_query(
            session,
            market=market,
            announcement_item=announcement_item,
            start_date=start_date,
            end_date=end_date,
            timeout_seconds=timeout_seconds,
        )
        last_result = result
        if result.source_status != "error":
            return replace(
                result,
                attempt_count=attempt + 1,
                retry_error_codes=tuple(retry_errors),
            )
        if result.error_code:
            retry_errors.append(result.error_code)
    assert last_result is not None
    return replace(
        last_result,
        attempt_count=max_retries + 1,
        retry_error_codes=tuple(retry_errors[:-1]),
    )


def _iter_date_windows(
    start_date: date,
    end_date: date,
    *,
    window_days: int,
) -> tuple[tuple[date, date], ...]:
    if end_date < start_date:
        raise ValueError("end_date must not be earlier than start_date")
    if not 1 <= window_days <= 31:
        raise ValueError("window_days must be between 1 and 31")
    windows: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        window_end = min(end_date, cursor + timedelta(days=window_days - 1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return tuple(windows)


def _parse_choices(raw: str, allowed: set[str], label: str) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    invalid = sorted(set(values) - allowed)
    if not values or invalid:
        raise ValueError(f"invalid {label}: {','.join(invalid) if invalid else 'empty'}")
    return values


def _safe_output_path(root: Path, name: str) -> Path:
    if not name or Path(name).name != name:
        raise ValueError("output filename must be a plain filename")
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("output path must remain under output root")
    return candidate


if __name__ == "__main__":
    raise SystemExit(main())
