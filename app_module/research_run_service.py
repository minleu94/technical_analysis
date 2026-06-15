"""Research Run Registry service for immutable metadata and Parquet payloads."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import re
from datetime import date
from typing import Any

import pandas as pd

from app_module.factor_service import FactorService
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_repository import (
    ResearchRunConflictError,
    ResearchRunRepository,
)
from decision_module.factors.factor_dtos import FactorRecord


class ResearchRunServiceError(Exception):
    """Research Run Service 基底例外。"""


class ResearchRunIntegrityError(ResearchRunServiceError):
    """Parquet payload hash 與 registry metadata 不一致。"""


class PromotedResearchRunArchiveError(ResearchRunServiceError):
    """已升級策略版本的 run 不可封存。"""


class InjectedResearchRunFailure(ResearchRunServiceError):
    """測試用注入式崩潰點。"""


@dataclass(frozen=True)
class ResearchRunData:
    metadata: ResearchRunMetadataDTO
    equity: pd.DataFrame
    trades: pd.DataFrame


class ResearchRunService:
    """Research Run Registry 唯一寫入 owner。

    SQLite 與 filesystem 沒有共同 transaction；本服務使用 staging 狀態與
    啟動 reconciliation 來避免半成品被當成完整 run 載入。
    """

    def __init__(self, config: Any):
        self.config = config
        self.repository = ResearchRunRepository(config)
        self.parquet_dir = Path(config.research_run_parquet_dir)
        self.staging_dir = Path(config.research_run_staging_dir)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.reconcile_incomplete_saves()

    def save_run(
        self,
        metadata: ResearchRunMetadataDTO,
        equity: pd.DataFrame,
        trades: pd.DataFrame,
        *,
        factor_records: list[FactorRecord] | None = None,
        factor_decision_date: date | None = None,
        factor_snapshot: dict[str, Any] | None = None,
        factor_contributions: dict[str, Any] | None = None,
        fail_at: str | None = None,
    ) -> ResearchRunMetadataDTO:
        metadata = self._metadata_with_factor_manifest(
            metadata,
            factor_records=factor_records,
            factor_decision_date=factor_decision_date,
            factor_snapshot=factor_snapshot,
            factor_contributions=factor_contributions,
        )
        existing_raw = self.repository.get_raw_metadata_row(metadata.run_id)
        if existing_raw:
            existing = self.repository.get_metadata(metadata.run_id)
            if existing and existing.payload_hash != metadata.payload_hash:
                raise ResearchRunConflictError(
                    f"run_id 已存在但 payload_hash 不一致: {metadata.run_id}"
                )
            if existing_raw["storage_state"] == "committed":
                return existing  # type: ignore[return-value]
            raise ResearchRunIntegrityError(f"run 尚未完整提交: {metadata.run_id}")

        self._fail_if_requested(fail_at, "before_temp_write")

        self.repository.insert_metadata(metadata)
        self.repository.update_storage_fields(
            metadata.run_id,
            storage_state="staging",
            integrity_status="pending",
        )
        self._fail_if_requested(fail_at, "after_staging_row")

        paths = self._paths_for(metadata.run_id)
        equity.to_parquet(paths["equity_temp"], index=False)
        trades.to_parquet(paths["trades_temp"], index=False)
        self._fail_if_requested(fail_at, "after_temp_write")

        equity_hash = self._sha256_file(paths["equity_temp"])
        trades_hash = self._sha256_file(paths["trades_temp"])
        committed_metadata = replace(
            metadata,
            equity_path=str(paths["equity_final"]),
            equity_parquet_hash=equity_hash,
            trades_path=str(paths["trades_final"]),
            trades_parquet_hash=trades_hash,
        )
        self.repository.update_storage_fields(
            metadata.run_id,
            equity_path=committed_metadata.equity_path,
            equity_parquet_hash=equity_hash,
            trades_path=committed_metadata.trades_path,
            trades_parquet_hash=trades_hash,
            storage_state="files_ready",
            integrity_status="pending",
        )
        self._fail_if_requested(fail_at, "after_hash")

        os.replace(paths["equity_temp"], paths["equity_final"])
        self._fail_if_requested(fail_at, "after_first_rename")
        os.replace(paths["trades_temp"], paths["trades_final"])
        self._fail_if_requested(fail_at, "after_second_rename")
        self._fail_if_requested(fail_at, "before_final_commit")

        self.repository.update_storage_fields(
            metadata.run_id,
            storage_state="committed",
            integrity_status="valid",
        )
        return committed_metadata

    def load_run_data(self, run_id: str) -> ResearchRunData:
        raw = self.repository.get_raw_metadata_row(run_id)
        metadata = self.repository.get_metadata(run_id)
        if raw is None or metadata is None:
            raise ResearchRunIntegrityError(f"找不到 research run: {run_id}")
        if raw["storage_state"] != "committed" or raw["integrity_status"] != "valid":
            raise ResearchRunIntegrityError(f"run 尚未通過完整性檢查: {run_id}")

        self._verify_hash(Path(metadata.equity_path), metadata.equity_parquet_hash)
        self._verify_hash(Path(metadata.trades_path), metadata.trades_parquet_hash)
        return ResearchRunData(
            metadata=metadata,
            equity=pd.read_parquet(metadata.equity_path),
            trades=pd.read_parquet(metadata.trades_path),
        )

    def list_runs(self, *, include_archived: bool = False) -> list[ResearchRunMetadataDTO]:
        return self.repository.list_metadata(include_archived=include_archived)

    def archive_run(self, run_id: str) -> None:
        metadata = self.repository.get_metadata(run_id)
        if metadata is None:
            raise ResearchRunIntegrityError(f"找不到 research run: {run_id}")
        if metadata.promoted_version_id:
            raise PromotedResearchRunArchiveError(
                f"已升級策略版本的 run 不可封存: {run_id}"
            )
        self.repository.archive_run(run_id)

    def reconcile_incomplete_saves(self) -> None:
        for row in self.repository.list_uncommitted_rows():
            run_id = row["run_id"]
            if row["storage_state"] == "staging":
                self.repository.update_storage_fields(
                    run_id,
                    storage_state="failed",
                    integrity_status="failed",
                )
                continue

            if not self._finish_files_ready_row(row):
                self.repository.update_storage_fields(
                    run_id,
                    storage_state="failed",
                    integrity_status="failed",
                )

    def _finish_files_ready_row(self, row: dict[str, Any]) -> bool:
        run_id = str(row["run_id"])
        paths = self._paths_for(run_id)
        expected = [
            (
                paths["equity_temp"],
                Path(row["equity_path"]),
                row["equity_parquet_hash"],
            ),
            (
                paths["trades_temp"],
                Path(row["trades_path"]),
                row["trades_parquet_hash"],
            ),
        ]

        try:
            for temp_path, final_path, _expected_hash in expected:
                if not final_path.exists():
                    if temp_path.exists():
                        os.replace(temp_path, final_path)
                    else:
                        return False
            for _temp_path, final_path, expected_hash in expected:
                self._verify_hash(final_path, str(expected_hash))
        except (OSError, ResearchRunIntegrityError):
            return False

        self.repository.update_storage_fields(
            run_id,
            storage_state="committed",
            integrity_status="valid",
        )
        return True

    def _paths_for(self, run_id: str) -> dict[str, Path]:
        file_stem = self._safe_file_stem(run_id)
        return {
            "equity_temp": self.staging_dir / f"{file_stem}_equity.tmp.parquet",
            "trades_temp": self.staging_dir / f"{file_stem}_trades.tmp.parquet",
            "equity_final": self.parquet_dir / f"{file_stem}_equity.parquet",
            "trades_final": self.parquet_dir / f"{file_stem}_trades.parquet",
        }

    def _safe_file_stem(self, run_id: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("._")
        suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
        return f"{sanitized}_{suffix}" if sanitized else suffix

    def _metadata_with_factor_manifest(
        self,
        metadata: ResearchRunMetadataDTO,
        *,
        factor_records: list[FactorRecord] | None,
        factor_decision_date: date | None,
        factor_snapshot: dict[str, Any] | None,
        factor_contributions: dict[str, Any] | None,
    ) -> ResearchRunMetadataDTO:
        if factor_records is None and factor_snapshot is None and factor_contributions is None:
            return metadata

        factor_service = FactorService()
        snapshot = dict(factor_snapshot) if factor_snapshot is not None else None
        if factor_records is not None:
            if factor_decision_date is None:
                raise ValueError("factor_decision_date is required when factor_records are provided")
            snapshot = factor_service.build_snapshot(
                factor_records,
                decision_date=factor_decision_date,
            )
        contributions = (
            dict(factor_contributions)
            if factor_contributions is not None
            else factor_service.build_contributions(snapshot or {})
        )
        data_manifest = dict(metadata.data_manifest)
        if snapshot is not None:
            data_manifest["factor_snapshot"] = snapshot
        data_manifest["factor_contributions"] = contributions
        return replace(metadata, data_manifest=data_manifest)

    def _verify_hash(self, path: Path, expected_hash: str) -> None:
        if not path.exists():
            raise ResearchRunIntegrityError(f"payload 檔案不存在: {path}")
        actual = self._sha256_file(path)
        if actual != expected_hash:
            raise ResearchRunIntegrityError(f"payload hash 不一致: {path}")

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def _fail_if_requested(self, fail_at: str | None, point: str) -> None:
        if fail_at == point:
            raise InjectedResearchRunFailure(point)
