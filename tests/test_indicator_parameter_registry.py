import pytest
from decision_module.indicator_parameter_registry import IndicatorParameterRegistry, InvalidParameterError

def test_get_default_config():
    default_config = IndicatorParameterRegistry.get_default_config()
    assert 'rsi' in default_config
    assert default_config['rsi']['timeperiod'] == 14
    assert 'macd' in default_config
    assert default_config['macd']['fastperiod'] == 12
    assert 'ma' in default_config
    assert default_config['ma']['windows'] == [5, 10, 20, 60]

def test_validate_and_sanitize_success():
    # 測試合法參數
    params = {'timeperiod': 20}
    sanitized = IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config={'config_schema_version': 1})
    assert sanitized['timeperiod'] == 20

def test_validate_and_sanitize_alias_mapping():
    # 測試 alias 欄位名稱對應 (rsi: period -> timeperiod)
    params = {'period': 25}
    sanitized = IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config={'config_schema_version': 1})
    assert sanitized['timeperiod'] == 25

    # 測試 macd 縮寫轉換
    macd_params = {'fast': 10, 'slow': 20, 'signal': 5}
    sanitized_macd = IndicatorParameterRegistry.validate_and_sanitize('macd', macd_params, full_config={'config_schema_version': 1})
    assert sanitized_macd['fastperiod'] == 10
    assert sanitized_macd['slowperiod'] == 20
    assert sanitized_macd['signalperiod'] == 5

    # 測試 bollinger: window -> timeperiod, std -> nbdevup & nbdevdn
    boll_params = {'window': 20, 'std': 2.5, 'matype': 0}
    sanitized_boll = IndicatorParameterRegistry.validate_and_sanitize('bollinger', boll_params, full_config={'config_schema_version': 1})
    assert sanitized_boll['timeperiod'] == 20
    assert sanitized_boll['nbdevup'] == 2.5
    assert sanitized_boll['nbdevdn'] == 2.5

def test_validate_and_sanitize_fail_closed_v1():
    # 新版（v1+）配置缺失必要參數，一律拋出 InvalidParameterError
    params = {}
    with pytest.raises(InvalidParameterError) as excinfo:
        IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config={'config_schema_version': 1})
    assert "缺失指標 rsi 的必要參數 timeperiod" in str(excinfo.value)

def test_validate_and_sanitize_legacy_fallback_v0():
    # 舊版配置（v0 或 None）缺失必要參數，應套用 legacy default
    params = {}
    sanitized = IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config={'config_schema_version': 0})
    assert sanitized['timeperiod'] == 14

    # 當 full_config 為 None 時，預設判定為 v0
    sanitized_none = IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config=None)
    assert sanitized_none['timeperiod'] == 14

def test_validate_and_sanitize_invalid_range():
    # 參數值越界，一律 Fail-Closed 拋出 InvalidParameterError
    params = {'timeperiod': 1}  # schema 規定為 (2, 100)
    with pytest.raises(InvalidParameterError) as excinfo:
        IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config={'config_schema_version': 1})
    assert "超出合理範圍" in str(excinfo.value)

    # 舊版配置越界也一樣要拒絕
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config={'config_schema_version': 0})

def test_validate_and_sanitize_invalid_type():
    # 類型不符合且無法轉換
    params = {'timeperiod': 'abc'}
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize('rsi', params, full_config={'config_schema_version': 1})

def test_validate_and_sanitize_ma_list():
    # 測試 ma 的 windows list 校驗
    params = {'windows': [5, '10', 20]}
    sanitized = IndicatorParameterRegistry.validate_and_sanitize('ma', params, full_config={'config_schema_version': 1})
    assert sanitized['windows'] == [5, 10, 20]

    # ma 越界 (例如 1)
    params_invalid = {'windows': [1, 10]}
    with pytest.raises(InvalidParameterError):
        IndicatorParameterRegistry.validate_and_sanitize('ma', params_invalid, full_config={'config_schema_version': 1})
