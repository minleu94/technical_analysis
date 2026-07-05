"""SQLite repository for V1.6 cross-sectional factor snapshots."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from app_module.cross_sectional_factor_dtos import (
    CrossSectionalFactorDiagnostic,
    CrossSectionalFactorRow,
    CrossSectionalFactorSnapshot,
    parse_factor_quality,
    parse_missing_policy,
)
from app_module.evidence_event_service import utc_timestamp
from app_module.research_run_dtos import canonical_json
from data_module.cross_sectional_factor_migration import apply_cross_sectional_factor_schema


class CrossSectionalFactorSnapshotConflictError(ValueError):
    pass


class CrossSectionalFactorRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            apply_cross_sectional_factor_schema(conn)

    def save_snapshot(self, snapshot: CrossSectionalFactorSnapshot) -> CrossSectionalFactorSnapshot:
        existing_by_hash = self.get_snapshot_by_hash(snapshot.snapshot_hash)
        if existing_by_hash is not None:
            return existing_by_hash

        existing_by_id = self.get_snapshot(snapshot.snapshot_id)
        if existing_by_id is not None and existing_by_id.snapshot_hash != snapshot.snapshot_hash:
            raise CrossSectionalFactorSnapshotConflictError(
                f"snapshot_id already exists with different hash: {snapshot.snapshot_id}"
            )

        created_at = snapshot.created_at or utc_timestamp()
        row_snapshot = replace(snapshot, created_at=created_at)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cross_sectional_factor_snapshots (
                    snapshot_id,
                    snapshot_hash,
                    decision_date,
                    factor_set_version,
                    universe_id,
                    source_version,
                    row_count,
                    diagnostics_json,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_snapshot.snapshot_id,
                    row_snapshot.snapshot_hash,
                    row_snapshot.decision_date.isoformat(),
                    row_snapshot.factor_set_version,
                    row_snapshot.universe_id,
                    row_snapshot.source_version,
                    row_snapshot.row_count,
                    canonical_json([diagnostic.to_dict() for diagnostic in row_snapshot.diagnostics]),
                    canonical_json(dict(row_snapshot.metadata)),
                    row_snapshot.created_at,
                ),
            )
            conn.executemany(
                """
                INSERT INTO cross_sectional_factor_rows (
                    row_id,
                    snapshot_id,
                    stock_code,
                    factor_name,
                    as_of_date,
                    available_date,
                    value,
                    score_bp,
                    rank,
                    quantile_bp,
                    universe_size,
                    quality,
                    missing_policy,
                    source_version,
                    sector,
                    concept_basket,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._row_to_sql_values(row_snapshot.snapshot_id, row) for row in row_snapshot.rows],
            )

        saved = self.get_snapshot(row_snapshot.snapshot_id)
        if saved is None:
            raise RuntimeError(f"cross-sectional factor snapshot not found after insert: {row_snapshot.snapshot_id}")
        return saved

    def get_snapshot(self, snapshot_id: str) -> CrossSectionalFactorSnapshot | None:
        return self._fetch_snapshot("snapshot_id = ?", (snapshot_id,))

    def get_snapshot_by_hash(self, snapshot_hash: str) -> CrossSectionalFactorSnapshot | None:
        return self._fetch_snapshot("snapshot_hash = ?", (snapshot_hash,))

    def get_latest_snapshot_id(self) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT snapshot_id
                FROM cross_sectional_factor_snapshots
                ORDER BY decision_date DESC, snapshot_id DESC
                LIMIT 1
                """
            ).fetchone()
        return str(row[0]) if row is not None else None

    def list_rows(self, snapshot_id: str) -> list[CrossSectionalFactorRow]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM cross_sectional_factor_rows
                WHERE snapshot_id = ?
                ORDER BY factor_name ASC, rank ASC, stock_code ASC, row_id ASC
                """,
                (snapshot_id,),
            ).fetchall()
        return [self._sql_row_to_factor_row(dict(row)) for row in rows]

    def _fetch_snapshot(
        self,
        where: str,
        params: tuple[Any, ...],
    ) -> CrossSectionalFactorSnapshot | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM cross_sectional_factor_snapshots WHERE {where} LIMIT 1",
                params,
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        rows = tuple(self.list_rows(str(payload["snapshot_id"])))
        diagnostics = tuple(
            CrossSectionalFactorDiagnostic(
                code=str(item.get("code", "")),
                message=str(item.get("message", "")),
                factor_name=str(item.get("factor_name", "")),
                stock_code=str(item.get("stock_code", "")),
                severity=str(item.get("severity", "warning")),
                metadata=item.get("metadata", {}),
            )
            for item in json.loads(payload["diagnostics_json"] or "[]")
            if isinstance(item, dict)
        )
        return CrossSectionalFactorSnapshot(
            snapshot_id=str(payload["snapshot_id"]),
            decision_date=date.fromisoformat(str(payload["decision_date"])),
            factor_set_version=str(payload["factor_set_version"]),
            universe_id=str(payload["universe_id"]),
            source_version=str(payload["source_version"]),
            rows=rows,
            diagnostics=diagnostics,
            metadata=json.loads(payload["metadata_json"] or "{}"),
            snapshot_hash=str(payload["snapshot_hash"]),
            created_at=str(payload["created_at"]),
        )

    @staticmethod
    def _row_to_sql_values(snapshot_id: str, row: CrossSectionalFactorRow) -> tuple[Any, ...]:
        row_dict = row.to_dict()
        return (
            row.row_id,
            snapshot_id,
            row.stock_code,
            row.factor_name,
            row.as_of_date.isoformat(),
            row.available_date.isoformat(),
            row_dict["value"],
            row.score_bp,
            row.rank,
            row.quantile_bp,
            row.universe_size,
            row.quality.value,
            row.missing_policy.value,
            row.source_version,
            row.sector,
            row.concept_basket,
            canonical_json(row_dict["metadata"]),
        )

    @staticmethod
    def _sql_row_to_factor_row(row: dict[str, Any]) -> CrossSectionalFactorRow:
        return CrossSectionalFactorRow(
            row_id=str(row["row_id"]),
            stock_code=str(row["stock_code"]),
            factor_name=str(row["factor_name"]),
            as_of_date=date.fromisoformat(str(row["as_of_date"])),
            available_date=date.fromisoformat(str(row["available_date"])),
            value=_parse_value(row["value"]),
            score_bp=row["score_bp"],
            rank=row["rank"],
            quantile_bp=row["quantile_bp"],
            universe_size=int(row["universe_size"]),
            quality=parse_factor_quality(row["quality"]),
            missing_policy=parse_missing_policy(row["missing_policy"]),
            source_version=str(row["source_version"]),
            sector=row["sector"],
            concept_basket=row["concept_basket"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )


def _parse_value(value: Any) -> Decimal | int | str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return ""
    try:
        return Decimal(text)
    except Exception:  # noqa: BLE001
        return text
