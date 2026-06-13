import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from app_module.recommendation_service import RecommendationService
from app_module.recommendation_errors import RecommendationUniverseTooSmallError
from data_module.config import TWStockConfig

@pytest.fixture
def mock_config():
    config = MagicMock(spec=TWStockConfig)
    config.use_sqlite = False
    config.stock_data_file = MagicMock()
    config.stock_data_file.exists.return_value = True
    config.stock_data_file.stat.return_value.st_size = 1024
    config.all_stocks_data_file = MagicMock()
    config.all_stocks_data_file.exists.return_value = False
    return config

@pytest.fixture
def mock_stock_data():
    dates = pd.date_range("2026-05-01", periods=20)
    rows = []
    # 4 支股票，各有 20 筆資料
    for i in range(4):
        for d in dates:
            rows.append({
                "日期": d,
                "證券代號": f"STOCK_{i}",
                "證券名稱": f"STOCK_{i}_NAME",
                "收盤價": 100.0,
                "成交股數": 1000,
            })
    return pd.DataFrame(rows)

@patch("pandas.read_csv")
def test_recommendation_service_fixed_mode_keeps_original_behavior(mock_read_csv, mock_config, mock_stock_data):
    mock_read_csv.return_value = mock_stock_data
    service = RecommendationService(mock_config, industry_mapper=MagicMock())
    
    # Mock generate_recommendations
    def side_effect(stock_df, config):
        stock_code = stock_df["證券代號"].iloc[0]
        # STOCK_1 和 STOCK_2 同分 (70.0)
        scores = {
            "STOCK_0": 50.0,
            "STOCK_1": 70.0,
            "STOCK_2": 70.0,
            "STOCK_3": 90.0,
        }
        return pd.DataFrame({
            "TotalScore": [scores[stock_code]],
            "FinalScore": [scores[stock_code]],
            "收盤價": [100.0],
            "成交股數": [1000],
        })
    service.strategy_configurator.generate_recommendations = side_effect
    
    # 預設 fixed 模式
    recs = service.run_recommendation(
        config={"recommendation_ranking": {"threshold_mode": "fixed"}},
        top_n=4
    )
    
    # 檢查長度與排序（降序）
    assert len(recs) == 4
    assert recs[0].stock_code == "STOCK_3"  # 90.0
    # 在 fixed 模式下，同分 (70.0) 保持原有的穩定順序（依據 processing 順序 STOCK_1, STOCK_2）
    assert recs[1].stock_code == "STOCK_1"
    assert recs[2].stock_code == "STOCK_2"
    assert recs[3].stock_code == "STOCK_0"  # 50.0
    
    # 檢查沒有寫入 percentile metadata
    assert recs[0].score_percentile_bp is None
    assert recs[0].threshold_mode == "fixed"

@patch("pandas.read_csv")
def test_recommendation_service_quantile_mode_calculates_percentile_and_stable_sort(mock_read_csv, mock_config, mock_stock_data):
    mock_read_csv.return_value = mock_stock_data
    service = RecommendationService(mock_config, industry_mapper=MagicMock())
    
    def side_effect(stock_df, config):
        stock_code = stock_df["證券代號"].iloc[0]
        scores = {
            "STOCK_0": 50.0,
            "STOCK_1": 70.0,
            "STOCK_2": 70.0,
            "STOCK_3": 90.0,
        }
        return pd.DataFrame({
            "TotalScore": [scores[stock_code]],
            "FinalScore": [scores[stock_code]],
            "收盤價": [100.0],
            "成交股數": [1000],
        })
    service.strategy_configurator.generate_recommendations = side_effect
    
    # 執行 quantile 推薦，最低百分位為 50% (5000 bp)，最小母體設為 3 檔
    recs = service.run_recommendation(
        config={
            "recommendation_ranking": {
                "threshold_mode": "quantile",
                "recommendation_min_percentile_bp": 5000,
                "recommendation_min_universe_size": 3,
                "recommendation_ranking_method": "nearest_rank"
            }
        },
        top_n=4
    )
    
    # 母體中有 4 檔。
    # 百分位計算結果：
    # STOCK_0 (5000) -> 2500 (25%) -> 被過濾
    # STOCK_1 (7000) -> 7500 (75%) -> 保留
    # STOCK_2 (7000) -> 7500 (75%) -> 保留
    # STOCK_3 (9000) -> 10000 (100%) -> 保留
    assert len(recs) == 3
    assert recs[0].stock_code == "STOCK_3"
    assert recs[0].score_percentile_bp == 10000
    
    # 檢查同分穩定排序（由 stock_code 升序穩定，但在此例中本來就是 STOCK_1, STOCK_2）
    assert recs[1].stock_code == "STOCK_1"
    assert recs[1].score_percentile_bp == 7500
    assert recs[2].stock_code == "STOCK_2"
    assert recs[2].score_percentile_bp == 7500
    
    # 驗證其他 metadata
    assert recs[0].threshold_mode == "quantile"
    assert recs[0].eligible_universe_size == 4
    assert recs[0].eligible_universe_date == "2026-05-20"
    assert recs[0].ranking_method == "nearest_rank"


@patch("pandas.read_csv")
@pytest.mark.parametrize("ranking_config", [
    {"threshold_mode": "unknown"},
    {
        "threshold_mode": "quantile",
        "recommendation_min_universe_size": 3,
        "recommendation_ranking_method": "nearest_rank",
    },
    {
        "threshold_mode": "quantile",
        "recommendation_min_percentile_bp": 8000,
        "recommendation_ranking_method": "nearest_rank",
    },
    {
        "threshold_mode": "quantile",
        "recommendation_min_percentile_bp": 8000,
        "recommendation_min_universe_size": 3,
    },
    {
        "threshold_mode": "quantile",
        "recommendation_min_percentile_bp": 10001,
        "recommendation_min_universe_size": 3,
        "recommendation_ranking_method": "nearest_rank",
    },
    {
        "threshold_mode": "quantile",
        "recommendation_min_percentile_bp": 8000,
        "recommendation_min_universe_size": 3,
        "recommendation_ranking_method": "linear",
    },
])
def test_recommendation_ranking_rejects_invalid_or_incomplete_config(
    mock_read_csv,
    mock_config,
    mock_stock_data,
    ranking_config,
):
    mock_read_csv.return_value = mock_stock_data
    service = RecommendationService(mock_config, industry_mapper=MagicMock())

    with pytest.raises(ValueError):
        service.run_recommendation(config={"recommendation_ranking": ranking_config})

@patch("pandas.read_csv")
def test_recommendation_service_quantile_mode_universe_too_small_raises_exception(mock_read_csv, mock_config, mock_stock_data):
    mock_read_csv.return_value = mock_stock_data
    service = RecommendationService(mock_config, industry_mapper=MagicMock())
    
    # 只返回一檔
    def side_effect(stock_df, config):
        return pd.DataFrame({
            "TotalScore": [80.0],
            "FinalScore": [80.0],
            "收盤價": [100.0],
            "成交股數": [1000],
        })
    service.strategy_configurator.generate_recommendations = side_effect
    
    # 母體設為 5 檔，而我們只有 4 檔，應拋出異常
    with pytest.raises(RecommendationUniverseTooSmallError) as exc_info:
        service.run_recommendation(
            config={
                "recommendation_ranking": {
                    "threshold_mode": "quantile",
                    "recommendation_min_percentile_bp": 5000,
                    "recommendation_min_universe_size": 5,
                    "recommendation_ranking_method": "nearest_rank",
                }
            }
        )
    assert exc_info.value.actual_size == 4
    assert exc_info.value.minimum_size == 5

@patch("pandas.read_csv")
def test_recommendation_service_quantile_mode_top_n_does_not_affect_percentile_calculation(mock_read_csv, mock_config, mock_stock_data):
    mock_read_csv.return_value = mock_stock_data
    service = RecommendationService(mock_config, industry_mapper=MagicMock())
    
    def side_effect(stock_df, config):
        stock_code = stock_df["證券代號"].iloc[0]
        scores = {
            "STOCK_0": 50.0,
            "STOCK_1": 70.0,
            "STOCK_2": 70.0,
            "STOCK_3": 90.0,
        }
        return pd.DataFrame({
            "TotalScore": [scores[stock_code]],
            "FinalScore": [scores[stock_code]],
            "收盤價": [100.0],
            "成交股數": [1000],
        })
    service.strategy_configurator.generate_recommendations = side_effect
    
    # 限制 top_n = 1，這不應該影響百分位是基於 4 檔母體計算
    recs = service.run_recommendation(
        config={
            "recommendation_ranking": {
                "threshold_mode": "quantile",
                "recommendation_min_percentile_bp": 5000,
                "recommendation_min_universe_size": 3,
                "recommendation_ranking_method": "nearest_rank",
            }
        },
        top_n=1
    )
    
    assert len(recs) == 1
    assert recs[0].stock_code == "STOCK_3"
    assert recs[0].score_percentile_bp == 10000  # 依然是 100%
    assert recs[0].eligible_universe_size == 4
