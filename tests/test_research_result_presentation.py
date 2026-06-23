from types import SimpleNamespace

from app_module.research_result_presentation import (
    build_recommendation_replay_sections,
    build_train_test_reliability_notice,
    build_walkforward_reliability_notice,
)


def test_recommendation_replay_sections_explain_capital_and_monte_carlo():
    result = SimpleNamespace(
        summary={
            "total_return": 0.5372,
            "max_drawdown": -0.2137,
            "total_trades": 291,
            "avg_holding_days": 3.8,
            "capital_used": 488_333_333,
            "stop_loss_exits": 1,
            "take_profit_exits": 2,
            "holding_period_exits": 288,
            "loss_trade_ratio": 0.54,
            "worst_stock_code": "3580",
            "worst_stock_name": "友威科",
            "worst_stock_pnl": -12345,
            "sharpe_ratio": 1.66,
            "sortino_ratio": 1.73,
            "monte_carlo_p05_return": 7.9573,
            "monte_carlo_p50_return": 7.9573,
            "monte_carlo_p95_return": 7.9573,
        },
        improvement_hints=["降低持有天數後再觀察"],
    )

    sections = build_recommendation_replay_sections(result)
    text = "\n".join(sections)

    assert "【概況】" in text
    assert "【交易假設與可信度】" in text
    assert "【Monte Carlo 情境】" in text
    assert "資金使用代表期間投入金額，不等同最終淨值" in text
    assert "P05 / P50 / P95" in text
    assert text.count("總報酬率") == 1


def test_train_test_reliability_warns_when_oos_trades_are_low():
    train_report = SimpleNamespace(
        total_trades=18,
        win_rate=0.55,
        max_drawdown=-0.12,
    )
    test_report = SimpleNamespace(
        total_trades=3,
        win_rate=1.0,
        max_drawdown=-0.18,
    )

    notice = build_train_test_reliability_notice(train_report, test_report)

    assert notice.level == "warning"
    assert notice.evidence["test_trades"] == 3
    assert "OOS 交易數: 3" in notice.message
    assert "樣本不足，不宜作正式策略判斷" in notice.message


def test_walkforward_reliability_warns_when_folds_below_three():
    result = SimpleNamespace(
        test_metrics={"total_trades": 4, "sharpe_ratio": 1.2},
        degradation=0.1,
    )

    notice = build_walkforward_reliability_notice(
        [result, result],
        {"total_folds": 2, "consistency": 1.0},
    )

    assert notice.level == "warning"
    assert notice.evidence["total_folds"] == 2
    assert notice.evidence["oos_trades"] == 8
    assert "Fold 數: 2" in notice.message
    assert "OOS 交易數: 8" in notice.message
    assert "樣本不足，不宜作正式策略判斷" in notice.message


def test_reliability_flags_perfect_win_rate_with_large_drawdown():
    train_report = SimpleNamespace(
        total_trades=25,
        win_rate=0.52,
        max_drawdown=-0.08,
    )
    test_report = SimpleNamespace(
        total_trades=22,
        win_rate=1.0,
        max_drawdown=-0.7729,
    )

    notice = build_train_test_reliability_notice(train_report, test_report)

    assert notice.level == "warning"
    assert notice.evidence["test_win_rate_bp"] == 10000
    assert notice.evidence["test_max_drawdown_bp"] == -7729
    assert "勝率 100%" in notice.message
    assert "最大回撤偏大" in notice.message
