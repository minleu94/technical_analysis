import pytest
import pandas as pd
import numpy as np
from decimal import Decimal
import json
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.indicator_parameter_registry import IndicatorParameterRegistry, InvalidParameterError
from decision_module.weight_contract import RecommendationWeightContract, InvalidWeightError
from decision_module.scoring_engine import ScoringEngine

def copy_config(cfg):
    return json.loads(json.dumps(cfg))

@pytest.fixture
def sample_stock_df():
    """建立包含足夠歷史資料的 Mock DataFrame，以供指標計算"""
    np.random.seed(42)
    n_days = 80
    dates = pd.date_range(start="2026-01-01", periods=n_days, freq="D")
    
    # 建立隨機價格
    close = 100.0 + np.cumsum(np.random.normal(0, 2, n_days))
    high = close + np.random.uniform(0.5, 2.0, n_days)
    low = close - np.random.uniform(0.5, 2.0, n_days)
    open_p = close + np.random.normal(0, 1, n_days)
    volume = np.random.randint(1000, 10000, n_days)
    
    df = pd.DataFrame({
        '日期': dates.strftime('%Y-%m-%d'),
        '證券代號': '2330',
        '開盤價': open_p,
        '最高價': high,
        '最低價': low,
        '收盤價': close,
        '成交股數': volume
    })
    return df

def test_mixed_enable_disable_configuration(sample_stock_df):
    """測試混合啟用/停用配置。停用的指標不應報錯且應跳過計算"""
    configurator = StrategyConfigurator()
    
    # 新版配置：停用 rsi，但啟用 macd 與 kd (必須給齊 macd 與 kd 參數)
    config = {
        'config_schema_version': 1,
        'weights': {
            'pattern': 3000,
            'technical': 5000,
            'volume': 2000
        },
        'technical': {
            'momentum': {
                'enabled': True,
                'rsi': {
                    'enabled': False
                },
                'macd': {
                    'enabled': True,
                    'fastperiod': 12,
                    'slowperiod': 26,
                    'signalperiod': 9
                },
                'kd': {
                    'enabled': True,
                    'fastk_period': 5,
                    'slowk_period': 3,
                    'slowd_period': 3,
                    'slowk_matype': 0,
                    'slowd_matype': 0
                }
            }
        },
        'patterns': {
            'selected': []
        }
    }
    
    # 執行推薦，應能順利完成而不拋出 rsi 參數缺失的 InvalidParameterError
    result_df = configurator.generate_recommendations(sample_stock_df, config)
    
    assert not result_df.empty
    # 驗證 MACD 有計算，但 RSI 沒有計算
    latest_row = result_df.iloc[-1]
    assert 'MACD' in latest_row
    assert 'RSI' not in latest_row or pd.isna(latest_row['RSI']) or latest_row['RSI'] == 50.0  # 50.0 是無 RSI 時的預設中性

def test_strict_type_and_unknown_key_rejection():
    """測試嚴格的型別校驗與未知欄位拒絕"""
    # 1. 拒絕 config_schema_version 為 bool
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize(
            'rsi', 
            {'timeperiod': 14}, 
            full_config={'config_schema_version': True}
        )
        
    # 2. 拒絕 config_schema_version 為浮點數
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize(
            'rsi', 
            {'timeperiod': 14}, 
            full_config={'config_schema_version': 1.5}
        )

    # 3. 拒絕 config_schema_version 為非數字字串
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize(
            'rsi', 
            {'timeperiod': 14}, 
            full_config={'config_schema_version': 'abc'}
        )

    # 4. 拒絕指標參數為 bool
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize(
            'rsi', 
            {'timeperiod': True}, 
            full_config={'config_schema_version': 1}
        )

    # 5. 拒絕指標參數為負數
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize(
            'rsi', 
            {'timeperiod': -5}, 
            full_config={'config_schema_version': 1}
        )

    # 6. 拒絕未知欄位 (防拼寫錯誤)
    with pytest.raises(InvalidParameterError) as excinfo:
        # timeperiod_ 是未知欄位
        IndicatorParameterRegistry.validate_and_sanitize(
            'rsi', 
            {'timeperiod_': 14}, 
            full_config={'config_schema_version': 1}
        )
    assert "未知參數" in str(excinfo.value)

def test_weight_contract_strict_keys():
    """測試權重合約是否嚴格校驗 keys (不允許缺漏或多餘 key)"""
    # 1. 缺漏 key (缺少 volume)
    invalid_weights_missing = {
        'pattern': 5000,
        'technical': 5000
    }
    with pytest.raises(InvalidWeightError):
        RecommendationWeightContract.validate_and_enforce(invalid_weights_missing)

    # 2. 多出額外 key
    invalid_weights_extra = {
        'pattern': 3000,
        'technical': 5000,
        'volume': 2000,
        'extra_key': 0
    }
    with pytest.raises(InvalidWeightError):
        RecommendationWeightContract.validate_and_enforce(invalid_weights_extra)

def test_weight_contract_bool_rejection():
    """測試權重合約拒絕 bool 權重"""
    invalid_weights_bool = {
        'pattern': True,
        'technical': 5000,
        'volume': 4999
    }
    with pytest.raises(InvalidWeightError):
        RecommendationWeightContract.validate_and_enforce(invalid_weights_bool)

def test_scoring_engine_decimal_accuracy_and_regime_limit(sample_stock_df):
    """測試 ScoringEngine 評分精度，Regime 權重重分配之 Decimal 正確性與 10000 bp 限制"""
    engine = ScoringEngine()
    
    # 基礎權重 10000 bp
    config = {
        'weights': {
            'pattern': 3000,
            'technical': 5000,
            'volume': 2000
        },
        'technical': {
            'momentum': {
                'enabled': True,
                'rsi': {'enabled': True, 'timeperiod': 14}
            }
        }
    }
    
    # 測試 Trend regime 下的權重調整是否符合整數 bp 且總和為 10000 bp
    # 原本 Trend regime 下：
    # pattern: 3000 * 0.8 = 2400
    # technical: 5000 * 1.2 = 6000
    # volume: 2000 * 1.0 = 2000
    # 總和 10400，再 normalize_to_10000_bp
    adjusted_weights = engine._get_regime_weights('Trend', config['weights'])
    
    # 驗證調整後皆為整數 bp
    for k, v in adjusted_weights.items():
        assert isinstance(v, int)
    
    # 驗證總和固定為 10000 bp
    assert sum(adjusted_weights.values()) == 10000
    
    # 驗證 ScoringEngine 計算出的 TotalScore 沒有裸 float 正規化污染，且類型為 Decimal
    res_df = engine.calculate_total_score(sample_stock_df, config, regime='Trend')
    assert 'TotalScore' in res_df.columns
    latest_score = res_df.iloc[-1]['TotalScore']
    assert isinstance(latest_score, Decimal)
    assert 0 <= latest_score <= 100

def test_no_look_ahead_prefix_invariance(sample_stock_df):
    """測試前綴不變性 (Prefix-Invariance)，以驗證絕無未來函數 Look-ahead bias"""
    configurator = StrategyConfigurator()
    
    config = {
        'config_schema_version': 1,
        'weights': {
            'pattern': 3000,
            'technical': 5000,
            'volume': 2000
        },
        'technical': {
            'momentum': {
                'enabled': True,
                'rsi': {
                    'enabled': True,
                    'timeperiod': 14
                }
            }
        },
        'patterns': {
            'selected': []
        }
    }
    
    T = 40  # 選擇第 40 天作為基準日
    
    # 1. 僅以截止到 T 日的子資料計算
    df_short = sample_stock_df.iloc[:T+1].copy()
    res_short = configurator.generate_recommendations(df_short, config)
    score_short = res_short.iloc[0]['TotalScore']  # generate_recommendations 只回傳最新一筆的 DataFrame
    
    # 2. 以完整資料計算後，取出同一日 (T 日) 的結果
    res_long_df = configurator.configure_technical_indicators(sample_stock_df, config.get('technical', {}), full_config=config)
    res_long_df = configurator.scoring_engine.calculate_total_score(res_long_df, config)
    score_long = res_long_df.iloc[T]['TotalScore']
    
    # 3. 斷言前綴不變性，證明無 Look-ahead bias
    assert score_short == score_long
    assert isinstance(score_short, Decimal)

def test_decimal_score_type(sample_stock_df):
    """測試 TotalScore 與 FinalScore 類型為 Decimal"""
    configurator = StrategyConfigurator()
    config = {
        'config_schema_version': 1,
        'weights': {
            'pattern': 3000,
            'technical': 5000,
            'volume': 2000
        },
        'technical': {
            'momentum': {
                'enabled': True,
                'rsi': {'enabled': True, 'timeperiod': 14}
            }
        }
    }
    res_df = configurator.scoring_engine.calculate_total_score(sample_stock_df, config)
    assert 'TotalScore' in res_df.columns
    assert 'FinalScore' in res_df.columns
    for v in res_df['TotalScore'].dropna():
        assert isinstance(v, Decimal)
    for v in res_df['FinalScore'].dropna():
        assert isinstance(v, Decimal)


def test_total_score_quantizes_to_score_basis_points_with_half_up():
    """核心評分以 0.01 分為單位，並使用 ROUND_HALF_UP 決定中點。"""
    engine = ScoringEngine()
    frame = pd.DataFrame({'收盤價': [100.0]})
    score = pd.Series([Decimal('60.005')])

    engine.calculate_pattern_score = lambda df, config: score
    engine.calculate_indicator_score = lambda df, config, regime=None: pd.Series([Decimal('0')])
    engine.calculate_volume_score = lambda df, config: pd.Series([Decimal('0')])

    result = engine.calculate_total_score(
        frame,
        {
            'weights': {
                'pattern': 10000,
                'technical': 0,
                'volume': 0,
            }
        },
    )

    assert result.iloc[0]['TotalScore'] == Decimal('60.01')
    assert result.iloc[0]['FinalScore'] == Decimal('60.01')


@pytest.mark.parametrize(
    ("section", "indicator", "invalid_params", "disabled_columns", "enabled_column"),
    [
        ("momentum", "rsi", {"timeperiod": 1}, ["RSI"], "MACD"),
        (
            "momentum",
            "macd",
            {"fastperiod": 30, "slowperiod": 10, "signalperiod": 9},
            ["MACD", "MACD_signal", "MACD_hist"],
            "RSI",
        ),
        (
            "momentum",
            "kd",
            {"fastk_period": 1, "slowk_period": 3, "slowd_period": 3, "slowk_matype": 0, "slowd_matype": 0},
            ["SlowK", "SlowD"],
            "RSI",
        ),
        (
            "volatility",
            "bollinger",
            {"timeperiod": 1, "nbdevup": 2.0, "nbdevdn": 2.0, "matype": 0},
            ["BB_Upper", "BB_Middle", "BB_Lower"],
            "SAR",
        ),
        ("volatility", "sar", {"acceleration": 0.5, "maximum": 0.2}, ["SAR"], "BB_Upper"),
        ("volatility", "atr", {"timeperiod": 1}, ["ATR"], "SAR"),
        ("trend", "tsf", {"timeperiod": 1}, ["TSF"], "ADX"),
        ("trend", "adx", {"timeperiod": 1}, ["ADX"], "TSF"),
        ("trend", "ma", {"windows": [1, 5]}, ["MA5", "MA10", "MA20", "MA60"], "ADX"),
    ],
)
def test_single_indicator_disabled(
    sample_stock_df,
    section,
    indicator,
    invalid_params,
    disabled_columns,
    enabled_column,
):
    """停用指標必須略過非法參數驗證與計算，其他啟用指標仍須正常產生。"""
    configurator = StrategyConfigurator()

    base_config = {
        'config_schema_version': 1,
        'weights': {'pattern': 3000, 'technical': 5000, 'volume': 2000},
        'technical': {
            'momentum': {
                'enabled': True,
                'rsi': {'enabled': True, 'timeperiod': 14},
                'macd': {'enabled': True, 'fastperiod': 12, 'slowperiod': 26, 'signalperiod': 9},
                'kd': {'enabled': True, 'fastk_period': 5, 'slowk_period': 3, 'slowd_period': 3, 'slowk_matype': 0, 'slowd_matype': 0}
            },
            'volatility': {
                'enabled': True,
                'bollinger': {'enabled': True, 'timeperiod': 30, 'nbdevup': 2.0, 'nbdevdn': 2.0, 'matype': 0},
                'sar': {'enabled': True, 'acceleration': 0.02, 'maximum': 0.2},
                'atr': {'enabled': True, 'timeperiod': 14}
            },
            'trend': {
                'enabled': True,
                'tsf': {'enabled': True, 'timeperiod': 14},
                'adx': {'enabled': True, 'timeperiod': 14},
                'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
            }
        }
    }

    cfg = copy_config(base_config)
    cfg['technical'][section][indicator] = {
        'enabled': False,
        **invalid_params,
    }

    result = configurator.configure_technical_indicators(
        sample_stock_df,
        cfg['technical'],
        full_config=cfg,
    )

    assert enabled_column in result.columns
    for column in disabled_columns:
        assert column not in result.columns

def test_generate_recommendations_fail_closed_propagation(sample_stock_df):
    """測試 generate_recommendations 的端到端 Fail-Closed 異常傳播"""
    configurator = StrategyConfigurator()
    
    # 非法 RSI 週期 (timeperiod=1)
    config_invalid = {
        'config_schema_version': 1,
        'weights': {'pattern': 3000, 'technical': 5000, 'volume': 2000},
        'technical': {
            'momentum': {
                'enabled': True,
                'rsi': {
                    'enabled': True,
                    'timeperiod': 1  # 非法：範圍是 2-100
                }
            }
        }
    }
    
    with pytest.raises(InvalidParameterError):
        configurator.generate_recommendations(sample_stock_df, config_invalid)


@pytest.mark.parametrize("version", ["1", -1, True, 1.5])
def test_generate_recommendations_rejects_invalid_schema_version_when_indicators_are_disabled(
    sample_stock_df,
    version,
):
    configurator = StrategyConfigurator()
    config_invalid = {
        'config_schema_version': version,
        'weights': {'pattern': 3000, 'technical': 5000, 'volume': 2000},
        'technical': {
            'momentum': {'enabled': False},
            'volatility': {'enabled': False},
            'trend': {'enabled': False},
        },
    }

    with pytest.raises(InvalidParameterError, match="config_schema_version"):
        configurator.generate_recommendations(sample_stock_df, config_invalid)


def test_cross_field_validations():
    """測試 MACD, SAR, MA 跨欄位契約校驗失敗"""
    # 1. MACD fastperiod >= slowperiod
    with pytest.raises(InvalidParameterError) as exc:
        IndicatorParameterRegistry.validate_and_sanitize(
            'macd',
            {'fastperiod': 20, 'slowperiod': 10, 'signalperiod': 9},
            full_config={'config_schema_version': 1}
        )
    assert "MACD 快線週期 fastperiod" in str(exc.value)

    # 2. SAR acceleration > maximum
    with pytest.raises(InvalidParameterError) as exc:
        IndicatorParameterRegistry.validate_and_sanitize(
            'sar',
            {'acceleration': 0.5, 'maximum': 0.2},
            full_config={'config_schema_version': 1}
        )
    assert "SAR 加速因子 acceleration" in str(exc.value)

    # 3. MA windows duplicate
    with pytest.raises(InvalidParameterError) as exc:
        IndicatorParameterRegistry.validate_and_sanitize(
            'ma',
            {'windows': [5, 5, 10]},
            full_config={'config_schema_version': 1}
        )
    assert "windows 不能包含重複" in str(exc.value)
    
    # 4. MA windows elements containing bool
    with pytest.raises(InvalidParameterError) as exc:
        IndicatorParameterRegistry.validate_and_sanitize(
            'ma',
            {'windows': [5, True, 10]},
            full_config={'config_schema_version': 1}
        )
    assert "不可為 bool" in str(exc.value)

def test_prefix_invariance_intermediate_indicators(sample_stock_df):
    """前綴不變性測試：逐日比對中間指標的計算值，以確保中間指標也符合物理隔離"""
    configurator = StrategyConfigurator()
    config = {
        'config_schema_version': 1,
        'weights': {'pattern': 3000, 'technical': 5000, 'volume': 2000},
        'technical': {
            'momentum': {
                'enabled': True,
                'rsi': {'enabled': True, 'timeperiod': 14},
                'kd': {
                    'enabled': True,
                    'fastk_period': 5,
                    'slowk_period': 3,
                    'slowd_period': 3,
                    'slowk_matype': 0,
                    'slowd_matype': 0
                }
            }
        }
    }
    
    # 1. 以完整資料計算
    df_long = sample_stock_df.copy()
    df_long_processed = configurator.configure_technical_indicators(df_long, config.get('technical', {}), full_config=config)
    
    # 2. 對於每一個長度 t (30 到 79)，以子資料計算並比對 day t 的指標值
    for t in range(30, len(sample_stock_df)):
        df_short = sample_stock_df.iloc[:t+1].copy()
        df_short_processed = configurator.configure_technical_indicators(df_short, config.get('technical', {}), full_config=config)
        
        # 取得最後一天 (即 day t) 的數值
        row_short = df_short_processed.iloc[-1]
        row_long = df_long_processed.iloc[t]
        
        # 斷言中間指標 (RSI, SlowK, SlowD) 一致
        for indicator in ['RSI', 'SlowK', 'SlowD']:
            if indicator in row_long and not pd.isna(row_long[indicator]):
                assert row_short[indicator] == row_long[indicator], f"指標 {indicator} 於第 {t} 日不一致！"
