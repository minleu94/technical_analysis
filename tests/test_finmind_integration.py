import unittest
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path
import shutil
import os
import importlib.util
import sys
import finmind


# 動態導入模組
spec = importlib.util.spec_from_file_location("stock_collector", "01_stock_data_collector_enhanced.py")
stock_collector = importlib.util.module_from_spec(spec)
sys.modules["stock_collector"] = stock_collector
spec.loader.exec_module(stock_collector)

from stock_collector import TWMarketDataProcessor, MarketDateRange, TWStockConfig

class TestFinMindIntegration(unittest.TestCase):
    """測試 FinMind 整合"""
    
    def setUp(self):
        """測試前的設置"""
        # 創建臨時測試目錄
        self.test_dir = Path("test_data")
        self.test_dir.mkdir(exist_ok=True)
        
        # 創建測試用的配置
        self.config = TWStockConfig()
        self.config.base_dir = self.test_dir
        
        # 設定測試日期範圍（最近7天）
        self.date_range = MarketDateRange.last_n_days(7)
        
        # 創建處理器實例
        self.processor = TWMarketDataProcessor(
            config=self.config,
            date_range=self.date_range
        )
    
    def tearDown(self):
        """測試後的清理"""
        # 刪除測試目錄及其內容
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_finmind_market_index(self):
        """測試 FinMind 大盤指數數據獲取"""
        # 執行更新
        result = self.processor.update_market_index()
        
        # 驗證結果
        self.assertTrue(result, "大盤指數更新應該成功")
        
        # 檢查檔案是否存在
        self.assertTrue(self.config.market_index_file.exists(), "大盤指數檔案應該被創建")
        
        # 讀取並驗證數據
        df = pd.read_csv(self.config.market_index_file)
        
        # 驗證必要的列是否存在
        required_columns = ['日期', '開盤價', '最高價', '最低價', '收盤價', '成交量']
        for col in required_columns:
            self.assertIn(col, df.columns, f"數據中應該包含 {col} 列")
        
        # 驗證數據格式
        self.assertTrue(pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d').equals(df['日期']), 
                       "日期格式應該為 YYYY-MM-DD")
        
        # 驗證數值格式
        numeric_columns = ['開盤價', '最高價', '最低價', '收盤價']
        for col in numeric_columns:
            self.assertTrue(pd.to_numeric(df[col], errors='coerce').notnull().all(),
                          f"{col} 應該都是有效的數值")
        
        # 驗證數據範圍
        self.assertTrue(len(df) > 0, "應該至少有一筆數據")
        
        # 驗證日期範圍
        dates = pd.to_datetime(df['日期'])
        self.assertTrue(dates.min() >= pd.to_datetime(self.date_range.start_date),
                       "數據日期不應該早於開始日期")
        self.assertTrue(dates.max() <= pd.to_datetime(self.date_range.end_date),
                       "數據日期不應該晚於結束日期")
    
    def test_data_consistency(self):
        """測試數據一致性"""
        # 執行兩次更新
        result1 = self.processor.update_market_index()
        result2 = self.processor.update_market_index()
        
        # 驗證兩次更新都成功
        self.assertTrue(result1 and result2, "兩次更新都應該成功")
        
        # 讀取兩次更新後的數據
        df1 = pd.read_csv(self.config.market_index_file)
        
        # 驗證數據沒有重複
        self.assertEqual(len(df1), len(df1.drop_duplicates(subset=['日期'])),
                        "數據中不應該有重複的日期")
        
        # 驗證數據按日期排序
        self.assertTrue(df1['日期'].is_monotonic_increasing,
                        "數據應該按日期排序")
    
    def test_error_handling(self):
        """測試錯誤處理"""
        # 測試無效的日期範圍
        invalid_date_range = MarketDateRange(
            start_date="2024-12-31",  # 未來的日期
            end_date="2024-12-31"
        )
        processor = TWMarketDataProcessor(
            config=self.config,
            date_range=invalid_date_range
        )
        
        # 執行更新
        result = processor.update_market_index()
        
        # 驗證結果
        self.assertFalse(result, "使用無效日期範圍應該返回 False")
        
        # 驗證沒有創建檔案
        self.assertFalse(self.config.market_index_file.exists(),
                        "使用無效日期範圍不應該創建檔案")

def main():
    # 執行測試
    unittest.main(verbosity=2)

if __name__ == '__main__':
    main() 