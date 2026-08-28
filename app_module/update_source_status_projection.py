"""UpdateView 與研究治理共用的唯讀來源狀態投影。

``UpdateService`` 的核心資料狀態與 P0 candidate audit 原本各自有一份
payload，導致畫面只看得到 SQLite/CSV 新鮮度，卻看不到實際 acquisition route、
fallback、PIT／公告時間與 owner 決議。本模組只做結構化合併與摘要，不會讀網路、
不會寫入正式資料庫，也不會把 P0 source 轉成正式可用來源。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from app_module.p0_source_control_center import P0SourceControlCenterDTO


UPDATE_SOURCE_STATUS_PROJECTION_SCHEMA = "update-source-status-projection.v1"


def compose_source_status_projection(
    statuses: Mapping[str, Any],
    *,
    p0_control_center: P0SourceControlCenterDTO | None = None,
    p0_load_error: str | None = None,
    p0_reference: str | None = None,
) -> dict[str, Any]:
    """組合核心資料狀態與 P0 唯讀治理狀態。

    核心來源維持原有頂層 key，避免破壞既有 UpdateView/呼叫端契約；新增的
    ``p0_source_control`` 則是完整、可供 UI 與診斷使用的治理投影。任何讀取
    artifact 的錯誤都以 ``audit_unavailable`` 保留在投影中，而不是假裝成
    ``contract_only`` 的正常完成。
    """

    result: dict[str, Any] = {}
    for source, payload in statuses.items():
        if isinstance(payload, Mapping):
            result[str(source)] = dict(payload)
        else:
            result[str(source)] = {
                "latest_date": None,
                "total_records": 0,
                "status": "invalid",
                "message": "來源狀態 payload 不是 object",
            }

    result["p0_source_control"] = compose_p0_source_control_projection(
        p0_control_center,
        load_error=p0_load_error,
        reference=p0_reference,
    )
    return result


def compose_p0_source_control_projection(
    control_center: P0SourceControlCenterDTO | None,
    *,
    load_error: str | None = None,
    reference: str | None = None,
) -> dict[str, Any]:
    """將 P0 control center DTO 轉成 UI/diagnostic 可序列化 payload。"""

    if control_center is None:
        return {
            "schema_version": UPDATE_SOURCE_STATUS_PROJECTION_SCHEMA,
            "status": "not_available",
            "source_count": 0,
            "rows": [],
            "summary": {},
            "boundary": {
                "read_only": True,
                "writes_allowed": False,
                "production_ingestion_allowed": False,
                "production_scheduler_allowed": False,
                "formal_oos_allowed": False,
                "auto_accept_allowed": False,
                "downstream_eligibility": "none",
            },
            "reference": reference,
            "load_error": load_error or "P0 control center 未建立",
        }

    if load_error:
        status = "audit_unavailable"
    elif control_center.contract_only_count == control_center.p0_source_count:
        status = "contract_only"
    elif control_center.blocked_count:
        status = "blocked_provenance"
    elif control_center.research_shadow_count:
        status = "research_shadow"
    else:
        status = "governance_review"

    rows = [row.to_dict() for row in control_center.rows]
    # 舊 artifact 尚未帶 ``fallback_attempted`` 時，已採用本身就是「曾嘗試」
    # 的證據；只在 summary 做此保守推導，不覆寫 row 原始欄位。
    fallback_attempted_count = sum(
        row.fallback_attempted is True or row.fallback_used is True
        for row in control_center.rows
    )
    fallback_used_count = sum(row.fallback_used is True for row in control_center.rows)
    fallback_rejected_count = sum(
        row.fallback_attempted is True and row.fallback_used is not True
        for row in control_center.rows
    )
    return {
        "schema_version": UPDATE_SOURCE_STATUS_PROJECTION_SCHEMA,
        "status": status,
        "source_count": control_center.p0_source_count,
        "rows": rows,
        "summary": {
            "governance_status_counts": dict(control_center.status_counts),
            "machine_status_counts": dict(control_center.machine_status_counts),
            "decision_status_counts": dict(control_center.decision_status_counts),
            "accepted_count": control_center.accepted_count,
            "limited_count": control_center.limited_count,
            "research_shadow_count": control_center.research_shadow_count,
            "blocked_count": control_center.blocked_count,
            "contract_only_count": control_center.contract_only_count,
            "downstream_eligible_count": control_center.downstream_eligible_count,
            "observed_rows": _sum_optional_int(row.observed_rows for row in control_center.rows),
            "accepted_rows": _sum_optional_int(row.accepted_rows for row in control_center.rows),
            "blocked_rows": _sum_optional_int(row.blocked_rows for row in control_center.rows),
            "fallback_attempted_count": fallback_attempted_count,
            "fallback_used_count": fallback_used_count,
            "fallback_rejected_count": fallback_rejected_count,
            "license_status_counts": dict(
                Counter(row.license_status for row in control_center.rows)
            ),
            "license_evidence_capture_status_counts": dict(
                Counter(
                    row.license_evidence_capture_status
                    for row in control_center.rows
                )
            ),
        },
        "boundary": {
            "read_only": control_center.read_only,
            "writes_allowed": control_center.writes_allowed,
            "production_ingestion_allowed": control_center.production_ingestion_allowed,
            "production_scheduler_allowed": control_center.production_scheduler_allowed,
            "formal_oos_allowed": control_center.formal_oos_allowed,
            "auto_accept_allowed": control_center.auto_accept_allowed,
            "downstream_eligibility": "none",
        },
        "reference": reference,
        "load_error": load_error,
    }


def _sum_optional_int(values: Any) -> int | None:
    materialized = tuple(value for value in values if value is not None)
    if not materialized:
        return None
    return sum(materialized)
