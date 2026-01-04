"""
參數最佳化服務 (Optimizer Service)
支援 Grid Search 參數掃描和最佳化
"""

import itertools
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParamRange:
    """參數範圍定義"""
    name: str
    type: str  # 'int', 'float', 'list'
    values: List[Any]  # 固定值列表
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None


@dataclass
class OptimizationResult:
    """最佳化結果"""
    params: Dict[str, Any]
    metrics: Dict[str, float]
    rank: int = 0
    run_id: Optional[str] = None


class OptimizerService:
    """參數最佳化服務"""
    
    def __init__(self, backtest_service, run_repository=None, max_workers: Optional[int] = None):
        """
        初始化最佳化服務
        
        Args:
            backtest_service: BacktestService 實例
            run_repository: BacktestRunRepository 實例（可選，用於保存結果）
            max_workers: 最大並行工作線程數（None 表示使用 CPU 核心數，但限制最大為 8）
        """
        self.backtest_service = backtest_service
        # 預設使用 CPU 核心數，但限制最大為 8 以避免過載
        if max_workers is None:
            max_workers = min(os.cpu_count() or 4, 8)
        self.max_workers = max_workers
        logger.info(f"[OptimizerService] 初始化，最大並行線程數: {self.max_workers}")
        self.run_repository = run_repository
    
    def generate_param_grid(self, param_ranges: Dict[str, ParamRange]) -> List[Dict[str, Any]]:
        """
        生成參數網格
        
        Args:
            param_ranges: 參數範圍字典 {param_name: ParamRange}
        
        Returns:
            參數組合列表
        """
        param_combinations = []
        
        # 為每個參數生成值列表
        param_value_lists = {}
        for param_name, param_range in param_ranges.items():
            if param_range.type == 'list':
                # 直接使用提供的值列表
                param_value_lists[param_name] = param_range.values
            elif param_range.type == 'int':
                # 整數範圍
                if param_range.min is not None and param_range.max is not None:
                    step = param_range.step or 1
                    param_value_lists[param_name] = list(
                        range(int(param_range.min), int(param_range.max) + 1, int(step))
                    )
                else:
                    param_value_lists[param_name] = param_range.values
            elif param_range.type == 'float':
                # 浮點數範圍
                if param_range.min is not None and param_range.max is not None:
                    step = param_range.step or 1.0
                    values = []
                    current = param_range.min
                    while current <= param_range.max:
                        values.append(round(current, 2))
                        current += step
                    param_value_lists[param_name] = values
                else:
                    param_value_lists[param_name] = param_range.values
        
        # 生成所有組合
        param_names = list(param_value_lists.keys())
        param_values = [param_value_lists[name] for name in param_names]
        
        for combination in itertools.product(*param_values):
            param_dict = dict(zip(param_names, combination))
            param_combinations.append(param_dict)
        
        return param_combinations
    
    def grid_search(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        strategy_id: str,
        base_params: Dict[str, Any],
        param_ranges: Dict[str, ParamRange],
        capital: float = 1000000.0,
        fee_bps: float = 14.25,
        slippage_bps: float = 5.0,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        objective: str = 'sharpe_ratio',  # 'sharpe_ratio', 'cagr', 'cagr_mdd'
        top_n: int = 20,
        progress_callback: Optional[Callable] = None
    ) -> List[OptimizationResult]:
        """
        執行 Grid Search 參數掃描
        
        Args:
            stock_code: 股票代號
            start_date: 開始日期
            end_date: 結束日期
            strategy_id: 策略ID
            base_params: 基礎參數（固定參數）
            param_ranges: 要掃描的參數範圍
            capital: 初始資金
            fee_bps: 手續費
            slippage_bps: 滑價
            stop_loss_pct: 停損百分比
            take_profit_pct: 停利百分比
            objective: 目標指標
            top_n: 返回前N名結果
            progress_callback: 進度回調函數 (current, total, message)
        
        Returns:
            最佳化結果列表（已排序）
        """
        from app_module.strategy_spec import StrategySpec
        from app_module.strategy_registry import StrategyRegistry
        
        # 生成參數網格
        param_combinations = self.generate_param_grid(param_ranges)
        total_combinations = len(param_combinations)
        
        if progress_callback:
            progress_callback(0, total_combinations, f"開始掃描 {total_combinations} 組參數（使用 {self.max_workers} 個線程）...")
        
        logger.info(f"[OptimizerService] 開始 Grid Search，共 {total_combinations} 組參數，使用 {self.max_workers} 個並行線程")
        
        # ✅ 優化：預先載入數據一次，所有參數組合共用
        logger.info(f"[OptimizerService] 預先載入數據（股票 {stock_code}，日期範圍 {start_date} 到 {end_date}）...")
        preloaded_data, actual_start_date, actual_end_date = self.backtest_service._load_stock_data(
            stock_code, start_date, end_date
        )
        
        if preloaded_data is None or len(preloaded_data) == 0:
            logger.error(f"[OptimizerService] 無法載入數據，參數掃描終止")
            return []
        
        # 記錄日期調整信息（只在第一次顯示）
        if actual_start_date != start_date or actual_end_date != end_date:
            logger.warning(
                f"[OptimizerService] ⚠️ 日期範圍已自動調整: "
                f"請求 {start_date}~{end_date} → 實際 {actual_start_date}~{actual_end_date}"
            )
        
        logger.info(f"[OptimizerService] 數據載入完成，共 {len(preloaded_data)} 筆數據，開始參數掃描...")
        
        results = []
        completed_count = 0
        
        # 定義單個參數組合的回測函數
        def run_single_backtest(param_combo, idx):
            """執行單個參數組合的回測"""
            try:
                # 合併基礎參數和掃描參數
                full_params = {**base_params, **param_combo}
                
                # 創建策略規格
                strategy_info = StrategyRegistry.list_strategies().get(strategy_id, {})
                strategy_spec = StrategySpec(
                    strategy_id=strategy_id,
                    strategy_version="1.0",
                    name=strategy_info.get('name', strategy_id),
                    description=strategy_info.get('description', ''),
                    regime=[],
                    risk_level="medium",
                    target_type="stock",
                    config={
                        'params': full_params
                    }
                )
                
                # 執行回測（使用預載入的數據）
                report = self.backtest_service.run_backtest(
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    strategy_spec=strategy_spec,
                    capital=capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    preloaded_data=preloaded_data,  # ✅ 使用預載入的數據
                    actual_start_date=actual_start_date,  # ✅ 傳遞實際日期範圍
                    actual_end_date=actual_end_date
                )
                
                # 計算目標分數
                if objective == 'sharpe_ratio':
                    score = report.sharpe_ratio
                elif objective == 'cagr':
                    score = report.annual_return
                elif objective == 'cagr_mdd':
                    # CAGR - MDD 權衡（MDD為負數，所以是加法）
                    score = report.annual_return + report.max_drawdown
                else:
                    score = report.sharpe_ratio
                
                # 構建結果
                result = OptimizationResult(
                    params=full_params,
                    metrics={
                        'total_return': report.total_return,
                        'annual_return': report.annual_return,
                        'sharpe_ratio': report.sharpe_ratio,
                        'max_drawdown': report.max_drawdown,
                        'win_rate': report.win_rate,
                        'total_trades': report.total_trades,
                        'expectancy': report.expectancy,
                        'profit_factor': report.details.get('profit_factor', 0.0),
                        'score': score  # 目標分數
                    }
                )
                return (idx, result, None)
                
            except Exception as e:
                # 記錄錯誤但繼續
                error_msg = f"參數組合 {param_combo} 回測失敗: {e}"
                logger.warning(f"[OptimizerService] {error_msg}")
                return (idx, None, error_msg)
        
        # 使用線程池並行執行
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任務
            future_to_idx = {
                executor.submit(run_single_backtest, param_combo, idx): idx
                for idx, param_combo in enumerate(param_combinations)
            }
            
            # 收集結果（按完成順序）
            completed_results = {}
            for future in as_completed(future_to_idx):
                idx, result, error = future.result()
                completed_results[idx] = (result, error)
                completed_count += 1
                
                # 更新進度
                if progress_callback:
                    progress_callback(
                        completed_count,
                        total_combinations,
                        f"已完成 {completed_count}/{total_combinations} ({completed_count/total_combinations*100:.1f}%)"
                    )
        
        # 按原始順序整理結果
        for idx in range(total_combinations):
            if idx in completed_results:
                result, error = completed_results[idx]
                if result is not None:
                    results.append(result)
        
        # 按目標分數排序
        results.sort(key=lambda x: x.metrics.get('score', 0), reverse=True)
        
        # 設置排名
        for rank, result in enumerate(results, 1):
            result.rank = rank
        
        # 返回前N名
        return results[:top_n]
    
    def create_optimization_summary(self, results: List[OptimizationResult]) -> pd.DataFrame:
        """
        創建最佳化結果摘要表格
        
        Args:
            results: 最佳化結果列表
        
        Returns:
            DataFrame
        """
        summary_data = []
        
        for result in results:
            row = {
                '排名': result.rank,
                **{f'參數_{k}': v for k, v in result.params.items()},
                '總報酬率%': result.metrics.get('total_return', 0) * 100,
                '年化報酬率%': result.metrics.get('annual_return', 0) * 100,
                '夏普比率': result.metrics.get('sharpe_ratio', 0),
                '最大回撤%': result.metrics.get('max_drawdown', 0) * 100,
                '勝率%': result.metrics.get('win_rate', 0) * 100,
                '交易次數': result.metrics.get('total_trades', 0),
                '期望值%': result.metrics.get('expectancy', 0) * 100,
                '獲利因子': result.metrics.get('profit_factor', 0),
                '目標分數': result.metrics.get('score', 0)
            }
            summary_data.append(row)
        
        return pd.DataFrame(summary_data)

