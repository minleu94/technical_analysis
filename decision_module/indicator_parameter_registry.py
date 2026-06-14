"""
指標參數註冊表 (Indicator Parameter Registry)
定義所有技術指標參數的 Schema、範圍限制與驗證邏輯，實施 Fail-Closed 門禁。
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class InvalidParameterError(ValueError):
    """指標參數校驗不合規異常"""
    pass


class IndicatorParameterRegistry:
    """技術指標參數註冊表與驗證器"""

    # 靜態定義所有支援指標的參數 Schema
    SCHEMAS = {
        'rsi': {
            'timeperiod': {'type': int, 'range': (2, 100), 'default': 14, 'unit': 'days', 'description': 'RSI 計算週期'}
        },
        'macd': {
            'fastperiod': {'type': int, 'range': (2, 100), 'default': 12, 'unit': 'days', 'description': 'MACD 快線週期'},
            'slowperiod': {'type': int, 'range': (2, 100), 'default': 26, 'unit': 'days', 'description': 'MACD 慢線週期'},
            'signalperiod': {'type': int, 'range': (2, 100), 'default': 9, 'unit': 'days', 'description': 'MACD 信號線週期'}
        },
        'kd': {
            'fastk_period': {'type': int, 'range': (2, 100), 'default': 5, 'unit': 'days', 'description': 'KD Fast K 週期'},
            'slowk_period': {'type': int, 'range': (2, 100), 'default': 3, 'unit': 'days', 'description': 'KD Slow K 週期'},
            'slowd_period': {'type': int, 'range': (2, 100), 'default': 3, 'unit': 'days', 'description': 'KD Slow D 週期'},
            'slowk_matype': {'type': int, 'range': (0, 8), 'default': 0, 'unit': 'ma_type', 'description': 'KD K 均線類型'},
            'slowd_matype': {'type': int, 'range': (0, 8), 'default': 0, 'unit': 'ma_type', 'description': 'KD D 均線類型'}
        },
        'adx': {
            'timeperiod': {'type': int, 'range': (2, 100), 'default': 14, 'unit': 'days', 'description': 'ADX 計算週期'}
        },
        'atr': {
            'timeperiod': {'type': int, 'range': (2, 100), 'default': 14, 'unit': 'days', 'description': 'ATR 計算週期'}
        },
        'bollinger': {
            'timeperiod': {'type': int, 'range': (2, 200), 'default': 30, 'unit': 'days', 'description': '布林通道週期'},
            'nbdevup': {'type': (int, float), 'range': (0.1, 10.0), 'default': 2.0, 'unit': 'multiplier', 'description': '上軌標準差倍數'},
            'nbdevdn': {'type': (int, float), 'range': (0.1, 10.0), 'default': 2.0, 'unit': 'multiplier', 'description': '下軌標準差倍數'},
            'matype': {'type': int, 'range': (0, 8), 'default': 0, 'unit': 'ma_type', 'description': '中軌均線類型'}
        },
        'sar': {
            'acceleration': {'type': float, 'range': (0.001, 1.0), 'default': 0.02, 'unit': 'step', 'description': 'SAR 加速因子'},
            'maximum': {'type': float, 'range': (0.01, 10.0), 'default': 0.2, 'unit': 'max', 'description': 'SAR 加速上限'}
        },
        'tsf': {
            'timeperiod': {'type': int, 'range': (2, 100), 'default': 14, 'unit': 'days', 'description': 'TSF 計算週期'}
        },
        'ma': {
            'windows': {'type': list, 'default': [5, 10, 20, 60], 'unit': 'days_list', 'description': '移動平均週期列表'}
        }
    }

    @classmethod
    def get_default_config(cls) -> Dict[str, Any]:
        """獲取所有指標的預設參數字典"""
        default_config: Dict[str, Any] = {}
        for indicator, schema in cls.SCHEMAS.items():
            default_config[indicator] = {}
            for param_name, param_meta in schema.items():
                default_config[indicator][param_name] = param_meta['default']
        return default_config

    @classmethod
    def validate_and_sanitize(cls, indicator_name: str, params: Dict[str, Any], full_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        驗證並清理指定指標的自訂參數。新版（v1+）缺失或任何版本值非法一律拋出 InvalidParameterError (Fail-Closed)。

        Args:
            indicator_name: 指標名稱 (例如 'rsi', 'macd')
            params: 自訂參數字典
            full_config: 完整配置字典，用以自動解析 config_schema_version

        Returns:
            Dict[str, Any]: 清理與補足預設值後的安全參數字典
        """
        indicator_name = str(indicator_name).lower()
        if indicator_name not in cls.SCHEMAS:
            raise InvalidParameterError(f"未知的技術指標名稱: {indicator_name}")

        # 解析 config_schema_version，受控處理轉換 ValueError
        config_schema_version = 0
        if full_config and isinstance(full_config, dict):
            raw_version = full_config.get('config_schema_version', 0)
            if isinstance(raw_version, bool) or not isinstance(raw_version, int):
                raise InvalidParameterError("Invalid config_schema_version format")
            if raw_version < 0:
                raise InvalidParameterError("config_schema_version must be non-negative")
            config_schema_version = raw_version

        schema = cls.SCHEMAS[indicator_name]

        # 1. 建立 copy，移除 enabled 等治理欄位
        clean_params = dict(params) if params else {}
        clean_params.pop('enabled', None)

        # 2. 別名規範化 (Alias Canonicalization)
        if indicator_name == 'rsi' and 'period' in clean_params:
            clean_params['timeperiod'] = clean_params.pop('period')
        elif indicator_name == 'macd':
            if 'fast' in clean_params:
                clean_params['fastperiod'] = clean_params.pop('fast')
            if 'slow' in clean_params:
                clean_params['slowperiod'] = clean_params.pop('slow')
            if 'signal' in clean_params:
                clean_params['signalperiod'] = clean_params.pop('signal')
        elif indicator_name == 'bollinger':
            if 'window' in clean_params:
                clean_params['timeperiod'] = clean_params.pop('window')
            if 'std' in clean_params:
                std_val = clean_params.pop('std')
                if 'nbdevup' not in clean_params:
                    clean_params['nbdevup'] = std_val
                if 'nbdevdn' not in clean_params:
                    clean_params['nbdevdn'] = std_val
        elif indicator_name in ('atr', 'adx') and 'period' in clean_params:
            clean_params['timeperiod'] = clean_params.pop('period')

        # 3. 拒絕剩餘的未知欄位
        for k in clean_params:
            if k not in schema:
                raise InvalidParameterError(f"指標 {indicator_name} 含有未知參數: {k}")

        sanitized = {}
        for param_name, param_meta in schema.items():
            expected_type: Any = param_meta['type']
            default_val = param_meta['default']
            
            # 判斷參數欄位是否存在
            has_param = param_name in clean_params
            val = clean_params.get(param_name) if has_param else None

            # 若欄位缺失
            if not has_param or val is None:
                if config_schema_version < 1:
                    # 舊版配置缺失，允許使用 legacy default 備份並記錄原因
                    sanitized[param_name] = default_val
                    logger.info(
                        f"[Registry] 舊版配置 {indicator_name} 缺失參數 {param_name}，"
                        f"使用 legacy 預設值: {default_val}。"
                    )
                    continue
                else:
                    # 新版配置缺失必要參數，一律拋出 Exception (Fail-Closed)
                    raise InvalidParameterError(
                        f"新版配置 (schema_version={config_schema_version}) 缺失指標 {indicator_name} 的必要參數 {param_name}。"
                    )

            # 類型校驗（拒絕隱式轉換與 bool）
            if isinstance(val, bool):
                raise InvalidParameterError(
                    f"指標 {indicator_name} 的參數 {param_name} 類型不符 (預期: {expected_type}，實際為 bool)。"
                )

            valid_type = False
            if isinstance(expected_type, tuple):
                valid_type = any(isinstance(val, t) for t in expected_type)
            else:
                valid_type = isinstance(val, expected_type)

            if not valid_type:
                raise InvalidParameterError(
                    f"指標 {indicator_name} 的參數 {param_name} 類型不符 (預期: {expected_type}，實際: {type(val)})。"
                )

            # 額外對 list (針對 ma.windows) 內部元素檢查
            if expected_type is list:
                if not isinstance(val, list) or len(val) == 0:
                    raise InvalidParameterError(f"均線窗口清單 {param_name} 必須是包含整數的非空清單。")
                cleaned_list = []
                for x in val:
                    if isinstance(x, bool):
                        raise InvalidParameterError(f"均線窗口元素 {x} 不可為 bool。")
                    if not isinstance(x, int):
                        raise InvalidParameterError(f"均線窗口 {x} 不是合法的整數。")
                    if 2 <= x <= 500:
                        cleaned_list.append(x)
                    else:
                        raise InvalidParameterError(f"均線窗口 {x} 超出合理範圍 [2, 500]。")
                
                # 校驗重複數值
                if len(cleaned_list) != len(set(cleaned_list)):
                    raise InvalidParameterError("均線窗口清單 windows 不能包含重複的週期數值。")
                
                sanitized[param_name] = sorted(cleaned_list)
                continue

            # 範圍校驗
            param_range: Any = param_meta.get('range')
            if param_range and isinstance(param_range, (list, tuple)):
                min_val, max_val = param_range
                if not (min_val <= val <= max_val):
                    raise InvalidParameterError(
                        f"指標 {indicator_name} 的參數 {param_name} 數值 {val} 超出合理範圍 [{min_val}, {max_val}]。"
                    )

            sanitized[param_name] = val

        # 4. 跨欄位契約驗證
        if indicator_name == 'macd':
            fast = sanitized.get('fastperiod')
            slow = sanitized.get('slowperiod')
            if fast is not None and slow is not None and int(fast) >= int(slow):  # type: ignore
                raise InvalidParameterError(f"MACD 快線週期 fastperiod ({fast}) 必須小於慢線週期 slowperiod ({slow})。")
        elif indicator_name == 'sar':
            acc = sanitized.get('acceleration')
            mx = sanitized.get('maximum')
            if acc is not None and mx is not None and float(acc) > float(mx):  # type: ignore
                raise InvalidParameterError(f"SAR 加速因子 acceleration ({acc}) 必須小於等於加速上限 maximum ({mx})。")

        return sanitized
