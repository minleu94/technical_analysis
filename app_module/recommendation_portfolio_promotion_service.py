"""
推薦組合 research run 升級服務。

將已保存的 Recommendation Portfolio Backtest run 轉成 StrategyVersionService 可追蹤的策略版本。
"""

from typing import Any, Dict, Optional

from app_module.recommendation_portfolio_run_repository import (
    RecommendationPortfolioRunRepository,
)
from app_module.promotion_reconciliation_service import PromotionReconciliationService
from app_module.strategy_version_service import StrategyVersionService


class RecommendationPortfolioPromotionService:
    """管理推薦組合 research run 的策略版本升級流程。"""

    def __init__(
        self,
        run_repository: RecommendationPortfolioRunRepository,
        strategy_version_service: StrategyVersionService,
        promotion_reconciliation_service: Optional[PromotionReconciliationService] = None,
    ):
        self.run_repository = run_repository
        self.strategy_version_service = strategy_version_service
        self.promotion_reconciliation_service = promotion_reconciliation_service

    def promote_to_strategy_version(
        self,
        run_id: str,
        notes: Optional[str] = None,
    ) -> Optional[str]:
        """
        將已保存的推薦組合 run 升級為策略版本。

        Args:
            run_id: 推薦組合 research run ID
            notes: 額外備註

        Returns:
            策略版本 ID；若 run 不存在或未達最低升級條件則回傳 None。
        """
        if self.promotion_reconciliation_service is not None:
            return self.promotion_reconciliation_service.promote_registry_run(
                run_id,
                notes=notes,
            )

        run_data = self.run_repository.load_run(run_id)
        if not run_data:
            return None

        result = run_data["result_dto"]
        summary = dict(result.summary)
        if not self._passes_minimum_criteria(summary):
            return None

        config = dict(run_data.get("config", {}))
        profile_id = config.get("profile_id") or "advanced"
        strategy_id = f"recommendation_portfolio:{profile_id}"

        version_id = self.strategy_version_service.create_version(
            strategy_id=strategy_id,
            params=self._build_params(config),
            config={
                "type": "recommendation_portfolio",
                "recommendation_config": self._extract_recommendation_config(result),
                "portfolio_config": config,
                "source_run_name": run_data.get("run_name", ""),
            },
            backtest_summary=summary,
            regime=self._extract_regime(result),
            source_run_id=run_id,
            profile_id=profile_id,
            validation_status="pending",
            validation_metrics={
                "improvement_hints": result.improvement_hints,
                "stock_contribution_count": len(result.stock_contribution),
                "snapshot_count": len(result.snapshots),
            },
            notes=self._build_notes(run_data, result.improvement_hints, notes),
        )

        if version_id:
            self.run_repository.mark_as_promoted(run_id, version_id)
        return version_id

    def _passes_minimum_criteria(self, summary: Dict[str, Any]) -> bool:
        total_return = float(summary.get("total_return") or 0.0)
        total_trades = int(summary.get("total_trades") or 0)
        return total_return > 0 and total_trades > 0

    def _extract_recommendation_config(self, result) -> Dict[str, Any]:
        if not result.snapshots:
            return {}
        return dict(result.snapshots[0].strategy_config or {})

    def _extract_regime(self, result) -> list[str]:
        regimes = []
        for snapshot in result.snapshots:
            regime = getattr(snapshot, "regime", "")
            if regime and regime not in regimes:
                regimes.append(regime)
        return regimes

    def _build_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "rebalance_frequency",
            "top_n",
            "allocation_method",
            "holding_days",
            "stop_loss_pct",
            "take_profit_pct",
        ]
        return {key: config.get(key) for key in keys}

    def _build_notes(self, run_data, hints, extra_notes: Optional[str]) -> str:
        lines = []
        run_name = run_data.get("run_name")
        if run_name:
            lines.append(f"來源推薦組合 run: {run_name}")
        existing_notes = run_data.get("notes")
        if existing_notes:
            lines.append(f"Run 備註: {existing_notes}")
        if hints:
            lines.append("改善建議:")
            lines.extend(f"- {hint}" for hint in hints)
        if extra_notes:
            lines.append(f"Promote 備註: {extra_notes}")
        return "\n".join(lines)
