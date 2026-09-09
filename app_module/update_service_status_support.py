from __future__ import annotations

from typing import Any, Mapping

from app_module.dtos.update_loop_dtos import enrich_status_mapping


_DATE_ALIGNED_SOURCES = {
    "market_index",
    "industry_index",
    "broker_branch",
    "technical_indicators",
}

_FRESHNESS_SOURCE_TO_STATUS = {
    "twse.daily_prices.raw": "daily_data",
    "tpex.daily_prices.raw": "daily_data",
    "sqlite.daily_prices": "daily_data",
    "sqlite.market_indices": "market_index",
    "sqlite.industry_indices": "industry_index",
    "sqlite.broker_flows": "broker_branch",
    "sqlite.technical_indicators": "technical_indicators",
    "fundamental.monthly_revenues": "monthly_revenue",
    "fundamental.quarterly_statements": "quarterly_statements",
}

_FRESHNESS_SEVERITY = {
    "current": 0,
    "not_applicable": 0,
    "expected_wait": 1,
    "partial": 2,
    "stale": 2,
    "failed": 3,
    "unknown": 3,
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


def apply_freshness_receipt(
    statuses: Mapping[str, Mapping[str, Any]],
    receipt: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Project the read-only scheduled freshness receipt into update status DTO input.

    The probe remains the owner of source reconciliation.  This projection only
    copies its explicit state/reason/coverage into the existing update-page
    mapping; it never infers freshness from a newer ``MAX(date)``.
    """

    result = {source: dict(payload) for source, payload in statuses.items()}
    if not isinstance(receipt, Mapping):
        return result

    receipt_status = str(receipt.get("status", "unknown")).strip().lower()
    checked_at = receipt.get("checked_at")
    source_items = receipt.get("source_statuses")
    if not isinstance(source_items, list):
        source_items = []
    for payload in result.values():
        payload["freshness_probe_status"] = receipt_status
        payload["freshness_probe_checked_at"] = checked_at
        if receipt_status == "failed":
            payload.setdefault("freshness_probe_errors", list(receipt.get("errors", [])))

    selected: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for item in source_items:
        if not isinstance(item, Mapping):
            continue
        status_key = _FRESHNESS_SOURCE_TO_STATUS.get(str(item.get("source_id", "")))
        if status_key is None or status_key not in result:
            continue
        freshness_status = str(item.get("freshness_status", "unknown")).strip().lower()
        severity = _FRESHNESS_SEVERITY.get(freshness_status, 3)
        previous = selected.get(status_key)
        if previous is None or severity > previous[0]:
            selected[status_key] = (severity, item)

    for status_key, (_severity, item) in selected.items():
        payload = result[status_key]
        freshness_status = str(item.get("freshness_status", "unknown")).strip().lower()
        payload["freshness_status"] = freshness_status
        payload["freshness_reason"] = item.get("reason")
        payload["freshness_expected_period"] = item.get("expected_period")
        payload["freshness_actual_period"] = item.get("actual_period")
        payload["freshness_available_at"] = item.get("available_at")
        payload["freshness_coverage"] = dict(item.get("coverage", {})) if isinstance(item.get("coverage"), Mapping) else item.get("coverage")
        payload["freshness_missing_periods"] = list(item.get("missing_periods", []))
        # Keep the legacy status vocabulary usable by existing widgets/DTOs,
        # while exposing the precise status above for new consumers.
        if freshness_status in {"failed", "unknown"}:
            payload["status"] = "error"
        elif freshness_status in {"stale", "partial", "expected_wait"}:
            payload["status"] = "lagging"
    return result


def compose_sqlite_status_read_model(
    statuses: Mapping[str, Mapping[str, Any]],
    *,
    is_overview: bool = False,
    apply_freshness: bool = False,
    include_contract: bool = False,
    freshness_receipt: Mapping[str, Any] | None = None,
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
    if freshness_receipt is not None:
        result = apply_freshness_receipt(result, freshness_receipt)
    if include_contract:
        return enrich_status_mapping(result)
    return result
