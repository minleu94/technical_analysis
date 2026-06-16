import pandas as pd

from data_module.tpex_daily_price_source import TpexDailyPriceSource


def test_tpex_daily_price_source_writes_requested_date_csv(tmp_path):
    source = TpexDailyPriceSource(
        output_dir=tmp_path,
        fetch_rows=lambda: [
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
            },
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "00720B",
                "CompanyName": "債券",
                "Close": "100.00",
            },
        ],
    )

    result = source.update_for_date("2026-06-16")

    assert result.success is True
    assert result.requested_date == "20260616"
    assert result.source_date == "20260616"
    assert result.row_count == 1
    assert result.skipped_count == 1
    assert result.output_file == tmp_path / "20260616.csv"

    df = pd.read_csv(result.output_file, encoding="utf-8-sig", dtype={"證券代號": str, "日期": str})
    assert df[["日期", "證券代號", "證券名稱", "收盤價"]].to_dict(orient="records") == [
        {"日期": "20260616", "證券代號": "3207", "證券名稱": "耀勝", "收盤價": 42.5}
    ]


def test_tpex_daily_price_source_reports_date_mismatch(tmp_path):
    source = TpexDailyPriceSource(
        output_dir=tmp_path,
        fetch_rows=lambda: [
            {
                "Date": "1150615",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
            }
        ],
    )

    result = source.update_for_date("2026-06-16")

    assert result.success is False
    assert result.row_count == 0
    assert "does not contain requested date" in result.message
    assert not (tmp_path / "20260616.csv").exists()

