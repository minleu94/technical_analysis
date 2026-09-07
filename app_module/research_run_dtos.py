"""Research Run Registry DTO 與 canonical JSON 序列化工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class EvidenceReviewProposalDTO:
    """人工覆盤接點；內容為研究提案，不是 lifecycle 決議。"""

    run_id: str
    payload_hash: str
    execution_contract: str
    evidence: tuple[JsonObject, ...] = ()
    missing_requirements: tuple[str, ...] = ()
    reviewer: str = ""
    review_notes: str = ""
    next_research_question: str = ""
    formal_credit_granted: bool = False
    promotion_allowed: bool = False
    proposal_only: bool = True


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

    @property
    def execution_contract(self) -> str:
        """舊 next_open/close 不推測為新契約，歷史快照不原地升級。"""
        declared = self.data_manifest.get("execution_contract")
        if declared:
            return str(declared)
        return self.execution_price if ".v" in self.execution_price else "unversioned"

    @property
    def factor_snapshot(self) -> JsonObject:
        snapshot = self.data_manifest.get("factor_snapshot", {})
        if not isinstance(snapshot, dict):
            raise ValueError("factor_snapshot 必須是 object")
        return snapshot

    @property
    def factor_contributions(self) -> JsonObject:
        contributions = self.data_manifest.get("factor_contributions", {})
        if not isinstance(contributions, dict):
            raise ValueError("factor_contributions 必須是 object")
        return contributions
