from __future__ import annotations

import os
import sys
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.advice_dtos import (
    AdviceAction,
    AdviceClassification,
    AdviceDashboardDTO,
    AdviceMode,
    AdvicePolicyConfig,
    PortfolioAdviceDTO,
    RecommendationAdviceDTO,
)
from app_module.workbench_dtos import WorkbenchAccessBoundary, WorkbenchDashboardDTO
from ui_qt.views.workbench_view import UnifiedDecisionWorkbenchView


def _app() -> QApplication:
    instance = QApplication.instance()
    if isinstance(instance, QApplication):
        return instance
    return QApplication(sys.argv)


def _dashboard_with_advice() -> WorkbenchDashboardDTO:
    advice = AdviceDashboardDTO(
        decision_date="2026-07-12",
        data_as_of_date="2026-07-11",
        mode=AdviceMode.GUIDED,
        policy=AdvicePolicyConfig(),
        recommendations=(
            RecommendationAdviceDTO(
                stock_code="2330",
                advice_action=AdviceAction.NO_NEW_POSITION,
                why_not_reasons=("guided_mode_strategy_not_promoted",),
                data_quality="DEGRADED",
                execution_feasibility="NOT_FEASIBLE",
            ),
        ),
        portfolio_rows=(
            PortfolioAdviceDTO(
                stock_code="2330",
                advice_action=AdviceAction.NO_NEW_POSITION,
                target_weight_bp=0,
                current_weight_bp=1200,
                weight_gap_bp=-1200,
                reasons=("risk_budget_unavailable",),
                data_quality="DEGRADED",
                execution_feasibility="NOT_FEASIBLE",
            ),
        ),
        warnings=("evidence_degraded",),
    )
    return WorkbenchDashboardDTO(
        as_of_date=date(2026, 7, 12),
        generated_at=datetime(2026, 7, 12, 12, 0, 0),
        source_mode="read_only",
        access_boundary=WorkbenchAccessBoundary(),
        status_strip=(),
        review_items=(),
        evidence_summary=(),
        market_context={},
        portfolio_watchlist_summary={},
        daily_checklist=(),
        advice_dashboard=advice,
    )


def test_workbench_renders_advice_dto_without_policy_execution() -> None:
    _app()

    view = UnifiedDecisionWorkbenchView(dashboard=_dashboard_with_advice(), auto_refresh=False)

    assert "NO_NEW_POSITION" in view.advice_summary.text()
    assert "guided_mode_strategy_not_promoted" in view.advice_summary.text()
    assert "DEGRADED" in view.advice_summary.text()
    assert "NOT_FEASIBLE" in view.advice_summary.text()
    assert "Advice 僅呈現已注入 DTO、不執行 Policy" in view.boundary_banner.text()
    assert view.advice_portfolio_model.rowCount() == 1
    assert view.advice_portfolio_model.data(
        view.advice_portfolio_model.index(0, view.advice_portfolio_model.column_index("target_weight_bp"))
    ) == "0"


def test_workbench_separates_professional_candidates_from_formal_advice() -> None:
    _app()
    dashboard = _dashboard_with_advice()
    professional_advice = AdviceDashboardDTO(
        decision_date=dashboard.advice_dashboard.decision_date,
        data_as_of_date=dashboard.advice_dashboard.data_as_of_date,
        mode=AdviceMode.PROFESSIONAL,
        policy=AdvicePolicyConfig(mode=AdviceMode.PROFESSIONAL),
        recommendations=(
            RecommendationAdviceDTO(
                stock_code="2330",
                advice_action=AdviceAction.RESEARCH,
                classification=AdviceClassification.PROFESSIONAL_CANDIDATE,
            ),
        ),
    )
    candidate_dashboard = WorkbenchDashboardDTO(
        as_of_date=dashboard.as_of_date,
        generated_at=dashboard.generated_at,
        source_mode=dashboard.source_mode,
        access_boundary=dashboard.access_boundary,
        status_strip=dashboard.status_strip,
        review_items=dashboard.review_items,
        evidence_summary=dashboard.evidence_summary,
        market_context=dashboard.market_context,
        portfolio_watchlist_summary=dashboard.portfolio_watchlist_summary,
        daily_checklist=dashboard.daily_checklist,
        advice_dashboard=professional_advice,
    )

    view = UnifiedDecisionWorkbenchView(dashboard=candidate_dashboard, auto_refresh=False)

    assert view.advice_recommendation_model.rowCount() == 0
    assert view.advice_candidate_model.rowCount() == 1
    assert "正式 Advice 0 筆" in view.advice_summary.text()
    assert "Professional 研究候選 1 筆" in view.advice_summary.text()
