import unittest
import pandas as pd
import numpy as np
from pathlib import Path
import shutil
import tempfile
from datetime import datetime
import logging
from data_module import DataConfig, DataLoader, DataProcessor

class TestDataModule(unittest.TestCase):
    """測試數據模塊的功能"""
    
    @classmethod
    def setUpClass(cls):
        """測試前的準備工作"""
        # 創建臨時測試目錄
        cls.test_dir = tempfile.mkdtemp()
        print(f"測試目錄: {cls.test_dir}")
        
        # 創建測試數據
        cls._create_test_data()
        
        # 初始化配置
        cls.config = DataConfig(base_dir=cls.test_dir)
        
        # 初始化加載器和處理器
        cls.loader = DataLoader(cls.config)
        cls.processor = DataProcessor(cls.config)
    
    @classmethod
    def tearDownClass(cls):
        """測試後的清理工作"""
        # 關閉所有日誌處理器
        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)
        
        # 清理測試目錄
        try:
            shutil.rmtree(cls.test_dir)
        except Exception as e:
            print(f"清理測試目錄時出錯: {e}")
    
    @classmethod
    def _create_test_data(cls):
        """創建測試用的數據文件"""
        # 創建測試數據目錄
        daily_price_dir = Path(cls.test_dir) / "daily_price"
        daily_price_dir.mkdir(parents=True)
        
        # 創建測試數據文件
        test_data = pd.DataFrame({
            'date': ['20240101'],
            'stock_id': ['2330'],
            'open': [100.0],
            'high': [105.0],
            'low': [95.0],
            'close': [102.0],
            'volume': [1000000]
        })
        test_data.to_csv(daily_price_dir / "20240101.csv", index=False)
        
        # 創建市場指數數據
        market_index = pd.DataFrame({
            'date': ['20240101'],
            'index': ['TWII'],
            'value': [18000.0]
        })
        market_index.to_csv(Path(cls.test_dir) / "market_index.csv", index=False)
        
        # 創建產業指數數據
        industry_index = pd.DataFrame({
            'date': ['20240101'],
            'industry': ['半導體'],
            'value': [2000.0]
        })
        industry_index.to_csv(Path(cls.test_dir) / "industry_index.csv", index=False)
        
        # 創建股票基本資料
        stock_data = pd.DataFrame({
            'stock_id': ['2330'],
            'name': ['台積電'],
            'industry': ['半導體']
        })
        stock_data.to_csv(Path(cls.test_dir) / "stock_data.csv", index=False)
    
    def setUp(self):
        """每個測試方法前的準備工作"""
        self.loader = DataLoader(self.config)
        self.processor = DataProcessor(self.config)
    
    def test_data_loader(self):
        """測試數據加載器"""
        # 測試加載每日價格數據
        df = self.loader.load_daily_price('20240101')
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
        
        # 測試加載市場指數
        df = self.loader.load_market_index()
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
        
        # 測試加載產業指數
        df = self.loader.load_industry_index()
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
        
        # 測試加載股票基本資料
        df = self.loader.load_stock_data()
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
    
    def test_data_processor(self):
        """測試數據處理器"""
        # 加載測試數據
        df = self.loader.load_daily_price('20240101')
        
        # 測試數據清洗
        df_cleaned = self.processor.clean_price_data(df)
        self.assertIsNotNone(df_cleaned)
        self.assertEqual(len(df_cleaned), 1)
        
        # 測試添加基本特徵
        df_features = self.processor.add_basic_features(df_cleaned)
        self.assertIsNotNone(df_features)
        self.assertTrue('daily_return' in df_features.columns)
        
        # 測試計算技術指標
        df_indicators = self.processor.calculate_technical_indicators(df_features)
        self.assertIsNotNone(df_indicators)
        self.assertTrue('MA5' in df_indicators.columns)
        
        # 測試數據驗證
        is_valid = self.processor.validate_data(df_indicators)
        self.assertTrue(is_valid)
    
    def test_backup_mechanism(self):
        """測試備份機制"""
        # 創建測試文件
        test_file = Path(self.test_dir) / "test.csv"
        test_data = pd.DataFrame({'test': [1, 2, 3]})
        test_data.to_csv(test_file, index=False)
        
        # 測試創建備份
        backup_file = self.config.create_backup(test_file)
        self.assertTrue(backup_file.exists())
        
        # 測試備份文件命名
        self.assertTrue(backup_file.name.startswith("test_"))
        self.assertTrue(backup_file.name.endswith(".csv"))
    
    def test_data_integrity(self):
        """測試數據完整性"""
        # 測試完整的數據處理流程
        processed_df = self.processor.process_stock_data('2330', '20240101', '20240101')
        self.assertIsNotNone(processed_df)
        
        # 驗證必要的列是否存在
        required_columns = ['date', 'stock_id', 'open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            self.assertIn(col, processed_df.columns)
        
        # 驗證數據類型
        self.assertTrue(pd.api.types.is_numeric_dtype(processed_df['close']))
        self.assertTrue(pd.api.types.is_numeric_dtype(processed_df['volume']))
    
    def test_error_handling(self):
        """測試錯誤處理"""
        # 測試加載不存在的文件
        df = self.loader.load_daily_price('99999999')
        self.assertIsNone(df)
        
        # 測試處理無效數據
        invalid_df = pd.DataFrame({'invalid': [1, 2, 3]})
        is_valid = self.processor.validate_data(invalid_df)
        self.assertFalse(is_valid)

if __name__ == '__main__':
    unittest.main() 