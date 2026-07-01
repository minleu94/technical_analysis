from __future__ import annotations

from app_module.forward_performance_read_model import (
    ForwardPerformanceFilter,
    ForwardPerformanceGroupSummary,
    SUMMARY_STATUS_INSUFFICIENT_SAMPLE,
    SUMMARY_STATUS_MISSING_BENCHMARK,
    SUMMARY_STATUS_MISSING_INDUSTRY,
    SUMMARY_STATUS_READY,
)
from app_module.forward_performance_dashboard_dtos import ForwardPerformanceDashboardRequest
from app_module.forward_performance_dashboard_service import (
    ForwardPerformanceDashboardService,
    format_bp_as_percent,
)


class FakeReadModel:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def summarize(
        self,
        *,
        group_by: str = "event_type",
        filters: ForwardPerformanceFilter | None = None,
        min_sample_size: int = 1,
    ):
        self.calls.append(
            {
                "group_by": group_by,
                "filters": filters,
                "min_sample_size": min_sample_size,
            }
        )
        return list(self.rows)


def _summary(
    group_key: str,
    *,
    group_by: str = "event_type",
    window_days: int = 20,
    sample_size: int = 12,
    pending_count: int = 1,
    missing_count: int = 2,
    status: str = SUMMARY_STATUS_READY,
    warning_counts: dict[str, int] | None = None,
    quality_counts: dict[str, int] | None = None,
) -> ForwardPerformanceGroupSummary:
    return ForwardPerformanceGroupSummary(
        group_by=group_by,
        group_key=group_key,
        window_days=window_days,
        sample_size=sample_size,
        pending_count=pending_count,
        missing_count=missing_count,
        mean_forward_return_bp=123,
        median_forward_return_bp=100,
        mean_benchmark_excess_bp=45,
        median_benchmark_excess_bp=40,
        mean_industry_excess_bp=20,
        median_industry_excess_bp=10,
        positive_rate_bp=6500,
        win_vs_benchmark_rate_bp=5400,
        win_vs_industry_rate_bp=5100,
        mean_mae_bp=-80,
        mean_mfe_bp=210,
        quality_counts=quality_counts or {"observed": sample_size},
        warning_counts=warning_counts or {},
        first_event_date="2026-07-01",
        last_event_date="2026-07-10",
        summary_status=status,
    )


def test_dashboard_service_maps_filters_and_defaults() -> None:
    read_model = FakeReadModel([_summary("recommendation_included")])
    service = ForwardPerformanceDashboardService(read_model)

    result = service.load_dashboard(ForwardPerformanceDashboardRequest(symbol="2330"))

    call = read_model.calls[0]
    assert call["group_by"] == "event_type"
    assert call["min_sample_size"] == 10
    assert call["filters"] == ForwardPerformanceFilter(symbol="2330", window_days=20)
    assert result.request.window_days == 20
    assert result.request.min_sample_size == 10
    assert result.cards.ready_outcomes == 12
    assert result.cards.pending_outcomes == 1
    assert result.cards.missing_outcomes == 2


def test_dashboard_service_supports_required_group_by_values() -> None:
    read_model = FakeReadModel([])
    service = ForwardPerformanceDashboardService(read_model)

    service.load_dashboard(ForwardPerformanceDashboardRequest(group_by="regime"))
    service.load_dashboard(ForwardPerformanceDashboardRequest(group_by="score_percentile_bucket"))

    assert [call["group_by"] for call in read_model.calls] == ["regime", "score_percentile_bucket"]


def test_dashboard_service_builds_status_cards_and_limitations() -> None:
    rows = [
        _summary("ready", status=SUMMARY_STATUS_READY),
        _summary("small", sample_size=3, status=SUMMARY_STATUS_INSUFFICIENT_SAMPLE),
        _summary(
            "benchmark_gap",
            status=SUMMARY_STATUS_MISSING_BENCHMARK,
            warning_counts={"missing_benchmark": 8},
        ),
        _summary(
            "industry_gap",
            status=SUMMARY_STATUS_MISSING_INDUSTRY,
            warning_counts={"missing_industry_benchmark": 6},
        ),
    ]
    result = ForwardPerformanceDashboardService(FakeReadModel(rows)).load_dashboard(
        ForwardPerformanceDashboardRequest()
    )

    assert result.cards.groups_ready == 1
    assert result.cards.groups_insufficient_sample == 1
    assert result.cards.groups_degraded == 2
    assert result.cards.missing_benchmark_count == 8
    assert result.cards.missing_industry_count == 6
    assert result.cards.warnings_count == 14
    assert any("close-to-close" in item for item in result.limitations)
    assert any("不是買賣建議" in item for item in result.limitations)


def test_empty_state_and_bp_formatting_keep_raw_bp() -> None:
    empty = ForwardPerformanceDashboardService(FakeReadModel([])).load_dashboard(
        ForwardPerformanceDashboardRequest()
    )

    assert empty.rows == ()
    assert "尚無足夠 forward evidence" in empty.empty_state_message
    assert format_bp_as_percent(123) == "1.23%"
    assert format_bp_as_percent(-50) == "-0.50%"
    assert format_bp_as_percent(None) == "N/A"

    row = ForwardPerformanceDashboardService(FakeReadModel([_summary("ready")])).load_dashboard(
        ForwardPerformanceDashboardRequest()
    ).rows[0]
    assert row.mean_forward_return_bp == 123
