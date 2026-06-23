from __future__ import annotations

from dataclasses import dataclass

from app_module.decision_desk_dtos import (
    DecisionDeskActionSummary,
    DecisionDeskQuality,
    DecisionDeskSectorCard,
    DecisionDeskSectorFocus,
    DecisionDeskStockCard,
    DecisionDeskStockFocus,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)


RESEARCH_MODE_NOTE = "研究模式：以下為市場與籌碼輔助判讀，不是交易建議。"


@dataclass(frozen=True)
class DecisionDeskDashboard:
    action_summary: DecisionDeskActionSummary
    sector_focus: DecisionDeskSectorFocus
    stock_focus: DecisionDeskStockFocus


class DecisionDeskDashboardComposer:
    """Compose answer-first Daily Decision dashboard DTOs from section snapshots."""

    def compose(
        self,
        *,
        market_regime: MarketRegimeSummary,
        market_breadth: MarketBreadthSummary,
        sector_rotation: SectorRotationSummary,
        relative_strength_liquidity: RelativeStrengthLiquiditySummary,
        watchlist_triggers: WatchlistTriggerSummary,
        portfolio_alerts: PortfolioAlertSummary,
        smart_money_summary=None,
    ) -> DecisionDeskDashboard:
        return DecisionDeskDashboard(
            action_summary=self._compose_action(market_regime, market_breadth),
            sector_focus=self._compose_sector_focus(sector_rotation),
            stock_focus=self._compose_stock_focus(
                relative_strength_liquidity=relative_strength_liquidity,
                watchlist_triggers=watchlist_triggers,
                portfolio_alerts=portfolio_alerts,
                smart_money_summary=smart_money_summary,
            ),
        )

    def _compose_action(
        self,
        market_regime: MarketRegimeSummary,
        market_breadth: MarketBreadthSummary,
    ) -> DecisionDeskActionSummary:
        reasons: list[str] = []
        warnings: list[str] = []
        if market_regime.quality in {DecisionDeskQuality.MISSING, DecisionDeskQuality.DEGRADED}:
            warnings.append(f"market_regime_quality:{market_regime.quality.value}")
        if market_breadth.quality in {DecisionDeskQuality.MISSING, DecisionDeskQuality.DEGRADED}:
            warnings.append(f"market_breadth_quality:{market_breadth.quality.value}")

        breadth_bp = market_breadth.breadth_ratio_bp
        confidence_bp = market_regime.regime_confidence
        regime_label = market_regime.regime_label or "市場狀態未定義"
        reasons.append(f"市場狀態：{regime_label}")
        if breadth_bp is not None:
            reasons.append(f"廣度比率：{breadth_bp} bp")
        if confidence_bp is not None:
            reasons.append(f"Regime confidence：{confidence_bp} bp")

        action_level = self._action_level(market_regime, market_breadth)
        headline = f"今日主結論：{action_level}，{self._headline_reason(action_level, breadth_bp, regime_label)}"
        return DecisionDeskActionSummary(
            action_level=action_level,
            headline=headline,
            research_mode_note=RESEARCH_MODE_NOTE,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _action_level(
        market_regime: MarketRegimeSummary,
        market_breadth: MarketBreadthSummary,
    ) -> str:
        if market_regime.quality == DecisionDeskQuality.MISSING or market_breadth.quality == DecisionDeskQuality.MISSING:
            return "保守觀察"
        if market_regime.quality == DecisionDeskQuality.DEGRADED or market_breadth.quality == DecisionDeskQuality.DEGRADED:
            return "保守觀察"

        breadth_bp = market_breadth.breadth_ratio_bp
        confidence_bp = market_regime.regime_confidence
        label = (market_regime.regime_label or "").lower()
        risk_off = any(token in label for token in ("risk-off", "bear", "空", "弱"))

        if breadth_bp is None:
            return "保守觀察"
        if risk_off and breadth_bp < 4000:
            return "暫停新進場"
        if breadth_bp >= 5500 and (confidence_bp is None or confidence_bp >= 7000) and not risk_off:
            return "積極研究"
        if breadth_bp >= 4500 and not risk_off:
            return "正常研究"
        if breadth_bp >= 3500:
            return "保守觀察"
        return "暫停新進場"

    @staticmethod
    def _headline_reason(action_level: str, breadth_bp: int | None, regime_label: str) -> str:
        if action_level == "積極研究":
            return f"{regime_label} 且市場廣度偏強，優先尋找可研究標的"
        if action_level == "正常研究":
            return f"{regime_label}，維持一般研究節奏並留意品質"
        if action_level == "暫停新進場":
            return f"{regime_label} 且廣度偏弱，先處理風險與等待確認"
        if breadth_bp is None:
            return "關鍵市場廣度不足，先降低判讀強度"
        return f"{regime_label}，市場條件尚未明確轉強"

    @staticmethod
    def _compose_sector_focus(sector_rotation: SectorRotationSummary) -> DecisionDeskSectorFocus:
        priority: list[DecisionDeskSectorCard] = []
        risk: list[DecisionDeskSectorCard] = []
        if sector_rotation.leading_sector:
            priority.append(
                DecisionDeskSectorCard(
                    sector_name=sector_rotation.leading_sector,
                    role="priority",
                    reason="產業輪動領先",
                    quality=sector_rotation.quality,
                    target_tab="強勢產業",
                )
            )
        if sector_rotation.trailing_sector:
            risk.append(
                DecisionDeskSectorCard(
                    sector_name=sector_rotation.trailing_sector,
                    role="risk",
                    reason="產業輪動落後",
                    quality=sector_rotation.quality,
                    target_tab="弱勢產業",
                )
            )
        return DecisionDeskSectorFocus(priority_sectors=tuple(priority), risk_sectors=tuple(risk))

    @staticmethod
    def _compose_stock_focus(
        *,
        relative_strength_liquidity: RelativeStrengthLiquiditySummary,
        watchlist_triggers: WatchlistTriggerSummary,
        portfolio_alerts: PortfolioAlertSummary,
        smart_money_summary=None,
    ) -> DecisionDeskStockFocus:
        priority: list[DecisionDeskStockCard] = []
        risk: list[DecisionDeskStockCard] = []
        seen_priority: set[str] = set()
        seen_risk: set[str] = set()

        for code in relative_strength_liquidity.top_strength_codes[:5]:
            text = str(code)
            if text and text not in seen_priority:
                seen_priority.add(text)
                priority.append(
                    DecisionDeskStockCard(
                        stock_code=text,
                        stock_name=text,
                        role="priority",
                        reason="相對強勢名單",
                        source="relative_strength",
                        quality=relative_strength_liquidity.quality,
                    )
                )

        if smart_money_summary is not None:
            for item in getattr(smart_money_summary, "priority_summaries", ())[:5]:
                text = str(getattr(item, "stock_code", ""))
                if text and text not in seen_priority:
                    seen_priority.add(text)
                    priority.append(
                        DecisionDeskStockCard(
                            stock_code=text,
                            stock_name=str(getattr(item, "stock_name", text)),
                            role="priority",
                            reason=f"主力流向：{getattr(item, 'primary_state', '語意訊號')}",
                            source="smart_money",
                            quality=DecisionDeskQuality.OBSERVED
                            if getattr(item, "quality", "observed") == "observed"
                            else DecisionDeskQuality.DEGRADED,
                        )
                    )
            for item in getattr(smart_money_summary, "risk_summaries", ())[:5]:
                text = str(getattr(item, "stock_code", ""))
                if text and text not in seen_risk:
                    flags = tuple(getattr(item, "semantic_flags", ()) or ())
                    flag_text = "、".join(flags) if flags else getattr(item, "primary_state", "語意風險")
                    seen_risk.add(text)
                    risk.append(
                        DecisionDeskStockCard(
                            stock_code=text,
                            stock_name=str(getattr(item, "stock_name", text)),
                            role="risk",
                            reason=f"主力流向：{flag_text}",
                            source="smart_money",
                            quality=DecisionDeskQuality.OBSERVED
                            if getattr(item, "quality", "observed") == "observed"
                            else DecisionDeskQuality.DEGRADED,
                        )
                    )

        for code in tuple(portfolio_alerts.alert_codes) + tuple(watchlist_triggers.triggered_codes):
            text = str(code)
            if text and text not in seen_risk:
                seen_risk.add(text)
                risk.append(
                    DecisionDeskStockCard(
                        stock_code=text,
                        stock_name=text,
                        role="risk",
                        reason="持倉或觀察清單風險提示",
                        source="portfolio_watchlist",
                        quality=DecisionDeskQuality.DEGRADED
                        if portfolio_alerts.quality == DecisionDeskQuality.DEGRADED
                        or watchlist_triggers.quality == DecisionDeskQuality.DEGRADED
                        else DecisionDeskQuality.OBSERVED,
                    )
                )

        for code in tuple(relative_strength_liquidity.weak_strength_codes) + tuple(
            relative_strength_liquidity.low_liquidity_codes
        ):
            text = str(code)
            if text and text not in seen_risk:
                seen_risk.add(text)
                risk.append(
                    DecisionDeskStockCard(
                        stock_code=text,
                        stock_name=text,
                        role="risk",
                        reason="弱勢或低流動性",
                        source="relative_strength_liquidity",
                        quality=relative_strength_liquidity.quality,
                    )
                )

        return DecisionDeskStockFocus(priority_stocks=tuple(priority[:5]), risk_stocks=tuple(risk[:5]))
