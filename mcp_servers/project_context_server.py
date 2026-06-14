from __future__ import annotations

from pathlib import Path
from typing import Any

from data_module.config import TWStockConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_SNAPSHOT_PATH = PROJECT_ROOT / "docs" / "00_core" / "PROJECT_SNAPSHOT.md"


def _path_value(value: Any) -> str:
    return str(value) if isinstance(value, Path) else str(value)


def build_twstock_config_snapshot() -> dict[str, Any]:
    """回傳 TWStockConfig 的 JSON-friendly 狀態。"""
    config = TWStockConfig()
    path_fields = [
        "data_root",
        "output_root",
        "base_dir",
        "data_dir",
        "daily_price_dir",
        "meta_data_dir",
        "technical_dir",
        "log_dir",
        "market_index_file",
        "industry_index_file",
        "stock_data_file",
        "all_stocks_data_file",
        "broker_flow_dir",
        "broker_branch_registry_file",
        "backup_dir",
    ]
    scalar_fields = [
        "profile",
        "default_start_date",
        "backup_keep_days",
        "min_data_days",
        "request_timeout",
        "max_retries",
        "retry_delay",
    ]

    payload: dict[str, Any] = {}
    for field_name in path_fields:
        payload[field_name] = _path_value(getattr(config, field_name))
    for field_name in scalar_fields:
        payload[field_name] = getattr(config, field_name)
    return payload


def read_project_snapshot() -> dict[str, Any]:
    """回傳專案快照文件內容與基本 metadata。"""
    content = PROJECT_SNAPSHOT_PATH.read_text(encoding="utf-8")
    return {
        "path": str(PROJECT_SNAPSHOT_PATH),
        "line_count": len(content.splitlines()),
        "content": content,
    }


def build_boot_context() -> dict[str, Any]:
    return {
        "twstock_config": build_twstock_config_snapshot(),
        "project_snapshot": read_project_snapshot(),
    }


def create_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("technical-analysis-context")

    @mcp.tool()
    def get_twstock_config_status() -> dict[str, Any]:
        """讀取 data_module.config.TWStockConfig 目前解析後的路徑與參數。"""
        return build_twstock_config_snapshot()

    @mcp.tool()
    def get_project_snapshot() -> dict[str, Any]:
        """讀取 docs/00_core/PROJECT_SNAPSHOT.md。"""
        return read_project_snapshot()

    @mcp.tool()
    def get_project_boot_context() -> dict[str, Any]:
        """一次取得 TWStockConfig 狀態與 PROJECT_SNAPSHOT 內容。"""
        return build_boot_context()

    return mcp


if __name__ == "__main__":
    create_mcp_server().run(show_banner=False)
