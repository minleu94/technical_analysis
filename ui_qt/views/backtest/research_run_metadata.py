"""Research Run metadata 的純組裝與序列化 helper。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from typing import Any
import uuid

import pandas as pd

from app_module.research_run_dtos import ResearchRunMetadataDTO, canonical_json


def factor_save_kwargs(details: dict[str, Any]) -> dict[str, Any]:
    factor_records = details.get("factor_records")
    factor_decision_date = details.get("factor_decision_date")
    if not factor_records or factor_decision_date is None:
        return {}
    return {
        "factor_records": list(factor_records),
        "factor_decision_date": factor_decision_date,
    }


def single_backtest_metrics(report: Any) -> dict[str, Any]:
    return {
        "total_return": getattr(report, "total_return", None),
        "annual_return": getattr(report, "annual_return", None),
        "sharpe_ratio": getattr(report, "sharpe_ratio", None),
        "max_drawdown": getattr(report, "max_drawdown", None),
        "win_rate": getattr(report, "win_rate", None),
        "total_trades": getattr(report, "total_trades", None),
        "expectancy": getattr(report, "expectancy", None),
    }


def next_research_run_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "value") and value.__class__.__name__.endswith("Status"):
        return value.value
    return value


def research_payload_hash(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(json_safe(payload)).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def money_to_cents(value: Any) -> int:
    return int((Decimal(str(value or 0)) * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


def bps_to_bp_x100(value: Any) -> int:
    return int((Decimal(str(value or 0)) * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


def pct_to_bp(value: Any) -> int | None:
    if value is None:
        return None
    return int((Decimal(str(value)) * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


def build_single_backtest_metadata(
    *,
    run_id: str,
    run_name: str,
    notes: str,
    params: dict[str, Any],
    details: dict[str, Any],
    report: Any,
    created_at: str,
) -> ResearchRunMetadataDTO:
    metrics = single_backtest_metrics(report)
    payload_hash = research_payload_hash(
        {
            "run_type": "single_backtest",
            "params": params,
            "metrics": metrics,
            "validation_status": getattr(report.validation_status, "value", ""),
        }
    )
    return ResearchRunMetadataDTO(
        run_id=run_id,
        run_name=run_name,
        run_type="single_backtest",
        strategy_id=str(params.get("strategy_id", "")),
        strategy_version=str(details.get("strategy_version", "")),
        parameter_contract_version=str(details.get("parameter_contract_version", "")),
        original_input={"source": "BacktestView", "notes": notes, "raw_params": params},
        normalized_params=dict(params.get("strategy_params", {}) or {}),
        fallback_reason=dict(details.get("fallback_reason", {}) or {}),
        universe=[str(params.get("stock_code", ""))] if params.get("stock_code") else [],
        start_date=str(params.get("start_date", "")),
        end_date=str(params.get("end_date", "")),
        data_cutoff_date=str(details.get("data_as_of_date", "")),
        data_fingerprint=str(details.get("data_version", "")),
        fingerprint_algorithm=(
            "sha256" if str(details.get("data_version", "")).startswith("sha256") else ""
        ),
        data_manifest=dict(details.get("data_manifest", {}) or {}),
        capital_cents=money_to_cents(params.get("capital", 0)),
        fee_bp_x100=bps_to_bp_x100(params.get("fee_bps", 0)),
        slippage_bp_x100=bps_to_bp_x100(params.get("slippage_bps", 0)),
        stop_loss_bp=pct_to_bp(params.get("stop_loss_pct")),
        take_profit_bp=pct_to_bp(params.get("take_profit_pct")),
        execution_price=str(params.get("execution_price") or details.get("execution_price", "")),
        sizing_mode=str(params.get("sizing_mode", "")),
        metrics=metrics,
        regime_breakdown=dict(details.get("regime_breakdown", {}) or {}),
        benchmark_results=dict(details.get("benchmark_results", {}) or {}),
        payload_hash=payload_hash,
        created_at=created_at,
    )


def build_recommendation_portfolio_metadata(
    *,
    run_id: str,
    run_name: str,
    notes: str,
    config: dict[str, Any],
    run_params: dict[str, Any],
    details: dict[str, Any],
    metrics: dict[str, Any],
    created_at: str,
) -> ResearchRunMetadataDTO:
    strategy_config = dict(config.get("strategy_config", {}) or {})
    payload_hash = research_payload_hash(
        {
            "run_type": "recommendation_portfolio",
            "config": config,
            "run_params": run_params,
            "metrics": metrics,
        }
    )
    return ResearchRunMetadataDTO(
        run_id=run_id,
        run_name=run_name,
        run_type="recommendation_portfolio",
        strategy_id=str(strategy_config.get("strategy_id") or config.get("profile_id", "")),
        strategy_version=str(details.get("strategy_version", "")),
        parameter_contract_version=str(details.get("parameter_contract_version", "")),
        original_input={"source": "BacktestView", "notes": notes, "config": config},
        normalized_params=run_params,
        fallback_reason=dict(details.get("fallback_reason", {}) or {}),
        universe=list(config.get("universe", []) or []),
        start_date=str(run_params.get("start_date", "")),
        end_date=str(run_params.get("end_date", "")),
        data_cutoff_date=str(details.get("data_as_of_date", "")),
        data_fingerprint=str(details.get("data_version", "")),
        fingerprint_algorithm=(
            "sha256" if str(details.get("data_version", "")).startswith("sha256") else ""
        ),
        data_manifest=dict(details.get("data_manifest", {}) or {}),
        capital_cents=money_to_cents(run_params.get("initial_capital", 0)),
        stop_loss_bp=pct_to_bp(run_params.get("stop_loss_pct")),
        take_profit_bp=pct_to_bp(run_params.get("take_profit_pct")),
        execution_price=str(details.get("execution_price", "")),
        sizing_mode=str(run_params.get("allocation_method", "")),
        metrics=metrics,
        regime_breakdown=dict(details.get("regime_breakdown", {}) or {}),
        benchmark_results=dict(details.get("benchmark_results", {}) or {}),
        payload_hash=payload_hash,
        created_at=created_at,
    )
