import pytest
import pandas as pd
from datetime import datetime, timedelta
from utils.date_utils import DateUtils
from utils.data_utils import DataUtils

class TestDateUtils:
    """測試日期工具函數"""
    
    def test_date_format_conversion(self):
        """測試日期格式轉換"""
        date_str = '20240101'
        date_obj = DateUtils.str_to_date(date_str)
        assert isinstance(date_obj, datetime)
        assert date_obj.year == 2024
        assert date_obj.month == 1
        assert date_obj.day == 1
        
        converted_str = DateUtils.date_to_str(date_obj)
        assert converted_str == date_str
    
    def test_date_range_generation(self):
        """測試日期範圍生成"""
        start_date = '20240101'
        end_date = '20240110'
        date_range = DateUtils.generate_date_range(start_date, end_date)
        
        assert len(date_range) == 10
        assert date_range[0] == start_date
        assert date_range[-1] == end_date
    
    def test_trading_days(self):
        """測試交易日判斷"""
        # 測試週一
        monday = '20240101'
        assert DateUtils.is_trading_day(monday)
        
        # 測試週日
        sunday = '20240107'
        assert not DateUtils.is_trading_day(sunday)

class TestDataUtils:
    """測試數據工具函數"""
    
    def test_data_cleaning(self):
        """測試數據清理"""
        df = pd.DataFrame({
            'price': [100, None, 200, 'N/A', 300],
            'volume': [1000, 2000, None, 3000, 'N/A']
        })
        
        cleaned_df = DataUtils.clean_data(df)
        assert cleaned_df['price'].isna().sum() == 0
        assert cleaned_df['volume'].isna().sum() == 0
        assert len(cleaned_df) == 3
    
    def test_data_normalization(self):
        """測試數據標準化"""
        df = pd.DataFrame({
            'price': [100, 200, 300, 400, 500],
            'volume': [1000, 2000, 3000, 4000, 5000]
        })
        
        normalized_df = DataUtils.normalize_data(df)
        assert normalized_df['price'].mean() == pytest.approx(0, abs=1e-10)
        assert normalized_df['price'].std() == pytest.approx(1, abs=1e-10)
    
    def test_data_validation(self):
        """測試數據驗證"""
        df = pd.DataFrame({
            'price': [100, 200, 300],
            'volume': [1000, 2000, 3000]
        })
        
        assert DataUtils.validate_data(df, required_columns=['price', 'volume'])
        assert not DataUtils.validate_data(df, required_columns=['price', 'volume', 'missing']) 