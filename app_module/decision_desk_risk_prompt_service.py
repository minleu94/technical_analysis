from __future__ import annotations

from datetime import date

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskRiskPrompt,
    DecisionDeskRiskPromptSummary,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    RelativeStrengthLiquiditySummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)


class DecisionDeskRiskPromptService:
    """Derive actionable risk prompts from existing Daily Decision Desk sections."""

    def build_summary(
        self,
        *,
        as_of_date: date,
        market_regime: MarketRegimeSummary,
        market_breadth: MarketBreadthSummary,
        sector_rotation: SectorRotationSummary,
        relative_strength_liquidity: RelativeStrengthLiquiditySummary,
        watchlist_triggers: WatchlistTriggerSummary,
        portfolio_alerts: PortfolioAlertSummary,
    ) -> DecisionDeskRiskPromptSummary:
        prompts: list[DecisionDeskRiskPrompt] = []
        warnings: list[str] = []

        sections = (
            ("market_regime", market_regime),
            ("market_breadth", market_breadth),
            ("sector_rotation", sector_rotation),
            ("relative_strength_liquidity", relative_strength_liquidity),
            ("watchlist_triggers", watchlist_triggers),
            ("portfolio_alerts", portfolio_alerts),
        )
        for section_name, section in sections:
            if section.quality != DecisionDeskQuality.OBSERVED:
                warnings.append(f"risk_prompt_source_quality:{section_name}:{section.quality.value}")

        prompts.extend(self._market_context_prompts(market_regime))
        prompts.extend(self._relative_strength_prompts(relative_strength_liquidity))
        prompts.extend(self._watchlist_prompts(watchlist_triggers))
        prompts.extend(self._portfolio_prompts(portfolio_alerts))

        prompts = self._dedupe(prompts)
        if not prompts:
            # 如果沒有任何警告，但是有品質缺失 (MISSING 等)，我們還是要回傳 quality 及 warnings 
            # 依照 quality 規則：
            # - MISSING if all source sections are missing and no prompt can be derived.
            # 這裡因為 dedupe 後 prompts 為空，我們先確認是不是全部都是 MISSING，或是其他情況。
            # 如果 all sections 都是 MISSING，那我們回傳 MISSING 並在 warnings 寫 "risk_prompt_missing"
            all_missing = all(section.quality == DecisionDeskQuality.MISSING for _, section in sections)
            quality = DecisionDeskQuality.MISSING if all_missing else (DecisionDeskQuality.DEGRADED if warnings else DecisionDeskQuality.OBSERVED)
            
            # 如果 all_missing, warning 就包含 "risk_prompt_missing"
            # 如果非 all_missing 但 prompts 為空，說明沒有訊號，那這也是 observed / degraded 的正常狀態
            return DecisionDeskRiskPromptSummary(
                as_of_date=as_of_date,
                quality=quality,
                warnings=tuple(warnings) if not all_missing else ("risk_prompt_missing",),
                prompts=(),
            )

        quality = DecisionDeskQuality.OBSERVED if not warnings else DecisionDeskQuality.DEGRADED
        return DecisionDeskRiskPromptSummary(
            as_of_date=as_of_date,
            quality=quality,
            warnings=tuple(dict.fromkeys(warnings)),
            prompts=tuple(prompts),
        )

    @staticmethod
    def _market_context_prompts(section: MarketRegimeSummary) -> list[DecisionDeskRiskPrompt]:
        label = (section.regime_label or "").lower()
        if "risk-off" not in label and "bear" not in label and "空" not in label:
            return []
        return [
            DecisionDeskRiskPrompt(
                category="market_context",
                severity="warning",
                source="market_regime",
                code=None,
                title="市場風險偏高",
                reason=f"Market Regime 顯示 {section.regime_label}",
                action_hint="降低解讀強勢股的確定性，先檢查大盤與產業是否同步支持。",
            )
        ]

    @staticmethod
    def _relative_strength_prompts(section: RelativeStrengthLiquiditySummary) -> list[DecisionDeskRiskPrompt]:
        prompts: list[DecisionDeskRiskPrompt] = []
        for code in section.low_liquidity_codes:
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="liquidity",
                    severity="warning",
                    source="relative_strength_liquidity",
                    code=code,
                    title="低流動性",
                    reason=f"{code} 被 Relative Strength / Liquidity Ranking 標記為低流動性。",
                    action_hint="加入研究或下單前檢查平均成交金額、部位大小與可成交性。",
                )
            )
        for code in section.weak_strength_codes:
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="weakness",
                    severity="info",
                    source="relative_strength_liquidity",
                    code=code,
                    title="相對弱勢",
                    reason=f"{code} 位於 20 日相對弱勢清單。",
                    action_hint="避免只因短線反彈納入候選，先確認反轉條件或基本面催化。",
                )
            )
        return prompts

    @staticmethod
    def _watchlist_prompts(section: WatchlistTriggerSummary) -> list[DecisionDeskRiskPrompt]:
        prompts: list[DecisionDeskRiskPrompt] = []
        for warning in section.warnings:
            prefix = "watchlist_trigger_risk_alert:"
            if not warning.startswith(prefix):
                continue
            code = warning.removeprefix(prefix)
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="watchlist_risk",
                    severity="warning",
                    source="watchlist_triggers",
                    code=code,
                    title="觀察清單風險觸發",
                    reason=f"{code} 觸發 Watchlist risk_alert。",
                    action_hint="查看 RSI、布林通道與近期量價變化，不把觸發視為自動買賣訊號。",
                )
            )
        return prompts

    @staticmethod
    def _portfolio_prompts(section: PortfolioAlertSummary) -> list[DecisionDeskRiskPrompt]:
        prompts: list[DecisionDeskRiskPrompt] = []
        severity = "critical" if section.alert_level in {"high", "critical", "extreme"} else "warning"
        
        attribution_by_code = {item.stock_code: item for item in getattr(section, "attributions", ())}
        
        for code in section.alert_codes:
            attribution = attribution_by_code.get(code)
            if attribution is not None:
                reason = (
                    f"{code} 出現在 Portfolio Alert 清單；來源 {attribution.source_label}；"
                    f"condition={attribution.condition_status}；chip={attribution.chip_risk_level}；"
                    f"reasons={', '.join(attribution.reasons) if attribution.reasons else '無'}。"
                )
            else:
                reason = f"{code} 出現在 Portfolio Alert 清單。"
            
            prompts.append(
                DecisionDeskRiskPrompt(
                    category="portfolio_alert",
                    severity=severity,
                    source="portfolio_alerts",
                    code=code,
                    title="持倉警示",
                    reason=reason,
                    action_hint="檢查條件監控、籌碼摘要與持倉風險，不直接自動調整部位。",
                )
            )
        return prompts


    @staticmethod
    def _dedupe(prompts: list[DecisionDeskRiskPrompt]) -> list[DecisionDeskRiskPrompt]:
        seen: set[tuple[str, str | None, str]] = set()
        result: list[DecisionDeskRiskPrompt] = []
        for prompt in prompts:
            key = (prompt.category, prompt.code, prompt.source)
            if key in seen:
                continue
            seen.add(key)
            result.append(prompt)
        return result
