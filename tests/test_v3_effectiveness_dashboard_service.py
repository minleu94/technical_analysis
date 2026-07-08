from app_module.v3_effectiveness_dashboard_service import (
    V3EffectivenessDashboardService,
)
from app_module.v3_effectiveness_read_model import V3EffectivenessReadModel


def test_dashboard_discloses_read_only_and_sample_limitations() -> None:
    report = V3EffectivenessReadModel(min_sample_size=30).build_report(
        rows=[
            {
                "event_family": "watchlist",
                "event_type": "watchlist_trigger",
                "source_type": "daily_decision_snapshot",
                "ready_outcome_count": 4,
                "pending_outcome_count": 1,
                "missing_outcome_count": 0,
                "benchmark_coverage_bp": 10000,
                "industry_coverage_bp": 0,
                "warnings": ("sample_below_minimum",),
            }
        ]
    )

    dashboard = V3EffectivenessDashboardService().build_dashboard(report)
    payload = dashboard.to_dict()

    assert payload["access_boundary"]["writes_allowed"] is False
    assert payload["summary_cards"]["insufficient_sample_count"] == 1
    assert any("樣本不足" in item["disclosure"] for item in payload["rows"])
    assert "不是交易建議" in payload["boundary_banner"]


def test_dashboard_rows_do_not_use_trading_or_guarantee_terms() -> None:
    report = V3EffectivenessReadModel(min_sample_size=30).build_report(
        rows=[
            {
                "event_family": "portfolio_alert",
                "event_type": "portfolio_alert_triggered",
                "source_type": "daily_decision_snapshot",
                "ready_outcome_count": 80,
                "pending_outcome_count": 0,
                "missing_outcome_count": 0,
                "benchmark_coverage_bp": 10000,
                "industry_coverage_bp": 3500,
                "warnings": (),
            }
        ]
    )

    payload = V3EffectivenessDashboardService().build_dashboard(report).to_dict()
    forbidden = ("買進", "賣出", "保證", "勝率保證")
    all_text = payload["boundary_banner"] + "\n" + "\n".join(
        row["disclosure"] for row in payload["rows"]
    )
    for term in forbidden:
        assert term not in all_text
