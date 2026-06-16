import sqlite3

from data_module.tpex_daily_price_history_plan import build_tpex_daily_price_history_plan


def test_tpex_daily_price_history_plan_counts_existing_and_candidates(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )
        conn.execute(
            'INSERT INTO daily_prices ("日期", "證券代號", "收盤價") VALUES ("20260616", "3207", 40.0)'
        )

    def fetch_rows(date_key):
        return [
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
            },
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3211",
                "CompanyName": "順達",
                "Close": "80.00",
            },
        ]

    plan = build_tpex_daily_price_history_plan(
        db_file=db_file,
        start_date="2026-06-16",
        end_date="2026-06-16",
        fetch_rows_for_date=fetch_rows,
    )

    assert plan.date_count == 1
    assert plan.existing_count == 1
    assert plan.candidate_insert_count == 1
    assert plan.failed_dates == ()
    assert "candidate_insert_count: 1" in plan.to_markdown()


def test_tpex_daily_price_history_plan_reports_missing_source_date(tmp_path):
    db_file = tmp_path / "twstock.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "收盤價" REAL, PRIMARY KEY ("證券代號", "日期"))'
        )

    plan = build_tpex_daily_price_history_plan(
        db_file=db_file,
        start_date="2026-06-15",
        end_date="2026-06-15",
        fetch_rows_for_date=lambda date_key: [
            {
                "Date": "1150616",
                "SecuritiesCompanyCode": "3207",
                "CompanyName": "耀勝",
                "Close": "42.50",
            }
        ],
    )

    assert plan.candidate_insert_count == 0
    assert plan.failed_dates == ("20260615",)

