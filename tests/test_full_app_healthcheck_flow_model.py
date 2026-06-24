from __future__ import annotations

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.flow_model import (
    ClosedLoopFlow,
    FlowModelReport,
    FlowStep,
    generate_flow_model_report,
    get_all_flows,
    get_flow,
    render_flow_model_markdown,
)
from qa.full_app_healthcheck.test_inventory import get_category


def test_get_all_flows_returns_four_structured_flows():
    flows = get_all_flows()
    assert len(flows) == 4

    flow_ids = {flow.flow_id for flow in flows}
    assert flow_ids == {
        "data_market_loop",
        "research_validation_loop",
        "portfolio_review_loop",
        "daily_decision_loop",
    }

    for flow in flows:
        assert isinstance(flow, ClosedLoopFlow)
        assert flow.flow_id
        assert flow.display_name
        assert flow.entrypoint
        assert flow.steps
        assert flow.ordered_feature_ids
        assert flow.evidence_sources
        assert flow.expected_next_step
        assert flow.manual_gaps
        assert flow.safety_notes
        for step in flow.steps:
            assert isinstance(step, FlowStep)
            assert step.feature_id in FEATURE_ROUTES
            assert step.purpose
            assert step.evidence_sources
            assert step.expected_next_step


def test_get_flow_by_id():
    flow = get_flow("data_market_loop")
    assert flow is not None
    assert flow.flow_id == "data_market_loop"
    assert flow.ordered_feature_ids == ("update_view", "market_regime", "smart_money")

    assert get_flow("non_existent_flow") is None


def test_required_closed_loop_feature_order():
    assert get_flow("research_validation_loop").ordered_feature_ids == (
        "research_lab",
        "registry_compare",
    )
    assert get_flow("portfolio_review_loop").ordered_feature_ids == (
        "smart_money",
        "smart_money",
        "decision_desk",
    )
    assert get_flow("daily_decision_loop").ordered_feature_ids == (
        "decision_desk",
        "market_regime",
        "update_view",
    )


def test_service_oracles_are_evidence_not_flow_steps():
    for flow in get_all_flows():
        step_ids_and_purposes = " ".join(
            [step.step_id for step in flow.steps] + [step.purpose for step in flow.steps]
        )
        for source in flow.evidence_sources:
            category = get_category(source)
            if category and category.startswith("service-oracle-"):
                source_name = source.split("/")[-1]
                assert source not in step_ids_and_purposes
                assert source_name not in step_ids_and_purposes


def test_flow_model_report_and_markdown_renderer():
    report = generate_flow_model_report()
    assert isinstance(report, FlowModelReport)
    assert "4 closed-loop flows" in report.summary
    assert "ordered feature steps" in report.summary
    assert "manual or UX gaps tracked" in report.summary

    markdown = render_flow_model_markdown(report)
    assert "Full App Healthcheck Closed-loop Flow Model" in markdown
    assert "Service oracle tests are evidence only" in markdown
    assert "data_market_loop" in markdown
    assert "research_validation_loop" in markdown
    assert "portfolio_review_loop" in markdown
    assert "daily_decision_loop" in markdown
    assert "TWSE/TPEX real API fetch progress bar indication" in markdown
    assert "Recommendation / portfolio handoff route is not a first-class feature route yet." in markdown
    assert "data update and cache status evidence" in markdown
