"""保存並驗證 TWSE MI_INDEX 歷史日價的官方 response evidence。

本模組是研究用、唯讀的 historical capture。它保存 HTTP wire bytes 與可重播
的 receipt，再以官方 response 內的個股交易表和 SQLite / current canonical /
指定歷史 backup 逐列比對。擷取時間是事後取得時間，不能回填成該交易日盤前
的 ``available_at``，也不會修改 D 槽、SQLite、feature 或 label。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

import requests

from data_module.ml_daily_price_source_quality import _canonical_csv_rows


TWSE_MI_INDEX_ENDPOINT = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
CAPTURE_SCHEMA_VERSION = "twse-mi-index-historical-capture.v1"
COMPARISON_SCHEMA_VERSION = "twse-historical-daily-price-comparison.v1"
_SHA256_PREFIX = "sha256:"
_UTC = timezone.utc
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_CHUNK_BYTES = 1 << 20
_REQUIRED_FIELDS = (
    "證券代號",
    "證券名稱",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "成交股數",
)
_COMPARE_FIELDS = ("open", "high", "low", "close", "volume_shares")


class TwseHistoricalCaptureError(ValueError):
    """官方 response 不可安全保存、解析或比對。"""


@dataclass(frozen=True)
class TwseHistoricalCaptureResult:
    """一次 immutable capture 與比對結果。"""

    capture_directory: Path
    response_path: Path
    receipt_path: Path
    comparison_path: Path
    capture_id: str
    response_sha256: str
    comparison_hash: str
    candidate_count: int


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise TwseHistoricalCaptureError(
            f"source file cannot be read for hash: {path}"
        ) from exc
    return _SHA256_PREFIX + digest.hexdigest()


def _aware_now() -> datetime:
    return datetime.now(_UTC)


def _normalise_date(value: str) -> str:
    text = str(value).strip()
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise TwseHistoricalCaptureError(
            "date must be YYYY-MM-DD or YYYYMMDD"
        ) from exc


def _symbol(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise TwseHistoricalCaptureError("official symbol is empty")
    return text


def _decimal(value: object, *, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TwseHistoricalCaptureError(f"{field_name} is missing")
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "-", "N/A"}:
        raise TwseHistoricalCaptureError(f"{field_name} is unavailable")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise TwseHistoricalCaptureError(f"{field_name} is not numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise TwseHistoricalCaptureError(f"{field_name} is not positive finite")
    return parsed


def _integer(value: object, *, field_name: str) -> int:
    if value is None or isinstance(value, bool):
        raise TwseHistoricalCaptureError(f"{field_name} is missing")
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "-", "N/A"}:
        raise TwseHistoricalCaptureError(f"{field_name} is unavailable")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise TwseHistoricalCaptureError(f"{field_name} is not numeric") from exc
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise TwseHistoricalCaptureError(f"{field_name} is not an integer")
    result = int(parsed)
    if result < 0:
        raise TwseHistoricalCaptureError(f"{field_name} is negative")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _normalise_official_row(
    raw: Mapping[str, object],
    *,
    position: int,
) -> dict[str, Any]:
    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        raise TwseHistoricalCaptureError(
            "official stock table is missing fields: " + ",".join(missing)
        )
    symbol = _symbol(raw.get("證券代號"))
    prices = {
        field: _decimal(
            raw.get(source_field),
            field_name=f"official row {position} {source_field}",
        )
        for field, source_field in (
            ("open", "開盤價"),
            ("high", "最高價"),
            ("low", "最低價"),
            ("close", "收盤價"),
        )
    }
    if prices["low"] > min(prices["open"], prices["close"]):
        raise TwseHistoricalCaptureError(
            f"official row {position} low is above open/close"
        )
    if prices["high"] < max(prices["open"], prices["close"]):
        raise TwseHistoricalCaptureError(
            f"official row {position} high is below open/close"
        )
    return {
        "symbol": symbol,
        "name": str(raw.get("證券名稱") or ""),
        "open": _decimal_text(prices["open"]),
        "high": _decimal_text(prices["high"]),
        "low": _decimal_text(prices["low"]),
        "close": _decimal_text(prices["close"]),
        "volume_shares": _integer(
            raw.get("成交股數"),
            field_name=f"official row {position} 成交股數",
        ),
        "unit": "price_1e4",
        "scale": 10_000,
    }


def _stock_table(
    payload: Mapping[str, object],
    *,
    requested_symbols: set[str] | None = None,
) -> tuple[dict[str, Any], ...]:
    if payload.get("stat") != "OK":
        raise TwseHistoricalCaptureError(
            f"official response stat is not OK: {payload.get('stat')}"
        )
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise TwseHistoricalCaptureError("official response tables are missing")
    selected: Mapping[str, object] | None = None
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        fields = table.get("fields")
        if isinstance(fields, list) and all(
            field in fields for field in ("證券代號", "收盤價")
        ):
            selected = table
            break
    if selected is None:
        raise TwseHistoricalCaptureError("official stock table is missing")
    fields = selected.get("fields")
    rows = selected.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise TwseHistoricalCaptureError("official stock table shape is invalid")
    field_names = tuple(str(field) for field in fields)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, list) or len(raw_row) != len(field_names):
            raise TwseHistoricalCaptureError(
                f"official stock row {position} has invalid field count"
            )
        mapped = dict(zip(field_names, raw_row))
        raw_symbol = str(mapped.get("證券代號") or "").strip()
        # MI_INDEX=ALL 包含停牌或無交易 row；非目標 row 的數值可能是
        # ``--``，不應令 33 個目標 row 的證據解析失敗。目標 row 仍須
        # 經完整數值與 OHLC invariants 驗證。
        if requested_symbols is not None and raw_symbol not in requested_symbols:
            continue
        normalized = _normalise_official_row(mapped, position=position)
        if normalized["symbol"] in seen:
            raise TwseHistoricalCaptureError(
                f"official stock table has duplicate symbol: {normalized['symbol']}"
            )
        seen.add(normalized["symbol"])
        result.append(normalized)
    return tuple(result)


def _decode_response(raw: bytes, *, content_encoding: str | None) -> bytes:
    encoding = (content_encoding or "").lower()
    if "gzip" in encoding or raw.startswith(b"\x1f\x8b"):
        try:
            return gzip.decompress(raw)
        except OSError as exc:
            raise TwseHistoricalCaptureError(
                "official gzip response cannot be decompressed"
            ) from exc
    return raw


def _read_json_payload(raw: bytes, *, content_encoding: str | None) -> tuple[dict[str, Any], bytes]:
    decoded = _decode_response(raw, content_encoding=content_encoding)
    try:
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TwseHistoricalCaptureError(
            "official response is not UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise TwseHistoricalCaptureError("official response JSON must be an object")
    return payload, decoded


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    output = path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != value:
            raise FileExistsError(
                f"immutable capture object exists with different content: {output}"
            )
        return
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (_canonical_json(dict(value)) + "\n").encode("utf-8"),
    )


def _required_hash(value: object, *, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if (
        len(text) != 71
        or not text.startswith(_SHA256_PREFIX)
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise TwseHistoricalCaptureError(f"{field_name} is not a sha256 digest")
    return text


def _safe_source_path(path: Path, *, output_root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise FileNotFoundError(resolved)
    output = output_root.resolve()
    if resolved == output or output in resolved.parents:
        raise TwseHistoricalCaptureError(
            "historical source must not be under capture output"
        )
    return resolved


def _reject_output_source_overlap(
    output_root: Path,
    *,
    source_roots: Sequence[Path],
) -> None:
    output = output_root.resolve()
    for source_root in source_roots:
        root = source_root.resolve()
        if output == root or root in output.parents or output in root.parents:
            raise TwseHistoricalCaptureError(
                "capture output must be outside all read-only source roots"
            )


def _read_sqlite_rows(
    sqlite_path: Path,
    *,
    date_iso: str,
    symbols: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    source = sqlite_path.resolve()
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(source)
    connection = sqlite3.connect(
        f"file:{source.as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in symbols)
        cursor = connection.execute(
            """
            SELECT 證券代號, 證券名稱, 開盤價, 最高價, 最低價, 收盤價, 成交股數
            FROM daily_prices
            WHERE 日期 = ? AND 證券代號 IN ("""
            + placeholders
            + ") ORDER BY 證券代號",
            (date_iso.replace("-", ""), *symbols),
        )
        result: list[dict[str, Any]] = []
        for row in cursor:
            try:
                prices = {
                    field: _decimal(
                        row[source_field],
                        field_name=f"sqlite {source_field}",
                    )
                    for field, source_field in (
                        ("open", "開盤價"),
                        ("high", "最高價"),
                        ("low", "最低價"),
                        ("close", "收盤價"),
                    )
                }
                volume = _integer(
                    row["成交股數"],
                    field_name="sqlite 成交股數",
                )
            except TwseHistoricalCaptureError:
                result.append(
                    {
                        "symbol": _symbol(row["證券代號"]),
                        "name": str(row["證券名稱"] or ""),
                        "open": row["開盤價"],
                        "high": row["最高價"],
                        "low": row["最低價"],
                        "close": row["收盤價"],
                        "volume_shares": row["成交股數"],
                        "unit": "price_1e4",
                        "scale": 10_000,
                        "row_valid": False,
                    }
                )
                continue
            result.append(
                {
                    "symbol": _symbol(row["證券代號"]),
                    "name": str(row["證券名稱"] or ""),
                    "open": _decimal_text(prices["open"]),
                    "high": _decimal_text(prices["high"]),
                    "low": _decimal_text(prices["low"]),
                    "close": _decimal_text(prices["close"]),
                    "volume_shares": volume,
                    "unit": "price_1e4",
                    "scale": 10_000,
                    "row_valid": True,
                }
            )
        return tuple(result)
    finally:
        connection.close()


def _row_differences(
    left: Mapping[str, object] | None,
    right: Mapping[str, object] | None,
) -> list[str]:
    if left is None or right is None:
        return list(_COMPARE_FIELDS)
    differences: list[str] = []
    for field in _COMPARE_FIELDS:
        left_value = left.get(field)
        right_value = right.get(field)
        if field == "volume_shares":
            try:
                equal = int(Decimal(str(left_value).replace(",", ""))) == int(
                    Decimal(str(right_value).replace(",", ""))
                )
            except (InvalidOperation, TypeError, ValueError):
                equal = left_value == right_value
        else:
            try:
                equal = Decimal(str(left_value).replace(",", "")) == Decimal(
                    str(right_value).replace(",", "")
                )
            except (InvalidOperation, TypeError, ValueError):
                equal = left_value == right_value
        if not equal:
            differences.append(field)
    return differences


def _source_file_reference(path: Path, *, output_root: Path) -> dict[str, Any]:
    resolved = _safe_source_path(path, output_root=output_root)
    return {
        "path": str(resolved),
        "file_sha256": _file_sha256(resolved),
        "bytes": resolved.stat().st_size,
    }


def _capture_id(date_iso: str, request_type: str, wire_hash: str) -> str:
    return (
        f"twse-mi-index-{date_iso.replace('-', '')}-"
        f"{request_type.lower()}-{wire_hash[7:23]}"
    )


def _load_existing_receipt(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TwseHistoricalCaptureError(
            f"existing receipt cannot be read: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise TwseHistoricalCaptureError("existing capture receipt is invalid")
    supplied = _required_hash(payload.get("receipt_hash"), field_name="receipt_hash")
    body = dict(payload)
    body.pop("receipt_hash", None)
    if _payload_hash(body) != supplied:
        raise TwseHistoricalCaptureError("existing receipt hash mismatch")
    return payload


def _download_wire_response(
    *,
    date_iso: str,
    request_type: str,
    timeout_seconds: float,
    response_path: Path,
) -> tuple[dict[str, Any], bytes, bytes]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    started = _aware_now()
    parameters = {
        "date": date_iso.replace("-", ""),
        "type": request_type,
        "response": "json",
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "technical-analysis-twse-historical-capture/1.0",
        "Referer": "https://www.twse.com.tw/",
    }
    try:
        with requests.Session() as session:
            response = session.get(
                TWSE_MI_INDEX_ENDPOINT,
                params=parameters,
                headers=headers,
                timeout=timeout_seconds,
                stream=True,
            )
            response.raw.decode_content = False
            chunks: list[bytes] = []
            total = 0
            while chunk := response.raw.read(_CHUNK_BYTES):
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    raise TwseHistoricalCaptureError(
                        "official response exceeds bounded capture size"
                    )
                chunks.append(bytes(chunk))
            raw = b"".join(chunks)
            completed = _aware_now()
            metadata: dict[str, Any] = {
                "request_started_at_utc": started.isoformat(),
                "response_completed_at_utc": completed.isoformat(),
                "source_url": response.url,
                "endpoint": TWSE_MI_INDEX_ENDPOINT,
                "request_parameters": dict(parameters),
                "request_headers": dict(headers),
                "http_status": int(response.status_code),
                "response_headers": {
                    str(key).lower(): str(value)
                    for key, value in response.headers.items()
                },
                "content_type": response.headers.get("Content-Type"),
                "content_encoding": response.headers.get("Content-Encoding"),
                "wire_response_bytes": len(raw),
                "wire_response_sha256": _hash_bytes(raw),
            }
            response.close()
    except requests.RequestException as exc:
        raise TwseHistoricalCaptureError(
            f"official TWSE request failed: {exc}"
        ) from exc
    if metadata["http_status"] != 200:
        raise TwseHistoricalCaptureError(
            f"official TWSE response HTTP {metadata['http_status']}"
        )
    _atomic_write_bytes(response_path, raw)
    decoded = _decode_response(
        raw,
        content_encoding=metadata.get("content_encoding"),
    )
    metadata["decoded_response_bytes"] = len(decoded)
    metadata["decoded_response_sha256"] = _hash_bytes(decoded)
    return metadata, raw, decoded


def _build_receipt(
    *,
    date_iso: str,
    request_type: str,
    metadata: Mapping[str, Any],
    response_path: Path,
    response_sha256: str,
    decoded_sha256: str,
    raw_payload: Mapping[str, Any],
    official_rows: Sequence[Mapping[str, Any]],
    source_files: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "status": "official_response_captured_historical_research",
        "source": "TWSE",
        "endpoint": TWSE_MI_INDEX_ENDPOINT,
        "date": date_iso,
        "request_type": request_type,
        "request": {
            "source_url": metadata["source_url"],
            "parameters": metadata["request_parameters"],
            "headers": metadata["request_headers"],
        },
        "response": {
            "http_status": metadata["http_status"],
            "content_type": metadata["content_type"],
            "content_encoding": metadata["content_encoding"],
            "response_headers": metadata["response_headers"],
            "wire_bytes": metadata["wire_response_bytes"],
            "wire_sha256": response_sha256,
            "decoded_bytes": metadata["decoded_response_bytes"],
            "decoded_sha256": decoded_sha256,
            "path": str(response_path.resolve()),
        },
        "capture_timing": {
            "request_started_at_utc": metadata["request_started_at_utc"],
            "response_completed_at_utc": metadata["response_completed_at_utc"],
            "historical_decision_time_available": False,
            "quality_known_at": metadata["response_completed_at_utc"],
        },
        "official_payload": {
            "stat": raw_payload.get("stat"),
            "payload_sha256": _payload_hash(raw_payload),
            "stock_row_count": len(official_rows),
        },
        "source_files": dict(source_files),
        "safety": {
            "read_only": True,
            "labels_mutated": False,
            "formal_training_allowed": False,
            "promotion_eligible": False,
            "historical_retroactive_filtering_allowed": False,
        },
        "official_rows": [dict(row) for row in official_rows],
    }
    body["receipt_hash"] = _payload_hash(body)
    return body


def capture_twse_historical_daily(
    *,
    sqlite_path: Path,
    canonical_daily_price_dir: Path,
    date_value: str,
    symbols: Sequence[str],
    output_root: Path,
    historical_backup_path: Path | None = None,
    request_type: str = "ALL",
    timeout_seconds: float = 30.0,
) -> TwseHistoricalCaptureResult:
    """取得一次官方 response，並建立 immutable response/receipt/comparison。"""

    date_iso = _normalise_date(date_value)
    normalized_symbols = tuple(
        sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})
    )
    if not normalized_symbols:
        raise ValueError("symbols must not be empty")
    normalized_type = str(request_type).strip().upper()
    if normalized_type not in {"ALL", "ALLBUT0999"}:
        raise ValueError("request_type must be ALL or ALLBUT0999")
    output = output_root.resolve()
    _reject_output_source_overlap(
        output,
        source_roots=(sqlite_path.parent, canonical_daily_price_dir)
        + (() if historical_backup_path is None else (historical_backup_path.parent,)),
    )
    output.mkdir(parents=True, exist_ok=True)
    sqlite_source = _safe_source_path(sqlite_path, output_root=output)
    canonical_source = canonical_daily_price_dir.resolve()
    if not canonical_source.is_dir() or canonical_source.is_symlink():
        raise FileNotFoundError(canonical_source)
    backup_source = (
        None
        if historical_backup_path is None
        else _safe_source_path(historical_backup_path, output_root=output)
    )

    # Capture into a temporary run directory first; the final directory is
    # content-addressed by the response hash and therefore reusable.
    temporary = output / f".capture-{os.getpid()}"
    temporary.mkdir(parents=True, exist_ok=True)
    temporary_response = temporary / "response.json.gz"
    metadata, raw_bytes, decoded_bytes = _download_wire_response(
        date_iso=date_iso,
        request_type=normalized_type,
        timeout_seconds=timeout_seconds,
        response_path=temporary_response,
    )
    raw_payload, _ = _read_json_payload(
        decoded_bytes,
        content_encoding=None,
    )
    official_rows = _stock_table(
        raw_payload,
        requested_symbols=set(normalized_symbols),
    )
    official_by_symbol = {str(row["symbol"]): row for row in official_rows}
    missing = sorted(set(normalized_symbols) - set(official_by_symbol))
    if missing:
        raise TwseHistoricalCaptureError(
            "official response misses requested symbols: " + ",".join(missing)
        )

    wire_hash = _hash_bytes(raw_bytes)
    capture_id = _capture_id(date_iso, normalized_type, wire_hash)
    capture_directory = output / "runs" / capture_id
    capture_directory.mkdir(parents=True, exist_ok=True)
    response_path = capture_directory / "response.json.gz"
    _atomic_write_bytes(response_path, raw_bytes)
    temporary_response.unlink(missing_ok=True)
    try:
        temporary.rmdir()
    except OSError:
        pass

    sqlite_rows = _read_sqlite_rows(
        sqlite_source,
        date_iso=date_iso,
        symbols=normalized_symbols,
    )
    sqlite_by_symbol = {str(row["symbol"]): row for row in sqlite_rows}
    canonical_rows, canonical_file = _canonical_csv_rows(
        canonical_source / f"{date_iso.replace('-', '')}.csv"
    )
    backup_rows: dict[str, dict[str, Any]] = {}
    backup_file: dict[str, Any] | None = None
    if backup_source is not None:
        backup_rows, backup_file = _canonical_csv_rows(backup_source)

    source_files: dict[str, Mapping[str, Any]] = {
        "sqlite": _source_file_reference(sqlite_source, output_root=output),
        "canonical_daily_csv": {
            **canonical_file,
            "path": str((canonical_source / f"{date_iso.replace('-', '')}.csv").resolve()),
        },
    }
    if backup_source is not None and backup_file is not None:
        source_files["historical_backup"] = {
            **backup_file,
            "path": str(backup_source),
            "bytes": backup_source.stat().st_size,
        }

    rows: list[dict[str, Any]] = []
    sqlite_matches = 0
    canonical_matches = 0
    backup_matches = 0
    for symbol in normalized_symbols:
        official = official_by_symbol[symbol]
        sqlite_row = sqlite_by_symbol.get(symbol)
        canonical_row = canonical_rows.get(symbol)
        backup_row = backup_rows.get(symbol)
        official_sqlite_diff = _row_differences(official, sqlite_row)
        official_canonical_diff = _row_differences(official, canonical_row)
        official_backup_diff = _row_differences(official, backup_row)
        if sqlite_row is not None and not official_sqlite_diff:
            sqlite_matches += 1
        if canonical_row is not None and not official_canonical_diff:
            canonical_matches += 1
        if backup_row is not None and not official_backup_diff:
            backup_matches += 1
        rows.append(
            {
                "symbol": symbol,
                "date": date_iso,
                "official_row": official,
                "sqlite_row": sqlite_row,
                "current_canonical_row": canonical_row,
                "historical_backup_row": backup_row,
                "official_vs_sqlite_differing_fields": official_sqlite_diff,
                "official_vs_current_canonical_differing_fields": official_canonical_diff,
                "official_vs_historical_backup_differing_fields": official_backup_diff,
                "correction_candidate": bool(official_sqlite_diff),
                "correction_status": "isolated_candidate_not_applied",
            }
        )

    receipt_path = capture_directory / "receipt.json"
    existing_receipt = _load_existing_receipt(receipt_path)
    receipt = (
        existing_receipt
        if existing_receipt is not None
        else _build_receipt(
            date_iso=date_iso,
            request_type=normalized_type,
            metadata=metadata,
            response_path=response_path,
            response_sha256=wire_hash,
            decoded_sha256=_hash_bytes(decoded_bytes),
            raw_payload=raw_payload,
            official_rows=official_rows,
            source_files=source_files,
        )
    )
    if _required_hash(receipt.get("response", {}).get("wire_sha256"), field_name="response wire_sha256") != wire_hash:
        raise TwseHistoricalCaptureError("existing receipt response hash mismatch")
    _atomic_write_json(receipt_path, receipt)

    comparison_body: dict[str, Any] = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": "official_historical_response_research_candidate",
        "source": "TWSE",
        "endpoint": TWSE_MI_INDEX_ENDPOINT,
        "date": date_iso,
        "requested_symbols": list(normalized_symbols),
        "capture": {
            "capture_id": capture_id,
            "capture_directory": str(capture_directory.resolve()),
            "response_path": str(response_path.resolve()),
            "response_sha256": wire_hash,
            "response_bytes": len(raw_bytes),
            "decoded_response_sha256": _hash_bytes(decoded_bytes),
            "receipt_path": str(receipt_path.resolve()),
            "receipt_hash": receipt["receipt_hash"],
            "captured_at_utc": receipt["capture_timing"][
                "response_completed_at_utc"
            ],
            "historical_decision_time_available": False,
        },
        "source_files": source_files,
        "verification": {
            "requested_symbol_count": len(normalized_symbols),
            "official_row_count": len(official_rows),
            "official_requested_rows_present": len(missing) == 0,
            "official_matches_sqlite_count": sqlite_matches,
            "official_matches_current_canonical_count": canonical_matches,
            "official_matches_historical_backup_count": backup_matches
            if backup_source is not None
            else None,
            "correction_candidate_count": sum(
                1 for row in rows if row["correction_candidate"]
            ),
        },
        "rows": rows,
        "safety": {
            "read_only": True,
            "labels_mutated": False,
            "formal_training_allowed": False,
            "promotion_eligible": False,
            "historical_retroactive_filtering_allowed": False,
        },
    }
    comparison_body["comparison_hash"] = _payload_hash(comparison_body)
    comparison_path = capture_directory / "comparison.json"
    _atomic_write_json(comparison_path, comparison_body)

    return TwseHistoricalCaptureResult(
        capture_directory=capture_directory,
        response_path=response_path,
        receipt_path=receipt_path,
        comparison_path=comparison_path,
        capture_id=capture_id,
        response_sha256=wire_hash,
        comparison_hash=str(comparison_body["comparison_hash"]),
        candidate_count=int(
            comparison_body["verification"]["correction_candidate_count"]
        ),
    )


def load_twse_capture(
    capture_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """讀回並驗證 immutable receipt/comparison；不讀任何 D source。"""

    root = capture_directory.resolve()
    receipt_path = root / "receipt.json"
    comparison_path = root / "comparison.json"
    receipt = _load_existing_receipt(receipt_path)
    if receipt is None:
        raise TwseHistoricalCaptureError("capture receipt is missing")
    try:
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TwseHistoricalCaptureError("capture comparison cannot be read") from exc
    if not isinstance(comparison, dict):
        raise TwseHistoricalCaptureError("capture comparison is invalid")
    supplied = _required_hash(
        comparison.get("comparison_hash"),
        field_name="comparison_hash",
    )
    body = dict(comparison)
    body.pop("comparison_hash", None)
    if _payload_hash(body) != supplied:
        raise TwseHistoricalCaptureError("capture comparison hash mismatch")
    response_path = Path(str(receipt["response"]["path"])).resolve()
    if not response_path.is_file() or _file_sha256(response_path) != receipt["response"]["wire_sha256"]:
        raise TwseHistoricalCaptureError("capture response custody mismatch")
    return receipt, comparison


__all__ = [
    "CAPTURE_SCHEMA_VERSION",
    "COMPARISON_SCHEMA_VERSION",
    "TWSE_MI_INDEX_ENDPOINT",
    "TwseHistoricalCaptureError",
    "TwseHistoricalCaptureResult",
    "capture_twse_historical_daily",
    "load_twse_capture",
]
