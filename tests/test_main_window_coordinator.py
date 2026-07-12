from ui_qt.main_window_coordinator import WORKSPACE_DEFINITIONS, resolve_workspace_key


def test_resolve_workspace_key_preserves_navigation_aliases() -> None:
    assert resolve_workspace_key("決策工作台") == "workbench"
    assert resolve_workspace_key("每日決策") == "workbench"
    assert resolve_workspace_key("市場觀察") == "market_explore"
    assert resolve_workspace_key("策略回測") == "backtest"
    assert resolve_workspace_key("Runtime Observatory") == "runtime"
    assert resolve_workspace_key("custom") == "custom"


def test_workspace_definitions_lock_navigation_order_and_icons() -> None:
    assert [(item.key, item.label, item.icon) for item in WORKSPACE_DEFINITIONS] == [
        ("workbench", "決策工作台", "command"),
        ("market_explore", "市場探索", "radar"),
        ("recommendation", "推薦分析", "spark-list"),
        ("backtest", "策略回測", "replay"),
        ("watchlist", "觀察清單", "bookmark"),
        ("portfolio", "持倉管理", "briefcase"),
        ("update", "數據更新", "database-sync"),
        ("runtime", "Runtime", "pulse"),
    ]
