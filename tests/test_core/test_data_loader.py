import pytest
import pandas as pd
from pathlib import Path
from data_module.data_loader import DataLoader

class TestDataLoader:
    """測試數據加載器"""
    
    def test_load_daily_price(self, test_config, sample_stock_data):
        """測試加載每日價格數據"""
        # 保存測試數據
        test_file = test_config.daily_price_dir / "20240101.csv"
        sample_stock_data.to_csv(test_file, index=False)
        
        # 測試加載
        loader = DataLoader(test_config)
        df = loader.load_daily_price('20240101')
        assert df is not None
        assert len(df) > 0
        assert 'stock_id' in df.columns
        assert 'close' in df.columns
    
    def test_load_market_index(self, test_config, sample_market_data):
        """測試加載市場指數"""
        # 保存測試數據
        test_file = test_config.meta_data_dir / "market_index.csv"
        sample_market_data.to_csv(test_file, index=False)
        
        # 測試加載
        loader = DataLoader(test_config)
        df = loader.load_market_index()
        assert df is not None
        assert len(df) > 0
        assert 'date' in df.columns
        assert 'close' in df.columns
    
    def test_load_industry_index(self, test_config, sample_index_data):
        """測試加載產業指數"""
        # 保存測試數據
        test_file = test_config.meta_data_dir / "industry_index.csv"
        sample_index_data.to_csv(test_file, index=False)
        
        # 測試加載
        loader = DataLoader(test_config)
        df = loader.load_industry_index()
        assert df is not None
        assert len(df) > 0
        assert 'date' in df.columns
        assert 'index_name' in df.columns
    
    def test_load_nonexistent_file(self, test_config):
        """測試加載不存在的文件"""
        loader = DataLoader(test_config)
        df = loader.load_daily_price('99999999')
        assert df is None
    
    @pytest.mark.data
    def test_data_validation(self, test_config, sample_stock_data):
        """測試數據驗證"""
        loader = DataLoader(test_config)
        assert loader.validate_data(sample_stock_data)
        
        # 測試無效數據
        invalid_df = pd.DataFrame({'invalid': [1, 2, 3]})
        assert not loader.validate_data(invalid_df) 