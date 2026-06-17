"""Valuation metric source policy for Month 5 fundamental layer."""

from __future__ import annotations

from dataclasses import dataclass

from decision_module.factors.factor_dtos import FactorDiagnostic


@dataclass(frozen=True)
class ValuationSourcePolicyInspection:
    ready_metrics: tuple[str, ...]
    pending_metrics: tuple[str, ...]
    diagnostics: tuple[FactorDiagnostic, ...]
    scoring_engine_connected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ready_metrics", tuple(self.ready_metrics))
        object.__setattr__(self, "pending_metrics", tuple(self.pending_metrics))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Valuation Source Policy",
                "",
                f"- ready_metrics: {', '.join(self.ready_metrics) or 'none'}",
                f"- pending_metrics: {', '.join(self.pending_metrics) or 'none'}",
                f"- diagnostics: {len(self.diagnostics)}",
                f"- scoring_engine_connected: {str(self.scoring_engine_connected).lower()}",
            ]
        )


def inspect_valuation_source_policy() -> ValuationSourcePolicyInspection:
    diagnostics = (
        FactorDiagnostic(
            code="valuation_source_policy.pb_external_source_required",
            factor_name="valuation.pb",
            stock_code="",
            message=(
                "P/B presentation is enabled only for governed external observations "
                "or explicit future backfill records; the system does not infer book "
                "value per share from incomplete statement data"
            ),
        ),
        FactorDiagnostic(
            code="valuation_source_policy.ps_external_source_required",
            factor_name="valuation.ps",
            stock_code="",
            message=(
                "P/S presentation is enabled only for governed external observations "
                "or explicit future backfill records; the system does not infer market "
                "cap or TTM sales inside ScoringEngine"
            ),
        ),
    )
    return ValuationSourcePolicyInspection(
        ready_metrics=("pe", "pb", "ps"),
        pending_metrics=(),
        diagnostics=diagnostics,
        scoring_engine_connected=False,
    )
