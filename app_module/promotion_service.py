"""
Promote 服務 (Promotion Service)
管理回測結果升級為策略版本的流程
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict

from app_module.backtest_repository import BacktestRunRepository
from app_module.backtest_service import BacktestService
from app_module.walkforward_service import WalkForwardService
from app_module.strategy_version_service import StrategyVersionService
from app_module.preset_service import PresetService

logger = logging.getLogger(__name__)


@dataclass
class PromotionCriteria:
    """升級條件檢查結果"""
    passed: bool
    reasons: List[str]  # 通過或失敗的原因
    details: Dict[str, Any]  # 詳細檢查結果


class PromotionService:
    """Promote 服務類"""
    
    def __init__(
        self,
        config,
        backtest_repository: BacktestRunRepository,
        backtest_service: BacktestService,
        walkforward_service: WalkForwardService,
        strategy_version_service: StrategyVersionService,
        preset_service: PresetService
    ):
        """
        初始化 Promote 服務
        
        Args:
            config: TWStockConfig 實例
            backtest_repository: BacktestRunRepository 實例
            backtest_service: BacktestService 實例
            walkforward_service: WalkForwardService 實例
            strategy_version_service: StrategyVersionService 實例
            preset_service: PresetService 實例
        """
        self.config = config
        self.backtest_repository = backtest_repository
        self.backtest_service = backtest_service
        self.walkforward_service = walkforward_service
        self.strategy_version_service = strategy_version_service
        self.preset_service = preset_service
    
    def check_promotion_criteria(
        self,
        run_id: str,
        min_consistency: float = 0.6,
        max_degradation: float = 0.4,
        min_sharpe_ratio: float = 0.5,
        max_drawdown_threshold: float = 0.3,
        min_win_rate: float = 0.5
    ) -> PromotionCriteria:
        """
        檢查回測結果是否符合升級條件
        
        Args:
            run_id: 回測執行 ID
            min_consistency: 最小一致性要求（0-1）
            max_degradation: 最大退化程度（0-1）
            min_sharpe_ratio: 最小 Sharpe Ratio
            max_drawdown_threshold: 最大回撤閾值（0-1）
            min_win_rate: 最小勝率（0-1）
        
        Returns:
            PromotionCriteria: 升級條件檢查結果
        """
        logger.info(f"[PromotionService] 檢查升級條件: run_id={run_id}")
        
        # 1. 載入回測結果
        run = self.backtest_repository.get_run(run_id)
        if run is None:
            return PromotionCriteria(
                passed=False,
                reasons=[f"找不到回測結果: {run_id}"],
                details={}
            )
        
        reasons = []
        details = {}
        passed = True
        
        # 2. 檢查基本績效指標
        if run.total_return <= 0:
            passed = False
            reasons.append(f"總報酬率為負或零: {run.total_return:.2%}")
        else:
            reasons.append(f"✓ 總報酬率: {run.total_return:.2%}")
        
        if run.sharpe_ratio < min_sharpe_ratio:
            passed = False
            reasons.append(f"Sharpe Ratio 過低: {run.sharpe_ratio:.2f} < {min_sharpe_ratio}")
        else:
            reasons.append(f"✓ Sharpe Ratio: {run.sharpe_ratio:.2f}")
        
        if run.max_drawdown > max_drawdown_threshold:
            passed = False
            reasons.append(f"最大回撤過大: {run.max_drawdown:.2%} > {max_drawdown_threshold:.2%}")
        else:
            reasons.append(f"✓ 最大回撤: {run.max_drawdown:.2%}")
        
        if run.win_rate < min_win_rate:
            passed = False
            reasons.append(f"勝率過低: {run.win_rate:.2%} < {min_win_rate:.2%}")
        else:
            reasons.append(f"✓ 勝率: {run.win_rate:.2%}")
        
        details['basic_metrics'] = {
            'total_return': run.total_return,
            'sharpe_ratio': run.sharpe_ratio,
            'max_drawdown': run.max_drawdown,
            'win_rate': run.win_rate
        }
        
        # 3. 檢查 Baseline 對比（如果回測報告中有）
        # 注意：需要從保存的報告中讀取 baseline_comparison
        # 這裡假設我們可以從 BacktestReportDTO 中獲取
        # 實際實現時需要從保存的報告文件中讀取
        
        # 4. 檢查過擬合風險（如果回測報告中有）
        # 注意：需要從保存的報告中讀取 overfitting_risk
        # 實際實現時需要從保存的報告文件中讀取
        
        # 5. 檢查 Walk-Forward 驗證（如果有）
        # 注意：Walk-Forward 結果可能沒有保存在 BacktestRun 中
        # 需要從其他地方獲取或重新計算
        
        logger.info(
            f"[PromotionService] 升級條件檢查完成: "
            f"passed={passed}, reasons={len(reasons)}"
        )
        
        return PromotionCriteria(
            passed=passed,
            reasons=reasons,
            details=details
        )
    
    def promote_to_strategy_version(
        self,
        run_id: str,
        version_name: Optional[str] = None,
        profile_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Optional[str]:
        """
        將回測結果升級為策略版本
        
        Args:
            run_id: 回測執行 ID
            version_name: 版本名稱（可選，如果不提供則自動生成）
            profile_id: Profile ID（可選，用於掛載到 Profile）
            notes: 備註（可選）
        
        Returns:
            策略版本 ID，如果失敗則返回 None
        """
        logger.info(f"[PromotionService] 開始升級回測結果: run_id={run_id}")
        
        # 1. 檢查升級條件
        criteria = self.check_promotion_criteria(run_id)
        if not criteria.passed:
            logger.warning(
                f"[PromotionService] 升級條件未通過: {criteria.reasons}"
            )
            return None
        
        # 2. 載入回測結果
        run = self.backtest_repository.get_run(run_id)
        if run is None:
            logger.error(f"[PromotionService] 找不到回測結果: {run_id}")
            return None
        
        # 3. 提取策略配置
        strategy_id = run.strategy_id
        strategy_params = run.strategy_params
        
        # 4. 構建回測摘要
        backtest_summary = {
            'total_return': run.total_return,
            'annual_return': run.annual_return,
            'sharpe_ratio': run.sharpe_ratio,
            'max_drawdown': run.max_drawdown,
            'win_rate': run.win_rate,
            'total_trades': run.total_trades,
            'expectancy': run.expectancy,
            'profit_factor': run.profit_factor
        }
        
        # 5. 推斷適用 Regime（從回測期間的市場狀態）
        # 簡化實現：暫時使用空列表，後續可以從 RegimeService 獲取
        regime = []
        
        # 6. 生成策略版本
        version_id = self.strategy_version_service.create_version(
            strategy_id=strategy_id,
            strategy_version=None,  # 自動生成版本號
            params=strategy_params,
            config={},  # 完整策略配置（需要從其他地方獲取）
            backtest_summary=backtest_summary,
            regime=regime,
            source_run_id=run_id,
            profile_id=profile_id,
            notes=notes
        )
        
        if version_id:
            # 7. 標記回測結果為已升級
            self.backtest_repository.mark_as_promoted(run_id, version_id)
            logger.info(
                f"[PromotionService] 升級成功: run_id={run_id} -> version_id={version_id}"
            )
        else:
            logger.error(f"[PromotionService] 升級失敗: run_id={run_id}")
        
        return version_id
    
    def list_promoted_versions(
        self,
        strategy_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        列出已升級的策略版本
        
        Args:
            strategy_id: 策略 ID 篩選（可選）
        
        Returns:
            策略版本列表
        """
        return self.strategy_version_service.list_versions(strategy_id)

