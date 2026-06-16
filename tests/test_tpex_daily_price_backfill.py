import sqlite3

from data_module.tpex_daily_price_backfill import (
    build_tpex_daily_price_plan,
    normalize_tpex_daily_price_rows,
)


def test_normalize_tpex_daily_price_rows_maps_quote_fields():
    result = normalize_tpex_daily_price_rows(
        [
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
                "Open": "42.00",
                "High": "43.00",
                "Low": "41.50",
                "TradingShares": "1,234,000",
                "TransactionAmount": "52,445,000",
                "TransactionNumber": "901",
                "Change": "+0.50",
                "LastBestBidPrice": "42.45",
                "LastBestBidVolume": "3",
                "LastBestAskPrice": "42.50",
                "LastBestAskVolume": "2",
                "PERatio": "12.34",
            }
        ],
        fallback_date="2026-06-16",
    )

    assert result.diagnostics == ()
    assert result.rows == (
        {
            "日期": "20260616",
            "證券代號": "3207",
            "證券名稱": "耀勝",
            "成交股數": 1234000,
            "成交筆數": 901,
            "成交金額": 52445000,
            "開盤價": "42.00",
            "最高價": "43.00",
            "最低價": "41.50",
            "收盤價": "42.50",
            "漲跌": "+",
            "漲跌價差": "0.50",
            "最後揭示買價": "42.45",
            "最後揭示買量": 3,
            "最後揭示賣價": "42.50",
            "最後揭示賣量": 2,
            "本益比": "12.34",
        },
    )


def test_normalize_tpex_daily_price_rows_reports_invalid_price():
    result = normalize_tpex_daily_price_rows(
        [
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "--",
            }
        ],
        fallback_date="2026-06-16",
    )

    assert result.rows == ()
    assert result.diagnostics[0].code == "tpex_daily_price.invalid_price"


def test_build_tpex_daily_price_plan_skips_existing_rows(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
        conn.execute(
            'INSERT INTO daily_prices ("日期", "證券代號", "收盤價") VALUES ("20260616", "3207", 40.0)'
        )

    result = build_tpex_daily_price_plan(
        db_file=db_file,
        source_rows=[
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
            }
        ],
        fallback_date="2026-06-16",
    )

    assert result.ready_for_apply is False
    assert result.existing_count == 1
    assert result.insert_count == 0
