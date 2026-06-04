"""Build source metadata for Portfolio trades created from research artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping

from app_module.dtos import RecommendationDTO, RecommendationResultDTO


@dataclass(frozen=True)
class PortfolioTradeSource:
    """Traceable source metadata attached to append-only Portfolio trades."""

    source_type: str
    source_id: str
    source_snapshot_hash: str
    source_summary: Dict[str, Any]


def stable_snapshot_hash(payload: Mapping[str, Any]) -> str:
    """Return a deterministic hash for JSON-compatible metadata."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _split_reasons(raw: Any) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    for separator in ["；", ";", "、", "\n"]:
        text = text.replace(separator, "|")
    return [part.strip() for part in text.split("|") if part.strip()]


def build_recommendation_trade_source(
    result: RecommendationResultDTO,
    recommendation: RecommendationDTO,
) -> PortfolioTradeSource:
    """Create trace metadata for a trade recorded from a Recommendation row."""

    config = dict(result.config or {})
    regime_snapshot = dict(config.get("regime_snapshot") or {})
    summary: Dict[str, Any] = {
        "result_id": result.result_id,
        "result_name": result.result_name,
        "created_at": result.created_at,
        "stock_code": recommendation.stock_code,
        "stock_name": recommendation.stock_name,
        "close_price": recommendation.close_price,
        "price_change": recommendation.price_change,
        "profile_id": config.get("profile_id") or config.get("selected_profile") or "",
        "profile_version": config.get("profile_version") or "",
        "regime": result.regime or regime_snapshot.get("regime") or config.get("regime") or "",
        "total_score": recommendation.total_score,
        "indicator_score": recommendation.indicator_score,
        "pattern_score": recommendation.pattern_score,
        "volume_score": recommendation.volume_score,
        "recommendation_reasons": recommendation.recommendation_reasons,
        "reasons": _split_reasons(recommendation.recommendation_reasons),
        "industry": recommendation.industry,
        "regime_match": recommendation.regime_match,
    }
    return PortfolioTradeSource(
        source_type="recommendation_result",
        source_id=result.result_id,
        source_snapshot_hash=stable_snapshot_hash(summary),
        source_summary=summary,
    )


def _row_value(row: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return default


def build_backtest_trade_source(
    run_id: str,
    run_name: str,
    strategy_id: str,
    validation_status: str,
    trade_row: Mapping[str, Any],
) -> PortfolioTradeSource:
    """Create trace metadata for a trade recorded from a Backtest trade row."""

    summary: Dict[str, Any] = {
        "run_id": run_id,
        "run_name": run_name,
        "strategy_id": strategy_id,
        "validation_status": validation_status,
        "stock_code": str(_row_value(trade_row, "股票代號", "證券代號", "stock_code")),
        "stock_name": str(_row_value(trade_row, "股票名稱", "證券名稱", "stock_name")),
        "side": str(_row_value(trade_row, "買賣", "side")),
        "trade_date": str(_row_value(trade_row, "交易日期", "日期", "date", "trade_date")),
        "price": _row_value(trade_row, "價格", "單價", "成交價", "price"),
        "quantity": _row_value(
            trade_row,
            "數量",
            "交易股數",
            "股數",
            "quantity",
            "amount",
            default="",
        ),
    }
    return PortfolioTradeSource(
        source_type="backtest_run",
        source_id=run_id,
        source_snapshot_hash=stable_snapshot_hash(summary),
        source_summary=summary,
    )
