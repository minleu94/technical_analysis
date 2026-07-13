"""Verifies P0 evidence readiness without applying source acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_contract_registry import build_p0_source_contract_registry


@dataclass(frozen=True)
class P0SourceAcceptanceVerification:
    source_id: str
    status: str
    diagnostics: tuple[str, ...]
    coverage_bp: int
    human_decision: str = "requires_human_acceptance"
    downstream_eligibility: str = "none"
    formal_acceptance_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "diagnostics": list(self.diagnostics),
            "coverage_bp": self.coverage_bp,
            "human_decision": self.human_decision,
            "downstream_eligibility": self.downstream_eligibility,
            "formal_acceptance_applied": self.formal_acceptance_applied,
        }


class P0SourceAcceptanceVerifier:
    def __init__(self, *, minimum_coverage_bp: int = 8000) -> None:
        if not 0 <= minimum_coverage_bp <= 10000:
            raise ValueError("minimum_coverage_bp must be within 0..10000")
        self._minimum_coverage_bp = minimum_coverage_bp

    def verify(
        self,
        *,
        source_id: str,
        decision_date: str,
        observations: Iterable[P0ShadowObservation],
        coverage_bp: int,
        license_evidence: str,
        quality_evidence: str,
    ) -> P0SourceAcceptanceVerification:
        build_p0_source_contract_registry().require(source_id)
        rows = tuple(observations)
        diagnostics: list[str] = []
        service_decision_date = _parse_date(decision_date)
        if service_decision_date is None:
            diagnostics.append("invalid_service_decision_date")
        if not rows:
            diagnostics.append("missing_shadow_observations")
        if any(row.source_id != source_id for row in rows):
            diagnostics.append("source_id_mismatch")
        if any(row.status != "shadow_ready" for row in rows):
            diagnostics.append("shadow_observation_blocked")
        future_blocked = any(
            (available_date := _parse_date(row.available_date)) is not None
            and service_decision_date is not None
            and available_date > service_decision_date
            for row in rows
        )
        if future_blocked:
            diagnostics.extend(("future_blocked", "quality_blocked"))
        effective_coverage_bp = 0 if future_blocked else coverage_bp
        if (
            not isinstance(effective_coverage_bp, int)
            or isinstance(effective_coverage_bp, bool)
            or not 0 <= effective_coverage_bp <= 10000
        ):
            diagnostics.append("invalid_coverage_bp")
        elif effective_coverage_bp < self._minimum_coverage_bp:
            diagnostics.append("coverage_below_minimum")
        if not license_evidence.strip():
            diagnostics.append("missing_license_evidence")
        if not quality_evidence.strip():
            diagnostics.append("missing_quality_evidence")
        unique = tuple(sorted(set(diagnostics)))
        return P0SourceAcceptanceVerification(
            source_id=source_id,
            status="blocked" if unique else "eligible_for_human_review",
            diagnostics=unique,
            coverage_bp=effective_coverage_bp,
        )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
