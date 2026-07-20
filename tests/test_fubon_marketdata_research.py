from datetime import datetime, timezone

from data_module.fubon_marketdata_research import (
    FUBON_RESEARCH_WARNING,
    project_capital_changes,
    project_dividends,
    project_ticker,
)


NOW = datetime(2026, 7, 19, 1, 2, 3, tzinfo=timezone.utc)


def test_ticker_projects_documented_microstructure_flags_research_only() -> None:
    result = project_ticker(
        {
            "date": "2026-07-19",
            "symbol": "1234",
            "exchange": "TPEX",
            "isDisposition": True,
            "matchingInterval": 300,
            "securityStatus": "SUSPENDED",
            "limitUpPrice": 11,
            "limitDownPrice": 9,
        },
        quote_payload={"lastPrice": 11},
        fetched_at=NOW,
    )

    assert {row.source_id for row in result.observations} == {
        "microstructure.disposition_stock",
        "microstructure.periodic_call_auction",
        "microstructure.suspended_halt_resume",
        "microstructure.limit_lock",
    }
    assert all(row.quality == "degraded" for row in result.observations)
    assert all(row.downstream_eligibility == "none" for row in result.observations)
    assert FUBON_RESEARCH_WARNING in result.diagnostics
    assert "fubon_no_documented_full_delivery_indicator" in result.diagnostics


def test_ticker_fails_closed_when_quote_is_not_captured() -> None:
    result = project_ticker(
        {"date": "2026-07-19", "symbol": "1234", "isDisposition": False, "matchingInterval": 0, "securityStatus": "NORMAL"},
        fetched_at=NOW,
    )

    assert result.observations == ()
    assert "fubon_quote_not_captured_limit_lock_unavailable" in result.diagnostics


def test_corporate_actions_project_only_documented_relevant_events() -> None:
    dividends = project_dividends(
        [{"symbol": "1234", "date": "2026-08-01", "exchange": "TPEX"}], fetched_at=NOW
    )
    capital = project_capital_changes(
        [
            {"symbol": "1234", "effectiveDate": "2026-08-02", "actionType": "capital_reduction"},
            {"symbol": "5678", "effectiveDate": "2026-08-03", "actionType": "other"},
        ],
        fetched_at=NOW,
    )

    assert [row.source_id for row in dividends.observations] == ["corporate_action.ex_dividend_timeline"]
    assert [row.source_id for row in capital.observations] == ["corporate_action.reduction_split_par_value"]
    assert "fubon_capital_change_skipped_action_type:other" in capital.diagnostics
