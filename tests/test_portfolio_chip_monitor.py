"""Unit tests for PortfolioChipService.
"""

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

from app_module.portfolio_chip_service import PortfolioChipService
from data_module.config import TWStockConfig
from app_module.dtos.broker_flow_dtos import BrokerFlowEvent


class TestPortfolioChipService(unittest.TestCase):

    def setUp(self):
        self.config = MagicMock(spec=TWStockConfig)
        self.config.broker_branch_registry_file = MagicMock()
        self.config.broker_branch_registry_file.exists.return_value = False
        self.config.use_sqlite = False
        
        self.broker_flow_service = MagicMock()
        self.service = PortfolioChipService(self.config, self.broker_flow_service)

    def test_empty_summary(self):
        # 測試在無交易數據時，返回正確的空摘要結構
        summary = self.service._empty_summary("2330", 5)
        self.assertEqual(summary['stock_code'], "2330")
        self.assertEqual(summary['accumulated_buy'], 0)
        self.assertEqual(summary['accumulated_sell'], 0)
        self.assertEqual(summary['accumulated_net'], 0)
        self.assertEqual(summary['concentration'], 0.0)
        self.assertEqual(summary['consecutive_days'], 0)
        self.assertEqual(summary['risk_level'], 'neutral')
        self.assertIn("無主力分點交易數據", summary['risk_reasons'])

    def test_aggregate_flow_dataframe_neutral(self):
        # 測試正常/溫和的買賣超聚合計算
        df = pd.DataFrame([
            {'日期': '20260611', '分點名稱': 'branch_a', '買進股數': 10000, '賣出股數': 5000, '買賣超股數': 5000},
            {'日期': '20260611', '分點名稱': 'branch_b', '買進股數': 20000, '賣出股數': 25000, '買賣超股數': -5000},
        ])
        
        summary = self.service._aggregate_flow_dataframe(df, "2330", 5, ["20260611"])
        
        self.assertEqual(summary['accumulated_buy'], 30000)
        self.assertEqual(summary['accumulated_sell'], 30000)
        self.assertEqual(summary['accumulated_net'], 0)
        self.assertEqual(summary['concentration'], 0.0)
        self.assertEqual(summary['risk_level'], 'neutral')
        self.assertEqual(len(summary['branch_details']), 2)

    def test_aggregate_flow_dataframe_bullish_large_buy(self):
        # 測試大額淨買超觸發 bullish 警示
        df = pd.DataFrame([
            {'日期': '20260611', '分點名稱': 'branch_a', '買進股數': 600000, '賣出股數': 50000, '買賣超股數': 550000},
        ])
        
        summary = self.service._aggregate_flow_dataframe(df, "2330", 5, ["20260611"])
        
        self.assertEqual(summary['accumulated_net'], 550000)
        self.assertEqual(summary['risk_level'], 'bullish')
        self.assertTrue(any("累計大額買進" in reason for reason in summary['risk_reasons']))

    def test_consecutive_selling_bearish(self):
        # 測試連續 3 天淨賣超觸發 bearish 警示
        df = pd.DataFrame([
            {'日期': '20260611', '分點名稱': 'branch_a', '買進股數': 1000, '賣出股數': 5000, '買賣超股數': -4000},
            {'日期': '20260610', '分點名稱': 'branch_a', '買進股數': 1000, '賣出股數': 6000, '買賣超股數': -5000},
            {'日期': '20260609', '分點名稱': 'branch_a', '買進股數': 1000, '賣出股數': 7000, '買賣超股數': -6000},
        ])
        
        summary = self.service._aggregate_flow_dataframe(df, "2330", 5, ["20260611", "20260610", "20260609"])
        
        self.assertEqual(summary['consecutive_days'], -3)
        self.assertEqual(summary['risk_level'], 'bearish')
        self.assertTrue(any("連續 3 日淨出貨" in reason for reason in summary['risk_reasons']))

    @patch('data_module.db_manager.DBManager')
    def test_sqlite_query_flow(self, mock_db_class):
        # 測試 SQLite 模式下的查詢流
        self.config.use_sqlite = True
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db
        
        # 模擬日期返回
        mock_db.execute_query.side_effect = [
            pd.DataFrame({'日期': ['20260611']}), # 交易日期
            pd.DataFrame([ # 明細數據
                {'日期': '20260611', '分點名稱': 'branch_a', '買進股數': 100000, '賣出股數': 50000, '買賣超股數': 50000}
            ])
        ]
        
        summary = self.service.get_stock_chip_summary("2330", 5)
        
        self.assertEqual(summary['stock_code'], "2330")
        self.assertEqual(summary['accumulated_net'], 50000)
        self.assertEqual(summary['concentration'], 50000 / 150000)

    def test_csv_fallback_flow(self):
        # 測試 CSV 降級模式下的數據查詢
        self.config.use_sqlite = False
        
        self.broker_flow_service._load_data.return_value = [
            BrokerFlowEvent(
                date='2026-06-11',
                branch_system_key='branch_a',
                branch_display_name='分點A',
                stock_code='2330',
                stock_name='台積電',
                buy_qty=100,  # 100張 = 100,000股
                sell_qty=20,   # 20張 = 20,000股
                net_qty=80     # 80張 = 80,000股
            )
        ]
        
        summary = self.service.get_stock_chip_summary("2330", 5)
        
        self.assertEqual(summary['stock_code'], "2330")
        self.assertEqual(summary['accumulated_buy'], 100000)
        self.assertEqual(summary['accumulated_sell'], 20000)
        self.assertEqual(summary['accumulated_net'], 80000)
        self.assertEqual(summary['concentration'], 80000 / 120000)


if __name__ == '__main__':
    unittest.main()
