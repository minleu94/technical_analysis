import pytest
from pathlib import Path
import shutil
import tempfile
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

@pytest.fixture(scope="session")
def test_data_dir():
    """創建臨時測試數據目錄"""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)

@pytest.fixture(scope="session")
def sample_market_data():
    """生成測試用的市場數據"""
    dates = pd.date_range('2024-01-01', '2024-01-10')
    return pd.DataFrame({
        'date': dates,
        'open': np.random.normal(100, 10, len(dates)),
        'high': np.random.normal(105, 10, len(dates)),
        'low': np.random.normal(95, 10, len(dates)),
        'close': np.random.normal(102, 10, len(dates)),
        'volume': np.random.randint(1000000, 2000000, len(dates))
    })

@pytest.fixture(scope="session")
def sample_stock_data():
    """生成測試用的股票數據"""
    dates = pd.date_range('2024-01-01', '2024-01-10')
    stock_ids = ['2330', '2317', '2412']
    data = []
    
    for stock_id in stock_ids:
        for date in dates:
            data.append({
                'date': date,
                'stock_id': stock_id,
                'open': np.random.normal(100, 10),
                'high': np.random.normal(105, 10),
                'low': np.random.normal(95, 10),
                'close': np.random.normal(102, 10),
                'volume': np.random.randint(1000000, 2000000)
            })
    
    return pd.DataFrame(data)

@pytest.fixture(scope="session")
def sample_index_data():
    """生成測試用的指數數據"""
    dates = pd.date_range('2024-01-01', '2024-01-10')
    indices = ['半導體', '電子', '金融']
    data = []
    
    for index in indices:
        for date in dates:
            data.append({
                'date': date,
                'index_name': index,
                'value': np.random.normal(1000, 100),
                'change': np.random.normal(0, 10),
                'change_pct': np.random.normal(0, 1)
            })
    
    return pd.DataFrame(data)

@pytest.fixture(scope="session")
def test_config(test_data_dir):
    """創建測試配置"""
    from data_module.config import DataConfig
    return DataConfig(base_dir=test_data_dir) 