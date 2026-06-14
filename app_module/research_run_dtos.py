"""Research Run Registry DTO 與 canonical JSON 序列化工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


JsonObject = dict[str, Any]


def canonical_json(value: Any) -> str:
    """產生穩定 JSON 字串，供 SQLite round-trip 與 hash 前置序列化使用。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json_object(value: str | None) -> JsonObject:
    if not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ValueError("Research run JSON 欄位必須是 object")
    return loaded


def parse_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        raise ValueError("Research run universe 欄位必須是 list")
    return loaded


@dataclass(frozen=True)
class ResearchRunMetadataDTO:
    """統一研究 run 的 metadata 快照。

    詳細 equity / trades payload 由後續 service 寫入 Parquet；本 DTO 只保存
    可比較、可追溯的 metadata 與檔案 hash。
    """

    run_id: str
    run_name: str
    run_type: str
    strategy_id: str = ""
    strategy_version: str = ""
    parameter_contract_version: str = ""
    original_input: JsonObject = field(default_factory=dict)
    normalized_params: JsonObject = field(default_factory=dict)
    fallback_reason: JsonObject = field(default_factory=dict)
    universe: list[Any] = field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    data_cutoff_date: str = ""
    data_fingerprint: str = ""
    fingerprint_algorithm: str = ""
    data_manifest: JsonObject = field(default_factory=dict)
    capital_cents: int = 0
    fee_bp_x100: int = 0
    slippage_bp_x100: int = 0
    stop_loss_bp: int | None = None
    take_profit_bp: int | None = None
    execution_price: str = ""
    sizing_mode: str = ""
    metrics: JsonObject = field(default_factory=dict)
    regime_breakdown: JsonObject = field(default_factory=dict)
    benchmark_results: JsonObject = field(default_factory=dict)
    payload_hash: str = ""
    equity_path: str = ""
    equity_parquet_hash: str = ""
    trades_path: str = ""
    trades_parquet_hash: str = ""
    is_archived: bool = False
    promoted_version_id: str | None = None
    promotion_reconciliation_status: str = "none"
    created_at: str = ""
