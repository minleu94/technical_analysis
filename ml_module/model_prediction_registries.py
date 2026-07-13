"""Append-only shadow model and prediction registries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import math
from pathlib import Path
import sqlite3


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
    return_prediction_bp: float
    ranking_score: float
    downside_probability: float
    shadow_only: bool = True
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        if not all((self.prediction_id, self.model_id, self.dataset_id, self.symbol)):
            raise ValueError("prediction identity fields are required")
        if _date(self.available_date) > _date(self.decision_date):
            raise ValueError("available_date cannot be after decision_date")
        if not all(math.isfinite(value) for value in (self.return_prediction_bp, self.ranking_score)):
            raise ValueError("prediction values must be finite")
        if not math.isfinite(self.downside_probability) or not 0 <= self.downside_probability <= 1:
            raise ValueError("downside_probability must be within 0..1")
        if not self.shadow_only or self.production_action_allowed:
            raise ValueError("prediction must remain shadow-only")


class MLModelRegistry:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ml_models (model_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)"
            )

    def append(self, record: MLModelRecord) -> None:
        payload = {
            **record.__dict__,
            "feature_names": list(record.feature_names),
        }
        try:
            with sqlite3.connect(self._path) as conn:
                conn.execute("INSERT INTO ml_models VALUES (?, ?)", (record.model_id, json.dumps(payload)))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"model already exists: {record.model_id}") from exc

    def get(self, model_id: str) -> MLModelRecord | None:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute("SELECT payload_json FROM ml_models WHERE model_id = ?", (model_id,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        payload["feature_names"] = tuple(payload["feature_names"])
        return MLModelRecord(**payload)


class MLShadowPredictionRegistry:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ml_shadow_predictions (
                    prediction_id TEXT PRIMARY KEY, model_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, decision_date TEXT NOT NULL, available_date TEXT NOT NULL,
                    return_prediction_bp REAL NOT NULL, ranking_score REAL NOT NULL,
                    downside_probability REAL NOT NULL, shadow_only INTEGER NOT NULL,
                    production_action_allowed INTEGER NOT NULL
                )"""
            )

    def append(self, record: MLShadowPredictionRecord) -> None:
        try:
            with sqlite3.connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO ml_shadow_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.prediction_id, record.model_id, record.dataset_id, record.symbol,
                        record.decision_date, record.available_date, record.return_prediction_bp,
                        record.ranking_score, record.downside_probability, int(record.shadow_only),
                        int(record.production_action_allowed),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"prediction already exists: {record.prediction_id}") from exc

    def list_for_model(self, model_id: str) -> tuple[MLShadowPredictionRecord, ...]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM ml_shadow_predictions WHERE model_id = ? ORDER BY decision_date, prediction_id",
                (model_id,),
            ).fetchall()
        return tuple(
            MLShadowPredictionRecord(
                prediction_id=row[0], model_id=row[1], dataset_id=row[2], symbol=row[3],
                decision_date=row[4], available_date=row[5], return_prediction_bp=float(row[6]),
                ranking_score=float(row[7]), downside_probability=float(row[8]),
                shadow_only=bool(row[9]), production_action_allowed=bool(row[10]),
            )
            for row in rows
        )


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])
