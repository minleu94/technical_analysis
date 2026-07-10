import pandas as pd
import pytest

from app_module.backtest_report_support import create_empty_report, date_from_index, factor_decision_date, score_factor_records
from app_module.dtos import ValidationStatus

def test_factor_records_use_signal_index_dates_only():
    records = score_factor_records("2330", pd.Series([80, None, 90], index=["2026-01-02", "2026-01-03", "2026-01-04"]))
    assert [record.as_of_date.isoformat() for record in records] == ["2026-01-02", "2026-01-04"]
    assert factor_decision_date(pd.DataFrame({"signal": [1, 2]}, index=["2026-01-02", "2026-01-04"])).isoformat() == "2026-01-04"


def test_empty_report_preserves_dto_schema_and_invalid_index_is_none():
    report = create_empty_report("boom")

    assert report.validation_status is ValidationStatus.FAIL
    assert report.details["error"] == "boom"
    assert report.details["can_promote"] is False
    assert report.total_trades == 0
    assert report.total_return == 0.0
    assert report.details["equity_curve"].empty
    with pytest.raises(ValueError):
        date_from_index("not-a-date")
