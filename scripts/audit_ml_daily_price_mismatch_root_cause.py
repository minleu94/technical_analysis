"""唯讀比對 persisted SQLite、current canonical CSV 與指定歷史 backup。

此工具只建立 root-cause evidence，不修復 D source，也不把 backup/canonical
任一方自動升格為官方真值。
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_daily_price_source_quality import (  # noqa: E402
    _canonical_csv_rows,
    audit_daily_price_source,
    write_quarantine_report,
)
from data_module.twse_historical_daily_capture import (  # noqa: E402
    COMPARISON_SCHEMA_VERSION,
    load_twse_capture,
)


_SHA256_PREFIX = "sha256:"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _source_symbol(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit() and len(text) <= 4:
        text = text.zfill(4)
    return text


def _source_decimal(value: object, *, field_name: str) -> str:
    from decimal import Decimal, InvalidOperation

    text = str(value).strip().replace(",", "") if value is not None else ""
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} is not numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field_name} is not finite")
    return format(number, "f")


def _source_integer(value: object, *, field_name: str) -> int:
    from decimal import Decimal, InvalidOperation

    text = str(value).strip().replace(",", "") if value is not None else ""
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} is not numeric") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"{field_name} is not an integer")
    return int(number)


def _read_alternate_daily_rows(
    path: Path,
    *,
    date_iso: str,
    symbols: tuple[str, ...],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """以串流方式核對整合日價檔；不把全歷史 CSV 載入記憶體。"""

    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise FileNotFoundError(resolved)
    date_key = date_iso.replace("-", "")
    expected = set(symbols)
    rows: dict[str, dict[str, Any]] = {}
    rows_scanned = 0
    with resolved.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "日期",
            "證券代號",
            "證券名稱",
            "開盤價",
            "最高價",
            "最低價",
            "收盤價",
            "成交股數",
        }
        missing = sorted(required - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(
                "alternate daily input missing columns: " + ",".join(missing)
            )
        for raw in reader:
            rows_scanned += 1
            symbol = _source_symbol(raw.get("證券代號"))
            if str(raw.get("日期") or "").strip().replace("-", "") != date_key:
                continue
            if symbol not in expected:
                continue
            if symbol in rows:
                raise ValueError(
                    f"alternate daily input duplicate target row: {symbol}"
                )
            prices = {
                field: _source_decimal(
                    raw.get(source_field),
                    field_name=f"alternate {symbol} {field}",
                )
                for field, source_field in (
                    ("open", "開盤價"),
                    ("high", "最高價"),
                    ("low", "最低價"),
                    ("close", "收盤價"),
                )
            }
            from decimal import Decimal

            decimal_prices = {
                field: Decimal(value) for field, value in prices.items()
            }
            if any(value <= 0 for value in decimal_prices.values()):
                raise ValueError(f"alternate {symbol} prices must be positive")
            if decimal_prices["low"] > min(
                decimal_prices["open"], decimal_prices["close"]
            ):
                raise ValueError(f"alternate {symbol} low is above open/close")
            if decimal_prices["high"] < max(
                decimal_prices["open"], decimal_prices["close"]
            ):
                raise ValueError(f"alternate {symbol} high is below open/close")
            volume = _source_integer(
                raw.get("成交股數"),
                field_name=f"alternate {symbol} volume",
            )
            if volume < 0:
                raise ValueError(f"alternate {symbol} volume is negative")
            rows[symbol] = {
                "symbol": symbol,
                "name": str(raw.get("證券名稱") or ""),
                **prices,
                "volume_shares": volume,
                "unit": "price_1e4",
                "scale": 10_000,
            }
    return rows, {
        "path": str(resolved),
        "file_sha256": _file_sha256(resolved),
        "bytes": resolved.stat().st_size,
        "mtime_utc": datetime.fromtimestamp(
            resolved.stat().st_mtime,
            timezone.utc,
        ).isoformat(),
        "rows_scanned": rows_scanned,
        "target_row_count": len(rows),
        "parser_status": "streamed_target_date_rows",
    }


def _numeric_differences(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> list[str]:
    from decimal import Decimal, InvalidOperation

    fields = ("open", "high", "low", "close", "volume_shares")
    if left is None or right is None:
        return list(fields)
    differences: list[str] = []
    for field in fields:
        try:
            equal = Decimal(str(left.get(field)).replace(",", "")) == Decimal(
                str(right.get(field)).replace(",", "")
            )
        except (InvalidOperation, TypeError, ValueError):
            equal = left.get(field) == right.get(field)
        if not equal:
            differences.append(field)
    return differences


def _load_official_comparison(
    path: Path,
    *,
    date_iso: str,
    symbols: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], Path]:
    """讀取並驗證已保存的官方 response comparison。"""

    comparison_path = path.resolve()
    if comparison_path.name != "comparison.json":
        raise ValueError(
            "official comparison path must be its immutable comparison.json"
        )
    try:
        receipt, comparison = load_twse_capture(comparison_path.parent)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("official comparison cannot be verified") from exc
    if comparison.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        raise ValueError("official comparison schema is unsupported")
    if comparison.get("date") != date_iso:
        raise ValueError("official comparison date mismatch")
    if tuple(comparison.get("requested_symbols") or ()) != symbols:
        raise ValueError("official comparison symbol scope mismatch")
    capture = comparison.get("capture")
    verification = comparison.get("verification")
    rows = comparison.get("rows")
    if not isinstance(capture, Mapping) or not isinstance(verification, Mapping):
        raise ValueError("official comparison metadata is invalid")
    if not isinstance(rows, list) or len(rows) != len(symbols):
        raise ValueError("official comparison rows are incomplete")
    if (
        verification.get("official_requested_rows_present") is not True
        or verification.get("official_row_count") != len(symbols)
    ):
        raise ValueError("official comparison does not cover requested symbols")
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("official comparison row is invalid")
        symbol = str(row.get("symbol") or "").strip()
        official = row.get("official_row")
        if symbol not in symbols or not isinstance(official, Mapping):
            raise ValueError("official comparison row identity is invalid")
        if symbol in by_symbol:
            raise ValueError("official comparison has duplicate symbol")
        by_symbol[symbol] = dict(official)
    if tuple(sorted(by_symbol)) != symbols:
        raise ValueError("official comparison has partial symbol coverage")
    evidence = {
        "comparison_path": str(comparison_path),
        "comparison_file_sha256": _file_sha256(comparison_path),
        "comparison_hash": str(comparison["comparison_hash"]),
        "receipt_hash": str(receipt["receipt_hash"]),
        "response_sha256": str(capture["response_sha256"]),
        "captured_at_utc": capture.get("captured_at_utc"),
        "historical_decision_time_available": (
            capture.get("historical_decision_time_available") is True
        ),
        "verified_row_count": len(by_symbol),
    }
    if evidence["historical_decision_time_available"]:
        raise ValueError(
            "historical official capture cannot be marked decision-time available"
        )
    return evidence, by_symbol, comparison_path.parent


def _normalise_date(value: str) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def build_root_cause_report(
    *,
    sqlite_path: Path,
    canonical_daily_price_dir: Path,
    date_value: str,
    symbols: tuple[str, ...],
    historical_backup_path: Path,
    alternate_daily_input_path: Path | None = None,
    official_comparison_path: Path | None = None,
) -> dict[str, Any]:
    date_iso = _normalise_date(date_value)
    normalized_symbols = tuple(sorted({str(symbol).strip() for symbol in symbols}))
    if not normalized_symbols or any(not symbol for symbol in normalized_symbols):
        raise ValueError("symbols must be non-empty")
    backup_path = historical_backup_path.resolve()
    if not backup_path.is_file() or backup_path.is_symlink():
        raise FileNotFoundError(backup_path)
    source_report = audit_daily_price_source(
        sqlite_path=sqlite_path,
        canonical_daily_price_dir=canonical_daily_price_dir,
        start_date=date_iso,
        end_date=date_iso,
        symbols=normalized_symbols,
        quality_mode="ingest_guard",
    )
    candidates = source_report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("source quality candidate payload is invalid")
    by_symbol = {
        str(item["symbol"]): item
        for item in candidates
        if isinstance(item, Mapping)
    }
    if tuple(sorted(by_symbol)) != normalized_symbols:
        raise ValueError("root-cause audit requires every requested symbol")
    backup_rows, backup_file = _canonical_csv_rows(backup_path)
    alternate_rows: dict[str, dict[str, Any]] = {}
    alternate_file: dict[str, Any] | None = None
    if alternate_daily_input_path is not None:
        alternate_rows, alternate_file = _read_alternate_daily_rows(
            alternate_daily_input_path,
            date_iso=date_iso,
            symbols=normalized_symbols,
        )
    official_evidence: dict[str, Any] | None = None
    official_rows: dict[str, dict[str, Any]] = {}
    if official_comparison_path is not None:
        official_evidence, official_rows, _ = _load_official_comparison(
            official_comparison_path,
            date_iso=date_iso,
            symbols=normalized_symbols,
        )

    rows: list[dict[str, Any]] = []
    backup_matches_sqlite = 0
    alternate_matches_sqlite = 0
    official_matches_sqlite = 0
    official_matches_canonical = 0
    for symbol in normalized_symbols:
        candidate = by_symbol[symbol]
        sqlite_row = candidate.get("sqlite_row")
        if not isinstance(sqlite_row, Mapping):
            raise ValueError(f"SQLite row payload is invalid for {symbol}")
        backup_row = backup_rows.get(symbol)
        backup_differences = _numeric_differences(
            backup_row,
            sqlite_row,
        )
        match = backup_row is not None and not backup_differences
        if match:
            backup_matches_sqlite += 1
        alternate_row = alternate_rows.get(symbol)
        alternate_differences = _numeric_differences(
            alternate_row,
            sqlite_row,
        )
        if alternate_row is not None and not alternate_differences:
            alternate_matches_sqlite += 1
        official_row = official_rows.get(symbol)
        official_sqlite_differences = _numeric_differences(
            official_row,
            sqlite_row,
        )
        official_canonical_differences = _numeric_differences(
            official_row,
            candidate.get("canonical_row")
            if isinstance(candidate.get("canonical_row"), Mapping)
            else None,
        )
        if official_row is not None and not official_sqlite_differences:
            official_matches_sqlite += 1
        if official_row is not None and not official_canonical_differences:
            official_matches_canonical += 1
        rows.append(
            {
                "symbol": symbol,
                "date": date_iso,
                "sqlite_row": sqlite_row,
                "current_canonical_row": candidate.get("canonical_row"),
                "historical_backup_row": backup_row,
                "alternate_daily_input_row": alternate_row,
                "backup_matches_sqlite": match,
                "historical_backup_vs_sqlite_differing_fields": (
                    backup_differences
                ),
                "alternate_daily_input_matches_sqlite": (
                    alternate_row is not None and not alternate_differences
                ),
                "alternate_daily_input_vs_sqlite_differing_fields": (
                    alternate_differences
                ),
                "official_historical_row": official_row,
                "official_historical_vs_sqlite_differing_fields": (
                    official_sqlite_differences
                ),
                "official_historical_vs_current_canonical_differing_fields": (
                    official_canonical_differences
                ),
                "source_quality_classification": candidate.get("classification"),
            }
        )

    code_paths = {
        "data_loader": PROJECT_ROOT / "data_module" / "data_loader.py",
        "update_service": PROJECT_ROOT / "app_module" / "update_service.py",
        "update_data_normalization": (
            PROJECT_ROOT / "app_module" / "update_data_normalization.py"
        ),
        "fetching_contract_doc": (
            PROJECT_ROOT / "docs" / "03_data" / "DATA_FETCHING_LOGIC.md"
        ),
    }
    code_hashes = {
        name: {
            "path": str(path.resolve()),
            "file_sha256": _file_sha256(path),
        }
        for name, path in code_paths.items()
    }
    source_files: dict[str, Any] = {
        "sqlite": {
            "path": str(sqlite_path.resolve()),
            "file_sha256": _file_sha256(sqlite_path.resolve()),
            "bytes": sqlite_path.resolve().stat().st_size,
            "mtime_utc": datetime.fromtimestamp(
                sqlite_path.resolve().stat().st_mtime,
                timezone.utc,
            ).isoformat(),
        },
        "current_canonical_csv": {
            "path": str(
                (canonical_daily_price_dir / f"{date_iso.replace('-', '')}.csv").resolve()
            ),
            "file_sha256": source_report["candidates"][0]["canonical_file"].get(
                "file_sha256"
            ),
        },
        "historical_backup": {
            "path": str(backup_path),
            "file_sha256": _file_sha256(backup_path),
            "parser_status": backup_file.get("status"),
            "bytes": backup_path.stat().st_size,
            "mtime_utc": datetime.fromtimestamp(
                backup_path.stat().st_mtime,
                timezone.utc,
            ).isoformat(),
        },
    }
    if alternate_file is not None:
        source_files["alternate_daily_input"] = alternate_file
    if official_evidence is not None:
        source_files["official_comparison"] = official_evidence

    body: dict[str, Any] = {
        "schema_version": "portfolio-ml-daily-price-mismatch-root-cause.v2",
        "status": (
            "research_root_cause_evidence_with_official_response"
            if official_evidence is not None
            else "research_root_cause_evidence"
        ),
        "read_only": True,
        "labels_mutated": False,
        "repair_performed": False,
        "formal_training_allowed": False,
        "promotion_eligible": False,
        "scope": {
            "date": date_iso,
            "symbols": list(normalized_symbols),
            "row_count": len(rows),
        },
        "source_quality": {
            "report_hash": source_report.get("report_hash"),
            "quality_mode": "ingest_guard",
            "future_source_rows_used": False,
        },
        "source_files": source_files,
        "producer_and_mapping_evidence": {
            "code_file_hashes": code_hashes,
            "download_writer": {
                "method": "DataLoader.download_from_api",
                "endpoint": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                "request_types": ["ALL", "ALLBUT0999"],
                "output": "daily_price/YYYYMMDD.csv",
            },
            "sqlite_writer": {
                "method": "UpdateService._upsert_sqlite_rows",
                "key": ["證券代號", "日期"],
                "price_mapping": "欄位名稱保留，未執行價格尺度轉換",
                "alternate_daily_input": "meta_data/stock_data_whole.csv via daily_data",
            },
            "normalization": {
                "stock_code": "strip .0 and zero-pad <=4 digits",
                "price_scale_conversion": "none",
            },
        },
        "findings": {
            "backup_rows_matching_sqlite_count": backup_matches_sqlite,
            "requested_row_count": len(rows),
            "all_backup_rows_match_sqlite": backup_matches_sqlite == len(rows),
            "alternate_daily_input_rows_matching_sqlite_count": alternate_matches_sqlite,
            "all_alternate_daily_input_rows_match_sqlite": (
                alternate_daily_input_path is not None
                and alternate_matches_sqlite == len(rows)
            ),
            "alternate_daily_input_scope_complete": (
                alternate_daily_input_path is not None
                and len(alternate_rows) == len(rows)
            ),
            "official_historical_rows_matching_sqlite_count": official_matches_sqlite,
            "official_historical_rows_matching_current_canonical_count": (
                official_matches_canonical
            ),
            "official_historical_scope_complete": (
                official_comparison_path is not None
                and len(official_rows) == len(rows)
            ),
            "canonical_is_current_candidate_only": True,
            "official_raw_response_receipt_present": official_evidence is not None,
            "official_decision_time_response_receipt_present": False,
            "lineage_status": (
                "official_historical_response_matches_current_canonical_and_differs_from_sqlite; "
                "decision_time_receipt_missing"
                if official_evidence is not None
                else (
                    "sqlite_matches_named_corrupt_backup_and_differs_from_current_canonical; "
                    "raw_http_receipt_missing"
                )
            ),
            "interpretation": (
                (
                    "official historical response rows match current canonical rows and "
                    "differ from persisted SQLite rows; alternate input/backup matches "
                    "support a stale-input or writer-selection path, but no writer run "
                    "receipt proves the exact mutation cause"
                    if official_evidence is not None
                    else "persisted SQLite rows are consistent with the historical file named "
                    "corrupt, while current canonical CSV is a separate later value set; "
                    "the evidence does not authorize automatic correction"
                )
            ),
        },
        "rows": rows,
    }
    body["report_hash"] = _payload_hash(body)
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--daily-price-dir", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol", action="append", dest="symbols", required=True)
    parser.add_argument("--historical-backup", type=Path, required=True)
    parser.add_argument("--alternate-daily-input", type=Path)
    parser.add_argument("--official-comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_root_cause_report(
        sqlite_path=args.sqlite,
        canonical_daily_price_dir=args.daily_price_dir,
        date_value=args.date,
        symbols=tuple(args.symbols),
        historical_backup_path=args.historical_backup,
        alternate_daily_input_path=args.alternate_daily_input,
        official_comparison_path=args.official_comparison,
    )
    source_roots = [
        args.sqlite.parent,
        args.daily_price_dir,
        args.historical_backup.parent,
    ]
    if args.alternate_daily_input is not None:
        source_roots.append(args.alternate_daily_input.parent)
    if args.official_comparison is not None:
        source_roots.append(args.official_comparison.resolve().parent)
    output = write_quarantine_report(
        args.output,
        report,
        source_roots=tuple(source_roots),
    )
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "report_hash": report["report_hash"],
                "row_count": report["scope"]["row_count"],
                "backup_rows_matching_sqlite_count": report["findings"][
                    "backup_rows_matching_sqlite_count"
                ],
                "all_backup_rows_match_sqlite": report["findings"][
                    "all_backup_rows_match_sqlite"
                ],
                "official_raw_response_receipt_present": report["findings"][
                    "official_raw_response_receipt_present"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
