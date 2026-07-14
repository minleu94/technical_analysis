"""Evidence rehearsal 的 immutable detector-path fault transforms。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from types import MappingProxyType

from app_module.evidence_rehearsal_orchestrator import EvidenceRehearsalExecutionRequest


class EvidenceRehearsalSourceOutageError(RuntimeError):
    """Source gateway 的受控 outage。"""


class EvidenceRehearsalFaultInjector:
    """只改變輸入／gateway；不直接寫 report blocker。"""

    def inject(
        self,
        request: EvidenceRehearsalExecutionRequest,
        failure: str,
    ) -> EvidenceRehearsalExecutionRequest:
        if failure == "source_outage":
            return replace(
                request,
                source_error=EvidenceRehearsalSourceOutageError("source_outage"),
                fault_diagnostics=MappingProxyType(
                    {
                        "target": "source_gateway",
                        "mutation": "raise_typed_source_outage",
                        "detector": "EvidenceRehearsalService.run",
                    }
                ),
            )
        if failure == "future_available_date":
            if not request.p0_observations:
                raise ValueError("future_available_date requires a P0 observation")
            first, *remaining = request.p0_observations
            future_date = (
                date.fromisoformat(request.scenario.decision_date) + timedelta(days=1)
            ).isoformat()
            return replace(
                request,
                p0_observations=(
                    replace(first, available_date=future_date),
                    *remaining,
                ),
                fault_diagnostics=MappingProxyType(
                    {
                        "target": f"p0_observation:{first.source_id}",
                        "mutation": "p0_available_date_plus_one_day",
                        "detector": "P0SourceShadowComparisonService",
                    }
                ),
            )
        raise ValueError(f"unsupported independent fault injection: {failure}")
