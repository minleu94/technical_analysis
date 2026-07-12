from app_module.broker_branch_merge import merge_metric_records
from app_module.broker_branch_transport import build_branch_url


def test_transport_builder_rejects_missing_branch_parameter() -> None:
    try:
        build_branch_url({"branch_system_key": "A", "url_param_b": ""}, "2026-01-01", "2026-01-02")
    except ValueError as exc:
        assert str(exc) == "url_param_b 為空: A"
    else:
        raise AssertionError("missing url_param_b must fail closed")


def test_merge_plan_keeps_amount_only_record_explicit() -> None:
    amount = {
        "date": "2026-01-02",
        "trade_type": "買超",
        "branch_system_key": "A",
        "branch_broker_code": "A",
        "branch_code": "B",
        "branch_display_name": "分點",
        "counterparty_broker_code": "2330",
        "counterparty_broker_name": "台積電",
        "buy_amount_k_twd": 10,
        "sell_amount_k_twd": 2,
        "net_amount_k_twd": 8,
        "metric_rank": 1,
    }

    merged = merge_metric_records([], [amount])

    assert merged[0]["lots_observed"] is False
    assert merged[0]["amount_observed"] is True
    assert merged[0]["amount_rank"] == 1
