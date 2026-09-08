"""唯讀追查 Direct label 極值的來源、時間與公司行動 custody。

本工具只掃描既有 immutable Direct numeric artifacts，先以 chunked memmap
找指定 horizon／label 的最大列，再以該列的 rows/replay 與可選的原始
SQLite／PIT shard 交叉核對。它不截斷、修正或重建 label，也不把未解決的
來源異常當成績效證據。
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_direct_shared_block_resolver import (  # noqa: E402
    resolve_direct_numeric_artifact,
)
from data_module.portfolio_ml_out_of_core_store import (  # noqa: E402
    LABEL_FIELDS,
)


_SHA256_PREFIX = "sha256:"
_DIRECT_SCHEMA = "portfolio-ml-ooc-store.v3"
_YEAR_SCHEMA = "portfolio-ml-ooc-year.v3"
_DEFAULT_CHUNK_ROWS = 65_536


class LabelExtremeAuditError(ValueError):
    """來源 custody、schema 或 label 極值核對失敗。"""


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


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LabelExtremeAuditError(f"JSON object cannot be read: {path}") from exc
    if not isinstance(payload, dict):
        raise LabelExtremeAuditError(f"JSON object required: {path}")
    return payload


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LabelExtremeAuditError(f"{field_name} must be non-empty text")
    return value


def _required_int(value: object, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LabelExtremeAuditError(
            f"{field_name} must be integer >= {minimum}"
        )
    return value


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as exc:
        raise LabelExtremeAuditError(f"source file cannot be read: {path}") from exc
    return _SHA256_PREFIX + digest.hexdigest()


def _verify_manifest_hash(
    payload: Mapping[str, Any],
    *,
    field_name: str = "manifest_hash",
) -> str:
    supplied = _required_text(payload.get(field_name), field_name=field_name)
    if not supplied.startswith(_SHA256_PREFIX) or len(supplied) != 71:
        raise LabelExtremeAuditError(f"{field_name} is not a sha256 digest")
    body = dict(payload)
    body.pop(field_name, None)
    if _payload_hash(body) != supplied:
        raise LabelExtremeAuditError(f"{field_name} mismatch")
    return supplied


def _artifact_entries(year_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = year_manifest.get("artifacts")
    if not isinstance(raw, list):
        raise LabelExtremeAuditError("year artifacts must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise LabelExtremeAuditError("year artifact must be an object")
        artifact_id = item.get("artifact_id")
        if artifact_id is None and isinstance(item.get("path"), str):
            artifact_id = Path(str(item["path"])).name
        if not isinstance(artifact_id, str) or artifact_id in result:
            raise LabelExtremeAuditError("year artifact id is invalid")
        result[artifact_id] = item
    for required in (
        "labels.i32",
        "labels.masks.u8",
        "rows.sqlite",
        "replay_source.sqlite",
    ):
        if required not in result:
            raise LabelExtremeAuditError(f"year artifact missing: {required}")
    return result


def _resolve_artifact(
    entry: Mapping[str, Any],
    *,
    year_directory: Path,
    shared_numeric_store_root: Path | None,
) -> Path:
    if entry.get("storage") == "immutable_shared":
        if shared_numeric_store_root is None:
            raise LabelExtremeAuditError(
                "shared_numeric_store_root is required for shared artifact"
            )
        try:
            return resolve_direct_numeric_artifact(
                entry,
                shared_store_root=shared_numeric_store_root,
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise LabelExtremeAuditError("shared artifact custody failed") from exc
    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise LabelExtremeAuditError("local artifact path is missing")
    relative = Path(raw_path)
    root = year_directory.resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts:
        raise LabelExtremeAuditError("local artifact path escapes year directory")
    if path != root and root not in path.parents:
        raise LabelExtremeAuditError("local artifact path escapes year directory")
    if path.is_symlink() or not path.is_file():
        raise LabelExtremeAuditError(f"local artifact is missing: {path}")
    expected_bytes = _required_int(
        entry.get("byte_count"),
        field_name="artifact.byte_count",
    )
    if path.stat().st_size != expected_bytes:
        raise LabelExtremeAuditError(f"artifact bytes mismatch: {path.name}")
    expected_hash = _required_text(
        entry.get("file_sha256"),
        field_name="artifact.file_sha256",
    )
    if _file_hash(path) != expected_hash:
        raise LabelExtremeAuditError(f"artifact hash mismatch: {path.name}")
    return path


def _open_ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise LabelExtremeAuditError(f"SQLite source is missing: {path}")
    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
        )
    except sqlite3.Error as exc:
        raise LabelExtremeAuditError(f"SQLite source cannot be opened: {path}") from exc
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _row_by_index(path: Path, table: str, local_row_index: int) -> dict[str, Any]:
    connection = _open_ro(path)
    try:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE local_row_index=?",
            (local_row_index,),
        ).fetchone()
        if row is None:
            raise LabelExtremeAuditError(
                f"{table} row is missing: {local_row_index}"
            )
        return {str(key): row[key] for key in row.keys()}
    finally:
        connection.close()


def _date_key(value: str) -> str:
    return value.replace("-", "")[:8]


def _iso_date(value: str) -> str:
    key = _date_key(value)
    try:
        return date(
            int(key[:4]),
            int(key[4:6]),
            int(key[6:8]),
        ).isoformat()
    except (ValueError, TypeError) as exc:
        raise LabelExtremeAuditError(f"invalid date: {value}") from exc


def _decimal(value: object, *, field_name: str) -> Decimal:
    if value is None:
        raise LabelExtremeAuditError(f"{field_name} is null")
    try:
        parsed = Decimal(str(value).replace(",", ""))
    except Exception as exc:  # Decimal raises several concrete subclasses.
        raise LabelExtremeAuditError(f"{field_name} is not numeric") from exc
    if not parsed.is_finite():
        raise LabelExtremeAuditError(f"{field_name} is not finite")
    return parsed


def _return_bp(entry: Decimal, exit_value: Decimal) -> int:
    if entry <= 0:
        raise LabelExtremeAuditError("entry price must be positive")
    return int(
        (((exit_value / entry) - Decimal(1)) * Decimal(10_000)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _scan_label_extreme(
    manifest_path: Path,
    *,
    horizon: int,
    field_name: str,
    shared_numeric_store_root: Path | None,
    chunk_rows: int,
) -> dict[str, Any]:
    manifest = _read_object(manifest_path)
    if manifest.get("schema_version") != _DIRECT_SCHEMA:
        raise LabelExtremeAuditError("Direct manifest schema mismatch")
    if manifest.get("status") != "complete":
        raise LabelExtremeAuditError("Direct manifest is not complete")
    manifest_hash = _verify_manifest_hash(manifest)
    horizons = manifest.get("horizons")
    if not isinstance(horizons, list) or horizon not in horizons:
        raise LabelExtremeAuditError("requested horizon is not in manifest")
    if field_name not in LABEL_FIELDS:
        raise LabelExtremeAuditError("requested label field is not supported")
    field_position = LABEL_FIELDS.index(field_name)
    horizon_position = horizons.index(horizon)
    best: tuple[int, int, int, Path, Path, Path] | None = None
    selected_year: dict[str, Any] | None = None
    selected_entries: dict[str, Mapping[str, Any]] | None = None
    selected_year_directory: Path | None = None
    for raw_year in manifest.get("years", []):
        if not isinstance(raw_year, Mapping):
            raise LabelExtremeAuditError("Direct manifest year is invalid")
        year = _required_int(raw_year.get("year"), field_name="year", minimum=1900)
        row_count = _required_int(
            raw_year.get("row_count"),
            field_name=f"year {year}.row_count",
        )
        year_directory = manifest_path.parent / f"year={year:04d}"
        year_manifest_path = year_directory / "manifest.json"
        year_manifest = _read_object(year_manifest_path)
        if year_manifest.get("schema_version") != _YEAR_SCHEMA:
            raise LabelExtremeAuditError(f"year {year} schema mismatch")
        year_hash = _verify_manifest_hash(year_manifest)
        declared_year_hash = raw_year.get("manifest_hash")
        if declared_year_hash is not None and declared_year_hash != year_hash:
            raise LabelExtremeAuditError(f"year {year} manifest hash mismatch")
        entries = _artifact_entries(year_manifest)
        labels_path = _resolve_artifact(
            entries["labels.i32"],
            year_directory=year_directory,
            shared_numeric_store_root=shared_numeric_store_root,
        )
        masks_path = _resolve_artifact(
            entries["labels.masks.u8"],
            year_directory=year_directory,
            shared_numeric_store_root=shared_numeric_store_root,
        )
        labels = np.memmap(
            labels_path,
            mode="r",
            dtype="<i4",
            shape=(row_count, len(horizons), len(LABEL_FIELDS)),
        )
        masks = np.memmap(
            masks_path,
            mode="r",
            dtype="u1",
            shape=(row_count, len(horizons), len(LABEL_FIELDS)),
        )
        for start in range(0, row_count, chunk_rows):
            end = min(row_count, start + chunk_rows)
            values = np.asarray(labels[start:end, horizon_position, field_position])
            valid = np.asarray(masks[start:end, horizon_position, field_position]) == 0
            if not np.any(valid):
                continue
            candidates = values.copy()
            candidates[~valid] = np.iinfo(np.int32).min
            local_offset = int(np.argmax(candidates))
            candidate = int(candidates[local_offset])
            local_index = start + local_offset
            key = (candidate, -year, -local_index)
            if best is None or key > (best[0], -best[1], -best[2]):
                best = (
                    candidate,
                    year,
                    local_index,
                    labels_path,
                    masks_path,
                    year_manifest_path,
                )
                selected_year = dict(year_manifest)
                selected_entries = entries
                selected_year_directory = year_directory
        del labels, masks
    if best is None or selected_year is None or selected_entries is None:
        raise LabelExtremeAuditError("no observed label rows selected")
    assert selected_year_directory is not None
    row_index = best[2]
    rows_path = _resolve_artifact(
        selected_entries["rows.sqlite"],
        year_directory=selected_year_directory,
        shared_numeric_store_root=shared_numeric_store_root,
    )
    replay_path = _resolve_artifact(
        selected_entries["replay_source.sqlite"],
        year_directory=selected_year_directory,
        shared_numeric_store_root=shared_numeric_store_root,
    )
    row = _row_by_index(rows_path, "rows", row_index)
    replay = _row_by_index(replay_path, "replay_source", row_index)
    return {
        "manifest_hash": manifest_hash,
        "manifest_file_hash": _file_hash(manifest_path),
        "year": best[1],
        "year_manifest_hash": _verify_manifest_hash(selected_year),
        "local_row_index": row_index,
        "label_field": field_name,
        "horizon": horizon,
        "label_value_bp": best[0],
        "rows": row,
        "replay_source": replay,
        "source": manifest.get("source_manifest_hashes"),
        "training_as_of": manifest.get("training_as_of"),
    }


def _source_db_evidence(
    source_db: Path,
    *,
    symbol: str,
    decision_date: str,
    horizon: int,
    benchmark_entity: str,
) -> dict[str, Any]:
    connection = _open_ro(source_db)
    try:
        start_key = _date_key(decision_date)
        stock_rows = connection.execute(
            "SELECT 日期, 證券代號, 開盤價, 最高價, 最低價, 收盤價, 成交股數 "
            "FROM daily_prices WHERE 證券代號=? ORDER BY 日期",
            (symbol,),
        ).fetchall()
        stock_by_date = {
            _date_key(str(row[0])): {
                "date": str(row[0]),
                "symbol": str(row[1]),
                "open": row[2],
                "high": row[3],
                "low": row[4],
                "close": row[5],
                "volume": row[6],
            }
            for row in stock_rows
        }
        market_rows = connection.execute(
            "SELECT 日期, 指數名稱, 開盤價, 最高價, 最低價, 收盤價 "
            "FROM market_indices WHERE 指數名稱=? ORDER BY 日期",
            (benchmark_entity,),
        ).fetchall()
        market_by_date = {
            _date_key(str(row[0])): {
                "date": str(row[0]),
                "entity": str(row[1]),
                "open": row[2],
                "high": row[3],
                "low": row[4],
                "close": row[5],
            }
            for row in market_rows
        }
        dates = sorted(day for day in market_by_date if day >= start_key)
        if start_key not in market_by_date or len(dates) < horizon:
            raise LabelExtremeAuditError(
                "source DB lacks the benchmark session range for h20 audit"
            )
        end_key = dates[horizon - 1]
        start_stock = stock_by_date.get(start_key)
        end_stock = stock_by_date.get(end_key)
        start_market = market_by_date[start_key]
        end_market = market_by_date[end_key]
        if start_stock is None or end_stock is None:
            raise LabelExtremeAuditError("source DB lacks selected stock prices")
        stock_dates = sorted(stock_by_date)
        start_position = stock_dates.index(start_key)
        stock_context = {
            "previous": (
                stock_by_date[stock_dates[start_position - 1]]
                if start_position > 0
                else None
            ),
            "decision": start_stock,
            "next": (
                stock_by_date[stock_dates[start_position + 1]]
                if start_position + 1 < len(stock_dates)
                else None
            ),
        }
        stock_return_bp = _return_bp(
            _decimal(start_stock["open"], field_name="stock entry open"),
            _decimal(end_stock["close"], field_name="stock exit close"),
        )
        benchmark_return_bp = _return_bp(
            _decimal(start_market["open"], field_name="benchmark entry open"),
            _decimal(end_market["close"], field_name="benchmark exit close"),
        )
        price_scale_discontinuity = False
        previous = stock_context["previous"]
        following = stock_context["next"]
        if previous is not None and following is not None:
            previous_close = _decimal(
                previous["close"],
                field_name="stock previous close",
            )
            entry_open = _decimal(
                start_stock["open"],
                field_name="stock decision open",
            )
            next_open = _decimal(
                following["open"],
                field_name="stock next open",
            )
            # 這只是來源品質的可重現診斷旗標，不是修正或截斷規則。
            price_scale_discontinuity = (
                entry_open * Decimal(10) < previous_close
                and next_open > entry_open * Decimal(10)
            )
        return {
            "decision_date": decision_date,
            "horizon_end_date": _iso_date(end_key),
            "stock": {"entry": start_stock, "exit": end_stock},
            "stock_context": stock_context,
            "benchmark": {
                "entry": start_market,
                "exit": end_market,
                "session_count": horizon,
            },
            "stock_return_bp": stock_return_bp,
            "benchmark_return_bp": benchmark_return_bp,
            "transaction_cost_bp": 80,
            "reconstructed_excess_return_bp": (
                stock_return_bp - benchmark_return_bp - 80
            ),
            "price_scale_discontinuity_detected": price_scale_discontinuity,
        }
    finally:
        connection.close()


def _raw_shard_evidence(
    raw_shard: Path,
    *,
    symbol: str,
    dates: set[str],
) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    try:
        with gzip.open(raw_shard, "rt", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise LabelExtremeAuditError(
                        f"raw shard JSON is invalid at line {line_number}"
                    ) from exc
                if not isinstance(payload, Mapping):
                    continue
                if payload.get("source_table") != "daily_prices":
                    continue
                if str(payload.get("entity_id")) != symbol:
                    continue
                event_date = str(payload.get("event_at", ""))[:10]
                if event_date not in dates:
                    continue
                values = payload.get("values")
                if not isinstance(values, list):
                    continue
                entry = result.setdefault(
                    event_date,
                    {
                        "event_at": payload.get("event_at"),
                        "available_at": payload.get("available_at"),
                        "source_row_hash": payload.get("source_row_hash"),
                        "values": {},
                    },
                )
                for value in values:
                    if not isinstance(value, Mapping):
                        continue
                    feature_id = value.get("feature_id")
                    if isinstance(feature_id, str) and feature_id in {
                        "daily_prices.開盤價",
                        "daily_prices.收盤價",
                        "daily_prices.最高價",
                        "daily_prices.最低價",
                    }:
                        entry["values"][feature_id] = {
                            "value_int": value.get("value_int"),
                            "scale": value.get("scale"),
                            "source_value_hash": value.get("source_value_hash"),
                        }
    except OSError as exc:
        raise LabelExtremeAuditError(f"raw shard cannot be read: {raw_shard}") from exc
    return {
        "file_hash": _file_hash(raw_shard),
        "symbol": symbol,
        "dates": sorted(result),
        "rows": result,
    }


def _corporate_action_evidence(
    manifest_path: Path,
    *,
    symbol: str,
    decision_date: str,
    horizon_end_date: str,
) -> dict[str, Any]:
    publication = _read_object(manifest_path)
    manifest_hash = _verify_manifest_hash(publication)
    canonical = publication.get("canonical_events")
    if not isinstance(canonical, Mapping):
        raise LabelExtremeAuditError("corporate action canonical metadata is missing")
    relative = _required_text(canonical.get("path"), field_name="canonical_events.path")
    path = (manifest_path.parent / relative).resolve()
    root = manifest_path.parent.resolve()
    if path != root and root not in path.parents:
        raise LabelExtremeAuditError("corporate action path escapes publication")
    expected_hash = _required_text(
        canonical.get("file_hash"),
        field_name="canonical_events.file_hash",
    )
    actual_hash = _file_hash(path)
    if actual_hash != expected_hash:
        raise LabelExtremeAuditError("corporate action canonical hash mismatch")
    interval_start = _iso_date(decision_date)
    interval_end = _iso_date(horizon_end_date)
    if interval_start > interval_end:
        raise LabelExtremeAuditError("corporate action interval is reversed")
    matched: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, Mapping) or str(record.get("symbol")) != symbol:
                    continue
                effective = _iso_date(str(record.get("effective_at", "")))
                if interval_start <= effective <= interval_end:
                    matched.append(dict(record))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LabelExtremeAuditError(
            "corporate action canonical events cannot be read"
        ) from exc
    return {
        "publication_manifest_hash": manifest_hash,
        "publication_manifest_file_hash": _file_hash(manifest_path),
        "canonical_events_hash": actual_hash,
        "symbol": symbol,
        "interval": {
            "start": interval_start,
            "end": interval_end,
        },
        "matching_events": matched,
    }


def audit_label_extreme(
    manifest_path: Path,
    *,
    source_db: Path | None = None,
    raw_shard: Path | None = None,
    corporate_action_manifest: Path | None = None,
    horizon: int = 20,
    field_name: str = "benchmark_excess_return_bp",
    benchmark_entity: str = "TAIEX",
    shared_numeric_store_root: Path | None = None,
    chunk_rows: int = _DEFAULT_CHUNK_ROWS,
) -> dict[str, Any]:
    if horizon <= 0 or chunk_rows <= 0:
        raise LabelExtremeAuditError("horizon and chunk_rows must be positive")
    selected = _scan_label_extreme(
        manifest_path.resolve(),
        horizon=horizon,
        field_name=field_name,
        shared_numeric_store_root=(
            None
            if shared_numeric_store_root is None
            else shared_numeric_store_root.resolve()
        ),
        chunk_rows=chunk_rows,
    )
    row = selected["rows"]
    decision_date = str(row["decision_date"])
    symbol = str(row["symbol"])
    report: dict[str, Any] = {
        "schema_version": "portfolio-ml-label-extreme-audit.v1",
        "status": "complete",
        "read_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "do_not_clip_or_retrain": True,
        "selection": selected,
    }
    if source_db is not None:
        source = _source_db_evidence(
            source_db.resolve(),
            symbol=symbol,
            decision_date=decision_date,
            horizon=horizon,
            benchmark_entity=benchmark_entity,
        )
        report["source_db_evidence"] = source
        date_keys = sorted(
            {
                _date_key(decision_date),
                _date_key(source["horizon_end_date"]),
                _date_key(
                    str(
                        (
                            source["stock_context"].get("previous")
                            or {}
                        ).get("date", decision_date)
                    )
                ),
                _date_key(
                    str(
                        (source["stock_context"].get("next") or {}).get(
                            "date", decision_date
                        )
                    )
                ),
            }
        )
        if raw_shard is not None:
            report["raw_shard_evidence"] = _raw_shard_evidence(
                raw_shard.resolve(),
                symbol=symbol,
                dates={
                    value[:4] + "-" + value[4:6] + "-" + value[6:]
                    for value in date_keys
                },
            )
    elif raw_shard is not None:
        report["raw_shard_evidence"] = _raw_shard_evidence(
            raw_shard.resolve(),
            symbol=symbol,
            dates={decision_date},
        )
    if corporate_action_manifest is not None:
        horizon_end = str(
            report.get("source_db_evidence", {}).get(
                "horizon_end_date",
                row.get("max_horizon_end_date", decision_date),
            )
        )
        report["corporate_action_evidence"] = _corporate_action_evidence(
            corporate_action_manifest.resolve(),
            symbol=symbol,
            decision_date=decision_date,
            horizon_end_date=horizon_end,
        )
    source_evidence = report.get("source_db_evidence")
    matching_events = report.get("corporate_action_evidence", {}).get(
        "matching_events",
        [],
    )
    reconstruction_matches = None
    if isinstance(source_evidence, Mapping):
        reconstruction_matches = int(
            source_evidence.get("reconstructed_excess_return_bp", 0)
        ) == int(selected["label_value_bp"])
        report["reconstruction_matches_label"] = reconstruction_matches
    if reconstruction_matches is False:
        classification = "source_reconstruction_mismatch"
    elif isinstance(source_evidence, Mapping) and source_evidence.get(
        "price_scale_discontinuity_detected"
    ) is True:
        classification = "source_price_scale_anomaly_unresolved"
    elif matching_events:
        classification = "corporate_action_interval_requires_label_exclusion_review"
    else:
        classification = "label_extreme_requires_source_review"
    report["classification"] = classification
    report["audit_conclusion"] = (
        "保留 immutable label 與 source hash；此報告只標記來源核對結果，"
        "不截斷、補值、重訓或把極值轉成投資有效性證據。"
    )
    return report


def _same_existing_file(first: Path, second: Path) -> bool:
    if not first.exists() or not second.exists():
        return False
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _validate_output_path(output: Path, *, sources: tuple[Path, ...]) -> Path:
    resolved = output.expanduser().resolve()
    for source in sources:
        source_resolved = source.expanduser().resolve()
        source_root = (
            source_resolved
            if source_resolved.is_dir()
            else source_resolved.parent
        )
        if (
            resolved == source_resolved
            or source_root == resolved
            or source_root in resolved.parents
            or _same_existing_file(resolved, source_resolved)
        ):
            raise LabelExtremeAuditError("audit output must not overwrite a source")
    return resolved


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(payload) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="read-only bounded audit of a Direct label extreme"
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-db", type=Path, default=None)
    parser.add_argument("--raw-shard", type=Path, default=None)
    parser.add_argument("--corporate-action-manifest", type=Path, default=None)
    parser.add_argument("--shared-numeric-store-root", type=Path, default=None)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--field", default="benchmark_excess_return_bp")
    parser.add_argument("--benchmark-entity", default="TAIEX")
    parser.add_argument("--chunk-rows", type=int, default=_DEFAULT_CHUNK_ROWS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.manifest.expanduser().resolve()
    sources = tuple(
        path.resolve()
        for path in (
            manifest,
            args.source_db,
            args.raw_shard,
            args.corporate_action_manifest,
        )
        if path is not None
    )
    try:
        output = _validate_output_path(args.output, sources=sources)
        report = audit_label_extreme(
            manifest,
            source_db=args.source_db,
            raw_shard=args.raw_shard,
            corporate_action_manifest=args.corporate_action_manifest,
            horizon=args.horizon,
            field_name=args.field,
            benchmark_entity=args.benchmark_entity,
            shared_numeric_store_root=args.shared_numeric_store_root,
            chunk_rows=args.chunk_rows,
        )
        _atomic_write_json(output, report)
    except (OSError, LabelExtremeAuditError, TypeError, ValueError) as exc:
        print(f"label extreme audit failed: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
