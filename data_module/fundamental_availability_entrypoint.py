"""月營收公告日 mapping 的正式驗證入口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from data_module.fundamental_availability_sources import (
    FundamentalAvailabilityOverride,
    load_monthly_revenue_availability_overrides_csv,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES = frozenset(
    {
        "manual.twse_monthly_revenue_announcement_log",
        "manual.available_date_mapping",
        "twse.monthly_revenue_announcement",
        "tpex.monthly_revenue_announcement",
        "mops.monthly_revenue_announcement",
        "tej.monthly_revenue_announcement_pit",
    }
)
MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS = 45


@dataclass(frozen=True)
class MonthlyRevenueAvailabilityValidationResult:
    valid: bool
    accepted_count: int
    source_versions: tuple[str, ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_versions", tuple(self.source_versions))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Monthly Revenue Availability Validation",
                "",
                f"- valid: {str(self.valid).lower()}",
                f"- accepted_count: {self.accepted_count}",
                f"- source_versions: {', '.join(self.source_versions) or 'none'}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


def validate_monthly_revenue_availability_file(
    path: Path,
) -> MonthlyRevenueAvailabilityValidationResult:
    load_result = load_monthly_revenue_availability_overrides_csv(Path(path))
    diagnostics = list(load_result.diagnostics)
    for override in load_result.overrides.values():
        if override.source not in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES:
            diagnostics.append(_unsupported_source_diagnostic(override))
        if override.available_date > override.as_of_date + timedelta(
            days=MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS
        ):
            diagnostics.append(_unreasonably_late_available_date_diagnostic(override))

    accepted = tuple(
        override
        for override in load_result.overrides.values()
        if override.source in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
        and override.available_date
        <= override.as_of_date + timedelta(days=MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS)
    )
    return MonthlyRevenueAvailabilityValidationResult(
        valid=bool(accepted) and not diagnostics,
        accepted_count=len(accepted),
        source_versions=tuple(sorted({item.source_version for item in accepted})),
        diagnostics=tuple(diagnostics),
    )


def _unsupported_source_diagnostic(
    override: FundamentalAvailabilityOverride,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code="fundamental_availability.unsupported_available_date_source",
        factor_name="fundamental.availability",
        stock_code=override.stock_code,
        message=(
            "monthly revenue availability source is not in allowed source list; "
            f"period={override.period}; source={override.source}"
        ),
    )


def _unreasonably_late_available_date_diagnostic(
    override: FundamentalAvailabilityOverride,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code="fundamental_availability.available_date_unreasonably_late",
        factor_name="fundamental.availability",
        stock_code=override.stock_code,
        message=(
            "monthly revenue availability date is outside the allowed disclosure window; "
            f"period={override.period}; as_of_date={override.as_of_date.isoformat()}; "
            f"available_date={override.available_date.isoformat()}; "
            f"max_lag_days={MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS}"
        ),
    )
