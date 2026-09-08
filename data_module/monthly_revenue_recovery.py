"""月營收 mapping 與 SQLite 的受控跨檔更新協調器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile
from typing import Any
from uuid import uuid4

from data_module.monthly_revenue_availability_merge import (
    MonthlyRevenueAvailabilityMergeApplyResult,
    MonthlyRevenueAvailabilityMergePlan,
    apply_monthly_revenue_availability_merge,
    monthly_revenue_availability_lock,
    plan_monthly_revenue_availability_merge,
    reserve_monthly_revenue_mapping_backup_path,
)
from data_module.fundamental_data import MonthlyRevenueRecord
from data_module.monthly_revenue_backfill import (
    MonthlyRevenueBackfillApplyResult,
    MonthlyRevenueBackfillPlan,
    apply_mops_snapshot_monthly_revenue_backfill,
    plan_mops_snapshot_monthly_revenue_backfill,
    reserve_monthly_revenue_sqlite_backup_path,
)


@dataclass(frozen=True)
class MonthlyRevenueRecoveryPlan:
    """同一候選 mapping 與 snapshot 的跨檔唯讀計畫。"""

    availability_plan: MonthlyRevenueAvailabilityMergePlan
    backfill_plan: MonthlyRevenueBackfillPlan

    @property
    def ready_for_apply(self) -> bool:
        return (
            self.availability_plan.ready_for_apply
            and self.backfill_plan.ready_for_apply
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "ready_for_apply": self.ready_for_apply,
            "snapshot_scope": self.backfill_plan.snapshot_scope,
            "full_snapshot_row_count": self.backfill_plan.full_snapshot_row_count,
            "accepted_snapshot_row_count": self.backfill_plan.raw_row_count,
            "excluded_snapshot_row_count": (
                self.backfill_plan.excluded_snapshot_row_count
            ),
            "availability": {
                "target_file": str(self.availability_plan.target_file),
                "candidate_file": str(self.availability_plan.candidate_file),
                "existing_count": self.availability_plan.existing_count,
                "candidate_count": self.availability_plan.candidate_count,
                "added_count": self.availability_plan.added_count,
                "unchanged_count": self.availability_plan.unchanged_count,
                "conflict_count": self.availability_plan.conflict_count,
                "merged_count": len(self.availability_plan.merged_rows),
                "target_sha256": self.availability_plan.target_sha256,
                "merged_sha256": self.availability_plan.merged_sha256,
                "diagnostics": _diagnostics_payload(
                    self.availability_plan.diagnostics
                ),
            },
            "backfill": {
                "raw_row_count": self.backfill_plan.raw_row_count,
                "normalized_record_count": len(self.backfill_plan.records),
                "snapshot_duplicate_row_count": (
                    self.backfill_plan.snapshot_duplicate_row_count
                ),
                "snapshot_unmatched_mapping_count": (
                    self.backfill_plan.snapshot_unmatched_mapping_count
                ),
                "snapshot_invalid_row_count": (
                    self.backfill_plan.snapshot_invalid_row_count
                ),
                "diagnostics": _diagnostics_payload(
                    self.backfill_plan.diagnostics
                ),
            },
        }


@dataclass(frozen=True)
class MonthlyRevenueRecoveryApplyResult:
    applied: bool
    rolled_back: bool
    plan: MonthlyRevenueRecoveryPlan
    availability_result: MonthlyRevenueAvailabilityMergeApplyResult | None
    backfill_result: MonthlyRevenueBackfillApplyResult | None
    mapping_backup_file: Path | None
    db_backup_file: Path | None
    evidence_file: Path
    error: str | None = None
    commit_observed_after_error: bool = False
    journal_file: Path | None = None


def plan_monthly_revenue_recovery(
    *,
    candidate_mapping_file: Path,
    snapshot_file: Path,
    scope_manifest_file: Path | None,
    target_mapping_file: Path,
    source_version: str,
) -> MonthlyRevenueRecoveryPlan:
    """建立 mapping merge 與 snapshot backfill 的共同 dry run。"""

    availability_plan = plan_monthly_revenue_availability_merge(
        candidate_file=Path(candidate_mapping_file),
        target_file=Path(target_mapping_file),
    )
    backfill_plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=Path(snapshot_file),
        availability_file=Path(candidate_mapping_file),
        source_version=source_version,
        scope_manifest_file=scope_manifest_file,
    )
    return MonthlyRevenueRecoveryPlan(
        availability_plan=availability_plan,
        backfill_plan=backfill_plan,
    )


def apply_monthly_revenue_recovery(
    *,
    candidate_mapping_file: Path,
    snapshot_file: Path,
    scope_manifest_file: Path | None,
    target_mapping_file: Path,
    db_file: Path,
    backup_dir: Path,
    evidence_file: Path,
    source_version: str,
    journal_file: Path | None = None,
) -> MonthlyRevenueRecoveryApplyResult:
    """先備份並套用 mapping／DB，DB 失敗時以 mapping 備份補償。"""

    candidate_mapping = (
        Path(candidate_mapping_file).expanduser().resolve(strict=False)
    )
    snapshot_source = Path(snapshot_file).expanduser().resolve(strict=False)
    scope_manifest = (
        Path(scope_manifest_file).expanduser().resolve(strict=False)
        if scope_manifest_file is not None
        else None
    )
    mapping_target = Path(target_mapping_file).expanduser().resolve(strict=False)
    db_target = Path(db_file).expanduser().resolve(strict=False)
    backup_root = Path(backup_dir).expanduser().resolve(strict=False)
    evidence_path = Path(evidence_file).expanduser().resolve(strict=False)
    journal_path = (
        Path(journal_file).expanduser().resolve(strict=False)
        if journal_file is not None
        else evidence_path.with_suffix(evidence_path.suffix + ".journal.json")
    )
    plan = plan_monthly_revenue_recovery(
        candidate_mapping_file=candidate_mapping,
        snapshot_file=snapshot_source,
        scope_manifest_file=scope_manifest,
        target_mapping_file=mapping_target,
        source_version=source_version,
    )
    operation_identity = _recovery_operation_identity(
        candidate_mapping_file=candidate_mapping,
        snapshot_file=snapshot_source,
        scope_manifest_file=scope_manifest,
        target_mapping_file=mapping_target,
        db_file=db_target,
        backup_dir=backup_root,
        evidence_file=evidence_path,
        journal_file=journal_path,
        source_version=source_version,
        expected_mapping_after_sha256=plan.availability_plan.merged_sha256,
    )
    mapping_before_sha256 = _sha256_if_file(mapping_target)
    previous_journal = _read_json_if_file(journal_path)
    previous_identity = previous_journal.get("operation_identity")
    previous_identity_matches = (
        isinstance(previous_identity, dict)
        and previous_identity == operation_identity
    )
    resume_journal = previous_journal if previous_identity_matches else {}
    base_evidence: dict[str, Any] = {
        "schema_version": "monthly-revenue-recovery.v1",
        "status": "blocked" if not plan.ready_for_apply else "pending",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "backup_dir": str(backup_root),
        "mapping_target": str(mapping_target),
        "db_target": str(db_target),
        "operation_identity": operation_identity,
        "previous_journal_identity_match": previous_identity_matches,
        "previous_journal_ignored": bool(previous_journal)
        and not previous_identity_matches,
        "plan": plan.to_payload(),
        "mapping_before_sha256": mapping_before_sha256,
        "mapping_expected_after_sha256": plan.availability_plan.merged_sha256,
        "mapping_backup_file": None,
        "db_backup_file": None,
        "journal_file": str(journal_path),
        "commit_observed_after_error": False,
        "rollback": {
            "attempted": False,
            "succeeded": False,
        },
        "error": None,
    }
    if not plan.ready_for_apply:
        _write_recovery_journal(
            journal_path,
            {
                "schema_version": "monthly-revenue-recovery-journal.v1",
                "operation_id": uuid4().hex,
                "state": "blocked",
                "captured_at": base_evidence["captured_at"],
                "mapping_target": str(mapping_target),
                "db_target": str(db_target),
                "mapping_before_sha256": mapping_before_sha256,
                "mapping_expected_after_sha256": plan.availability_plan.merged_sha256,
                "operation_identity": operation_identity,
                "plan": plan.to_payload(),
            },
        )
        _write_recovery_evidence(evidence_path, base_evidence)
        return MonthlyRevenueRecoveryApplyResult(
            applied=False,
            rolled_back=False,
            plan=plan,
            availability_result=None,
            backfill_result=None,
            mapping_backup_file=None,
            db_backup_file=None,
            evidence_file=evidence_path,
            journal_file=journal_path,
        )

    availability_result: MonthlyRevenueAvailabilityMergeApplyResult | None = None
    backfill_result: MonthlyRevenueBackfillApplyResult | None = None
    prior_mapping_backup_file = _path_from_journal(
        resume_journal,
        "mapping_backup_file",
    )
    prior_mapping_state = (
        str(resume_journal.get("state", "")) if resume_journal else ""
    )
    mapping_expected_after_sha256 = plan.availability_plan.merged_sha256
    mapping_already_applied = (
        prior_mapping_state
        in {"prepared", "mapping_applied", "db_committed", "db_committed_evidence_pending"}
        and prior_mapping_backup_file is not None
        and prior_mapping_backup_file.is_file()
        and _sha256_if_file(mapping_target)
        == resume_journal.get("mapping_expected_after_sha256")
    )
    mapping_backup_file: Path | None = (
        prior_mapping_backup_file if mapping_already_applied else None
    )
    db_backup_file: Path | None = None
    planned_mapping_backup_file = (
        mapping_backup_file
        if mapping_backup_file is not None
        else reserve_monthly_revenue_mapping_backup_path(
            mapping_target,
            backup_root,
            label="monthly_revenue_availability_merge",
        )
        if plan.availability_plan.changed
        else None
    )
    planned_db_backup_file = reserve_monthly_revenue_sqlite_backup_path(
        db_target,
        backup_root,
        label="mops_monthly_revenue_backfill",
    )
    operation_id = uuid4().hex
    journal_payload: dict[str, Any] = {
        "schema_version": "monthly-revenue-recovery-journal.v1",
        "operation_id": operation_id,
        "recovery_of": (
            resume_journal.get("operation_id") if previous_identity_matches else None
        ),
        "state": "prepared",
        "captured_at": base_evidence["captured_at"],
        "backup_dir": str(backup_root),
        "mapping_target": str(mapping_target),
        "db_target": str(db_target),
        "operation_identity": operation_identity,
        "previous_journal_identity_match": previous_identity_matches,
        "previous_journal_ignored": bool(previous_journal)
        and not previous_identity_matches,
        "mapping_before_sha256": mapping_before_sha256,
        "mapping_expected_after_sha256": mapping_expected_after_sha256,
        "mapping_backup_file": (
            str(planned_mapping_backup_file)
            if planned_mapping_backup_file is not None
            else None
        ),
        "db_backup_file": (
            str(planned_db_backup_file) if planned_db_backup_file is not None else None
        ),
        "mapping_already_applied": mapping_already_applied,
        "plan": plan.to_payload(),
        "error": None,
    }
    _write_recovery_journal(journal_path, journal_payload)
    rolled_back = False
    database_committed = False
    commit_observed_after_error = False
    error: str | None = None
    try:
        with monthly_revenue_availability_lock(mapping_target):
            availability_result = apply_monthly_revenue_availability_merge(
                plan=plan.availability_plan,
                backup_dir=backup_root,
                backup_file=planned_mapping_backup_file,
                lock_held=True,
            )
            mapping_backup_file = availability_result.backup_file or planned_mapping_backup_file
            if not availability_result.applied and plan.availability_plan.changed:
                raise RuntimeError("monthly revenue availability merge did not apply")
            journal_payload.update(
                {
                    "state": (
                        "mapping_applied"
                        if availability_result.applied
                        else "mapping_already_applied"
                    ),
                    "mapping_after_sha256": _sha256_if_file(mapping_target),
                    "mapping_backup_file": (
                        str(mapping_backup_file) if mapping_backup_file else None
                    ),
                }
            )
            _write_recovery_journal(journal_path, journal_payload)

            try:
                backfill_result = apply_mops_snapshot_monthly_revenue_backfill(
                    db_file=db_target,
                    backup_dir=backup_root,
                    snapshot_file=snapshot_source,
                    availability_file=candidate_mapping,
                    source_version=source_version,
                    scope_manifest_file=scope_manifest,
                    backup_file=planned_db_backup_file,
                )
                db_backup_file = backfill_result.backup_file
                if not backfill_result.applied:
                    raise RuntimeError("monthly revenue SQLite backfill did not apply")
                # backfill 已回傳成功即代表 transaction commit 完成；之後的
                # journal/evidence 例外不得再把 mapping 還原。
                database_committed = True
            except Exception as db_exc:
                if _database_contains_records(
                    db_target,
                    plan.backfill_plan.records,
                ):
                    commit_observed_after_error = True
                    error = f"{type(db_exc).__name__}: {db_exc}"
                    journal_payload.update(
                        {
                            "state": "db_committed_needs_review",
                            "commit_observed_after_error": True,
                            "error": error,
                        }
                    )
                    _write_recovery_journal(journal_path, journal_payload)
                else:
                    raise
            else:
                journal_payload.update(
                    {
                        "state": "db_committed",
                        "db_backup_file": (
                            str(db_backup_file) if db_backup_file else None
                        ),
                    }
                )
                _write_recovery_journal(journal_path, journal_payload)
    except Exception as exc:
        if database_committed:
            commit_observed_after_error = True
        if error is None:
            error = f"{type(exc).__name__}: {exc}"
        mapping_mutated_by_operation = (
            availability_result is not None and availability_result.applied
        )
        mapping_can_be_compensated = mapping_mutated_by_operation or mapping_already_applied
        if (
            not database_committed
            and not commit_observed_after_error
            and mapping_can_be_compensated
        ):
            base_evidence["rollback"]["attempted"] = True
            try:
                if mapping_backup_file is None:
                    raise RuntimeError("mapping backup is unavailable")
                _restore_mapping_from_backup(
                    mapping_backup_file,
                    mapping_target,
                    expected_current_sha256=mapping_expected_after_sha256,
                )
            except Exception as restore_exc:
                error = (
                    f"{error}; mapping restore failed: "
                    f"{type(restore_exc).__name__}: {restore_exc}"
                )
            else:
                rolled_back = True
                base_evidence["rollback"]["succeeded"] = True
        journal_payload.update(
            {
                "state": (
                    "db_committed_needs_review"
                    if commit_observed_after_error
                    else "rolled_back"
                    if rolled_back
                    else "failed"
                ),
                "mapping_after_sha256": _sha256_if_file(mapping_target),
                "commit_observed_after_error": commit_observed_after_error,
                "error": error,
            }
        )
        _write_recovery_journal(journal_path, journal_payload)

    applied = error is None and database_committed
    base_evidence["status"] = (
        "applied"
        if applied
        else "db_committed_needs_review"
        if commit_observed_after_error
        else "rolled_back"
        if rolled_back
        else "failed"
    )
    base_evidence["mapping_backup_file"] = (
        str(mapping_backup_file) if mapping_backup_file else None
    )
    base_evidence["db_backup_file"] = (
        str(db_backup_file) if db_backup_file else None
    )
    base_evidence["mapping_after_sha256"] = _sha256_if_file(mapping_target)
    base_evidence["error"] = error
    base_evidence["commit_observed_after_error"] = commit_observed_after_error
    try:
        _write_recovery_evidence(evidence_path, base_evidence)
    except Exception as evidence_exc:
        journal_payload.update(
            {
                "state": (
                    "db_committed_evidence_pending"
                    if applied or commit_observed_after_error
                    else "evidence_write_failed"
                ),
                "evidence_error": f"{type(evidence_exc).__name__}: {evidence_exc}",
            }
        )
        _write_recovery_journal(journal_path, journal_payload)
        raise
    if applied:
        journal_payload.update(
            {
                "state": "completed",
                "evidence_file": str(evidence_path),
            }
        )
        _write_recovery_journal(journal_path, journal_payload)
    return MonthlyRevenueRecoveryApplyResult(
        applied=applied,
        rolled_back=rolled_back,
        plan=plan,
        availability_result=availability_result,
        backfill_result=backfill_result,
        mapping_backup_file=mapping_backup_file,
        db_backup_file=db_backup_file,
        evidence_file=evidence_path,
        error=error,
        commit_observed_after_error=commit_observed_after_error,
        journal_file=journal_path,
    )


def _restore_mapping_from_backup(
    backup_file: Path,
    target_file: Path,
    *,
    expected_current_sha256: str | None = None,
) -> None:
    """以同目錄 temporary + replace 補償 mapping，避免半檔。"""

    target_file = Path(target_file)
    with monthly_revenue_availability_lock(target_file):
        if expected_current_sha256 is not None:
            actual_current_sha256 = _sha256_if_file(target_file)
            if actual_current_sha256 != expected_current_sha256:
                raise RuntimeError(
                    "monthly revenue availability target changed before compensation; "
                    f"expected={expected_current_sha256}; actual={actual_current_sha256}"
                )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target_file.parent,
                prefix=f".{target_file.name}.{uuid4().hex}.",
                suffix=".restore",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
            shutil.copy2(Path(backup_file), temporary_path)
            os.replace(temporary_path, target_file)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


def _write_json_atomic(path: Path, payload: MappingLike) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.{uuid4().hex}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _sha256_if_file(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recovery_operation_identity(
    *,
    candidate_mapping_file: Path,
    snapshot_file: Path,
    scope_manifest_file: Path | None,
    target_mapping_file: Path,
    db_file: Path,
    backup_dir: Path,
    evidence_file: Path,
    journal_file: Path,
    source_version: str,
    expected_mapping_after_sha256: str | None,
) -> dict[str, Any]:
    """建立可重算的 operation identity，避免跨批次誤用舊 backup。"""

    def input_identity(path: Path | None) -> dict[str, str | None] | None:
        if path is None:
            return None
        resolved = Path(path).expanduser().resolve(strict=False)
        return {
            "path": str(resolved),
            "sha256": _sha256_if_file(resolved),
        }

    return {
        "schema_version": "monthly-revenue-recovery-operation.v1",
        "source_version": str(source_version).strip(),
        "candidate_mapping": input_identity(candidate_mapping_file),
        "snapshot": input_identity(snapshot_file),
        "scope_manifest": input_identity(scope_manifest_file),
        "target_mapping_path": str(
            Path(target_mapping_file).expanduser().resolve(strict=False)
        ),
        "db_path": str(Path(db_file).expanduser().resolve(strict=False)),
        "backup_dir": str(Path(backup_dir).expanduser().resolve(strict=False)),
        "evidence_path": str(
            Path(evidence_file).expanduser().resolve(strict=False)
        ),
        "journal_path": str(Path(journal_file).expanduser().resolve(strict=False)),
        "expected_mapping_after_sha256": expected_mapping_after_sha256,
    }


def _read_json_if_file(path: Path) -> dict[str, Any]:
    """讀取既有 journal；格式錯誤時視為不可恢復的舊狀態。"""

    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _path_from_journal(
    payload: dict[str, Any],
    field_name: str,
) -> Path | None:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _write_recovery_journal(path: Path, payload: dict[str, Any]) -> None:
    """以 atomic replace 持久化跨檔更新 phase，供 crash recovery 辨識。"""

    _write_json_atomic(Path(path), payload)


def _write_recovery_evidence(path: Path, payload: dict[str, Any]) -> None:
    """以 atomic replace 寫入完成或阻擋證據。"""

    _write_json_atomic(Path(path), payload)


def _database_contains_records(
    db_file: Path,
    records: tuple[MonthlyRevenueRecord, ...],
) -> bool:
    """唯讀確認預期列已 commit，避免 DB 已提交卻補償 mapping。"""

    if not records or not Path(db_file).is_file():
        return False
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{Path(db_file).as_posix()}?mode=ro",
            uri=True,
            timeout=30,
        )
        connection.execute("PRAGMA query_only=ON")
        for record in records:
            row = connection.execute(
                """
                SELECT as_of_date, announced_date, available_date, revenue,
                       source, quality
                FROM fundamental_monthly_revenues
                WHERE stock_code = ? AND period = ? AND source_version = ?
                """,
                (
                    str(record.stock_code),
                    str(record.period),
                    str(record.source_version),
                ),
            ).fetchone()
            if row is None:
                return False
            expected = (
                record.as_of_date.isoformat(),
                record.announced_date.isoformat()
                if record.announced_date is not None
                else None,
                record.available_date.isoformat(),
                str(record.revenue),
                str(record.source),
                record.quality.value,
            )
            if tuple(row) != expected:
                return False
        return True
    except (OSError, sqlite3.Error, AttributeError, TypeError, ValueError):
        return False
    finally:
        if connection is not None:
            connection.close()


def _diagnostics_payload(items: tuple[object, ...]) -> list[dict[str, str]]:
    return [
        {
            "code": str(getattr(item, "code", "")),
            "stock_code": str(getattr(item, "stock_code", "")),
            "message": str(getattr(item, "message", "")),
        }
        for item in items
    ]


MappingLike = dict[str, Any]
