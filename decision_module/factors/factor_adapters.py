"""既有技術、量能與券商分點資料的 Factor v1 adapter。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from decision_module.factors.factor_dtos import FactorQuality, FactorRecord, MissingPolicy


def _score_to_bp(score: Decimal) -> int:
    score_bp = (score * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
    return max(0, min(10000, int(score_bp)))


def _volume_ratio_to_score_bp(ratio: Decimal) -> int:
    score_bp = (ratio * Decimal("5000")).to_integral_value(rounding=ROUND_HALF_UP)
    return max(0, min(10000, int(score_bp)))


def build_technical_total_score_factor(
    *,
    stock_code: str,
    as_of_date: date,
    available_date: date,
    total_score: Decimal,
) -> FactorRecord:
    return FactorRecord(
        factor_name="technical.total_score",
        stock_code=stock_code,
        as_of_date=as_of_date,
        available_date=available_date,
        value=total_score,
        score_bp=_score_to_bp(total_score),
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
    )


def build_volume_ratio_factor(
    *,
    stock_code: str,
    as_of_date: date,
    available_date: date,
    volume_ratio: Decimal | None,
) -> FactorRecord:
    if volume_ratio is None:
        quality = FactorQuality.MISSING
        score_bp = None
    else:
        quality = FactorQuality.OBSERVED
        score_bp = _volume_ratio_to_score_bp(volume_ratio)

    return FactorRecord(
        factor_name="volume.volume_ratio",
        stock_code=stock_code,
        as_of_date=as_of_date,
        available_date=available_date,
        value=volume_ratio,
        score_bp=score_bp,
        quality=quality,
        missing_policy=MissingPolicy.NEUTRAL,
        source_version="volume-v1",
    )


def broker_flow_quality_to_factor_quality(quality: str) -> FactorQuality:
    if quality == "observed":
        return FactorQuality.OBSERVED
    if quality == "estimated":
        return FactorQuality.ESTIMATED
    return FactorQuality.MISSING


def build_broker_flow_factor(
    *,
    stock_code: str,
    as_of_date: date,
    available_date: date,
    net_lots: int | None,
    quality: str,
    rank: int | None,
) -> FactorRecord:
    factor_quality = broker_flow_quality_to_factor_quality(quality)
    value = net_lots if factor_quality != FactorQuality.MISSING else None

    return FactorRecord(
        factor_name="broker_flow.net_lots",
        stock_code=stock_code,
        as_of_date=as_of_date,
        available_date=available_date,
        value=value,
        score_bp=None,
        quality=factor_quality,
        missing_policy=MissingPolicy.SKIP,
        source_version="broker-flow-v1",
        metadata={"rank": rank, "source_quality": quality},
    )
