"""建立與讀取隔離的 daily price candidate overlay。

overlay 只供研究 consumer 重新讀取 canonical CSV 的候選 row；它不修改
SQLite、daily CSV、feature 或 label。canonical CSV 的 producer contract 可
追溯到 TWSE MI_INDEX，但本專案沒有保存該次 HTTP response receipt，因此本
未提供官方 capture 時，lineage 標成 ``candidate_only``；若提供已驗證的
historical response comparison，模組會把 response／receipt hash 綁入新 overlay，
但仍保留事後擷取與不可訓練／不可 promotion 語意，不把 canonical 名稱當成官方真值。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from data_module.ml_daily_price_source_quality import (
    SOURCE_QUALITY_SCHEMA_VERSION,
    audit_daily_price_source,
)
from data_module.twse_historical_daily_capture import (
    COMPARISON_SCHEMA_VERSION,
    load_twse_capture,
)


OVERLAY_SCHEMA_VERSION = "portfolio-ml-daily-price-candidate-overlay.v1"
_SHA256_PREFIX = "sha256:"
_TWSE_MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"


class DailyPriceOverlayError(ValueError):
    """隔離 overlay 的來源、hash 或內容驗證失敗。"""


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


def _normalise_date(value: str) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date.fromisoformat(
            f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        ).isoformat()
    return date.fromisoformat(text).isoformat()


def _required_hash(value: object, *, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if (
        len(text) != 71
        or not text.startswith(_SHA256_PREFIX)
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise DailyPriceOverlayError(f"{field_name} must be a sha256 digest")
    return text


def _numeric_differences(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> list[str]:
    fields = ("open", "high", "low", "close", "volume_shares")
    if left is None or right is None:
        return list(fields)
    differences: list[str] = []
    for field in fields:
        try:
            left_number = Decimal(str(left.get(field)).replace(",", ""))
            right_number = Decimal(str(right.get(field)).replace(",", ""))
            equal = left_number == right_number
        except (InvalidOperation, TypeError, ValueError):
            equal = left.get(field) == right.get(field)
        if not equal:
            differences.append(field)
    return differences


def _load_official_capture_binding(
    path: Path,
    *,
    date_iso: str,
    symbols: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    comparison_path = path.resolve()
    if comparison_path.name != "comparison.json":
        raise DailyPriceOverlayError(
            "official capture path must be its immutable comparison.json"
        )
    try:
        receipt, comparison = load_twse_capture(comparison_path.parent)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise DailyPriceOverlayError(
            "official historical capture cannot be verified"
        ) from exc
    if comparison.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        raise DailyPriceOverlayError("unsupported official capture comparison schema")
    if comparison.get("date") != date_iso:
        raise DailyPriceOverlayError("official capture date mismatch")
    raw_symbols = comparison.get("requested_symbols")
    if tuple(raw_symbols or ()) != symbols:
        raise DailyPriceOverlayError("official capture symbol scope mismatch")
    capture = comparison.get("capture")
    verification = comparison.get("verification")
    if not isinstance(capture, Mapping) or not isinstance(verification, Mapping):
        raise DailyPriceOverlayError("official capture metadata is invalid")
    if (
        verification.get("official_requested_rows_present") is not True
        or verification.get("official_row_count") != len(symbols)
        or verification.get("official_matches_current_canonical_count")
        != len(symbols)
    ):
        raise DailyPriceOverlayError(
            "official capture does not verify every canonical candidate row"
        )
    if capture.get("historical_decision_time_available") is not False:
        raise DailyPriceOverlayError(
            "official historical capture cannot be treated as decision-time data"
        )
    rows = comparison.get("rows")
    if not isinstance(rows, list) or len(rows) != len(symbols):
        raise DailyPriceOverlayError("official capture rows are incomplete")
    for row in rows:
        if not isinstance(row, Mapping):
            raise DailyPriceOverlayError("official capture row is invalid")
        if _numeric_differences(
            row.get("official_row") if isinstance(row.get("official_row"), Mapping) else None,
            row.get("current_canonical_row")
            if isinstance(row.get("current_canonical_row"), Mapping)
            else None,
        ):
            raise DailyPriceOverlayError(
                "official capture canonical row binding mismatch"
            )
    return (
        {
            "comparison_path": str(comparison_path),
            "comparison_hash": _required_hash(
                comparison.get("comparison_hash"),
                field_name="official comparison_hash",
            ),
            "receipt_hash": _required_hash(
                receipt.get("receipt_hash"),
                field_name="official receipt_hash",
            ),
            "response_sha256": _required_hash(
                capture.get("response_sha256"),
                field_name="official response_sha256",
            ),
            "captured_at_utc": capture.get("captured_at_utc"),
            "historical_decision_time_available": False,
            "verified_row_count": len(rows),
        },
        {str(row["symbol"]): dict(row["official_row"]) for row in rows},
        comparison_path.parent,
    )


def _read_overlay(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DailyPriceOverlayError("overlay JSON cannot be read") from exc
    if not isinstance(payload, dict):
        raise DailyPriceOverlayError("overlay must be a JSON object")
    supplied_hash = _required_hash(payload.get("overlay_hash"), field_name="overlay_hash")
    body = dict(payload)
    body.pop("overlay_hash", None)
    if _payload_hash(body) != supplied_hash:
        raise DailyPriceOverlayError("overlay_hash mismatch")
    if payload.get("schema_version") != OVERLAY_SCHEMA_VERSION:
        raise DailyPriceOverlayError("unsupported overlay schema")
    if payload.get("status") != "candidate_only_research_overlay":
        raise DailyPriceOverlayError("overlay is not candidate-only")
    if payload.get("labels_mutated") is not False:
        raise DailyPriceOverlayError("overlay must not mutate labels")
    return payload


def _write_overlay(
    path: Path,
    body: Mapping[str, Any],
    *,
    source_roots: Sequence[Path],
) -> Path:
    output = path.resolve()
    for source_root in source_roots:
        resolved_root = source_root.resolve()
        if output == resolved_root or resolved_root in output.parents:
            raise DailyPriceOverlayError("overlay output must be outside source roots")
    encoded = (_canonical_json(dict(body)) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != encoded:
            raise FileExistsError(
                f"overlay already exists with different content: {output}"
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


def build_daily_price_overlay(
    *,
    sqlite_path: Path,
    canonical_daily_price_dir: Path,
    date_value: str,
    symbols: Sequence[str],
    output_path: Path,
    source_manifest_hash: str | None = None,
    official_capture_comparison_path: Path | None = None,
) -> Path:
    """建立隔離 candidate overlay，並以原子方式保存到 repo output。"""

    date_iso = _normalise_date(date_value)
    expected_symbols = tuple(sorted({str(item).strip() for item in symbols if str(item).strip()}))
    if not expected_symbols:
        raise DailyPriceOverlayError("symbols must not be empty")
    source_report = audit_daily_price_source(
        sqlite_path=sqlite_path,
        canonical_daily_price_dir=canonical_daily_price_dir,
        start_date=date_iso,
        end_date=date_iso,
        symbols=expected_symbols,
        source_manifest_hash=source_manifest_hash,
        quality_mode="ingest_guard",
    )
    candidates = source_report.get("candidates")
    if not isinstance(candidates, list):
        raise DailyPriceOverlayError("source quality candidates are invalid")
    by_symbol = {
        str(candidate.get("symbol")): candidate
        for candidate in candidates
        if isinstance(candidate, Mapping)
    }
    if tuple(sorted(by_symbol)) != expected_symbols:
        raise DailyPriceOverlayError(
            "overlay requires one canonical candidate row for every requested symbol"
        )

    official_binding: dict[str, Any] | None = None
    official_rows: dict[str, dict[str, Any]] = {}
    official_capture_directory: Path | None = None
    if official_capture_comparison_path is not None:
        (
            official_binding,
            official_rows,
            official_capture_directory,
        ) = _load_official_capture_binding(
            official_capture_comparison_path,
            date_iso=date_iso,
            symbols=expected_symbols,
        )

    rows: list[dict[str, Any]] = []
    canonical_file_hashes: dict[str, str] = {}
    for symbol in expected_symbols:
        candidate = by_symbol[symbol]
        canonical = candidate.get("canonical_row")
        canonical_file = candidate.get("canonical_file")
        if not isinstance(canonical, Mapping) or not isinstance(canonical_file, Mapping):
            raise DailyPriceOverlayError(
                f"canonical row/file is unavailable for {symbol}"
            )
        file_hash = _required_hash(
            canonical_file.get("file_sha256"),
            field_name=f"canonical_file[{symbol}].file_sha256",
        )
        canonical_file_hashes[str(canonical_file.get("path"))] = file_hash
        row_payload: dict[str, Any] = {
                "symbol": symbol,
                "date": date_iso,
                "original_sqlite": candidate.get("sqlite_row"),
                "overlay_row": dict(canonical),
                "differing_fields": list(candidate.get("differing_fields", [])),
                "classification": candidate.get("classification"),
                "canonical_file": {
                    "path": str(canonical_file.get("path")),
                    "file_sha256": file_hash,
                },
            }
        if official_binding is not None:
            row_payload["official_row"] = official_rows[symbol]
        rows.append(row_payload)

    body: dict[str, Any] = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "status": "candidate_only_research_overlay",
        "read_only": True,
        "labels_mutated": False,
        "repair_performed": False,
        "formal_training_allowed": False,
        "promotion_eligible": False,
        "scope": {
            "date": date_iso,
            "symbols": list(expected_symbols),
            "row_count": len(rows),
        },
        "source_quality": {
            "schema_version": SOURCE_QUALITY_SCHEMA_VERSION,
            "report_hash": source_report.get("report_hash"),
            "quality_mode": "ingest_guard",
            "future_source_rows_used": False,
            "quality_known_at": source_report.get("quality_timing", {}).get(
                "quality_known_at"
            ),
        },
        "source_lineage": {
            "sqlite_path": str(sqlite_path.resolve()),
            "canonical_daily_price_dir": str(canonical_daily_price_dir.resolve()),
            "canonical_file_hashes": dict(sorted(canonical_file_hashes.items())),
            "producer_contract": {
                "producer": "data_module.data_loader.DataLoader.download_from_api",
                "endpoint": _TWSE_MI_INDEX_URL,
                "request_types": ["ALL", "ALLBUT0999"],
                "response": "json",
                "row_table_selection": "fields contain 證券代號 and 收盤價",
                "numeric_mapping": "TWSE field names preserved; no price rescaling",
            },
            "official_raw_response_receipt_present": official_binding is not None,
            "lineage_status": (
                "official_historical_response_receipt_bound_candidate_only"
                if official_binding is not None
                else "candidate_only_contract_lineage_raw_response_receipt_missing"
            ),
        },
        "rows": rows,
        "verification": {
            "requested_symbol_count": len(expected_symbols),
            "overlay_row_count": len(rows),
            "all_requested_symbols_present": True,
            "all_rows_have_canonical_file_hash": True,
            "consumer_mode": "isolated_overlay_read_only",
        },
    }
    if official_binding is not None:
        body["official_capture"] = official_binding
    body["overlay_hash"] = _payload_hash(body)
    output = output_path.resolve()
    _write_overlay(
        output,
        body,
        source_roots=(
            sqlite_path.parent,
            canonical_daily_price_dir,
            *((official_capture_directory,) if official_capture_directory else ()),
        ),
    )
    return output


def load_daily_price_overlay(path: Path) -> dict[str, Any]:
    """讀取並驗證隔離 overlay；不觸碰原 SQLite/CSV。"""

    return _read_overlay(path.resolve())


def overlay_rows(path: Path, *, date_value: str | None = None) -> tuple[dict[str, Any], ...]:
    """提供 consumer 使用的 canonical candidate rows。"""

    payload = load_daily_price_overlay(path)
    scope = payload.get("scope")
    if not isinstance(scope, Mapping):
        raise DailyPriceOverlayError("overlay scope is invalid")
    expected_date = (
        _normalise_date(date_value) if date_value is not None else str(scope.get("date"))
    )
    if expected_date != scope.get("date"):
        raise DailyPriceOverlayError("overlay date mismatch")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise DailyPriceOverlayError("overlay rows are invalid")
    return tuple(dict(row) for row in raw_rows if isinstance(row, Mapping))


__all__ = [
    "DailyPriceOverlayError",
    "OVERLAY_SCHEMA_VERSION",
    "build_daily_price_overlay",
    "load_daily_price_overlay",
    "overlay_rows",
]
