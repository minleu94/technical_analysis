from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.portfolio_source_adapter import (
    build_backtest_trade_source,
    build_recommendation_trade_source,
    stable_snapshot_hash,
)


def make_recommendation() -> RecommendationDTO:
    return RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        close_price=888.0,
        price_change=1.25,
        total_score=82.5,
        indicator_score=80.0,
        pattern_score=75.0,
        volume_score=92.0,
        recommendation_reasons="量能放大；趨勢偏多",
        industry="半導體",
        regime_match=True,
    )


def test_build_recommendation_trade_source_contains_traceable_context():
    result = RecommendationResultDTO(
        result_id="rec_20260604_001",
        result_name="短線暴衝候選",
        created_at="2026-06-04T09:00:00",
        config={
            "profile_id": "aggressive_short",
            "profile_version": "1.0",
            "regime_snapshot": {"regime": "trend", "confidence": 0.81},
        },
        recommendations=[make_recommendation()],
        regime="trend",
        notes="日常推薦",
    )

    source = build_recommendation_trade_source(result, make_recommendation())

    assert source.source_type == "recommendation_result"
    assert source.source_id == "rec_20260604_001"
    assert source.source_snapshot_hash
    assert source.source_summary["result_id"] == "rec_20260604_001"
    assert source.source_summary["result_name"] == "短線暴衝候選"
    assert source.source_summary["created_at"] == "2026-06-04T09:00:00"
    assert source.source_summary["stock_code"] == "2330"
    assert source.source_summary["stock_name"] == "台積電"
    assert source.source_summary["close_price"] == 888.0
    assert source.source_summary["price_change"] == 1.25
    assert source.source_summary["profile_id"] == "aggressive_short"
    assert source.source_summary["profile_version"] == "1.0"
    assert source.source_summary["regime"] == "trend"
    assert source.source_summary["total_score"] == 82.5
    assert source.source_summary["indicator_score"] == 80.0
    assert source.source_summary["pattern_score"] == 75.0
    assert source.source_summary["volume_score"] == 92.0
    assert source.source_summary["recommendation_reasons"] == "量能放大；趨勢偏多"
    assert source.source_summary["reasons"] == "量能放大；趨勢偏多"
    assert source.source_summary["industry"] == "半導體"
    assert source.source_summary["regime_match"] is True


def test_build_backtest_trade_source_contains_run_and_strategy_context():
    row = {
        "股票代號": "2330",
        "股票名稱": "台積電",
        "買賣": "買入",
        "交易日期": "2026-06-04",
        "價格": 888.0,
        "數量": 1000,
    }
    source = build_backtest_trade_source(
        run_id="run_001",
        run_name="2330 momentum smoke",
        strategy_id="momentum_aggressive_v1",
        validation_status="PASS",
        trade_row=row,
    )

    assert source.source_type == "backtest_run"
    assert source.source_id == "run_001"
    assert source.source_snapshot_hash
    assert source.source_summary["strategy_id"] == "momentum_aggressive_v1"
    assert source.source_summary["validation_status"] == "PASS"
    assert source.source_summary["stock_code"] == "2330"


def test_build_backtest_trade_source_maps_amount_to_quantity_when_quantity_missing():
    row = {
        "股票代號": "2330",
        "股票名稱": "台積電",
        "買賣": "買入",
        "交易日期": "2026-06-04",
        "價格": 888.0,
        "amount": 1000,
    }
    source = build_backtest_trade_source(
        run_id="run_002",
        run_name="2330 momentum smoke",
        strategy_id="momentum_aggressive_v1",
        validation_status="PASS",
        trade_row=row,
    )

    assert source.source_summary["quantity"] == 1000


def test_build_backtest_trade_source_supports_realistic_ui_row_aliases():
    row = {
        "證券代號": "2330",
        "證券名稱": "台積電",
        "買賣": "買入",
        "日期": "2026-06-04",
        "單價": 888.0,
        "交易股數": 1000,
    }
    source = build_backtest_trade_source(
        run_id="run_003",
        run_name="2330 momentum smoke",
        strategy_id="momentum_aggressive_v1",
        validation_status="PASS",
        trade_row=row,
    )

    assert source.source_summary["stock_code"] == "2330"
    assert source.source_summary["stock_name"] == "台積電"
    assert source.source_summary["trade_date"] == "2026-06-04"
    assert source.source_summary["price"] == 888.0
    assert source.source_summary["quantity"] == 1000


def test_stable_snapshot_hash_is_deterministic_for_same_payload_and_changes_with_payload():
    same_left = stable_snapshot_hash({"a": 1, "b": [2]})
    same_right = stable_snapshot_hash({"b": [2], "a": 1})
    different = stable_snapshot_hash({"a": 2, "b": [2]})

    assert same_left == same_right
    assert same_left != different
