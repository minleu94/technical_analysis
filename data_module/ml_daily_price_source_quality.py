"""唯讀檢查 daily price source 的尺度斷裂與來源選擇。

這個模組只做 source evidence 與 fail-closed 判定：它不修 SQLite、不改 PIT
shard，也不重算既有 label。資料庫以 ``mode=ro`` 開啟，canonical daily CSV
只以串流方式讀取；金融數值在 Decimal 邊界比較，不以裸 ``float`` 推導倍率。

事後稽核固定檢查「前一筆收盤、當筆開盤、下一筆開盤」的兩側尺度斷裂。這是
quarantine detector，不是 corporate action 推論；若 canonical CSV 也異常，同樣
保留 raw-source quarantine，交由正式來源治理處理。PIT/ingest 使用獨立的
``ingest_guard``，只讀當筆與已存在的前一筆證據，絕不讀下一筆資料；因此事後
稽核結果不能回溯篩除歷史 decision row，也不能把檔案 mtime 當成
``quality_known_at``。
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Literal, Mapping, Sequence


SOURCE_QUALITY_SCHEMA_VERSION = (
    "portfolio-ml-daily-price-source-quality.v1"
)
DETECTOR_POLICY_VERSION = "two-sided-price-scale-discontinuity.v1"
INGEST_GUARD_POLICY_VERSION = "one-sided-price-scale-discontinuity.v1"
QualityMode = Literal["retrospective_audit", "ingest_guard"]
PRICE_UNIT = "price_1e4"
PRICE_SCALE = 10_000
_SHA256_PREFIX = "sha256:"
_REQUIRED_CSV_COLUMNS = (
    "證券代號",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "成交股數",
)
_DB_PRICE_COLUMNS = (
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "成交股數",
)


class DailyPriceSourceQualityError(ValueError):
    """來源品質未通過；呼叫端不得繼續建立新 label/PIT artifact。"""

    def __init__(self, message: str, *, report: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.report = dict(report)


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


def _normalise_date(value: str, *, field_name: str) -> tuple[str, str]:
    text = str(value).strip()
    parsed: date
    if len(text) == 8 and text.isdigit():
        try:
            parsed = datetime.strptime(text, "%Y%m%d").date()
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid date") from exc
    else:
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be YYYY-MM-DD or YYYYMMDD") from exc
    return parsed.strftime("%Y%m%d"), parsed.isoformat()


def _decimal(value: object, *, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field_name} is missing")
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{field_name} is not numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} is not finite")
    return parsed


def _positive_decimal(value: object, *, field_name: str) -> Decimal:
    parsed = _decimal(value, field_name=field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _integer(value: object, *, field_name: str) -> int:
    parsed = _decimal(value, field_name=field_name)
    if parsed != parsed.to_integral_value():
        raise ValueError(f"{field_name} must be an integer")
    return int(parsed)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _symbol(value: object, *, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is missing")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is empty")
    return text


def _open_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    connection = sqlite3.connect(
        f"file:{resolved.as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _canonical_csv_rows(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """讀單一日期 CSV；檔案通常小於一個交易日，避免讀全歷史。"""

    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        return {}, {
            "path": str(resolved),
            "status": "missing",
            "file_sha256": None,
        }
    file_hash = _file_sha256(resolved)
    rows: dict[str, dict[str, Any]] = {}
    invalid_rows: list[dict[str, Any]] = []
    try:
        with resolved.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = tuple(str(item).strip() for item in (reader.fieldnames or ()))
            missing = sorted(set(_REQUIRED_CSV_COLUMNS) - set(columns))
            if missing:
                return rows, {
                    "path": str(resolved),
                    "status": "invalid_missing_columns",
                    "file_sha256": file_hash,
                    "missing_columns": missing,
                }
            for line_number, raw in enumerate(reader, start=2):
                try:
                    symbol = _symbol(
                        raw.get("證券代號"),
                        field_name=f"{resolved.name}:{line_number}:證券代號",
                    )
                    if symbol in rows:
                        raise ValueError(f"duplicate symbol: {symbol}")
                    prices = {
                        column: _positive_decimal(
                            raw.get(column),
                            field_name=f"{resolved.name}:{line_number}:{column}",
                        )
                        for column in _DB_PRICE_COLUMNS[:4]
                    }
                    if prices["最低價"] > min(
                        prices["開盤價"], prices["收盤價"]
                    ):
                        raise ValueError("low price is above open/close")
                    if prices["最高價"] < max(
                        prices["開盤價"], prices["收盤價"]
                    ):
                        raise ValueError("high price is below open/close")
                    volume = _integer(
                        raw.get("成交股數"),
                        field_name=f"{resolved.name}:{line_number}:成交股數",
                    )
                    if volume < 0:
                        raise ValueError("volume must be non-negative")
                except ValueError as exc:
                    invalid_rows.append(
                        {
                            "line_number": line_number,
                            "error": str(exc),
                        }
                    )
                    continue
                rows[symbol] = {
                    "symbol": symbol,
                    "open": _decimal_text(prices["開盤價"]),
                    "high": _decimal_text(prices["最高價"]),
                    "low": _decimal_text(prices["最低價"]),
                    "close": _decimal_text(prices["收盤價"]),
                    "volume_shares": volume,
                    "unit": PRICE_UNIT,
                    "scale": PRICE_SCALE,
                }
    except (OSError, UnicodeError, csv.Error) as exc:
        return {}, {
            "path": str(resolved),
            "status": "invalid_read",
            "file_sha256": file_hash,
            "error": str(exc),
        }
    metadata: dict[str, Any] = {
        "path": str(resolved),
        "status": "valid" if not invalid_rows else "valid_with_invalid_rows",
        "file_sha256": file_hash,
        "row_count": len(rows),
        "unit": PRICE_UNIT,
        "scale": PRICE_SCALE,
    }
    if invalid_rows:
        metadata["invalid_row_count"] = len(invalid_rows)
        metadata["invalid_rows_sample"] = invalid_rows[:8]
    return rows, metadata


def _db_row_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    prices = {
        key: _decimal(row[key], field_name=f"sqlite.{key}")
        for key in _DB_PRICE_COLUMNS[:4]
    }
    volume = _integer(row["成交股數"], field_name="sqlite.成交股數")
    return {
        "symbol": _symbol(row["證券代號"], field_name="sqlite.證券代號"),
        "name": "" if row["證券名稱"] is None else str(row["證券名稱"]),
        "open": _decimal_text(prices["開盤價"]),
        "high": _decimal_text(prices["最高價"]),
        "low": _decimal_text(prices["最低價"]),
        "close": _decimal_text(prices["收盤價"]),
        "volume_shares": volume,
        "unit": PRICE_UNIT,
        "scale": PRICE_SCALE,
    }


def _source_roots_for_output(
    *,
    output_path: Path,
    sqlite_path: Path,
    canonical_dir: Path,
) -> None:
    resolved_output = output_path.resolve()
    for root in (sqlite_path.resolve().parent, canonical_dir.resolve()):
        if resolved_output == root or root in resolved_output.parents:
            raise ValueError(
                "source quality output must be outside read-only source roots"
            )


def _normalise_quality_mode(value: str) -> QualityMode:
    mode = str(value).strip()
    if mode not in {"retrospective_audit", "ingest_guard"}:
        raise ValueError(
            "quality_mode must be retrospective_audit or ingest_guard"
        )
    return mode  # type: ignore[return-value]


def _normalise_quality_known_at(value: str | None) -> str | None:
    """驗證呼叫端提供的 source receipt 時間；不以檔案 mtime 代替。"""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise ValueError("quality_known_at must be a timezone-aware ISO datetime")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "quality_known_at must be a timezone-aware ISO datetime"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError("quality_known_at must be a timezone-aware ISO datetime")
    return parsed.isoformat()


def _quality_timing(
    *,
    quality_mode: QualityMode,
    quality_known_at: str | None,
) -> dict[str, Any]:
    return {
        "quality_mode": quality_mode,
        "uses_future_source_rows": quality_mode == "retrospective_audit",
        "future_source_row_used": quality_mode == "retrospective_audit",
        "quality_known_at": quality_known_at,
        "quality_known_at_status": (
            "source_receipt_time_declared_not_independently_verified"
            if quality_known_at is not None
            else "source_receipt_time_not_supplied"
        ),
        # 事後雙側結果沒有歷史可得時間證據，永遠不能拿來回溯篩選。
        "historical_retroactive_filtering_allowed": False,
    }


def _audit_ingest_guard(
    *,
    sqlite_path: Path,
    canonical_daily_price_dir: Path,
    start_key: str,
    start_iso: str,
    end_key: str,
    end_iso: str,
    normalized_symbols: tuple[str, ...] | None,
    source_manifest_hash: str | None,
    quality_known_at: str | None,
) -> dict[str, Any]:
    """以當時可得的當筆/前一筆證據執行 ingest guard。

    這個分支刻意沒有 ``next_open`` 查詢，也不讀下一個日期的 CSV。它可
    阻擋目前 SQLite 與當筆 canonical row 的不一致，但不會把事後才出現的
    下一筆價格異常回溯套到歷史 decision row。
    """

    database = sqlite_path.resolve()
    canonical_dir = canonical_daily_price_dir.resolve()
    connection = _open_readonly(database)
    csv_cache: dict[str, tuple[dict[str, dict[str, Any]], dict[str, Any]]] = {}
    candidates: list[dict[str, Any]] = []
    try:
        symbol_predicate = ""
        parameters: list[object] = [start_key, end_key]
        if normalized_symbols is not None:
            symbol_predicate = (
                " AND 證券代號 IN ("
                + ",".join("?" for _ in normalized_symbols)
                + ")"
            )
            parameters.extend(normalized_symbols)
        # 只取前一筆 SQLite close；下一筆資料在此模式中不可被觀察。
        cursor = connection.execute(
            """
            SELECT cur.日期, cur.證券代號, cur.證券名稱,
                   cur.開盤價, cur.最高價, cur.最低價, cur.收盤價,
                   cur.成交股數,
                   (SELECT prev.收盤價 FROM daily_prices AS prev
                    WHERE prev.證券代號 = cur.證券代號
                      AND prev.日期 < cur.日期
                    ORDER BY prev.日期 DESC LIMIT 1) AS previous_close
            FROM daily_prices AS cur
            WHERE cur.日期 >= ? AND cur.日期 <= ?
            """ + symbol_predicate + " ORDER BY cur.日期, cur.證券代號",
            tuple(parameters),
        )
        while rows := cursor.fetchmany(2_048):
            for row in rows:
                date_key, date_iso = _normalise_date(
                    str(row["日期"]).strip(),
                    field_name="sqlite.日期",
                )
                symbol = _symbol(row["證券代號"], field_name="sqlite.證券代號")
                if date_key not in csv_cache:
                    csv_cache[date_key] = _canonical_csv_rows(
                        canonical_dir / f"{date_key}.csv"
                    )
                canonical_rows, canonical_file = csv_cache[date_key]
                previous_date = (
                    date.fromisoformat(date_iso) - timedelta(days=1)
                ).strftime("%Y%m%d")
                if previous_date not in csv_cache:
                    csv_cache[previous_date] = _canonical_csv_rows(
                        canonical_dir / f"{previous_date}.csv"
                    )
                previous_rows, previous_file = csv_cache[previous_date]
                canonical = canonical_rows.get(symbol)
                canonical_previous = previous_rows.get(symbol)

                try:
                    db_payload = _db_row_payload(row)
                except ValueError as exc:
                    # ingest guard 也必須對 null/非法當筆資料 fail closed，不能
                    # 因無法組 payload 而把該 row 靜默略過。原始欄位只作
                    # quarantine evidence，不會被拿去重算 feature/label。
                    candidates.append(
                        {
                            "symbol": symbol,
                            "date": date_iso,
                            "detector": {
                                "previous_close": None,
                                "current_open": None,
                                "next_open": None,
                                "threshold_factor": "10",
                                "policy_version": INGEST_GUARD_POLICY_VERSION,
                                "future_source_row_used": False,
                                "parse_error": str(exc),
                            },
                            "sqlite_row": {
                                "symbol": symbol,
                                "name": (
                                    "" if row["證券名稱"] is None
                                    else str(row["證券名稱"])
                                ),
                                "open": row["開盤價"],
                                "high": row["最高價"],
                                "low": row["最低價"],
                                "close": row["收盤價"],
                                "volume_shares": row["成交股數"],
                                "unit": PRICE_UNIT,
                                "scale": PRICE_SCALE,
                            },
                            "canonical_file": canonical_file,
                            "canonical_row": canonical,
                            "canonical_context": {
                                "previous": canonical_previous,
                                "next": None,
                                "previous_file": previous_file,
                                "next_file": None,
                                "scale_discontinuity": None,
                            },
                            "differing_fields": list(
                                ("open", "high", "low", "close", "volume_shares")
                            ),
                            "classification": "sqlite_row_invalid_requires_quarantine",
                        }
                    )
                    continue
                differing_fields: list[str] = []
                if canonical is not None:
                    for field in ("open", "high", "low", "close", "volume_shares"):
                        if db_payload[field] != canonical[field]:
                            differing_fields.append(field)

                sqlite_previous_close: Decimal | None = None
                sqlite_current_open: Decimal | None = None
                try:
                    sqlite_previous_close = _positive_decimal(
                        row["previous_close"],
                        field_name="sqlite.previous_close",
                    )
                    sqlite_current_open = _positive_decimal(
                        row["開盤價"],
                        field_name="sqlite.開盤價",
                    )
                except ValueError:
                    # 缺前一筆只表示單側尺度規則無法計算；當筆來源仍須
                    # 經 canonical row 與欄位映射比對。
                    pass
                sqlite_scale_discontinuity = bool(
                    sqlite_previous_close is not None
                    and sqlite_current_open is not None
                    and sqlite_current_open * Decimal(10) < sqlite_previous_close
                )
                canonical_scale_discontinuity = False
                if canonical is not None and canonical_previous is not None:
                    canonical_scale_discontinuity = (
                        Decimal(canonical["open"]) * Decimal(10)
                        < Decimal(canonical_previous["close"])
                    )

                if canonical is None:
                    classification = (
                        "canonical_daily_row_missing"
                        if str(canonical_file["status"]).startswith("valid")
                        else "canonical_daily_source_unavailable_requires_quarantine"
                    )
                elif differing_fields:
                    classification = "sqlite_row_mismatch_against_canonical_daily_csv"
                    if sqlite_scale_discontinuity or canonical_scale_discontinuity:
                        classification = (
                            "both_sources_one_sided_scale_discontinuity_requires_quarantine"
                        )
                elif sqlite_scale_discontinuity or canonical_scale_discontinuity:
                    classification = "canonical_daily_row_has_one_sided_scale_discontinuity"
                else:
                    continue

                candidates.append(
                    {
                        "symbol": symbol,
                        "date": date_iso,
                        "detector": {
                            "previous_close": (
                                _decimal_text(sqlite_previous_close)
                                if sqlite_previous_close is not None
                                else None
                            ),
                            "current_open": (
                                _decimal_text(sqlite_current_open)
                                if sqlite_current_open is not None
                                else None
                            ),
                            "next_open": None,
                            "threshold_factor": "10",
                            "policy_version": INGEST_GUARD_POLICY_VERSION,
                            "future_source_row_used": False,
                        },
                        "sqlite_row": db_payload,
                        "canonical_file": canonical_file,
                        "canonical_row": canonical,
                        "canonical_context": {
                            "previous": canonical_previous,
                            "next": None,
                            "previous_file": previous_file,
                            "next_file": None,
                            "scale_discontinuity": canonical_scale_discontinuity,
                        },
                        "differing_fields": differing_fields,
                        "classification": classification,
                    }
                )
    finally:
        connection.close()

    classification_counts: dict[str, int] = {}
    date_counts: dict[str, int] = {}
    for candidate in candidates:
        classification = str(candidate["classification"])
        classification_counts[classification] = (
            classification_counts.get(classification, 0) + 1
        )
        day = str(candidate["date"])
        date_counts[day] = date_counts.get(day, 0) + 1
    anomaly = bool(candidates)
    report: dict[str, Any] = {
        "schema_version": SOURCE_QUALITY_SCHEMA_VERSION,
        "status": "quarantine_required" if anomaly else "source_quality_pass",
        "read_only": True,
        "labels_mutated": False,
        "repair_performed": False,
        "formal_training_allowed": not anomaly,
        "promotion_eligible": False,
        "quality_timing": _quality_timing(
            quality_mode="ingest_guard",
            quality_known_at=quality_known_at,
        ),
        "scope": {
            "start_date": start_iso,
            "end_date": end_iso,
            "symbols": (
                None if normalized_symbols is None else list(normalized_symbols)
            ),
        },
        "policy": {
            "detector_version": INGEST_GUARD_POLICY_VERSION,
            "threshold_factor": "10",
            "price_unit": PRICE_UNIT,
            "price_scale": PRICE_SCALE,
            "correction": "none",
            "corporate_action_inference": False,
            "future_source_rows": "forbidden",
        },
        "source": {
            "sqlite_path": str(database),
            "sqlite_mode": "ro",
            "sqlite_query_only": True,
            "canonical_daily_price_dir": str(canonical_dir),
            "source_manifest_hash": source_manifest_hash,
        },
        "candidate_count": len(candidates),
        "affected_date_counts": dict(sorted(date_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "candidates": sorted(
            candidates,
            key=lambda item: (str(item["date"]), str(item["symbol"])),
        ),
    }
    report["report_hash"] = _payload_hash(report)
    return report


def audit_daily_price_source(
    *,
    sqlite_path: Path,
    canonical_daily_price_dir: Path,
    start_date: str,
    end_date: str,
    symbols: Sequence[str] | None = None,
    source_manifest_hash: str | None = None,
    quality_mode: QualityMode = "retrospective_audit",
    quality_known_at: str | None = None,
) -> dict[str, Any]:
    """以唯讀 SQLite 與 canonical daily CSV 比對固定日期範圍。

    ``retrospective_audit`` 是事後雙側稽核，會讀下一筆 source row 來找出
    尺度回復；它只能產生 quarantine evidence。``ingest_guard`` 是 PIT/ingest
    唯一可用的模式，只讀當筆及前一筆，且報告明確記錄未使用未來資料。
    """

    normalized_quality_mode = _normalise_quality_mode(quality_mode)
    normalized_quality_known_at = _normalise_quality_known_at(quality_known_at)
    start_key, start_iso = _normalise_date(start_date, field_name="start_date")
    end_key, end_iso = _normalise_date(end_date, field_name="end_date")
    if start_key > end_key:
        raise ValueError("start_date must not exceed end_date")
    normalized_symbols: tuple[str, ...] | None = None
    if symbols is not None:
        normalized_symbols = tuple(sorted({_symbol(item, field_name="symbol") for item in symbols}))
        if not normalized_symbols:
            raise ValueError("symbols must not be empty when supplied")
    database = sqlite_path.resolve()
    canonical_dir = canonical_daily_price_dir.resolve()
    if not canonical_dir.is_dir():
        raise FileNotFoundError(canonical_dir)
    if normalized_quality_mode == "ingest_guard":
        return _audit_ingest_guard(
            sqlite_path=database,
            canonical_daily_price_dir=canonical_dir,
            start_key=start_key,
            start_iso=start_iso,
            end_key=end_key,
            end_iso=end_iso,
            normalized_symbols=normalized_symbols,
            source_manifest_hash=source_manifest_hash,
            quality_known_at=normalized_quality_known_at,
        )
    connection = _open_readonly(database)
    csv_cache: dict[str, tuple[dict[str, dict[str, Any]], dict[str, Any]]] = {}
    candidates: list[dict[str, Any]] = []
    try:
        symbol_predicate = ""
        parameters: list[object] = [start_key, end_key]
        if normalized_symbols is not None:
            symbol_predicate = (
                " AND 證券代號 IN ("
                + ",".join("?" for _ in normalized_symbols)
                + ")"
            )
            parameters.extend(normalized_symbols)
        # 用 correlated subquery 取得真正相鄰 source row，避免 window query
        # 因掃描邊界把前一個月／下一個月誤當成缺失。
        cursor = connection.execute(
            """
            SELECT cur.日期, cur.證券代號, cur.證券名稱,
                   cur.開盤價, cur.最高價, cur.最低價, cur.收盤價,
                   cur.成交股數,
                   (SELECT prev.收盤價 FROM daily_prices AS prev
                    WHERE prev.證券代號 = cur.證券代號
                      AND prev.日期 < cur.日期
                    ORDER BY prev.日期 DESC LIMIT 1) AS previous_close,
                   (SELECT next_row.開盤價 FROM daily_prices AS next_row
                    WHERE next_row.證券代號 = cur.證券代號
                      AND next_row.日期 > cur.日期
                    ORDER BY next_row.日期 ASC LIMIT 1) AS next_open
            FROM daily_prices AS cur
            WHERE cur.日期 >= ? AND cur.日期 <= ?
            """ + symbol_predicate + " ORDER BY cur.日期, cur.證券代號",
            tuple(parameters),
        )
        while rows := cursor.fetchmany(2_048):
            for row in rows:
                try:
                    current_open = _positive_decimal(
                        row["開盤價"], field_name="sqlite.開盤價"
                    )
                    previous_close = _positive_decimal(
                        row["previous_close"], field_name="sqlite.previous_close"
                    )
                    next_open = _positive_decimal(
                        row["next_open"], field_name="sqlite.next_open"
                    )
                except ValueError:
                    continue
                if not (
                    current_open * Decimal(10) < previous_close
                    and next_open > current_open * Decimal(10)
                ):
                    continue
                date_key = str(row["日期"]).strip()
                date_key, date_iso = _normalise_date(
                    date_key,
                    field_name="sqlite.日期",
                )
                if date_key not in csv_cache:
                    csv_cache[date_key] = _canonical_csv_rows(
                        canonical_dir / f"{date_key}.csv"
                    )
                canonical_rows, canonical_file = csv_cache[date_key]
                symbol = _symbol(row["證券代號"], field_name="sqlite.證券代號")
                canonical = canonical_rows.get(symbol)
                canonical_context: dict[str, Any] = {
                    "previous": None,
                    "next": None,
                    "previous_file": None,
                    "next_file": None,
                    "scale_discontinuity": None,
                }
                current_date = date.fromisoformat(date_iso)
                for relation, offset in (("previous", -1), ("next", 1)):
                    context_key = (current_date + timedelta(days=offset)).strftime(
                        "%Y%m%d"
                    )
                    if context_key not in csv_cache:
                        csv_cache[context_key] = _canonical_csv_rows(
                            canonical_dir / f"{context_key}.csv"
                        )
                    context_rows, context_file = csv_cache[context_key]
                    canonical_context[f"{relation}_file"] = context_file
                    context_row = context_rows.get(symbol)
                    if context_row is not None:
                        canonical_context[relation] = context_row
                if canonical is not None:
                    context_previous = canonical_context["previous"]
                    context_next = canonical_context["next"]
                    if context_previous is not None and context_next is not None:
                        canonical_context["scale_discontinuity"] = (
                            Decimal(canonical["open"]) * Decimal(10)
                            < Decimal(context_previous["close"])
                            and Decimal(context_next["open"])
                            > Decimal(canonical["open"]) * Decimal(10)
                        )
                db_payload = _db_row_payload(row)
                differing_fields: list[str] = []
                classification = "raw_source_anomaly_requires_quarantine"
                if canonical is None:
                    if str(canonical_file["status"]).startswith("valid"):
                        classification = "canonical_daily_row_missing"
                    else:
                        classification = (
                            "canonical_daily_source_unavailable_requires_quarantine"
                        )
                else:
                    for field in ("open", "high", "low", "close", "volume_shares"):
                        if db_payload[field] != canonical[field]:
                            differing_fields.append(field)
                    if differing_fields:
                        classification = (
                            "sqlite_row_mismatch_against_canonical_daily_csv"
                            if canonical_context["scale_discontinuity"] is not True
                            else "both_sources_scale_discontinuity_requires_quarantine"
                        )
                    else:
                        classification = (
                            "canonical_daily_row_has_scale_discontinuity"
                        )
                candidates.append(
                    {
                        "symbol": symbol,
                        "date": date_iso,
                        "detector": {
                            "previous_close": _decimal_text(previous_close),
                            "current_open": _decimal_text(current_open),
                            "next_open": _decimal_text(next_open),
                            "threshold_factor": "10",
                            "policy_version": DETECTOR_POLICY_VERSION,
                        },
                        "sqlite_row": db_payload,
                        "canonical_file": canonical_file,
                        "canonical_row": canonical,
                        "canonical_context": canonical_context,
                        "differing_fields": differing_fields,
                        "classification": classification,
                    }
                )
    finally:
        connection.close()

    classification_counts: dict[str, int] = {}
    date_counts: dict[str, int] = {}
    for candidate in candidates:
        classification = str(candidate["classification"])
        classification_counts[classification] = (
            classification_counts.get(classification, 0) + 1
        )
        day = str(candidate["date"])
        date_counts[day] = date_counts.get(day, 0) + 1
    anomaly = bool(candidates)
    report: dict[str, Any] = {
        "schema_version": SOURCE_QUALITY_SCHEMA_VERSION,
        "status": (
            "quarantine_required" if anomaly else "source_quality_pass"
        ),
        "read_only": True,
        "labels_mutated": False,
        "repair_performed": False,
        "formal_training_allowed": not anomaly,
        "promotion_eligible": False,
        "quality_timing": _quality_timing(
            quality_mode="retrospective_audit",
            quality_known_at=normalized_quality_known_at,
        ),
        "scope": {
            "start_date": start_iso,
            "end_date": end_iso,
            "symbols": (
                None if normalized_symbols is None else list(normalized_symbols)
            ),
        },
        "policy": {
            "detector_version": DETECTOR_POLICY_VERSION,
            "threshold_factor": "10",
            "price_unit": PRICE_UNIT,
            "price_scale": PRICE_SCALE,
            "correction": "none",
            "corporate_action_inference": False,
            "future_source_rows": "used_for_posthoc_audit_only",
        },
        "source": {
            "sqlite_path": str(database),
            "sqlite_mode": "ro",
            "sqlite_query_only": True,
            "canonical_daily_price_dir": str(canonical_dir),
            "source_manifest_hash": source_manifest_hash,
        },
        "candidate_count": len(candidates),
        "affected_date_counts": dict(sorted(date_counts.items())),
        "classification_counts": dict(sorted(classification_counts.items())),
        "candidates": sorted(
            candidates,
            key=lambda item: (str(item["date"]), str(item["symbol"])),
        ),
    }
    report["report_hash"] = _payload_hash(report)
    return report


def write_quarantine_report(
    path: Path,
    report: Mapping[str, Any],
    *,
    source_roots: Iterable[Path] = (),
) -> Path:
    """原子保存 quarantine report，禁止寫入任何 source root。"""

    output = path.resolve()
    for root in source_roots:
        resolved_root = Path(root).resolve()
        if output == resolved_root or resolved_root in output.parents:
            raise ValueError("quarantine report must be outside source roots")
    if not isinstance(report, Mapping):
        raise TypeError("report must be a mapping")
    body = dict(report)
    supplied_hash = body.pop("report_hash", None)
    expected_hash = _payload_hash(body)
    if supplied_hash is not None and supplied_hash != expected_hash:
        raise ValueError("report_hash mismatch")
    body["report_hash"] = expected_hash
    encoded = (_canonical_json(body) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != encoded:
            raise FileExistsError(
                f"quarantine report already exists with different content: {output}"
            )
        return output
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def assert_daily_price_source_quality(
    *,
    sqlite_path: Path,
    canonical_daily_price_dir: Path,
    start_date: str,
    end_date: str,
    symbols: Sequence[str] | None = None,
    quality_mode: QualityMode = "ingest_guard",
    quality_known_at: str | None = None,
) -> dict[str, Any]:
    """供 PIT ingest 使用的 fail-closed source guard。

    預設使用不讀未來 row 的 ``ingest_guard``。呼叫端若明確選擇
    ``retrospective_audit``，所得結果仍只能作事後 quarantine evidence，
    不能當成歷史 decision row 的可得性證明。
    """

    report = audit_daily_price_source(
        sqlite_path=sqlite_path,
        canonical_daily_price_dir=canonical_daily_price_dir,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
        quality_mode=quality_mode,
        quality_known_at=quality_known_at,
    )
    if report["candidate_count"]:
        raise DailyPriceSourceQualityError(
            "daily price source quality quarantine required: "
            f"{report['candidate_count']} candidate rows",
            report=report,
        )
    return report


__all__ = [
    "DETECTOR_POLICY_VERSION",
    "DailyPriceSourceQualityError",
    "INGEST_GUARD_POLICY_VERSION",
    "PRICE_SCALE",
    "PRICE_UNIT",
    "QualityMode",
    "SOURCE_QUALITY_SCHEMA_VERSION",
    "assert_daily_price_source_quality",
    "audit_daily_price_source",
    "write_quarantine_report",
]
