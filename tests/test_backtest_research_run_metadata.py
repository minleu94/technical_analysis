from __future__ import annotations

from dataclasses import fields
from datetime import date
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace

import pandas as pd

from app_module.research_run_dtos import ResearchRunMetadataDTO
from ui_qt.views.backtest.research_run_metadata import (
    bps_to_bp_x100,
    build_recommendation_portfolio_metadata,
    build_single_backtest_metadata,
    factor_save_kwargs,
    json_safe,
    money_to_cents,
    pct_to_bp,
    research_payload_hash,
)


class _ValidationStatus(Enum):
    PASS = "pass"


def test_research_run_metadata_dto_contract_fields_remain_stable():
    assert tuple(field.name for field in fields(ResearchRunMetadataDTO)) == (
        "run_id",
        "run_name",
        "run_type",
        "strategy_id",
        "strategy_version",
        "parameter_contract_version",
        "original_input",
        "normalized_params",
        "fallback_reason",
        "universe",
        "start_date",
        "end_date",
        "data_cutoff_date",
        "data_fingerprint",
        "fingerprint_algorithm",
        "data_manifest",
        "capital_cents",
        "fee_bp_x100",
        "slippage_bp_x100",
        "stop_loss_bp",
        "take_profit_bp",
        "execution_price",
        "sizing_mode",
        "metrics",
        "regime_breakdown",
        "benchmark_results",
        "payload_hash",
        "equity_path",
        "equity_parquet_hash",
        "trades_path",
        "trades_parquet_hash",
        "is_archived",
        "promoted_version_id",
        "promotion_reconciliation_status",
        "created_at",
    )


def test_single_backtest_metadata_preserves_complete_assembly_contract():
    report = SimpleNamespace(
        total_return=Decimal("0.12"),
        annual_return=Decimal("0.18"),
        sharpe_ratio=Decimal("1.25"),
        max_drawdown=Decimal("-0.08"),
        win_rate=Decimal("0.55"),
        total_trades=3,
        expectancy=Decimal("0.04"),
        validation_status=_ValidationStatus.PASS,
    )
    params = {
        "stock_code": "2330",
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "strategy_id": "baseline_score",
        "strategy_params": {"buy_score": 55},
        "capital": Decimal("12.345"),
        "fee_bps": Decimal("14.255"),
        "slippage_bps": Decimal("5.004"),
        "stop_loss_pct": Decimal("2.345"),
        "take_profit_pct": None,
        "execution_price": "next_open",
        "sizing_mode": "all_in",
    }
    details = {
        "strategy_version": "baseline_score@1.0",
        "parameter_contract_version": "strategy-params@1",
        "fallback_reason": {"code": "none"},
        "data_as_of_date": "2026-03-31",
        "data_version": "sha256:data",
        "data_manifest": {"daily_prices": {"max_date": "2026-03-31"}},
        "regime_breakdown": {"bull": {"trades": 2}},
        "benchmark_results": {"TAIEX": {"excess_return": "0.01"}},
    }

    metadata = build_single_backtest_metadata(
        run_id="single_backtest_001",
        run_name="Run Name",
        notes="notes",
        params=params,
        details=details,
        report=report,
        created_at="2026-07-10T00:30:00-07:00",
    )

    assert metadata == ResearchRunMetadataDTO(
        run_id="single_backtest_001",
        run_name="Run Name",
        run_type="single_backtest",
        strategy_id="baseline_score",
        strategy_version="baseline_score@1.0",
        parameter_contract_version="strategy-params@1",
        original_input={"source": "BacktestView", "notes": "notes", "raw_params": params},
        normalized_params={"buy_score": 55},
        fallback_reason={"code": "none"},
        universe=["2330"],
        start_date="2026-01-01",
        end_date="2026-03-31",
        data_cutoff_date="2026-03-31",
        data_fingerprint="sha256:data",
        fingerprint_algorithm="sha256",
        data_manifest={"daily_prices": {"max_date": "2026-03-31"}},
        capital_cents=1235,
        fee_bp_x100=1426,
        slippage_bp_x100=500,
        stop_loss_bp=235,
        take_profit_bp=None,
        execution_price="next_open",
        sizing_mode="all_in",
        metrics={
            "total_return": Decimal("0.12"),
            "annual_return": Decimal("0.18"),
            "sharpe_ratio": Decimal("1.25"),
            "max_drawdown": Decimal("-0.08"),
            "win_rate": Decimal("0.55"),
            "total_trades": 3,
            "expectancy": Decimal("0.04"),
        },
        regime_breakdown={"bull": {"trades": 2}},
        benchmark_results={"TAIEX": {"excess_return": "0.01"}},
        payload_hash=research_payload_hash(
            {
                "run_type": "single_backtest",
                "params": params,
                "metrics": {
                    "total_return": Decimal("0.12"),
                    "annual_return": Decimal("0.18"),
                    "sharpe_ratio": Decimal("1.25"),
                    "max_drawdown": Decimal("-0.08"),
                    "win_rate": Decimal("0.55"),
                    "total_trades": 3,
                    "expectancy": Decimal("0.04"),
                },
                "validation_status": "pass",
            }
        ),
        created_at="2026-07-10T00:30:00-07:00",
    )


def test_recommendation_portfolio_metadata_preserves_complete_assembly_contract():
    config = {
        "profile_id": "advanced",
        "strategy_config": {"strategy_id": "recommendation_replay"},
        "universe": ["2330", "2317"],
    }
    run_params = {
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "initial_capital": Decimal("1000000.005"),
        "stop_loss_pct": Decimal("3.125"),
        "take_profit_pct": Decimal("8.875"),
        "allocation_method": "equal_weight",
    }
    details = {
        "strategy_version": "recommendation_replay@1.0",
        "parameter_contract_version": "replay@1",
        "data_as_of_date": "2026-03-31",
        "data_version": "legacy-data-v1",
        "data_manifest": {
            "factor_snapshot": {"schema_version": 1, "records": []},
            "factor_contributions": {"schema_version": 1, "by_stock": {}},
        },
        "execution_price": "next_open",
    }
    metrics = {"total_return": Decimal("0.15"), "total_trades": 4}

    metadata = build_recommendation_portfolio_metadata(
        run_id="recommendation_portfolio_001",
        run_name="Replay Run",
        notes="notes",
        config=config,
        run_params=run_params,
        details=details,
        metrics=metrics,
        created_at="2026-07-10T00:31:00-07:00",
    )

    assert metadata.run_type == "recommendation_portfolio"
    assert metadata.strategy_id == "recommendation_replay"
    assert metadata.original_input == {"source": "BacktestView", "notes": "notes", "config": config}
    assert metadata.normalized_params == run_params
    assert metadata.universe == ["2330", "2317"]
    assert metadata.capital_cents == 100000001
    assert metadata.stop_loss_bp == 313
    assert metadata.take_profit_bp == 888
    assert metadata.fingerprint_algorithm == ""
    assert metadata.factor_snapshot == {"schema_version": 1, "records": []}
    assert metadata.factor_contributions == {"schema_version": 1, "by_stock": {}}


def test_json_safe_hash_and_integer_conversions_are_stable():
    payload = {
        "frame": pd.DataFrame([{"stock_code": "2330", "score": Decimal("82.35")}]),
        "decimal": Decimal("1.2300"),
        "status": _ValidationStatus.PASS,
        "tuple": (Decimal("2.50"),),
    }

    assert json_safe(payload) == {
        "frame": [{"stock_code": "2330", "score": Decimal("82.35")}],
        "decimal": "1.2300",
        "status": "pass",
        "tuple": ["2.50"],
    }
    assert research_payload_hash({"b": Decimal("2.0"), "a": 1}) == research_payload_hash(
        {"a": 1, "b": Decimal("2.0")}
    )
    assert money_to_cents(Decimal("0.005")) == 1
    assert bps_to_bp_x100(Decimal("14.255")) == 1426
    assert pct_to_bp(Decimal("2.345")) == 235
    assert pct_to_bp(None) is None


def test_factor_save_kwargs_preserves_none_and_complete_behavior():
    decision_date = date(2026, 1, 5)

    assert factor_save_kwargs({}) == {}
    assert factor_save_kwargs({"factor_records": ["record"], "factor_decision_date": None}) == {}
    assert factor_save_kwargs(
        {"factor_records": ["record"], "factor_decision_date": decision_date}
    ) == {"factor_records": ["record"], "factor_decision_date": decision_date}
