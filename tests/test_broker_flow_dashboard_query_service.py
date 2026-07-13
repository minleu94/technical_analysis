from datetime import date

import pytest

from app_module.broker_flow_dashboard_dtos import BrokerFlowDashboardQuery
from scripts.qa_broker_flow_dashboard_latency import (
    inspect_broker_flow_sqlite,
    summarize_latency_samples,
)


@pytest.mark.parametrize(
    ("period", "expected_days"),
    (("day", 1), ("week", 5), ("month", 20)),
)
def test_dashboard_query_maps_period_to_broker_trading_days(period, expected_days):
    query = BrokerFlowDashboardQuery(
        period=period,
        scope="top_bottom",
        requested_as_of_date=date(2026, 7, 5),
        limit_per_side=50,
    )

    assert query.period_trading_days == expected_days


def test_dashboard_query_selects_recent_dates_at_or_before_explicit_as_of():
    query = BrokerFlowDashboardQuery(
        period="week",
        scope="top_bottom",
        requested_as_of_date=date(2026, 7, 5),
        limit_per_side=50,
    )
    available_dates = (
        date(2026, 6, 26),
        date(2026, 6, 27),
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
        date(2026, 7, 6),
    )

    assert query.select_trading_dates(available_dates) == (
        date(2026, 6, 27),
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    )


def test_dashboard_query_rejects_implicit_or_invalid_contract_values():
    with pytest.raises(ValueError, match="requested_as_of_date"):
        BrokerFlowDashboardQuery(
            period="week",
            scope="top_bottom",
            requested_as_of_date=None,
            limit_per_side=50,
        )
    with pytest.raises(ValueError, match="period"):
        BrokerFlowDashboardQuery(
            period="calendar_week",
            scope="top_bottom",
            requested_as_of_date=date(2026, 7, 5),
            limit_per_side=50,
        )
    with pytest.raises(ValueError, match="limit_per_side"):
        BrokerFlowDashboardQuery(
            period="week",
            scope="top_bottom",
            requested_as_of_date=date(2026, 7, 5),
            limit_per_side=0,
        )


def test_latency_summary_separates_cold_sample_and_warm_nearest_rank_p95():
    summary = summarize_latency_samples([900.0, 10.0, 20.0, 30.0, 40.0, 50.0])

    assert summary == {
        "sample_count": 6,
        "cold_ms": 900.0,
        "warm_sample_count": 5,
        "warm_p95_ms": 50.0,
        "warm_min_ms": 10.0,
        "warm_max_ms": 50.0,
    }


def test_sqlite_shape_probe_is_read_only_and_missing_path_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"

    result = inspect_broker_flow_sqlite(missing)

    assert result["quality"] == "missing"
    assert result["row_count"] == 0
    assert not missing.exists()
