"""Evidence rehearsal 真實 working-copy 編排器。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from app_module.artifact_lineage_verifier import ArtifactIdentity, ArtifactLineageVerifier
from app_module.evidence_rehearsal_adapters import canonical_payload_hash
from app_module.evidence_rehearsal_dtos import EvidenceRehearsalScenario, RehearsalArtifact
from app_module.evidence_rehearsal_lineage_adapter import RehearsalArtifactIdentityAdapter
from app_module.evidence_rehearsal_ml_comparison import (
    MLRehearsalComparisonService,
    MLShadowComparison,
    MLShadowDiagnosticsInput,
)
from app_module.evidence_rehearsal_service import EvidenceRehearsalService
from app_module.evidence_rehearsal_source_comparison import P0SourceShadowComparisonService
from app_module.evidence_rehearsal_source_reader import EvidenceRehearsalSourceReader
from app_module.historical_evidence_replay import (
    HistoricalEvidenceReplayRequest,
    HistoricalEvidenceReplayService,
)
from data_module.config import TWStockConfig
from data_module.p0_shadow_observation import P0ShadowObservation


_ADAPTER_TYPES = {
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
class EvidenceRehearsalMLInputs:
    manifest: Any
    boundary_report: Any
    predictions: tuple[Any, ...]
    diagnostics: MLShadowDiagnosticsInput | None = None
    artifacts: tuple[RehearsalArtifact, ...] = ()


class MLRehearsalEvidenceProvider(Protocol):
    def load(self) -> EvidenceRehearsalMLInputs: ...


@dataclass(frozen=True)
class EvidenceRehearsalExecutionRequest:
    scenario: EvidenceRehearsalScenario
    config: TWStockConfig
    source_db_path: Path
    working_copy_db_path: Path
    start_date: str
    end_date: str
    overwrite_working_copy: bool = False
    sources: tuple[str, ...] = ("all",)
    p0_observations: tuple[P0ShadowObservation, ...] = ()
    artifact_inputs: Mapping[str, tuple[RehearsalArtifact, ...]] = field(
        default_factory=dict
    )
    ml_provider: MLRehearsalEvidenceProvider | None = None
    source_error: BaseException | None = None
    fault_diagnostics: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_db_path", Path(self.source_db_path))
        object.__setattr__(self, "working_copy_db_path", Path(self.working_copy_db_path))
        source = Path(self.source_db_path).expanduser().resolve()
        working_copy = Path(self.working_copy_db_path).expanduser().resolve()
        data_root = Path(self.config.data_root).expanduser().resolve()
        if source == working_copy:
            raise ValueError("working-copy DB must differ from source DB")
        if _is_at_or_below(working_copy, data_root):
            raise ValueError("working copy must be outside DATA_ROOT")
        if date.fromisoformat(self.start_date) > date.fromisoformat(self.end_date):
            raise ValueError("start_date must not be after end_date")
        if self.end_date != self.scenario.decision_date:
            raise ValueError("scenario_replay_decision_date_mismatch")
        if Path(self.scenario.source_db_path).expanduser().resolve() != source:
            raise ValueError("scenario source path must match request source path")
        if (
            Path(self.scenario.working_copy_db_path).expanduser().resolve()
            != working_copy
        ):
            raise ValueError("scenario working-copy path must match request path")
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "p0_observations", tuple(self.p0_observations))
        object.__setattr__(
            self,
            "artifact_inputs",
            MappingProxyType(
                {key: tuple(value) for key, value in self.artifact_inputs.items()}
            ),
        )
        object.__setattr__(
            self, "fault_diagnostics", MappingProxyType(dict(self.fault_diagnostics))
        )


@dataclass(frozen=True)
class EvidenceRehearsalExecutionReport:
    scenario_id: str
    decision_date: str
    execution_mode: str
    status: str
    source_db_opened: bool
    source_db_write_performed: bool
    working_copy_created: bool
    working_copy_write_performed: bool
    service_call_facts: Mapping[str, bool]
    adapter_statuses: tuple[tuple[str, str], ...]
    artifact_dag: Mapping[str, tuple[str, ...]]
    artifact_hashes: Mapping[str, str]
    lineage_status: str
    p0_source_shadow: Mapping[str, object]
    ml_shadow: MLShadowComparison | None
    semantic_fingerprint: str
    blockers: tuple[str, ...]
    fault_diagnostics: Mapping[str, str]
    formal_product_closeout: bool = False
    production_actions_allowed: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "service_call_facts",
            "artifact_dag",
            "artifact_hashes",
            "p0_source_shadow",
            "fault_diagnostics",
        ):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, MappingProxyType(dict(value)))
        object.__setattr__(self, "adapter_statuses", tuple(self.adapter_statuses))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        if self.formal_product_closeout is not False:
            raise ValueError("formal_product_closeout must be False")
        if self.production_actions_allowed is not False:
            raise ValueError("production_actions_allowed must be False")

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "decision_date": self.decision_date,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "source_db_opened": self.source_db_opened,
            "source_db_write_performed": self.source_db_write_performed,
            "working_copy_created": self.working_copy_created,
            "working_copy_write_performed": self.working_copy_write_performed,
            "service_call_facts": dict(self.service_call_facts),
            "adapter_statuses": [list(item) for item in self.adapter_statuses],
            "artifact_dag": {
                key: list(value) for key, value in self.artifact_dag.items()
            },
            "artifact_hashes": dict(self.artifact_hashes),
            "lineage_status": self.lineage_status,
            "p0_source_shadow": dict(self.p0_source_shadow),
            "ml_shadow": asdict(self.ml_shadow) if self.ml_shadow is not None else None,
            "semantic_fingerprint": self.semantic_fingerprint,
            "blockers": list(self.blockers),
            "fault_diagnostics": dict(self.fault_diagnostics),
            "formal_product_closeout": self.formal_product_closeout,
            "production_actions_allowed": self.production_actions_allowed,
        }


class EvidenceRehearsalOrchestrator:
    """依真實 service output 建立 rehearsal report；缺 stage 一律保留。"""

    def __init__(
        self,
        *,
        reader: EvidenceRehearsalSourceReader | None = None,
        verifier: ArtifactLineageVerifier | None = None,
    ) -> None:
        self._reader = reader or EvidenceRehearsalSourceReader()
        self._verifier = verifier or ArtifactLineageVerifier()

    def run(
        self, request: EvidenceRehearsalExecutionRequest
    ) -> EvidenceRehearsalExecutionReport:
        service_calls = {
            "source_probe": False,
            "historical_replay": False,
            "p0_comparison": False,
            "ml_comparison": False,
            "lineage_verifier": False,
            "evidence_rehearsal_service_run": False,
        }
        statuses = {key: "not_invoked_missing_input" for key in _ADAPTER_TYPES}
        adapter_outputs: dict[str, tuple[ArtifactIdentity | BaseException, ...]] = {
            key: () for key in _ADAPTER_TYPES
        }
        identities: list[ArtifactIdentity] = []
        source_opened = False
        working_copy_created = False

        if request.source_error is not None:
            statuses["source"] = "invoked_failure"
            adapter_outputs["source"] = (request.source_error,)
        else:
            snapshot = self._reader.read(
                request.source_db_path,
                decision_date=request.scenario.decision_date,
            )
            service_calls["source_probe"] = True
            source_opened = snapshot.opened
            source_identity = self._source_identity(request, snapshot.to_dict())
            identities.append(source_identity)
            adapter_outputs["source"] = (source_identity,)
            statuses["source"] = "invoked"

            replay_report = HistoricalEvidenceReplayService(request.config).run(
                HistoricalEvidenceReplayRequest(
                    start_date=request.start_date,
                    end_date=request.end_date,
                    source_db_path=request.source_db_path,
                    replay_db_path=request.working_copy_db_path,
                    sources=request.sources,
                    confirm=True,
                    overwrite_replay_db=request.overwrite_working_copy,
                    replay_run_id=f"rehearsal-{request.scenario.scenario_id}",
                )
            )
            service_calls["historical_replay"] = True
            working_copy_created = request.working_copy_db_path.is_file()
            replay_artifacts = replay_report.to_rehearsal_artifacts(
                decision_date=request.scenario.decision_date,
                rollback_reference=f"working-copy:{request.working_copy_db_path.name}",
            )
            replay_identities = self._project_artifacts(
                replay_artifacts,
                adapter_name="replay",
                run_id=replay_report.replay_run_id,
            )
            identities.extend(replay_identities)
            adapter_outputs["replay"] = replay_identities
            statuses["replay"] = "invoked" if replay_identities else "invoked_no_output"

        for adapter_name, artifacts in request.artifact_inputs.items():
            if adapter_name not in _ADAPTER_TYPES or adapter_name in {"source", "replay", "ml"}:
                continue
            projected = self._project_artifacts(
                artifacts,
                adapter_name=adapter_name,
                run_id=request.scenario.scenario_id,
            )
            identities.extend(projected)
            adapter_outputs[adapter_name] = projected
            statuses[adapter_name] = "invoked" if projected else "invoked_no_output"

        p0_report = P0SourceShadowComparisonService(
            decision_date=request.scenario.decision_date,
            shadow_observations=request.p0_observations,
        ).build_report().to_dict()
        service_calls["p0_comparison"] = True

        ml_shadow = None
        if request.ml_provider is not None:
            ml_inputs = request.ml_provider.load()
            ml_shadow = MLRehearsalComparisonService().compare(
                ml_inputs.manifest,
                ml_inputs.boundary_report,
                ml_inputs.predictions,
                diagnostics=ml_inputs.diagnostics,
            )
            service_calls["ml_comparison"] = True
            ml_identities = self._project_artifacts(
                ml_inputs.artifacts,
                adapter_name="ml",
                run_id=request.scenario.scenario_id,
            )
            identities.extend(ml_identities)
            adapter_outputs["ml"] = ml_identities
            statuses["ml"] = "invoked" if ml_identities else "invoked_no_output"

        lineage = self._verifier.verify(identities)
        service_calls["lineage_verifier"] = True
        service_report = EvidenceRehearsalService(self._verifier).run(
            request.scenario,
            adapter_outputs,
        )
        service_calls["evidence_rehearsal_service_run"] = True

        blockers = [*service_report.blockers, *lineage.blockers]
        blockers.extend(_p0_blockers(p0_report))
        if ml_shadow is None:
            blockers.append("ml_shadow:not_invoked_missing_input")
        elif ml_shadow.status != "shadow_ready":
            blockers.append(f"ml_shadow:{ml_shadow.status}")
        blockers = list(dict.fromkeys(blockers))
        artifact_dag = {
            identity.artifact_id: identity.parent_artifact_ids for identity in identities
        }
        artifact_hashes = {
            identity.artifact_id: identity.content_hash for identity in identities
        }
        return EvidenceRehearsalExecutionReport(
            scenario_id=request.scenario.scenario_id,
            decision_date=request.scenario.decision_date,
            execution_mode="working_copy_e2e",
            status="degraded" if blockers else "rehearsal_only",
            source_db_opened=source_opened,
            source_db_write_performed=False,
            working_copy_created=working_copy_created,
            working_copy_write_performed=working_copy_created,
            service_call_facts=service_calls,
            adapter_statuses=tuple(statuses.items()),
            artifact_dag=artifact_dag,
            artifact_hashes=artifact_hashes,
            lineage_status=(
                "complete"
                if lineage.status == "complete" and service_report.status == "complete"
                else "incomplete"
            ),
            p0_source_shadow=p0_report,
            ml_shadow=ml_shadow,
            semantic_fingerprint=_semantic_fingerprint(request, artifact_hashes, blockers),
            blockers=tuple(blockers),
            fault_diagnostics=request.fault_diagnostics,
        )

    def _project_artifacts(
        self,
        artifacts: Iterable[RehearsalArtifact],
        *,
        adapter_name: str,
        run_id: str,
    ) -> tuple[ArtifactIdentity, ...]:
        adapter = RehearsalArtifactIdentityAdapter()
        return tuple(
            adapter.project(
                artifact,
                artifact_type=_ADAPTER_TYPES[adapter_name],
                run_id=run_id,
                source_id=adapter_name,
            )
            for artifact in artifacts
        )

    def _source_identity(
        self,
        request: EvidenceRehearsalExecutionRequest,
        snapshot: Mapping[str, object],
    ) -> ArtifactIdentity:
        source_artifact = RehearsalArtifact(
            artifact_id=(
                f"source:{request.scenario.scenario_id}:"
                f"{request.scenario.decision_date}"
            ),
            decision_date=request.scenario.decision_date,
            available_date=request.scenario.decision_date,
            tier="engineering_fixture",
            as_of_date=request.scenario.decision_date,
            source_version=str(snapshot["schema_fingerprint"]),
            data_quality="observed",
            missing_state="none",
            content_hash=canonical_payload_hash(snapshot),
            current_status="projected",
            canonical_payload=snapshot,
            rollback_reference=f"working-copy:{request.working_copy_db_path.name}",
        )
        return RehearsalArtifactIdentityAdapter().project(
            source_artifact,
            artifact_type="daily_governed_data",
            run_id=request.scenario.scenario_id,
            source_id="source-db",
        )


def _p0_blockers(report: Mapping[str, object]) -> tuple[str, ...]:
    blockers: list[str] = []
    items = report.get("items", ())
    if not isinstance(items, list):
        return ()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        source_id = item.get("source_id")
        item_blockers = item.get("blockers", ())
        if isinstance(source_id, str) and isinstance(item_blockers, list):
            blockers.extend(
                f"p0_shadow:{source_id}:{blocker}" for blocker in item_blockers
            )
    return tuple(blockers)


def _is_at_or_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _semantic_fingerprint(
    request: EvidenceRehearsalExecutionRequest,
    artifact_hashes: Mapping[str, str],
    blockers: Iterable[str],
) -> str:
    payload = {
        "scenario_id": request.scenario.scenario_id,
        "decision_date": request.scenario.decision_date,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "blockers": sorted(set(blockers)),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
