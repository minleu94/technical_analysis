"""從已保存 Recommendation 建立 research-only V2.4 paper baseline。"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig
from app_module.portfolio_construction_dtos import (
    PortfolioConstructionCandidate,
    PortfolioConstructionRequest,
)
from app_module.portfolio_construction_service import PortfolioConstructionService


def _decimal(value: object, *, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or isinstance(value, bool):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


class PaperPortfolioBaselineService:
    """只讀 Recommendation artifact；不寫持倉或建立 broker order。"""

    def __init__(self, policy: PaperPortfolioPolicyConfig | None = None) -> None:
        self._policy = policy or PaperPortfolioPolicyConfig()

    def build(self, source_path: str | Path) -> dict[str, Any]:
        path = Path(source_path)
        source = json.loads(path.read_text(encoding="utf-8"))
        rows = source.get("recommendations")
        if not isinstance(rows, list) or not rows:
            raise ValueError("saved recommendation contains no candidates")

        selected = rows[: self._policy.max_positions]
        candidates = tuple(self._candidate(row) for row in selected)
        decision_date = self._decision_date(source)
        result = PortfolioConstructionService().construct(
            PortfolioConstructionRequest(
                decision_date=decision_date,
                capital_amount=self._policy.initial_capital,
                allocation_method="score_weight",
                candidates=candidates,
                max_position_weight_bp=self._policy.max_single_position_bp,
                lot_size=1000,
            )
        )
        score_by_code = {candidate.stock_code: candidate.score_bp for candidate in candidates}
        allocations = []
        for row in result.allocations:
            payload = row.to_dict()
            payload["score_bp"] = score_by_code[row.stock_code]
            allocations.append(payload)

        policy = asdict(self._policy)
        policy["initial_capital"] = str(self._policy.initial_capital)
        return {
            "source_path": str(path.resolve()),
            "source_result_id": str(source.get("result_id") or ""),
            "decision_date": decision_date,
            "research_only": True,
            "writes_positions_db": False,
            "broker_order_allowed": False,
            "auto_rebalance_allowed": False,
            "policy": policy,
            "allocations": allocations,
            "residual_cash": str(result.residual_cash),
            "diagnostics": list(result.diagnostics),
            "warnings": [
                *result.warnings,
                "saved_recommendation_is_not_forward_or_live_evidence",
            ],
        }

    @staticmethod
    def _candidate(row: object) -> PortfolioConstructionCandidate:
        if not isinstance(row, dict):
            raise ValueError("recommendation row must be an object")
        score = _decimal(row.get("總分"))
        return PortfolioConstructionCandidate(
            stock_code=str(row.get("證券代號") or "").strip(),
            stock_name=str(row.get("證券名稱") or "").strip(),
            score_bp=int(score * Decimal("100")),
            reference_price=_decimal(row.get("收盤價")).quantize(Decimal("0.01")),
            metadata={"sector": str(row.get("產業") or "")},
        )

    @staticmethod
    def _decision_date(source: dict[str, Any]) -> str:
        created_at = str(source.get("created_at") or "")
        if len(created_at) >= 10:
            return created_at[:10]
        result_id = str(source.get("result_id") or "")
        for token in result_id.split("_"):
            if len(token) == 8 and token.isdigit():
                return f"{token[:4]}-{token[4:6]}-{token[6:]}"
        raise ValueError("saved recommendation is missing a decision date")
