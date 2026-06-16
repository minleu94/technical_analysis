"""估值 factor adapter：只輸出相對估值區間，不輸出交易建議。"""

from __future__ import annotations

from dataclasses import dataclass

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorRecord, MissingPolicy
from decision_module.factors.valuation_policy import (
    ValuationBand,
    ValuationObservation,
    classify_relative_valuation,
)


@dataclass(frozen=True)
class ValuationFactorBuildResult:
    records: tuple[FactorRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def build_relative_valuation_factor(
    observation: ValuationObservation,
) -> ValuationFactorBuildResult:
    policy_result = classify_relative_valuation(observation)
    diagnostics = tuple(policy_result.diagnostics)

    if policy_result.band == ValuationBand.UNAVAILABLE:
        return ValuationFactorBuildResult(records=(), diagnostics=diagnostics)

    record = FactorRecord(
        factor_name=f"valuation.{policy_result.metric_name}.relative_band",
        stock_code=policy_result.stock_code,
        as_of_date=policy_result.as_of_date,
        available_date=policy_result.available_date,
        value=policy_result.band.value,
        score_bp=None,
        quality=policy_result.quality,
        missing_policy=MissingPolicy.SKIP,
        source_version=policy_result.source_version,
        metadata=policy_result.to_metadata(),
    )
    return ValuationFactorBuildResult(records=(record,), diagnostics=diagnostics)
