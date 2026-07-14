"""P0 candidate working-copy repository 的安全邊界。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from data_module.p0_candidate_manifest import RawPayloadManifest
from data_module.p0_source_candidate_contracts import NormalizedP0Observation


class ProductionPathRejectedError(ValueError):
    """目標解析到正式資料根或正式 DB 時拒絕。"""


def validate_candidate_working_copy_path(
    working_copy_db: str | Path | None,
    *,
    production_data_root: str | Path,
    production_db_path: str | Path,
) -> Path:
    """純路徑驗證；不建立目錄、DB、table 或 log。"""
    if working_copy_db is None or not str(working_copy_db).strip():
        raise ValueError("apply 必須提供 explicit working-copy DB path")

    candidate = Path(working_copy_db).expanduser().resolve(strict=False)
    data_root = Path(production_data_root).expanduser().resolve(strict=False)
    production_db = Path(production_db_path).expanduser().resolve(strict=False)
    if candidate == production_db or candidate == data_root or candidate.is_relative_to(data_root):
        raise ProductionPathRejectedError(f"candidate apply 拒絕正式資料路徑: {candidate}")
    return candidate


@dataclass(frozen=True)
class CandidateWriteResult:
    accepted: int
    duplicates: int
    conflicts: int
    quarantined: int

    def to_dict(self) -> dict[str, int]:
        return {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "conflicts": self.conflicts,
            "quarantined": self.quarantined,
        }


class CandidateRepository:
    """只寫 explicit isolated working-copy 的 candidate repository。"""

    def __init__(
        self,
        working_copy_db: str | Path,
        *,
        production_data_root: str | Path,
        production_db_path: str | Path,
    ) -> None:
        self.db_path = validate_candidate_working_copy_path(
            working_copy_db,
            production_data_root=production_data_root,
            production_db_path=production_db_path,
        )

    def apply(
        self,
        *,
        manifest: RawPayloadManifest,
        observations: Iterable[NormalizedP0Observation],
        confirm_candidate_write: bool,
    ) -> CandidateWriteResult:
        if not confirm_candidate_write:
            raise PermissionError("apply 必須提供 --confirm-candidate-write")

        rows = tuple(observations)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        accepted = 0
        duplicates = 0
        conflicts = 0
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT OR IGNORE INTO p0_candidate_manifests (
                    run_id, source_id, source_version, fetched_at,
                    payload_sha256, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    manifest.source_id,
                    manifest.source_version,
                    manifest.fetched_at.isoformat(),
                    manifest.payload_sha256,
                    json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True),
                ),
            )
            for observation in rows:
                identity = (
                    observation.source_id,
                    observation.source_version,
                    observation.symbol,
                    observation.observation_date,
                    observation.period,
                )
                existing = conn.execute(
                    """
                    SELECT normalized_content_sha256
                    FROM p0_candidate_observations
                    WHERE source_id = ? AND source_version = ? AND symbol = ?
                      AND observation_date = ? AND period = ?
                    """,
                    identity,
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO p0_candidate_observations (
                            source_id, source_version, symbol, observation_date,
                            period, available_at, quality, raw_payload_sha256,
                            normalized_content_sha256, observation_json, first_run_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            *identity,
                            observation.available_at.isoformat(),
                            observation.quality,
                            observation.raw_payload_sha256,
                            observation.normalized_content_sha256,
                            json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True),
                            manifest.run_id,
                        ),
                    )
                    accepted += 1
                elif str(existing[0]) == observation.normalized_content_sha256:
                    duplicates += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO p0_candidate_quarantine (
                            run_id, source_id, source_version, symbol,
                            observation_date, period, raw_row_sha256,
                            reason_code, detail
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            manifest.run_id,
                            *identity,
                            observation.raw_payload_sha256,
                            "identity_content_conflict",
                            "相同 natural identity 出現不同 normalized content；保留既有 row。",
                        ),
                    )
                    conflicts += 1
        return CandidateWriteResult(
            accepted=accepted,
            duplicates=duplicates,
            conflicts=conflicts,
            quarantined=conflicts,
        )

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS p0_candidate_manifests (
                run_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_version TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                manifest_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS p0_candidate_observations (
                source_id TEXT NOT NULL,
                source_version TEXT NOT NULL,
                symbol TEXT NOT NULL,
                observation_date TEXT NOT NULL,
                period TEXT NOT NULL,
                available_at TEXT NOT NULL,
                quality TEXT NOT NULL,
                raw_payload_sha256 TEXT NOT NULL,
                normalized_content_sha256 TEXT NOT NULL,
                observation_json TEXT NOT NULL,
                first_run_id TEXT NOT NULL,
                PRIMARY KEY (source_id, source_version, symbol, observation_date, period)
            );
            CREATE TABLE IF NOT EXISTS p0_candidate_quarantine (
                quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_version TEXT NOT NULL,
                symbol TEXT NOT NULL,
                observation_date TEXT NOT NULL,
                period TEXT NOT NULL,
                raw_row_sha256 TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                detail TEXT NOT NULL
            );
            """
        )
