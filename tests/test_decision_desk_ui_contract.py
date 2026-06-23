from pathlib import Path


def test_decision_desk_view_does_not_import_domain_calculation_modules():
    source = Path("ui_qt/views/decision_desk_view.py").read_text(encoding="utf-8")
    blocked_patterns = [
        "decision_module.scoring_engine",
        "decision_module.stock_screener",
        "decision_module.flow_signal_engine",
        "data_module.db_manager",
        "backtest_module",
        "app_module.recommendation_service",
        "app_module.recommendation_replay_service",
        "portfolio_module.core",
    ]

    for pattern in blocked_patterns:
        assert pattern not in source


def test_decision_desk_view_uses_approved_snapshot_services_only():
    source = Path("ui_qt/views/decision_desk_view.py").read_text(encoding="utf-8")

    assert "app_module.decision_desk_dtos" in source
    assert "app_module.decision_desk_service" in source
