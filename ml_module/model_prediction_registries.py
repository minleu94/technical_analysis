"""Append-only shadow model and integer-bp prediction registries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class MLModelRecord:
    model_id: str
    dataset_id: str
    created_at: str
    model_family: str
    feature_names: tuple[str, ...]
    artifact_path: str
    artifact_hash: str
    calibration_id: str | None = None
    lifecycle_status: str = "shadow_candidate"
    shadow_only: bool = True
    production_eligible: bool = False

    def __post_init__(self) -> None:
        if not all((self.model_id, self.dataset_id, self.model_family, self.artifact_path, self.artifact_hash)):
            raise ValueError("model identity and artifact metadata are required")
        if not self.feature_names:
            raise ValueError("feature_names are required")
        if self.lifecycle_status != "shadow_candidate" or not self.shadow_only or self.production_eligible:
            raise ValueError("Gate 7 model record must remain shadow-only")


@dataclass(frozen=True)
class MLShadowPredictionRecord:
    prediction_id: str
    model_id: str
    dataset_id: str
    symbol: str
    decision_date: str
    available_date: str
    return_prediction_bp: int | float
    ranking_score: int | float
    downside_probability: int | float
    uncertainty_bp: int = 0
    feature_snapshot_hash: str = "legacy:unknown"
    source_versions_hash: str = "legacy:unknown"
    shadow_only: bool = True
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        if not all((self.prediction_id, self.model_id, self.dataset_id, self.symbol)):
            raise ValueError("prediction identity fields are required")
        if _date(self.available_date) > _date(self.decision_date):
            raise ValueError("available_date cannot be after decision_date")
        numeric = (self.return_prediction_bp, self.ranking_score, self.downside_probability)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in numeric):
            raise ValueError("prediction values must be finite numbers")
        probability_max = 10000 if isinstance(self.downside_probability, int) else 1
        if not 0 <= self.downside_probability <= probability_max:
            raise ValueError("downside_probability must be within its bp or legacy unit interval")
        if isinstance(self.uncertainty_bp, bool) or not isinstance(self.uncertainty_bp, int) or self.uncertainty_bp < 0:
            raise ValueError("uncertainty_bp must be a non-negative integer")
        if not self.shadow_only or self.production_action_allowed:
            raise ValueError("prediction must remain shadow-only")


def initialize_shadow_registry(db_path: str | Path, *, data_root: str | Path | None = None) -> None:
    path = _validate_shadow_db(db_path, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ml_models (model_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ml_shadow_predictions_v2 (
                prediction_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                available_date TEXT NOT NULL,
                return_prediction_bp INTEGER NOT NULL,
                ranking_score_bp INTEGER NOT NULL,
                downside_probability_bp INTEGER NOT NULL,
                uncertainty_bp INTEGER NOT NULL,
                feature_snapshot_hash TEXT NOT NULL,
                source_versions_hash TEXT NOT NULL,
                shadow_only INTEGER NOT NULL,
                production_action_allowed INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            )"""
        )


class MLModelRegistry:
    def __init__(self, db_path: str | Path, *, data_root: str | Path | None = None) -> None:
        self._path = _validate_shadow_db(db_path, data_root=data_root)

    def append(self, record: MLModelRecord) -> str:
        payload = {**record.__dict__, "feature_names": list(record.feature_names)}
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._connect_rw() as conn:
            existing = conn.execute(
                "SELECT payload_json FROM ml_models WHERE model_id = ?", (record.model_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] == payload_json:
                    return "idempotent"
                raise ValueError(f"model conflict: {record.model_id}")
            conn.execute("INSERT INTO ml_models VALUES (?, ?)", (record.model_id, payload_json))
        return "inserted"

    def get(self, model_id: str) -> MLModelRecord | None:
        with self._connect_rw() as conn:
            row = conn.execute("SELECT payload_json FROM ml_models WHERE model_id = ?", (model_id,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        payload["feature_names"] = tuple(payload["feature_names"])
        return MLModelRecord(**payload)

    def _connect_rw(self) -> sqlite3.Connection:
        return _connect_existing(self._path)


class MLShadowPredictionRegistry:
    def __init__(self, db_path: str | Path, *, data_root: str | Path | None = None) -> None:
        self._path = _validate_shadow_db(db_path, data_root=data_root)

    def append(self, record: MLShadowPredictionRecord) -> str:
        with self._connect_rw() as conn:
            return self._append_in_transaction(conn, record)

    def append_batch(self, records: Iterable[MLShadowPredictionRecord]) -> tuple[str, ...]:
        with self._connect_rw() as conn:
            return tuple(self._append_in_transaction(conn, record) for record in records)

    def _append_in_transaction(self, conn: sqlite3.Connection, record: MLShadowPredictionRecord) -> str:
        _require_integer_prediction(record)
        payload_json = _prediction_payload_json(record)
        existing = conn.execute(
            "SELECT payload_json FROM ml_shadow_predictions_v2 WHERE prediction_id = ?",
            (record.prediction_id,),
        ).fetchone()
        if existing is not None:
            if existing[0] == payload_json:
                return "idempotent"
            raise ValueError(f"prediction conflict: {record.prediction_id}")
        conn.execute(
            """INSERT INTO ml_shadow_predictions_v2 VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                record.prediction_id,
                record.model_id,
                record.dataset_id,
                record.symbol,
                record.decision_date,
                record.available_date,
                record.return_prediction_bp,
                record.ranking_score,
                record.downside_probability,
                record.uncertainty_bp,
                record.feature_snapshot_hash,
                record.source_versions_hash,
                int(record.shadow_only),
                int(record.production_action_allowed),
                payload_json,
            ),
        )
        return "inserted"

    def list_for_model(self, model_id: str) -> tuple[MLShadowPredictionRecord, ...]:
        with self._connect_rw() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "ml_shadow_predictions_v2" in tables:
                rows = conn.execute(
                    """SELECT prediction_id, model_id, dataset_id, symbol, decision_date,
                              available_date, return_prediction_bp, ranking_score_bp,
                              downside_probability_bp, uncertainty_bp, feature_snapshot_hash,
                              source_versions_hash, shadow_only, production_action_allowed
                       FROM ml_shadow_predictions_v2
                       WHERE model_id = ? ORDER BY decision_date, prediction_id""",
                    (model_id,),
                ).fetchall()
                return tuple(_record_from_v2(row) for row in rows)
            return self._read_legacy(conn, model_id)

    @staticmethod
    def _read_legacy(conn: sqlite3.Connection, model_id: str) -> tuple[MLShadowPredictionRecord, ...]:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "ml_shadow_predictions" not in tables:
            return ()
        rows = conn.execute(
            "SELECT * FROM ml_shadow_predictions WHERE model_id = ? ORDER BY decision_date, prediction_id",
            (model_id,),
        ).fetchall()
        return tuple(
            MLShadowPredictionRecord(
                prediction_id=row[0], model_id=row[1], dataset_id=row[2], symbol=row[3],
                decision_date=row[4], available_date=row[5],
                return_prediction_bp=_integer_bp(row[6]),
                ranking_score=_legacy_fraction_to_bp(row[7]),
                downside_probability=_legacy_fraction_to_bp(row[8]),
                feature_snapshot_hash="legacy:unknown", source_versions_hash="legacy:unknown",
                shadow_only=bool(row[9]), production_action_allowed=bool(row[10]),
            )
            for row in rows
        )

    def _connect_rw(self) -> sqlite3.Connection:
        return _connect_existing(self._path)


def _record_from_v2(row: Sequence[Any]) -> MLShadowPredictionRecord:
    return MLShadowPredictionRecord(
        prediction_id=str(row[0]), model_id=str(row[1]), dataset_id=str(row[2]), symbol=str(row[3]),
        decision_date=str(row[4]), available_date=str(row[5]), return_prediction_bp=int(row[6]),
        ranking_score=int(row[7]), downside_probability=int(row[8]), uncertainty_bp=int(row[9]),
        feature_snapshot_hash=str(row[10]), source_versions_hash=str(row[11]),
        shadow_only=bool(row[12]), production_action_allowed=bool(row[13]),
    )


def _prediction_payload_json(record: MLShadowPredictionRecord) -> str:
    return json.dumps(record.__dict__, sort_keys=True, separators=(",", ":"))


def _require_integer_prediction(record: MLShadowPredictionRecord) -> None:
    for name in ("return_prediction_bp", "ranking_score", "downside_probability", "uncertainty_bp"):
        value = getattr(record, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"new prediction writes require integer bp: {name}")


def _connect_existing(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"shadow registry is not initialized: {path}")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=rw", uri=True)


def _validate_shadow_db(path: str | Path, *, data_root: str | Path | None) -> Path:
    resolved = Path(path).resolve()
    formal_root = Path(data_root or os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    if resolved == formal_root or formal_root in resolved.parents:
        raise ValueError("shadow registry cannot be DATA_ROOT or its descendant")
    return resolved


def _integer_bp(value: object) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def _legacy_fraction_to_bp(value: object) -> int:
    decimal_value = Decimal(str(value))
    if Decimal("-1") <= decimal_value <= Decimal("1"):
        decimal_value *= Decimal("10000")
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])
