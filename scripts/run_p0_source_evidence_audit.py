"""產生 13 項 P0 官方來源證據與就緒度 (Readiness) 稽核報告與 Owner 群組化決策包。

本 CLI 工具具備下列特性：
1. 預設模式僅讀取已知 fixture / 既有 artifact，不打網路。
2. Live 探測模式必須明確傳入 --live 且配合 --confirm-live-readonly 旗標。
3. 輸出路徑嚴格限制於 approved TEMP / candidate-safe 目錄，絕對不寫入正式 DB 或 repo。
4. 13 項 P0 來源收斂為最多 5 個群組化 Owner 決策問題，集中討論內部研究意圖/條款接受度。
"""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.p0_source_acquisition_routes import (
    build_p0_acquisition_route_registry,
)
from scripts.run_p0_candidate_audit import (
    LIVE_PROBE_SOURCE_MAP,
    _probe_report_sha256,
    _validate_fubon_projection,
    _validate_mops_quarterly_artifact,
    _validate_probe_report,
    _validated_probe_counts,
)
from scripts.update_phase3c_candidates import run_bounded_official_probe


GROUPED_OWNER_PACKET_KEYS = (
    "twse_market_corporate",
    "twse_microstructure",
    "twse_flows_credit",
    "tdcc_distribution",
    "mops_monthly_quarterly",
)

GROUPED_OWNER_PACKET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "twse_market_corporate": {
        "group_id": "twse_market_corporate",
        "title": "TWSE 除權息與減資/分割/面額變更事件時間軸",
        "covered_source_ids": [
            "corporate_action.ex_dividend_timeline",
            "corporate_action.reduction_split_par_value",
        ],
        "provider": "TWSE 臺灣證券交易所 (TWT49U / TWTAUU)",
        "owner_question": "是否核准將來自 TWSE (TWT49U/TWTAUU) 的除權息與減資／分割／面額變更資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "twse_microstructure": {
        "group_id": "twse_microstructure",
        "title": "TWSE 交易限制與成交可行性 Preflight",
        "covered_source_ids": [
            "microstructure.suspended_halt_resume",
            "microstructure.disposition_stock",
            "microstructure.periodic_call_auction",
            "microstructure.full_delivery",
            "microstructure.limit_lock",
        ],
        "provider": "TWSE 臺灣證券交易所 (TWTAWU / 處置公告 / TWT85U / TWT84U)",
        "owner_question": "是否核准將來自 TWSE (TWTAWU/處置公告/TWT85U/TWT84U) 的停復牌、處置、分盤撮合、全額交割與漲跌停鎖死觀測作為交易限制與成交可行性 preflight 備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "twse_flows_credit": {
        "group_id": "twse_flows_credit",
        "title": "TWSE 三大法人買賣超與信用交易",
        "covered_source_ids": [
            "institutional_flows",
            "credit_transactions",
        ],
        "provider": "TWSE 臺灣證券交易所 (T86 / MI_MARGN)",
        "owner_question": "是否核准將來自 TWSE (T86/MI_MARGN) 的三大法人買賣超與信用交易（融資融券）餘額資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "tdcc_distribution": {
        "group_id": "tdcc_distribution",
        "title": "TDCC 集保持股分散級距",
        "covered_source_ids": [
            "tdcc_shareholding",
        ],
        "provider": "TDCC 臺灣集中保管結算所 (OpenData 1-5)",
        "owner_question": "是否核准將來自 TDCC 1-5 開放資料的集保持股分散級距資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
    "mops_monthly_quarterly": {
        "group_id": "mops_monthly_quarterly",
        "title": "TWSE/TPEx 月營收公告與 MOPS 季度財報 Artifact",
        "covered_source_ids": [
            "twse.monthly_revenue_announcement",
            "tpex.monthly_revenue_announcement",
            "pit.quarterly_financials",
        ],
        "provider": "TWSE / TPEx OpenAPI (營收) & MOPS 公開資訊觀測站 (季報 Artifact)",
        "owner_question": "是否核准將來自 TWSE/TPEx OpenData 月營收公告與 MOPS 官方採集之合併未更正季報歷史 Artifact 作為 PIT 營收與財報比對備選源？（條款限制：僅供內部研究使用，不可對外再散布）",
    },
}

SOURCE_PROVIDER_INFO: dict[str, tuple[str, str, str]] = {
    "corporate_action.ex_dividend_timeline": ("TWSE", "exchangeReport:TWT49U", "bounded_live_probe"),
    "corporate_action.reduction_split_par_value": ("TWSE", "exchangeReport:TWTAUU", "bounded_live_probe"),
    "microstructure.suspended_halt_resume": ("TWSE", "exchangeReport:TWTAWU", "bounded_live_probe"),
    "microstructure.disposition_stock": ("TWSE", "announcement:punish", "bounded_live_probe"),
    "microstructure.periodic_call_auction": ("TWSE", "announcement:punish", "bounded_live_probe"),
    "microstructure.full_delivery": ("TWSE", "exchangeReport:TWT85U", "bounded_live_probe"),
    "microstructure.limit_lock": ("TWSE", "exchangeReport:TWT84U", "bounded_live_probe"),
    "institutional_flows": ("TWSE", "fund:T86", "bounded_live_probe"),
    "credit_transactions": ("TWSE", "exchangeReport:MI_MARGN", "bounded_live_probe"),
    "tdcc_shareholding": ("TDCC", "opendata:1-5", "bounded_live_probe"),
    "twse.monthly_revenue_announcement": ("TWSE", "opendata:t187ap05_L", "bounded_live_probe"),
    "tpex.monthly_revenue_announcement": ("TPEx", "openapi:mopsfin_t187ap05_O", "bounded_live_probe"),
    "pit.quarterly_financials": ("MOPS", "statement:publication_artifact", "existing_artifact"),
}

REDACT_KEYS = {"api_key", "cookie", "credential", "password", "authorization", "secret", "token"}

MICROSTRUCTURE_SOURCE_IDS = (
    "microstructure.suspended_halt_resume",
    "microstructure.disposition_stock",
    "microstructure.periodic_call_auction",
    "microstructure.full_delivery",
    "microstructure.limit_lock",
)

MICROSTRUCTURE_TIMESTAMP_POLICIES: dict[str, dict[str, str]] = {
    "microstructure.suspended_halt_resume": {
        "primary_evidence_class": "first_observed_only",
        "primary_field": "first_observed_at",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "停牌／復牌有效狀態與事件順序的 research preflight",
    },
    "microstructure.disposition_stock": {
        "primary_evidence_class": "official_publication_date_only",
        "primary_field": "official_publication_date",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "處置公告日期、有效期間與措施內容的 research preflight",
    },
    "microstructure.periodic_call_auction": {
        "primary_evidence_class": "official_publication_date_only",
        "primary_field": "official_publication_date",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "由處置公告相符措施衍生的分盤撮合 research preflight",
    },
    "microstructure.full_delivery": {
        "primary_evidence_class": "market_session_observation",
        "primary_field": "market_session_date",
        "pit_blocker": "official_publication_timestamp_missing",
        "research_use": "全額交割／交易方法當日狀態的 research preflight",
    },
    "microstructure.limit_lock": {
        "primary_evidence_class": "market_session_observation",
        "primary_field": "market_session_date",
        "pit_blocker": "decision_time_availability_not_proven",
        "research_use": "漲跌停鎖死的交易日行情觀測與成交可行性 research preflight",
    },
}

TIMESTAMP_FIELDS = (
    "official_publication_timestamp",
    "official_publication_date",
    "effective_from",
    "effective_to",
    "market_session_date",
    "decision_time_observed_at",
    "first_observed_at",
    "captured_at",
    "http_date",
    "http_last_modified",
)


def _timestamp_field_projection(
    probe: Mapping[str, Any],
    *,
    field_name: str,
    evidence_class: str,
    pit_gate_allowed: bool,
    missing_reason: str,
) -> dict[str, Any]:
    source_field = field_name
    value = probe.get(field_name)
    if field_name == "http_last_modified" and value is None:
        source_field = "last_modified"
        value = probe.get(source_field)
    return {
        "raw_evidence_location": f"probe.{source_field}",
        "normalized_value": value,
        "timezone": "Asia/Taipei" if field_name not in {"http_date", "http_last_modified"} else "HTTP-header-defined",
        "evidence_class": evidence_class if value is not None else "missing",
        "quality": "verified" if value is not None else "missing",
        "pit_gate_allowed": pit_gate_allowed and value is not None,
        "reason_code": None if value is not None else missing_reason,
    }


def _build_microstructure_timestamp_semantics(
    source_id: str,
    probe: Mapping[str, Any],
    *,
    decision_date: date,
) -> dict[str, Any]:
    policy = MICROSTRUCTURE_TIMESTAMP_POLICIES[source_id]
    primary_class = policy["primary_evidence_class"]
    primary_field = policy["primary_field"]
    semantics: dict[str, dict[str, Any]] = {}

    for field_name in TIMESTAMP_FIELDS:
        if field_name in {"http_date", "http_last_modified"}:
            evidence_class = "capture_time_only"
            pit_gate_allowed = False
            missing_reason = "http_header_not_supplied"
        elif field_name == "official_publication_timestamp":
            evidence_class = "official_row_timestamp"
            pit_gate_allowed = True
            missing_reason = "official_publication_timestamp_not_proven"
        elif field_name == "official_publication_date":
            evidence_class = "official_publication_date_only"
            pit_gate_allowed = False
            missing_reason = "official_publication_date_not_exposed_by_probe"
        elif field_name in {"effective_from", "effective_to"}:
            evidence_class = "effective_date_only"
            pit_gate_allowed = False
            missing_reason = "effective_period_not_exposed_by_probe"
        elif field_name == "market_session_date":
            evidence_class = "market_session_observation"
            pit_gate_allowed = False
            missing_reason = "market_session_date_not_exposed_by_probe"
        elif field_name == "decision_time_observed_at":
            evidence_class = "market_session_observation"
            pit_gate_allowed = True
            missing_reason = "decision_time_observation_not_exposed_by_probe"
        elif field_name == "captured_at":
            evidence_class = "capture_time_only"
            pit_gate_allowed = False
            missing_reason = "capture_time_not_exposed_by_probe"
        elif field_name == "first_observed_at":
            evidence_class = "first_observed_only"
            pit_gate_allowed = False
            missing_reason = "first_observed_time_not_exposed_by_probe"
        else:
            evidence_class = "missing"
            pit_gate_allowed = False
            missing_reason = f"{field_name}_not_proven"
        semantics[field_name] = _timestamp_field_projection(
            probe,
            field_name=field_name,
            evidence_class=evidence_class,
            pit_gate_allowed=pit_gate_allowed,
            missing_reason=missing_reason,
        )

    if primary_field == "market_session_date" and semantics[primary_field]["normalized_value"] is None:
        semantics[primary_field] = {
            "raw_evidence_location": "probe.probe_date",
            "normalized_value": decision_date.isoformat(),
            "timezone": "Asia/Taipei",
            "evidence_class": "market_session_observation",
            "quality": "date_only",
            "pit_gate_allowed": False,
            "reason_code": "decision_time_within_session_not_proven",
        }

    return {
        "source_id": source_id,
        "primary_evidence_class": primary_class,
        "primary_field": primary_field,
        "fields": semantics,
        "http_headers_never_promoted_to_publication": True,
        "capture_time_never_promoted_to_publication": True,
        "first_observed_never_backfilled_as_publication": True,
    }


def _microstructure_owner_recommendation(
    item: Mapping[str, Any],
    *,
    fubon_shadow_usable: bool,
) -> dict[str, Any]:
    source_id = str(item["source_id"])
    policy = MICROSTRUCTURE_TIMESTAMP_POLICIES[source_id]
    machine_blockers = [str(item["remaining_blocker"])]
    return {
        "source_id": source_id,
        "proposed_decision": "deferred",
        "machine_recommendation": "deferred",
        "ready_for_owner_review": False,
        "timestamp_evidence_class": item["timestamp_kind"],
        "pit_gate_allowed": False,
        "permitted_research_use": policy["research_use"],
        "prohibited_use": [
            "formal_evidence_credit",
            "production_ingestion",
            "formal_score_or_advice",
            "broker_execution",
        ],
        "machine_blockers": machine_blockers,
        "human_blockers": ["legal_license_review", "owner_written_acceptance"],
        "fubon_shadow_usable": fubon_shadow_usable,
        "fubon_formal_credit_allowed": False,
        "production_blend_alpha_bp": 0,
        "rollback_path": "disable_or_supersede_future_owner_decision; preserve append-only evidence",
    }


def validate_approved_output_path(target_path: Path) -> bool:
    """確認輸出路徑是否位於 OS TEMP 內。

    本工具目前沒有受治理的 candidate-safe 輸出根目錄；因此不能僅憑
    路徑中含有 ``candidate``、``temp`` 或 ``handoff`` 等字串就放行。這可
    避免誤將報告寫回 repository 或任何正式資料根目錄。
    """
    resolved = target_path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()

    # Allow inside OS temp directory
    try:
        resolved.relative_to(temp_root)
        return True
    except ValueError:
        pass

    return False


def redact_secrets(data: Any) -> Any:
    """遞迴過濾敏感資訊（API keys, credentials, cookies）。"""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if str(k).lower() in REDACT_KEYS:
                result[k] = "[REDACTED]"
            else:
                result[k] = redact_secrets(v)
        return result
    if isinstance(data, list):
        return [redact_secrets(item) for item in data]
    return data


def build_p0_source_evidence_audit(
    decision_date: date,
    *,
    probe_report: Mapping[str, Any] | None = None,
    fubon_projection: Mapping[str, Any] | None = None,
    mops_quarterly_artifact: Mapping[str, Any] | None = None,
    live_mode: bool = False,
    confirm_live_readonly: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """產出 13 項 P0 官方來源證據矩陣與 5 個 Owner 群組化決策包。"""
    if live_mode and not confirm_live_readonly:
        raise ValueError("live 探測模式必須明確指定 --confirm-live-readonly 旗標")

    if output_path is not None:
        if not validate_approved_output_path(output_path):
            raise ValueError(
                f"輸出路徑 {output_path} 不位於 approved TEMP / candidate-safe 目錄，拒絕執行"
            )

    if probe_report is not None:
        report = dict(probe_report)
        live_executed = False
    elif live_mode:
        report = dict(run_bounded_official_probe(decision_date))
        live_executed = True
    else:
        # Default offline mode: mock unprobed or fixture report
        report = {
            "probe_date": decision_date.isoformat(),
            "probe_mode": "bounded_official_read_only",
            "license_accepted": False,
            "source_accepted": False,
            "downstream_eligibility": "none",
            "production_scheduler_allowed": False,
            "human_decision": "requires_human_acceptance",
            "sources": [],
        }
        live_executed = False

    probe_items = _validate_probe_report(report, decision_date)
    acquisition_routes = build_p0_acquisition_route_registry()
    fubon_items = _validate_fubon_projection(fubon_projection) if fubon_projection is not None else {}
    mops_rows = _validate_mops_quarterly_artifact(mops_quarterly_artifact) if mops_quarterly_artifact is not None else []

    matrix: list[dict[str, Any]] = []

    for source_id in P0_SOURCE_IDS:
        provider, endpoint_type, acquisition_mode = SOURCE_PROVIDER_INFO[source_id]

        if source_id == "pit.quarterly_financials":
            if mops_rows:
                item = {
                    "source_id": source_id,
                    "family": "pit",
                    "provider": provider,
                    "endpoint_or_artifact_type": endpoint_type,
                    "acquisition_mode": acquisition_mode,
                    "machine_status": "verified",
                    "pit_status": "pit_date_verified",
                    "timestamp_kind": "official_document_upload_timestamp",
                    "availability": "artifact_verified",
                    "schema_status": "matched",
                    "payload_sha256": mops_rows[0]["source_hash"],
                    "remaining_blocker": "legal_and_license_acceptance_required",
                    "auto_verifiable": [
                        "schema_validation_passed",
                        "row_conservation_verified",
                        "isolation_guaranteed",
                        "payload_hash_verified",
                        "mops_artifact_provenance_verified",
                    ],
                    "non_auto_verifiable": [
                        "legal_license_review",
                        "owner_written_acceptance",
                    ],
                }
            else:
                item = {
                    "source_id": source_id,
                    "family": "pit",
                    "provider": provider,
                    "endpoint_or_artifact_type": endpoint_type,
                    "acquisition_mode": acquisition_mode,
                    "machine_status": "missing",
                    "pit_status": "unavailable",
                    "timestamp_kind": "unavailable",
                    "availability": "artifact_missing",
                    "schema_status": "unavailable",
                    "payload_sha256": None,
                    "remaining_blocker": "mops_candidate_artifact_not_supplied",
                    "auto_verifiable": ["adapter_contract_implemented"],
                    "non_auto_verifiable": ["mops_candidate_artifact_supply"],
                }
            item["acquisition_routes"] = [
                route.to_dict()
                for route in acquisition_routes.for_source(source_id)
            ]
            matrix.append(item)
            continue

        probe_source_id = LIVE_PROBE_SOURCE_MAP.get(source_id)
        probe = probe_items.get(probe_source_id) if probe_source_id else None

        if probe is None:
            availability = "probe_failed" if (live_executed or report["sources"]) else "not_probed"
            item = {
                "source_id": source_id,
                "family": source_id.split(".")[0],
                "provider": provider,
                "endpoint_or_artifact_type": endpoint_type,
                "acquisition_mode": acquisition_mode,
                "machine_status": "missing",
                "pit_status": "unavailable",
                "timestamp_kind": "unavailable",
                "availability": availability,
                "schema_status": "unavailable",
                "payload_sha256": None,
                "remaining_blocker": "official_probe_not_returned",
                "auto_verifiable": ["adapter_contract_implemented"],
                "non_auto_verifiable": ["network_probe_execution", "legal_license_review"],
            }
            item["acquisition_routes"] = [
                route.to_dict()
                for route in acquisition_routes.for_source(source_id)
            ]
            matrix.append(item)
            continue

        counts = _validated_probe_counts(probe)
        raw_timestamp_evidence = str(probe.get("timestamp_evidence", "unavailable"))
        schema_status = str(probe.get("schema_status", "mismatch"))
        network_status = str(probe.get("network_status", "reachable"))
        probe_outcome = str(probe.get("probe_outcome", "unknown"))

        if network_status == "failed":
            availability = "probe_failed"
        elif probe_outcome == "official_no_data" or schema_status == "no_data":
            availability = "official_no_data"
        else:
            availability = "network_probed"

        if network_status == "failed":
            machine_status = "missing"
            pit_status = "unavailable"
            timestamp_kind = "unavailable"
            remaining_blocker = "network_probe_failed"
        elif probe_outcome == "official_no_data" or schema_status == "no_data":
            machine_status = "missing"
            pit_status = "unavailable"
            timestamp_kind = "unavailable"
            remaining_blocker = "official_no_data_for_requested_date"
        elif schema_status == "matched" and raw_timestamp_evidence == "official_publication_timestamp":
            machine_status = "verified"
            pit_status = "pit_date_verified"
            timestamp_kind = "official_publication_timestamp"
            remaining_blocker = "legal_and_license_acceptance_required"
        elif schema_status == "matched":
            machine_status = "degraded"
            pit_status = "official_publication_timestamp_missing"
            timestamp_kind = "first_observed_only"
            remaining_blocker = "official_publication_timestamp_missing"
        else:
            machine_status = "missing"
            pit_status = "unavailable"
            timestamp_kind = "unavailable"
            remaining_blocker = "schema_mismatch_or_probe_failed"

        if schema_status == "matched" and network_status != "failed":
            auto_verifiable = [
                "schema_validation_passed",
                "row_conservation_verified",
                "isolation_guaranteed",
                "payload_hash_verified",
            ]
            non_auto_verifiable = [
                "legal_license_review",
                "owner_written_acceptance",
            ]
        else:
            auto_verifiable = ["adapter_contract_implemented"]
            if network_status != "failed" and probe.get("payload_sha256"):
                auto_verifiable.append("payload_hash_verified")
            non_auto_verifiable = [
                "completed_publication_probe_or_schema_repair",
                "legal_license_review",
                "owner_written_acceptance",
            ]

        item = {
            "source_id": source_id,
            "family": source_id.split(".")[0],
            "provider": provider,
            "endpoint_or_artifact_type": endpoint_type,
            "acquisition_mode": acquisition_mode,
            "machine_status": machine_status,
            "pit_status": pit_status,
            "timestamp_kind": timestamp_kind,
            "availability": availability,
            "schema_status": schema_status,
            "probe_outcome": probe_outcome,
            "payload_sha256": probe.get("payload_sha256"),
            "raw_row_count": counts["raw_row_count"],
            "accepted_row_count": counts["accepted_row_count"],
            "quarantine_row_count": counts["quarantine_row_count"],
            "blocked_row_count": counts["blocked_row_count"],
            "remaining_blocker": remaining_blocker,
            "auto_verifiable": auto_verifiable,
            "non_auto_verifiable": non_auto_verifiable,
        }
        if (
            source_id in MICROSTRUCTURE_SOURCE_IDS
            and schema_status == "matched"
            and network_status != "failed"
        ):
            policy = MICROSTRUCTURE_TIMESTAMP_POLICIES[source_id]
            timestamp_semantics = _build_microstructure_timestamp_semantics(
                source_id,
                probe,
                decision_date=decision_date,
            )
            primary_field = policy["primary_field"]
            primary_projection = timestamp_semantics["fields"][primary_field]
            official_timestamp = timestamp_semantics["fields"][
                "official_publication_timestamp"
            ]
            if (
                raw_timestamp_evidence == "official_publication_timestamp"
                and official_timestamp["normalized_value"] is not None
            ):
                timestamp_kind = "official_row_timestamp"
                pit_status = "pit_timestamp_verified"
                remaining_blocker = "legal_and_license_acceptance_required"
                item["machine_status"] = "verified"
            elif primary_projection["normalized_value"] is not None:
                timestamp_kind = str(primary_projection["evidence_class"])
                pit_status = (
                    "market_session_observation_only"
                    if timestamp_kind == "market_session_observation"
                    else "official_publication_date_only"
                )
                remaining_blocker = policy["pit_blocker"]
            else:
                timestamp_kind = "first_observed_only"
                pit_status = "official_publication_timestamp_missing"
                remaining_blocker = policy["pit_blocker"]
            item["timestamp_kind"] = timestamp_kind
            item["pit_status"] = pit_status
            item["remaining_blocker"] = remaining_blocker
            item["timestamp_semantics"] = timestamp_semantics
        if "request_parameters" in probe:
            item["request_parameters"] = probe["request_parameters"]
        for route_field in (
            "endpoint_id",
            "acquisition_route_id",
            "fallback_used",
            "fallback_from_endpoint_id",
            "fallback_from_acquisition_route_id",
        ):
            if route_field in probe:
                item[route_field] = probe[route_field]
        item["acquisition_routes"] = [
            route.to_dict() for route in acquisition_routes.for_source(source_id)
        ]
        matrix.append(item)

    # Aggregate matrix into 5 grouped owner decision questions
    grouped_packet: list[dict[str, Any]] = []
    matrix_by_id = {item["source_id"]: item for item in matrix}

    for group_key in GROUPED_OWNER_PACKET_KEYS:
        defn = GROUPED_OWNER_PACKET_DEFINITIONS[group_key]
        covered_ids = defn["covered_source_ids"]
        sub_items = [matrix_by_id[sid] for sid in covered_ids if sid in matrix_by_id]

        verified_count = sum(1 for item in sub_items if item["machine_status"] == "verified")
        degraded_count = sum(1 for item in sub_items if item["machine_status"] == "degraded")
        missing_count = sum(1 for item in sub_items if item["machine_status"] == "missing")

        grouped_packet.append(
            {
                "group_id": defn["group_id"],
                "title": defn["title"],
                "covered_source_ids": covered_ids,
                "provider": defn["provider"],
                "owner_question": defn["owner_question"],
                "group_status_summary": {
                    "total_sources": len(covered_ids),
                    "verified_sources": verified_count,
                    "degraded_sources": degraded_count,
                    "missing_sources": missing_count,
                },
                "decision_scope": "internal_research_only_intent_and_terms_acceptability",
                **(
                    {
                        "source_recommendations": [
                            _microstructure_owner_recommendation(
                                matrix_by_id[source_id],
                                fubon_shadow_usable=bool(fubon_items.get(source_id)),
                            )
                            for source_id in covered_ids
                        ],
                        "fubon_shadow_usable": any(
                            bool(fubon_items.get(source_id)) for source_id in covered_ids
                        ),
                        "fubon_formal_credit_allowed": False,
                        "production_blend_alpha_bp": 0,
                    }
                    if group_key == "twse_microstructure"
                    else {}
                ),
            }
        )

    verified_sources = sum(1 for item in matrix if item["machine_status"] == "verified")
    degraded_sources = sum(1 for item in matrix if item["machine_status"] == "degraded")
    missing_sources = sum(1 for item in matrix if item["machine_status"] == "missing")

    payload = {
        "schema_version": "p0-source-evidence-audit.v1",
        "task_id": "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1",
        "decision_date": decision_date.isoformat(),
        "mode": "bounded_official_read_only",
        "live_probe_executed": live_executed,
        "machine_evidence_matrix": matrix,
        "grouped_owner_decision_packet": grouped_packet,
        "acquisition_route_summary": acquisition_routes.to_dict(),
        "machine_vs_owner_blocker_summary": {
            "total_sources": len(matrix),
            "machine_verified_sources": verified_sources,
            "degraded_sources": degraded_sources,
            "missing_sources": missing_sources,
            "grouped_owner_decision_count": len(grouped_packet),
        },
        "formal_clock_zeros": {
            "snapshot_count": 0,
            "observed_days": 0,
            "outcome_denominator": 0,
            "formal_credit": 0,
        },
        "safety_flags": {
            "formal_oos_allowed": False,
            "formal_evidence_credit_authorized": False,
            "production_allowed": False,
            "production_blend_alpha_bp": 0,
            "training_allowed": False,
            "promotion_allowed": False,
            "scheduler_allowed": False,
            "unblind_allowed": False,
            "formal_rule_only_path_unchanged": True,
            "downstream_eligibility": "none",
            "human_decision": "requires_human_acceptance",
        },
    }

    sanitized_payload = redact_secrets(payload)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(sanitized_payload, ensure_ascii=False, indent=2) + "\n"
        output_path.write_text(rendered, encoding="utf-8")

    return sanitized_payload


def export_p0_13_handoff_json(
    audit_payload: dict[str, Any],
    *,
    git_status_str: str = "unverified",
    test_results: dict[str, Any] | None = None,
) -> Path:
    """匯出真實 handoff JSON 至指定 %TEMP% 目錄。"""
    temp_dir = Path(tempfile.gettempdir())
    handoff_dir = temp_dir / "technical_analysis_gemini_handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    target_path = handoff_dir / "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1.json"

    changed_files = [
        "data_module/p0_source_contract_registry.py",
        "data_module/p0_official_source_parsers.py",
        "scripts/run_p0_source_evidence_audit.py",
        "scripts/run_p0_candidate_audit.py",
        "scripts/update_phase3c_candidates.py",
        "tests/test_run_p0_source_evidence_audit.py",
        "tests/test_run_p0_candidate_audit.py",
        "tests/test_p0_official_source_parsers.py",
        "qa/full_app_healthcheck/test_inventory.py",
        "docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md",
        "docs/07_guides/APPLICATION_MANUAL.md",
    ]
    changed_file_entries: list[dict[str, str]] = []
    for rel_path in changed_files:
        abs_p = PROJECT_ROOT / rel_path
        if abs_p.exists():
            changed_file_entries.append(
                {"path": rel_path, "sha256": sha256(abs_p.read_bytes()).hexdigest()}
            )

    handoff = {
        "task_id": "GEMINI-P0-13-OFFICIAL-EVIDENCE-AND-READINESS-HARDENING-V1",
        # This CLI can validate a supplied evidence payload, but cannot know the
        # terminal result of pytest/mypy or the final Git state.  A reviewer must
        # add those facts to a separate handoff after independent verification.
        "status": "audit_generated_not_validation_handoff",
        "base_head": "6f245223f5c6c599a9e3341687cca10b0512ebe8",
        "timestamp": audit_payload.get("decision_date"),
        "live_probe_executed": audit_payload.get("live_probe_executed", False),
        "changed_files": changed_file_entries,
        "machine_evidence_matrix": audit_payload.get("machine_evidence_matrix", []),
        "grouped_owner_decision_packet": audit_payload.get("grouped_owner_decision_packet", []),
        "machine_vs_owner_blocker_summary": audit_payload.get("machine_vs_owner_blocker_summary", {}),
        "test_suite_results": test_results or {
            "status": "not_run_by_cli",
            "reason": "terminal validation must be recorded by the independent reviewer",
        },
        "formal_clock_zeros": {
            "snapshot_count": 0,
            "observed_days": 0,
            "outcome_denominator": 0,
            "formal_credit": 0,
            "production_blend_alpha_bp": 0,
        },
        "safety_flags": audit_payload.get("safety_flags", {}),
        "git_status": {
            "working_tree_clean_for_commit": False,
            "no_git_commit_performed": True,
            "details": git_status_str,
        },
        "blockers_and_known_limitations": [
            "13 P0 sources remain research_only with downstream_eligibility=none",
            "formal source acceptance by owner remains pending",
            "production scheduler and DB writes remain prohibited",
        ],
        "recommended_commit_batches": [
            {
                "batch_id": "batch-1-evidence-contracts-and-parsers",
                "title": "Harden P0 source contracts, publication timestamp semantics, and test inventory",
                "files": [
                    "data_module/p0_source_contract_registry.py",
                    "data_module/p0_official_source_parsers.py",
                    "qa/full_app_healthcheck/test_inventory.py",
                    "tests/test_run_p0_source_evidence_audit.py",
                ],
            },
            {
                "batch_id": "batch-2-audit-cli-and-grouped-packet",
                "title": "Add read-only P0-13 source evidence audit CLI and 5-group owner decision packet",
                "files": [
                    "scripts/run_p0_source_evidence_audit.py",
                    "scripts/run_p0_candidate_audit.py",
                    "scripts/update_phase3c_candidates.py",
                    "tests/test_run_p0_candidate_audit.py",
                ],
            },
            {
                "batch_id": "batch-3-acceptance-register-and-manual",
                "title": "Update V2.3 P0 acceptance register and application manual for P0-13 audit workflow",
                "files": [
                    "docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md",
                    "docs/07_guides/APPLICATION_MANUAL.md",
                ],
            },
        ],
    }

    sanitized_handoff = redact_secrets(handoff)
    rendered = json.dumps(sanitized_handoff, ensure_ascii=False, indent=2) + "\n"
    target_path.write_text(rendered, encoding="utf-8")
    return target_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-date", type=date.fromisoformat, required=True, help="決策日期 (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, help="指定輸出的 JSON 檔案路徑 (必須位於 TEMP 或 candidate Safe 目錄)")
    parser.add_argument("--live", action="store_true", help="啟用 live 探測模式 (必須同時傳入 --confirm-live-readonly)")
    parser.add_argument("--confirm-live-readonly", action="store_true", help="確認執行唯讀 bounded live 探測")
    parser.add_argument("--mops-quarterly-artifact", type=Path, help="唯讀載入已保存的 MOPS 季報 artifact JSON")
    parser.add_argument("--fubon-projection", type=Path, help="唯讀載入富邦 research projection JSON")
    args = parser.parse_args(argv)

    fubon_projection = (
        json.loads(args.fubon_projection.read_text(encoding="utf-8"))
        if args.fubon_projection is not None
        else None
    )
    mops_quarterly_artifact = (
        json.loads(args.mops_quarterly_artifact.read_text(encoding="utf-8"))
        if args.mops_quarterly_artifact is not None
        else None
    )

    payload = build_p0_source_evidence_audit(
        args.decision_date,
        fubon_projection=fubon_projection,
        mops_quarterly_artifact=mops_quarterly_artifact,
        live_mode=args.live,
        confirm_live_readonly=args.confirm_live_readonly,
        output_path=args.output,
    )

    export_p0_13_handoff_json(payload)

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        print(rendered, end="")
    except UnicodeEncodeError:
        sys.stdout.buffer.write(rendered.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
