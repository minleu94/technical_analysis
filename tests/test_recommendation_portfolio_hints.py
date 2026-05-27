from app_module.recommendation_portfolio_metrics import generate_improvement_hints

def test_hints_no_trades():
    summary = {"total_trades": 0}
    hints = generate_improvement_hints(summary)
    assert len(hints) == 1
    assert "沒有任何推薦交易" in hints[0]


def test_hints_stop_loss_too_frequent():
    summary = {
        "total_trades": 10,
        "stop_loss_exits": 4,
        "holding_period_exits": 6,
        "total_return": 0.02,
        "capital_used": 100000.0,
        "worst_stock_pnl": -100.0,
        "worst_stock_code": "2330",
        "worst_stock_name": "TSMC",
    }
    hints = generate_improvement_hints(summary)
    # 停損佔比 4/10 = 40% > 30%，應觸發
    assert any("停損出場次數過高" in h for h in hints)
    # 報酬為正，不應觸發持有到期績效差提示
    assert not any("期滿出場" in h for h in hints)


def test_hints_holding_period_poor_performance():
    summary = {
        "total_trades": 10,
        "stop_loss_exits": 2,
        "holding_period_exits": 8,
        "total_return": -0.05,
        "capital_used": 100000.0,
        "worst_stock_pnl": -2000.0,  # 佔比 2000/100000 = 2% < 5%，不觸發個股曝險
        "worst_stock_code": "2330",
        "worst_stock_name": "TSMC",
    }
    hints = generate_improvement_hints(summary)
    # 持有到期佔比 80% 且整體虧損，應觸發
    assert any("期滿出場" in h for h in hints)
    # 虧損應觸發未能擊敗大盤提示
    assert any("整體報酬率為負值" in h for h in hints)


def test_hints_worst_stock_exposure_too_high():
    summary = {
        "total_trades": 5,
        "stop_loss_exits": 1,
        "holding_period_exits": 4,
        "total_return": -0.02,
        "capital_used": 100000.0,
        "worst_stock_pnl": -6000.0,  # 佔比 6000/100000 = 6% > 5% 應觸發
        "worst_stock_code": "2317",
        "worst_stock_name": "鴻海",
    }
    hints = generate_improvement_hints(summary)
    assert any("單一最差個股（2317 鴻海）" in h for h in hints)


def test_hints_too_few_trades():
    summary = {
        "total_trades": 2,
        "stop_loss_exits": 0,
        "holding_period_exits": 2,
        "total_return": 0.05,
        "capital_used": 100000.0,
        "worst_stock_pnl": 0.0,
        "worst_stock_code": "",
        "worst_stock_name": "",
    }
    hints = generate_improvement_hints(summary)
    assert any("交易次數過少" in h for h in hints)
