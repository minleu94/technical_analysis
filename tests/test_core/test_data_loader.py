import pytest
import pandas as pd
from pathlib import Path
from data_module.data_loader import DataLoader


class _DummyResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FallbackSession:
    def __init__(self):
        self.requested_types = []

    def get(self, url, params=None, headers=None, timeout=None):
        if not params:
            return _DummyResponse()
        request_type = params.get("type")
        self.requested_types.append(request_type)
        if request_type == "ALL":
            return _DummyResponse(payload={"stat": "查詢日期大於今日，請重新查詢!"})
        if request_type == "ALLBUT0999":
            return _DummyResponse(
                payload={
                    "stat": "OK",
                    "tables": [
                        {},
                        {},
                        {},
                        {},
                        {},
                        {},
                        {},
                        {},
                        {
                            "fields": [
                                "證券代號",
                                "證券名稱",
                                "成交股數",
                                "成交筆數",
                                "成交金額",
                                "開盤價",
                                "最高價",
                                "最低價",
                                "收盤價",
                                "漲跌(+/-)",
                                "漲跌價差",
                                "最後揭示買價",
                                "最後揭示買量",
                                "最後揭示賣價",
                                "最後揭示賣量",
                                "本益比",
                            ],
                            "data": [
                                [
                                    "2330",
                                    "台積電",
                                    "1,000",
                                    "10",
                                    "500,000",
                                    "500.00",
                                    "510.00",
                                    "499.00",
                                    "505.00",
                                    "<p style= color:red>+</p>",
                                    "5.00",
                                    "505.00",
                                    "1",
                                    "506.00",
                                    "2",
                                    "20.00",
                                ]
                            ],
                        },
                    ],
                }
            )
        return _DummyResponse(status_code=404)

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
        market_data = sample_market_data.rename(
            columns={"date": "日期", "close": "收盤指數"}
        )
        test_file = test_config.meta_data_dir / "market_index.csv"
        market_data.to_csv(test_file, index=False, encoding="utf-8-sig")
        
        # 測試加載
        loader = DataLoader(test_config)
        df = loader.load_market_index()
        assert df is not None
        assert len(df) > 0
        assert '日期' in df.columns
        assert '收盤指數' in df.columns
    
    def test_load_industry_index(self, test_config, sample_index_data):
        """測試加載產業指數"""
        # 保存測試數據
        industry_data = sample_index_data.rename(
            columns={"date": "日期", "index_name": "指數名稱"}
        )
        test_file = test_config.meta_data_dir / "industry_index.csv"
        industry_data.to_csv(test_file, index=False, encoding="utf-8-sig")
        
        # 測試加載
        loader = DataLoader(test_config)
        df = loader.load_industry_index()
        assert df is not None
        assert len(df) > 0
        assert '日期' in df.columns
        assert '指數名稱' in df.columns
    
    def test_load_nonexistent_file(self, test_config):
        """測試加載不存在的文件"""
        loader = DataLoader(test_config)
        df = loader.load_daily_price('99999999')
        assert df is None

    def test_download_daily_price_falls_back_to_allbut0999_when_all_has_no_data(self, test_config, monkeypatch):
        session = _FallbackSession()
        monkeypatch.setattr("data_module.data_loader.requests.Session", lambda: session)
        monkeypatch.setattr("data_module.data_loader.time.sleep", lambda _seconds: None)
        monkeypatch.setattr("data_module.data_loader.random.uniform", lambda _start, _end: 0)

        loader = DataLoader(test_config)
        df = loader.download_from_api("2026-07-02")

        assert df is not None
        assert session.requested_types == ["ALL", "ALLBUT0999"]
        assert len(df) == 1
        assert (test_config.daily_price_dir / "20260702.csv").exists()
    
    @pytest.mark.data
    def test_data_validation(self, test_config, sample_stock_data):
        """測試數據驗證"""
        loader = DataLoader(test_config)
        valid_df = pd.DataFrame(
            {
                "證券代號": ["2330", "2317"],
                "證券名稱": ["台積電", "鴻海"],
            }
        )
        assert loader.validate_stock_data(valid_df)
        
        # 測試無效數據
        invalid_df = pd.DataFrame({'invalid': [1, 2, 3]})
        assert not loader.validate_stock_data(invalid_df)
