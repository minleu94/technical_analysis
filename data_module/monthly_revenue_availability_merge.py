"""受控合併月營收 availability candidate 到正式 mapping 的工具。

候選建置、驗證與正式 mapping 寫入刻意拆開：本模組的 plan 是唯讀，只有
呼叫端明確要求 apply 時才會先備份目標、再以同目錄 atomic replace 更新 CSV。
相同 natural key 若內容相同視為 idempotent；內容不同則 fail closed，不猜
哪一筆應該覆蓋既有證據。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from data_module.backup_retention import create_retained_backup
from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)
from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
    FundamentalAvailabilityOverride,
    load_monthly_revenue_availability_overrides_csv,
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

    existing = existing_result.overrides if target_path.exists() else {}
    candidate = candidate_result.overrides
    merged: dict[tuple[str, str], FundamentalAvailabilityOverride] = dict(existing)
    added_count = 0
    unchanged_count = 0
    conflict_count = 0
    for key, override in sorted(candidate.items()):
        previous = existing.get(key)
        if previous is None:
            merged[key] = override
            added_count += 1
            continue
        if _override_fingerprint(previous) == _override_fingerprint(override):
            unchanged_count += 1
            continue
        conflict_count += 1
        diagnostics.append(
            _diagnostic(
                "merge_conflict",
                "candidate and existing monthly revenue availability rows disagree; "
                f"natural_key={key[0]}|{key[1]}; existing_source={previous.source}; "
                f"candidate_source={override.source}",
                stock_code=key[0],
            )
        )

    rows = tuple(
        _override_to_row(merged[key])
        for key in sorted(merged)
    )
    return MonthlyRevenueAvailabilityMergePlan(
        target_file=target_path,
        candidate_file=candidate_path,
        target_exists=target_path.exists(),
        existing_count=len(existing),
        candidate_count=len(candidate),
        added_count=added_count,
        unchanged_count=unchanged_count,
        conflict_count=conflict_count,
        merged_rows=rows,
        diagnostics=tuple(diagnostics),
    )


def apply_monthly_revenue_availability_merge(
    *,
    plan: MonthlyRevenueAvailabilityMergePlan,
    backup_dir: Path,
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

    backup_file = create_retained_backup(
        plan.target_file,
        Path(backup_dir),
        label="monthly_revenue_availability_merge",
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

    return MonthlyRevenueAvailabilityMergeApplyResult(
        applied=True,
        backup_file=backup_file,
        output_file=plan.target_file,
        plan=plan,
    )


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
