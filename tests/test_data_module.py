import unittest
import pandas as pd
import numpy as np
from pathlib import Path
import shutil
import tempfile
from datetime import datetime
import logging
from data_module import TWStockConfig, DataLoader, TWMarketDataProcessor

class TestDataModule(unittest.TestCase):
    """測試數據模塊的功能"""
    
    @classmethod
    def setUpClass(cls):
        """測試前的準備工作"""
        # 創立臨時測試目錄
        cls.test_dir = tempfile.mkdtemp()
        print(f"測試目錄: {cls.test_dir}")
        
        # 初始化配置，將 data_root 設在臨時目錄
        cls.config = TWStockConfig(data_root=Path(cls.test_dir), output_root=Path(cls.test_dir)/"output")
        # 確保關閉 sqlite，只測試 csv 載入
        cls.config.use_sqlite = False
        
        # 創建測試數據
        cls._create_test_data()
        
        # 初始化加載器和處理器
        cls.loader = DataLoader(cls.config)
        cls.processor = TWMarketDataProcessor(cls.config)
    
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
        daily_price_dir = cls.config.daily_price_dir
        daily_price_dir.mkdir(parents=True, exist_ok=True)
        
        # 創建每日價格數據文件 (與 merge_daily_data 欄位格式相同)
        test_data = pd.DataFrame({
            '證券代號': ['2330'],
            '證券名稱': ['台積電'],
            '成交股數': [1000000],
            '成交筆數': [1000],
            '成交金額': [102000000],
            '開盤價': [100.0],
            '最高價': [105.0],
            '最低價': [95.0],
            '收盤價': [102.0],
            '漲跌(+/-)': ['+'],
            '漲跌價差': [2.0],
            '最後揭示買價': [101.5],
            '最後揭示買量': [100],
            '最後揭示賣價': [102.0],
            '最後揭示賣量': [150],
            '本益比': [15.0]
        })
        test_data.to_csv(daily_price_dir / "20240101.csv", index=False, encoding='utf-8-sig')
        
        # 創建 meta_data 目錄
        meta_data_dir = cls.config.meta_data_dir
        meta_data_dir.mkdir(parents=True, exist_ok=True)
        
        # 創建市場指數數據
        market_index = pd.DataFrame({
            '日期': ['2024/01/01'],
            '開盤價': [18000.0],
            '最高價': [18100.0],
            '最低價': [17950.0],
            '收盤價': [18050.0],
            '成交量': [5000000000]
        })
        market_index.to_csv(cls.config.market_index_file, index=False, encoding='utf-8-sig')
        
        # 創建產業指數數據
        industry_index = pd.DataFrame({
            '產業別': ['半導體'],
            '開盤指數': [2000.0],
            '最高指數': [2020.0],
            '最低指數': [1990.0],
            '收盤指數': [2010.0],
            '漲跌點數': [10.0],
            '漲跌百分比': [0.5],
            '日期': ['2024-01-01']
        })
        industry_index.to_csv(cls.config.industry_index_file, index=False, encoding='utf-8-sig')
        
        # 創建股票基本資料 (即 stock_data_whole.csv)
        stock_data = pd.DataFrame({
            '證券代號': ['2330'],
            '證券名稱': ['台積電'],
            '日期': ['2024/01/01']
        })
        stock_data.to_csv(cls.config.stock_data_file, index=False, encoding='utf-8-sig')
    
    def setUp(self):
        """每個測試方法前的準備工作"""
        self.loader = DataLoader(self.config)
        self.processor = TWMarketDataProcessor(self.config)
    
    def test_data_loader(self):
        """測試數據加載器"""
        # 測試加載每日價格數據
        df = self.loader.load_daily_price('20240101')
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
        self.assertEqual(str(df.iloc[0]['證券代號']), '2330')
        
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
        # 測試數據一致性檢查
        is_consistent = self.processor.check_data_consistency()
        self.assertTrue(is_consistent)
        
        # 測試報告生成
        report_generated = self.processor.generate_report()
        self.assertTrue(report_generated)
    
    def test_backup_mechanism(self):
        """測試備份機制"""
        # 創建測試文件
        test_file = Path(self.test_dir) / "test.csv"
        test_data = pd.DataFrame({'test': [1, 2, 3]})
        test_data.to_csv(test_file, index=False)
        
        # 測試創建備份
        backup_file = self.config.create_backup(test_file)
        self.assertIsNotNone(backup_file)
        self.assertTrue(backup_file.exists())
        
        # 測試備份文件命名
        self.assertTrue(backup_file.name.startswith("test_"))
        self.assertTrue(backup_file.name.endswith(".csv"))
    
    def test_data_integrity(self):
        """測試數據完整性與合併"""
        # 測試合併每日價格數據
        merged_df = self.loader.merge_daily_data()
        self.assertIsNotNone(merged_df)
        self.assertEqual(len(merged_df), 1)
        self.assertEqual(merged_df.iloc[0]['證券代號'], '2330')
        self.assertEqual(merged_df.iloc[0]['日期'], '20240101')
        
        # 驗證合併後的檔案路徑存在
        self.assertTrue(self.config.all_stocks_data_file.exists())
    
    def test_error_handling(self):
        """測試錯誤處理"""
        # 測試加載不存在的每日價格數據
        df = self.loader.load_daily_price('99999999')
        self.assertIsNone(df)
        
        # 測試驗證無效的股票基本資料格式
        invalid_df = pd.DataFrame({'invalid': [1, 2, 3]})
        is_valid = self.loader.validate_stock_data(invalid_df)
        self.assertFalse(is_valid)

if __name__ == '__main__':
    unittest.main()