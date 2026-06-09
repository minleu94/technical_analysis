"""Portfolio condition monitoring for append-only Phase 4.1 positions.

此模組只對照進場來源快照與目前狀態，提供決策支援標籤；
不做自動交易、不調整持倉，也不寫入儲存層。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from app_module.dtos.portfolio_dtos import PositionDTO


@dataclass(frozen=True)
class PortfolioCurrentSnapshot:
    """目前狀態快照，用於和持倉來源快照對照。"""

    current_regime: str = ""
    current_total_score: Optional[Any] = None


@dataclass(frozen=True)
class PortfolioConditionResult:
    """單一持倉的條件監控結果。"""

    stock_code: str
    status: str
    label: str
    source_label: str
    entry_regime: str = ""
    current_regime: str = ""
    entry_total_score: str = ""
    current_total_score: str = ""
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class PortfolioConditionMonitor:
    """Evaluate whether a derived position still matches its source thesis."""

    def __init__(self, score_warning_points: int | str | Decimal = 10):
        self.score_warning_points = self._to_decimal(score_warning_points) or Decimal("10")

    def evaluate(
        self,
        position: PositionDTO,
        current_snapshot: Optional[PortfolioCurrentSnapshot] = None,
    ) -> PortfolioConditionResult:
        source_summary = dict(position.source_summary or {})
        source_label = self._source_label(position, source_summary)

        if not position.source_type and not source_summary:
            return PortfolioConditionResult(
                stock_code=position.stock_code,
                status="warning",
                label="來源不足",
                source_label=source_label,
                reasons=["缺少推薦、回測或策略版本來源，無法對照進場假設"],
                details={
                    "source_type": position.source_type,
                    "source_id": position.source_id,
                    "source_summary_available": False,
                },
            )

        snapshot = current_snapshot or PortfolioCurrentSnapshot()
        entry_regime = str(
            source_summary.get("regime")
            or source_summary.get("entry_regime")
            or ""
        )
        current_regime = str(snapshot.current_regime or "")

        entry_score = self._to_decimal(
            source_summary.get("total_score", source_summary.get("entry_total_score"))
        )
        current_score = self._to_decimal(snapshot.current_total_score)

        reasons: List[str] = []
        details: Dict[str, Any] = {
            "source_type": position.source_type,
            "source_id": position.source_id,
            "profile_id": source_summary.get("profile_id", ""),
            "strategy_id": source_summary.get("strategy_id", ""),
            "entry_regime": entry_regime,
            "current_regime": current_regime,
            "regime_changed": False,
            "score_degraded": False,
        }

        if entry_regime and current_regime:
            if entry_regime != current_regime:
                details["regime_changed"] = True
                reasons.append(f"Regime 已由 {entry_regime} 轉為 {current_regime}")
            else:
                reasons.append(f"Regime 仍為 {entry_regime}")

        score_change: Optional[Decimal] = None
        if entry_score is not None and current_score is not None:
            score_change = current_score - entry_score
            details["score_change"] = self._format_decimal(score_change)
            details["entry_total_score"] = self._format_decimal(entry_score)
            details["current_total_score"] = self._format_decimal(current_score)
            if score_change <= -self.score_warning_points:
                details["score_degraded"] = True
                reasons.append(
                    f"評分下降 {self._format_decimal(abs(score_change))} 分"
                )
            else:
                reasons.append(
                    "評分變化 "
                    f"{self._format_decimal(score_change)} 分，"
                    f"未超過 {self._format_points(self.score_warning_points)} 分門檻"
                )

        if not reasons:
            return PortfolioConditionResult(
                stock_code=position.stock_code,
                status="warning",
                label="待更新",
                source_label=source_label,
                entry_regime=entry_regime,
                current_regime=current_regime,
                entry_total_score=self._format_decimal(entry_score),
                current_total_score=self._format_decimal(current_score),
                reasons=["尚無目前 Regime 或評分快照，請更新後再判讀"],
                details=details,
            )

        if details["regime_changed"] and details["score_degraded"]:
            status = "invalid"
            label = "假設失效"
        elif details["regime_changed"] or details["score_degraded"]:
            status = "warning"
            label = "需要留意"
        else:
            status = "valid"
            label = "仍符合"

        return PortfolioConditionResult(
            stock_code=position.stock_code,
            status=status,
            label=label,
            source_label=source_label,
            entry_regime=entry_regime,
            current_regime=current_regime,
            entry_total_score=self._format_decimal(entry_score),
            current_total_score=self._format_decimal(current_score),
            reasons=reasons,
            details=details,
        )

    def _source_label(self, position: PositionDTO, source_summary: Dict[str, Any]) -> str:
        if position.source_type == "recommendation_result":
            profile_id = str(source_summary.get("profile_id") or "").strip()
            return f"推薦：{profile_id}" if profile_id else "推薦"
        if position.source_type == "backtest_run":
            strategy_id = str(source_summary.get("strategy_id") or "").strip()
            return f"回測：{strategy_id}" if strategy_id else "回測"
        if position.source_type:
            return position.source_type
        return "手動"

    def _to_decimal(self, value: Any) -> Optional[Decimal]:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    def _format_decimal(self, value: Optional[Decimal]) -> str:
        if value is None:
            return ""
        normalized = value.quantize(Decimal("0.1"))
        return format(normalized, "f")

    def _format_points(self, value: Decimal) -> str:
        if value == value.to_integral_value():
            return format(value.quantize(Decimal("1")), "f")
        return self._format_decimal(value)
