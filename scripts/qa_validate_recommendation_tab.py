"""
Recommendation Analysis Tab QA 驗證腳本
自動檢查與測試推薦分析功能是否正確、穩定、可回歸
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from decimal import Decimal

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

import traceback
import logging
from typing import List, Dict, Any, Optional

# 添加專案根目錄到路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from app_module.recommendation_service import RecommendationService
from app_module.regime_service import RegimeService
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
# from ui_app.industry_mapper import IndustryMapper
# from ui_app.strategy_configurator import StrategyConfigurator
from decision_module.industry_mapper import IndustryMapper
from decision_module.strategy_configurator import StrategyConfigurator

# 確保策略已註冊
import app_module.strategies  # 這會觸發策略註冊

# 設置日誌
log_dir = project_root / 'output' / 'qa' / 'recommendation_tab'
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,  # ✅ 改為 DEBUG 以查看詳細過程
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'RUN_LOG.txt', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 測試配置
TEST_STOCKS = {
    'large_cap': '2330',  # 台積電（大型股）
    'mid_cap': '2317',    # 鴻海（中型股）
    'volatile': '2454',   # 聯發科（波動較大）
}

# 預期欄位（從 RecommendationDTO.to_dict() 和 UI 使用）
EXPECTED_DTO_FIELDS = {
    '證券代號': str,
    '證券名稱': str,
    '收盤價': (float, Decimal),
    '漲幅%': (float, Decimal),
    '總分': (float, Decimal),
    '指標分': (float, Decimal),
    '圖形分': (float, Decimal),
    '成交量分': (float, Decimal),
    '推薦理由': str,
    '產業': str,
    'Regime匹配': str,
}

# 分數範圍
SCORE_RANGE = {
    'total_score': (0, 100),
    'indicator_score': (0, 100),
    'pattern_score': (0, 100),
    'volume_score': (0, 100),
}

# NaN 容忍度
MAX_NAN_RATIO = 0.1  # 最多 10% 的欄位可以是 NaN


class ValidationResult:
    """驗證結果記錄"""
    def __init__(self):
        self.passed = []
        self.failed = []
        self.skipped = []
        self.evidence = {}
        self.issues = {
            'logic_errors': [],
            'contract_violations': [],
            'data_quality': [],
            'ui_service_mismatch': [],
        }
    
    def add_pass(self, feature, evidence=None):
        self.passed.append(feature)
        if evidence:
            self.evidence[feature] = evidence
    
    def add_fail(self, feature, error, evidence=None, issue_type='logic_errors'):
        self.failed.append({
            'feature': feature,
            'error': error,
            'evidence': evidence,
            'issue_type': issue_type
        })
        if issue_type in self.issues:
            self.issues[issue_type].append({
                'feature': feature,
                'error': error,
                'evidence': evidence
            })
    
    def add_skip(self, feature, reason):
        self.skipped.append({
            'feature': feature,
            'reason': reason
        })


def validate_dto_structure(dto: RecommendationDTO, result: ValidationResult) -> bool:
    """驗證 DTO 結構"""
    try:
        # 檢查必要欄位
        required_fields = ['stock_code', 'stock_name', 'close_price', 'price_change',
                          'total_score', 'indicator_score', 'pattern_score', 'volume_score',
                          'recommendation_reasons', 'industry', 'regime_match']
        
        missing_fields = []
        for field in required_fields:
            if not hasattr(dto, field):
                missing_fields.append(field)
        
        if missing_fields:
            result.add_fail(
                'DTO_Structure',
                f"DTO 缺少必要欄位: {missing_fields}",
                issue_type='contract_violations'
            )
            return False
        
        # 檢查 to_dict() 輸出
        dto_dict = dto.to_dict()
        for expected_field, expected_type in EXPECTED_DTO_FIELDS.items():
            if expected_field not in dto_dict:
                result.add_fail(
                    'DTO_to_dict',
                    f"to_dict() 缺少欄位: {expected_field}",
                    evidence={'available_fields': list(dto_dict.keys())},
                    issue_type='contract_violations'
                )
                return False
            
            # 檢查類型（允許 None）
            if dto_dict[expected_field] is not None:
                actual_type = type(dto_dict[expected_field])
                if not isinstance(dto_dict[expected_field], expected_type):
                    result.add_fail(
                        'DTO_Type',
                        f"欄位 {expected_field} 類型錯誤: 期望 {expected_type}, 實際 {actual_type}",
                        evidence={'value': dto_dict[expected_field]},
                        issue_type='contract_violations'
                    )
                    return False
        
        return True
        
    except Exception as e:
        result.add_fail('DTO_Structure', str(e), traceback.format_exc())
        return False


def validate_score_ranges(dto: RecommendationDTO, result: ValidationResult) -> bool:
    """驗證分數範圍"""
    try:
        issues = []
        
        # 檢查總分
        if not (SCORE_RANGE['total_score'][0] <= dto.total_score <= SCORE_RANGE['total_score'][1]):
            issues.append(f"總分超出範圍: {dto.total_score} (應在 {SCORE_RANGE['total_score']})")
        
        # 檢查指標分
        if not (SCORE_RANGE['indicator_score'][0] <= dto.indicator_score <= SCORE_RANGE['indicator_score'][1]):
            issues.append(f"指標分超出範圍: {dto.indicator_score} (應在 {SCORE_RANGE['indicator_score']})")
        
        # 檢查圖形分
        if not (SCORE_RANGE['pattern_score'][0] <= dto.pattern_score <= SCORE_RANGE['pattern_score'][1]):
            issues.append(f"圖形分超出範圍: {dto.pattern_score} (應在 {SCORE_RANGE['pattern_score']})")
        
        # 檢查成交量分
        if not (SCORE_RANGE['volume_score'][0] <= dto.volume_score <= SCORE_RANGE['volume_score'][1]):
            issues.append(f"成交量分超出範圍: {dto.volume_score} (應在 {SCORE_RANGE['volume_score']})")
        
        if issues:
            result.add_fail(
                'Score_Range',
                "; ".join(issues),
                evidence={'dto': dto.__dict__},
                issue_type='data_quality'
            )
            return False
        
        return True
        
    except Exception as e:
        result.add_fail('Score_Range', str(e), traceback.format_exc())
        return False


def validate_dataframe_quality(df: pd.DataFrame, result: ValidationResult, test_name: str) -> bool:
    """驗證 DataFrame 品質"""
    try:
        issues = []
        
        # 檢查 DataFrame 是否為空
        if len(df) == 0:
            result.add_fail(
                f'{test_name}_EmptyDataFrame',
                "DataFrame 為空",
                issue_type='data_quality'
            )
            return False
        
        # 檢查必要欄位
        required_columns = list(EXPECTED_DTO_FIELDS.keys())
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            result.add_fail(
                f'{test_name}_MissingColumns',
                f"缺少必要欄位: {missing_columns}",
                evidence={'available_columns': list(df.columns)},
                issue_type='contract_violations'
            )
            return False
        
        # 檢查 NaN 比例
        optional_columns = ['score_percentile_bp', 'eligible_universe_size', 'eligible_universe_date', 'ranking_method', 'threshold_mode']
        for col in df.columns:
            if col in optional_columns: continue
            nan_count = df[col].isna().sum()
            nan_ratio = nan_count / len(df)
            if nan_ratio > MAX_NAN_RATIO:
                issues.append(f"欄位 {col} NaN 比例過高: {nan_ratio:.2%} (>{MAX_NAN_RATIO:.2%})")
        
        # 檢查分數欄位的 NaN
        score_columns = ['總分', '指標分', '圖形分', '成交量分']
        for col in score_columns:
            if col in df.columns:
                nan_count = df[col].isna().sum()
                if nan_count > 0:
                    issues.append(f"分數欄位 {col} 有 {nan_count} 個 NaN")
        
        # 檢查排序（總分應該降序）
        if '總分' in df.columns:
            if not df['總分'].is_monotonic_decreasing:
                # 允許前幾個相同分數
                sorted_df = df.sort_values('總分', ascending=False)
                if not df['總分'].equals(sorted_df['總分']):
                    issues.append("總分未按降序排列")
        
        if issues:
            result.add_fail(
                f'{test_name}_DataQuality',
                "; ".join(issues),
                evidence={'shape': df.shape, 'columns': list(df.columns)},
                issue_type='data_quality'
            )
            return False
        
        return True
        
    except Exception as e:
        result.add_fail(f'{test_name}_DataQuality', str(e), traceback.format_exc())
        return False


def validate_service_layer(config, result: ValidationResult):
    """驗證 Service 層（不啟動 UI）"""
    logger.info("=" * 80)
    logger.info("驗證 Service 層")
    logger.info("=" * 80)
    
    try:
        industry_mapper = IndustryMapper(config)
        recommendation_service = RecommendationService(config, industry_mapper)
        regime_service = RegimeService(config)
        
        # 獲取當前 Regime
        regime_result = regime_service.detect_regime()
        current_regime = regime_result.regime
        logger.info(f"當前市場狀態: {current_regime} (信心度: {regime_result.confidence:.2%})")
        
        # 測試配置（放寬篩選條件以確保有結果）
        test_configs = [
            {
                'name': '基本配置（放寬篩選）',
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
                            'bollinger': {'enabled': False},
                            'atr': {'enabled': True, 'period': 14}
                        },
                        'trend': {
                            'enabled': True,
                            'adx': {'enabled': True, 'period': 14},
                            'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                        }
                    },
                    'patterns': {
                        'selected': ['W底']
                    },
                    'signals': {
                        'technical_indicators': ['momentum', 'trend'],
                        'volume_conditions': ['increasing'],
                        'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
                    },
                    'filters': {
                        'price_change_min': -10.0,  # 允許負報酬
                        'price_change_max': 100.0,
                        'volume_ratio_min': 0.5,  # 降低成交量要求
                        'industry': '全部'
                    },
                    'regime': current_regime
                }
            },
            {
                'name': '僅移動平均線',
                'config': {
                    'technical': {
                        'momentum': {
                            'enabled': False,
                            'rsi': {'enabled': False},
                            'macd': {'enabled': False},
                            'kd': {'enabled': False}
                        },
                        'volatility': {
                            'enabled': False,
                            'bollinger': {'enabled': False},
                            'atr': {'enabled': True, 'period': 14}
                        },
                        'trend': {
                            'enabled': True,
                            'adx': {'enabled': False},
                            'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                        }
                    },
                    'patterns': {
                        'selected': ['W底']
                    },
                    'signals': {
                        'technical_indicators': ['trend'],
                        'volume_conditions': ['increasing'],
                        'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
                    },
                    'filters': {
                        'price_change_min': -10.0,
                        'price_change_max': 100.0,
                        'volume_ratio_min': 0.5,
                        'industry': '全部'
                    },
                    'regime': current_regime
                }
            },
            {
                'name': '產業篩選（半導體業）',
                'config': {
                    'technical': {
                        'momentum': {
                            'enabled': True,
                            'rsi': {'enabled': True, 'period': 14},
                            'macd': {'enabled': False},
                            'kd': {'enabled': False}
                        },
                        'volatility': {
                            'enabled': False,
                            'bollinger': {'enabled': False},
                            'atr': {'enabled': True, 'period': 14}
                        },
                        'trend': {
                            'enabled': True,
                            'adx': {'enabled': False},
                            'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                        }
                    },
                    'patterns': {
                        'selected': ['W底']
                    },
                    'signals': {
                        'technical_indicators': ['momentum', 'trend'],
                        'volume_conditions': ['increasing'],
                        'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
                    },
                    'filters': {
                        'price_change_min': -10.0,
                        'price_change_max': 100.0,
                        'volume_ratio_min': 0.5,
                        'industry': '半導體業'
                    },
                    'regime': current_regime
                }
            }
        ]
        
        for test_case in test_configs:
            test_name = test_case['name']
            test_config = test_case['config']
            
            logger.info(f"\n[Service Test] {test_name}")
            logger.info(f"  配置: {json.dumps(test_config, indent=2, ensure_ascii=False)}")
            
            try:
                # 執行推薦分析
                recommendations = recommendation_service.run_recommendation(
                    config=test_config,
                    max_stocks=50,
                    top_n=10
                )
                
                logger.info(f"  返回 {len(recommendations)} 個推薦")
                
                # 驗證返回類型
                if not isinstance(recommendations, list):
                    result.add_fail(
                        f'{test_name}_ReturnType',
                        f"返回類型錯誤: {type(recommendations)}, 期望 list",
                        issue_type='contract_violations'
                    )
                    continue
                
                # 如果沒有結果，記錄但不一定失敗（可能是篩選條件太嚴格）
                if len(recommendations) == 0:
                    logger.warning(f"  ⚠️ 沒有找到推薦（可能是篩選條件太嚴格）")
                    result.add_skip(
                        f'{test_name}_NoResults',
                        "沒有找到推薦結果（可能是篩選條件太嚴格或數據問題）"
                    )
                    continue
                
                # 驗證每個 DTO
                for idx, rec in enumerate(recommendations):
                    if not isinstance(rec, RecommendationDTO):
                        result.add_fail(
                            f'{test_name}_DTOType',
                            f"第 {idx} 個元素類型錯誤: {type(rec)}, 期望 RecommendationDTO",
                            issue_type='contract_violations'
                        )
                        break
                    
                    # 驗證 DTO 結構
                    if not validate_dto_structure(rec, result):
                        break
                    
                    # 驗證分數範圍
                    if not validate_score_ranges(rec, result):
                        break
                
                # 轉換為 DataFrame 並驗證
                if len(recommendations) > 0:
                    data = [rec.to_dict() for rec in recommendations]
                    df = pd.DataFrame(data)
                    
                    # 保存證據
                    evidence_file = log_dir / f'{test_name.replace(" ", "_")}_results.csv'
                    df.to_csv(evidence_file, index=False, encoding='utf-8-sig')
                    
                    # 驗證 DataFrame 品質
                    if validate_dataframe_quality(df, result, test_name):
                        result.add_pass(f'{test_name}_Service', {
                            'file': str(evidence_file),
                            'count': len(recommendations),
                            'columns': list(df.columns),
                            'shape': df.shape
                        })
                    
                    # 記錄統計信息
                    logger.info(f"  DataFrame shape: {df.shape}")
                    logger.info(f"  DataFrame columns: {list(df.columns)}")
                    if '總分' in df.columns:
                        logger.info(f"  總分範圍: {df['總分'].min():.2f} ~ {df['總分'].max():.2f}")
                        logger.info(f"  總分平均: {df['總分'].mean():.2f}")
                    
            except Exception as e:
                result.add_fail(
                    f'{test_name}_Exception',
                    str(e),
                    traceback.format_exc(),
                    issue_type='logic_errors'
                )
        
    except Exception as e:
        logger.error(f"Service 層驗證失敗: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('Service_Layer_Setup', str(e), traceback.format_exc())


def validate_ui_service_contract(result: ValidationResult):
    """驗證 UI 與 Service 的 Contract"""
    logger.info("=" * 80)
    logger.info("驗證 UI ↔ Service Contract")
    logger.info("=" * 80)
    
    try:
        # 讀取 UI 代碼，檢查使用的欄位
        ui_file = project_root / 'ui_qt' / 'views' / 'recommendation_view.py'
        if not ui_file.exists():
            result.add_skip('UI_Contract_Check', "找不到 UI 文件")
            return
        
        ui_code = ui_file.read_text(encoding='utf-8')
        
        # 檢查 UI 中使用的欄位（從 to_dict() 轉換後的欄位名）
        # UI 使用 rec.to_dict() 轉換為 DataFrame，所以應該使用 DTO.to_dict() 的欄位名
        ui_used_fields = []
        
        # 檢查是否有直接訪問 DTO 屬性的地方
        # 實際上 UI 使用 to_dict()，所以應該檢查 to_dict() 的輸出欄位
        
        # 驗證所有 EXPECTED_DTO_FIELDS 都存在於 DTO.to_dict() 中
        from app_module.dtos import RecommendationDTO
        
        # 創建一個測試 DTO 來檢查 to_dict() 輸出
        test_dto = RecommendationDTO(
            stock_code='TEST',
            stock_name='測試',
            close_price=100.0,
            price_change=1.0,
            total_score=50.0,
            indicator_score=50.0,
            pattern_score=50.0,
            volume_score=50.0,
            recommendation_reasons='測試理由',
            industry='測試產業',
            regime_match=True
        )
        
        test_dict = test_dto.to_dict()
        
        # 檢查所有預期欄位都存在
        missing_in_dto = []
        for field in EXPECTED_DTO_FIELDS.keys():
            if field not in test_dict:
                missing_in_dto.append(field)
        
        if missing_in_dto:
            result.add_fail(
                'UI_Contract_DTO_MissingFields',
                f"DTO.to_dict() 缺少 UI 需要的欄位: {missing_in_dto}",
                evidence={'dto_fields': list(test_dict.keys())},
                issue_type='contract_violations'
            )
        else:
            result.add_pass('UI_Contract_DTO', {
                'dto_fields': list(test_dict.keys()),
                'expected_fields': list(EXPECTED_DTO_FIELDS.keys())
            })
        
        # 檢查 UI 預設配置與 Service 預設配置的一致性
        # 這需要手動檢查，因為 UI 和 Service 的預設配置可能不同
        
    except Exception as e:
        logger.error(f"UI Contract 驗證失敗: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('UI_Contract_Check', str(e), traceback.format_exc())


def validate_filtering_logic(config, result: ValidationResult):
    """驗證篩選邏輯"""
    logger.info("=" * 80)
    logger.info("驗證篩選邏輯")
    logger.info("=" * 80)
    
    try:
        industry_mapper = IndustryMapper(config)
        recommendation_service = RecommendationService(config, industry_mapper)
        regime_service = RegimeService(config)
        
        regime_result = regime_service.detect_regime()
        current_regime = regime_result.regime
        
        # 測試不同的篩選條件
        filter_tests = [
            {
                'name': '無篩選條件',
                'filters': {
                    'price_change_min': -100.0,  # 極寬鬆
                    'price_change_max': 100.0,
                    'volume_ratio_min': 0.0,  # 極寬鬆
                    'industry': '全部'
                }
            },
            {
                'name': '嚴格漲幅篩選',
                'filters': {
                    'price_change_min': 5.0,  # 要求漲幅 >= 5%
                    'price_change_max': 100.0,
                    'volume_ratio_min': 0.0,
                    'industry': '全部'
                }
            },
            {
                'name': '嚴格成交量篩選',
                'filters': {
                    'price_change_min': -100.0,
                    'price_change_max': 100.0,
                    'volume_ratio_min': 2.0,  # 要求成交量 >= 200%
                    'industry': '全部'
                }
            }
        ]
        
        base_config = {
            'technical': {
                'momentum': {
                    'enabled': True,
                    'rsi': {'enabled': True, 'period': 14},
                    'macd': {'enabled': False},
                    'kd': {'enabled': False}
                },
                'volatility': {
                    'enabled': False,
                    'bollinger': {'enabled': False},
                    'atr': {'enabled': True, 'period': 14}
                },
                'trend': {
                    'enabled': True,
                    'adx': {'enabled': False},
                    'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                }
            },
            'patterns': {
                'selected': ['W底']
            },
            'signals': {
                'technical_indicators': ['momentum', 'trend'],
                'volume_conditions': ['increasing'],
                'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
            },
            'regime': current_regime
        }
        
        for filter_test in filter_tests:
            test_name = filter_test['name']
            filters = filter_test['filters']
            
            logger.info(f"\n[Filter Test] {test_name}")
            logger.info(f"  篩選條件: {filters}")
            
            try:
                test_config = {**base_config, 'filters': filters}
                
                recommendations = recommendation_service.run_recommendation(
                    config=test_config,
                    max_stocks=50,
                    top_n=10
                )
                
                logger.info(f"  返回 {len(recommendations)} 個推薦")
                
                # 驗證篩選是否生效
                if len(recommendations) > 0:
                    df = pd.DataFrame([rec.to_dict() for rec in recommendations])
                    
                    # 檢查漲幅篩選
                    if filters.get('price_change_min', -100) > -100:
                        if '漲幅%' in df.columns:
                            min_price_change = df['漲幅%'].min()
                            if min_price_change < filters['price_change_min']:
                                result.add_fail(
                                    f'{test_name}_PriceFilter',
                                    f"漲幅篩選未生效: 最小漲幅 {min_price_change:.2f}% < 要求 {filters['price_change_min']:.2f}%",
                                    evidence={'df_min': min_price_change, 'filter_min': filters['price_change_min']},
                                    issue_type='logic_errors'
                                )
                            else:
                                result.add_pass(f'{test_name}_PriceFilter', {
                                    'min_price_change': min_price_change,
                                    'filter_min': filters['price_change_min']
                                })
                    
                    # 檢查成交量篩選
                    if filters.get('volume_ratio_min', 0) > 0:
                        # volume_ratio_min 需要轉換為百分比變化
                        volume_ratio_min_pct = (filters['volume_ratio_min'] - 1) * 100
                        if '成交量變化率%' in df.columns:
                            min_volume_change = df['成交量變化率%'].min()
                            if min_volume_change < volume_ratio_min_pct:
                                result.add_fail(
                                    f'{test_name}_VolumeFilter',
                                    f"成交量篩選未生效: 最小變化率 {min_volume_change:.2f}% < 要求 {volume_ratio_min_pct:.2f}%",
                                    evidence={'df_min': min_volume_change, 'filter_min': volume_ratio_min_pct},
                                    issue_type='logic_errors'
                                )
                            else:
                                result.add_pass(f'{test_name}_VolumeFilter', {
                                    'min_volume_change': min_volume_change,
                                    'filter_min': volume_ratio_min_pct
                                })
                
            except Exception as e:
                result.add_fail(
                    f'{test_name}_Exception',
                    str(e),
                    traceback.format_exc(),
                    issue_type='logic_errors'
                )
        
    except Exception as e:
        logger.error(f"篩選邏輯驗證失敗: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('Filter_Logic_Setup', str(e), traceback.format_exc())


def generate_report(result: ValidationResult) -> str:
    """生成 Markdown 報告"""
    report_lines = [
        "# Recommendation Analysis Tab 驗證報告",
        "",
        f"**生成時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 📊 測試摘要",
        "",
        f"- ✅ **通過**: {len(result.passed)} 項",
        f"- ❌ **失敗**: {len(result.failed)} 項",
        f"- ⏭️ **跳過**: {len(result.skipped)} 項",
        "",
        "## ✅ 通過項目",
        ""
    ]
    
    if result.passed:
        for feature in result.passed:
            report_lines.append(f"- {feature}")
            if feature in result.evidence:
                evidence = result.evidence[feature]
                if isinstance(evidence, dict):
                    report_lines.append(f"  - 證據: {json.dumps(evidence, ensure_ascii=False, indent=2, cls=DecimalEncoder)}")
    else:
        report_lines.append("無")
    
    report_lines.extend([
        "",
        "## ❌ 失敗項目",
        ""
    ])
    
    if result.failed:
        for fail in result.failed:
            report_lines.append(f"### {fail['feature']}")
            report_lines.append(f"**錯誤**: {fail['error']}")
            report_lines.append(f"**問題類型**: {fail.get('issue_type', 'unknown')}")
            if fail.get('evidence'):
                report_lines.append(f"**證據**:")
                report_lines.append(f"```json")
                report_lines.append(json.dumps(fail['evidence'], ensure_ascii=False, indent=2, cls=DecimalEncoder))
                report_lines.append(f"```")
            report_lines.append("")
    else:
        report_lines.append("無")
    
    report_lines.extend([
        "",
        "## ⏭️ 跳過項目",
        ""
    ])
    
    if result.skipped:
        for skip in result.skipped:
            report_lines.append(f"- **{skip['feature']}**: {skip['reason']}")
    else:
        report_lines.append("無")
    
    report_lines.extend([
        "",
        "## 🔍 問題分類",
        ""
    ])
    
    for issue_type, issues in result.issues.items():
        if issues:
            report_lines.append(f"### {issue_type}")
            for issue in issues:
                report_lines.append(f"- **{issue['feature']}**: {issue['error']}")
            report_lines.append("")
    
    report_lines.extend([
        "",
        "## 🚨 阻擋 Release 的問題",
        ""
    ])
    
    blockers = []
    for fail in result.failed:
        issue_type = fail.get('issue_type', 'unknown')
        if issue_type in ['contract_violations', 'logic_errors']:
            blockers.append(fail)
    
    if blockers:
        for blocker in blockers:
            report_lines.append(f"- **{blocker['feature']}**: {blocker['error']}")
    else:
        report_lines.append("無阻擋問題")
    
    report_lines.extend([
        "",
        "## 📝 建議",
        "",
        "### 可全自動驗證（✅ QA script 可 cover）",
        "- Service 層測試",
        "- DTO 結構驗證",
        "- 分數範圍驗證",
        "- DataFrame 品質驗證",
        "- 篩選邏輯驗證",
        "",
        "### 需啟動 Qt 但可自動化（⚠️ pytest-qt / QTest）",
        "- UI 組件初始化",
        "- 信號/槽連接",
        "- 表格模型設置",
        "",
        "### 必須人工檢查（👀 純視覺/UX）",
        "- UI 布局",
        "- 按鈕樣式",
        "- 進度條動畫",
        "- 錯誤訊息顯示",
        ""
    ])
    
    return "\n".join(report_lines)


def main():
    """主函數"""
    logger.info("=" * 80)
    logger.info("Recommendation Analysis Tab QA 驗證")
    logger.info("=" * 80)
    
    result = ValidationResult()
    
    try:
        # 初始化配置
        config = TWStockConfig()
        
        # 驗證 Service 層
        validate_service_layer(config, result)
        
        # 驗證 UI ↔ Service Contract
        validate_ui_service_contract(result)
        
        # 驗證篩選邏輯
        validate_filtering_logic(config, result)
        
    except Exception as e:
        logger.error(f"驗證過程發生錯誤: {e}")
        logger.error(traceback.format_exc())
        result.add_fail('Main_Exception', str(e), traceback.format_exc())
    
    # 生成報告
    report = generate_report(result)
    report_file = log_dir / 'VALIDATION_REPORT.md'
    report_file.write_text(report, encoding='utf-8')
    logger.info(f"\n報告已保存至: {report_file}")
    
    # 控制台摘要（使用 logging 避免編碼問題）
    logger.info("\n" + "=" * 80)
    logger.info("驗證摘要")
    logger.info("=" * 80)
    logger.info(f"通過: {len(result.passed)}")
    logger.info(f"失敗: {len(result.failed)}")
    logger.info(f"跳過: {len(result.skipped)}")
    logger.info(f"\n詳細報告: {report_file}")
    
    # 返回退出碼
    if result.failed:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

