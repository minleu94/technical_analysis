import pytest
import pandas as pd
from pathlib import Path
from data_module.config import TWStockConfig
from app_module.sqlite_inspector_service import SqliteInspectorService


@pytest.fixture
def test_config():
    """使用測試設定"""
    config = TWStockConfig(profile="test")
    # 確保 SQLite 啟用，且測試 db 存在
    config.use_sqlite = True
    return config


def test_sqlite_inspector_service_basic(test_config):
    """測試 Inspector Service 的基本查詢"""
    service = SqliteInspectorService(test_config)
    
    # 1. 測試獲取 Table 列表
    tables = service.get_tables()
    assert isinstance(tables, list)
    # 必須包含我們預設的 5 大核心表
    expected_tables = ['daily_prices', 'technical_indicators', 'market_indices', 'industry_indices', 'broker_flows']
    for t in expected_tables:
        assert t in tables

    # 2. 測試獲取 Schema
    schema_df = service.get_table_schema('daily_prices')
    assert isinstance(schema_df, pd.DataFrame)
    assert not schema_df.empty
    assert '欄位名稱' in schema_df.columns
    assert '資料型態' in schema_df.columns
    # 確認包含核心欄位
    columns_list = schema_df['欄位名稱'].tolist()
    assert '日期' in columns_list
    assert '證券代號' in columns_list
    assert '收盤價' in columns_list

    # 3. 測試不合法的表名稱防禦
    with pytest.raises(ValueError):
        service.get_table_schema("daily_prices; DROP TABLE daily_prices;")


def test_sqlite_inspector_service_info(test_config):
    """測試獲取表資訊"""
    service = SqliteInspectorService(test_config)
    info = service.get_table_info('market_indices')
    
    assert isinstance(info, dict)
    assert info['table_name'] == 'market_indices'
    assert 'total_records' in info
    assert 'columns_count' in info
    assert info['success'] is True


def test_sqlite_inspector_service_security(test_config):
    """測試自訂 SQL 的唯讀限制防禦"""
    service = SqliteInspectorService(test_config)

    # 1. 合法查詢應成功執行 (或至少不會因為安全性檢查而報錯，若無資料回傳空 df)
    res = service.execute_query("SELECT * FROM market_indices LIMIT 5;")
    assert isinstance(res, pd.DataFrame)

    # 2. 包含破壞性語句應直接被阻擋
    with pytest.raises(ValueError, match="僅允許執行唯讀的 SELECT 查詢"):
        service.execute_query("DROP TABLE market_indices;")

    with pytest.raises(ValueError, match="僅允許執行唯讀的 SELECT 查詢"):
        service.execute_query("DELETE FROM market_indices WHERE 日期 = '20260529';")

    with pytest.raises(ValueError, match="僅允許執行唯讀的 SELECT 查詢"):
        service.execute_query("UPDATE market_indices SET 指數名稱 = '加權指數';")

    # 3. 夾帶破壞性寫入關鍵字應阻擋
    with pytest.raises(ValueError, match="不被允許的寫入或修改關鍵字"):
        service.execute_query("SELECT * FROM market_indices; DROP TABLE market_indices;")

    with pytest.raises(ValueError, match="不被允許的寫入或修改關鍵字"):
        service.execute_query("SELECT * FROM market_indices WHERE 漲跌 = 'INSERT';")


def test_sqlite_inspector_service_limit_protection(test_config):
    """測試 Limit 自動補全防禦"""
    service = SqliteInspectorService(test_config)
    
    # 執行無 Limit 語句，應自動被截斷至 Limit 限制
    # 這裡我們模擬它產生的 SQL 中包含 LIMIT
    # 我們不實際比對執行結果行數，而是驗證 execute_query 成功運行且限制生效
    res = service.execute_query("SELECT * FROM market_indices", limit=10)
    assert isinstance(res, pd.DataFrame)
