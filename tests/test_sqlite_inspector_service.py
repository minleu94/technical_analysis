import pytest
import pandas as pd
from pathlib import Path
from data_module.config import TWStockConfig
from app_module.sqlite_inspector_service import SqliteInspectorService


@pytest.fixture
def test_config(tmp_path):
    """使用測試設定，完全隔離至臨時路徑，並注入 mock 測試資料"""
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    data_root.mkdir()
    output_root.mkdir()

    config = TWStockConfig(
        data_root=data_root,
        output_root=output_root,
        profile="test"
    )
    config.use_sqlite = True

    # 寫入 mock 測試資料
    from data_module.db_manager import DBManager
    db = DBManager(config)
    with db.connect() as conn:
        # 1. 寫入 market_indices
        conn.execute(
            "INSERT INTO market_indices (日期, 指數名稱, 收盤指數, 漲跌, 漲跌點數, 漲跌百分比) "
            "VALUES ('20260529', '加權指數', 20000.0, '+', 100.0, 0.5);"
        )
        # 2. 寫入 daily_prices
        conn.execute(
            "INSERT INTO daily_prices (日期, 證券代號, 證券名稱, 收盤價) "
            "VALUES ('20260529', '2330', '台積電', 800.0);"
        )
        conn.execute(
            "INSERT INTO daily_prices (日期, 證券代號, 證券名稱, 收盤價) "
            "VALUES ('20260528', '2330', '台積電', 790.0);"
        )
        # 3. 寫入 broker_flows
        conn.execute(
            "INSERT INTO broker_flows (日期, 分點名稱, 證券代號, 證券名稱, 買進股數, 賣出股數) "
            "VALUES ('20260529', '美商高盛', '2330', '台積電', 1000, 500);"
        )
        # 4. 寫入 technical_indicators
        conn.execute(
            "INSERT INTO technical_indicators (日期, 證券代號) "
            "VALUES ('20260529', '2330');"
        )
        # 5. 寫入 industry_indices
        conn.execute(
            "INSERT INTO industry_indices (日期, 指數名稱, 收盤指數) "
            "VALUES ('20260529', '半導體類指數', 400.0);"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamental_monthly_revenues (
                stock_code TEXT NOT NULL,
                period TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                revenue TEXT NOT NULL,
                announced_date TEXT NOT NULL,
                available_date TEXT NOT NULL,
                source TEXT NOT NULL,
                source_version TEXT NOT NULL,
                quality TEXT NOT NULL,
                PRIMARY KEY (stock_code, period, source_version)
            );
            """
        )
        conn.execute(
            """
            INSERT INTO fundamental_monthly_revenues (
                stock_code, period, as_of_date, revenue, announced_date,
                available_date, source, source_version, quality
            )
            VALUES (
                '2330', '2026-05', '2026-05-31', '416975163', '2026-06-16',
                '2026-06-17', 'mops.monthly_revenue_static_snapshot',
                'mops-static-snapshot-monthly-revenue-2026-06-16', 'observed'
            );
            """
        )
    return config


def test_sqlite_inspector_service_basic(test_config):
    """測試 Inspector Service 的基本查詢"""
    service = SqliteInspectorService(test_config)
    
    # 1. 測試獲取 Table 列表 (必須全在白名單中)
    tables = service.get_tables()
    assert isinstance(tables, list)
    expected_tables = ['daily_prices', 'technical_indicators', 'market_indices', 'industry_indices', 'broker_flows', 'fundamental_monthly_revenues']
    for t in expected_tables:
        assert t in tables

    # 2. 測試獲取 Schema
    schema_df = service.get_table_schema('daily_prices')
    assert isinstance(schema_df, pd.DataFrame)
    assert not schema_df.empty
    assert '欄位名稱' in schema_df.columns
    assert '資料型態' in schema_df.columns
    columns_list = schema_df['欄位名稱'].tolist()
    assert '日期' in columns_list
    assert '證券代號' in columns_list
    assert '收盤價' in columns_list

    # 3. 測試非白名單的表拋出 ValueError
    with pytest.raises(ValueError, match="拒絕訪問非白名單資料表"):
        service.get_table_schema("sqlite_master")


def test_sqlite_inspector_service_info(test_config):
    """測試獲取表資訊"""
    service = SqliteInspectorService(test_config)
    
    # 1. 正常獲取白名單表資訊
    info = service.get_table_info('market_indices')
    assert isinstance(info, dict)
    assert info['table_name'] == 'market_indices'
    assert info['total_records'] == 1
    assert info['latest_date'] == '2026-05-29'
    assert info['earliest_date'] == '2026-05-29'
    assert info['success'] is True

    # 2. 查詢非白名單表拋出 ValueError
    with pytest.raises(ValueError, match="拒絕訪問非白名單資料表"):
        service.get_table_info('sqlite_sequence')


def test_sqlite_inspector_service_queries(test_config):
    """測試受控查詢 query_table_data 的篩選功能"""
    service = SqliteInspectorService(test_config)

    # 1. 查詢 daily_prices 不帶條件
    df = service.query_table_data('daily_prices')
    assert len(df) == 2
    # 預設依日期降序排列
    assert df.iloc[0]['日期'] == '20260529'
    assert df.iloc[1]['日期'] == '20260528'

    # 2. 帶股票代號篩選
    df_2330 = service.query_table_data('daily_prices', stock_code='2330')
    assert len(df_2330) == 2

    # 3. 帶股票名稱模糊篩選
    df_name = service.query_table_data('daily_prices', stock_name='積電')
    assert len(df_name) == 2

    # 4. 帶日期篩選
    df_date = service.query_table_data('daily_prices', date_str='2026-05-29')
    assert len(df_date) == 1
    assert df_date.iloc[0]['日期'] == '20260529'

    # 5. 區間日期篩選
    df_range = service.query_table_data('daily_prices', start_date='2026-05-28', end_date='2026-05-28')
    assert len(df_range) == 1
    assert df_range.iloc[0]['日期'] == '20260528'

    # 6. 券商分點篩選
    df_broker = service.query_table_data('broker_flows', broker_branch='高盛')
    assert len(df_broker) == 1
    assert df_broker.iloc[0]['分點名稱'] == '美商高盛'

    # 7. 非白名單表拒絕查詢
    with pytest.raises(ValueError, match="拒絕訪問非白名單資料表"):
        service.query_table_data('sqlite_master')


def test_sqlite_inspector_service_queries_monthly_revenue_table(test_config):
    service = SqliteInspectorService(test_config)

    info = service.get_table_info("fundamental_monthly_revenues")
    assert info["success"] is True
    assert info["total_records"] == 1
    assert info["latest_date"] == "2026-05-31"

    df = service.query_table_data(
        "fundamental_monthly_revenues",
        stock_code="2330",
        date_str="2026-05-31",
    )

    assert len(df) == 1
    assert df.iloc[0]["stock_code"] == "2330"
    assert df.iloc[0]["period"] == "2026-05"


def test_sqlite_inspector_service_limit_clamp(test_config):
    """測試 limit clamp 限制防護"""
    service = SqliteInspectorService(test_config)
    
    # 傳入大於 5000 的 limit，驗證不會報錯，且仍能正常查詢
    df_large = service.query_table_data('market_indices', limit=99999)
    assert isinstance(df_large, pd.DataFrame)
    
    # 傳入小於 10 的 limit，驗證不會報錯
    df_small = service.query_table_data('market_indices', limit=2)
    assert isinstance(df_small, pd.DataFrame)


def test_query_table_data_count_uses_same_filters(test_config):
    """測試資料筆數計算與篩選條件一致"""
    service = SqliteInspectorService(test_config)
    
    # 獲取總筆數 (無篩選，fixture 中 daily_prices 有 2 筆)
    total_count = service.query_table_data_count("daily_prices")
    assert total_count == 2
    
    # 帶有篩選的筆數 (2330 有 2 筆)
    count_2330 = service.query_table_data_count("daily_prices", stock_code="2330")
    assert count_2330 == 2

    # 不存在的股票代號應為 0
    count_none = service.query_table_data_count("daily_prices", stock_code="9999")
    assert count_none == 0


def test_paginated_rows_are_stable_without_overlap(test_config):
    """測試分頁查詢的穩定性，確保跨頁資料無重複且無遺漏"""
    from data_module.db_manager import DBManager
    db = DBManager(test_config)
    # 多插入幾筆 daily_prices 資料以供測試
    with db.connect() as conn:
        conn.execute("INSERT INTO daily_prices (日期, 證券代號, 證券名稱, 收盤價) VALUES ('20260527', '2330', '台積電', 780.0);")
        conn.execute("INSERT INTO daily_prices (日期, 證券代號, 證券名稱, 收盤價) VALUES ('20260526', '2330', '台積電', 770.0);")

    service = SqliteInspectorService(test_config)
    # 總共有 4 筆，依日期降序排列
    # 測試 limit=2, offset=0 (第一頁)
    page_1 = service.query_table_data("daily_prices", limit=2, offset=0)
    assert len(page_1) == 2
    
    # 測試 limit=2, offset=2 (第二頁)
    page_2 = service.query_table_data("daily_prices", limit=2, offset=2)
    assert len(page_2) == 2
    
    # 確保兩頁的資料主鍵(日期+證券代號)無交集
    keys_1 = set(zip(page_1["日期"], page_1["證券代號"]))
    keys_2 = set(zip(page_2["日期"], page_2["證券代號"]))
    assert keys_1.isdisjoint(keys_2)
    
    # 合併後共 4 筆
    assert len(keys_1.union(keys_2)) == 4


def test_negative_offset_is_clamped_to_zero(test_config):
    """測試負數 offset 會被自動導正為 0"""
    service = SqliteInspectorService(test_config)
    
    # offset = -100 應該與 offset = 0 的查詢結果完全一致
    actual = service.query_table_data("daily_prices", limit=10, offset=-100)
    expected = service.query_table_data("daily_prices", limit=10, offset=0)
    
    pd.testing.assert_frame_equal(actual, expected)


def test_daily_price_schema_displays_traditional_change_column(test_config):
    service = SqliteInspectorService(test_config)

    schema_df = service.get_table_schema("daily_prices")
    columns = schema_df["欄位名稱"].tolist()

    assert "漲跌" in columns
    assert "涨跌" not in columns


def test_query_table_data_supports_server_side_sorting(test_config):
    service = SqliteInspectorService(test_config)

    df = service.query_table_data(
        "daily_prices",
        sort_column="收盤價",
        sort_order="asc",
    )

    assert df.iloc[0]["日期"] == "20260528"
    assert df.iloc[0]["收盤價"] == 790.0


def test_daily_price_change_diff_uses_direction_sign_for_display(test_config):
    from data_module.db_manager import DBManager

    db = DBManager(test_config)
    with db.connect() as conn:
        conn.execute('ALTER TABLE daily_prices ADD COLUMN "漲跌(+/-)" TEXT;')
        conn.execute(
            'UPDATE daily_prices SET "漲跌(+/-)" = ?, "漲跌價差" = ? WHERE 日期 = ?;',
            ("-", 10.0, "20260529"),
        )
        conn.execute(
            'UPDATE daily_prices SET "漲跌(+/-)" = ?, "漲跌價差" = ? WHERE 日期 = ?;',
            ("+", 5.0, "20260528"),
        )

    service = SqliteInspectorService(test_config)
    df = service.query_table_data(
        "daily_prices",
        sort_column="漲跌價差",
        sort_order="asc",
    )

    assert df.iloc[0]["日期"] == "20260529"
    assert df.iloc[0]["漲跌價差"] == -10.0
    assert df.iloc[1]["漲跌價差"] == 5.0


