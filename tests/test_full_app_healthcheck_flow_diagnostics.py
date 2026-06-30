from __future__ import annotations

from qa.full_app_healthcheck.flow_diagnostics import (
    FlowDiagnostic,
    FlowDiagnosticDetail,
    FlowDiagnosticsReport,
    generate_flow_diagnostics,
    render_flow_diagnostics_markdown,
)


def test_flow_diagnostics_generation():
    report = generate_flow_diagnostics()
    assert isinstance(report, FlowDiagnosticsReport)
    assert len(report.diagnostics) == 4
    assert report.items == report.diagnostics
    assert "4 closed-loop flows" in report.summary

    details_by_id = {item.flow_id: item for item in report.diagnostics}

    data_market = details_by_id["data_market_loop"]
    assert isinstance(data_market, FlowDiagnostic)
    assert isinstance(data_market, FlowDiagnosticDetail)
    assert data_market.coverage_status == "full_or_manual_required"
    assert data_market.likely_owner == "data_audit"
    assert data_market.handoff_owner == data_market.likely_owner
    assert data_market.ordered_feature_ids == ("update_view", "market_regime", "smart_money")
    assert any("run_full_app_healthcheck.py --mode full" in cmd for cmd in data_market.recommended_commands)
    assert len(data_market.ux_gaps) > 0

    portfolio = details_by_id["portfolio_review_loop"]
    assert portfolio.coverage_status == "full_or_manual_required"
    assert "tests/test_ui_qt_portfolio_view.py" in portfolio.evidence_sources
    assert any("Portfolio view has direct bridge evidence" in gap for gap in portfolio.manual_gaps)

    daily_decision = details_by_id["daily_decision_loop"]
    assert daily_decision.coverage_status == "full_or_manual_required"
    assert daily_decision.next_steps[-1].startswith("若 freshness 不足")


def test_quick_ineligible_flows_are_not_reported_as_failed():
    report = generate_flow_diagnostics()
    statuses = {item.flow_id: item.coverage_status for item in report.diagnostics}

    assert statuses["research_validation_loop"] == "full_or_manual_required"
    assert statuses["daily_decision_loop"] == "full_or_manual_required"
    assert "failed" not in set(statuses.values())
    assert "gapped" not in set(statuses.values())


def test_service_oracles_are_evidence_only_in_markdown():
    markdown = render_flow_diagnostics_markdown(generate_flow_diagnostics())

    assert "tests/test_update_service_status.py` evidence-only" in markdown
    assert "tests/test_decision_desk_service.py` evidence-only" in markdown
    assert "Service oracle" not in "\n".join(
        line for line in markdown.splitlines() if line.startswith("|")
    )


def test_flow_diagnostics_markdown_renderer():
    markdown = render_flow_diagnostics_markdown(generate_flow_diagnostics())

    assert "Closed-loop Flow Diagnostics Report" in markdown
    assert "data_market_loop" in markdown
    assert "portfolio_review_loop" in markdown
    assert "**Coverage Status**: `full_or_manual_required`" in markdown
    assert "**Handoff Owner**: `data_audit`" in markdown
    assert "Recommended Commands" in markdown
    assert "pytest tests/test_ui_qt_smart_money_flow_view.py" in markdown
    assert "UX Gaps" in markdown
    assert "TWSE/TPEX real API fetch progress bar indication" in markdown
