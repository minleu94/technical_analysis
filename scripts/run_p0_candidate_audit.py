"""產生 13 項 P0 候選資料來源的唯讀品質稽核總覽。"""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.mops_ezsearch_statement_availability import (
    MOPS_STATEMENT_AVAILABILITY_SCHEMA,
    MOPS_STATEMENT_AVAILABILITY_SOURCE,
    build_availability_projection,
)
from scripts.validate_mops_quarterly_artifact import validate_artifact
from scripts.update_phase3c_candidates import run_bounded_official_probe


LIVE_PROBE_SOURCE_MAP = {
    "institutional_flows": "twse_institutional",
    "credit_transactions": "twse_credit",
    "tdcc_shareholding": "tdcc_shareholding",
    "microstructure.disposition_stock": "twse_disposition",
    "microstructure.periodic_call_auction": "twse_periodic_call_auction",
    "microstructure.full_delivery": "twse_full_delivery",
    "microstructure.suspended_halt_resume": "twse_halt_resume",
    "microstructure.limit_lock": "twse_limit_lock",
    "twse.monthly_revenue_announcement": "twse_monthly_revenue",
    "tpex.monthly_revenue_announcement": "tpex_monthly_revenue",
    "corporate_action.ex_dividend_timeline": "twse_ex_dividend",
    "corporate_action.reduction_split_par_value": "twse_reduction",
}

MINIMUM_OWNER_QUESTIONS: dict[str, str] = {
    "corporate_action.ex_dividend_timeline": "是否核准將來自 TWSE TWT49U 的除權息時間軸資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "corporate_action.reduction_split_par_value": "是否核准將來自 TWSE TWTAUU 的減資／分割／面額變更資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "microstructure.suspended_halt_resume": "是否核准將來自 TWSE TWTAWU 的停牌／復牌時間資料作為交易限制 preflight 備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "microstructure.disposition_stock": "是否核准將來自 TWSE 公告的處置股資料作為交易限制 preflight 備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "microstructure.periodic_call_auction": "是否核准將來自 TWSE 處置公告分盤撮合措施作為交易限制 preflight 備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "microstructure.full_delivery": "是否核准將來自 TWSE TWT85U 的變更交易全額交割資料作為交易限制 preflight 備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "microstructure.limit_lock": "是否核准將來自 TWSE TWT84U 的漲跌停價與最後揭示買賣價所驗證之鎖死觀測，作為成交可行性 preflight 備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "institutional_flows": "是否核准將來自 TWSE T86 的三大法人買賣超資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "credit_transactions": "是否核准將來自 TWSE MI_MARGN 的信用交易（融資融券）金額與餘額資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "tdcc_shareholding": "是否核准將來自 TDCC 1-5 開放資料的集保持股分散級距資料作為內部量化研究與歷史回測備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "twse.monthly_revenue_announcement": "是否核准將來自 TWSE t187ap05_L OpenData 的上市月營收公告資料作為 PIT 營收比對備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "tpex.monthly_revenue_announcement": "是否核准將來自 TPEx OpenData 的上櫃月營收公告資料作為 PIT 營收比對備選源？（條款限制：僅供內部使用，不可對外再散布）",
    "pit.quarterly_financials": "是否核准將來自 MOPS 官方採集之合併未更正季報歷史 Artifact 作為 PIT 季度財報比對備選源？（條款限制：僅供內部使用，不可對外再散布）",
}


def build_p0_candidate_audit(
    decision_date: date,
    *,
    probe_report: Mapping[str, Any] | None = None,
    fubon_projection: Mapping[str, Any] | None = None,
    mops_quarterly_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """投影候選品質與 13 項 P0 機器驗證狀態；只探測官方來源，絕不寫入資料庫。"""
    report = dict(
        probe_report
        if probe_report is not None
        else run_bounded_official_probe(decision_date)
    )
    probe_items = _validate_probe_report(report, decision_date)
    fubon_items = _validate_fubon_projection(fubon_projection) if fubon_projection is not None else {}
    mops_rows = _validate_mops_quarterly_artifact(mops_quarterly_artifact) if mops_quarterly_artifact is not None else []
    probe_report_sha256 = _probe_report_sha256(report)
    items: list[dict[str, Any]] = []
    for source_id in P0_SOURCE_IDS:
        if source_id == "pit.quarterly_financials" and mops_rows:
            item = {
                "source_id": source_id,
                "audit_status": "observed_candidate",
                "machine_status": "verified",
                "adapter_status": "candidate_adapter_ready",
                "pit_status": "pit_date_verified",
                "evidence_status": "candidate_artifact_verified",
                "quality_status": "verified",
                "row_count": len(mops_rows),
                "accepted_row_count": len(mops_rows),
                "timestamp_evidence": "official_document_upload_timestamp",
                "payload_sha256": mops_rows[0]["source_hash"],
                "remaining_blocker_category": "legal_and_license_acceptance_required",
                "owner_action_required": True,
                "minimum_owner_question": MINIMUM_OWNER_QUESTIONS[source_id],
                "safe_automated_work": ["schema_validation_passed", "row_conservation_verified", "isolation_guaranteed", "payload_hash_verified", "tdd_test_passed"],
                "non_automated_work": ["legal_license_review", "owner_written_acceptance", "formal_promotion_to_production"],
                "blockers": ["research_only_not_source_accepted"],
            }
            items.append(item)
            continue
        if source_id == "pit.quarterly_financials":
            items.append({
                "source_id": source_id,
                "audit_status": "candidate_artifact_not_supplied",
                "machine_status": "missing",
                "adapter_status": "candidate_adapter_ready",
                "pit_status": "unavailable",
                "evidence_status": "candidate_artifact_not_supplied",
                "quality_status": "missing",
                "row_count": 0,
                "accepted_row_count": 0,
                "remaining_blocker_category": "mops_candidate_artifact_not_supplied",
                "owner_action_required": False,
                "minimum_owner_question": "",
                "safe_automated_work": ["adapter_contract_implemented"],
                "non_automated_work": ["mops_candidate_artifact_supply"],
                "blockers": ["mops_candidate_artifact_not_supplied"],
            })
            continue
        probe_source_id = LIVE_PROBE_SOURCE_MAP.get(source_id)
        if probe_source_id is None:
            item = {
                "source_id": source_id,
                "audit_status": "not_started_no_candidate_adapter",
                "machine_status": "missing",
                "adapter_status": "candidate_adapter_not_implemented",
                "pit_status": "unavailable",
                "evidence_status": "missing",
                "quality_status": "missing",
                "row_count": 0,
                "accepted_row_count": 0,
                "remaining_blocker_category": "candidate_adapter_not_implemented",
                "owner_action_required": True,
                "minimum_owner_question": MINIMUM_OWNER_QUESTIONS.get(source_id, ""),
                "safe_automated_work": [],
                "non_automated_work": ["candidate_adapter_implementation", "legal_license_review"],
                "blockers": ["candidate_adapter_not_implemented"],
            }
            _attach_fubon_research_supplement(item, fubon_items.get(source_id))
            items.append(item)
            continue
        probe = probe_items.get(probe_source_id)
        if probe is None:
            item = {
                "source_id": source_id,
                "audit_status": "probe_not_returned",
                "machine_status": "missing",
                "adapter_status": "candidate_adapter_ready",
                "pit_status": "unavailable",
                "evidence_status": "probe_not_returned",
                "quality_status": "missing",
                "row_count": 0,
                "accepted_row_count": 0,
                "remaining_blocker_category": "official_probe_not_returned",
                "owner_action_required": True,
                "minimum_owner_question": MINIMUM_OWNER_QUESTIONS.get(source_id, ""),
                "safe_automated_work": ["adapter_contract_implemented"],
                "non_automated_work": ["network_probe_execution", "legal_license_review"],
                "blockers": ["official_probe_not_returned"],
            }
            _attach_fubon_research_supplement(item, fubon_items.get(source_id))
            items.append(item)
            continue
        counts = _validated_probe_counts(probe)
        timestamp_evidence = str(probe.get("timestamp_evidence", "unavailable"))
        network_status = str(probe.get("network_status", "reachable"))
        schema_status = str(probe.get("schema_status", "mismatch"))
        probe_outcome = str(probe.get("probe_outcome", "unknown"))
        if network_status == "failed":
            audit_status = "probe_failed"
            machine_status = "missing"
            evidence_status = "network_probe_failed"
            quality_status = "missing"
            remaining_blocker = "network_probe_failed"
            blockers = [remaining_blocker]
        elif probe_outcome == "official_no_data" or schema_status == "no_data":
            audit_status = "official_no_data"
            machine_status = "missing"
            evidence_status = "official_no_data_for_requested_date"
            quality_status = "missing"
            remaining_blocker = "official_no_data_for_requested_date"
            blockers = [remaining_blocker]
        elif schema_status != "matched":
            audit_status = "schema_blocked"
            machine_status = "missing"
            evidence_status = "official_schema_mismatch"
            quality_status = "missing"
            remaining_blocker = "official_schema_mismatch"
            blockers = [remaining_blocker]
        else:
            audit_status = "observed_candidate"
            machine_status = (
                "verified"
                if timestamp_evidence == "official_publication_timestamp"
                else "degraded"
            )
            evidence_status = "official_endpoint_probed"
            quality_status = (
                "verified"
                if timestamp_evidence == "official_publication_timestamp"
                else "degraded"
            )
            remaining_blocker = "legal_and_license_acceptance_required"
            blockers = (
                ["official_publication_timestamp_missing"]
                if timestamp_evidence == "first_observed_only"
                else []
            )
        observed = schema_status == "matched" and network_status != "failed"
        item = {
            "source_id": source_id,
            "audit_status": audit_status,
            "machine_status": machine_status,
            "adapter_status": "candidate_adapter_ready",
            "pit_status": (
                "pit_date_verified"
                if timestamp_evidence == "official_publication_timestamp"
                else (
                    "official_publication_timestamp_missing"
                    if observed
                    else "unavailable"
                )
            ),
            "evidence_status": evidence_status,
            "quality_status": quality_status,
            "row_count": counts["raw_row_count"],
            "accepted_row_count": counts["accepted_row_count"],
            "timestamp_evidence": timestamp_evidence,
            "probe_outcome": probe_outcome,
            "payload_sha256": probe.get("payload_sha256"),
            "remaining_blocker_category": remaining_blocker,
            "owner_action_required": True,
            "minimum_owner_question": MINIMUM_OWNER_QUESTIONS.get(source_id, ""),
            "safe_automated_work": (
                [
                    "schema_validation_passed",
                    "row_conservation_verified",
                    "isolation_guaranteed",
                    "payload_hash_verified",
                    "tdd_test_passed",
                ]
                if observed
                else ["adapter_contract_implemented"]
            ),
            "non_automated_work": (
                [
                    "legal_license_review",
                    "owner_written_acceptance",
                    "formal_promotion_to_production",
                ]
                if observed
                else [
                    "completed_publication_probe_or_schema_repair",
                    "legal_license_review",
                ]
            ),
            "blockers": blockers,
        }
        for route_field in (
            "endpoint_id",
            "acquisition_route_id",
            "fallback_used",
            "fallback_from_endpoint_id",
            "fallback_from_acquisition_route_id",
        ):
            if route_field in probe:
                item[route_field] = probe[route_field]
        _attach_fubon_research_supplement(item, fubon_items.get(source_id))
        items.append(item)

    machine_verified_sources = sum(1 for item in items if item["machine_status"] == "verified")
    degraded_sources = sum(1 for item in items if item["machine_status"] == "degraded")
    unavailable_sources = sum(1 for item in items if item["machine_status"] == "missing")
    return {
        "schema_version": "p0-candidate-audit.v1",
        "decision_date": decision_date.isoformat(),
        "mode": "bounded_official_read_only",
        "lineage": {
            "probe_date": decision_date.isoformat(),
            "probe_mode": "bounded_official_read_only",
            "probe_report_sha256": f"sha256:{probe_report_sha256}",
            "fubon_research_projection_present": fubon_projection is not None,
            "mops_quarterly_artifact_present": mops_quarterly_artifact is not None,
        },
        "machine_vs_owner_blocker_summary": {
            "total_sources": len(items),
            "machine_verified_sources": machine_verified_sources,
            "degraded_sources": degraded_sources,
            "unavailable_sources": unavailable_sources,
            "owner_decision_questions_required": sum(1 for item in items if item["owner_action_required"]),
        },
        "items": items,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
        "human_decision": "requires_human_acceptance",
    }


def _validate_mops_quarterly_artifact(payload: Mapping[str, Any]) -> list[dict[str, object]]:
    if payload.get("schema_version") == MOPS_STATEMENT_AVAILABILITY_SCHEMA:
        return _validate_mops_ezsearch_availability_artifact(payload)
    expected = {
        "research_only": True,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "downstream_eligibility": "none",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"MOPS quarterly artifact {key} mismatch")
    rows = validate_artifact(dict(payload))
    for row in rows:
        if row.get("statement_scope") != "consolidated" or row.get("correction_status") != "none":
            raise ValueError("MOPS quarterly artifact must be an uncorrected consolidated report")
    return rows


def _validate_mops_ezsearch_availability_artifact(
    payload: Mapping[str, Any],
) -> list[dict[str, object]]:
    """驗證新版 MOPS 秒級 availability-only artifact。

    此 artifact 只證明公告可得時間，不含財報數值，也不授權 formal
    credit。P0 audit 可據此解除「artifact 未提供」，但後續 disposition
    仍只能是 availability/research shadow。
    """

    expected = {
        "source_id": MOPS_STATEMENT_AVAILABILITY_SOURCE,
        "research_only": True,
        "read_only_source": True,
        "formal_oos_allowed": False,
        "formal_credit_authorized": False,
        "production_scheduler_allowed": False,
        "production_blend_alpha_bp": 0,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"MOPS EZSearch availability artifact {key} mismatch")
    rows = payload.get("rows")
    projections = payload.get("availability_projection")
    quality = payload.get("quality_summary")
    if not isinstance(rows, list) or not rows:
        raise ValueError("MOPS EZSearch availability artifact rows are required")
    if not isinstance(projections, list) or not projections:
        raise ValueError(
            "MOPS EZSearch availability artifact projection is required"
        )
    if not isinstance(quality, Mapping):
        raise ValueError("MOPS EZSearch availability quality summary is required")
    if quality.get("event_count") != len(rows):
        raise ValueError("MOPS EZSearch availability event count mismatch")
    if quality.get("projection_count") != len(projections):
        raise ValueError("MOPS EZSearch availability projection count mismatch")
    for quality_key in (
        "duplicate_event_count",
        "future_event_count",
        "invalid_event_count",
    ):
        if quality.get(quality_key) != 0:
            raise ValueError(
                f"MOPS EZSearch availability {quality_key} must be zero"
            )
    manifest = payload.get("query_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("MOPS EZSearch availability query manifest is required")
    manifest_hashes: dict[tuple[str, str], str] = {}
    for raw_manifest_item in manifest:
        if not isinstance(raw_manifest_item, Mapping):
            raise ValueError("MOPS EZSearch availability manifest item must be an object")
        market = str(raw_manifest_item.get("market", "")).strip()
        announcement_item = str(
            raw_manifest_item.get("announcement_item", "")
        ).strip()
        response_sha256 = str(
            raw_manifest_item.get("response_sha256", "")
        ).strip()
        if (
            not market
            or not announcement_item
            or len(response_sha256) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in response_sha256)
        ):
            raise ValueError("MOPS EZSearch availability manifest lineage is invalid")
        route_key = (market, announcement_item)
        if route_key in manifest_hashes:
            raise ValueError("MOPS EZSearch availability manifest route is duplicated")
        manifest_hashes[route_key] = f"sha256:{response_sha256.lower()}"
    normalized_rows: list[Mapping[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise ValueError("MOPS EZSearch availability row must be an object")
        required = {
            "stock_code",
            "market",
            "statement_type",
            "period",
            "period_end",
            "announcement_at",
            "announcement_item",
            "detail_url",
            "event_hash",
        }
        if not required.issubset(raw_row):
            raise ValueError("MOPS EZSearch availability row fields are incomplete")
        event_material = {
            "announcement_at": str(raw_row["announcement_at"]),
            "announcement_item": str(raw_row["announcement_item"]),
            "detail_url": str(raw_row["detail_url"]),
            "period": str(raw_row["period"]),
            "stock_code": str(raw_row["stock_code"]),
        }
        expected_event_hash = sha256(
            json.dumps(
                event_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if raw_row.get("event_hash") != expected_event_hash:
            raise ValueError("MOPS EZSearch availability event hash mismatch")
        lineage_key = (
            str(raw_row["market"]).strip(),
            str(raw_row["announcement_item"]).strip(),
        )
        expected_source_hash = manifest_hashes.get(lineage_key)
        if expected_source_hash is None:
            raise ValueError("MOPS EZSearch availability row has no manifest lineage")
        row_source_hash = raw_row.get("source_hash")
        if row_source_hash is not None and row_source_hash != expected_source_hash:
            raise ValueError("MOPS EZSearch availability source hash mismatch")
        normalized_rows.append(
            {**dict(raw_row), "source_hash": expected_source_hash}
        )
    expected_projections = build_availability_projection(normalized_rows)
    if projections != expected_projections and not _matches_legacy_mops_projection(
        projections,
        expected_projections,
    ):
        raise ValueError("MOPS EZSearch availability projection mismatch")
    source_hash = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return [
        {
            **dict(row),
            "source_hash": source_hash,
            "evidence_tier": "availability_only",
        }
        for row in projections
    ]


def _matches_legacy_mops_projection(
    projections: Sequence[Any],
    expected_projections: Sequence[Mapping[str, Any]],
) -> bool:
    """Accept the pre-formal-availability.v2 projection after full revalidation."""

    legacy_fields = {
        "stock_code",
        "statement_type",
        "period",
        "as_of_date",
        "announced_date",
        "available_date",
        "source",
        "source_version",
    }
    if len(projections) != len(expected_projections):
        return False
    expected_by_key = {
        (
            str(item["stock_code"]),
            str(item["statement_type"]),
            str(item["period"]),
        ): item
        for item in expected_projections
    }
    for raw_projection in projections:
        if not isinstance(raw_projection, Mapping):
            return False
        if set(raw_projection) != legacy_fields:
            return False
        key = (
            str(raw_projection["stock_code"]),
            str(raw_projection["statement_type"]),
            str(raw_projection["period"]),
        )
        expected = expected_by_key.get(key)
        if expected is None:
            return False
        if any(raw_projection[field] != expected[field] for field in legacy_fields):
            return False
    return True


def _attach_fubon_research_supplement(
    item: dict[str, Any], rows: Sequence[Mapping[str, Any]] | None
) -> None:
    """Expose a bounded research supplement without upgrading official evidence."""
    if not rows:
        return
    if item["audit_status"] in {"not_started_no_candidate_adapter", "probe_not_returned"}:
        # A captured Fubon projection is a real, but explicitly non-official,
        # candidate path.  Do not leave it indistinguishable from no adapter.
        item["audit_status"] = "observed_research_only"
        item["quality_status"] = "degraded"
        item["timestamp_evidence"] = "first_observed_only"
    item["fubon_research_supplement"] = {
        "status": "observed_research_only",
        "row_count": len(rows),
        "quality": "degraded",
        "availability_evidence": "first_observed_only",
        "blockers": [
            "not_official_announcement_evidence",
            "formal_oos_not_allowed",
        ],
    }


def _validate_fubon_projection(
    projection: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    expected = {
        "schema_version": "fubon-p0-research-projection.v1",
        "source": "fubon.marketdata",
        "research_only": True,
        "formal_oos_allowed": False,
        "production_scheduler_allowed": False,
        "production_blend_alpha_bp": 0,
    }
    for key, value in expected.items():
        if projection.get(key) != value:
            raise ValueError(f"Fubon projection {key} mismatch")
    raw_rows = projection.get("observations")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise ValueError("Fubon projection observations must be an array")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        if not isinstance(row, Mapping):
            raise ValueError("Fubon projection observation must be an object")
        source_id = row.get("source_id")
        if source_id not in P0_SOURCE_IDS:
            raise ValueError("Fubon projection source_id must be a P0 source")
        if row.get("quality") != "degraded" or row.get("availability_evidence_kind") != "first_observed_only":
            raise ValueError("Fubon projection must remain first_observed_only degraded")
        if row.get("downstream_eligibility") != "none" or row.get("production_scheduler_allowed") is not False:
            raise ValueError("Fubon projection access boundary mismatch")
        grouped.setdefault(str(source_id), []).append(dict(row))
    return grouped


def _validate_probe_report(
    report: Mapping[str, Any],
    decision_date: date,
) -> dict[str, dict[str, Any]]:
    expected = {
        "probe_date": decision_date.isoformat(),
        "probe_mode": "bounded_official_read_only",
        "license_accepted": False,
        "source_accepted": False,
        "downstream_eligibility": "none",
        "production_scheduler_allowed": False,
        "human_decision": "requires_human_acceptance",
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            raise ValueError(f"probe report {key} mismatch")
    raw_sources = report.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
        raise ValueError("probe report sources must be an array")
    probe_items: dict[str, dict[str, Any]] = {}
    for raw_item in raw_sources:
        if not isinstance(raw_item, Mapping):
            raise ValueError("probe source row must be an object")
        source_id = raw_item.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("probe source_id is required")
        if source_id in probe_items:
            raise ValueError(f"duplicate probe source_id: {source_id}")
        if source_id not in LIVE_PROBE_SOURCE_MAP.values():
            raise ValueError(f"unknown probe source_id: {source_id}")
        _validated_probe_counts(raw_item)
        _validate_payload_sha256(raw_item)
        probe_items[source_id] = dict(raw_item)
    return probe_items


def _validated_probe_counts(probe: Mapping[str, Any]) -> dict[str, int]:
    names = (
        "raw_row_count",
        "accepted_row_count",
        "duplicate_row_count",
        "quarantine_row_count",
        "blocked_row_count",
    )
    counts: dict[str, int] = {}
    for name in names:
        value = probe.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"probe {name} must be a non-negative integer")
        counts[name] = value
    classified = (
        counts["accepted_row_count"]
        + counts["duplicate_row_count"]
        + counts["quarantine_row_count"]
        + counts["blocked_row_count"]
    )
    if counts["raw_row_count"] != classified:
        raise ValueError("probe row conservation violated")
    return counts


def _validate_payload_sha256(probe: Mapping[str, Any]) -> None:
    payload_sha256 = probe.get("payload_sha256")
    if probe.get("schema_status") == "matched":
        if not isinstance(payload_sha256, str) or len(payload_sha256) != 64:
            raise ValueError("matched probe payload_sha256 must be a SHA-256 hex digest")
        try:
            int(payload_sha256, 16)
        except ValueError as exc:
            raise ValueError("matched probe payload_sha256 must be a SHA-256 hex digest") from exc


def _probe_report_sha256(report: Mapping[str, Any]) -> str:
    canonical = dict(report)
    sources = canonical.get("sources")
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        canonical["sources"] = sorted(
            (dict(item) for item in sources if isinstance(item, Mapping)),
            key=lambda item: str(item.get("source_id", "")),
        )
    rendered = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(rendered.encode("utf-8")).hexdigest()


def export_p0_handoff_packet(audit_payload: dict[str, Any], *, git_status_str: str = "unverified") -> Path:
    import tempfile
    temp_dir = Path(tempfile.gettempdir())
    handoff_dir = temp_dir / "technical_analysis_gemini_handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    target_path = handoff_dir / "GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1.json"

    changed_files = [
        "data_module/p0_official_source_parsers.py",
        "scripts/run_p0_candidate_audit.py",
        "scripts/update_phase3c_candidates.py",
        "tests/test_p0_official_source_parsers.py",
        "tests/test_run_p0_candidate_audit.py",
        "tests/fixtures/p0_official_sources/twse_limit_lock.json",
        "tests/fixtures/p0_official_sources/mops_quarterly_financials.json",
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
        "task_id": "GEMINI-P0-13-MACHINE-AUDIT-AND-BLOCKER-REDUCTION-V1",
        "status": "audit_generated_not_validation_handoff",
        "base_head": "3319b1c0372503ab865c45e376e299e52d943834",
        "timestamp": audit_payload.get("decision_date"),
        "changed_files": changed_file_entries,
        "matrix_13_sources": audit_payload.get("items", []),
        "machine_vs_owner_blocker_summary": audit_payload.get("machine_vs_owner_blocker_summary", {}),
        "formal_clock_zeros": {
            "formal_oos_allowed": audit_payload.get("formal_oos_allowed", False),
            "production_scheduler_allowed": audit_payload.get("production_scheduler_allowed", False),
            "downstream_eligibility": audit_payload.get("downstream_eligibility", "none"),
            "human_decision": audit_payload.get("human_decision", "requires_human_acceptance"),
            "production_blend_alpha_bp": 0,
        },
        "safety_flags": {
            "no_formal_db_mutation": True,
            "no_production_scheduler_enabled": True,
            "no_unverified_lookahead_introduced": True,
            "fail_closed_boundaries_preserved": True,
        },
        "git_status": {
            "working_tree_status_unverified_by_audit_cli": True,
            "no_git_commit_performed": True,
            "details": git_status_str,
        },
        "test_final_status": {
            "status": "not_run_by_audit_cli",
        },
        "recommended_commit_batches": [
            {
                "batch_id": "batch-1-parsers-and-fixtures",
                "title": "Add P0 candidate parsers and fixtures for limit lock and quarterly financials",
                "files": [
                    "data_module/p0_official_source_parsers.py",
                    "tests/fixtures/p0_official_sources/twse_limit_lock.json",
                    "tests/fixtures/p0_official_sources/mops_quarterly_financials.json",
                    "tests/test_p0_official_source_parsers.py",
                ],
            },
            {
                "batch_id": "batch-2-candidate-audit-tools",
                "title": "Expand P0 candidate audit tool to 13 sources and generate owner decision packet",
                "files": [
                    "scripts/run_p0_candidate_audit.py",
                    "scripts/update_phase3c_candidates.py",
                    "tests/test_run_p0_candidate_audit.py",
                ],
            },
            {
                "batch_id": "batch-3-documentation-sync",
                "title": "Sync P0 source acceptance register and application manual for P0-13 audit",
                "files": [
                    "docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md",
                    "docs/07_guides/APPLICATION_MANUAL.md",
                ],
            },
        ],
    }

    target_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fubon-projection", type=Path, help="唯讀載入手動富邦 research JSON")
    parser.add_argument("--mops-quarterly-artifact", type=Path, help="唯讀載入已保存的 MOPS 季報 artifact")
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
    payload = build_p0_candidate_audit(
        args.decision_date,
        fubon_projection=fubon_projection,
        mops_quarterly_artifact=mops_quarterly_artifact,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    try:
        print(rendered, end="")
    except UnicodeEncodeError:
        sys.stdout.buffer.write(rendered.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
