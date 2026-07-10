import pandas as pd
from app_module.backtest_report_support import factor_decision_date, score_factor_records

def test_factor_records_use_signal_index_dates_only():
    records = score_factor_records("2330", pd.Series([80, None, 90], index=["2026-01-02", "2026-01-03", "2026-01-04"]))
    assert [record.as_of_date.isoformat() for record in records] == ["2026-01-02", "2026-01-04"]
    assert factor_decision_date(pd.DataFrame({"signal": [1, 2]}, index=["2026-01-02", "2026-01-04"])).isoformat() == "2026-01-04"
