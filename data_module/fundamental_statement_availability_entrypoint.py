"""季度財報 available_date mapping 的正式驗證入口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from data_module.fundamental_availability import RETROACTIVE_STATEMENT_BASELINE_SOURCE
from data_module.fundamental_statement_availability_sources import (
    StatementAvailabilityOverride,
    load_statement_availability_overrides_csv,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


STATEMENT_ALLOWED_AVAILABILITY_SOURCES = frozenset(
    {
        "manual.statement_available_date_mapping",
        "tej.statement_announcement_pit",
        RETROACTIVE_STATEMENT_BASELINE_SOURCE,
    }
)
STATEMENT_MAX_AVAILABLE_LAG_DAYS = 120


@dataclass(frozen=True)
class StatementAvailabilityValidationResult:
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
                "# Statement Availability Validation",
                "",
                f"- valid: {str(self.valid).lower()}",
                f"- accepted_count: {self.accepted_count}",
                f"- source_versions: {', '.join(self.source_versions) or 'none'}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


def validate_statement_availability_file(
    path: Path,
) -> StatementAvailabilityValidationResult:
    load_result = load_statement_availability_overrides_csv(Path(path))
    diagnostics = list(load_result.diagnostics)
    for override in load_result.overrides.values():
        if override.source not in STATEMENT_ALLOWED_AVAILABILITY_SOURCES:
            diagnostics.append(_unsupported_source_diagnostic(override))
        if _requires_disclosure_window_check(override) and override.available_date > (
            override.as_of_date + timedelta(days=STATEMENT_MAX_AVAILABLE_LAG_DAYS)
        ):
            diagnostics.append(_unreasonably_late_available_date_diagnostic(override))

    accepted = tuple(
        override
        for override in load_result.overrides.values()
        if override.source in STATEMENT_ALLOWED_AVAILABILITY_SOURCES
        and (
            not _requires_disclosure_window_check(override)
            or override.available_date
            <= override.as_of_date + timedelta(days=STATEMENT_MAX_AVAILABLE_LAG_DAYS)
        )
    )
    return StatementAvailabilityValidationResult(
        valid=bool(accepted) and not diagnostics,
        accepted_count=len(accepted),
        source_versions=tuple(sorted({item.source_version for item in accepted})),
        diagnostics=tuple(diagnostics),
    )


def _unsupported_source_diagnostic(
    override: StatementAvailabilityOverride,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code="fundamental_statement_availability.unsupported_available_date_source",
        factor_name="fundamental.statement_availability",
        stock_code=override.stock_code,
        message=(
            "statement availability source is not in allowed source list; "
            f"statement_type={override.statement_type}; period={override.period}; "
            f"source={override.source}"
        ),
    )


def _unreasonably_late_available_date_diagnostic(
    override: StatementAvailabilityOverride,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code="fundamental_statement_availability.available_date_unreasonably_late",
        factor_name="fundamental.statement_availability",
        stock_code=override.stock_code,
        message=(
            "statement availability date is outside the allowed disclosure window; "
            f"statement_type={override.statement_type}; period={override.period}; "
            f"as_of_date={override.as_of_date.isoformat()}; "
            f"available_date={override.available_date.isoformat()}; "
            f"max_lag_days={STATEMENT_MAX_AVAILABLE_LAG_DAYS}"
        ),
    )


def _requires_disclosure_window_check(
    override: StatementAvailabilityOverride,
) -> bool:
    return override.source != RETROACTIVE_STATEMENT_BASELINE_SOURCE
