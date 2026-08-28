"""月營收 availability candidate 的唯讀檢查與合併預覽。

候選 mapping 可能由官方公告日／可得日 builder 產生，但在 owner 確認前
不能被當成正式 mapping。這個模組只讀取候選與正式 target，並回傳適合
狀態頁投影的 metadata；不會建立備份、改寫 CSV 或寫入 SQLite。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)
from data_module.fundamental_availability_sources import (
    load_monthly_revenue_availability_overrides_csv,
)
from data_module.monthly_revenue_availability_merge import (
    plan_monthly_revenue_availability_merge,
)


@dataclass(frozen=True)
class MonthlyRevenueAvailabilityCandidateInfo:
    """availability candidate 的安全 read model。"""

    path: Path
    status: str
    row_count: int = 0
    latest_period: str | None = None
    latest_available_date: str | None = None
    source_versions: tuple[str, ...] = ()
    diagnostic_count: int = 0
    added_count: int | None = None
    unchanged_count: int | None = None
    conflict_count: int | None = None
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())
        object.__setattr__(self, "source_versions", tuple(self.source_versions))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def inspect_monthly_revenue_availability_candidate(
    path: Path,
    *,
    target_file: Path | None = None,
) -> MonthlyRevenueAvailabilityCandidateInfo:
    """唯讀檢查候選 mapping，必要時附帶 target merge plan。

    ``target_file`` 只用於建立 in-memory merge plan；此函式不會呼叫 apply，
    因此不會產生 backup 或 atomic replace。
    """

    candidate_path = Path(path).expanduser().resolve(strict=False)
    if not candidate_path.is_file():
        return MonthlyRevenueAvailabilityCandidateInfo(
            path=candidate_path,
            status="missing",
            diagnostic_count=1,
            diagnostics=(f"候選 mapping 不存在：{candidate_path}",),
        )

    try:
        load_result = load_monthly_revenue_availability_overrides_csv(candidate_path)
        validation = validate_monthly_revenue_availability_file(candidate_path)
    except (OSError, TypeError, ValueError) as exc:
        return MonthlyRevenueAvailabilityCandidateInfo(
            path=candidate_path,
            status="error",
            diagnostic_count=1,
            diagnostics=(f"候選 mapping 讀取失敗：{exc}",),
        )

    overrides = load_result.overrides
    diagnostics = tuple(
        str(item.message).strip()
        for item in validation.diagnostics
        if str(item.message).strip()
    )
    if not overrides or diagnostics or not validation.valid:
        return MonthlyRevenueAvailabilityCandidateInfo(
            path=candidate_path,
            status="invalid",
            row_count=len(overrides),
            latest_period=_latest_period(overrides),
            latest_available_date=_latest_available_date(overrides),
            source_versions=validation.source_versions,
            diagnostic_count=len(diagnostics),
            diagnostics=diagnostics[:3],
        )

    merge_fields: dict[str, int | None] = {
        "added_count": None,
        "unchanged_count": None,
        "conflict_count": None,
    }
    status = "ready_for_merge"
    if target_file is not None:
        try:
            plan = plan_monthly_revenue_availability_merge(
                candidate_file=candidate_path,
                target_file=Path(target_file),
            )
            merge_fields = {
                "added_count": plan.added_count,
                "unchanged_count": plan.unchanged_count,
                "conflict_count": plan.conflict_count,
            }
            plan_diagnostics = tuple(
                str(item.message).strip()
                for item in plan.diagnostics
                if str(item.message).strip()
            )
            if plan.conflict_count:
                status = "conflict"
                diagnostics = plan_diagnostics
            elif plan.diagnostics:
                status = "merge_blocked"
                diagnostics = plan_diagnostics
            elif plan.added_count == 0:
                status = "already_merged"
        except (OSError, TypeError, ValueError) as exc:
            status = "error"
            diagnostics = (f"候選 mapping merge preview 失敗：{exc}",)

    return MonthlyRevenueAvailabilityCandidateInfo(
        path=candidate_path,
        status=status,
        row_count=len(overrides),
        latest_period=_latest_period(overrides),
        latest_available_date=_latest_available_date(overrides),
        source_versions=validation.source_versions,
        diagnostic_count=len(diagnostics),
        added_count=merge_fields["added_count"],
        unchanged_count=merge_fields["unchanged_count"],
        conflict_count=merge_fields["conflict_count"],
        diagnostics=diagnostics[:3],
    )


def _latest_period(overrides: object) -> str | None:
    values = getattr(overrides, "keys", lambda: ())()
    periods = [str(key[1]).strip() for key in values if isinstance(key, tuple) and len(key) > 1]
    return max(periods) if periods else None


def _latest_available_date(overrides: object) -> str | None:
    values = getattr(overrides, "values", lambda: ())()
    dates = [
        item.available_date.isoformat()
        for item in values
        if getattr(item, "available_date", None) is not None
    ]
    return max(dates) if dates else None
