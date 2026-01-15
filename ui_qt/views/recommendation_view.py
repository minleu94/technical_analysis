"""
推薦分析視圖
顯示策略配置、執行推薦分析、顯示推薦結果
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTableView, QGroupBox, QProgressBar,
    QTextEdit, QHeaderView, QCheckBox, QSpinBox, QDoubleSpinBox,
    QComboBox, QMessageBox, QSplitter, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime

from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.workers.task_worker import ProgressTaskWorker
from app_module.recommendation_service import RecommendationService
from app_module.regime_service import RegimeService
from app_module.watchlist_service import WatchlistService
from app_module.recommendation_repository import RecommendationRepository
from app_module.universe_service import UniverseService
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from data_module.config import TWStockConfig
from ui_qt.widgets.info_button import InfoButton


class RecommendationView(QWidget):
    """推薦分析視圖"""
    
    # 自定義信號
    recommendationRequested = Signal(dict)  # 推薦請求（傳遞配置）
    sendToBacktestRequested = Signal(dict)  # 一鍵送回測請求（Phase 3.3）
    
    def __init__(
        self, 
        recommendation_service: RecommendationService,
        regime_service: RegimeService,
        watchlist_service: WatchlistService = None,
        config: Optional[TWStockConfig] = None,
        universe_service: Optional[UniverseService] = None,
        parent=None
    ):
        """初始化推薦視圖
        
        Args:
            recommendation_service: 推薦服務實例
            regime_service: 市場狀態服務實例
            watchlist_service: 觀察清單服務實例（可選）
            config: TWStockConfig 實例（用於創建 Repository）
            universe_service: 選股清單服務實例（可選，用於自動創建選股清單）
            parent: 父窗口
        """
        super().__init__(parent)
        self.recommendation_service = recommendation_service
        self.regime_service = regime_service
        self.watchlist_service = watchlist_service
        
        # 初始化 Repository（如果提供了 config）
        if config:
            self.recommendation_repository = RecommendationRepository(config)
            # 如果沒有傳入 universe_service，則創建一個
            if universe_service is None:
                self.universe_service = UniverseService(config)
            else:
                self.universe_service = universe_service
        else:
            self.recommendation_repository = None
            self.universe_service = universe_service
        
        # 數據模型
        self.recommendations_model: Optional[PandasTableModel] = None
        
        # Worker
        self.worker: Optional[ProgressTaskWorker] = None
        
        # 策略配置狀態
        self.strategy_config = self._get_default_config()
        
        # 當前推薦結果（用於保存）
        self.current_recommendations: Optional[List[RecommendationDTO]] = None
        self.current_config: Optional[Dict[str, Any]] = None
        self.current_regime: Optional[str] = None
        self.current_profile: Optional[str] = None  # 當前使用的 Profile
        
        # 模式切換（新手/進階）
        self.is_beginner_mode = True  # 預設為新手模式
        
        # 技術指標和圖形模式的說明數據
        self._init_indicator_descriptions()
        
        # 初始化 Profiles
        self._init_profiles()
        
        self._setup_ui()
        self._load_current_regime()
        # 初始化策略傾向提示
        self._update_strategy_tendency()
    
    def _init_indicator_descriptions(self):
        """初始化技術指標和圖形模式的說明數據（集中管理）"""
        # 技術指標說明資料結構（集中管理）
        self.technical_descriptions = {
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
        
        # 圖形模式說明資料結構（集中管理）
        self.pattern_descriptions = {
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
        
        # 建立反向映射（從中文名稱到 key）
        self._init_name_mapping()
    
    def _init_name_mapping(self):
        """初始化中文名稱到 key 的映射"""
        # 技術指標名稱映射
        self.technical_name_map = {
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
        self.pattern_name_map = {
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
    
    def _init_profiles(self):
        """初始化 Profiles（暴衝/穩健/長期）"""
        self.profiles = {
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
    
    def _get_default_config(self) -> Dict[str, Any]:
        """獲取預設策略配置"""
        return {
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
                'selected': ['W底', '頭肩底', '雙底', '矩形']
            },
            'signals': {
                'technical_indicators': ['momentum', 'trend'],
                'volume_conditions': ['increasing'],
                'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
            },
            'filters': {
                'price_change_min': 0.0,
                'price_change_max': 100.0,
                'volume_ratio_min': 1.0,
                'rsi_min': 0,
                'rsi_max': 100,
                'industry': '全部'
            },
            'regime': None  # 將從市場狀態服務獲取
        }
    
    def _setup_ui(self):
        """設置 UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("推薦分析")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("recommendation", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)
        
        # 創建分割器（左側配置，右側結果）
        splitter = QSplitter(Qt.Horizontal)
        
        # 左側：策略配置面板（使用 ScrollArea 支援滾動）
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setMinimumWidth(350)  # 設置最小寬度
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        config_panel = self._create_config_panel()
        config_scroll.setWidget(config_panel)
        splitter.addWidget(config_scroll)
        
        # 右側：結果面板
        result_panel = self._create_result_panel()
        splitter.addWidget(result_panel)
        
        # 設置分割器比例（左側40%，右側60%）
        splitter.setSizes([200, 800])
        
        main_layout.addWidget(splitter)
    
    def _create_checkbox_with_tooltip(
        self, 
        text: str, 
        desc_key: str, 
        desc_type: str = 'technical',  # 'technical' 或 'pattern'
        checked: bool = False
    ) -> QCheckBox:
        """創建帶 tooltip 的 checkbox（從集中資料結構讀取）
        
        Args:
            text: 顯示名稱（如 "RSI"）
            desc_key: 說明資料的 key（如 "rsi"）
            desc_type: 類型（'technical' 或 'pattern'）
            checked: 是否預設勾選
        """
        # 從集中資料結構讀取
        if desc_type == 'technical':
            desc = self.technical_descriptions.get(desc_key, {})
        else:
            desc = self.pattern_descriptions.get(desc_key, {})
        
        short_label = desc.get('short_label', '')
        tooltip_lines = desc.get('tooltip_lines', [])
        
        # 組合顯示文字：名稱（短說明）
        display_text = f"{text}（{short_label}）"
        checkbox = QCheckBox(display_text)
        checkbox.setChecked(checked)
        
        # 組合 tooltip（使用換行符）
        tooltip_text = '\n'.join(tooltip_lines)
        checkbox.setToolTip(tooltip_text)
        
        # 保存 desc_key 供後續使用
        checkbox.setProperty('desc_key', desc_key)
        checkbox.setProperty('desc_type', desc_type)
        
        return checkbox
    
    def _create_config_panel(self) -> QWidget:
        """創建策略配置面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)  # 設置邊距，確保內容不會貼邊
        
        # 標題和模式切換
        title_layout = QHBoxLayout()
        title = QLabel("策略配置")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        # 模式切換按鈕
        self.mode_btn = QPushButton("切換至進階模式")
        self.mode_btn.setCheckable(False)
        self.mode_btn.clicked.connect(self._toggle_mode)
        title_layout.addWidget(self.mode_btn)
        layout.addLayout(title_layout)
        
        # 市場狀態顯示
        regime_group = QGroupBox("市場狀態")
        regime_layout = QVBoxLayout()
        self.regime_label = QLabel("檢測中...")
        self.regime_label.setWordWrap(True)
        regime_layout.addWidget(self.regime_label)
        regime_group.setLayout(regime_layout)
        layout.addWidget(regime_group)
        
        # Regime → Profile 建議（Phase 3.2）
        self.regime_suggestion_group = QGroupBox("策略建議")
        suggestion_layout = QVBoxLayout()
        self.regime_suggestion_label = QLabel("")
        self.regime_suggestion_label.setWordWrap(True)
        self.regime_suggestion_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d2d;
                color: #e0e0e0;
                padding: 8px;
                border-radius: 4px;
                font-size: 0.9em;
                line-height: 1.4;
            }
        """)
        suggestion_layout.addWidget(self.regime_suggestion_label)
        
        # 一鍵套用按鈕
        self.apply_suggestion_btn = QPushButton("一鍵套用建議 Profile")
        self.apply_suggestion_btn.setVisible(False)
        self.apply_suggestion_btn.clicked.connect(self._apply_suggested_profile)
        suggestion_layout.addWidget(self.apply_suggestion_btn)
        
        self.regime_suggestion_group.setLayout(suggestion_layout)
        self.regime_suggestion_group.setVisible(False)  # 初始隱藏，等待 Regime 檢測
        layout.addWidget(self.regime_suggestion_group)
        
        # 保存建議的 Profile ID（用於一鍵套用）
        self.suggested_profile_id: Optional[str] = None
        
        # 新手模式：Profile 選擇（只在新手模式顯示）
        self.profile_group = QGroupBox("選擇策略風格（Profile）")
        profile_layout = QVBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("請選擇 Profile...", None)
        for profile_id, profile_data in self.profiles.items():
            self.profile_combo.addItem(profile_data['name'], profile_id)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        profile_layout.addWidget(self.profile_combo)
        
        # Profile 說明
        self.profile_desc_label = QLabel("")
        self.profile_desc_label.setWordWrap(True)
        self.profile_desc_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d2d;
                color: #e0e0e0;
                padding: 8px;
                border-radius: 4px;
                font-size: 0.9em;
                line-height: 1.4;
            }
        """)
        profile_layout.addWidget(self.profile_desc_label)
        self.profile_group.setLayout(profile_layout)
        layout.addWidget(self.profile_group)
        
        # 策略傾向提示區（新增）
        self.strategy_tendency_group = QGroupBox("策略傾向")
        strategy_tendency_layout = QVBoxLayout()
        self.strategy_tendency_label = QLabel("請選擇技術指標和圖形模式")
        self.strategy_tendency_label.setWordWrap(True)
        self.strategy_tendency_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        strategy_tendency_layout.addWidget(self.strategy_tendency_label)
        self.strategy_tendency_group.setLayout(strategy_tendency_layout)
        layout.addWidget(self.strategy_tendency_group)
        
        # 技術指標配置（按交易意圖分類）- 進階模式才顯示
        tech_group = QGroupBox("技術指標")
        tech_layout = QVBoxLayout()
        
        # 趨勢類
        trend_label = QLabel("📈 趨勢 (Trend)")
        trend_font = QFont()
        trend_font.setBold(True)
        trend_label.setFont(trend_font)
        tech_layout.addWidget(trend_label)
        
        self.ma_check = self._create_checkbox_with_tooltip(
            "移動平均線",
            'ma',
            'technical',
            checked=True
        )
        tech_layout.addWidget(self.ma_check)
        self.ma_check.toggled.connect(self._update_strategy_tendency)
        
        self.adx_check = self._create_checkbox_with_tooltip(
            "ADX",
            'adx',
            'technical',
            checked=True
        )
        tech_layout.addWidget(self.adx_check)
        self.adx_check.toggled.connect(self._update_strategy_tendency)
        
        self.macd_check = self._create_checkbox_with_tooltip(
            "MACD",
            'macd',
            'technical',
            checked=True
        )
        tech_layout.addWidget(self.macd_check)
        self.macd_check.toggled.connect(self._update_strategy_tendency)
        
        # 動能類
        momentum_label = QLabel("⚡ 動能 (Momentum)")
        momentum_font = QFont()
        momentum_font.setBold(True)
        momentum_label.setFont(momentum_font)
        tech_layout.addWidget(momentum_label)
        
        self.rsi_check = self._create_checkbox_with_tooltip(
            "RSI",
            'rsi',
            'technical',
            checked=True
        )
        tech_layout.addWidget(self.rsi_check)
        self.rsi_check.toggled.connect(self._update_strategy_tendency)
        
        self.kd_check = self._create_checkbox_with_tooltip(
            "KD",
            'kd',
            'technical',
            checked=False
        )
        tech_layout.addWidget(self.kd_check)
        self.kd_check.toggled.connect(self._update_strategy_tendency)
        
        # 波動/風險類
        volatility_label = QLabel("📊 波動 / 風險 (Volatility)")
        volatility_font = QFont()
        volatility_font.setBold(True)
        volatility_label.setFont(volatility_font)
        tech_layout.addWidget(volatility_label)
        
        self.bollinger_check = self._create_checkbox_with_tooltip(
            "布林通道",
            'bollinger',
            'technical',
            checked=False
        )
        tech_layout.addWidget(self.bollinger_check)
        self.bollinger_check.toggled.connect(self._update_strategy_tendency)
        
        self.atr_check = self._create_checkbox_with_tooltip(
            "ATR",
            'atr',
            'technical',
            checked=False
        )
        tech_layout.addWidget(self.atr_check)
        self.atr_check.toggled.connect(self._update_strategy_tendency)
        
        tech_group.setLayout(tech_layout)
        layout.addWidget(tech_group)
        self.tech_group = tech_group  # 保存引用以便切換顯示
        
        # 圖形模式配置（按交易意圖分類）- 進階模式才顯示
        pattern_group = QGroupBox("圖形模式")
        pattern_layout = QVBoxLayout()
        
        # 反轉類（看漲反轉）
        reversal_label = QLabel("🔄 反轉 (Bullish Reversal)")
        reversal_font = QFont()
        reversal_font.setBold(True)
        reversal_label.setFont(reversal_font)
        pattern_layout.addWidget(reversal_label)
        
        self.pattern_w_bottom = self._create_checkbox_with_tooltip(
            "W底",
            'w_bottom',
            'pattern',
            checked=True
        )
        pattern_layout.addWidget(self.pattern_w_bottom)
        self.pattern_w_bottom.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_head_shoulder_bottom = self._create_checkbox_with_tooltip(
            "頭肩底",
            'head_shoulder_bottom',
            'pattern',
            checked=True
        )
        pattern_layout.addWidget(self.pattern_head_shoulder_bottom)
        self.pattern_head_shoulder_bottom.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_double_bottom = self._create_checkbox_with_tooltip(
            "雙底",
            'double_bottom',
            'pattern',
            checked=True
        )
        pattern_layout.addWidget(self.pattern_double_bottom)
        self.pattern_double_bottom.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_v_reversal = self._create_checkbox_with_tooltip(
            "V形反轉",
            'v_reversal',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_v_reversal)
        self.pattern_v_reversal.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_rounding_bottom = self._create_checkbox_with_tooltip(
            "圓底",
            'rounding_bottom',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_rounding_bottom)
        self.pattern_rounding_bottom.toggled.connect(self._update_strategy_tendency)
        
        # 上漲延續類
        continuation_label = QLabel("📈 上漲延續 (Bullish Continuation)")
        continuation_font = QFont()
        continuation_font.setBold(True)
        continuation_label.setFont(continuation_font)
        pattern_layout.addWidget(continuation_label)
        
        self.pattern_flag = self._create_checkbox_with_tooltip(
            "旗形",
            'flag',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_flag)
        self.pattern_flag.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_wedge = self._create_checkbox_with_tooltip(
            "楔形",
            'wedge',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_wedge)
        self.pattern_wedge.toggled.connect(self._update_strategy_tendency)
        
        # 盤整/區間類
        consolidation_label = QLabel("📊 盤整 / 區間 (Consolidation)")
        consolidation_font = QFont()
        consolidation_font.setBold(True)
        consolidation_label.setFont(consolidation_font)
        pattern_layout.addWidget(consolidation_label)
        
        self.pattern_rectangle = self._create_checkbox_with_tooltip(
            "矩形",
            'rectangle',
            'pattern',
            checked=True
        )
        pattern_layout.addWidget(self.pattern_rectangle)
        self.pattern_rectangle.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_triangle = self._create_checkbox_with_tooltip(
            "三角形",
            'triangle',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_triangle)
        self.pattern_triangle.toggled.connect(self._update_strategy_tendency)
        
        # 下跌訊號類（用於反向篩選）
        bearish_label = QLabel("⚠️ 下跌訊號 (Bearish Signal)")
        bearish_font = QFont()
        bearish_font.setBold(True)
        bearish_label.setFont(bearish_font)
        pattern_layout.addWidget(bearish_label)
        
        self.pattern_head_shoulder_top = self._create_checkbox_with_tooltip(
            "頭肩頂",
            'head_shoulder_top',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_head_shoulder_top)
        self.pattern_head_shoulder_top.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_double_top = self._create_checkbox_with_tooltip(
            "雙頂",
            'double_top',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_double_top)
        self.pattern_double_top.toggled.connect(self._update_strategy_tendency)
        
        self.pattern_rounding_top = self._create_checkbox_with_tooltip(
            "圓頂",
            'rounding_top',
            'pattern',
            checked=False
        )
        pattern_layout.addWidget(self.pattern_rounding_top)
        self.pattern_rounding_top.toggled.connect(self._update_strategy_tendency)
        
        pattern_group.setLayout(pattern_layout)
        layout.addWidget(pattern_group)
        self.pattern_group = pattern_group  # 保存引用以便切換顯示
        
        # 篩選條件 - 進階模式才顯示
        filter_group = QGroupBox("篩選條件")
        filter_layout = QVBoxLayout()
        
        # 最小漲幅
        price_layout = QHBoxLayout()
        price_layout.addWidget(QLabel("最小漲幅%:"))
        self.price_change_min = QDoubleSpinBox()
        self.price_change_min.setRange(0.0, 100.0)
        self.price_change_min.setValue(0.0)
        self.price_change_min.setDecimals(1)
        price_layout.addWidget(self.price_change_min)
        filter_layout.addLayout(price_layout)
        
        # 最小成交量比率
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("最小成交量比率:"))
        self.volume_ratio_min = QDoubleSpinBox()
        self.volume_ratio_min.setRange(0.1, 10.0)
        self.volume_ratio_min.setValue(1.0)
        self.volume_ratio_min.setDecimals(1)
        volume_layout.addWidget(self.volume_ratio_min)
        filter_layout.addLayout(volume_layout)
        
        # 產業篩選
        industry_layout = QHBoxLayout()
        industry_layout.addWidget(QLabel("產業:"))
        self.industry_filter = QComboBox()
        self.industry_filter.addItem("全部")
        # 從 IndustryMapper 獲取產業列表
        try:
            if hasattr(self.recommendation_service, 'industry_mapper'):
                industries = self.recommendation_service.industry_mapper.get_all_industries()
                for industry in sorted(industries):
                    self.industry_filter.addItem(industry)
        except Exception as e:
            print(f"[RecommendationView] 載入產業列表失敗: {e}")
        industry_layout.addWidget(self.industry_filter)
        filter_layout.addLayout(industry_layout)
        
        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)
        self.filter_group = filter_group  # 保存引用以便切換顯示
        
        # 執行按鈕
        self.execute_btn = QPushButton("執行推薦分析")
        self.execute_btn.setMinimumHeight(40)
        self.execute_btn.clicked.connect(self._execute_recommendation)
        layout.addWidget(self.execute_btn)
        
        # 進度條
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 進度文本
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)
        
        layout.addStretch()
        
        # 初始設置：新手模式隱藏進階選項
        self._update_mode_ui()
        
        return panel
    
    def _create_result_panel(self) -> QWidget:
        """創建結果面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        
        # 標題和控制欄
        title_layout = QHBoxLayout()
        title = QLabel("推薦結果")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        
        # 保存結果按鈕
        self.save_result_btn = QPushButton("保存結果")
        self.save_result_btn.setVisible(False)  # 初始隱藏
        self.save_result_btn.clicked.connect(self._save_recommendation_result)
        if self.recommendation_repository:
            title_layout.addWidget(self.save_result_btn)
        
        # 加入觀察清單按鈕
        self.add_to_watchlist_btn = QPushButton("加入觀察清單")
        self.add_to_watchlist_btn.setVisible(False)  # 初始隱藏
        self.add_to_watchlist_btn.clicked.connect(self._add_selected_to_watchlist)
        if self.watchlist_service:
            title_layout.addWidget(self.add_to_watchlist_btn)
        
        # 一鍵送回測按鈕（Phase 3.3）
        self.send_to_backtest_btn = QPushButton("一鍵送回測")
        self.send_to_backtest_btn.setVisible(False)  # 初始隱藏
        self.send_to_backtest_btn.clicked.connect(self._send_to_backtest)
        title_layout.addWidget(self.send_to_backtest_btn)
        
        layout.addLayout(title_layout)
        
        # 使用分割器來控制表格和詳情的比例
        result_splitter = QSplitter(Qt.Vertical)
        
        # 結果表格
        self.results_table = QTableView()
        self.results_table.setSortingEnabled(True)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setAlternatingRowColors(True)
        # 設置選擇模式為單行選擇
        self.results_table.setSelectionBehavior(QTableView.SelectRows)
        self.results_table.setSelectionMode(QTableView.SingleSelection)
        result_splitter.addWidget(self.results_table)
        
        # 詳細信息（推薦理由）
        detail_group = QGroupBox("推薦理由詳情")
        detail_layout = QVBoxLayout()
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)
        detail_group.setLayout(detail_layout)
        result_splitter.addWidget(detail_group)
        
        # 設置分割器比例（上面70%，下面30%）
        result_splitter.setSizes([700, 300])
        
        layout.addWidget(result_splitter)
        
        # 注意：表格選擇事件將在設置模型後連接（在 _on_recommendation_finished 中）
        
        return panel
    
    def _load_current_regime(self):
        """載入當前市場狀態"""
        try:
            regime_result = self.regime_service.detect_regime()
            regime_text = f"市場狀態：{regime_result.regime_name_cn}\n"
            regime_text += f"信心度：{regime_result.confidence:.0%}"
            self.regime_label.setText(regime_text)
            
            # 更新策略配置中的 regime
            self.strategy_config['regime'] = regime_result.regime
            self.current_regime = regime_result.regime
            
            # 根據 Regime 建議 Profile（Phase 3.2）
            self._suggest_profile_for_regime(regime_result.regime, regime_result.confidence)
            
            # 根據 Regime 自動調整策略配置（如果用戶沒有選擇 Profile）
            if not self.current_profile:
                auto_config = self.regime_service.get_strategy_config(regime_result.regime)
                if auto_config:
                    # 合併自動配置（保留用戶設置的篩選條件）
                    self.strategy_config.update(auto_config)
                    self._update_ui_from_config()
        except Exception as e:
            self.regime_label.setText(f"檢測失敗：{str(e)}")
    
    def _suggest_profile_for_regime(self, regime: str, confidence: float):
        """根據市場狀態建議 Profile（Phase 3.2）
        
        Args:
            regime: 市場狀態（'Trend' | 'Reversion' | 'Breakout'）
            confidence: 信心度（0-1）
        """
        # 找到適用該 Regime 的 Profiles
        suitable_profiles = []
        for profile_id, profile in self.profiles.items():
            if regime in profile.get('regime', []):
                suitable_profiles.append((profile_id, profile))
        
        if not suitable_profiles:
            # 沒有適用的 Profile，隱藏建議
            if hasattr(self, 'regime_suggestion_group'):
                self.regime_suggestion_group.setVisible(False)
            return
        
        # 選擇最適合的 Profile（優先選擇風險等級適中的）
        # 如果信心度高，可以選擇風險較高的 Profile
        if confidence >= 0.7:
            # 高信心度：優先選擇風險較高的 Profile
            suitable_profiles.sort(key=lambda x: {'high': 3, 'medium': 2, 'low': 1}.get(x[1].get('risk_level', 'medium'), 2), reverse=True)
        else:
            # 低信心度：優先選擇風險較低的 Profile
            suitable_profiles.sort(key=lambda x: {'high': 1, 'medium': 2, 'low': 3}.get(x[1].get('risk_level', 'medium'), 2), reverse=True)
        
        suggested_profile_id, suggested_profile = suitable_profiles[0]
        self.suggested_profile_id = suggested_profile_id
        
        # 顯示建議（如果建議區塊存在）
        if hasattr(self, 'regime_suggestion_group'):
            self._update_regime_suggestion(suggested_profile_id, suggested_profile, confidence)
            self.regime_suggestion_group.setVisible(True)
    
    def _update_regime_suggestion(self, profile_id: str, profile: Dict[str, Any], confidence: float):
        """更新 Regime 建議顯示
        
        Args:
            profile_id: 建議的 Profile ID
            profile: Profile 資料
            confidence: 市場狀態信心度
        """
        regime_names = {
            'Trend': '趨勢追蹤',
            'Reversion': '均值回歸',
            'Breakout': '突破準備'
        }
        current_regime_name = regime_names.get(self.current_regime, self.current_regime)
        
        suggestion_text = f"<b>💡 根據當前市場狀態（{current_regime_name}，信心度 {confidence:.0%}）</b><br/>"
        suggestion_text += f"<b>建議使用：{profile['name']}</b><br/><br/>"
        suggestion_text += f"{profile['description']}<br/><br/>"
        suggestion_text += f"<b>風險等級：</b>{profile.get('risk_level', '未知')}"
        
        self.regime_suggestion_label.setText(suggestion_text)
        self.apply_suggestion_btn.setVisible(True)
    
    def _apply_suggested_profile(self):
        """一鍵套用建議的 Profile"""
        if not self.suggested_profile_id:
            return
        
        profile = self.profiles.get(self.suggested_profile_id)
        if not profile:
            return
        
        # 切換到新手模式（如果當前是進階模式）
        if not self.is_beginner_mode:
            self.is_beginner_mode = True
            self._update_mode_ui()
        
        # 在 Profile 下拉選單中選擇建議的 Profile
        for i in range(self.profile_combo.count()):
            if self.profile_combo.itemData(i) == self.suggested_profile_id:
                self.profile_combo.setCurrentIndex(i)
                break
        
        # 套用 Profile 配置
        self._apply_profile_config(profile)
        
        # 顯示提示
        QMessageBox.information(
            self,
            "已套用建議 Profile",
            f"已套用建議的 Profile：{profile['name']}\n\n"
            f"配置已自動更新，您可以點擊「執行推薦分析」開始分析。"
        )
    
    def _update_ui_from_config(self):
        """從配置更新 UI"""
        # 更新技術指標
        momentum = self.strategy_config.get('technical', {}).get('momentum', {})
        self.rsi_check.setChecked(momentum.get('rsi', {}).get('enabled', False))
        self.macd_check.setChecked(momentum.get('macd', {}).get('enabled', False))
        self.kd_check.setChecked(momentum.get('kd', {}).get('enabled', False))
        
        trend = self.strategy_config.get('technical', {}).get('trend', {})
        self.ma_check.setChecked(trend.get('ma', {}).get('enabled', False))
        self.adx_check.setChecked(trend.get('adx', {}).get('enabled', False))
        
        volatility = self.strategy_config.get('technical', {}).get('volatility', {})
        self.bollinger_check.setChecked(volatility.get('bollinger', {}).get('enabled', False))
        self.atr_check.setChecked(volatility.get('atr', {}).get('enabled', False))
        
        # 更新圖形模式
        patterns = self.strategy_config.get('patterns', {}).get('selected', [])
        self.pattern_w_bottom.setChecked('W底' in patterns)
        self.pattern_head_shoulder_bottom.setChecked('頭肩底' in patterns)
        self.pattern_double_bottom.setChecked('雙底' in patterns)
        self.pattern_v_reversal.setChecked('V形反轉' in patterns)
        self.pattern_rounding_bottom.setChecked('圓底' in patterns)
        self.pattern_rectangle.setChecked('矩形' in patterns)
        self.pattern_triangle.setChecked('三角形' in patterns)
        self.pattern_flag.setChecked('旗形' in patterns)
        self.pattern_wedge.setChecked('楔形' in patterns)
        self.pattern_head_shoulder_top.setChecked('頭肩頂' in patterns)
        self.pattern_double_top.setChecked('雙頂' in patterns)
        self.pattern_rounding_top.setChecked('圓頂' in patterns)
        
        # 更新篩選條件
        filters = self.strategy_config.get('filters', {})
        self.price_change_min.setValue(filters.get('price_change_min', 0.0))
        self.volume_ratio_min.setValue(filters.get('volume_ratio_min', 1.0))
        
        # 更新策略傾向
        self._update_strategy_tendency()
    
    def _toggle_mode(self):
        """切換新手/進階模式"""
        self.is_beginner_mode = not self.is_beginner_mode
        self._update_mode_ui()
    
    def _update_mode_ui(self):
        """根據模式更新 UI 顯示"""
        if self.is_beginner_mode:
            # 新手模式：顯示 Profile 選擇，隱藏詳細配置
            self.mode_btn.setText("切換至進階模式")
            self.profile_group.setVisible(True)
            self.tech_group.setVisible(False)
            self.pattern_group.setVisible(False)
            self.filter_group.setVisible(False)
            self.strategy_tendency_group.setVisible(False)
            # Regime 建議在新手模式下顯示
            if hasattr(self, 'regime_suggestion_group'):
                self.regime_suggestion_group.setVisible(self.suggested_profile_id is not None)
        else:
            # 進階模式：隱藏 Profile 選擇，顯示詳細配置
            self.mode_btn.setText("切換至新手模式")
            self.profile_group.setVisible(False)
            self.tech_group.setVisible(True)
            self.pattern_group.setVisible(True)
            self.filter_group.setVisible(True)
            self.strategy_tendency_group.setVisible(True)
            # Regime 建議在進階模式下也顯示（但一鍵套用按鈕可能不太有用）
            if hasattr(self, 'regime_suggestion_group'):
                self.regime_suggestion_group.setVisible(self.suggested_profile_id is not None)
    
    def _on_profile_selected(self, index: int):
        """Profile 選擇改變"""
        profile_id = self.profile_combo.itemData(index)
        if profile_id is None:
            self.profile_desc_label.setText("")
            return
        
        profile = self.profiles.get(profile_id)
        if not profile:
            return
        
        # 顯示 Profile 說明（包含風險提示）
        desc_text = f"<b>{profile['name']}</b> (v{profile.get('version', '1.0.0')})<br/>"
        desc_text += f"{profile['description']}<br/><br/>"
        
        # 適用市場狀態
        regime_names = {
            'Trend': '趨勢追蹤',
            'Reversion': '均值回歸',
            'Breakout': '突破準備'
        }
        suitable_regimes = [regime_names.get(r, r) for r in profile.get('regime', [])]
        desc_text += f"<b>✓ 適用市場狀態：</b>{'、'.join(suitable_regimes)}<br/>"
        
        # 不適用市場狀態
        not_suitable_regimes = profile.get('regime_not_suitable', [])
        if not_suitable_regimes:
            not_suitable_names = [regime_names.get(r, r) for r in not_suitable_regimes]
            desc_text += f"<b>✗ 不適用市場狀態：</b>{'、'.join(not_suitable_names)}<br/>"
        
        # 風險提示
        risk_warning = profile.get('risk_warning', {})
        if risk_warning:
            desc_text += f"<br/><b>風險提示：</b><br/>"
            desc_text += f"  • 預期最大回撤：{risk_warning.get('max_drawdown_expected', '未知')}<br/>"
            desc_text += f"  • 波動性：{risk_warning.get('volatility', '未知')}<br/>"
            desc_text += f"  • 建議持有期間：{risk_warning.get('holding_period', '未知')}<br/>"
            desc_text += f"  • 適合：{risk_warning.get('suitable_for', '未知')}<br/>"
        
        self.profile_desc_label.setText(desc_text)
        
        # 套用 Profile 配置
        self._apply_profile_config(profile)
    
    def _apply_profile_config(self, profile: Dict[str, Any]):
        """套用 Profile 配置到 UI"""
        config = profile.get('config', {})
        
        # 更新技術指標
        tech_config = config.get('technical', {})
        momentum = tech_config.get('momentum', {})
        self.rsi_check.setChecked(momentum.get('rsi', {}).get('enabled', False))
        self.macd_check.setChecked(momentum.get('macd', {}).get('enabled', False))
        self.kd_check.setChecked(momentum.get('kd', {}).get('enabled', False))
        
        trend = tech_config.get('trend', {})
        self.ma_check.setChecked(trend.get('ma', {}).get('enabled', False))
        self.adx_check.setChecked(trend.get('adx', {}).get('enabled', False))
        
        volatility = tech_config.get('volatility', {})
        self.bollinger_check.setChecked(volatility.get('bollinger', {}).get('enabled', False))
        self.atr_check.setChecked(volatility.get('atr', {}).get('enabled', False))
        
        # 更新圖形模式
        patterns = config.get('patterns', {}).get('selected', [])
        self.pattern_w_bottom.setChecked('W底' in patterns)
        self.pattern_head_shoulder_bottom.setChecked('頭肩底' in patterns)
        self.pattern_double_bottom.setChecked('雙底' in patterns)
        self.pattern_v_reversal.setChecked('V形反轉' in patterns)
        self.pattern_rounding_bottom.setChecked('圓底' in patterns)
        self.pattern_rectangle.setChecked('矩形' in patterns)
        self.pattern_triangle.setChecked('三角形' in patterns)
        self.pattern_flag.setChecked('旗形' in patterns)
        self.pattern_wedge.setChecked('楔形' in patterns)
        self.pattern_head_shoulder_top.setChecked('頭肩頂' in patterns)
        self.pattern_double_top.setChecked('雙頂' in patterns)
        self.pattern_rounding_top.setChecked('圓頂' in patterns)
        
        # 更新篩選條件
        filters = config.get('filters', {})
        self.price_change_min.setValue(filters.get('price_change_min', 0.0))
        self.volume_ratio_min.setValue(filters.get('volume_ratio_min', 1.0))
        
        # 更新策略傾向
        self._update_strategy_tendency()
    
    def _update_strategy_tendency(self):
        """根據當前選擇的指標/圖形，動態更新策略傾向提示"""
        # 收集已勾選的技術指標
        selected_indicators = []
        if self.ma_check.isChecked():
            selected_indicators.append(self.technical_descriptions['ma'])
        if self.adx_check.isChecked():
            selected_indicators.append(self.technical_descriptions['adx'])
        if self.macd_check.isChecked():
            selected_indicators.append(self.technical_descriptions['macd'])
        if self.rsi_check.isChecked():
            selected_indicators.append(self.technical_descriptions['rsi'])
        if self.kd_check.isChecked():
            selected_indicators.append(self.technical_descriptions['kd'])
        if self.bollinger_check.isChecked():
            selected_indicators.append(self.technical_descriptions['bollinger'])
        if self.atr_check.isChecked():
            selected_indicators.append(self.technical_descriptions['atr'])
        
        # 收集已勾選的圖形模式
        selected_patterns = []
        if self.pattern_w_bottom.isChecked():
            selected_patterns.append(self.pattern_descriptions['w_bottom'])
        if self.pattern_head_shoulder_bottom.isChecked():
            selected_patterns.append(self.pattern_descriptions['head_shoulder_bottom'])
        if self.pattern_double_bottom.isChecked():
            selected_patterns.append(self.pattern_descriptions['double_bottom'])
        if self.pattern_v_reversal.isChecked():
            selected_patterns.append(self.pattern_descriptions['v_reversal'])
        if self.pattern_rounding_bottom.isChecked():
            selected_patterns.append(self.pattern_descriptions['rounding_bottom'])
        if self.pattern_flag.isChecked():
            selected_patterns.append(self.pattern_descriptions['flag'])
        if self.pattern_wedge.isChecked():
            selected_patterns.append(self.pattern_descriptions['wedge'])
        if self.pattern_rectangle.isChecked():
            selected_patterns.append(self.pattern_descriptions['rectangle'])
        if self.pattern_triangle.isChecked():
            selected_patterns.append(self.pattern_descriptions['triangle'])
        if self.pattern_head_shoulder_top.isChecked():
            selected_patterns.append(self.pattern_descriptions['head_shoulder_top'])
        if self.pattern_double_top.isChecked():
            selected_patterns.append(self.pattern_descriptions['double_top'])
        if self.pattern_rounding_top.isChecked():
            selected_patterns.append(self.pattern_descriptions['rounding_top'])
        
        # 計算策略傾向
        if not selected_indicators and not selected_patterns:
            tendency_text = "請選擇技術指標和圖形模式"
            tendency_icon = "❓"
            tendency_color = "#666666"
        else:
            # 統計各類別數量
            trend_count = sum(1 for ind in selected_indicators if ind['category'] == 'Trend')
            momentum_count = sum(1 for ind in selected_indicators if ind['category'] == 'Momentum')
            volatility_count = sum(1 for ind in selected_indicators if ind['category'] == 'Volatility')
            
            reversal_count = sum(1 for pat in selected_patterns if pat['category'] == 'Reversal')
            continuation_count = sum(1 for pat in selected_patterns if pat['category'] == 'Continuation')
            consolidation_count = sum(1 for pat in selected_patterns if pat['category'] == 'Consolidation')
            
            # 判斷策略傾向
            # 趨勢策略：Trend 類指標權重較高
            if trend_count >= 2 and (momentum_count + volatility_count) <= 2:
                tendency_text = "目前選擇偏向：📈 趨勢追蹤策略"
                tendency_icon = "📈"
                tendency_color = "#16a34a"
            # 反轉策略：Momentum + Reversal 類為主
            elif (momentum_count >= 1 and reversal_count >= 2) or (reversal_count >= 3):
                tendency_text = "目前選擇偏向：🔄 反轉策略"
                tendency_icon = "🔄"
                tendency_color = "#2563eb"
            # 盤整策略：Volatility / Consolidation 為主
            elif (volatility_count >= 1 and consolidation_count >= 1) or consolidation_count >= 2:
                tendency_text = "目前選擇偏向：📊 盤整 / 區間策略"
                tendency_icon = "📊"
                tendency_color = "#7c3aed"
            # 延續策略：Continuation 為主
            elif continuation_count >= 1 and trend_count >= 1:
                tendency_text = "目前選擇偏向：📈 趨勢延續策略"
                tendency_icon = "📈"
                tendency_color = "#16a34a"
            # 混合策略
            else:
                tendency_text = "目前選擇偏向：⚠️ 混合策略（可能不穩定）"
                tendency_icon = "⚠️"
                tendency_color = "#dc2626"
        
        # 更新標籤
        self.strategy_tendency_label.setText(tendency_text)
        self.strategy_tendency_label.setStyleSheet(f"""
            QLabel {{
                background-color: {tendency_color}15;
                color: {tendency_color};
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
                border: 1px solid {tendency_color}40;
            }}
        """)
    
    def _collect_config(self) -> Dict[str, Any]:
        """收集策略配置（新手模式使用 Profile 配置，進階模式使用 UI 配置）"""
        # 如果在新手模式下且已選擇 Profile，使用 Profile 配置
        if self.is_beginner_mode and self.current_profile:
            profile = self.profiles.get(self.current_profile)
            if profile:
                config = profile['config'].copy()
                # 添加 Regime 信息
                config['regime'] = self.strategy_config.get('regime')
                return config
        
        # 進階模式或未選擇 Profile：使用 UI 配置
        # 技術指標
        momentum = {
            'enabled': self.rsi_check.isChecked() or self.macd_check.isChecked() or self.kd_check.isChecked(),
            'rsi': {'enabled': self.rsi_check.isChecked(), 'period': 14},
            'macd': {'enabled': self.macd_check.isChecked(), 'fast': 12, 'slow': 26, 'signal': 9},
            'kd': {'enabled': self.kd_check.isChecked()}
        }
        
        trend = {
            'enabled': self.ma_check.isChecked() or self.adx_check.isChecked(),
            'adx': {'enabled': self.adx_check.isChecked(), 'period': 14},
            'ma': {'enabled': self.ma_check.isChecked(), 'windows': [5, 10, 20, 60]}
        }
        
        volatility = {
            'enabled': self.bollinger_check.isChecked() or self.atr_check.isChecked(),
            'bollinger': {'enabled': self.bollinger_check.isChecked(), 'window': 20, 'std': 2},
            'atr': {'enabled': self.atr_check.isChecked(), 'period': 14}
        }
        
        # 圖形模式
        patterns = []
        if self.pattern_w_bottom.isChecked():
            patterns.append('W底')
        if self.pattern_head_shoulder_bottom.isChecked():
            patterns.append('頭肩底')
        if self.pattern_double_bottom.isChecked():
            patterns.append('雙底')
        if self.pattern_v_reversal.isChecked():
            patterns.append('V形反轉')
        if self.pattern_rounding_bottom.isChecked():
            patterns.append('圓底')
        if self.pattern_rectangle.isChecked():
            patterns.append('矩形')
        if self.pattern_triangle.isChecked():
            patterns.append('三角形')
        if self.pattern_flag.isChecked():
            patterns.append('旗形')
        if self.pattern_wedge.isChecked():
            patterns.append('楔形')
        if self.pattern_head_shoulder_top.isChecked():
            patterns.append('頭肩頂')
        if self.pattern_double_top.isChecked():
            patterns.append('雙頂')
        if self.pattern_rounding_top.isChecked():
            patterns.append('圓頂')
        
        # 信號組合
        technical_indicators = []
        if momentum['enabled']:
            technical_indicators.append('momentum')
        if trend['enabled']:
            technical_indicators.append('trend')
        if volatility['enabled']:
            technical_indicators.append('volatility')
        
        # 篩選條件
        filters = {
            'price_change_min': self.price_change_min.value(),
            'price_change_max': 100.0,
            'volume_ratio_min': self.volume_ratio_min.value(),
            'rsi_min': 0,
            'rsi_max': 100,
            'industry': self.industry_filter.currentText()
        }
        
        config = {
            'technical': {
                'momentum': momentum,
                'volatility': volatility,
                'trend': trend
            },
            'patterns': {
                'selected': patterns
            },
            'signals': {
                'technical_indicators': technical_indicators,
                'volume_conditions': ['increasing'],
                'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
            },
            'filters': filters,
            'regime': self.strategy_config.get('regime')
        }
        
        return config
    
    def _execute_recommendation(self):
        """執行推薦分析"""
        # 收集配置
        config = self._collect_config()
        
        # 檢查配置有效性
        if not config['patterns']['selected']:
            QMessageBox.warning(self, "配置錯誤", "請至少選擇一個圖形模式")
            return
        
        if not config['signals']['technical_indicators']:
            QMessageBox.warning(self, "配置錯誤", "請至少選擇一個技術指標")
            return
        
        # 保存當前配置和 Regime（用於後續保存）
        self.current_config = config
        self.current_regime = config.get('regime')
        
        # 保存當前 Profile（如果在新手模式下）
        if self.is_beginner_mode:
            profile_index = self.profile_combo.currentIndex()
            self.current_profile = self.profile_combo.itemData(profile_index)
        else:
            self.current_profile = None
        
        # 禁用執行按鈕
        self.execute_btn.setEnabled(False)
        self.execute_btn.setText("分析中...")
        
        # 顯示進度條
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("準備開始分析...")
        
        # 清空結果
        self.results_table.setModel(None)
        self.detail_text.clear()
        
        # 隱藏保存按鈕（等待結果）
        if self.recommendation_repository:
            self.save_result_btn.setVisible(False)
        
        # 創建 Worker 包裝推薦服務調用
        def recommendation_task(progress_callback=None):
            """推薦分析任務（支持進度回調）"""
            if progress_callback:
                progress_callback("讀取股票數據...", 10)
            
            # 調用推薦服務
            recommendations = self.recommendation_service.run_recommendation(
                config=config,
                max_stocks=200,
                top_n=50
            )
            
            if progress_callback:
                progress_callback("分析完成", 100)
            
            return recommendations
        
        # 創建 Worker
        self.worker = ProgressTaskWorker(recommendation_task)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_recommendation_finished)
        self.worker.error.connect(self._on_recommendation_error)
        self.worker.start()
    
    def _on_progress(self, message: str, percentage: int):
        """進度更新"""
        self.progress_label.setText(message)
        self.progress_bar.setValue(percentage)
    
    def _on_recommendation_finished(self, recommendations: List[RecommendationDTO]):
        """推薦分析完成"""
        # 恢復按鈕
        self.execute_btn.setEnabled(True)
        self.execute_btn.setText("執行推薦分析")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 保存當前推薦結果（用於保存功能）
        self.current_recommendations = recommendations
        
        # 顯示結果
        if not recommendations:
            QMessageBox.information(self, "分析完成", "沒有找到符合條件的推薦股票")
            return
        
        # 轉換為 DataFrame
        data = [rec.to_dict() for rec in recommendations]
        df = pd.DataFrame(data)
        
        # 設置模型
        self.recommendations_model = PandasTableModel(df)
        self.results_table.setModel(self.recommendations_model)
        
        # 連接表格選擇事件（在設置模型後）
        selection_model = self.results_table.selectionModel()
        if selection_model:
            selection_model.selectionChanged.connect(self._on_selection_changed)
        
        # 連接雙擊事件
        self.results_table.doubleClicked.connect(self._on_row_double_clicked)
        
        # 連接單擊事件（確保單擊也能觸發）
        self.results_table.clicked.connect(self._on_row_clicked)
        
        # 調整列寬
        self.results_table.resizeColumnsToContents()
        
        # 顯示統計信息
        self.progress_label.setText(f"找到 {len(recommendations)} 支推薦股票")
        self.progress_label.setVisible(True)
        
        # 顯示按鈕
        if self.watchlist_service:
            self.add_to_watchlist_btn.setVisible(True)
        if self.recommendation_repository:
            self.save_result_btn.setVisible(True)
        # 一鍵送回測按鈕（只要有推薦結果就顯示）
        self.send_to_backtest_btn.setVisible(True)
    
    def _on_recommendation_error(self, error_msg: str):
        """推薦分析出錯"""
        # 恢復按鈕
        self.execute_btn.setEnabled(True)
        self.execute_btn.setText("執行推薦分析")
        
        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        # 顯示錯誤（如果錯誤信息太長，截取前500字符）
        display_msg = error_msg[:500] + "..." if len(error_msg) > 500 else error_msg
        QMessageBox.critical(
            self, 
            "分析失敗", 
            f"推薦分析失敗：\n\n{display_msg}\n\n"
            f"請檢查：\n"
            f"1. 數據文件是否存在且格式正確\n"
            f"2. 技術指標計算所需的欄位是否完整\n"
            f"3. 查看日誌文件獲取詳細錯誤信息"
        )
    
    def _send_to_backtest(self):
        """一鍵送回測（Profile → Backtest）（Phase 3.3）"""
        if not self.current_recommendations or not self.current_config:
            QMessageBox.warning(self, "錯誤", "沒有可送回測的推薦結果")
            return
        
        # 獲取選中的股票（如果沒有選中，則使用所有推薦股票）
        selection = self.results_table.selectionModel()
        selected_stocks = []
        
        if selection and selection.selectedRows():
            # 使用選中的股票
            df = self.recommendations_model.getDataFrame()
            for index in selection.selectedRows():
                row = index.row()
                if row < len(df):
                    stock_code = df.iloc[row].get('證券代號')
                    if stock_code:
                        selected_stocks.append(str(stock_code))
        else:
            # 使用所有推薦股票（最多前 20 檔）
            for rec in self.current_recommendations[:20]:
                selected_stocks.append(rec.stock_code)
        
        if not selected_stocks:
            QMessageBox.warning(self, "錯誤", "沒有可送回測的股票")
            return
        
        # 準備回測配置
        backtest_config = {
            'stock_list': selected_stocks,
            'profile_id': self.current_profile,
            'profile_name': None,
            'strategy_config': self.current_config,
            'regime': self.current_regime,
            'regime_snapshot': None
        }
        
        # 如果有 Profile，添加 Profile 信息
        if self.current_profile and self.current_profile in self.profiles:
            profile = self.profiles[self.current_profile]
            backtest_config['profile_name'] = profile.get('name', '')
            backtest_config['profile_version'] = profile.get('version', '1.0.0')
        
        # 創建 Regime snapshot
        if self.current_regime:
            try:
                regime_result = self.regime_service.detect_regime()
                backtest_config['regime_snapshot'] = {
                    'regime': regime_result.regime,
                    'regime_name_cn': regime_result.regime_name_cn,
                    'confidence': regime_result.confidence,
                    'details': regime_result.details,
                    'detected_at': datetime.now().isoformat()
                }
            except:
                backtest_config['regime_snapshot'] = {
                    'regime': self.current_regime,
                    'detected_at': datetime.now().isoformat()
                }
        
        # 發送信號
        self.sendToBacktestRequested.emit(backtest_config)
        
        # 顯示提示
        QMessageBox.information(
            self,
            "已送出",
            f"已將 {len(selected_stocks)} 檔股票送出到策略回測\n\n"
            f"請切換到「策略回測」標籤查看。"
        )
    
    def _add_selected_to_watchlist(self):
        """將選中的股票加入觀察清單"""
        if not self.watchlist_service or not self.recommendations_model:
            return
        
        selection = self.results_table.selectionModel().selectedRows()
        if not selection:
            QMessageBox.warning(self, "提示", "請先選擇要加入觀察清單的股票")
            return
        
        # 取得選中的股票
        df = self.recommendations_model.getDataFrame()
        stocks = []
        for index in selection:
            row = index.row()
            if row < len(df):
                stock_code = df.iloc[row].get('證券代號')
                stock_name = df.iloc[row].get('證券名稱', stock_code)
                if stock_code:
                    stocks.append({
                        'stock_code': str(stock_code),
                        'stock_name': str(stock_name)
                    })
        
        if stocks:
            try:
                # 添加來源信息（Profile/時間/Regime）到 notes
                profile_name = self.current_profile or '進階模式'
                if self.current_profile and self.current_profile in self.profiles:
                    profile_name = self.profiles[self.current_profile]['name']
                
                regime_name = self.current_regime or '未知'
                notes = f"來源：{profile_name}, Regime: {regime_name}, 時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                
                # 將 notes 添加到每個股票
                for stock in stocks:
                    stock['notes'] = notes
                
                added_count = self.watchlist_service.add_stocks(stocks, source='recommendation')
                if added_count > 0:
                    QMessageBox.information(self, "成功", f"已將 {added_count} 檔股票加入觀察清單\n{notes}")
                else:
                    QMessageBox.warning(self, "提示", "選中的股票已在觀察清單中")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"加入觀察清單失敗：\n{str(e)}")
    
    def _save_recommendation_result(self):
        """保存推薦結果"""
        if not self.recommendation_repository:
            QMessageBox.warning(self, "錯誤", "推薦結果儲存庫未初始化")
            return
        
        if not self.current_recommendations or not self.current_config:
            QMessageBox.warning(self, "錯誤", "沒有可保存的推薦結果")
            return
        
        # 顯示輸入對話框
        from PySide6.QtWidgets import QInputDialog
        result_name, ok = QInputDialog.getText(
            self,
            "保存推薦結果",
            "請輸入結果名稱:",
            text=f"推薦結果_{datetime.now().strftime('%Y%m%d_%H%M')}"
        )
        
        if not ok or not result_name.strip():
            return
        
        try:
            # 創建 RecommendationResultDTO（包含完整的 Profile meta 信息，Phase 3.2）
            # 在 config 中添加 profile 信息
            config_with_meta = self.current_config.copy() if self.current_config else {}
            if self.current_profile:
                profile = self.profiles.get(self.current_profile, {})
                if profile:
                    config_with_meta['profile_id'] = self.current_profile
                    config_with_meta['profile_name'] = profile.get('name', '')
                    config_with_meta['profile_version'] = profile.get('version', '1.0.0')
            
            # 創建 regime_snapshot（包含完整的市場狀態信息）
            regime_snapshot = None
            if self.current_regime:
                try:
                    regime_result = self.regime_service.detect_regime()
                    regime_snapshot = {
                        'regime': regime_result.regime,
                        'regime_name_cn': regime_result.regime_name_cn,
                        'confidence': regime_result.confidence,
                        'details': regime_result.details,
                        'detected_at': datetime.now().isoformat()
                    }
                except:
                    # 如果檢測失敗，至少保存基本的 regime 信息
                    regime_snapshot = {
                        'regime': self.current_regime,
                        'detected_at': datetime.now().isoformat()
                    }
            
            result = RecommendationResultDTO(
                result_id="",  # 將由 Repository 生成
                result_name=result_name.strip(),
                config=config_with_meta,
                recommendations=self.current_recommendations,
                regime=self.current_regime,
                created_at=datetime.now().isoformat(),
                notes=f"Profile: {self.current_profile or '進階模式'}, Regime: {self.current_regime or '未知'}"
            )
            
            # 將 regime_snapshot 添加到 config 中（因為 RecommendationResultDTO 沒有專門的字段）
            if regime_snapshot:
                result.config['regime_snapshot'] = regime_snapshot
            
            # 保存推薦結果
            result_id = self.recommendation_repository.save_result(result)
            
            # 自動創建選股清單（如果 universe_service 可用）
            watchlist_id = None
            if self.universe_service and self.current_recommendations:
                try:
                    # 提取股票代號列表
                    stock_codes = [rec.stock_code for rec in self.current_recommendations]
                    
                    # 創建選股清單名稱（使用推薦結果名稱）
                    watchlist_name = f"{result_name.strip()}"
                    
                    # 創建選股清單描述
                    description = f"來自推薦結果: {result_id}\n"
                    if self.current_profile:
                        description += f"Profile: {self.current_profile}\n"
                    if self.current_regime:
                        description += f"Regime: {self.current_regime}\n"
                    description += f"股票數量: {len(stock_codes)}"
                    
                    # 保存選股清單
                    watchlist_id = self.universe_service.save_watchlist(
                        name=watchlist_name,
                        codes=stock_codes,
                        source="recommendation",
                        description=description
                    )
                except Exception as e:
                    # 如果創建選股清單失敗，只記錄錯誤但不影響推薦結果的保存
                    print(f"[RecommendationView] 創建選股清單失敗: {e}")
            
            # 顯示成功訊息
            success_msg = f"推薦結果已保存！\n結果ID: {result_id}\n股票數量: {len(self.current_recommendations)}"
            if watchlist_id:
                success_msg += f"\n\n已自動創建選股清單：{watchlist_name}\n可在「策略回測」Tab 的選股清單中查看"
            
            QMessageBox.information(
                self,
                "成功",
                success_msg
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self,
                "錯誤",
                f"保存推薦結果失敗：\n{str(e)}\n\n{traceback.format_exc()}"
            )
    
    def _on_selection_changed(self):
        """表格選擇改變（單擊時觸發）"""
        self._update_detail_text()
    
    def _on_row_clicked(self, index):
        """表格行單擊事件"""
        self._update_detail_text()
    
    def _on_row_double_clicked(self, index):
        """表格行雙擊事件"""
        self._update_detail_text()
    
    def _generate_why_not(self, recommendation: RecommendationDTO, config: Dict[str, Any]) -> str:
        """生成 Why Not（反向解釋）：為什麼分數不夠高或可能被其他股票超越
        
        Args:
            recommendation: 推薦股票 DTO
            config: 策略配置
            
        Returns:
            str: Why Not 說明文字（HTML 格式）
        """
        why_not_items = []
        
        # 檢查各子分數（相對於理想值）
        # 理想值：各子分數都應該在 60 以上才算優秀
        ideal_score = 60.0
        
        if recommendation.indicator_score < ideal_score:
            gap = ideal_score - recommendation.indicator_score
            why_not_items.append({
                'item': '技術指標分數',
                'current': f'{recommendation.indicator_score:.1f}',
                'ideal': f'{ideal_score:.1f}',
                'gap': f'{gap:.1f}',
                'severity': 'high' if gap > 20 else 'medium' if gap > 10 else 'low',
                'hint': '可考慮等待更多技術指標訊號'
            })
        
        if recommendation.pattern_score < ideal_score:
            gap = ideal_score - recommendation.pattern_score
            why_not_items.append({
                'item': '圖形模式分數',
                'current': f'{recommendation.pattern_score:.1f}',
                'ideal': f'{ideal_score:.1f}',
                'gap': f'{gap:.1f}',
                'severity': 'high' if gap > 20 else 'medium' if gap > 10 else 'low',
                'hint': '圖形模式尚未完全形成'
            })
        
        if recommendation.volume_score < ideal_score:
            gap = ideal_score - recommendation.volume_score
            why_not_items.append({
                'item': '成交量分數',
                'current': f'{recommendation.volume_score:.1f}',
                'ideal': f'{ideal_score:.1f}',
                'gap': f'{gap:.1f}',
                'severity': 'medium' if gap > 15 else 'low',
                'hint': '成交量可能尚未明顯放大'
            })
        
        # 檢查篩選條件（如果不符合會被直接過濾）
        filters = config.get('filters', {})
        price_change_min = filters.get('price_change_min', 0.0)
        if recommendation.price_change < price_change_min:
            gap = price_change_min - recommendation.price_change
            why_not_items.append({
                'item': '漲幅篩選',
                'current': f'{recommendation.price_change:.1f}%',
                'required': f'{price_change_min:.1f}%',
                'gap': f'{gap:.1f}%',
                'severity': 'high',
                'hint': '不符合漲幅篩選條件，可能被過濾'
            })
        
        price_change_max = filters.get('price_change_max', 100.0)
        if recommendation.price_change > price_change_max:
            gap = recommendation.price_change - price_change_max
            why_not_items.append({
                'item': '漲幅上限',
                'current': f'{recommendation.price_change:.1f}%',
                'required': f'{price_change_max:.1f}%',
                'gap': f'{gap:.1f}%',
                'severity': 'medium',
                'hint': '漲幅過大，可能不符合策略要求'
            })
        
        # 檢查 Regime 匹配
        if not recommendation.regime_match:
            why_not_items.append({
                'item': '市場狀態匹配',
                'current': '不匹配',
                'required': '匹配',
                'gap': '需等待市場狀態變化',
                'severity': 'medium',
                'hint': '當前市場狀態與策略不匹配，分數可能被降權'
            })
        
        # 總分相對排名提示（如果總分較低）
        if recommendation.total_score < 50:
            why_not_items.append({
                'item': '總分偏低',
                'current': f'{recommendation.total_score:.1f}',
                'ideal': '60.0+',
                'gap': f'{60 - recommendation.total_score:.1f}',
                'severity': 'high',
                'hint': '總分較低，可能排名較後'
            })
        
        # 格式化輸出
        if not why_not_items:
            return "<div style='line-height: 1.6;'><p style='color: #16a34a;'><b>✓ 所有條件均符合，分數表現優秀</b></p></div>"
        
        html_text = "<div style='line-height: 1.6;'>"
        html_text += "<p style='margin: 5px 0;'><b>⚠️ 可能影響排名的因素：</b></p>"
        html_text += "<ul style='margin: 5px 0; padding-left: 20px;'>"
        
        for item in why_not_items:
            severity_color = {
                'high': '#dc2626',
                'medium': '#f59e0b',
                'low': '#6b7280'
            }.get(item['severity'], '#6b7280')
            
            html_text += f"<li style='margin: 5px 0;'>"
            html_text += f"<span style='color: {severity_color}; font-weight: bold;'>{item['item']}</span><br/>"
            html_text += f"&nbsp;&nbsp;目前：{item['current']}"
            if 'ideal' in item:
                html_text += f"，理想：{item['ideal']}"
            elif 'required' in item:
                html_text += f"，需要：{item['required']}"
            html_text += f"，差距：{item['gap']}<br/>"
            if 'hint' in item:
                html_text += f"&nbsp;&nbsp;<span style='color: #6b7280; font-size: 0.9em;'>{item['hint']}</span>"
            html_text += "</li>"
        
        html_text += "</ul>"
        html_text += "</div>"
        
        return html_text
    
    def _format_recommendation_reason(self, reason_text: str) -> str:
        """格式化推薦理由，使用 Tag/關鍵詞高亮顯示，並加入可反推線索
        
        Args:
            reason_text: 原始推薦理由文字
            
        Returns:
            str: 格式化後的推薦理由（使用 HTML 格式以便高亮）
        """
        if not reason_text:
            return "無推薦理由"
        
        # 從集中資料結構建立關鍵詞映射（技術指標）
        technical_keywords = {}
        for key, desc in self.technical_descriptions.items():
            # 建立名稱映射
            name_map = {
                'ma': ['移動平均', '均線', 'MA'],
                'adx': ['ADX'],
                'macd': ['MACD'],
                'rsi': ['RSI'],
                'kd': ['KD'],
                'bollinger': ['布林', '布林通道'],
                'atr': ['ATR']
            }
            for name in name_map.get(key, []):
                technical_keywords[name] = {
                    'display': f'📊 <b style="color: #2563eb;">{name}</b>',
                    'category': desc.get('category', ''),
                    'tags': desc.get('tags', [])
                }
        
        # 從集中資料結構建立關鍵詞映射（圖形模式）
        pattern_keywords = {}
        for key, desc in self.pattern_descriptions.items():
            # 建立名稱映射
            name_map = {
                'w_bottom': ['W底'],
                'head_shoulder_bottom': ['頭肩底'],
                'double_bottom': ['雙底'],
                'v_reversal': ['V形反轉', 'V形'],
                'rounding_bottom': ['圓底'],
                'flag': ['旗形'],
                'wedge': ['楔形'],
                'rectangle': ['矩形'],
                'triangle': ['三角形'],
                'head_shoulder_top': ['頭肩頂'],
                'double_top': ['雙頂'],
                'rounding_top': ['圓頂']
            }
            for name in name_map.get(key, []):
                category = desc.get('category', '')
                if category == 'Reversal':
                    icon = '🔄'
                    color = '#16a34a'
                elif category == 'Continuation':
                    icon = '📈'
                    color = '#16a34a'
                elif category == 'Consolidation':
                    icon = '📊'
                    color = '#7c3aed'
                else:  # Bearish
                    icon = '⚠️'
                    color = '#dc2626'
                
                pattern_keywords[name] = {
                    'display': f'{icon} <b style="color: {color};">{name}</b>',
                    'category': category,
                    'tags': desc.get('tags', [])
                }
        
        # 替換關鍵詞
        formatted_text = reason_text
        all_keywords = {**technical_keywords, **pattern_keywords}
        
        # 按長度排序，先替換長關鍵詞
        sorted_keywords = sorted(all_keywords.keys(), key=len, reverse=True)
        for keyword in sorted_keywords:
            if keyword in formatted_text:
                formatted_text = formatted_text.replace(keyword, all_keywords[keyword]['display'])
        
        # 其他標籤映射
        other_tags = {
            '趨勢': '📈 <b style="color: #2563eb;">趨勢</b>',
            '動能': '⚡ <b style="color: #2563eb;">動能</b>',
            '波動': '📊 <b style="color: #2563eb;">波動</b>',
            '反轉': '🔄 <b style="color: #16a34a;">反轉</b>',
            '延續': '📈 <b style="color: #16a34a;">延續</b>',
            '盤整': '📊 <b style="color: #16a34a;">盤整</b>',
            '超買': '<span style="color: #dc2626;">超買</span>',
            '超賣': '<span style="color: #16a34a;">超賣</span>',
            '金叉': '<span style="color: #16a34a;">金叉</span>',
            '死叉': '<span style="color: #dc2626;">死叉</span>',
            '多頭': '<span style="color: #16a34a;">多頭</span>',
            '空頭': '<span style="color: #dc2626;">空頭</span>',
            '成交量': '📊 <b style="color: #2563eb;">成交量</b>',
        }
        
        for keyword, replacement in other_tags.items():
            formatted_text = formatted_text.replace(keyword, replacement)
        
        # 解析理由文字，提取觸發來源
        # 如果理由文字包含 "、" 分隔符，則按分隔符拆分
        if '、' in formatted_text:
            parts = formatted_text.split('、')
            formatted_parts = []
            triggered_indicators = []
            triggered_patterns = []
            
            for part in parts:
                part = part.strip()
                if part:
                    # 移除 + 或 - 符號
                    clean_part = part.replace('+', '').replace('-', '')
                    
                    # 檢查是否包含技術指標
                    for keyword, info in technical_keywords.items():
                        if keyword in clean_part:
                            if keyword not in triggered_indicators:
                                triggered_indicators.append(keyword)
                    
                    # 檢查是否包含圖形模式
                    for keyword, info in pattern_keywords.items():
                        if keyword in clean_part:
                            if keyword not in triggered_patterns:
                                triggered_patterns.append(keyword)
                    
                    formatted_parts.append(f"• {clean_part}")
            
            # 組合為 HTML 格式
            html_text = "<div style='line-height: 1.6;'>"
            html_text += "<p style='margin: 5px 0;'><b>推薦理由：</b></p>"
            
            # 顯示觸發來源（可反推線索）
            if triggered_indicators or triggered_patterns:
                html_text += "<p style='margin: 5px 0; font-size: 0.9em; color: #666;'><b>觸發來源：</b>"
                if triggered_indicators:
                    indicators_display = '、'.join([all_keywords[k]['display'] for k in triggered_indicators if k in all_keywords])
                    html_text += f"📊 技術指標：{indicators_display}"
                if triggered_patterns:
                    if triggered_indicators:
                        html_text += " | "
                    patterns_display = '、'.join([all_keywords[k]['display'] for k in triggered_patterns if k in all_keywords])
                    html_text += f"🔺 圖形訊號：{patterns_display}"
                html_text += "</p>"
            
            html_text += "<ul style='margin: 5px 0; padding-left: 20px;'>"
            for part in formatted_parts:
                html_text += f"<li style='margin: 3px 0;'>{part}</li>"
            html_text += "</ul>"
            html_text += "</div>"
            return html_text
        else:
            # 單一理由，直接格式化
            html_text = "<div style='line-height: 1.6;'>"
            html_text += f"<p style='margin: 5px 0;'><b>推薦理由：</b>{formatted_text}</p>"
            html_text += "</div>"
            return html_text
    
    def _update_detail_text(self):
        """更新推薦理由詳情顯示"""
        if not self.recommendations_model:
            self.detail_text.clear()
            return
        
        selection = self.results_table.selectionModel()
        if not selection:
            self.detail_text.clear()
            return
        
        selected_rows = selection.selectedRows()
        if not selected_rows:
            self.detail_text.clear()
            return
        
        # 獲取選中的行
        row = selected_rows[0].row()
        df = self.recommendations_model.getDataFrame()
        
        if row < len(df):
            # 獲取對應的 RecommendationDTO
            stock_code = df.iloc[row].get('證券代號', '')
            recommendation = None
            if self.current_recommendations:
                for rec in self.current_recommendations:
                    if str(rec.stock_code) == str(stock_code):
                        recommendation = rec
                        break
            
            html_content = ""
            
            # Explain 面板 v1：分數拆解（Phase 3.3）
            if recommendation:
                explain_panel = self._generate_explain_panel(recommendation)
                html_content += explain_panel
                html_content += "<hr style='margin: 10px 0;'/>"
            
            # 顯示推薦理由（Why）
            reason = df.iloc[row].get('推薦理由', '')
            if reason:
                # 格式化推薦理由（使用 HTML 格式）
                formatted_reason = self._format_recommendation_reason(reason)
                html_content += formatted_reason
            else:
                html_content += "<div style='line-height: 1.6;'><p>無推薦理由</p></div>"
            
            # 顯示 Why Not（反向解釋）
            if recommendation and self.current_config:
                why_not = self._generate_why_not(recommendation, self.current_config)
                html_content += "<hr style='margin: 10px 0;'/>"
                html_content += why_not
            
            if html_content:
                self.detail_text.setHtml(html_content)
            else:
                self.detail_text.setPlainText("無詳細信息")
        else:
            self.detail_text.clear()
    
    def _generate_explain_panel(self, recommendation: RecommendationDTO) -> str:
        """生成 Explain 面板 v1：推薦分數拆解 + 風險點（Phase 3.3）
        
        Args:
            recommendation: 推薦股票 DTO
            
        Returns:
            str: Explain 面板 HTML 內容
        """
        html_text = "<div style='line-height: 1.6;'>"
        html_text += "<p style='margin: 5px 0;'><b>📊 分數拆解：</b></p>"
        html_text += "<table style='width: 100%; border-collapse: collapse; margin: 5px 0;'>"
        
        # 總分
        total_score = recommendation.total_score
        score_color = '#16a34a' if total_score >= 60 else '#f59e0b' if total_score >= 50 else '#dc2626'
        html_text += f"""
        <tr style='background-color: #2d2d2d;'>
            <td style='padding: 5px; border: 1px solid #444;'><b>總分</b></td>
            <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
                <span style='color: {score_color}; font-weight: bold; font-size: 1.1em;'>{total_score:.1f}</span>
            </td>
        </tr>
        """
        
        # 各子分數
        indicator_score = recommendation.indicator_score
        pattern_score = recommendation.pattern_score
        volume_score = recommendation.volume_score
        
        # 指標分數
        indicator_color = '#16a34a' if indicator_score >= 60 else '#f59e0b' if indicator_score >= 50 else '#dc2626'
        html_text += f"""
        <tr style='background-color: #1e1e1e;'>
            <td style='padding: 5px; border: 1px solid #444;'>📈 技術指標分數</td>
            <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
                <span style='color: {indicator_color};'>{indicator_score:.1f}</span>
            </td>
        </tr>
        """
        
        # 圖形分數
        pattern_color = '#16a34a' if pattern_score >= 60 else '#f59e0b' if pattern_score >= 50 else '#dc2626'
        html_text += f"""
        <tr style='background-color: #1e1e1e;'>
            <td style='padding: 5px; border: 1px solid #444;'>🔺 圖形模式分數</td>
            <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
                <span style='color: {pattern_color};'>{pattern_score:.1f}</span>
            </td>
        </tr>
        """
        
        # 成交量分數
        volume_color = '#16a34a' if volume_score >= 60 else '#f59e0b' if volume_score >= 50 else '#dc2626'
        html_text += f"""
        <tr style='background-color: #1e1e1e;'>
            <td style='padding: 5px; border: 1px solid #444;'>📊 成交量分數</td>
            <td style='padding: 5px; border: 1px solid #444; text-align: right;'>
                <span style='color: {volume_color};'>{volume_score:.1f}</span>
            </td>
        </tr>
        """
        
        html_text += "</table>"
        
        # 風險點提示
        html_text += "<p style='margin: 10px 0 5px 0;'><b>⚠️ 風險點：</b></p>"
        html_text += "<ul style='margin: 5px 0; padding-left: 20px;'>"
        
        risk_points = []
        
        # 檢查各項分數是否偏低
        if indicator_score < 50:
            risk_points.append(f"技術指標分數偏低（{indicator_score:.1f}），可能缺乏技術面支撐")
        if pattern_score < 40:
            risk_points.append(f"圖形模式分數偏低（{pattern_score:.1f}），圖形尚未完全形成")
        if volume_score < 50:
            risk_points.append(f"成交量分數偏低（{volume_score:.1f}），可能缺乏資金關注")
        
        # 檢查總分
        if total_score < 50:
            risk_points.append(f"總分偏低（{total_score:.1f}），綜合評分不足，建議謹慎")
        elif total_score < 60:
            risk_points.append(f"總分中等（{total_score:.1f}），建議觀察後續表現")
        
        # 檢查 Regime 匹配
        if not recommendation.regime_match:
            risk_points.append("市場狀態不匹配，策略可能不適用當前市場環境")
        
        # 檢查價格變化
        if recommendation.price_change < 0:
            risk_points.append(f"價格下跌（{recommendation.price_change:.1f}%），需注意趨勢反轉風險")
        elif recommendation.price_change > 10:
            risk_points.append(f"價格漲幅較大（{recommendation.price_change:.1f}%），需注意追高風險")
        
        if not risk_points:
            risk_points.append("✓ 各項指標表現良好，風險較低")
        
        for risk in risk_points:
            html_text += f"<li style='margin: 3px 0; color: #e0e0e0;'>{risk}</li>"
        
        html_text += "</ul>"
        html_text += "</div>"
        
        return html_text
    
    def closeEvent(self, event):
        """關閉事件"""
        # 取消正在運行的 Worker
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        event.accept()

