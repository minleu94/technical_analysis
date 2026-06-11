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

    assert events == []
