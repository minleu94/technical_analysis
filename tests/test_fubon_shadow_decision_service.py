from decimal import Decimal
import pandas as pd
import pytest

from data_module.fubon_shadow_authorization import FubonShadowComputationAuthorization
from app_module.fubon_shadow_decision_service import FubonShadowDecisionService
from app_module.portfolio_construction_dtos import (
    PortfolioConstructionCandidate,
    PortfolioConstructionRequest,
)


def test_fubon_shadow_decision_service_runs_baseline_vs_candidate() -> None:
    auth = FubonShadowComputationAuthorization()
    service = FubonShadowDecisionService(auth)

    df = pd.DataFrame(
        [
            {"股票代號": "2330", "證券名稱": "台積電", "收盤價": 1000.0, "TotalScore": 80.0, "FinalScore": 80.0},
            {"股票代號": "2317", "證券名稱": "鴻海", "收盤價": 200.0, "TotalScore": 70.0, "FinalScore": 70.0},
        ]
    )
    config = {
        "filters": {"pe_ratio_max": 999.0, "monthly_revenue_yoy_min": -100.0},
        "signals": {"weights": {"pattern": 3000, "technical": 5000, "volume": 2000}},
    }

    obs = [
        {
            "symbol": "2330",
            "available_at": "2026-07-25T00:00:00+00:00",
            "quantities": {"is_disposition": 1},
        }
    ]

    req = PortfolioConstructionRequest(
        decision_date="2026-07-26",
        allocation_method="equal_weight",
        capital_amount=Decimal("100000"),
        candidates=(
            PortfolioConstructionCandidate(stock_code="2330", stock_name="台積電", reference_price=Decimal("1000"), score_bp=8000),
            PortfolioConstructionCandidate(stock_code="2317", stock_name="鴻海", reference_price=Decimal("200"), score_bp=7000),
        ),
    )

    bundle = service.evaluate_shadow_decision(
        raw_observations=obs,
        decision_timestamp="2026-07-26T00:00:00+00:00",
        universe_df=df,
        strategy_config=config,
        portfolio_request=req,
    )

    assert bundle.formal_rule_unchanged is True
    assert bundle.formal_decision_influence_allowed is False
    assert bundle.formal_evidence_credit_authorized is False
    assert bundle.production_blend_alpha_bp == 0
    assert bundle.pit_validation_status in ("passed", "degraded")
    assert "score_differences" in bundle.differences
    assert bundle.fubon_shadow_result["status"] == "not_computable"
    assert "mapping_result" in bundle.fubon_shadow_result
    assert bundle.differences["status"] == "not_computable"
    assert "score_differences" in bundle.differences


def test_fubon_shadow_unmapped_feature_returns_not_computable() -> None:
    auth = FubonShadowComputationAuthorization()
    service = FubonShadowDecisionService(auth)

    df = pd.DataFrame([{"股票代號": "2330", "證券名稱": "台積電", "收盤價": 1000.0}])
    config = {"filters": {"pe_ratio_max": 999.0, "monthly_revenue_yoy_min": -100.0}}

    obs = [
        {
            "symbol": "2330",
            "available_at": "2026-07-25T00:00:00+00:00",
            "quantities": {"unknown_custom_signal": 999},
        }
    ]

    bundle = service.evaluate_shadow_decision(
        raw_observations=obs,
        decision_timestamp="2026-07-26T00:00:00+00:00",
        universe_df=df,
        strategy_config=config,
    )

    assert bundle.fubon_shadow_result.get("status") == "not_computable"
