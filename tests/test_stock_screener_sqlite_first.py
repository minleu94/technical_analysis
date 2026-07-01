from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import sqlite3

from decision_module.stock_screener import StockScreener


def _make_config(tmp_path):
    return SimpleNamespace(
        use_sqlite=True,
        db_file=tmp_path / "twstock.db",
        technical_dir=tmp_path / "missing_technical_dir",
        industry_index_file=tmp_path / "missing_industry_index.csv",
        meta_data_dir=tmp_path,
    )


def _insert_daily_prices(conn, start_date):
    conn.execute(
        """
        CREATE TABLE daily_prices (
            日期 TEXT,
            證券代號 TEXT,
            證券名稱 TEXT,
            收盤價 REAL,
            開盤價 REAL,
            最高價 REAL,
            最低價 REAL,
            成交股數 REAL,
            成交金額 REAL
        )
        """
    )
    rows = []
    for offset in range(25):
        current = (start_date + timedelta(days=offset)).strftime("%Y%m%d")
        symbols = {
            "2330": ("台積電", 100 + offset * 2, 1_000_000 + offset * 20_000),
            "2317": ("鴻海", 120 - offset, 800_000),
            "1101": ("台泥", 50 + offset * 0.1, 600_000),
        }
        for code, (name, close, volume) in symbols.items():
            rows.append(
                (
                    current,
                    code,
                    name,
                    close,
                    close - 1,
                    close + 1,
                    close - 2,
                    volume,
                    close * volume,
                )
            )
    conn.executemany(
        """
        INSERT INTO daily_prices (
            日期, 證券代號, 證券名稱, 收盤價, 開盤價, 最高價, 最低價, 成交股數, 成交金額
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _insert_industry_indices(conn, start_date):
    conn.execute(
        """
        CREATE TABLE industry_indices (
            日期 TEXT,
            指數名稱 TEXT,
            收盤指數 REAL
        )
        """
    )
    rows = []
    for offset in range(12):
        current = (start_date + timedelta(days=offset)).strftime("%Y%m%d")
        rows.extend(
            [
                (current, "半導體", 100 + offset * 2),
                (current, "金融保險", 100 - offset * 1.5),
                (current, "水泥", 95 + offset * 0.2),
            ]
        )
    conn.executemany(
        "INSERT INTO industry_indices (日期, 指數名稱, 收盤指數) VALUES (?, ?, ?)",
        rows,
    )


def _build_sqlite_db(db_file: Path):
    with sqlite3.connect(db_file) as conn:
        _insert_daily_prices(conn, date(2026, 5, 1))
        _insert_industry_indices(conn, date(2026, 5, 1))


def test_stock_screener_uses_sqlite_for_strong_and_weak_stocks_without_indicator_csv(tmp_path):
    config = _make_config(tmp_path)
    _build_sqlite_db(config.db_file)
    screener = StockScreener(config, min_price=0)

    strong, strong_universe = screener.get_strong_stocks(period="day", top_n=2)
    weak, weak_universe = screener.get_weak_stocks(period="day", top_n=2)

    assert strong_universe == 3
    assert weak_universe == 3
    assert strong.iloc[0]["證券代號"] == "2330"
    assert weak.iloc[0]["證券代號"] == "2317"
    assert strong.iloc[0]["評分"].startswith("Top")
    assert weak.iloc[0]["評分"].startswith("Bottom")


def test_stock_screener_uses_sqlite_for_strong_and_weak_industries_without_csv(tmp_path):
    config = _make_config(tmp_path)
    _build_sqlite_db(config.db_file)
    screener = StockScreener(config, min_price=0)

    strong = screener.get_strong_industries(period="day", top_n=2)
    weak = screener.get_weak_industries(period="day", top_n=2)

    assert strong.iloc[0]["指數名稱"] == "半導體"
    assert weak.iloc[0]["指數名稱"] == "金融保險"
    assert list(strong.columns) == ["排名", "指數名稱", "收盤指數", "漲幅%"]
    assert list(weak.columns) == ["排名", "指數名稱", "收盤指數", "漲幅%"]
