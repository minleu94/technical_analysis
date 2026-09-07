from __future__ import annotations

from typing import Any, Mapping

from app_module.dtos.update_loop_dtos import enrich_status_mapping


_DATE_ALIGNED_SOURCES = {
    "market_index",
    "industry_index",
    "broker_branch",
    "technical_indicators",
}


def _canonical_date(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in {"nan", "nat", "none", "未知", "無"}:
        return None
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw[:10]


def compose_sqlite_status_read_model(
    statuses: Mapping[str, Mapping[str, Any]],
    *,
    is_overview: bool = False,
    apply_freshness: bool = False,
    include_contract: bool = False,
) -> dict[str, dict[str, Any]]:
    """以既有 SQLite status payload 組裝唯讀回傳模型。"""
    result = {source: dict(payload) for source, payload in statuses.items()}
    if is_overview:
        for payload in result.values():
            payload["is_overview"] = True
    if apply_freshness:
        reference_date = _canonical_date(
            result.get("daily_data", {}).get("latest_date")
            if isinstance(result.get("daily_data"), Mapping)
            else None
        )
        if reference_date:
            daily_payload = result.get("daily_data")
            if isinstance(daily_payload, dict):
                daily_payload["freshness_status"] = "reference"
                daily_payload["freshness_reference_date"] = reference_date
            for source in _DATE_ALIGNED_SOURCES:
                source_payload = result.get(source)
                if not isinstance(source_payload, dict):
                    continue
                raw_status = str(source_payload.get("status", "")).strip().lower()
                latest_date = _canonical_date(source_payload.get("latest_date"))
                if raw_status.startswith(("error", "failed", "failure", "exception")):
                    source_payload["freshness_status"] = "error"
                    continue
                if latest_date is None:
                    source_payload["freshness_status"] = "unknown"
                    continue
                source_payload["freshness_reference_date"] = reference_date
                if latest_date < reference_date:
                    source_payload["freshness_status"] = "lagging"
                    source_payload["status"] = "lagging"
                else:
                    source_payload["freshness_status"] = "current"
    if include_contract:
        return enrich_status_mapping(result)
    return result
