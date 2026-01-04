import pytest
import pandas as pd
from datetime import datetime, timedelta
from data_module.api.twse_api import TWSEAPI

class TestTWSEAPI:
    """測試台灣證券交易所API"""
    
    @pytest.mark.api
    def test_get_daily_price(self):
        """測試獲取每日價格數據"""
        api = TWSEAPI()
        date = datetime.now().strftime('%Y%m%d')
        df = api.get_daily_price(date)
        
        assert df is not None
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert 'stock_id' in df.columns
        assert 'close' in df.columns
    
    @pytest.mark.api
    def test_get_market_index(self):
        """測試獲取市場指數"""
        api = TWSEAPI()
        df = api.get_market_index()
        
        assert df is not None
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert 'date' in df.columns
        assert 'close' in df.columns
    
    @pytest.mark.api
    def test_get_industry_index(self):
        """測試獲取產業指數"""
        api = TWSEAPI()
        df = api.get_industry_index()
        
        assert df is not None
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert 'date' in df.columns
        assert 'index_name' in df.columns
    
    @pytest.mark.api
    def test_error_handling(self):
        """測試錯誤處理"""
        api = TWSEAPI()
        # 測試無效日期
        df = api.get_daily_price('99999999')
        assert df is None
        
        # 測試API限流
        for _ in range(10):
            df = api.get_daily_price(datetime.now().strftime('%Y%m%d'))
        assert df is not None  # 應該能夠處理限流
    
    @pytest.mark.api
    def test_data_validation(self):
        """測試數據驗證"""
        api = TWSEAPI()
        date = datetime.now().strftime('%Y%m%d')
        df = api.get_daily_price(date)
        
        if df is not None:
            assert not df['close'].isna().all()
            assert not df['volume'].isna().all()
            assert df['close'].min() > 0
            assert df['volume'].min() >= 0 