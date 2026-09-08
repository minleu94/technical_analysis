"""受控合併月營收 availability candidate 到正式 mapping 的工具。

候選建置、驗證與正式 mapping 寫入刻意拆開：本模組的 plan 是唯讀，只有
呼叫端明確要求 apply 時才會先備份目標、再以同目錄 atomic replace 更新 CSV。
相同 natural key 與 revision 若內容相同視為 idempotent；同一 revision
內容不同則 fail closed，不猜哪一筆應該覆蓋既有證據。不同 revision
會以 append-only 方式保留，讓 provider 能依 decision date 讀取歷史 mapping。
"""

from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import os
from pathlib import Path
import shutil
import tempfile
import time
from uuid import uuid4

from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)
from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
    FundamentalAvailabilityOverride,
    load_monthly_revenue_availability_overrides_csv,
)
from data_module.ml_storage_capacity import (
    acquire_heavy_chain_reservation,
    release_heavy_chain_reservation,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


@dataclass(frozen=True)
class MonthlyRevenueAvailabilityMergePlan:
    """候選與既有 mapping 的唯讀合併計畫。"""

    target_file: Path
    candidate_file: Path
    target_exists: bool
    existing_count: int
    candidate_count: int
    added_count: int
    unchanged_count: int
    conflict_count: int
    merged_rows: tuple[dict[str, str], ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()
    target_sha256: str | None = None
    merged_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_file", Path(self.target_file))
        object.__setattr__(self, "candidate_file", Path(self.candidate_file))
        object.__setattr__(
            self,
            "merged_rows",
            tuple(dict(row) for row in self.merged_rows),
        )
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def ready_for_apply(self) -> bool:
        return bool(self.candidate_count) and not self.diagnostics and self.conflict_count == 0

    @property
    def changed(self) -> bool:
        return self.added_count > 0

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Monthly Revenue Availability Merge Plan",
                "",
                f"- ready_for_apply: {str(self.ready_for_apply).lower()}",
                f"- target_exists: {str(self.target_exists).lower()}",
                f"- target_file: {self.target_file}",
                f"- candidate_file: {self.candidate_file}",
                f"- existing_count: {self.existing_count}",
                f"- candidate_count: {self.candidate_count}",
                f"- added_count: {self.added_count}",
                f"- unchanged_count: {self.unchanged_count}",
                f"- conflict_count: {self.conflict_count}",
                f"- merged_count: {len(self.merged_rows)}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


@dataclass(frozen=True)
class MonthlyRevenueAvailabilityMergeApplyResult:
    applied: bool
    backup_file: Path | None
    output_file: Path
    plan: MonthlyRevenueAvailabilityMergePlan


def plan_monthly_revenue_availability_merge(
    *,
    candidate_file: Path,
    target_file: Path,
) -> MonthlyRevenueAvailabilityMergePlan:
    """驗證候選並建立合併計畫；此函式不建立或改寫任何檔案。"""

    candidate_path = Path(candidate_file).expanduser().resolve(strict=False)
    target_path = Path(target_file).expanduser().resolve(strict=False)
    diagnostics: list[FactorDiagnostic] = []

    validation = validate_monthly_revenue_availability_file(candidate_path)
    diagnostics.extend(validation.diagnostics)
    candidate_result = load_monthly_revenue_availability_overrides_csv(candidate_path)
    diagnostics.extend(candidate_result.diagnostics)

    existing_result = load_monthly_revenue_availability_overrides_csv(target_path)
    if target_path.exists():
        diagnostics.extend(existing_result.diagnostics)
    elif not target_path.parent.is_dir():
        diagnostics.append(
            _diagnostic(
                "target_parent_missing",
                f"monthly revenue availability target parent directory is missing; path={target_path.parent}",
            )
        )

    existing_rows = (
        _revision_rows(existing_result)
        if target_path.exists()
        else ()
    )
    candidate_rows = _revision_rows(candidate_result)
    existing = {
        _revision_identity(override): override
        for override in existing_rows
    }
    candidate = {
        _revision_identity(override): override
        for override in candidate_rows
    }
    merged: dict[tuple[str, str, int], FundamentalAvailabilityOverride] = dict(existing)
    added_count = 0
    unchanged_count = 0
    conflict_count = 0
    for revision_key, override in sorted(candidate.items()):
        previous = existing.get(revision_key)
        if previous is None:
            merged[revision_key] = override
            added_count += 1
            continue
        if _override_fingerprint(previous) == _override_fingerprint(override):
            unchanged_count += 1
            continue
        conflict_count += 1
        natural_key = (override.stock_code, override.period)
        diagnostics.append(
            _diagnostic(
                "merge_conflict",
                "candidate and existing monthly revenue availability rows disagree; "
                f"natural_key={natural_key[0]}|{natural_key[1]}; "
                f"revision={override.revision}; existing_source={previous.source}; "
                f"candidate_source={override.source}",
                stock_code=natural_key[0],
            )
        )

    rows = tuple(
        _override_to_row(merged[key])
        for key in sorted(
            merged,
            key=lambda item: (item[0], item[1], item[2]),
        )
    )
    target_sha256 = _file_sha256(target_path) if target_path.is_file() else None
    merged_sha256 = _serialized_rows_sha256(rows)
    return MonthlyRevenueAvailabilityMergePlan(
        target_file=target_path,
        candidate_file=candidate_path,
        target_exists=target_path.exists(),
        existing_count=len(existing_rows),
        candidate_count=len(candidate_rows),
        added_count=added_count,
        unchanged_count=unchanged_count,
        conflict_count=conflict_count,
        merged_rows=rows,
        diagnostics=tuple(diagnostics),
        target_sha256=target_sha256,
        merged_sha256=merged_sha256,
    )


def apply_monthly_revenue_availability_merge(
    *,
    plan: MonthlyRevenueAvailabilityMergePlan,
    backup_dir: Path,
    backup_file: Path | None = None,
    lock_held: bool = False,
) -> MonthlyRevenueAvailabilityMergeApplyResult:
    """套用已驗證計畫；先備份，再以 atomic replace 發布完整 CSV。"""

    if not plan.ready_for_apply:
        return MonthlyRevenueAvailabilityMergeApplyResult(
            applied=False,
            backup_file=None,
            output_file=plan.target_file,
            plan=plan,
        )
    if not plan.changed:
        return MonthlyRevenueAvailabilityMergeApplyResult(
            applied=False,
            backup_file=None,
            output_file=plan.target_file,
            plan=plan,
        )
    if not plan.target_file.parent.is_dir():
        raise FileNotFoundError(plan.target_file.parent)

    lock_context = (
        monthly_revenue_availability_lock(plan.target_file)
        if not lock_held
        else _null_context()
    )
    with lock_context:
        current_sha256 = (
            _file_sha256(plan.target_file)
            if plan.target_file.is_file()
            else None
        )
        if current_sha256 != plan.target_sha256:
            raise RuntimeError(
                "monthly revenue availability target changed after planning; "
                f"expected={plan.target_sha256}; actual={current_sha256}"
            )
        backup_file = _create_unique_mapping_backup(
            plan.target_file,
            Path(backup_dir),
            label="monthly_revenue_availability_merge",
            backup_file=backup_file,
        )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8-sig",
                newline="",
                dir=plan.target_file.parent,
                prefix=f".{plan.target_file.name}.{uuid4().hex}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                writer = csv.DictWriter(
                    handle,
                    fieldnames=MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(plan.merged_rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, plan.target_file)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
        actual_merged_sha256 = _file_sha256(plan.target_file)
        if plan.merged_sha256 is not None and actual_merged_sha256 != plan.merged_sha256:
            raise RuntimeError(
                "monthly revenue availability target hash differs after atomic replace; "
                f"expected={plan.merged_sha256}; actual={actual_merged_sha256}"
            )

    return MonthlyRevenueAvailabilityMergeApplyResult(
        applied=True,
        backup_file=backup_file,
        output_file=plan.target_file,
        plan=plan,
    )


def _create_unique_mapping_backup(
    source_file: Path,
    backup_dir: Path,
    *,
    label: str,
    backup_file: Path | None = None,
) -> Path | None:
    """建立任務專用 mapping 備份，不清理其他日期或 prefix 的檔案。"""

    source_file = Path(source_file)
    if not source_file.is_file():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_file = Path(backup_file) if backup_file is not None else (
        backup_dir
        / f"{source_file.stem}_{label}_{timestamp}_{uuid4().hex}.csv"
    )
    backup_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, backup_file)
    return backup_file


def reserve_monthly_revenue_mapping_backup_path(
    source_file: Path,
    backup_dir: Path,
    *,
    label: str,
) -> Path | None:
    """預留本任務 mapping 備份路徑；不建立檔案也不清理既有備份。"""

    source_file = Path(source_file)
    if not source_file.is_file():
        return None
    backup_dir = Path(backup_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return (
        backup_dir
        / f"{source_file.stem}_{label}_{timestamp}_{uuid4().hex}.csv"
    )


@contextmanager
def monthly_revenue_availability_lock(
    target_file: Path,
    *,
    timeout_seconds: float = 30.0,
):
    """以既有跨程序 OS advisory lock 序列化受控 mapping writer。"""

    lock_file = Path(target_file).with_name(
        f".{Path(target_file).name}.monthly-revenue.lock"
    )
    deadline = time.monotonic() + timeout_seconds
    reservation = None
    while reservation is None:
        reservation = acquire_heavy_chain_reservation(lock_file)
        if reservation is not None:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"monthly revenue availability lock is busy: {lock_file}"
            )
        time.sleep(0.05)
    try:
        yield lock_file
    finally:
        release_heavy_chain_reservation(reservation)


@contextmanager
def _null_context():
    yield None


def _file_sha256(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _serialized_rows_sha256(rows: tuple[dict[str, str], ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return hashlib.sha256(("\ufeff" + stream.getvalue()).encode("utf-8")).hexdigest()


def _override_fingerprint(
    override: FundamentalAvailabilityOverride,
) -> tuple[str, ...]:
    return (
        override.stock_code,
        override.period,
        override.as_of_date.isoformat(),
        override.announced_date.isoformat() if override.announced_date else "",
        override.available_date.isoformat(),
        override.source,
        override.source_version,
        override.evidence_class,
        override.source_hash,
        str(override.revision) if override.provenance_mode == "formal_v2" else "",
        (
            str(override.parent_revision)
            if override.provenance_mode == "formal_v2" and override.parent_revision is not None
            else ""
        ),
    )


def _revision_identity(
    override: FundamentalAvailabilityOverride,
) -> tuple[str, str, int]:
    """以自然鍵與 revision 識別 append-only mapping row。"""

    return (override.stock_code, override.period, override.revision)


def _revision_rows(
    result: object,
) -> tuple[FundamentalAvailabilityOverride, ...]:
    """展開 loader 保留的 revision history；舊型結果則退回 latest override。"""

    history = getattr(result, "revision_history", {})
    if history:
        return tuple(
            override
            for values in history.values()
            for override in values
        )
    overrides = getattr(result, "overrides", {})
    return tuple(overrides.values())


def _override_to_row(override: FundamentalAvailabilityOverride) -> dict[str, str]:
    is_formal = override.provenance_mode == "formal_v2"
    return {
        "stock_code": override.stock_code,
        "period": override.period,
        "as_of_date": override.as_of_date.isoformat(),
        "announced_date": (
            override.announced_date.isoformat() if override.announced_date else ""
        ),
        "available_date": override.available_date.isoformat(),
        "source": override.source,
        "source_version": override.source_version,
        "availability_contract_version": "formal-availability.v2" if is_formal else "",
        "evidence_class": override.evidence_class if is_formal else "",
        "source_hash": override.source_hash if is_formal else "",
        "revision": str(override.revision) if is_formal else "",
        "parent_revision": (
            str(override.parent_revision)
            if is_formal and override.parent_revision is not None
            else ""
        ),
    }


def _diagnostic(
    code: str,
    message: str,
    *,
    stock_code: str = "",
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=f"fundamental_availability.{code}",
        factor_name="fundamental.availability",
        stock_code=stock_code,
        message=message,
    )
