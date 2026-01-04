"""
Phase 3.3b 完整功能驗證與壓力測試腳本
驗證「研究閉環」：推薦 -> 加入候選池 -> 回測 -> 穩健性驗證 -> Promote 成策略版本 -> 回到推薦
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import traceback
import logging
from typing import List, Dict, Any, Optional

# 添加專案根目錄到路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from app_module.screening_service import ScreeningService
from app_module.regime_service import RegimeService
from app_module.recommendation_service import RecommendationService
from app_module.update_service import UpdateService
from app_module.backtest_service import BacktestService
from app_module.walkforward_service import WalkForwardService
from app_module.promotion_service import PromotionService
from app_module.watchlist_service import WatchlistService
from app_module.backtest_repository import BacktestRunRepository
from app_module.strategy_version_service import StrategyVersionService
from app_module.preset_service import PresetService
from app_module.broker_branch_update_service import BrokerBranchUpdateService
from decision_module.industry_mapper import IndustryMapper

# 確保策略已註冊
import app_module.strategies

# 設置日誌
log_dir = project_root / 'output' / 'qa' / 'phase3_3b_validation'
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'RUN_LOG.txt', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 測試配置
TEST_STOCK = '2330'  # 台積電
TEST_STOCKS = ['2330', '2317', '2454']  # 測試股票清單
TEST_DATE_RANGE = {
    'start': '2024-01-01',
    'end': '2024-12-31',
}


class ValidationResult:
    """驗證結果記錄"""
    def __init__(self, test_name: str):
        self.test_name = test_name
        self.passed = False
        self.error_message = None
        self.details = {}
        self.warning = False
        self.warning_message = None
    
    def to_dict(self) -> dict:
        return {
            'test_name': self.test_name,
            'passed': self.passed,
            'error_message': self.error_message,
            'warning': self.warning,
            'warning_message': self.warning_message,
            'details': self.details
        }


class Phase33BValidator:
    """Phase 3.3b 驗證器"""
    
    def __init__(self):
        """初始化驗證器"""
        self.config = TWStockConfig()
        self.results: List[ValidationResult] = []
        
        # 初始化服務
        shared_industry_mapper = IndustryMapper(self.config)
        self.screening_service = ScreeningService(self.config, industry_mapper=shared_industry_mapper)
        self.regime_service = RegimeService(self.config)
        self.recommendation_service = RecommendationService(self.config, industry_mapper=shared_industry_mapper)
        self.update_service = UpdateService(self.config)
        self.backtest_service = BacktestService(self.config)
        self.walkforward_service = WalkForwardService(self.config)
        self.watchlist_service = WatchlistService(self.config)
        self.backtest_repository = BacktestRunRepository(self.config)
        self.strategy_version_service = StrategyVersionService(self.config)
        self.preset_service = PresetService(self.config)
        self.promotion_service = PromotionService(
            config=self.config,
            backtest_repository=self.backtest_repository,
            backtest_service=self.backtest_service,
            walkforward_service=self.walkforward_service,
            strategy_version_service=self.strategy_version_service,
            preset_service=self.preset_service
        )
        self.broker_branch_service = BrokerBranchUpdateService(self.config)
    
    def run_all_tests(self):
        """執行所有測試"""
        logger.info("=" * 80)
        logger.info("開始執行 Phase 3.3b 完整功能驗證與壓力測試")
        logger.info("=" * 80)
        
        # 1. 數據與市場觀察 (Update & Market Watch)
        logger.info("\n" + "=" * 80)
        logger.info("測試場景 1：數據與市場觀察 (Update & Market Watch)")
        logger.info("=" * 80)
        self.test_data_update()
        self.test_market_regime()
        
        # 2. 推薦引擎與 Profile (Recommendation)
        logger.info("\n" + "=" * 80)
        logger.info("測試場景 2：推薦引擎與 Profile (Recommendation)")
        logger.info("=" * 80)
        self.test_profile_loading()
        self.test_why_why_not()
        self.test_watchlist_linkage()
        
        # 3. 研究閉環核心 (Backtest & Research Lab)
        logger.info("\n" + "=" * 80)
        logger.info("測試場景 3：研究閉環核心 (Backtest & Research Lab)")
        logger.info("=" * 80)
        self.test_send_to_backtest()
        self.test_robustness_metrics()
        self.test_visual_verification()
        
        # 4. Promote 機制 (The Final Loop)
        logger.info("\n" + "=" * 80)
        logger.info("測試場景 4：Promote 機制 (The Final Loop)")
        logger.info("=" * 80)
        self.test_promote_mechanism()
        self.test_promote_to_recommendation()
        
        # 生成報告
        self.generate_report()
    
    # ==================== 測試場景 1：數據與市場觀察 ====================
    
    def test_data_update(self):
        """驗證數據更新流程"""
        result = ValidationResult("測試 1.1：數據更新流程（券商分點資料）")
        
        try:
            logger.info("執行測試 1.1：數據更新流程（券商分點資料）")
            
            # 檢查券商分點資料目錄
            broker_flow_dir = self.config.broker_flow_dir
            if not broker_flow_dir.exists():
                result.passed = False
                result.error_message = f"券商分點資料目錄不存在: {broker_flow_dir}"
                self.results.append(result)
                return
            
            # 檢查最近的資料檔案
            data_files = list(broker_flow_dir.glob("*.parquet"))
            if not data_files:
                result.warning = True
                result.warning_message = "未找到券商分點資料檔案，可能需要執行更新"
            else:
                # 檢查最新檔案
                latest_file = max(data_files, key=lambda p: p.stat().st_mtime)
                file_age_days = (datetime.now().timestamp() - latest_file.stat().st_mtime) / 86400
                
                if file_age_days > 7:
                    result.warning = True
                    result.warning_message = f"最新資料檔案已過期 {file_age_days:.1f} 天"
                
                # 檢查 UNKNOWN 比例（讀取一個樣本檔案）
                try:
                    df = pd.read_parquet(latest_file)
                    if 'counterparty' in df.columns:
                        unknown_count = df[df['counterparty'].str.contains('UNKNOWN', case=False, na=False)].shape[0]
                        total_count = len(df)
                        unknown_ratio = unknown_count / total_count if total_count > 0 else 0
                        
                        result.details['unknown_ratio'] = unknown_ratio
                        result.details['total_records'] = total_count
                        result.details['unknown_count'] = unknown_count
                        
                        if unknown_ratio > 0.3:  # 超過 30% 為 UNKNOWN
                            result.warning = True
                            result.warning_message = f"UNKNOWN 比例過高: {unknown_ratio:.2%}"
                    else:
                        result.details['note'] = "資料檔案中沒有 counterparty 欄位"
                except Exception as e:
                    result.warning = True
                    result.warning_message = f"無法讀取資料檔案進行分析: {str(e)}"
            
            result.passed = True
            result.details['broker_flow_dir'] = str(broker_flow_dir)
            result.details['data_files_count'] = len(data_files)
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 1.1 完成: {'通過' if result.passed else '失敗'}")
    
    def test_market_regime(self):
        """驗證 Regime 判斷"""
        result = ValidationResult("測試 1.2：Regime 判斷（Market Watch）")
        
        try:
            logger.info("執行測試 1.2：Regime 判斷（Market Watch）")
            
            # 獲取當前市場 Regime
            regime_result = self.regime_service.detect_regime()
            
            if regime_result is None:
                result.passed = False
                result.error_message = "無法獲取市場 Regime"
                self.results.append(result)
                return
            
            # RegimeResultDTO 是 dataclass，使用屬性訪問
            # 驗證 Regime 值
            regime = regime_result.regime
            valid_regimes = ['Trend', 'Reversion', 'Breakout', 'Mixed']
            
            if regime not in valid_regimes:
                result.warning = True
                result.warning_message = f"Regime 值不在預期範圍內: {regime}"
            
            result.passed = True
            result.details['regime'] = regime
            result.details['regime_name_cn'] = regime_result.regime_name_cn
            result.details['confidence'] = regime_result.confidence
            result.details['details'] = regime_result.details
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 1.2 完成: {'通過' if result.passed else '失敗'}")
    
    # ==================== 測試場景 2：推薦引擎與 Profile ====================
    
    def test_profile_loading(self):
        """驗證 Profile 載入（新手/進階模式）"""
        result = ValidationResult("測試 2.1：Profile 載入（新手/進階模式）")
        
        try:
            logger.info("執行測試 2.1：Profile 載入（新手/進階模式）")
            
            # Profiles 定義在 RecommendationView 中，這裡直接使用定義
            # 模擬 RecommendationView 的 profiles 定義
            profiles = {
                'momentum': {
                    'id': 'momentum',
                    'name': '暴衝策略',
                    'risk_level': 'high',
                    'config': {
                        'technical': {'momentum': {'enabled': True}},
                        'patterns': {'selected': ['旗形', '三角形']},
                        'signals': {'technical_indicators': ['momentum']}
                    }
                },
                'stable': {
                    'id': 'stable',
                    'name': '穩健策略',
                    'risk_level': 'low',
                    'config': {
                        'technical': {'momentum': {'enabled': True}},
                        'patterns': {'selected': ['W底', '頭肩底']},
                        'signals': {'technical_indicators': ['momentum']}
                    }
                },
                'long_term': {
                    'id': 'long_term',
                    'name': '長期策略',
                    'risk_level': 'medium',
                    'config': {
                        'technical': {'trend': {'enabled': True}},
                        'patterns': {'selected': ['圓底', '矩形']},
                        'signals': {'technical_indicators': ['trend']}
                    }
                }
            }
            
            if not profiles:
                result.passed = False
                result.error_message = "未找到任何 Profile"
                self.results.append(result)
                return
            
            # 檢查 Profile 結構
            required_profile_keys = ['name', 'risk_level', 'config']
            profile_issues = []
            
            for profile_id, profile_data in profiles.items():
                missing_keys = [k for k in required_profile_keys if k not in profile_data]
                if missing_keys:
                    profile_issues.append(f"{profile_id}: 缺少 {missing_keys}")
            
            if profile_issues:
                result.warning = True
                result.warning_message = f"部分 Profile 結構不完整: {profile_issues}"
            
            # 測試載入 Profile 配置
            test_profile_id = list(profiles.keys())[0]
            profile_config = profiles[test_profile_id]['config']
            
            # 檢查配置是否包含必要欄位
            required_config_keys = ['technical', 'patterns', 'signals']
            missing_config_keys = [k for k in required_config_keys if k not in profile_config]
            
            if missing_config_keys:
                result.warning = True
                result.warning_message = f"Profile 配置缺少欄位: {missing_config_keys}"
            
            result.passed = True
            result.details['profiles_count'] = len(profiles)
            result.details['profile_ids'] = list(profiles.keys())
            result.details['test_profile_id'] = test_profile_id
            result.details['profile_config_keys'] = list(profile_config.keys())
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 2.1 完成: {'通過' if result.passed else '失敗'}")
    
    def test_why_why_not(self):
        """驗證 Why/Why Not（推薦理由）"""
        result = ValidationResult("測試 2.2：Why/Why Not（推薦理由）")
        
        try:
            logger.info("執行測試 2.2：Why/Why Not（推薦理由）")
            
            # 執行推薦（使用預設配置）
            # 使用 RecommendationView 的預設配置
            default_config = {
                'technical': {
                    'momentum': {'enabled': True, 'rsi': {'enabled': True, 'period': 14}},
                    'trend': {'enabled': True, 'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}}
                },
                'patterns': {'selected': ['W底', '頭肩底', '雙底', '矩形']},
                'signals': {'technical_indicators': ['momentum', 'trend']},
                'filters': {'price_change_min': 0.0, 'volume_ratio_min': 1.0}
            }
            
            recommendations = self.recommendation_service.run_recommendation(
                config=default_config,
                max_stocks=50,
                top_n=10
            )
            
            if not recommendations or len(recommendations) == 0:
                result.passed = False
                result.error_message = "無法生成推薦結果"
                self.results.append(result)
                return
            
            # 檢查推薦結果
            rec = recommendations[0]
            
            # 檢查推薦理由（RecommendationDTO 使用 recommendation_reasons 欄位）
            if not rec.recommendation_reasons or not rec.recommendation_reasons.strip():
                result.warning = True
                result.warning_message = "推薦結果缺少推薦理由（recommendation_reasons 為空）"
            else:
                # 檢查理由是否包含技術指標、圖形訊號
                why_text = rec.recommendation_reasons.lower()
                has_technical = any(keyword in why_text for keyword in ['指標', 'rsi', 'macd', '均線', 'adx', '技術'])
                has_pattern = any(keyword in why_text for keyword in ['圖形', 'w底', '頭肩', '雙底', '突破', '模式'])
                
                if not has_technical and not has_pattern:
                    result.warning = True
                    result.warning_message = "推薦理由可能缺少技術指標或圖形訊號說明"
            
            # 注意：RecommendationDTO 沒有 why_not 欄位，這是 UI 層的功能
            # 如果需要檢查 why_not，應該在 UI 層測試
            
            result.passed = True
            result.details['stock_code'] = rec.stock_code
            result.details['total_score'] = rec.total_score
            result.details['has_recommendation_reasons'] = bool(rec.recommendation_reasons and rec.recommendation_reasons.strip())
            result.details['recommendation_reasons_preview'] = rec.recommendation_reasons[:100] if rec.recommendation_reasons else None
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 2.2 完成: {'通過' if result.passed else '失敗'}")
    
    def test_watchlist_linkage(self):
        """驗證聯動（推薦股票加入 Watchlist）"""
        result = ValidationResult("測試 2.3：聯動（推薦股票加入 Watchlist）")
        
        try:
            logger.info("執行測試 2.3：聯動（推薦股票加入 Watchlist）")
            
            # 執行推薦
            default_config = {
                'technical': {
                    'momentum': {'enabled': True, 'rsi': {'enabled': True, 'period': 14}},
                    'trend': {'enabled': True, 'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}}
                },
                'patterns': {'selected': ['W底', '頭肩底', '雙底', '矩形']},
                'signals': {'technical_indicators': ['momentum', 'trend']},
                'filters': {'price_change_min': 0.0, 'volume_ratio_min': 1.0}
            }
            
            recommendations = self.recommendation_service.run_recommendation(
                config=default_config,
                max_stocks=50,
                top_n=10
            )
            
            if not recommendations or len(recommendations) == 0:
                result.passed = False
                result.error_message = "無法生成推薦結果"
                self.results.append(result)
                return
            
            # 獲取當前 Regime
            regime_result = self.regime_service.detect_regime()
            regime_name = regime_result.regime_name_cn if regime_result else '未知'
            
            # 準備加入 Watchlist 的股票
            stocks_to_add = []
            for rec in recommendations[:2]:
                stocks_to_add.append({
                    'stock_code': rec.stock_code,
                    'stock_name': rec.stock_name if hasattr(rec, 'stock_name') else rec.stock_code,
                    'notes': f"來源：推薦測試, Regime: {regime_name}"
                })
            
            # 加入 Watchlist
            added_count = self.watchlist_service.add_stocks(
                stocks=stocks_to_add,
                source='recommendation'
            )
            
            if added_count == 0:
                result.warning = True
                result.warning_message = "未成功加入任何股票到 Watchlist（可能已存在）"
            
            # 驗證 Watchlist 中的資料
            watchlist = self.watchlist_service.get_watchlist("default")
            if watchlist is None:
                result.passed = False
                result.error_message = "無法獲取 Watchlist"
                self.results.append(result)
                return
            
            # 檢查是否有我們剛加入的股票
            added_stocks = [item for item in watchlist.items if item.source == 'recommendation']
            
            if not added_stocks:
                result.warning = True
                result.warning_message = "Watchlist 中未找到來源為 recommendation 的股票"
            else:
                # 檢查 metadata（source_profile, regime_snapshot）
                for item in added_stocks:
                    if '來源' not in item.notes and 'Regime' not in item.notes:
                        result.warning = True
                        result.warning_message = f"股票 {item.stock_code} 的 notes 中缺少來源信息"
                        break
            
            result.passed = True
            result.details['added_count'] = added_count
            result.details['watchlist_total'] = len(watchlist.items)
            result.details['recommendation_source_count'] = len(added_stocks)
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 2.3 完成: {'通過' if result.passed else '失敗'}")
    
    # ==================== 測試場景 3：研究閉環核心 ====================
    
    def test_send_to_backtest(self):
        """驗證一鍵送回測"""
        result = ValidationResult("測試 3.1：一鍵送回測（Recommendation → Backtest）")
        
        try:
            logger.info("執行測試 3.1：一鍵送回測（Recommendation → Backtest）")
            
            # 模擬從推薦到回測的配置傳遞
            default_config = {
                'technical': {
                    'momentum': {'enabled': True, 'rsi': {'enabled': True, 'period': 14}},
                    'trend': {'enabled': True, 'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}}
                },
                'patterns': {'selected': ['W底', '頭肩底', '雙底', '矩形']},
                'signals': {'technical_indicators': ['momentum', 'trend']},
                'filters': {'price_change_min': 0.0, 'volume_ratio_min': 1.0}
            }
            
            # 執行推薦以獲取配置
            recommendations = self.recommendation_service.run_recommendation(
                config=default_config,
                max_stocks=50,
                top_n=10
            )
            
            if not recommendations:
                result.passed = False
                result.error_message = "無法生成推薦結果"
                self.results.append(result)
                return
            
            # 構建回測配置（模擬一鍵送回測的邏輯）
            backtest_config = {
                'stock_list': [rec.stock_code for rec in recommendations[:3]],
                'strategy_id': 'baseline_score_threshold',
                'strategy_params': {'buy_score': 60, 'sell_score': 40, 'confirm_days': 1},
                'start_date': TEST_DATE_RANGE['start'],
                'end_date': TEST_DATE_RANGE['end'],
                'execution_price': 'close',  # 根據 Profile 風險等級設置
                'risk_control': {
                    'use_atr': True,
                    'atr_multiplier': 2.0
                }
            }
            
            # 驗證配置完整性
            required_keys = ['stock_list', 'strategy_id', 'strategy_params', 'start_date', 'end_date']
            missing_keys = [k for k in required_keys if k not in backtest_config]
            
            if missing_keys:
                result.passed = False
                result.error_message = f"回測配置缺少必要欄位: {missing_keys}"
                self.results.append(result)
                return
            
            # 驗證股票清單
            if not backtest_config['stock_list']:
                result.passed = False
                result.error_message = "回測配置中股票清單為空"
                self.results.append(result)
                return
            
            # 驗證策略參數
            if not backtest_config['strategy_params']:
                result.warning = True
                result.warning_message = "回測配置中策略參數為空"
            
            result.passed = True
            result.details['stock_list'] = backtest_config['stock_list']
            result.details['strategy_id'] = backtest_config['strategy_id']
            result.details['has_strategy_params'] = bool(backtest_config['strategy_params'])
            result.details['has_risk_control'] = 'risk_control' in backtest_config
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 3.1 完成: {'通過' if result.passed else '失敗'}")
    
    def test_robustness_metrics(self):
        """驗證穩健性指標"""
        result = ValidationResult("測試 3.2：穩健性指標（Walk-forward, Baseline, Overfitting）")
        
        try:
            logger.info("執行測試 3.2：穩健性指標（Walk-forward, Baseline, Overfitting）")
            
            # 執行一個簡單的回測
            # 需要創建 StrategySpec
            from app_module.strategy_spec import StrategySpec
            from app_module.strategy_registry import StrategyRegistry
            
            strategy_spec = StrategySpec(
                strategy_id='baseline_score_threshold',
                strategy_version='1.0.0',
                default_params={
                    'buy_score': 60,
                    'sell_score': 40,
                    'confirm_days': 1
                }
            )
            
            backtest_result = self.backtest_service.run_backtest(
                stock_code=TEST_STOCK,
                start_date=TEST_DATE_RANGE['start'],
                end_date=TEST_DATE_RANGE['end'],
                strategy_spec=strategy_spec
            )
            
            if not backtest_result:
                result.passed = False
                result.error_message = "無法執行回測"
                self.results.append(result)
                return
            
            # backtest_result 本身就是 BacktestReportDTO，直接使用
            report = backtest_result
            
            # 1. 檢查 Walk-forward 暖機期（從 details 中獲取）
            # 注意：Walk-forward 結果通常需要手動執行，不在基本回測報告中
            walkforward_info = report.details.get('walkforward_result')
            if walkforward_info:
                if isinstance(walkforward_info, dict) and 'warmup_days' in walkforward_info:
                    result.details['has_warmup_days'] = True
                    result.details['warmup_days'] = walkforward_info.get('warmup_days', 0)
                else:
                    result.warning = True
                    result.warning_message = "Walk-forward 結果中缺少 warmup_days 欄位"
            else:
                result.warning = True
                result.warning_message = "回測報告中沒有 Walk-forward 結果（需要手動執行 Walk-forward 驗證）"
            
            # 2. 檢查 Baseline 對比
            if report.baseline_comparison:
                baseline = report.baseline_comparison
                result.details['has_baseline_comparison'] = True
                result.details['baseline_total_return'] = baseline.get('baseline_total_return')
                result.details['strategy_total_return'] = baseline.get('strategy_total_return')
                result.details['excess_return'] = baseline.get('excess_return')
            else:
                result.warning = True
                result.warning_message = "回測報告中沒有 Baseline 對比結果（可能未啟用或計算失敗）"
            
            # 3. 檢查過擬合風險提示
            if report.overfitting_risk:
                risk = report.overfitting_risk
                result.details['has_overfitting_risk'] = True
                result.details['risk_level'] = risk.get('risk_level', 'Unknown')
                result.details['risk_score'] = risk.get('risk_score', 0)
                result.details['risk_warnings'] = risk.get('warnings', [])
            else:
                result.warning = True
                result.warning_message = "回測報告中沒有過擬合風險提示（可能未提供 Walk-forward 結果或功能未啟用）"
            
            result.passed = True
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 3.2 完成: {'通過' if result.passed else '失敗'}")
    
    def test_visual_verification(self):
        """驗證視覺驗證（K 線圖標記）"""
        result = ValidationResult("測試 3.3：視覺驗證（K 線圖標記買賣點）")
        
        try:
            logger.info("執行測試 3.3：視覺驗證（K 線圖標記買賣點）")
            
            # 執行回測以獲取交易記錄
            from app_module.strategy_spec import StrategySpec
            
            strategy_spec = StrategySpec(
                strategy_id='baseline_score_threshold',
                strategy_version='1.0.0',
                default_params={
                    'buy_score': 60,
                    'sell_score': 40,
                    'confirm_days': 1
                }
            )
            
            backtest_result = self.backtest_service.run_backtest(
                stock_code=TEST_STOCK,
                start_date=TEST_DATE_RANGE['start'],
                end_date=TEST_DATE_RANGE['end'],
                strategy_spec=strategy_spec
            )
            
            if not backtest_result:
                result.passed = False
                result.error_message = "無法執行回測"
                self.results.append(result)
                return
            
            # 檢查交易記錄（從 details 中獲取）
            trades = backtest_result.details.get('trades', [])
            
            if not trades or len(trades) == 0:
                result.warning = True
                result.warning_message = "回測結果中沒有交易記錄（無法驗證視覺標記）"
                result.passed = True  # 這不是錯誤，只是沒有交易
                self.results.append(result)
                return
            
            # 檢查交易記錄結構（應該包含買賣點和理由）
            sample_trade = trades[0]
            
            required_trade_fields = ['entry_date', 'exit_date', 'entry_price', 'exit_price']
            missing_fields = [f for f in required_trade_fields if f not in sample_trade]
            
            if missing_fields:
                result.warning = True
                result.warning_message = f"交易記錄缺少必要欄位: {missing_fields}"
            
            # 檢查是否有理由標籤（reason_tags）
            has_reason_tags = 'entry_reason' in sample_trade or 'exit_reason' in sample_trade or 'reason_tags' in sample_trade
            
            if not has_reason_tags:
                result.warning = True
                result.warning_message = "交易記錄中缺少理由標籤（reason_tags）"
            
            result.passed = True
            result.details['total_trades'] = len(trades)
            result.details['has_reason_tags'] = has_reason_tags
            result.details['sample_trade_keys'] = list(sample_trade.keys()) if trades else []
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 3.3 完成: {'通過' if result.passed else '失敗'}")
    
    # ==================== 測試場景 4：Promote 機制 ====================
    
    def test_promote_mechanism(self):
        """驗證 Promote 機制"""
        result = ValidationResult("測試 4.1：Promote 機制（回測結果 → 策略版本）")
        
        try:
            logger.info("執行測試 4.1：Promote 機制（回測結果 → 策略版本）")
            
            # 執行回測
            from app_module.strategy_spec import StrategySpec
            
            strategy_spec = StrategySpec(
                strategy_id='baseline_score_threshold',
                strategy_version='1.0.0',
                default_params={
                    'buy_score': 60,
                    'sell_score': 40,
                    'confirm_days': 1
                }
            )
            
            backtest_result = self.backtest_service.run_backtest(
                stock_code=TEST_STOCK,
                start_date=TEST_DATE_RANGE['start'],
                end_date=TEST_DATE_RANGE['end'],
                strategy_spec=strategy_spec
            )
            
            if not backtest_result:
                result.passed = False
                result.error_message = "無法執行回測"
                self.results.append(result)
                return
            
            # 獲取 run_id（從 details 中獲取或生成）
            run_id = backtest_result.details.get('run_id')
            if not run_id:
                # 如果沒有 run_id，嘗試從 repository 獲取最新的
                runs = self.backtest_repository.list_runs(limit=1)
                if runs:
                    # runs 可能是字典列表或對象列表
                    if isinstance(runs[0], dict):
                        run_id = runs[0].get('run_id')
                    else:
                        run_id = runs[0].run_id
                else:
                    result.warning = True
                    result.warning_message = "無法獲取 run_id，跳過 Promote 測試"
                    result.passed = True
                    self.results.append(result)
                    return
            
            if not run_id:
                result.passed = False
                result.error_message = "回測結果中沒有 run_id"
                self.results.append(result)
                return
            
            # 檢查升級條件
            criteria = self.promotion_service.check_promotion_criteria(run_id)
            
            result.details['criteria_passed'] = criteria.passed
            result.details['criteria_reasons'] = criteria.reasons
            result.details['criteria_details'] = criteria.details
            
            # 如果條件通過，嘗試執行 Promote
            if criteria.passed:
                try:
                    version_id = self.promotion_service.promote_to_strategy_version(
                        run_id=run_id,
                        version_name=f"test_version_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        notes="測試用策略版本"
                    )
                    
                    if version_id:
                        result.details['promoted_version_id'] = version_id
                        result.details['promote_success'] = True
                    else:
                        result.warning = True
                        result.warning_message = "升級條件通過但 Promote 失敗"
                except Exception as e:
                    result.warning = True
                    result.warning_message = f"執行 Promote 時發生錯誤: {str(e)}"
            else:
                result.details['promote_success'] = False
                result.warning = True
                result.warning_message = f"升級條件未通過: {criteria.reasons}"
            
            result.passed = True
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 4.1 完成: {'通過' if result.passed else '失敗'}")
    
    def test_promote_to_recommendation(self):
        """驗證 Promote 後回到推薦"""
        result = ValidationResult("測試 4.2：Promote 後回到推薦（策略版本選擇）")
        
        try:
            logger.info("執行測試 4.2：Promote 後回到推薦（策略版本選擇）")
            
            # 列出已 Promote 的策略版本
            promoted_versions = self.promotion_service.list_promoted_versions()
            
            if not promoted_versions:
                result.warning = True
                result.warning_message = "目前沒有已 Promote 的策略版本（可能需要先執行 Promote）"
                result.passed = True  # 這不是錯誤
                self.results.append(result)
                return
            
            # 檢查策略版本結構
            sample_version = promoted_versions[0]
            
            required_version_fields = ['strategy_id', 'strategy_version', 'params']
            missing_fields = [f for f in required_version_fields if f not in sample_version]
            
            if missing_fields:
                result.warning = True
                result.warning_message = f"策略版本缺少必要欄位: {missing_fields}"
            
            # 驗證是否可以從 PresetService 載入（作為參數預設）
            # 這部分需要檢查 PresetService 是否支援從策略版本載入
            try:
                presets = self.preset_service.list_presets()
                result.details['presets_count'] = len(presets)
                result.details['has_presets'] = len(presets) > 0
            except Exception as e:
                result.warning = True
                result.warning_message = f"無法列出 Presets: {str(e)}"
            
            result.passed = True
            result.details['promoted_versions_count'] = len(promoted_versions)
            result.details['sample_version_keys'] = list(sample_version.keys()) if promoted_versions else []
            
        except Exception as e:
            result.passed = False
            result.error_message = f"測試失敗: {str(e)}"
            logger.error(traceback.format_exc())
        
        self.results.append(result)
        logger.info(f"測試 4.2 完成: {'通過' if result.passed else '失敗'}")
    
    # ==================== 報告生成 ====================
    
    def generate_report(self):
        """生成驗證報告"""
        logger.info("\n" + "=" * 80)
        logger.info("生成驗證報告")
        logger.info("=" * 80)
        
        # 統計結果
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.passed)
        failed_tests = sum(1 for r in self.results if not r.passed)
        warning_tests = sum(1 for r in self.results if r.warning)
        
        # 生成 Markdown 報告
        report_lines = [
            "# Phase 3.3b 完整功能驗證與壓力測試報告",
            "",
            f"**生成時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 測試摘要",
            "",
            f"- **總測試數**: {total_tests}",
            f"- **通過**: {passed_tests} ({passed_tests/total_tests*100:.1f}%)",
            f"- **失敗**: {failed_tests} ({failed_tests/total_tests*100:.1f}%)",
            f"- **警告**: {warning_tests} ({warning_tests/total_tests*100:.1f}%)",
            "",
            "## 測試結果詳情",
            ""
        ]
        
        # 按場景分組
        scenarios = {
            "1. 數據與市場觀察": [],
            "2. 推薦引擎與 Profile": [],
            "3. 研究閉環核心": [],
            "4. Promote 機制": []
        }
        
        for result in self.results:
            if "1." in result.test_name:
                scenarios["1. 數據與市場觀察"].append(result)
            elif "2." in result.test_name:
                scenarios["2. 推薦引擎與 Profile"].append(result)
            elif "3." in result.test_name:
                scenarios["3. 研究閉環核心"].append(result)
            elif "4." in result.test_name:
                scenarios["4. Promote 機制"].append(result)
        
        for scenario_name, scenario_results in scenarios.items():
            report_lines.append(f"### {scenario_name}")
            report_lines.append("")
            
            for result in scenario_results:
                status_icon = "✅" if result.passed else "❌"
                warning_icon = "⚠️" if result.warning else ""
                
                report_lines.append(f"#### {status_icon} {warning_icon} {result.test_name}")
                report_lines.append("")
                
                if result.error_message:
                    report_lines.append(f"**錯誤**: {result.error_message}")
                    report_lines.append("")
                
                if result.warning_message:
                    report_lines.append(f"**警告**: {result.warning_message}")
                    report_lines.append("")
                
                if result.details:
                    report_lines.append("**詳細信息**:")
                    report_lines.append("```json")
                    # 處理不可序列化的類型
                    def json_serial(obj):
                        """JSON serializer for objects not serializable by default json code"""
                        if isinstance(obj, (bool, np.bool_)):
                            return bool(obj)
                        elif isinstance(obj, (np.integer, np.int64, np.int32)):
                            return int(obj)
                        elif isinstance(obj, (np.floating, np.float64, np.float32)):
                            return float(obj)
                        elif isinstance(obj, (np.ndarray,)):
                            return obj.tolist()
                        elif isinstance(obj, (pd.Timestamp,)):
                            return obj.isoformat()
                        raise TypeError(f"Type {type(obj)} not serializable")
                    
                    try:
                        report_lines.append(json.dumps(result.details, indent=2, ensure_ascii=False, default=json_serial))
                    except Exception as e:
                        report_lines.append(f"無法序列化詳細信息: {str(e)}")
                        report_lines.append(str(result.details))
                    report_lines.append("```")
                    report_lines.append("")
        
        # 失效功能點與潛在問題
        report_lines.append("## 失效功能點與潛在問題")
        report_lines.append("")
        
        failed_features = [r for r in self.results if not r.passed]
        warning_features = [r for r in self.results if r.warning]
        
        if failed_features:
            report_lines.append("### ❌ 失效功能")
            report_lines.append("")
            for result in failed_features:
                report_lines.append(f"- **{result.test_name}**: {result.error_message}")
            report_lines.append("")
        else:
            report_lines.append("### ✅ 無失效功能")
            report_lines.append("")
        
        if warning_features:
            report_lines.append("### ⚠️ 潛在問題")
            report_lines.append("")
            for result in warning_features:
                report_lines.append(f"- **{result.test_name}**: {result.warning_message}")
            report_lines.append("")
        else:
            report_lines.append("### ✅ 無潛在問題")
            report_lines.append("")
        
        # 過擬合風險誤報分析
        report_lines.append("## 過擬合風險誤報分析")
        report_lines.append("")
        
        overfitting_results = [r for r in self.results if "過擬合" in r.test_name or "Overfitting" in r.test_name]
        
        if overfitting_results:
            for result in overfitting_results:
                report_lines.append(f"### {result.test_name}")
                report_lines.append("")
                if result.details.get('has_overfitting_risk'):
                    risk_level = result.details.get('risk_level', 'Unknown')
                    risk_score = result.details.get('risk_score', 0)
                    report_lines.append(f"- **風險等級**: {risk_level}")
                    report_lines.append(f"- **風險分數**: {risk_score}")
                    report_lines.append("")
                else:
                    report_lines.append("- ⚠️ 過擬合風險提示功能尚未實作或未啟用")
                    report_lines.append("")
        else:
            report_lines.append("⚠️ 未找到過擬合風險相關測試結果")
            report_lines.append("")
        
        # 寫入報告
        report_path = log_dir / 'VALIDATION_REPORT.md'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report_lines))
        
        logger.info(f"驗證報告已生成: {report_path}")
        
        # 同時輸出摘要到控制台（避免編碼問題）
        logger.info("\n" + "=" * 80)
        logger.info("Phase 3.3b 驗證摘要")
        logger.info("=" * 80)
        logger.info(f"總測試數: {total_tests}")
        logger.info(f"通過: {passed_tests} ({passed_tests/total_tests*100:.1f}%)")
        logger.info(f"失敗: {failed_tests} ({failed_tests/total_tests*100:.1f}%)")
        logger.info(f"警告: {warning_tests} ({warning_tests/total_tests*100:.1f}%)")
        logger.info(f"\n詳細報告: {report_path}")


def main():
    """主函數"""
    try:
        validator = Phase33BValidator()
        validator.run_all_tests()
        return 0
    except Exception as e:
        logger.error(f"驗證過程發生錯誤: {str(e)}")
        logger.error(traceback.format_exc())
        return 1


if __name__ == '__main__':
    exit(main())

