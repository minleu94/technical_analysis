"""跨領域 evidence rehearsal 的唯讀編排服務。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from app_module.artifact_lineage_verifier import (
    ArtifactIdentity,
    ArtifactLineageVerifier,
)
from app_module.evidence_rehearsal_dtos import EvidenceRehearsalScenario


_REQUIRED_ADAPTERS = (
    "source",
    "market",
    "replay",
    "advice",
    "paper",
    "health",
    "evidence",
    "outcome",
    "weekly",
    "signal",
    "ml",
)

_REQUIRED_ADAPTER_ARTIFACT_TYPES = {
    "source": "daily_governed_data",
    "market": "market_context",
    "replay": "recommendation",
    "advice": "bounded_advice",
    "paper": "paper_portfolio",
    "health": "position_health",
    "evidence": "evidence_event",
    "outcome": "forward_outcome",
    "weekly": "weekly_review",
    "signal": "signal_effectiveness",
    "ml": "ml_shadow_prediction",
}


@dataclass(frozen=True)
class EvidenceRehearsalServiceReport:
    """僅供工程排演使用的穩定、不可變報告。"""

    status: str
    ordered_artifact_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    diagnostics: tuple[str, ...]
    artifact_dag: Mapping[str, tuple[str, ...]]
    artifact_hashes: Mapping[str, str]
    artifact_count: int
    formal_product_closeout: bool = False
    production_actions_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordered_artifact_ids", tuple(self.ordered_artifact_ids))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(
            self,
            "artifact_dag",
            MappingProxyType({key: tuple(value) for key, value in self.artifact_dag.items()}),
        )
        object.__setattr__(self, "artifact_hashes", MappingProxyType(dict(self.artifact_hashes)))
        if self.formal_product_closeout is not False:
            raise ValueError("formal_product_closeout must be False")
        if self.production_actions_allowed is not False:
            raise ValueError("production_actions_allowed must be False")


class EvidenceRehearsalService:
    """整合 adapter 投影結果，不寫入正式產品或資料存放區。"""

    def __init__(self, verifier: ArtifactLineageVerifier | None = None) -> None:
        self._verifier = verifier or ArtifactLineageVerifier()

    def run(
        self,
        scenario: EvidenceRehearsalScenario,
        adapter_outputs: Mapping[str, Iterable[ArtifactIdentity | BaseException]],
    ) -> EvidenceRehearsalServiceReport:
        blockers: list[str] = []
        artifacts: list[ArtifactIdentity] = []
        for adapter_name in _REQUIRED_ADAPTERS:
            output = tuple(adapter_outputs.get(adapter_name, ()))
            if not output:
                blockers.append(f"missing_required_adapter_output:{adapter_name}")
                continue
            for item in output:
                if isinstance(item, BaseException):
                    blockers.append(f"adapter_failure:{adapter_name}:{item}")
                elif isinstance(item, ArtifactIdentity):
                    artifacts.append(item)
                    expected_type = _REQUIRED_ADAPTER_ARTIFACT_TYPES[adapter_name]
                    if item.artifact_type != expected_type:
                        blockers.append(
                            "adapter_artifact_type_mismatch:"
                            f"{adapter_name}:{item.artifact_type}:{expected_type}"
                        )
                    if item.decision_date != scenario.decision_date:
                        blockers.append(
                            f"scenario_decision_date_mismatch:{item.artifact_id}"
                        )
                else:
                    blockers.append(f"invalid_adapter_output:{adapter_name}")

        lineage = self._verifier.verify(artifacts)
        blockers.extend(lineage.blockers)
        ordered_ids = lineage.ordered_artifact_ids
        verified = not blockers and lineage.status == "complete"
        by_id = {artifact.artifact_id: artifact for artifact in artifacts} if verified else {}
        return EvidenceRehearsalServiceReport(
            status="complete" if not blockers and lineage.status == "complete" else "degraded",
            ordered_artifact_ids=ordered_ids,
            blockers=tuple(dict.fromkeys(blockers)),
            diagnostics=tuple(dict.fromkeys(blockers)),
            artifact_dag={
                artifact_id: by_id[artifact_id].parent_artifact_ids
                for artifact_id in ordered_ids
                if artifact_id in by_id
            },
            artifact_hashes={
                artifact_id: by_id[artifact_id].content_hash
                for artifact_id in ordered_ids
                if artifact_id in by_id
            },
            artifact_count=len(artifacts),
        )
