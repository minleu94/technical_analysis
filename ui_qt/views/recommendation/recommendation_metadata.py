"""推薦視圖使用的靜態元資料"""

from typing import Dict, Any

# 技術指標說明資料結構
TECHNICAL_DESCRIPTIONS = {
    'ma': {
        'short_label': '趨勢方向',
        'category': 'Trend',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['趨勢', '方向'],
        'tooltip_lines': [
            '移動平均線：判斷股價的趨勢方向',
            '通常代表：股價是否處於上升或下降趨勢',
            '系統角色：📊 分數加權依據（用於計算 IndicatorScore）',
            '注意：均線有滯後性，適合趨勢明確的市場'
        ]
    },
    'adx': {
        'short_label': '趨勢強度',
        'category': 'Trend',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['趨勢', '強度'],
        'tooltip_lines': [
            'ADX（平均趨向指標）：衡量趨勢的強度，而非方向',
            '通常代表：市場是否處於強趨勢或盤整狀態',
            '系統角色：📊 分數加權依據（用於計算 IndicatorScore）',
            '注意：ADX 不告訴你方向，只看強度'
        ]
    },
    'macd': {
        'short_label': '趨勢 + 動能',
        'category': 'Trend',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['趨勢', '動能', '反轉'],
        'tooltip_lines': [
            'MACD（指數平滑異同移動平均線）：結合趨勢和動能',
            '通常代表：趨勢轉換的訊號，當 MACD 線穿越訊號線時可能出現轉折',
            '系統角色：📊 分數加權依據（用於計算 IndicatorScore）',
            '注意：在盤整市場容易產生假訊號'
        ]
    },
    'rsi': {
        'short_label': '超買超賣 / 動能',
        'category': 'Momentum',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['動能', '反轉'],
        'tooltip_lines': [
            'RSI（相對強弱指標）：衡量股價動能和超買超賣狀態',
            '通常代表：RSI > 70 可能超買，RSI < 30 可能超賣，但強勢股可能長期超買',
            '系統角色：📊 分數加權依據（用於計算 IndicatorScore）',
            '注意：單獨使用 RSI 容易誤判，需配合趨勢指標'
        ]
    },
    'kd': {
        'short_label': '超買超賣 / 動能',
        'category': 'Momentum',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['動能', '反轉'],
        'tooltip_lines': [
            'KD（隨機指標）：類似 RSI，判斷超買超賣和動能',
            '通常代表：K 值和 D 值在 80 以上可能超買，20 以下可能超賣',
            '系統角色：📊 分數加權依據（用於計算 IndicatorScore）',
            '注意：在強趨勢中可能長期超買或超賣'
        ]
    },
    'bollinger': {
        'short_label': '波動 / 區間',
        'category': 'Volatility',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['波動', '盤整', '反轉'],
        'tooltip_lines': [
            '布林通道：顯示股價的波動區間和相對位置',
            '通常代表：股價觸及上軌可能超買，觸及下軌可能超賣；通道收窄表示波動降低',
            '系統角色：📊 分數加權依據（用於計算 IndicatorScore）',
            '注意：在強趨勢中，股價可能沿著通道邊緣持續移動'
        ]
    },
    'atr': {
        'short_label': '波動 / 風險',
        'category': 'Volatility',
        'system_role': '輔助判斷',
        'role_icon': '🧭',
        'tags': ['波動', '風險'],
        'tooltip_lines': [
            'ATR（平均真實波幅）：衡量股價的波動程度',
            '通常代表：ATR 值高表示波動大、風險高；ATR 值低表示波動小、風險低',
            '系統角色：🧭 市場狀態輔助判斷（用於標準化參數和風險評估）',
            '注意：ATR 不判斷方向，只看波動大小'
        ]
    }
}

# 圖形模式說明資料結構
PATTERN_DESCRIPTIONS = {
    'w_bottom': {
        'short_label': '反轉',
        'category': 'Reversal',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['反轉', '底部'],
        'tooltip_lines': [
            'W 底：股價形成兩個低點，通常出現在下跌趨勢末端',
            '通常代表：空頭力量衰竭，可能出現反轉上漲',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：需配合成交量確認，第二個低點成交量應較小'
        ]
    },
    'head_shoulder_bottom': {
        'short_label': '反轉',
        'category': 'Reversal',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['反轉', '底部'],
        'tooltip_lines': [
            '頭肩底：三個低點，中間最低（頭），兩側較高（肩）',
            '通常代表：強烈的看漲反轉訊號，通常出現在長期下跌後',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：需等待頸線突破確認，否則可能失敗'
        ]
    },
    'double_bottom': {
        'short_label': '反轉',
        'category': 'Reversal',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['反轉', '底部'],
        'tooltip_lines': [
            '雙底：股價兩次觸及相同或相近的低點',
            '通常代表：空頭力量在該價位受阻，可能反轉上漲',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：需配合成交量和其他指標確認'
        ]
    },
    'v_reversal': {
        'short_label': '反轉',
        'category': 'Reversal',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['反轉', '底部'],
        'tooltip_lines': [
            'V 形反轉：股價快速下跌後快速反彈，形成 V 字形',
            '通常代表：急跌後的快速反彈，通常伴隨重大消息或情緒轉換',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：V 形反轉可能不穩定，需配合其他指標確認'
        ]
    },
    'rounding_bottom': {
        'short_label': '反轉',
        'category': 'Reversal',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['反轉', '底部'],
        'tooltip_lines': [
            '圓底：股價緩慢下跌後緩慢上漲，形成圓弧形',
            '通常代表：長期底部形成，通常出現在長期下跌後',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：圓底形成時間較長，需耐心等待確認'
        ]
    },
    'flag': {
        'short_label': '上漲延續',
        'category': 'Continuation',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['延續', '趨勢'],
        'tooltip_lines': [
            '旗形：上漲後的小幅整理，通常伴隨成交量萎縮',
            '通常代表：上漲趨勢中的短暫休息，整理後通常繼續上漲',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：需確認整理期間成交量萎縮，突破時放量'
        ]
    },
    'wedge': {
        'short_label': '上漲延續',
        'category': 'Continuation',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['延續', '趨勢'],
        'tooltip_lines': [
            '楔形：股價在兩條收斂的趨勢線間波動',
            '通常代表：上升楔形可能延續上漲，下降楔形可能反轉',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：楔形方向需配合其他指標確認'
        ]
    },
    'rectangle': {
        'short_label': '盤整 / 區間',
        'category': 'Consolidation',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['盤整', '區間'],
        'tooltip_lines': [
            '矩形：股價在上下兩條水平線間波動',
            '通常代表：多空力量平衡，股價在區間內盤整',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：矩形突破方向需配合其他指標判斷'
        ]
    },
    'triangle': {
        'short_label': '盤整 / 區間',
        'category': 'Consolidation',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['盤整', '區間'],
        'tooltip_lines': [
            '三角形：股價波動範圍逐漸收窄，形成三角形',
            '通常代表：多空力量逐漸平衡，準備選擇方向',
            '系統角色：📊 分數加權依據（用於計算 PatternScore）',
            '注意：三角形突破方向需配合成交量和趨勢指標確認'
        ]
    },
    'head_shoulder_top': {
        'short_label': '下跌訊號',
        'category': 'Bearish',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['下跌', '頂部'],
        'tooltip_lines': [
            '頭肩頂：三個高點，中間最高（頭），兩側較低（肩）',
            '通常代表：強烈的看跌反轉訊號，通常出現在長期上漲後',
            '系統角色：📊 分數加權依據（用於計算 PatternScore，通常為負分）',
            '注意：需等待頸線跌破確認，否則可能失敗'
        ]
    },
    'double_top': {
        'short_label': '下跌訊號',
        'category': 'Bearish',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['下跌', '頂部'],
        'tooltip_lines': [
            '雙頂：股價兩次觸及相同或相近的高點',
            '通常代表：多頭力量在該價位受阻，可能反轉下跌',
            '系統角色：📊 分數加權依據（用於計算 PatternScore，通常為負分）',
            '注意：需配合成交量和其他指標確認'
        ]
    },
    'rounding_top': {
        'short_label': '下跌訊號',
        'category': 'Bearish',
        'system_role': '加分指標',
        'role_icon': '📊',
        'tags': ['下跌', '頂部'],
        'tooltip_lines': [
            '圓頂：股價緩慢上漲後緩慢下跌，形成圓弧形',
            '通常代表：長期頂部形成，通常出現在長期上漲後',
            '系統角色：📊 分數加權依據（用於計算 PatternScore，通常為負分）',
            '注意：圓頂形成時間較長，需耐心等待確認'
        ]
    }
}

# 技術指標名稱映射
TECHNICAL_NAME_MAP = {
    '移動平均線': 'ma',
    'MA': 'ma',
    'ADX': 'adx',
    'MACD': 'macd',
    'RSI': 'rsi',
    'KD': 'kd',
    '布林通道': 'bollinger',
    'ATR': 'atr'
}

# 圖形模式名稱映射
PATTERN_NAME_MAP = {
    'W底': 'w_bottom',
    '頭肩底': 'head_shoulder_bottom',
    '雙底': 'double_bottom',
    'V形反轉': 'v_reversal',
    '圓底': 'rounding_bottom',
    '旗形': 'flag',
    '楔形': 'wedge',
    '矩形': 'rectangle',
    '三角形': 'triangle',
    '頭肩頂': 'head_shoulder_top',
    '雙頂': 'double_top',
    '圓頂': 'rounding_top'
}

# 預設 Profiles
DEFAULT_PROFILES = {
    'momentum': {
        'id': 'momentum',
        'name': '暴衝策略',
        'version': '1.0.0',
        'description': '在趨勢明確、動能強勁的市場中，尋找價格快速上漲且成交量明顯放大的股票。適合願意承擔高風險以換取高報酬的交易者。',
        'regime': ['Trend', 'Breakout'],
        'regime_not_suitable': ['Reversion'],
        'risk_level': 'high',
        'risk_warning': {
            'max_drawdown_expected': '15-30%',
            'volatility': '高',
            'holding_period': '1-5 天',
            'suitable_for': '願意承擔高風險、追求快速獲利的交易者',
            'not_suitable_for': '風險承受度低、偏好穩定報酬的投資者'
        },
        'config': {
            'technical': {
                'momentum': {
                    'enabled': True,
                    'rsi': {'enabled': True, 'period': 14},
                    'macd': {'enabled': True, 'fast': 12, 'slow': 26, 'signal': 9},
                    'kd': {'enabled': False}
                },
                'volatility': {
                    'enabled': False,
                    'bollinger': {'enabled': False, 'window': 20, 'std': 2},
                    'atr': {'enabled': True, 'period': 14}
                },
                'trend': {
                    'enabled': True,
                    'adx': {'enabled': True, 'period': 14},
                    'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                }
            },
            'patterns': {
                'selected': ['旗形', '三角形', '矩形', 'V形反轉']
            },
            'signals': {
                'technical_indicators': ['momentum', 'trend'],
                'volume_conditions': ['increasing', 'spike'],
                'weights': {'pattern': 0.25, 'technical': 0.55, 'volume': 0.20}
            },
            'filters': {
                'price_change_min': 2.0,
                'price_change_max': 100.0,
                'volume_ratio_min': 1.5,
                'rsi_min': 0,
                'rsi_max': 100,
                'industry': '全部'
            }
        }
    },
    'stable': {
        'id': 'stable',
        'name': '穩健策略',
        'version': '1.0.0',
        'description': '在均值回歸市場中尋找被低估的機會，追求穩定報酬。適合風險承受度低的投資者。',
        'regime': ['Reversion'],
        'regime_not_suitable': ['Trend', 'Breakout'],
        'risk_level': 'low',
        'risk_warning': {
            'max_drawdown_expected': '5-10%',
            'volatility': '低',
            'holding_period': '5-20 天',
            'suitable_for': '風險承受度低、偏好穩定報酬的投資者',
            'not_suitable_for': '追求快速獲利、願意承擔高風險的交易者'
        },
        'config': {
            'technical': {
                'momentum': {
                    'enabled': True,
                    'rsi': {'enabled': True, 'period': 14},
                    'macd': {'enabled': True, 'fast': 12, 'slow': 26, 'signal': 9},
                    'kd': {'enabled': True}
                },
                'volatility': {
                    'enabled': True,
                    'bollinger': {'enabled': True, 'window': 20, 'std': 2},
                    'atr': {'enabled': True, 'period': 14}
                },
                'trend': {
                    'enabled': True,
                    'adx': {'enabled': True, 'period': 14},
                    'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                }
            },
            'patterns': {
                'selected': ['W底', '頭肩底', '雙底', '圓底', '矩形']
            },
            'signals': {
                'technical_indicators': ['momentum', 'trend', 'volatility'],
                'volume_conditions': ['increasing'],
                'weights': {'pattern': 0.35, 'technical': 0.45, 'volume': 0.20}
            },
            'filters': {
                'price_change_min': -5.0,
                'price_change_max': 5.0,
                'volume_ratio_min': 1.0,
                'rsi_min': 0,
                'rsi_max': 50,
                'industry': '全部'
            }
        }
    },
    'long_term': {
        'id': 'long_term',
        'name': '長期策略',
        'version': '1.0.0',
        'description': '基於長期趨勢和基本面，尋找具有持續成長潛力的股票。適合長期持有的投資者。',
        'regime': ['Trend', 'Breakout'],
        'regime_not_suitable': ['Reversion'],
        'risk_level': 'medium',
        'risk_warning': {
            'max_drawdown_expected': '10-20%',
            'volatility': '中',
            'holding_period': '20-60 天',
            'suitable_for': '長期持有、追求穩定成長的投資者',
            'not_suitable_for': '短期交易、追求快速獲利的交易者'
        },
        'config': {
            'technical': {
                'momentum': {
                    'enabled': False,
                    'rsi': {'enabled': False, 'period': 14},
                    'macd': {'enabled': True, 'fast': 12, 'slow': 26, 'signal': 9},
                    'kd': {'enabled': False}
                },
                'volatility': {
                    'enabled': False,
                    'bollinger': {'enabled': False, 'window': 20, 'std': 2},
                    'atr': {'enabled': True, 'period': 14}
                },
                'trend': {
                    'enabled': True,
                    'adx': {'enabled': True, 'period': 14},
                    'ma': {'enabled': True, 'windows': [5, 10, 20, 60, 120]}
                }
            },
            'patterns': {
                'selected': ['圓底', '矩形', '三角形']
            },
            'signals': {
                'technical_indicators': ['trend'],
                'volume_conditions': ['increasing'],
                'weights': {'pattern': 0.20, 'technical': 0.60, 'volume': 0.20}
            },
            'filters': {
                'price_change_min': 0.0,
                'price_change_max': 100.0,
                'volume_ratio_min': 1.0,
                'rsi_min': 0,
                'rsi_max': 100,
                'industry': '全部'
            }
        }
    }
}
