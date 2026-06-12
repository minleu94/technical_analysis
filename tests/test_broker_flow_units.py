from types import SimpleNamespace
import pandas as pd
from app_module.broker_flow_service import BrokerFlowService


def test_broker_flow_service_reads_explicit_lot_columns(tmp_path):
    branch_dir = tmp_path / "broker_flow" / "8450_845B" / "meta"
    branch_dir.mkdir(parents=True)
    pd.DataFrame([{
        "date": "2026-06-11",
        "branch_system_key": "8450_845B",
        "branch_display_name": "康和-永和",
        "counterparty_broker_code": "00631L",
        "counterparty_broker_name": "元大台灣50正2",
        "buy_lots": 160,
        "sell_lots": 20,
        "net_lots": 140,
        "buy_amount_k_twd": 5291,
        "sell_amount_k_twd": 653,
        "net_amount_k_twd": 4638,
    }]).to_csv(branch_dir / "merged.csv", index=False, encoding="utf-8-sig")
    config = SimpleNamespace(
        broker_flow_dir=tmp_path / "broker_flow",
        data_dir=tmp_path,
    )

    events = BrokerFlowService(config)._load_data()

    assert len(events) == 1
    assert events[0].buy_qty == 160
    assert events[0].net_qty == 140
    assert events[0].buy_amount_k_twd == 5291


def test_broker_flow_service_does_not_treat_legacy_b_values_as_lots(tmp_path):
    branch_dir = tmp_path / "broker_flow" / "8450_845B" / "meta"
    branch_dir.mkdir(parents=True)
    pd.DataFrame([{
        "date": "2026-06-11",
        "branch_system_key": "8450_845B",
        "branch_display_name": "康和-永和",
        "counterparty_broker_code": "00631L",
        "counterparty_broker_name": "元大台灣50正2",
        "buy_qty": 5291,
        "sell_qty": 653,
        "net_qty": 4638,
    }]).to_csv(branch_dir / "merged.csv", index=False, encoding="utf-8-sig")
    config = SimpleNamespace(
        broker_flow_dir=tmp_path / "broker_flow",
        data_dir=tmp_path,
    )

    events = BrokerFlowService(config)._load_data()

    # buy_lots is not present, so lots are missing. Since use_sqlite is False/missing,
    # it remains empty or fails to estimate, lots_available becomes False, buy_qty is None.
    assert len(events) == 1
    assert events[0].buy_qty is None
    assert events[0].lots_available is False


def test_flow_signal_engine_estimated_discount():
    from app_module.dtos.broker_flow_dtos import StockFlowAggregation, BrokerFlowEvent
    from decision_module.flow_signal_engine import FlowSignalEngine

    event = BrokerFlowEvent(
        date="2026-06-11",
        branch_system_key="8450_845B",
        branch_display_name="康和-永和",
        stock_code="2330",
        stock_name="台積電",
        buy_qty=100,
        sell_qty=0,
        net_qty=100,
        buy_amount_k_twd=1000,
        sell_amount_k_twd=0,
        net_amount_k_twd=1000,
        lots_available=True,
        has_estimated_lots=True
    )

    agg = StockFlowAggregation(
        stock_code="2330",
        stock_name="台積電",
        total_buy_qty=100,
        total_sell_qty=0,
        total_net_qty=100,
        buying_branches=["康和-永和"],
        selling_branches=[],
        events=[event],
        lots_available=True,
        has_estimated_lots=True
    )

    engine = FlowSignalEngine()
    signal = engine._process_single_stock(agg)

    # Base flow score: min(40, sqrt(100)/2) = 5.0
    # Branch concentration: 1.0 (>= 0.7) -> +10.0 score
    # Score sum = 15.0 -> Discounted by 0.8 -> 15.0 * 0.8 = 12.0
    assert signal.smart_money_score == 12.0
    assert signal.has_estimated_lots is True
    assert "金額估算" in signal.signal_tags


def test_broker_flow_service_no_price_remains_none(tmp_path):
    branch_dir = tmp_path / "broker_flow" / "8450_845B" / "meta"
    branch_dir.mkdir(parents=True)

    pd.DataFrame([{
        "date": "2026-06-11",
        "branch_system_key": "8450_845B",
        "branch_display_name": "康和-永和",
        "counterparty_broker_code": "00631L",
        "counterparty_broker_name": "元大台灣50正2",
        "buy_amount_k_twd": 5000,
        "sell_amount_k_twd": 0,
        "net_amount_k_twd": 5000,
    }]).to_csv(branch_dir / "merged.csv", index=False, encoding="utf-8-sig")

    config = SimpleNamespace(
        broker_flow_dir=tmp_path / "broker_flow",
        data_dir=tmp_path,
        use_sqlite=True
    )

    class MockDBManager:
        def __init__(self, cfg):
            pass
        def execute_query(self, *args, **kwargs):
            return pd.DataFrame()

    import data_module.db_manager
    original_db_manager = data_module.db_manager.DBManager
    data_module.db_manager.DBManager = MockDBManager

    try:
        service = BrokerFlowService(config)
        events = service._load_data(force_reload=True)

        assert len(events) == 1
        assert events[0].buy_qty is None
        assert events[0].lots_available is False
        assert events[0].has_estimated_lots is False
    finally:
        data_module.db_manager.DBManager = original_db_manager


def test_broker_flow_service_estimates_lots_with_price(tmp_path):
    branch_dir = tmp_path / "broker_flow" / "8450_845B" / "meta"
    branch_dir.mkdir(parents=True)

    pd.DataFrame([{
        "date": "2026-06-11",
        "branch_system_key": "8450_845B",
        "branch_display_name": "康和-永和",
        "counterparty_broker_code": "00631L",
        "counterparty_broker_name": "元大台灣50正2",
        "buy_amount_k_twd": 5000,
        "sell_amount_k_twd": 0,
        "net_amount_k_twd": 5000,
    }]).to_csv(branch_dir / "merged.csv", index=False, encoding="utf-8-sig")

    config = SimpleNamespace(
        broker_flow_dir=tmp_path / "broker_flow",
        data_dir=tmp_path,
        use_sqlite=True
    )

    price_df = pd.DataFrame([{
        "日期": "20260611",
        "證券代號": "00631L",
        "收盤價": 33.3
    }])

    class MockDBManager:
        def __init__(self, cfg):
            pass
        def execute_query(self, *args, **kwargs):
            return price_df

    import data_module.db_manager
    original_db_manager = data_module.db_manager.DBManager
    data_module.db_manager.DBManager = MockDBManager

    try:
        service = BrokerFlowService(config)
        events = service._load_data(force_reload=True)

        assert len(events) == 1
        # 5000 / 33.3 = 150.15015 -> ROUND_HALF_UP to 150 lots
        assert events[0].buy_qty == 150
        assert events[0].lots_available is True
        assert events[0].has_estimated_lots is True
    finally:
        data_module.db_manager.DBManager = original_db_manager
