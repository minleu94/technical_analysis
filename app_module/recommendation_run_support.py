"""RecommendationService 的純 payload 組裝與序列化支援。"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence

from financial_module.units import to_decimal


@dataclass(frozen=True)
class NegativeEvidenceBuffers:
    excluded_candidates: List[Dict[str, Any]]
    why_not_payload: List[Dict[str, Any]]
    liquidity_gate_payload: List[Dict[str, Any]]
    exclusion_quality: str
    exclusion_warnings: List[str]


def matrix_row(
    *,
    stock_code: str,
    stock_name: str = "",
    status: str,
    reason_codes: List[str],
    quality: str,
    stage: str,
    threshold_name: str = "",
    observed_value: Any = None,
    required_value: Any = None,
    total_score: Any = None,
    score_bp: Optional[int] = None,
    score_percentile_bp: Optional[int] = None,
    eligible_universe_size: Optional[int] = None,
    threshold_mode: str = "fixed",
    warnings: Optional[List[str]] = None,
    industry: str = "",
) -> Dict[str, Any]:
    return {
        "stock_code": str(stock_code),
        "stock_name": str(stock_name or stock_code),
        "status": status,
        "reason_codes": list(reason_codes),
        "quality": quality,
        "stage": stage,
        "threshold_name": threshold_name,
        "observed_value": "" if observed_value is None else str(observed_value),
        "required_value": "" if required_value is None else str(required_value),
        "total_score": "" if total_score is None else str(total_score),
        "score_bp": score_bp,
        "score_percentile_bp": score_percentile_bp,
        "eligible_universe_size": eligible_universe_size,
        "threshold_mode": threshold_mode,
        "warnings": list(warnings or []),
        "industry": industry,
    }


def build_negative_evidence_buffers(screening_matrix: Sequence[Mapping[str, Any]]) -> NegativeEvidenceBuffers:
    negative_rows = [
        dict(row)
        for row in screening_matrix
        if str(row.get("status")) in {"fail", "degraded", "skipped", "missing"}
    ]
    excluded_candidates = [
        {
            "stock_code": row["stock_code"],
            "stock_name": row.get("stock_name", ""),
            "status": row.get("status", ""),
            "reason_codes": list(row.get("reason_codes") or []),
            "quality": row.get("quality", "degraded"),
        }
        for row in negative_rows
    ]
    liquidity_gate_payload = [
        row
        for row in negative_rows
        if "liquidity" in " ".join(str(code) for code in row.get("reason_codes", [])).lower()
        or "liquidity" in str(row.get("threshold_name", "")).lower()
    ]
    return NegativeEvidenceBuffers(
        excluded_candidates=excluded_candidates,
        why_not_payload=negative_rows,
        liquidity_gate_payload=liquidity_gate_payload,
        exclusion_quality="observed",
        exclusion_warnings=["screening_matrix_persisted_v1"],
    )


def configured_volume_change_min_percent(config: Mapping[str, Any]) -> Decimal | None:
    filters = config.get("filters", {})
    key = ""
    if "min_volume_ratio" in filters:
        key = "min_volume_ratio"
    elif "volume_ratio_min" in filters:
        key = "volume_ratio_min"
    if not key:
        return None

    try:
        value = to_decimal(filters[key])
    except (InvalidOperation, ValueError, TypeError):
        return None
    if value.is_nan():
        return None

    if key == "min_volume_ratio" or Decimal("-50") <= value <= Decimal("10"):
        return (value - Decimal("1")) * Decimal("100")
    return value


def format_decimal_for_payload(value: Decimal) -> str:
    return format(value.normalize(), "f")


def validate_ranking_config(config: Mapping[str, Any]) -> tuple[Dict[str, Any], str]:
    ranking_config = config.get("recommendation_ranking", {})
    threshold_mode = ranking_config.get("threshold_mode", "fixed")

    if threshold_mode not in {"fixed", "quantile"}:
        raise ValueError("recommendation threshold_mode must be 'fixed' or 'quantile'")
    if threshold_mode == "fixed":
        return ranking_config, threshold_mode

    required_keys = {
        "recommendation_min_percentile_bp",
        "recommendation_min_universe_size",
        "recommendation_ranking_method",
    }
    missing_keys = sorted(required_keys - ranking_config.keys())
    if missing_keys:
        raise ValueError("missing recommendation ranking parameters: " + ", ".join(missing_keys))

    min_percentile_bp = ranking_config["recommendation_min_percentile_bp"]
    min_universe_size = ranking_config["recommendation_min_universe_size"]
    ranking_method = ranking_config["recommendation_ranking_method"]

    if type(min_percentile_bp) is not int or not 0 <= min_percentile_bp <= 10000:
        raise ValueError("recommendation_min_percentile_bp must be an integer between 0 and 10000")
    if type(min_universe_size) is not int or min_universe_size < 2:
        raise ValueError("recommendation_min_universe_size must be an integer of at least 2")
    if ranking_method != "nearest_rank":
        raise ValueError("recommendation_ranking_method must be 'nearest_rank'")

    return ranking_config, threshold_mode
