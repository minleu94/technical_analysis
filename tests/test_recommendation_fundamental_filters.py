from __future__ import annotations

import sqlite3
import pandas as pd
import pytest
from app_module.recommendation_service import RecommendationService
from app_module.application_ports import MarketFrameProvider


class _FakeMarketFrameProvider(MarketFrameProvider):
    def __init__(self, stock_df: pd.DataFrame) -> None:
        self._stock_df = stock_df

    def __call__(self) -> pd.DataFrame:
        return self._stock_df

    def get_market_frame(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._stock_df

    def get_stock_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._stock_df[self._stock_df["證券代號"] == stock_code]


def test_fundamental_filters_pe_and_yoy_scenarios(test_config) -> None:
    # 1. 建立測試的 SQLite 基本面資料表
    with sqlite3.connect(test_config.db_file) as conn:
        conn.execute(
            """
            CREATE TABLE fundamental_valuation_metrics (
                stock_code TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                available_date TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (stock_code, metric_name, available_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                available_date TEXT NOT NULL,
                revenue REAL NOT NULL,
                PRIMARY KEY (stock_code, period, available_date)
            )
            """
        )

        # 插入 PE 測試資料
        # 股票 2330: PE = 12 (符合門檻 15)
        conn.execute(
            "INSERT INTO fundamental_valuation_metrics VALUES (?, ?, ?, ?, ?)",
            ("2330", "pe", "2026-06-30", "2026-07-01", 12.0)
        )
        # 股票 2317: PE = 18 (超出門檻 15，應排除)
        conn.execute(
            "INSERT INTO fundamental_valuation_metrics VALUES (?, ?, ?, ?, ?)",
            ("2317", "pe", "2026-06-30", "2026-07-01", 18.0)
        )
        # 股票 2454: 故意不在 PE 表中插入資料，以測試 PE 缺失排除

        # 股票 2303: 測試 PIT 邊界（決策日為 2026-07-16）
        # 2026-07-10 宣告 PE = 14 (應採用)
        # 2026-07-18 宣告 PE = 22 (未來資料，不應採用)
        conn.execute(
            "INSERT INTO fundamental_valuation_metrics VALUES (?, ?, ?, ?, ?)",
            ("2303", "pe", "2026-06-30", "2026-07-10", 14.0)
        )
        conn.execute(
            "INSERT INTO fundamental_valuation_metrics VALUES (?, ?, ?, ?, ?)",
            ("2303", "pe", "2026-07-15", "2026-07-18", 22.0)
        )

        # 插入月營收 YoY 測試資料
        # 門檻為 5.0%
        # 2330: 今年營收 108，去年同期營收 100，YoY = 8% (符合)
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?)",
            ("2330", "2026-06", "2026-06-30", "2026-07-10", 108.0)
        )
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?)",
            ("2330", "2025-06", "2025-06-30", "2025-07-10", 100.0)
        )

        # 2317: 今年營收 103，去年同期營收 100，YoY = 3% (低於 5.0%，應排除)
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?)",
            ("2317", "2026-06", "2026-06-30", "2026-07-10", 103.0)
        )
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?)",
            ("2317", "2025-06", "2025-06-30", "2025-07-10", 100.0)
        )

        # 2303: 去年同期有多個版本，測試 PIT 穩定排序 (ORDER BY available_date DESC)
        # 今年營收 110 (YoY 對照 100 應為 10%)
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?)",
            ("2303", "2026-06", "2026-06-30", "2026-07-10", 110.0)
        )
        # 2025-06 原始版: 營收 100 (available_date: 2025-07-05)
        # 2025-06 修正版: 營收 105 (available_date: 2025-07-09) -> 應採用此版，YoY = 4.76% (低於 5%，排除)
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?)",
            ("2303", "2025-06", "2025-06-30", "2025-07-05", 100.0)
        )
        conn.execute(
            "INSERT INTO fundamental_monthly_revenues VALUES (?, ?, ?, ?, ?)",
            ("2303", "2025-06", "2025-06-30", "2025-07-09", 105.0)
        )

    # 2. 模擬市場資料 DataFrame (生成 20 筆歷史數據以符合 pre_evaluation 長度限制)
    rows = []
    codes = [("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"), ("2303", "聯電")]
    for code, name in codes:
        for i in range(20):
            date_val = pd.Timestamp("2026-07-16") - pd.Timedelta(days=(19-i))
            rows.append({
                "日期": date_val,
                "證券代號": code,
                "證券名稱": name,
                "漲幅%": 1.5,
                "成交量": 50000,
                "收盤價": 100.0,
                "成交量變化率%": 10.0,
            })
    mock_df = pd.DataFrame(rows)

    # 3. 配置門檻 (PE <= 15.0, YoY >= 5.0%)
    config = {
        "filters": {
            "pe_ratio_max": 15.0,
            "monthly_revenue_yoy_min": 5.0,
            "volume_change_min_percent": 0.0,
        },
        "ranking": {
            "weights": {"漲幅%": 100},
        }
    }

    # 4. 初始化 Service
    provider = _FakeMarketFrameProvider(mock_df)
    service = RecommendationService(config=test_config, market_data_provider=provider)

    # 執行推薦生成
    result = service.run_recommendation(
        config=config
    )

    # 5. 斷言驗證
    # 2330 符合所有條件，應通過篩選
    # 2317 因為 PE > 15 (18) 且 YoY < 5 (3%)，應被排除
    # 2454 因為查無 PE，應被排除
    # 2303 採用 2025-07-09 修正版營收 105，YoY = 4.76% (低於 5%)，應被排除

    matrix = service.last_screening_matrix
    assert len(matrix) > 0
    assert {recommendation.stock_code for recommendation in result} == {"2330"}

    rows_by_stock = {row["stock_code"]: row for row in matrix}

    # 2317 (PE = 18 > 15) 應因為 PE 被排除
    assert "2317" in rows_by_stock
    row_2317 = rows_by_stock["2317"]
    assert row_2317["status"] == "skipped"
    assert "valuation_pe_above_max" in row_2317["reason_codes"]
    assert row_2317["observed_value"] == "18.0"
    assert row_2317["required_value"] == "15.0"

    # 2454 (無 PE 數據) 應因為 PE 缺失被排除
    assert "2454" in rows_by_stock
    row_2454 = rows_by_stock["2454"]
    assert row_2454["status"] == "skipped"
    assert "valuation_pe_missing" in row_2454["reason_codes"]
    assert row_2454["observed_value"] == "missing"
    assert row_2454["required_value"] == "15.0"

    # 2303 (YoY 4.76% < 5.0%) 應因為 YoY 低於門檻被排除 (驗證了去年同期營收的穩定排序與 PIT 決策 PE=14)
    assert "2303" in rows_by_stock
    row_2303 = rows_by_stock["2303"]
    assert row_2303["status"] == "skipped"
    assert "fundamental_revenue_yoy_below_min" in row_2303["reason_codes"]
    # YoY = (110 - 105) / 105 * 100 = 4.7619... -> quantize to 0.01 is 4.76
    assert row_2303["observed_value"] == "4.76"
    assert row_2303["required_value"] == "5.0"


def test_normalize_decision_date_rejects_ambiguous_input() -> None:
    assert RecommendationService._normalize_decision_date("2026/07/16") == "2026-07-16"
    assert RecommendationService._normalize_decision_date(20260716) == "2026-07-16"

    with pytest.raises(ValueError):
        RecommendationService._normalize_decision_date("2026-07-16T00:00:00")
