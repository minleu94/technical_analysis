"""Isolated SQLite candidate/shadow repository for Fubon market data.

Enforces strict path guards so that candidate/shadow data is stored ONLY in an isolated
working-copy database outside the repository, outside DATA_ROOT, and outside formal twstock.db.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Sequence

from data_module.fubon_pit_validator import FubonPITObservation
from app_module.fubon_shadow_decision_service import FubonShadowDecisionBundle


class ProductionPathRejectedError(ValueError):
    """Raised when candidate DB path resolves to formal DATA_ROOT or formal DB."""


def validate_fubon_shadow_db_path(
    candidate_db_path: str | Path | None,
    *,
    production_data_root: str | Path | None = None,
    production_db_path: str | Path | None = None,
) -> Path:
    """Validate candidate DB path; reject formal DATA_ROOT and formal DBs."""
    if candidate_db_path is None or not str(candidate_db_path).strip():
        raise ValueError("candidate_db_path is required")

    candidate = Path(candidate_db_path).expanduser().resolve(strict=False)
    if candidate.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("candidate_db_path must be an explicit SQLite file")

    data_root_str = os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data") if production_data_root is None else str(production_data_root)
    data_root = Path(data_root_str).expanduser().resolve(strict=False)

    prod_db_str = str(data_root / "sqlite" / "twstock.db") if production_db_path is None else str(production_db_path)
    production_db = Path(prod_db_str).expanduser().resolve(strict=False)

    repo_root = Path(__file__).resolve().parents[1].resolve()

    for forbidden in (data_root, production_db, repo_root):
        if candidate == forbidden or candidate.is_relative_to(forbidden):
            raise ProductionPathRejectedError(
                f"Candidate DB write rejected for formal/repo path: {candidate}"
            )

    return candidate


@dataclass(frozen=True)
class FubonCandidateWriteResult:
    accepted_count: int
    duplicate_count: int
    quarantined_count: int
    bundle_duplicate_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "accepted_count": self.accepted_count,
            "duplicate_count": self.duplicate_count,
            "quarantined_count": self.quarantined_count,
            "bundle_duplicate_count": self.bundle_duplicate_count,
        }


class FubonShadowCandidateRepository:
    """Isolated SQLite repository for Fubon shadow decision bundles and observations."""

    def __init__(
        self,
        candidate_db_path: str | Path,
        *,
        production_data_root: str | Path | None = None,
        production_db_path: str | Path | None = None,
    ) -> None:
        self.db_path = validate_fubon_shadow_db_path(
            candidate_db_path,
            production_data_root=production_data_root,
            production_db_path=production_db_path,
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            self._ensure_schema(conn)

    def save_shadow_decision_bundle(
        self,
        bundle: FubonShadowDecisionBundle,
        observations: Sequence[FubonPITObservation] = (),
    ) -> FubonCandidateWriteResult:
        """Save a shadow decision bundle and its associated PIT observations."""
        accepted = 0
        duplicates = 0
        quarantined = 0
        bundle_duplicates = 0
        if not bundle.run_id.strip():
            raise ValueError("bundle run_id is required")
        bundle_json = bundle.to_sanitized_json()
        bundle_sha256 = _sha256_text(bundle_json)

        with sqlite3.connect(self.db_path) as conn:
            # 1. Save Bundle
            existing_bundle = conn.execute(
                """
                SELECT bundle_sha256
                FROM fubon_shadow_decision_bundles
                WHERE run_id = ?
                """,
                (bundle.run_id,),
            ).fetchone()
            if existing_bundle is None:
                conn.execute(
                    """
                    INSERT INTO fubon_shadow_decision_bundles (
                        run_id, decision_timestamp, pit_status, bundle_sha256, bundle_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        bundle.run_id,
                        bundle.decision_timestamp,
                        bundle.pit_validation_status,
                        bundle_sha256,
                        bundle_json,
                    ),
                )
            elif str(existing_bundle[0]) == bundle_sha256:
                bundle_duplicates += 1
            else:
                raise ValueError("conflicting bundle payload for existing run_id")

            # 2. Save PIT Observations
            for obs in observations:
                if not _is_sha256(obs.raw_payload_sha256) or not _is_sha256(
                    obs.normalized_content_sha256
                ):
                    raise ValueError("observation hashes must use sha256:<64 hex>")
                if obs.quarantine_status == "quarantined":
                    _insert_quarantine(
                        conn,
                        bundle.run_id,
                        obs,
                        "validator_quarantined",
                        ",".join(obs.missing_or_degraded_reasons),
                    )
                    quarantined += 1
                    continue

                key = (obs.source_id, obs.symbol, obs.available_at, obs.revision_id)
                existing = conn.execute(
                    """
                    SELECT normalized_content_sha256
                    FROM fubon_accepted_pit_observations
                    WHERE source_id = ? AND symbol = ? AND available_at = ?
                      AND revision_id = ?
                    """,
                    key,
                ).fetchone()

                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO fubon_accepted_pit_observations (
                            source_id, source_version, symbol, market_timestamp,
                            published_at, first_observed_at, available_at,
                            decision_timestamp, revision_id, raw_payload_sha256,
                            normalized_content_sha256, quality_status,
                            quarantine_status, observation_json, run_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            obs.source_id,
                            obs.source_version,
                            obs.symbol,
                            obs.market_timestamp,
                            obs.published_at,
                            obs.first_observed_at,
                            obs.available_at,
                            obs.decision_timestamp,
                            obs.revision_id,
                            obs.raw_payload_sha256,
                            obs.normalized_content_sha256,
                            obs.quality_status,
                            obs.quarantine_status,
                            json.dumps(obs.to_dict(), ensure_ascii=False, sort_keys=True),
                            bundle.run_id,
                        ),
                    )
                    accepted += 1
                elif str(existing[0]) == obs.normalized_content_sha256:
                    duplicates += 1
                else:
                    # Same key, different hash -> quarantine
                    _insert_quarantine(
                        conn,
                        bundle.run_id,
                        obs,
                        "conflicting_duplicate_hash",
                        "Same source/symbol/available_at/revision identity has a different hash.",
                    )
                    quarantined += 1

        return FubonCandidateWriteResult(
            accepted_count=accepted,
            duplicate_count=duplicates,
            quarantined_count=quarantined,
            bundle_duplicate_count=bundle_duplicates,
        )

    def read_shadow_decision_bundle(self, run_id: str) -> dict[str, Any] | None:
        """Read shadow decision bundle by run_id."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT bundle_json FROM fubon_shadow_decision_bundles WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["bundle_json"])

    def inspect_summary(self) -> dict[str, Any]:
        """Produce read-only summary of the shadow candidate database."""
        with sqlite3.connect(self.db_path) as conn:
            bundle_count = conn.execute("SELECT COUNT(*) FROM fubon_shadow_decision_bundles").fetchone()[0]
            observation_count = conn.execute("SELECT COUNT(*) FROM fubon_accepted_pit_observations").fetchone()[0]
            quarantine_count = conn.execute("SELECT COUNT(*) FROM fubon_quarantine_observations").fetchone()[0]

        return {
            "candidate_db_path": str(self.db_path),
            "bundle_count": bundle_count,
            "observation_count": observation_count,
            "quarantine_count": quarantine_count,
            "reads_positions_db": False,
            "writes_formal_db": False,
        }

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS fubon_shadow_decision_bundles (
                run_id TEXT PRIMARY KEY,
                decision_timestamp TEXT NOT NULL,
                pit_status TEXT NOT NULL,
                bundle_sha256 TEXT NOT NULL,
                bundle_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fubon_accepted_pit_observations (
                source_id TEXT NOT NULL,
                source_version TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market_timestamp TEXT,
                published_at TEXT,
                first_observed_at TEXT,
                available_at TEXT NOT NULL,
                decision_timestamp TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                raw_payload_sha256 TEXT NOT NULL,
                normalized_content_sha256 TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                quarantine_status TEXT NOT NULL,
                observation_json TEXT NOT NULL,
                run_id TEXT NOT NULL,
                PRIMARY KEY (source_id, symbol, available_at, revision_id)
            );

            CREATE TABLE IF NOT EXISTS fubon_quarantine_observations (
                quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                available_at TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                detail TEXT NOT NULL
            );
            """
        )


def _insert_quarantine(
    conn: sqlite3.Connection,
    run_id: str,
    observation: FubonPITObservation,
    reason_code: str,
    detail: str,
) -> None:
    conn.execute(
        """
        INSERT INTO fubon_quarantine_observations (
            run_id, source_id, symbol, available_at, reason_code, detail
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            observation.source_id,
            observation.symbol,
            observation.available_at,
            reason_code,
            detail,
        ),
    )


def _sha256_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _is_sha256(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest.lower())
