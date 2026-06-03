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
    return config


def test_sqlite_inspector_service_basic(test_config):
    """測試 Inspector Service 的基本查詢"""
    service = SqliteInspectorService(test_config)
    
    # 1. 測試獲取 Table 列表 (必須全在白名單中)
    tables = service.get_tables()
    assert isinstance(tables, list)
    expected_tables = ['daily_prices', 'technical_indicators', 'market_indices', 'industry_indices', 'broker_flows']
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


def test_sqlite_inspector_service_limit_clamp(test_config):
    """測試 limit clamp 限制防護"""
    service = SqliteInspectorService(test_config)
    
    # 傳入大於 5000 的 limit，驗證不會報錯，且仍能正常查詢
    df_large = service.query_table_data('market_indices', limit=99999)
    assert isinstance(df_large, pd.DataFrame)
    
    # 傳入小於 10 的 limit，驗證不會報錯
    df_small = service.query_table_data('market_indices', limit=2)
    assert isinstance(df_small, pd.DataFrame)

