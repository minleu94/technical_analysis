from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.flow_model import FLOWS


ALLOWED_UX_GAP_CATEGORIES = frozenset(
    {"unclear_copy", "missing_entrypoint", "layout_occlusion", "unclear_next_step"}
)


@dataclass(frozen=True)
class KnownUXGap:
    gap_id: str
    category: str  # 'unclear_copy', 'missing_entrypoint', 'layout_occlusion', 'unclear_next_step'
    title: str
    feature_id: str
    flow_id: str | None
    likely_owner: str
    evidence_sources: tuple[str, ...]
    recommended_next_step: str

    def __post_init__(self) -> None:
        if self.category not in ALLOWED_UX_GAP_CATEGORIES:
            raise ValueError(
                f"Invalid category '{self.category}' for KnownUXGap '{self.gap_id}'. "
                f"Allowed: {sorted(ALLOWED_UX_GAP_CATEGORIES)}"
            )
        if self.feature_id not in FEATURE_ROUTES:
            raise ValueError(f"Unknown feature_id '{self.feature_id}' for KnownUXGap '{self.gap_id}'.")
        if self.flow_id is not None and self.flow_id not in FLOWS:
            raise ValueError(f"Unknown flow_id '{self.flow_id}' for KnownUXGap '{self.gap_id}'.")


KNOWN_UX_GAPS: tuple[KnownUXGap, ...] = (
    KnownUXGap(
        gap_id="ux_gap_update_view_progress_bar",
        category="unclear_copy",
        title="TWSE/TPEX real API fetch progress bar indication",
        feature_id="update_view",
        flow_id="data_market_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_update_service_status.py",),
        recommended_next_step="Implement explicit progress bar widget for Twstock daily fetch.",
    ),
    KnownUXGap(
        gap_id="ux_gap_update_view_confirm_dialog",
        category="unclear_next_step",
        title="Confirm dialog on SQLite daily prices sync",
        feature_id="update_view",
        flow_id="daily_decision_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_update_service_status.py",),
        recommended_next_step="Add visual confirmation dialog when SQLite sync completes.",
    ),
    KnownUXGap(
        gap_id="ux_gap_decision_desk_why_not_readability",
        category="unclear_copy",
        title="Clicking Why Not button popup readability",
        feature_id="decision_desk",
        flow_id="portfolio_review_loop",
        likely_owner="execution",
        evidence_sources=(
            "tests/test_decision_desk_service.py",
            "tests/test_decision_desk_ui_contract.py",
        ),
        recommended_next_step="Improve font sizing and contrast in 'Why Not' popup explanation.",
    ),
    KnownUXGap(
        gap_id="ux_gap_decision_desk_warning_layout",
        category="layout_occlusion",
        title="Visual layout of warning flags under degraded data status",
        feature_id="decision_desk",
        flow_id="portfolio_review_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_decision_desk_dashboard_service.py",),
        recommended_next_step="Fix layout clipping of warning flags under degraded resolution.",
    ),
    KnownUXGap(
        gap_id="ux_gap_research_lab_slider_resize",
        category="layout_occlusion",
        title="Custom parameter slider UI layout resize check",
        feature_id="research_lab",
        flow_id="research_validation_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_ui_qt_research_lab_mode_driven_ui.py",),
        recommended_next_step="Ensure slider controls scale cleanly when resizing Research Lab widget.",
    ),
    KnownUXGap(
        gap_id="ux_gap_research_lab_zoom",
        category="unclear_next_step",
        title="Equity curve zoom interaction",
        feature_id="research_lab",
        flow_id="research_validation_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_ui_qt_research_run_save.py",),
        recommended_next_step="Add visual instructions or tooltip for equity chart zoom-in/out gestures.",
    ),
    KnownUXGap(
        gap_id="ux_gap_market_regime_tooltip",
        category="unclear_copy",
        title="Regime rule match tooltip verification",
        feature_id="market_regime",
        flow_id="data_market_loop",
        likely_owner="testing_qa",
        evidence_sources=("tests/test_walkforward_service.py",),
        recommended_next_step="Verify tooltip text content against regime guidelines.",
    ),
    KnownUXGap(
        gap_id="ux_gap_market_regime_geometry",
        category="layout_occlusion",
        title="Regime breakdown dropdown geometry details",
        feature_id="market_regime",
        flow_id="daily_decision_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_walkforward_service.py",),
        recommended_next_step="Check dropdown height and scrolling limits on lower display bounds.",
    ),
    KnownUXGap(
        gap_id="ux_gap_smart_money_drill_down",
        category="missing_entrypoint",
        title="Drill-down connection to portfolio/stock highlight",
        feature_id="smart_money",
        flow_id="data_market_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_smart_money_semantic_service.py",),
        recommended_next_step="Add context menu to open specific stock from Smart Money view.",
    ),
    KnownUXGap(
        gap_id="ux_gap_smart_money_sorting",
        category="unclear_next_step",
        title="Multi-day broker flow sorting",
        feature_id="smart_money",
        flow_id="portfolio_review_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_broker_flow_units.py",),
        recommended_next_step="Provide sorting indicators for multiday broker transaction lists.",
    ),
    KnownUXGap(
        gap_id="ux_gap_registry_compare_alignment",
        category="layout_occlusion",
        title="Cross-run parameters horizontal table alignment",
        feature_id="registry_compare",
        flow_id="research_validation_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_research_run_comparison_service.py",),
        recommended_next_step="Fix horizontal alignment of parameter header rows in comparisons.",
    ),
    KnownUXGap(
        gap_id="ux_gap_registry_compare_canvas",
        category="layout_occlusion",
        title="Normalized equity curve canvas rendering",
        feature_id="registry_compare",
        flow_id="research_validation_loop",
        likely_owner="execution",
        evidence_sources=("tests/test_research_run_comparison_service.py",),
        recommended_next_step="Validate canvas boundary sizes on standard Qt DPI scaling.",
    ),
    KnownUXGap(
        gap_id="ux_gap_portfolio_view_candidate",
        category="missing_entrypoint",
        title="Portfolio view is still candidate bridge, not direct healthcheck flow.",
        feature_id="smart_money",
        flow_id="portfolio_review_loop",
        likely_owner="testing_qa",
        evidence_sources=("tests/test_ui_qt_portfolio_view.py",),
        recommended_next_step="Promote portfolio view candidate bridge to direct healthcheck.",
    ),
    KnownUXGap(
        gap_id="ux_gap_watchlist_pool_candidate",
        category="missing_entrypoint",
        title="Watchlist candidate pool is still candidate bridge, not direct healthcheck flow.",
        feature_id="smart_money",
        flow_id="portfolio_review_loop",
        likely_owner="testing_qa",
        evidence_sources=("tests/test_ui_qt_watchlist_candidate_pool_copy_text.py",),
        recommended_next_step="Promote watchlist candidate pool to direct healthcheck.",
    ),
)


def get_all_ux_gaps() -> tuple[KnownUXGap, ...]:
    """取得所有內建的 KnownUXGap。"""
    return KNOWN_UX_GAPS


def get_ux_gaps_for_feature(feature_id: str) -> tuple[KnownUXGap, ...]:
    """取得特定 feature_id 的所有 KnownUXGap。"""
    return tuple(gap for gap in KNOWN_UX_GAPS if gap.feature_id == feature_id)


def get_ux_gaps_for_flow(flow_id: str) -> tuple[KnownUXGap, ...]:
    """取得特定 flow_id 的所有 KnownUXGap。"""
    return tuple(gap for gap in KNOWN_UX_GAPS if gap.flow_id == flow_id)


def render_ux_gap_mapping_markdown(gaps: Sequence[KnownUXGap]) -> str:
    """將 KnownUXGap 列表渲染成 Markdown。"""
    if not gaps:
        return "- (None)"

    lines = []
    for gap in gaps:
        flow_info = f", Flow: `{gap.flow_id}`" if gap.flow_id else ""
        lines.append(
            f"- `[{gap.category}]` {gap.title} (Feature: `{gap.feature_id}`"
            f"{flow_info}, Owner: `{gap.likely_owner}`)\n"
            f"  - **Recommended Next Step**: {gap.recommended_next_step}"
        )
    return "\n".join(lines)
