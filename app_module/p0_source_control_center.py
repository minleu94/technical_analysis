"""唯讀的 Gate 3 P0 資料來源控制中心。

這個模組只做既有 contract、候選稽核與人工決議的投影，不會建立
``SourceAcceptanceDecisionRegistry``、不會寫入 SQLite，也不會授予任何
formal／production 下游資格。P0 source 的正式分母固定由
``data_module.p0_source_contract_registry`` 提供。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from data_module.p0_source_contract_registry import (
    P0_SOURCE_IDS,
    P0SourceContract,
    P0SourceContractRegistry,
    build_p0_source_contract_registry,
)
from data_module.p0_source_acquisition_routes import build_p0_acquisition_route_registry
from data_module.source_acceptance_decision_registry import (
    SourceAcceptanceDecisionRevision,
    validate_source_acceptance_decision_revision,
)


CONTROL_CENTER_SCHEMA_VERSION = "p0-source-control-center.v1"
_CANDIDATE_AUDIT_SCHEMA = "p0-candidate-audit.v1"
_EVIDENCE_AUDIT_SCHEMA = "p0-source-evidence-audit.v1"
_LICENSE_CAPTURE_SCHEMA = "p0-license-evidence-capture.v1"
_DECISION_STATUSES = frozenset(
    {"deferred", "rejected", "disabled", "limited", "accepted"}
)
_REQUIRED_EVIDENCE = (
    "license_evidence",
    "quality_evidence",
    "pit_available_date_evidence",
    "owner_reviewer_decision",
)
_P0_LABELS = {
    "corporate_action.ex_dividend_timeline": "除權息時間軸",
    "corporate_action.reduction_split_par_value": "減資／分割／面額變更",
    "microstructure.suspended_halt_resume": "停牌／復牌",
    "microstructure.disposition_stock": "處置股",
    "microstructure.periodic_call_auction": "分盤撮合",
    "microstructure.full_delivery": "全額交割",
    "microstructure.limit_lock": "漲跌停鎖死",
    "institutional_flows": "三大法人買賣超",
    "credit_transactions": "信用交易",
    "tdcc_shareholding": "TDCC 集保持股分散",
    "twse.monthly_revenue_announcement": "TWSE 月營收公告",
    "tpex.monthly_revenue_announcement": "TPEx 月營收公告",
    "pit.quarterly_financials": "PIT 季度財報",
}


@dataclass(frozen=True)
class P0SourceControlRow:
    """單一 P0 source 的不可變控制中心列。"""

    source_id: str
    label: str
    family: str
    contract_version: str
    governance_status: str
    machine_status: str
    audit_status: str
    decision_status: str
    license_status: str
    human_decision: str
    downstream_eligibility: str
    observed_rows: int | None = None
    accepted_rows: int | None = None
    blocked_rows: int | None = None
    coverage_bp: int | None = None
    latest_available_date: str | None = None
    latest_observed_date: str | None = None
    provider: str | None = None
    revision: str | None = None
    payload_sha256: str | None = None
    acquisition_route_id: str | None = None
    acquisition_route_ids: tuple[str, ...] = ()
    fallback_used: bool | None = None
    fallback_from_route_id: str | None = None
    fallback_reason: str | None = None
    # 保留 evidence matrix 的 fallback 觀測，不讓 UI 只能看到「是否採用」。
    # ``fallback_used`` 與 ``fallback_attempted`` 必須分開：官方替代路徑可能
    # 已被嘗試，但因日期不符、官方無資料或 transport error 而安全拒絕。
    fallback_attempted: bool | None = None
    fallback_from_endpoint_id: str | None = None
    fallback_endpoint_id: str | None = None
    fallback_acquisition_route_id: str | None = None
    fallback_probe_outcome: str | None = None
    fallback_official_status: str | None = None
    fallback_http_status: int | None = None
    fallback_payload_sha256: str | None = None
    fallback_payload_size_bytes: int | None = None
    fallback_observation_dates: tuple[str, ...] = ()
    fallback_requested_date: str | None = None
    fallback_quarantine_reasons: tuple[str, ...] = ()
    fallback_error_type: str | None = None
    fallback_error: str | None = None
    primary_official_status: str | None = None
    pit_status: str | None = None
    timestamp_kind: str | None = None
    probe_outcome: str | None = None
    schema_status: str | None = None
    availability: str | None = None
    license_evidence_urls: tuple[str, ...] = ()
    license_evidence_capture_status: str = "not_supplied"
    license_evidence_content_sha256: tuple[str, ...] = ()
    license_evidence_keyword_groups: tuple[str, ...] = ()
    allowed_use_cases: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = _REQUIRED_EVIDENCE
    owner_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source_id not in P0_SOURCE_IDS:
            raise ValueError(f"unknown P0 source: {self.source_id}")
        if self.downstream_eligibility != "none":
            raise ValueError("P0 control center cannot grant downstream eligibility")
        for name in ("observed_rows", "accepted_rows", "blocked_rows", "coverage_bp"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer or None")
            if name == "coverage_bp" and value > 10000:
                raise ValueError("coverage_bp must be within 0..10000")
        object.__setattr__(self, "allowed_use_cases", _string_tuple(self.allowed_use_cases))
        object.__setattr__(self, "acquisition_route_ids", _string_tuple(self.acquisition_route_ids))
        object.__setattr__(
            self,
            "fallback_observation_dates",
            _string_tuple(self.fallback_observation_dates),
        )
        object.__setattr__(
            self,
            "fallback_quarantine_reasons",
            _string_tuple(self.fallback_quarantine_reasons),
        )
        object.__setattr__(self, "license_evidence_urls", _string_tuple(self.license_evidence_urls))
        object.__setattr__(
            self,
            "license_evidence_content_sha256",
            _string_tuple(self.license_evidence_content_sha256),
        )
        object.__setattr__(
            self,
            "license_evidence_keyword_groups",
            _string_tuple(self.license_evidence_keyword_groups),
        )
        object.__setattr__(self, "blockers", _string_tuple(self.blockers))
        object.__setattr__(self, "evidence_requirements", _string_tuple(self.evidence_requirements))
        object.__setattr__(self, "owner_actions", _string_tuple(self.owner_actions))
        if self.fallback_used is not None and type(self.fallback_used) is not bool:
            raise TypeError("fallback_used must be a boolean or None")
        if self.fallback_attempted is not None and type(self.fallback_attempted) is not bool:
            raise TypeError("fallback_attempted must be a boolean or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "label": self.label,
            "family": self.family,
            "contract_version": self.contract_version,
            "governance_status": self.governance_status,
            "machine_status": self.machine_status,
            "audit_status": self.audit_status,
            "decision_status": self.decision_status,
            "license_status": self.license_status,
            "human_decision": self.human_decision,
            "downstream_eligibility": self.downstream_eligibility,
            "observed_rows": self.observed_rows,
            "accepted_rows": self.accepted_rows,
            "blocked_rows": self.blocked_rows,
            "coverage_bp": self.coverage_bp,
            "latest_available_date": self.latest_available_date,
            "latest_observed_date": self.latest_observed_date,
            "provider": self.provider,
            "revision": self.revision,
            "payload_sha256": self.payload_sha256,
            "acquisition_route_id": self.acquisition_route_id,
            "acquisition_route_ids": list(self.acquisition_route_ids),
            "fallback_used": self.fallback_used,
            "fallback_from_route_id": self.fallback_from_route_id,
            "fallback_reason": self.fallback_reason,
            "fallback_attempted": self.fallback_attempted,
            "fallback_from_endpoint_id": self.fallback_from_endpoint_id,
            "fallback_endpoint_id": self.fallback_endpoint_id,
            "fallback_acquisition_route_id": self.fallback_acquisition_route_id,
            "fallback_probe_outcome": self.fallback_probe_outcome,
            "fallback_official_status": self.fallback_official_status,
            "fallback_http_status": self.fallback_http_status,
            "fallback_payload_sha256": self.fallback_payload_sha256,
            "fallback_payload_size_bytes": self.fallback_payload_size_bytes,
            "fallback_observation_dates": list(self.fallback_observation_dates),
            "fallback_requested_date": self.fallback_requested_date,
            "fallback_quarantine_reasons": list(self.fallback_quarantine_reasons),
            "fallback_error_type": self.fallback_error_type,
            "fallback_error": self.fallback_error,
            "primary_official_status": self.primary_official_status,
            "pit_status": self.pit_status,
            "timestamp_kind": self.timestamp_kind,
            "probe_outcome": self.probe_outcome,
            "schema_status": self.schema_status,
            "availability": self.availability,
            "license_evidence_urls": list(self.license_evidence_urls),
            "license_evidence_capture_status": self.license_evidence_capture_status,
            "license_evidence_content_sha256": list(self.license_evidence_content_sha256),
            "license_evidence_keyword_groups": list(self.license_evidence_keyword_groups),
            "allowed_use_cases": list(self.allowed_use_cases),
            "blockers": list(self.blockers),
            "evidence_requirements": list(self.evidence_requirements),
            "owner_actions": list(self.owner_actions),
        }


@dataclass(frozen=True)
class P0SourceControlCenterDTO:
    """P0 控制中心總覽；所有 safety flag 固定為 fail-closed。"""

    rows: tuple[P0SourceControlRow, ...]
    status_counts: Mapping[str, int]
    machine_status_counts: Mapping[str, int]
    decision_status_counts: Mapping[str, int]
    accepted_count: int
    limited_count: int
    research_shadow_count: int
    blocked_count: int
    contract_only_count: int
    downstream_eligible_count: int
    global_blockers: tuple[str, ...]
    schema_version: str = CONTROL_CENTER_SCHEMA_VERSION
    read_only: bool = True
    writes_allowed: bool = False
    production_ingestion_allowed: bool = False
    production_scheduler_allowed: bool = False
    formal_oos_allowed: bool = False
    auto_accept_allowed: bool = False

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        if len(rows) != len(P0_SOURCE_IDS) or tuple(item.source_id for item in rows) != P0_SOURCE_IDS:
            raise ValueError("P0 control center must contain the authoritative thirteen sources in order")
        if not all(isinstance(item, P0SourceControlRow) for item in rows):
            raise TypeError("P0 control center rows must be P0SourceControlRow values")
        if self.schema_version != CONTROL_CENTER_SCHEMA_VERSION:
            raise ValueError("unsupported P0 control center schema")
        for name, expected in {
            "read_only": True,
            "writes_allowed": False,
            "production_ingestion_allowed": False,
            "production_scheduler_allowed": False,
            "formal_oos_allowed": False,
            "auto_accept_allowed": False,
        }.items():
            if getattr(self, name) is not expected:
                raise ValueError(f"P0 control center boundary flag must remain {name}={expected}")
        if self.downstream_eligible_count != 0:
            raise ValueError("P0 control center cannot report downstream eligible sources")
        for name in (
            "accepted_count",
            "limited_count",
            "research_shadow_count",
            "blocked_count",
            "contract_only_count",
            "downstream_eligible_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        expected_status_counts = _freeze_counts(Counter(item.governance_status for item in rows))
        expected_machine_counts = _freeze_counts(Counter(item.machine_status for item in rows))
        expected_decision_counts = _freeze_counts(Counter(item.decision_status for item in rows))
        supplied_status_counts = _freeze_counts(self.status_counts)
        supplied_machine_counts = _freeze_counts(self.machine_status_counts)
        supplied_decision_counts = _freeze_counts(self.decision_status_counts)
        if supplied_status_counts != expected_status_counts:
            raise ValueError("status_counts must match the authoritative P0 rows")
        if supplied_machine_counts != expected_machine_counts:
            raise ValueError("machine_status_counts must match the authoritative P0 rows")
        if supplied_decision_counts != expected_decision_counts:
            raise ValueError("decision_status_counts must match the authoritative P0 rows")
        expected_counts = {
            "accepted_count": sum(item.decision_status == "accepted" for item in rows),
            "limited_count": sum(item.decision_status == "limited" for item in rows),
            "research_shadow_count": sum(item.governance_status == "research_shadow" for item in rows),
            "blocked_count": sum(item.governance_status == "blocked_provenance" for item in rows),
            "contract_only_count": sum(item.governance_status == "contract_only" for item in rows),
        }
        for name, expected_value in expected_counts.items():
            if getattr(self, name) != expected_value:
                raise ValueError(f"{name} must match the authoritative P0 rows")
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "status_counts", supplied_status_counts)
        object.__setattr__(self, "machine_status_counts", supplied_machine_counts)
        object.__setattr__(self, "decision_status_counts", supplied_decision_counts)
        object.__setattr__(self, "global_blockers", _string_tuple(self.global_blockers))

    @property
    def p0_source_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "p0_source_count": self.p0_source_count,
            "rows": [item.to_dict() for item in self.rows],
            "status_counts": dict(self.status_counts),
            "machine_status_counts": dict(self.machine_status_counts),
            "decision_status_counts": dict(self.decision_status_counts),
            "accepted_count": self.accepted_count,
            "limited_count": self.limited_count,
            "research_shadow_count": self.research_shadow_count,
            "blocked_count": self.blocked_count,
            "contract_only_count": self.contract_only_count,
            "downstream_eligible_count": self.downstream_eligible_count,
            "global_blockers": list(self.global_blockers),
            "boundary": {
                "read_only": self.read_only,
                "writes_allowed": self.writes_allowed,
                "production_ingestion_allowed": self.production_ingestion_allowed,
                "production_scheduler_allowed": self.production_scheduler_allowed,
                "formal_oos_allowed": self.formal_oos_allowed,
                "auto_accept_allowed": self.auto_accept_allowed,
            },
        }


class P0SourceControlCenterService:
    """將來源 contract、候選稽核與人工決議組合為唯讀投影。"""

    def __init__(self, registry: P0SourceContractRegistry | None = None) -> None:
        self._registry = registry or build_p0_source_contract_registry()
        contracts = self._registry.list()
        if tuple(item.source_id for item in contracts) != P0_SOURCE_IDS:
            raise ValueError("P0 registry does not match the authoritative source denominator")

    def build(
        self,
        *,
        candidate_audit: Mapping[str, Any] | None = None,
        license_evidence: Mapping[str, Any] | None = None,
        decisions: Iterable[SourceAcceptanceDecisionRevision] = (),
    ) -> P0SourceControlCenterDTO:
        audit_items = _normalize_audit(candidate_audit) if candidate_audit is not None else {}
        license_items = (
            _normalize_license_evidence(license_evidence)
            if license_evidence is not None
            else {}
        )
        decision_items = _normalize_decisions(decisions)
        rows = tuple(
            self._build_row(
                contract,
                audit_items.get(contract.source_id),
                license_items,
                decision_items.get(contract.source_id),
            )
            for contract in self._registry.list()
        )
        status_counts = Counter(item.governance_status for item in rows)
        machine_counts = Counter(item.machine_status for item in rows)
        decision_counts = Counter(item.decision_status for item in rows)
        accepted_count = sum(item.decision_status == "accepted" for item in rows)
        limited_count = sum(item.decision_status == "limited" for item in rows)
        research_shadow_count = sum(item.governance_status == "research_shadow" for item in rows)
        blocked_count = sum(item.governance_status == "blocked_provenance" for item in rows)
        contract_only_count = sum(item.governance_status == "contract_only" for item in rows)
        global_blockers = {
            "p0_source_acceptance_pending",
            "downstream_eligibility_none",
            "formal_oos_disabled",
            "production_scheduler_disabled",
        }
        global_blockers.update(blocker for item in rows for blocker in item.blockers)
        return P0SourceControlCenterDTO(
            rows=rows,
            status_counts=status_counts,
            machine_status_counts=machine_counts,
            decision_status_counts=decision_counts,
            accepted_count=accepted_count,
            limited_count=limited_count,
            research_shadow_count=research_shadow_count,
            blocked_count=blocked_count,
            contract_only_count=contract_only_count,
            downstream_eligible_count=0,
            global_blockers=tuple(sorted(global_blockers)),
        )

    def _build_row(
        self,
        contract: P0SourceContract,
        audit: Mapping[str, Any] | None,
        license_items: Mapping[str, Mapping[str, Any]],
        decision: SourceAcceptanceDecisionRevision | None,
    ) -> P0SourceControlRow:
        audit_status = _text(audit.get("audit_status")) if audit else "not_supplied"
        machine_status = _text(audit.get("machine_status")) if audit else "not_observed"
        blockers: list[str] = []
        if audit:
            blockers.extend(_string_tuple(audit.get("blockers", ())))
        else:
            blockers.append("candidate_audit_not_supplied")
        if decision is None:
            decision_status = "not_supplied"
            blockers.append("source_acceptance_decision_missing")
        else:
            decision_status = decision.status
            blockers.extend(decision.blockers)
            if decision.status in {"deferred", "rejected", "disabled"}:
                blockers.append(f"source_acceptance_{decision.status}")
        if contract.license_status != "approved":
            blockers.append("license_not_accepted")
        blockers.append("downstream_eligibility_none")
        governance_status = _governance_status(
            audit=audit,
            machine_status=machine_status,
            decision_status=decision_status,
        )
        owner_actions = _owner_actions(
            audit=audit,
            decision_status=decision_status,
            blockers=tuple(blockers),
        )
        return P0SourceControlRow(
            source_id=contract.source_id,
            label=_P0_LABELS.get(contract.source_id, contract.source_id),
            family=contract.family,
            contract_version=contract.contract_version,
            governance_status=governance_status,
            machine_status=machine_status,
            audit_status=audit_status,
            decision_status=decision_status,
            license_status=contract.license_status,
            human_decision=contract.human_decision,
            downstream_eligibility="none",
            observed_rows=_optional_int(audit.get("observed_rows")) if audit else None,
            accepted_rows=_optional_int(audit.get("accepted_rows")) if audit else None,
            blocked_rows=_optional_int(audit.get("blocked_rows")) if audit else None,
            coverage_bp=_optional_int(audit.get("coverage_bp"), maximum=10000) if audit else None,
            latest_available_date=_optional_text(audit.get("latest_available_date")) if audit else None,
            latest_observed_date=_optional_text(audit.get("latest_observed_date")) if audit else None,
            provider=_optional_text(audit.get("provider")) if audit else None,
            revision=(decision.decision_revision_id if decision is not None else None),
            payload_sha256=_optional_text(audit.get("payload_sha256")) if audit else None,
            acquisition_route_id=(
                _optional_text(audit.get("acquisition_route_id")) if audit else None
            ),
            acquisition_route_ids=(
                tuple(_string_tuple(audit.get("acquisition_route_ids", ()))) if audit else ()
            ),
            fallback_used=(
                _optional_bool(audit.get("fallback_used")) if audit else None
            ),
            fallback_from_route_id=(
                _optional_text(audit.get("fallback_from_route_id")) if audit else None
            ),
            fallback_reason=(
                _optional_text(audit.get("fallback_reason")) if audit else None
            ),
            fallback_attempted=(
                _optional_bool(audit.get("fallback_attempted")) if audit else None
            ),
            fallback_from_endpoint_id=(
                _optional_text(audit.get("fallback_from_endpoint_id")) if audit else None
            ),
            fallback_endpoint_id=(
                _optional_text(audit.get("fallback_endpoint_id")) if audit else None
            ),
            fallback_acquisition_route_id=(
                _optional_text(audit.get("fallback_acquisition_route_id")) if audit else None
            ),
            fallback_probe_outcome=(
                _optional_text(audit.get("fallback_probe_outcome")) if audit else None
            ),
            fallback_official_status=(
                _optional_text(audit.get("fallback_official_status")) if audit else None
            ),
            fallback_http_status=(
                _optional_int(audit.get("fallback_http_status")) if audit else None
            ),
            fallback_payload_sha256=(
                _optional_text(audit.get("fallback_payload_sha256")) if audit else None
            ),
            fallback_payload_size_bytes=(
                _optional_int(audit.get("fallback_payload_size_bytes")) if audit else None
            ),
            fallback_observation_dates=(
                _optional_string_tuple(audit.get("fallback_observation_dates"))
                if audit
                else ()
            ),
            fallback_requested_date=(
                _optional_text(audit.get("fallback_requested_date")) if audit else None
            ),
            fallback_quarantine_reasons=(
                _optional_string_tuple(audit.get("fallback_quarantine_reasons"))
                if audit
                else ()
            ),
            fallback_error_type=(
                _optional_text(audit.get("fallback_error_type")) if audit else None
            ),
            fallback_error=(
                _optional_text(audit.get("fallback_error")) if audit else None
            ),
            primary_official_status=(
                _optional_text(audit.get("primary_official_status")) if audit else None
            ),
            pit_status=_optional_text(audit.get("pit_status")) if audit else None,
            timestamp_kind=(
                _optional_text(audit.get("timestamp_kind")) if audit else None
            ),
            probe_outcome=(
                _optional_text(audit.get("probe_outcome")) if audit else None
            ),
            schema_status=_optional_text(audit.get("schema_status")) if audit else None,
            availability=_optional_text(audit.get("availability")) if audit else None,
            license_evidence_urls=_license_urls_for_source(contract.source_id, audit, license_items),
            license_evidence_capture_status=_license_capture_status_for_source(
                contract.source_id, license_items
            ),
            license_evidence_content_sha256=_license_capture_hashes_for_source(
                contract.source_id, license_items
            ),
            license_evidence_keyword_groups=_license_capture_keyword_groups_for_source(
                contract.source_id, license_items
            ),
            allowed_use_cases=(
                tuple(decision.allowed_use_cases)
                if decision is not None and decision.status in {"accepted", "limited"}
                else ()
            ),
            blockers=_unique_strings(blockers),
            owner_actions=owner_actions,
        )


def _normalize_decisions(
    decisions: Iterable[SourceAcceptanceDecisionRevision],
) -> dict[str, SourceAcceptanceDecisionRevision]:
    result: dict[str, SourceAcceptanceDecisionRevision] = {}
    for decision in decisions:
        if not isinstance(decision, SourceAcceptanceDecisionRevision):
            raise TypeError("decisions must contain SourceAcceptanceDecisionRevision values")
        if decision.source_id not in P0_SOURCE_IDS:
            raise ValueError(f"decision source is outside P0 denominator: {decision.source_id}")
        if decision.source_id in result:
            raise ValueError(f"duplicate current decision for source: {decision.source_id}")
        if decision.status not in _DECISION_STATUSES:
            raise ValueError(f"unsupported source decision status: {decision.status}")
        try:
            validate_source_acceptance_decision_revision(decision)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"invalid source acceptance decision for {decision.source_id}: {error}"
            ) from error
        result[decision.source_id] = decision
    return result


def _normalize_audit(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise TypeError("candidate audit must be an object")
    schema_version = payload.get("schema_version")
    if schema_version == _CANDIDATE_AUDIT_SCHEMA:
        _require_boundary(
            payload,
            {
                "formal_oos_allowed": False,
                "production_scheduler_allowed": False,
                "downstream_eligibility": "none",
                "human_decision": "requires_human_acceptance",
            },
        )
        raw_items = payload.get("items")
    elif schema_version == _EVIDENCE_AUDIT_SCHEMA:
        safety = payload.get("safety_flags")
        if not isinstance(safety, Mapping):
            raise ValueError("p0 source evidence audit safety_flags are required")
        _require_boundary(
            safety,
            {
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "production_allowed": False,
                "scheduler_allowed": False,
                "downstream_eligibility": "none",
                "human_decision": "requires_human_acceptance",
            },
        )
        raw_items = payload.get("machine_evidence_matrix")
    else:
        raise ValueError(f"unsupported P0 audit schema: {schema_version}")
    if not isinstance(raw_items, list):
        raise ValueError("P0 audit source rows must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            raise TypeError("P0 audit source row must be an object")
        source_id = _optional_text(raw.get("source_id"))
        if source_id is None or source_id not in P0_SOURCE_IDS:
            raise ValueError(f"unknown or missing P0 audit source: {source_id}")
        if source_id in result:
            raise ValueError(f"duplicate P0 audit source: {source_id}")
        result[source_id] = _normalize_audit_row(raw, schema_version == _EVIDENCE_AUDIT_SCHEMA)
    unknown_or_missing = set(P0_SOURCE_IDS) - set(result)
    if unknown_or_missing:
        raise ValueError(f"P0 audit is missing sources: {sorted(unknown_or_missing)}")
    return result


def _normalize_audit_row(raw: Mapping[str, Any], evidence_matrix: bool) -> Mapping[str, Any]:
    if evidence_matrix:
        blockers = []
        remaining = _optional_text(raw.get("remaining_blocker"))
        if remaining:
            blockers.append(remaining)
        observed_rows = _optional_int(raw.get("raw_row_count"))
        accepted_rows = _optional_int(raw.get("accepted_row_count"))
        fallback_from_route_id = _optional_text(raw.get("fallback_from_acquisition_route_id"))
        fallback_used = _optional_bool(raw.get("fallback_used"))
        fallback_reason = _optional_text(raw.get("fallback_reason"))
        if fallback_reason is None and fallback_from_route_id:
            fallback_reason = f"fallback_from:{fallback_from_route_id}"
        return {
            "audit_status": _optional_text(raw.get("availability")) or "not_supplied",
            "machine_status": _optional_text(raw.get("machine_status")) or "not_observed",
            "observed_rows": observed_rows,
            "accepted_rows": accepted_rows,
            "blocked_rows": _optional_int(raw.get("blocked_row_count")),
            "coverage_bp": _coverage_bp(observed_rows, accepted_rows),
            "acquisition_route_id": _optional_text(raw.get("acquisition_route_id")),
            "acquisition_route_ids": _route_ids(raw.get("acquisition_routes")),
            "fallback_used": fallback_used,
            "fallback_from_route_id": fallback_from_route_id,
            "fallback_reason": fallback_reason,
            "fallback_attempted": _optional_bool(raw.get("fallback_attempted")),
            "fallback_from_endpoint_id": _optional_text(raw.get("fallback_from_endpoint_id")),
            "fallback_endpoint_id": _optional_text(raw.get("fallback_endpoint_id")),
            "fallback_acquisition_route_id": _optional_text(
                raw.get("fallback_acquisition_route_id")
            ),
            "fallback_probe_outcome": _optional_text(raw.get("fallback_probe_outcome")),
            "fallback_official_status": _optional_text(raw.get("fallback_official_status")),
            "fallback_http_status": _optional_int(raw.get("fallback_http_status")),
            "fallback_payload_sha256": _optional_text(raw.get("fallback_payload_sha256")),
            "fallback_payload_size_bytes": _optional_int(
                raw.get("fallback_payload_size_bytes")
            ),
            "fallback_observation_dates": _optional_string_tuple(
                raw.get("fallback_observation_dates")
            ),
            "fallback_requested_date": _optional_text(raw.get("fallback_requested_date")),
            "fallback_quarantine_reasons": _optional_string_tuple(
                raw.get("fallback_quarantine_reasons")
            ),
            "fallback_error_type": _optional_text(raw.get("fallback_error_type")),
            "fallback_error": _optional_text(raw.get("fallback_error")),
            "primary_official_status": _optional_text(raw.get("primary_official_status")),
            "pit_status": _optional_text(raw.get("pit_status")),
            "timestamp_kind": _optional_text(raw.get("timestamp_kind")),
            "probe_outcome": _optional_text(raw.get("probe_outcome")),
            "schema_status": _optional_text(raw.get("schema_status")),
            "availability": _optional_text(raw.get("availability")),
            "license_evidence_urls": _license_evidence_urls(raw.get("acquisition_routes")),
            "provider": _optional_text(raw.get("provider")),
            "payload_sha256": _optional_text(raw.get("payload_sha256")),
            "blockers": _unique_strings((*blockers, *_string_tuple(raw.get("blockers", ())))),
        }
    fallback_from_route_id = _optional_text(raw.get("fallback_from_acquisition_route_id"))
    fallback_used = _optional_bool(raw.get("fallback_used"))
    fallback_reason = _optional_text(raw.get("fallback_reason"))
    if fallback_reason is None and fallback_from_route_id:
        fallback_reason = f"fallback_from:{fallback_from_route_id}"
    return {
        "audit_status": _optional_text(raw.get("audit_status")) or "not_supplied",
        "machine_status": _optional_text(raw.get("machine_status")) or "not_observed",
        "observed_rows": _optional_int(raw.get("row_count")),
        "accepted_rows": _optional_int(raw.get("accepted_row_count")),
        "blocked_rows": _optional_int(raw.get("blocked_row_count")),
        "coverage_bp": _optional_int(raw.get("coverage_bp"), maximum=10000),
        "latest_available_date": _optional_text(raw.get("latest_available_date")),
        "latest_observed_date": _optional_text(raw.get("latest_observation_date")),
        "provider": _optional_text(raw.get("provider")),
        "payload_sha256": _optional_text(raw.get("payload_sha256")),
        "acquisition_route_id": _optional_text(raw.get("acquisition_route_id")),
        "acquisition_route_ids": _route_ids(raw.get("acquisition_routes")),
        "fallback_used": fallback_used,
        "fallback_from_route_id": fallback_from_route_id,
        "fallback_reason": fallback_reason,
        "fallback_attempted": _optional_bool(raw.get("fallback_attempted")),
        "fallback_from_endpoint_id": _optional_text(raw.get("fallback_from_endpoint_id")),
        "fallback_endpoint_id": _optional_text(raw.get("fallback_endpoint_id")),
        "fallback_acquisition_route_id": _optional_text(
            raw.get("fallback_acquisition_route_id")
        ),
        "fallback_probe_outcome": _optional_text(raw.get("fallback_probe_outcome")),
        "fallback_official_status": _optional_text(raw.get("fallback_official_status")),
        "fallback_http_status": _optional_int(raw.get("fallback_http_status")),
        "fallback_payload_sha256": _optional_text(raw.get("fallback_payload_sha256")),
        "fallback_payload_size_bytes": _optional_int(raw.get("fallback_payload_size_bytes")),
        "fallback_observation_dates": _optional_string_tuple(
            raw.get("fallback_observation_dates")
        ),
        "fallback_requested_date": _optional_text(raw.get("fallback_requested_date")),
        "fallback_quarantine_reasons": _optional_string_tuple(
            raw.get("fallback_quarantine_reasons")
        ),
        "fallback_error_type": _optional_text(raw.get("fallback_error_type")),
        "fallback_error": _optional_text(raw.get("fallback_error")),
        "primary_official_status": _optional_text(raw.get("primary_official_status")),
        "pit_status": _optional_text(raw.get("pit_status")),
        "timestamp_kind": _optional_text(raw.get("timestamp_kind")),
        "probe_outcome": _optional_text(raw.get("probe_outcome")),
        "schema_status": _optional_text(raw.get("schema_status")),
        "availability": _optional_text(raw.get("availability")),
        "license_evidence_urls": _license_evidence_urls(raw.get("acquisition_routes")),
        "blockers": _unique_strings(_string_tuple(raw.get("blockers", ()))),
    }


def _normalize_license_evidence(
    payload: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Validate a candidate license-capture artifact without granting authority."""

    if not isinstance(payload, Mapping):
        raise TypeError("P0 license evidence must be an object")
    if payload.get("schema_version") != _LICENSE_CAPTURE_SCHEMA:
        raise ValueError("unsupported P0 license evidence schema")
    _require_boundary(
        payload,
        {
            "candidate_only": True,
            "source_acceptance_granted": False,
            "license_accepted": False,
            "downstream_eligibility": "none",
            "formal_eligible": False,
            "production_ingestion_allowed": False,
            "production_scheduler_allowed": False,
        },
    )
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list):
        raise ValueError("P0 license evidence targets must be an array")
    allowed_urls = {
        route.license_evidence_url
        for source_id in P0_SOURCE_IDS
        for route in build_p0_acquisition_route_registry().for_source(source_id)
    }
    result: dict[str, Mapping[str, Any]] = {}
    for raw in raw_targets:
        if not isinstance(raw, Mapping):
            raise TypeError("P0 license evidence target must be an object")
        url = _optional_text(raw.get("license_evidence_url"))
        if url is None or url not in allowed_urls:
            raise ValueError("P0 license evidence URL is outside the route registry")
        if url in result:
            raise ValueError(f"duplicate P0 license evidence URL: {url}")
        source_ids = raw.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            raise ValueError("P0 license evidence source_ids must be a non-empty array")
        normalized_sources = tuple(_string_tuple(source_ids))
        if any(source_id not in P0_SOURCE_IDS for source_id in normalized_sources):
            raise ValueError("P0 license evidence source is outside the denominator")
        status = _optional_text(raw.get("status"))
        if status not in {"captured", "http_error", "transport_error", "not_captured"}:
            raise ValueError("unsupported P0 license evidence target status")
        content_sha256 = _optional_text(raw.get("content_sha256"))
        if content_sha256 is not None and (
            len(content_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in content_sha256)
        ):
            raise ValueError("P0 license evidence content_sha256 must be 64 hex characters")
        keyword_flags = raw.get("keyword_flags", {})
        if keyword_flags is not None and not isinstance(keyword_flags, Mapping):
            raise TypeError("P0 license evidence keyword_flags must be an object")
        result[url] = {
            "license_evidence_url": url,
            "source_ids": normalized_sources,
            "status": status,
            "content_sha256": content_sha256,
            "keyword_flags": keyword_flags if isinstance(keyword_flags, Mapping) else {},
        }
    if not result:
        raise ValueError("P0 license evidence must contain at least one target")
    return result


def _license_records_for_source(
    source_id: str,
    license_items: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        item
        for item in license_items.values()
        if source_id in _string_tuple(item.get("source_ids", ()))
    )


def _license_urls_for_source(
    source_id: str,
    audit: Mapping[str, Any] | None,
    license_items: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    urls = list(_string_tuple(audit.get("license_evidence_urls", ()))) if audit else []
    for item in _license_records_for_source(source_id, license_items):
        url = _optional_text(item.get("license_evidence_url"))
        if url is not None and url not in urls:
            urls.append(url)
    return tuple(dict.fromkeys(urls))


def _license_capture_status_for_source(
    source_id: str,
    license_items: Mapping[str, Mapping[str, Any]],
) -> str:
    records = _license_records_for_source(source_id, license_items)
    if not records:
        return "not_supplied"
    statuses = {str(item.get("status")) for item in records}
    if statuses == {"captured"}:
        return "captured_candidate"
    if statuses == {"not_captured"}:
        return "preview_not_captured"
    # A source can legitimately reference more than one official terms page
    # (for example TWSE and TPEx).  Do not let one failed URL hide a successful
    # candidate fingerprint from another URL; the owner still has to review
    # every URL, so this is only a transport/readability projection.
    if "captured" in statuses:
        return "capture_partial"
    for status in ("transport_error", "http_error"):
        if status in statuses:
            return f"capture_{status}"
    return "capture_incomplete"


def _license_capture_hashes_for_source(
    source_id: str,
    license_items: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    hashes = {
        value
        for item in _license_records_for_source(source_id, license_items)
        for value in (_optional_text(item.get("content_sha256")),)
        if value is not None
    }
    return tuple(sorted(hashes))


def _license_capture_keyword_groups_for_source(
    source_id: str,
    license_items: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    groups: set[str] = set()
    for item in _license_records_for_source(source_id, license_items):
        flags = item.get("keyword_flags")
        if not isinstance(flags, Mapping):
            continue
        for group, value in flags.items():
            if isinstance(value, Mapping) and value.get("matched") is True:
                groups.add(str(group))
    return tuple(sorted(groups))


def _require_boundary(payload: Mapping[str, Any], expected: Mapping[str, object]) -> None:
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"P0 audit boundary mismatch: {key}")


def _governance_status(
    *, audit: Mapping[str, Any] | None, machine_status: str, decision_status: str
) -> str:
    if decision_status in {"rejected", "disabled", "deferred", "limited", "accepted"}:
        return decision_status
    if audit is None:
        return "contract_only"
    if machine_status in {"missing", "degraded", "blocked", "unavailable", "not_observed"}:
        return "blocked_provenance"
    audit_status = _text(audit.get("audit_status"))
    if audit_status in {
        "schema_blocked",
        "candidate_artifact_not_supplied",
        "probe_not_returned",
        "not_started_no_candidate_adapter",
        "probe_failed",
        "artifact_missing",
        "not_probed",
    }:
        return "blocked_provenance"
    return "research_shadow"


def _owner_actions(
    *, audit: Mapping[str, Any] | None, decision_status: str, blockers: tuple[str, ...]
) -> tuple[str, ...]:
    actions: list[str] = []
    if audit is None:
        actions.append("執行 bounded official read-only 稽核並保存來源證據")
    if any(
        blocker in blockers
        for blocker in (
            "official_publication_timestamp_missing",
            "decision_time_availability_not_proven",
            "mops_candidate_artifact_not_supplied",
            "candidate_audit_not_supplied",
        )
    ):
        actions.append("補齊 PIT 可得日／公告時間與 row provenance")
    if "license_not_accepted" in blockers:
        actions.append("由資料擁有者與法務記錄 license／再分發條款")
    if decision_status in {"not_supplied", "deferred", "rejected", "disabled"}:
        actions.append("取得 owner／reviewer 的明確 source acceptance 決議")
    actions.append("維持 downstream_eligibility=none；不得自動接受或升級")
    return tuple(dict.fromkeys(actions))


def _freeze_counts(values: Mapping[str, int]) -> Mapping[str, int]:
    result: dict[str, int] = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("status counts must be non-negative integers")
        result[str(key)] = value
    return MappingProxyType(dict(sorted(result.items())))


def _optional_int(value: object, *, maximum: int | None = None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("audit numeric fields must be non-negative integers")
    if maximum is not None and value > maximum:
        raise ValueError("audit numeric field exceeds maximum")
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise TypeError("audit boolean fields must be boolean values")
    return value


def _coverage_bp(observed_rows: int | None, accepted_rows: int | None) -> int | None:
    """從 evidence matrix 的 row conservation 數字推導整數基點覆蓋率。"""
    if observed_rows is None or accepted_rows is None or observed_rows <= 0:
        return None
    if accepted_rows < 0 or accepted_rows > observed_rows:
        return None
    return (accepted_rows * 10_000) // observed_rows


def _route_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError("acquisition_routes must be an array")
    route_ids: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("acquisition route must be an object")
        route_id = _optional_text(item.get("route_id"))
        if route_id is not None:
            route_ids.append(route_id)
    return tuple(dict.fromkeys(route_ids))


def _license_evidence_urls(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError("acquisition_routes must be an array")
    urls: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("acquisition route must be an object")
        url = _optional_text(item.get("license_evidence_url"))
        if url is not None:
            urls.append(url)
    return tuple(dict.fromkeys(urls))


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("audit text fields must be strings")
    return value or None


def _text(value: object) -> str:
    return _optional_text(value) or "unknown"


def _string_tuple(values: Iterable[object] | object) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise TypeError("string collection must be an iterable of strings")
    materialized = tuple(values)
    if not all(isinstance(value, str) for value in materialized):
        raise TypeError("string collection must contain strings")
    return materialized


def _optional_string_tuple(value: object) -> tuple[str, ...]:
    """將可選的 evidence array 正規化；缺少／null 不代表虛構資料。"""
    if value is None:
        return ()
    return _string_tuple(value)


def _unique_strings(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("diagnostic values must be strings")
        if value and value not in result:
            result.append(value)
    return tuple(result)
