"""把 sanitized frozen projection 投影成 Research Console DTO；不連線資料庫。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from app_module.research_console_dtos import (
    ResearchArtifactRowDTO,
    ResearchConsoleBoundaryDTO,
    ResearchConsoleDTO,
    ResearchGateCardDTO,
    ResearchPipelineRowDTO,
    ResearchSourceRowDTO,
)
from app_module.p0_source_control_center import (
    P0SourceControlCenterDTO,
    P0SourceControlCenterService,
)
from data_module.source_acceptance_decision_registry import (
    SourceAcceptanceDecisionRevision,
    parse_source_acceptance_decisions,
)


ProjectionProvider = Callable[[], Mapping[str, object] | None]
GovernanceProvider = Callable[[], Mapping[str, object] | None]
P0AuditProvider = Callable[[], Mapping[str, Any] | None]
P0DecisionProvider = Callable[[], Iterable[SourceAcceptanceDecisionRevision]]
ClockProvider = Callable[[], datetime]

P0_SOURCE_IDS = (
    "corporate_action.ex_dividend_timeline",
    "corporate_action.reduction_split_par_value",
    "microstructure.suspended_halt_resume",
    "microstructure.disposition_stock",
    "microstructure.periodic_call_auction",
    "microstructure.full_delivery",
    "microstructure.limit_lock",
    "institutional_flows",
    "credit_transactions",
    "tdcc_shareholding",
    "twse.monthly_revenue_announcement",
    "tpex.monthly_revenue_announcement",
    "pit.quarterly_financials",
)

_PIPELINE_LABELS = {
    "dataset": "Development Dataset V0",
    "rule": "Rule Development Baseline",
    "ml": "ML Development Challenger",
    "e2e": "Development E2E Run",
}

_REQUIRED_DISABLED_APPLY_FLAGS = (
    "apply_to_scoring",
    "apply_to_recommendation",
    "apply_to_portfolio",
    "apply_to_exit",
)

_DEFAULT_MAX_PROJECTION_AGE = timedelta(days=7)
_FUTURE_TIMESTAMP_TOLERANCE = timedelta(minutes=5)
_MOPS_SANITIZED_SCHEMA = "mops-sanitized-research-projection.v1"
_MOPS_SOURCE_ID = "mops.ezsearch.statement_publication"
_MOPS_DECISION_ID = "decision:mops.ezsearch.statement_publication:20260727-r1"
_MOPS_ALLOWED_USE = (
    "research_pit_statement_availability, development_shadow_projection"
)
_SHA256_REFERENCE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
_MOPS_FORBIDDEN_KEYS = frozenset(
    {
        "rows",
        "availability_projection",
        "subject",
        "hyperlink",
        "detail_url",
        "cookies",
        "headers",
        "token",
        "credential",
        "session",
        "db_path",
    }
)


class ResearchConsoleSourceService:
    """只讀取呼叫端注入 payload 或顯式 JSON artifact。"""

    def __init__(
        self,
        *,
        projection_provider: ProjectionProvider | None = None,
        projection_path: str | Path | None = None,
        governance_provider: GovernanceProvider | None = None,
        p0_audit_provider: P0AuditProvider | None = None,
        p0_audit_path: str | Path | None = None,
        p0_decision_provider: P0DecisionProvider | None = None,
        p0_decision_path: str | Path | None = None,
        clock: ClockProvider | None = None,
        max_projection_age: timedelta = _DEFAULT_MAX_PROJECTION_AGE,
    ) -> None:
        if projection_provider is not None and projection_path is not None:
            raise ValueError("use either projection_provider or projection_path")
        self._projection_provider = projection_provider
        self._projection_path = Path(projection_path).resolve() if projection_path is not None else None
        self._governance_provider = governance_provider
        self._p0_audit_provider = p0_audit_provider
        if p0_audit_provider is not None and p0_audit_path is not None:
            raise ValueError("use either p0_audit_provider or p0_audit_path")
        self._p0_audit_path = Path(p0_audit_path).resolve() if p0_audit_path is not None else None
        self._p0_decision_provider = p0_decision_provider
        if p0_decision_provider is not None and p0_decision_path is not None:
            raise ValueError("use either p0_decision_provider or p0_decision_path")
        self._p0_decision_path = (
            Path(p0_decision_path).resolve() if p0_decision_path is not None else None
        )
        self._p0_control_center_service = P0SourceControlCenterService()
        if max_projection_age <= timedelta(0):
            raise ValueError("max_projection_age must be positive")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_projection_age = max_projection_age

    def inspect(self) -> ResearchConsoleDTO:
        try:
            payload, reference, artifact_hash = self._read_projection()
        except Exception:
            return self._missing("projection_read_failed", overall_status="degraded")
        if payload is None:
            return self._missing("projection_missing")
        if not self._has_safe_boundary(payload):
            return self._missing("projection_boundary_violation", overall_status="degraded")
        try:
            return self._project(payload, reference, artifact_hash)
        except Exception:
            return self._missing("projection_schema_invalid", overall_status="degraded")

    def _read_projection(self) -> tuple[Mapping[str, object] | None, str, str | None]:
        if self._projection_provider is not None:
            return self._projection_provider(), "injected_projection", None
        if self._projection_path is None or not self._projection_path.is_file():
            return None, "not_configured", None
        projection_bytes = self._projection_path.read_bytes()
        payload = json.loads(projection_bytes)
        if not isinstance(payload, Mapping):
            raise TypeError("projection root must be an object")
        artifact_hash = "sha256:" + sha256(projection_bytes).hexdigest()
        return payload, str(self._projection_path), artifact_hash

    def _project(
        self,
        payload: Mapping[str, object],
        reference: str,
        artifact_hash: str | None,
    ) -> ResearchConsoleDTO:
        _validate_mops_sanitized_projection(payload)
        identity = _mapping(payload, "identity")
        status = _mapping(payload, "status")
        metrics = _mapping(payload, "frozen_metrics")
        lineage = _mapping(payload, "lineage")
        blockers = _string_tuple(payload.get("blockers")) + self._freshness_blockers(lineage)
        governance = self._governance_provider() if self._governance_provider is not None else None
        if governance is None and ("sources" in payload or "gates" in payload):
            governance = payload
        if governance is not None and not isinstance(governance, Mapping):
            raise TypeError("governance projection must be an object")
        source_control_center = self._build_p0_source_control_center(governance)
        sample_count = _optional_int(metrics.get("sample_count"))
        feature_names = lineage.get("feature_names")
        feature_count = len(feature_names) if isinstance(feature_names, list) else None
        dataset_id = _required_string(identity, "dataset_id")
        generation_id = _required_string(identity, "generation_id")
        research_run_id = _required_string(identity, "research_run_id")
        dataset_status = str(status.get("scope") or "development_only")
        rule_metrics = metrics.get("rule")
        ml_metrics = metrics.get("ml")
        rule_status = _component_status(rule_metrics, "research_baseline")
        ml_status = _component_status(ml_metrics, "development_challenger")
        pipeline = (
            ResearchPipelineRowDTO(
                component_id="dataset",
                label=_PIPELINE_LABELS["dataset"],
                identity=dataset_id,
                status=dataset_status,
                cutoff=_optional_string(lineage.get("training_as_of")),
                feature_interval=_feature_interval(feature_names),
                label_maturity=_optional_string(lineage.get("max_label_available_date")),
                row_count=_optional_int(lineage.get("input_fit_row_count"), fallback=sample_count),
                eligible_count=sample_count,
                feature_count=feature_count,
                artifact_hash=_optional_string(lineage.get("dataset_manifest_hash")),
                blockers=blockers,
            ),
            ResearchPipelineRowDTO(
                component_id="rule",
                label=_PIPELINE_LABELS["rule"],
                identity=_optional_string(lineage.get("rule_configuration_hash")) or "Unknown",
                status=rule_status,
                row_count=_metric_count(rule_metrics),
                blockers=blockers,
            ),
            ResearchPipelineRowDTO(
                component_id="ml",
                label=_PIPELINE_LABELS["ml"],
                identity=research_run_id,
                status=ml_status,
                row_count=_metric_count(ml_metrics),
                blockers=blockers,
            ),
            ResearchPipelineRowDTO(
                component_id="e2e",
                label=_PIPELINE_LABELS["e2e"],
                identity=research_run_id,
                status="degraded" if blockers else "observed",
                generated_at=_optional_string(lineage.get("generated_at")),
                artifact_path=reference,
                artifact_hash=artifact_hash,
                blockers=blockers,
            ),
        )
        return ResearchConsoleDTO(
            overall_status="degraded" if blockers else "observed",
            source_reference=reference,
            boundary=ResearchConsoleBoundaryDTO(),
            pipeline=pipeline,
            gates=_governance_gates(governance),
            sources=_governance_sources(governance),
            artifacts=_artifact_rows(lineage) + _governance_artifacts(governance),
            source_control_center=source_control_center,
            frozen_metrics=metrics,
            blockers=blockers,
        )

    def _freshness_blockers(self, lineage: Mapping[str, object]) -> tuple[str, ...]:
        generated_at = _optional_string(lineage.get("generated_at"))
        if generated_at is None:
            return ("projection_generated_at_missing",)
        try:
            parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            return ("projection_generated_at_invalid",)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return ("projection_generated_at_invalid",)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        age = now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)
        if age < -_FUTURE_TIMESTAMP_TOLERANCE:
            return ("projection_generated_at_future",)
        if age > self._max_projection_age:
            return ("projection_stale",)
        return ()

    def _missing(self, blocker: str, *, overall_status: str = "missing") -> ResearchConsoleDTO:
        try:
            source_control_center = self._build_p0_source_control_center(None)
        except Exception:
            # A malformed optional audit/decision artifact must not make the
            # fail-closed fallback itself escape.  Keep the authoritative
            # thirteen contract rows visible without applying the bad input.
            source_control_center = self._p0_control_center_service.build()
        return ResearchConsoleDTO(
            overall_status=overall_status,
            source_reference="not_configured",
            boundary=ResearchConsoleBoundaryDTO(),
            pipeline=tuple(
                ResearchPipelineRowDTO(
                    component_id=component_id,
                    label=label,
                    identity="Missing",
                    status="missing",
                    blockers=(blocker,),
                )
                for component_id, label in _PIPELINE_LABELS.items()
            ),
            gates=_missing_gates(),
            sources=_missing_sources(),
            source_control_center=source_control_center,
            blockers=(blocker,),
        )

    def _build_p0_source_control_center(
        self, governance: Mapping[str, object] | None
    ) -> P0SourceControlCenterDTO:
        audit = self._p0_audit_provider() if self._p0_audit_provider is not None else None
        if audit is None and self._p0_audit_path is not None:
            audit_bytes = self._p0_audit_path.read_bytes()
            parsed = json.loads(audit_bytes)
            if not isinstance(parsed, Mapping):
                raise TypeError("P0 audit artifact must be an object")
            audit = parsed  # type: ignore[assignment]
        if audit is None and governance is not None:
            schema = governance.get("schema_version")
            if schema in {"p0-candidate-audit.v1", "p0-source-evidence-audit.v1"}:
                audit = governance  # type: ignore[assignment]
            else:
                embedded = governance.get("p0_candidate_audit")
                if isinstance(embedded, Mapping):
                    audit = embedded  # type: ignore[assignment]
        decisions: Iterable[SourceAcceptanceDecisionRevision] = ()
        if self._p0_decision_provider is not None:
            decisions = self._p0_decision_provider()
        elif self._p0_decision_path is not None:
            decision_bytes = self._p0_decision_path.read_bytes()
            decisions = parse_source_acceptance_decisions(json.loads(decision_bytes))
        return self._p0_control_center_service.build(
            candidate_audit=audit,
            decisions=decisions,
        )

    @staticmethod
    def _has_safe_boundary(payload: Mapping[str, object]) -> bool:
        try:
            status = _mapping(payload, "status")
        except (KeyError, TypeError):
            return False
        flags = status.get("apply_flags")
        if not isinstance(flags, Mapping):
            return False
        alpha_bp = status.get("alpha_bp")
        return (
            status.get("scope") == "historical_research_seen_development_data"
            and status.get("formal_oos") is False
            and type(alpha_bp) is int
            and alpha_bp == 0
            and status.get("promotion_eligible") is False
            and set(flags) == set(_REQUIRED_DISABLED_APPLY_FLAGS)
            and all(flags.get(key) is False for key in _REQUIRED_DISABLED_APPLY_FLAGS)
        )


def _missing_gates() -> tuple[ResearchGateCardDTO, ...]:
    return tuple(
        ResearchGateCardDTO(
            gate_id=f"EV{index}",
            label=f"EV{index}",
            status="missing",
            detail="Not Available；未提供 sanitized gate projection。",
        )
        for index in range(1, 6)
    )


def _missing_sources() -> tuple[ResearchSourceRowDTO, ...]:
    p0 = tuple(
        ResearchSourceRowDTO(
            source_id=source_id,
            label=source_id,
            lane="p0",
            status="missing",
            allowed_use="Not Available",
            degraded_reason="sanitized_source_projection_missing",
        )
        for source_id in P0_SOURCE_IDS
    )
    return p0 + (
        ResearchSourceRowDTO(
            source_id="broker_dataset",
            label="Broker Dataset（獨立研究 lane）",
            lane="broker",
            status="missing",
            allowed_use="Development Only / Not formally accepted",
            degraded_reason="sanitized_broker_projection_missing",
        ),
    )


def _artifact_rows(lineage: Mapping[str, object]) -> tuple[ResearchArtifactRowDTO, ...]:
    rows = []
    for artifact_type, field_name in (
        ("dataset_manifest", "dataset_manifest_hash"),
        ("dataset_content", "dataset_content_hash"),
        ("feature_registry", "feature_registry_hash"),
        ("label_registry", "label_registry_hash"),
        ("rule_configuration", "rule_configuration_hash"),
    ):
        artifact_id = _optional_string(lineage.get(field_name))
        if artifact_id:
            rows.append(
                ResearchArtifactRowDTO(
                    artifact_type=artifact_type,
                    artifact_id=artifact_id,
                    status="development_only",
                    citation=f"ResearchConsoleProjection.lineage.{field_name}",
                )
            )
    return tuple(rows)


def _governance_gates(
    governance: Mapping[str, object] | None,
) -> tuple[ResearchGateCardDTO, ...]:
    rows = {item.gate_id: item for item in _missing_gates()}
    if governance is None:
        return tuple(rows.values())
    payload = governance.get("gates", [])
    if not isinstance(payload, list):
        raise TypeError("gates must be an array")
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise TypeError("gate row must be an object")
        gate_id = _required_string(raw, "gate_id")
        if gate_id not in rows:
            raise ValueError(f"unknown evidence gate: {gate_id}")
        rows[gate_id] = ResearchGateCardDTO(
            gate_id=gate_id,
            label=_optional_string(raw.get("label")) or gate_id,
            status=_required_string(raw, "status"),
            detail=_required_string(raw, "detail"),
            artifact_citation=_optional_string(raw.get("artifact_citation")),
        )
    return tuple(rows[f"EV{index}"] for index in range(1, 6))


def _governance_sources(
    governance: Mapping[str, object] | None,
) -> tuple[ResearchSourceRowDTO, ...]:
    defaults = {item.source_id: item for item in _missing_sources()}
    if governance is None:
        return tuple(defaults.values())
    payload = governance.get("sources", [])
    if not isinstance(payload, list):
        raise TypeError("sources must be an array")
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise TypeError("source row must be an object")
        source_id = _required_string(raw, "source_id")
        if source_id not in defaults:
            raise ValueError(f"unknown Research Console source: {source_id}")
        lane = _required_string(raw, "lane")
        expected_lane = defaults[source_id].lane
        if lane != expected_lane:
            raise ValueError(f"source lane mismatch: {source_id}")
        defaults[source_id] = ResearchSourceRowDTO(
            source_id=source_id,
            label=_optional_string(raw.get("label")) or defaults[source_id].label,
            lane=expected_lane,
            status=_required_string(raw, "status"),
            allowed_use=_required_string(raw, "allowed_use"),
            observed_rows=_optional_int(raw.get("observed_rows")),
            revision=_optional_string(raw.get("revision")),
            owner=_optional_string(raw.get("owner")),
            degraded_reason=_optional_string(raw.get("degraded_reason")),
        )
    return tuple(defaults[source_id] for source_id in P0_SOURCE_IDS) + (defaults["broker_dataset"],)


def _governance_artifacts(
    governance: Mapping[str, object] | None,
) -> tuple[ResearchArtifactRowDTO, ...]:
    if governance is None:
        return ()
    payload = governance.get("artifacts", [])
    if not isinstance(payload, list):
        raise TypeError("artifacts must be an array")
    rows = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise TypeError("artifact row must be an object")
        rows.append(
            ResearchArtifactRowDTO(
                artifact_type=_required_string(raw, "artifact_type"),
                artifact_id=_required_string(raw, "artifact_id"),
                status=_required_string(raw, "status"),
                citation=_required_string(raw, "citation"),
            )
        )
    return tuple(rows)


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be an object")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = _optional_string(payload.get(key))
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _optional_string(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _optional_int(value: object, *, fallback: int | None = None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return fallback
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("blockers must be a string array")
    return tuple(value)


def _validate_mops_sanitized_projection(payload: Mapping[str, object]) -> None:
    is_mops_projection = (
        payload.get("source") == _MOPS_SOURCE_ID
        or payload.get("p0_lane") == "pit.quarterly_financials"
    )
    if not is_mops_projection:
        return
    if payload.get("schema_version") != _MOPS_SANITIZED_SCHEMA:
        raise ValueError("unsupported MOPS sanitized projection schema")
    if (
        payload.get("source") != _MOPS_SOURCE_ID
        or payload.get("p0_lane") != "pit.quarterly_financials"
        or payload.get("source_decision") != _MOPS_DECISION_ID
        or payload.get("acceptance") != "limited"
        or payload.get("allowed_use") != _MOPS_ALLOWED_USE
        or payload.get("formal_allowed") is not False
        or payload.get("formal_evidence_credit_authorized") is not False
        or payload.get("production_allowed") is not False
        or payload.get("production_blend_alpha_bp") != 0
        or payload.get("scheduler_allowed") is not False
        or payload.get("training_allowed") is not False
        or payload.get("promotion_allowed") is not False
        or payload.get("fubon_shadow_usable") is not True
        or payload.get("fubon_formal_credit_allowed") is not False
    ):
        raise ValueError("MOPS sanitized projection governance boundary is invalid")
    _reject_forbidden_projection_keys(payload)
    artifact_hash = payload.get("current_artifact_hash")
    if not isinstance(artifact_hash, str) or not _SHA256_REFERENCE.fullmatch(artifact_hash):
        raise ValueError("MOPS sanitized projection artifact hash is invalid")
    if type(payload.get("multi_day_evidence_ready")) is not bool:
        raise TypeError("multi_day_evidence_ready must be boolean")
    counts = _mapping(payload, "counts")
    for key, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"MOPS sanitized projection count is invalid: {key}")
    run_status = payload.get("current_run_status")
    if run_status not in {
        "observed",
        "observed_empty",
        "degraded",
        "stale",
        "capture_failed",
    }:
        raise ValueError("MOPS sanitized projection run status is invalid")
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 1:
        raise ValueError("MOPS sanitized projection must contain exactly one source row")
    source = sources[0]
    if not isinstance(source, Mapping):
        raise TypeError("MOPS sanitized source row must be an object")
    expected_source_status = (
        "degraded" if run_status in {"degraded", "stale", "capture_failed"} else run_status
    )
    if (
        source.get("source_id") != "pit.quarterly_financials"
        or source.get("lane") != "p0"
        or source.get("status") != expected_source_status
        or source.get("allowed_use") != _MOPS_ALLOWED_USE
        or source.get("observed_rows") != counts.get("events")
    ):
        raise ValueError("MOPS sanitized source row is inconsistent with run status")


def _reject_forbidden_projection_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _MOPS_FORBIDDEN_KEYS:
                raise ValueError(f"forbidden key in MOPS sanitized projection: {key}")
            _reject_forbidden_projection_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_projection_keys(item)


def _component_status(value: object, fallback: str) -> str:
    if not isinstance(value, Mapping):
        return "missing"
    status = value.get("status")
    return str(status) if isinstance(status, str) and status else fallback


def _metric_count(value: object) -> int | None:
    return _optional_int(value.get("sample_count")) if isinstance(value, Mapping) else None


def _feature_interval(value: object) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    return f"{len(value)} frozen features"
