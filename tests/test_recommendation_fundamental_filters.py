from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from app_module.recommendation_service import RecommendationService
from app_module.application_ports import MarketFrameProvider
from data_module.fundamental_schema import apply_fundamental_schema


class _FakeMarketFrameProvider(MarketFrameProvider):
    def __init__(self, stock_df: pd.DataFrame) -> None:
        self._stock_df = stock_df

    def __call__(self) -> pd.DataFrame:
        return self._stock_df

    def get_market_frame(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._stock_df

    def get_stock_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._stock_df[self._stock_df["證券代號"] == stock_code]


def _write_formal_mapping(path: Path, rows: list[tuple[str, ...]]) -> None:
    header = (
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version,"
        "availability_contract_version,evidence_class,source_hash,revision,parent_revision"
    )
    path.write_text(
        "\n".join((header, *( ",".join(row) for row in rows))) + "\n",
        encoding="utf-8",
    )


def test_fundamental_filters_pe_and_yoy_scenarios(test_config) -> None:
    # 1. 建立測試的 SQLite 基本面資料表
    with sqlite3.connect(test_config.db_file) as conn:
        apply_fundamental_schema(conn)

        # 插入 PE 測試資料
        # 股票 2330: PE = 12 (符合門檻 15)
        conn.execute(
            """
            INSERT INTO fundamental_valuation_metrics(
                stock_code, as_of_date, available_date, metric_name, value,
                industry, industry_percentile_bp, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2330", "2026-06-30", "2026-07-01", "pe", "12.0", None, None, "test", "v1", "observed")
        )
        # 股票 2317: PE = 18 (超出門檻 15，應排除)
        conn.execute(
            """
            INSERT INTO fundamental_valuation_metrics(
                stock_code, as_of_date, available_date, metric_name, value,
                industry, industry_percentile_bp, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2317", "2026-06-30", "2026-07-01", "pe", "18.0", None, None, "test", "v1", "observed")
        )
        # 股票 2454: 故意不在 PE 表中插入資料，以測試 PE 缺失排除

        # 股票 2303: 測試 PIT 邊界（決策日為 2026-07-16）
        # 2026-07-10 宣告 PE = 14 (應採用)
        # 2026-07-18 宣告 PE = 22 (未來資料，不應採用)
        conn.execute(
            """
            INSERT INTO fundamental_valuation_metrics(
                stock_code, as_of_date, available_date, metric_name, value,
                industry, industry_percentile_bp, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2303", "2026-06-30", "2026-07-10", "pe", "14.0", None, None, "test", "v1", "observed")
        )
        conn.execute(
            """
            INSERT INTO fundamental_valuation_metrics(
                stock_code, as_of_date, available_date, metric_name, value,
                industry, industry_percentile_bp, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2303", "2026-07-15", "2026-07-18", "pe", "22.0", None, None, "test", "v1", "observed")
        )

        # 插入月營收 YoY 測試資料
        # 門檻為 5.0%
        # 2330: 今年營收 108，去年同期營收 100，YoY = 8% (符合)
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2330", "2026-06", "2026-06-30", "2026-07-10", "2026-07-10", "108.0", "mops.monthly_revenue_static_snapshot", "test-snapshot", "observed")
        )
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2330", "2025-06", "2025-06-30", "2025-07-10", "2025-07-10", "100.0", "mops.monthly_revenue_static_snapshot", "test-snapshot", "observed")
        )

        # 2317: 今年營收 103，去年同期營收 100，YoY = 3% (低於 5.0%，應排除)
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2317", "2026-06", "2026-06-30", "2026-07-10", "2026-07-10", "103.0", "mops.monthly_revenue_static_snapshot", "test-snapshot", "observed")
        )
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2317", "2025-06", "2025-06-30", "2025-07-10", "2025-07-10", "100.0", "mops.monthly_revenue_static_snapshot", "test-snapshot", "observed")
        )

        # 2303: 去年同期有多個版本，測試 PIT 穩定排序 (ORDER BY available_date DESC)
        # 今年營收 110 (YoY 對照 100 應為 10%)
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2303", "2026-06", "2026-06-30", "2026-07-10", "2026-07-10", "110.0", "mops.monthly_revenue_static_snapshot", "test-snapshot", "observed")
        )
        # 2025-06 原始版: 營收 100 (available_date: 2025-07-05)
        # 2025-06 修正版: 營收 105 (available_date: 2025-07-09) -> 應採用此版，YoY = 4.76% (低於 5%，排除)
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2303", "2025-06", "2025-06-30", "2025-07-05", "2025-07-05", "100.0", "mops.monthly_revenue_static_snapshot", "test-snapshot-r1", "observed")
        )
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2303", "2025-06", "2025-06-30", "2025-07-09", "2025-07-09", "105.0", "mops.monthly_revenue_static_snapshot", "test-snapshot-r2", "observed")
        )

    _write_formal_mapping(
        test_config.monthly_revenue_availability_file,
        [
            (
                stock_code,
                period,
                as_of_date,
                announced_date,
                available_date,
                "twse.monthly_revenue_announcement",
                "test-formal-v2",
                "formal-availability.v2",
                "official_announcement",
                source_hash,
                revision,
                parent_revision,
            )
            for (
                stock_code,
                period,
                as_of_date,
                announced_date,
                available_date,
                source_hash,
                revision,
                parent_revision,
            ) in [
                ("2330", "2026-06", "2026-06-30", "2026-07-10", "2026-07-10", "a" * 64, "1", ""),
                ("2330", "2025-06", "2025-06-30", "2025-07-10", "2025-07-10", "b" * 64, "1", ""),
                ("2317", "2026-06", "2026-06-30", "2026-07-10", "2026-07-10", "c" * 64, "1", ""),
                ("2317", "2025-06", "2025-06-30", "2025-07-10", "2025-07-10", "d" * 64, "1", ""),
                ("2303", "2026-06", "2026-06-30", "2026-07-10", "2026-07-10", "e" * 64, "1", ""),
                ("2303", "2025-06", "2025-06-30", "2025-07-05", "2025-07-05", "f" * 64, "1", ""),
                ("2303", "2025-06", "2025-06-30", "2025-07-09", "2025-07-09", "0" * 64, "2", "1"),
            ]
        ],
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


def test_recommendation_yoy_filter_rejects_unmapped_snapshot_rows(test_config) -> None:
    with sqlite3.connect(test_config.db_file) as conn:
        apply_fundamental_schema(conn)
        conn.executemany(
            """
            INSERT INTO fundamental_monthly_revenues(
                stock_code, period, as_of_date, announced_date, available_date,
                revenue, source, source_version, quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2330",
                    "2025-05",
                    "2025-05-31",
                    "2025-06-16",
                    "2025-06-17",
                    "100.0",
                    "mops.monthly_revenue_static_snapshot",
                    "snapshot-2026-07-14",
                    "observed",
                ),
                (
                    "2330",
                    "2026-05",
                    "2026-05-31",
                    "2026-06-16",
                    "2026-06-17",
                    "110.0",
                    "mops.monthly_revenue_static_snapshot",
                    "snapshot-2026-07-14",
                    "observed",
                ),
            ],
        )

    # 檔案本身有效，但沒有為 2330 的 snapshot row 提供正式 availability 證據。
    _write_formal_mapping(
        test_config.monthly_revenue_availability_file,
        [
            (
                "9999",
                "2026-06",
                "2026-06-30",
                "2026-07-14",
                "2026-07-15",
                "twse.monthly_revenue_announcement",
                "test-formal-v2",
                "formal-availability.v2",
                "official_announcement",
                "a" * 64,
                "1",
                "",
            )
        ],
    )
    market_frame = pd.DataFrame(
        [
            {
                "日期": pd.Timestamp("2026-06-11") + pd.Timedelta(days=index),
                "證券代號": "2330",
                "證券名稱": "台積電",
                "漲幅%": 1.5,
                "成交量": 50000,
                "收盤價": 100.0,
                "成交量變化率%": 10.0,
            }
            for index in range(20)
        ]
    )
    service = RecommendationService(
        config=test_config,
        market_data_provider=_FakeMarketFrameProvider(market_frame),
    )
    service.strategy_configurator.generate_recommendations = lambda _frame, _config: pd.DataFrame(
        {
            "TotalScore": [80.0],
            "FinalScore": [80.0],
            "收盤價": [100.0],
            "成交量": [50000],
        }
    )

    result = service.run_recommendation(
        config={
            "filters": {
                "pe_ratio_max": 999.0,
                "monthly_revenue_yoy_min": 5.0,
                "volume_change_min_percent": 0.0,
            },
            "ranking": {"weights": {"漲幅%": 100}},
        },
        max_stocks=1,
        top_n=1,
    )

    assert result == []
    assert service.last_screening_matrix[0]["reason_codes"] == [
        "fundamental_revenue_yoy_missing"
    ]


def test_normalize_decision_date_rejects_ambiguous_input() -> None:
    assert RecommendationService._normalize_decision_date("2026/07/16") == "2026-07-16"
    assert RecommendationService._normalize_decision_date(20260716) == "2026-07-16"

    with pytest.raises(ValueError):
        RecommendationService._normalize_decision_date("2026-07-16T00:00:00")
