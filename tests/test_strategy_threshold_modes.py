import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch

from app_module.strategy_spec import StrategySpec
from app_module.strategies.baseline_score_executor import BaselineScoreExecutor
from app_module.strategies.momentum_aggressive_executor import MomentumAggressiveExecutor
from app_module.strategies.stable_conservative_executor import StableConservativeExecutor

def make_dummy_data(days=100) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days)
    return pd.DataFrame({
        '開盤價': [100.0] * days,
        '最高價': [105.0] * days,
        '最低價': [95.0] * days,
        '收盤價': [100.0] * days,
        '成交股數': [1000000.0] * days,
    }, index=dates)

@pytest.mark.parametrize("executor_cls, default_buy, default_sell", [
    (BaselineScoreExecutor, 60.0, 40.0),
    (MomentumAggressiveExecutor, 70.0, 50.0),
    (StableConservativeExecutor, 55.0, 40.0),
])
def test_fixed_and_missing_modes_are_identical(executor_cls, default_buy, default_sell):
    df = make_dummy_data(100)
    
    # 構造一個固定的分數序列
    scores = [50.0] * 20 + [80.0] * 10 + [50.0] * 20 + [20.0] * 10 + [50.0] * 40
    
    def mock_calculate_total_score(df_arg, config_arg, regime=None):
        res = df_arg.copy()
        res['IndicatorScore'] = pd.Series(scores, index=df_arg.index)
        res['PatternScore'] = pd.Series(50.0, index=df_arg.index)
        res['VolumeScore'] = pd.Series(50.0, index=df_arg.index)
        res['TotalScore'] = pd.Series(scores, index=df_arg.index)
        res['RegimeMatch'] = pd.Series(True, index=df_arg.index)
        return res

    # Config 1: 缺少 threshold_mode
    spec1 = StrategySpec(
        strategy_id="test_missing",
        strategy_version="1.0",
        config={
            'params': {
                'buy_score': default_buy,
                'sell_score': default_sell,
                'buy_confirm_days': 2,
                'sell_confirm_days': 2,
                'cooldown_days': 2
            }
        }
    )
    
    # Config 2: 明確 fixed
    spec2 = StrategySpec(
        strategy_id="test_fixed",
        strategy_version="1.0",
        config={
            'params': {
                'threshold_mode': 'fixed',
                'buy_score': default_buy,
                'sell_score': default_sell,
                'buy_confirm_days': 2,
                'sell_confirm_days': 2,
                'cooldown_days': 2
            }
        }
    )
    
    executor1 = executor_cls(spec1)
    executor2 = executor_cls(spec2)
    
    with patch.object(executor1.scoring_engine, 'calculate_total_score', side_effect=mock_calculate_total_score), \
         patch.object(executor2.scoring_engine, 'calculate_total_score', side_effect=mock_calculate_total_score):
        
        sf1 = executor1.generate_signals(df, spec1)
        sf2 = executor2.generate_signals(df, spec2)
        
        # 訊號應完全相同
        pd.testing.assert_series_equal(sf1['signal'], sf2['signal'])

@pytest.mark.parametrize("executor_cls, default_buy, default_sell", [
    (BaselineScoreExecutor, 60.0, 40.0),
    (MomentumAggressiveExecutor, 70.0, 50.0),
    (StableConservativeExecutor, 55.0, 40.0),
])
def test_known_fixed_signal_series(executor_cls, default_buy, default_sell):
    # 用一個簡短的序列，驗證 fixed 模式產生的具體買賣點符合預期
    df = make_dummy_data(15)
    # 買入門檻以 60/70/55 為例。我們在第 5, 6 天給出高分，在第 11, 12 天給出低分
    scores = [50.0] * 4 + [80.0] * 3 + [50.0] * 3 + [20.0] * 3 + [50.0] * 2
    
    def mock_calculate_total_score(df_arg, config_arg, regime=None):
        res = df_arg.copy()
        res['IndicatorScore'] = pd.Series(scores, index=df_arg.index)
        res['PatternScore'] = pd.Series(50.0, index=df_arg.index)
        res['VolumeScore'] = pd.Series(50.0, index=df_arg.index)
        res['TotalScore'] = pd.Series(scores, index=df_arg.index)
        res['RegimeMatch'] = pd.Series(True, index=df_arg.index)
        return res

    spec = StrategySpec(
        strategy_id="test_fixed_known",
        strategy_version="1.0",
        config={
            'params': {
                'threshold_mode': 'fixed',
                'buy_score': default_buy,
                'sell_score': default_sell,
                'buy_confirm_days': 2,
                'sell_confirm_days': 2,
                'cooldown_days': 1
            }
        }
    )
    
    executor = executor_cls(spec)
    with patch.object(executor.scoring_engine, 'calculate_total_score', side_effect=mock_calculate_total_score):
        sf = executor.generate_signals(df, spec)
        # 由於 buy_confirm_days = 2：
        # 第 5, 6 天為高分(80.0)，所以在第 6 天(index 5)確認買入訊號(1)
        # 第 11, 12 天為低分(20.0)，所以在第 12 天(index 11)確認賣出訊號(-1)
        assert sf['signal'].iloc[5] == 1
        expected_sell_idx = 8 if default_sell >= 50.0 else 11
        assert sf['signal'].iloc[expected_sell_idx] == -1
        assert (sf['signal'] == 1).sum() == 1
        assert (sf['signal'] == -1).sum() == 1

@pytest.mark.parametrize("executor_cls", [
    (BaselineScoreExecutor),
    (MomentumAggressiveExecutor),
    (StableConservativeExecutor),
])
def test_quantile_mode_warmup_required(executor_cls):
    # 測試 quantile 模式下，第 61 個觀測值（index 60）前不可有任何交易訊號，且 warmup_ready 為 False
    df = make_dummy_data(100)
    # 前 59 天是 50.0 (暖機值為 60)，第 60、61 天（index 59, 60）是高分 90.0，第 62、63 天（index 61, 62）也是高分 90.0
    scores = [50.0] * 59 + [90.0] * 41
    
    def mock_calculate_total_score(df_arg, config_arg, regime=None):
        res = df_arg.copy()
        res['TotalScore'] = pd.Series(scores, index=df_arg.index)
        res['IndicatorScore'] = pd.Series(50.0, index=df_arg.index)
        res['PatternScore'] = pd.Series(50.0, index=df_arg.index)
        res['VolumeScore'] = pd.Series(50.0, index=df_arg.index)
        res['RegimeMatch'] = pd.Series(True, index=df_arg.index)
        return res

    spec = StrategySpec(
        strategy_id="test_quantile_warmup",
        strategy_version="1.0",
        config={
            'params': {
                'threshold_mode': 'quantile',
                'buy_quantile_bp': 8000,
                'sell_quantile_bp': 4000,
                'quantile_warmup_observations': 60,
                'quantile_method': 'nearest_rank',
                'buy_confirm_days': 2,
                'sell_confirm_days': 2,
                'cooldown_days': 2
            }
        }
    )
    
    executor = executor_cls(spec)
    with patch.object(executor.scoring_engine, 'calculate_total_score', side_effect=mock_calculate_total_score):
        sf = executor.generate_signals(df, spec)
        
        # 由於第 60 個有效觀測值以前（index < 60）處於暖機中：
        # index 60 是第 61 天，也就是第一個可能具有 buy_threshold_score_bp 且 warmup_ready=True 的天
        # 由於 buy_confirm_days = 2，所以 index 60 與 index 61 都必須符合條件，在 index 61 才能確認買入訊號。
        # 因此，在 index < 61 前均為 0 訊號。
        assert not (sf['signal'].iloc[:61] != 0).any()
        assert bool(sf['threshold_warmup_ready'].iloc[60]) is True
        assert bool(sf['threshold_warmup_ready'].iloc[59]) is False

@pytest.mark.parametrize("executor_cls", [
    (BaselineScoreExecutor),
    (MomentumAggressiveExecutor),
    (StableConservativeExecutor),
])
def test_quantile_look_ahead_bias_prevention(executor_cls):
    # 測試未來資料附加，不改變已計算之 thresholds 與 signals
    original_df = make_dummy_data(70)
    extended_df = make_dummy_data(100)
    
    scores_original = list(range(10, 80))  # 70 days
    scores_extended = scores_original + [100.0] * 30
    
    def mock_calculate_original_score(df_arg, config_arg, regime=None):
        res = df_arg.copy()
        res['TotalScore'] = pd.Series(scores_original, index=df_arg.index)
        res['IndicatorScore'] = pd.Series(50.0, index=df_arg.index)
        res['PatternScore'] = pd.Series(50.0, index=df_arg.index)
        res['VolumeScore'] = pd.Series(50.0, index=df_arg.index)
        res['RegimeMatch'] = pd.Series(True, index=df_arg.index)
        return res
        
    def mock_calculate_extended_score(df_arg, config_arg, regime=None):
        res = df_arg.copy()
        res['TotalScore'] = pd.Series(scores_extended, index=df_arg.index)
        res['IndicatorScore'] = pd.Series(50.0, index=df_arg.index)
        res['PatternScore'] = pd.Series(50.0, index=df_arg.index)
        res['VolumeScore'] = pd.Series(50.0, index=df_arg.index)
        res['RegimeMatch'] = pd.Series(True, index=df_arg.index)
        return res

    spec = StrategySpec(
        strategy_id="test_quantile_lookahead",
        strategy_version="1.0",
        config={
            'params': {
                'threshold_mode': 'quantile',
                'buy_quantile_bp': 8000,
                'sell_quantile_bp': 4000,
                'quantile_warmup_observations': 60,
                'quantile_method': 'nearest_rank',
                'buy_confirm_days': 2,
                'sell_confirm_days': 2,
                'cooldown_days': 2
            }
        }
    )
    
    executor_orig = executor_cls(spec)
    executor_ext = executor_cls(spec)
    
    with patch.object(executor_orig.scoring_engine, 'calculate_total_score', side_effect=mock_calculate_original_score), \
         patch.object(executor_ext.scoring_engine, 'calculate_total_score', side_effect=mock_calculate_extended_score):
         
        sf_orig = executor_orig.generate_signals(original_df, spec)
        sf_ext = executor_ext.generate_signals(extended_df, spec)
        
        # 比較前 70 筆
        pd.testing.assert_series_equal(sf_orig['signal'], sf_ext['signal'].iloc[:70], check_names=False)
        pd.testing.assert_series_equal(sf_orig['buy_threshold_score_bp'], sf_ext['buy_threshold_score_bp'].iloc[:70], check_names=False)
        pd.testing.assert_series_equal(sf_orig['sell_threshold_score_bp'], sf_ext['sell_threshold_score_bp'].iloc[:70], check_names=False)
