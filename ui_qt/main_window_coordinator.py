"""MainWindow 的非 Qt 導覽協調規則。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceDefinition:
    key: str
    label: str
    icon: str


WORKSPACE_DEFINITIONS = (
    WorkspaceDefinition("workbench", "決策工作台", "command"),
    WorkspaceDefinition("market_explore", "市場探索", "radar"),
    WorkspaceDefinition("recommendation", "推薦分析", "spark-list"),
    WorkspaceDefinition("backtest", "策略回測", "replay"),
    WorkspaceDefinition("watchlist", "觀察清單", "bookmark"),
    WorkspaceDefinition("portfolio", "持倉管理", "briefcase"),
    WorkspaceDefinition("update", "數據更新", "database-sync"),
    WorkspaceDefinition("runtime", "Runtime", "pulse"),
)


WORKSPACE_ALIASES = {
    "決策工作台": "workbench",
    "每日決策": "workbench",
    "市場探索": "market_explore",
    "市場觀察": "market_explore",
    "推薦分析": "recommendation",
    "策略回測": "backtest",
    "觀察清單": "watchlist",
    "持倉管理": "portfolio",
    "數據更新": "update",
    "Runtime": "runtime",
    "Runtime Observatory": "runtime",
}


def resolve_workspace_key(key_or_label: str) -> str:
    return WORKSPACE_ALIASES.get(key_or_label, key_or_label)
