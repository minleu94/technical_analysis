"""
Walk-forward 驗證服務
防止過擬合，支援 Train-Test Split 和 Walk-forward 驗證
"""

from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import pandas as pd
from app_module.backtest_service import BacktestService
from app_module.dtos import BacktestReportDTO
from app_module.strategy_spec import StrategySpec


@dataclass
class WalkForwardResult:
    """Walk-forward 驗證結果"""
    train_period: Tuple[str, str]  # (start, end)
    test_period: Tuple[str, str]
    train_metrics: Dict[str, float]
    test_metrics: Dict[str, float]
    degradation: float  # 測試期相對於訓練期的退化程度
    params: Dict[str, Any]
    warmup_days: int = 0  # 暖機期天數


class WalkForwardService:
    """Walk-forward 驗證服務"""
    
    def __init__(self, backtest_service: BacktestService):
        """
        初始化 Walk-forward 服務
        
        Args:
            backtest_service: BacktestService 實例
        """
        self.backtest_service = backtest_service
    
    def train_test_split(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        strategy_spec: StrategySpec,
        train_ratio: float = 0.7,
        capital: float = 1000000.0,
        fee_bps: float = 14.25,
        slippage_bps: float = 5.0,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        warmup_days: int = 0
    ) -> Tuple[BacktestReportDTO, BacktestReportDTO]:
        """
        執行 Train-Test Split 驗證
        
        Args:
            stock_code: 股票代號
            start_date: 開始日期
            end_date: 結束日期
            strategy_spec: 策略規格
            train_ratio: 訓練集比例（0-1）
            capital: 初始資金
            fee_bps: 手續費
            slippage_bps: 滑價
            stop_loss_pct: 停損百分比
            take_profit_pct: 停利百分比
        
        Returns:
            (train_report, test_report)
        """
        # 計算分割點
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        # 計算實際訓練期開始（從開始日期 + warmup_days 開始）
        actual_train_start = start_dt + timedelta(days=warmup_days)
        
        # 確保實際訓練期開始不晚於結束日期
        if actual_train_start >= end_dt:
            raise ValueError(f"warmup_days ({warmup_days}) 過大，導致可用數據不足")
        
        total_days = (end_dt - actual_train_start).days
        train_days = int(total_days * train_ratio)
        
        train_end_dt = actual_train_start + timedelta(days=train_days)
        train_end_date = train_end_dt.strftime('%Y-%m-%d')
        test_start_date = (train_end_dt + timedelta(days=1)).strftime('%Y-%m-%d')
        
        # 執行訓練集回測（使用實際訓練期開始日期）
        train_report = self.backtest_service.run_backtest(
            stock_code=stock_code,
            start_date=actual_train_start.strftime('%Y-%m-%d'),
            end_date=train_end_date,
            strategy_spec=strategy_spec,
            capital=capital,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct
        )
        
        # 執行測試集回測
        test_report = self.backtest_service.run_backtest(
            stock_code=stock_code,
            start_date=test_start_date,
            end_date=end_date,
            strategy_spec=strategy_spec,
            capital=capital,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct
        )
        
        return train_report, test_report
    
    def walk_forward(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        strategy_spec: StrategySpec,
        train_months: int = 6,
        test_months: int = 3,
        step_months: int = 3,
        capital: float = 1000000.0,
        fee_bps: float = 14.25,
        slippage_bps: float = 5.0,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        warmup_days: int = 0
    ) -> List[WalkForwardResult]:
        """
        執行 Walk-forward 驗證
        
        Args:
            stock_code: 股票代號
            start_date: 開始日期
            end_date: 結束日期
            strategy_spec: 策略規格
            train_months: 訓練期長度（月）
            test_months: 測試期長度（月）
            step_months: 步進長度（月）
            capital: 初始資金
            fee_bps: 手續費
            slippage_bps: 滑價
            stop_loss_pct: 停損百分比
            take_profit_pct: 停利百分比
            progress_callback: 進度回調函數
        
        Returns:
            Walk-forward 結果列表
        """
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        results = []
        current_start = start_dt
        
        fold = 0
        while current_start < end_dt:
            # 計算實際訓練期開始（從當前開始日期 + warmup_days 開始）
            actual_train_start = current_start + timedelta(days=warmup_days)
            
            # 確保實際訓練期開始不晚於結束日期
            if actual_train_start >= end_dt:
                break
            
            # 計算訓練期和測試期
            train_end = actual_train_start + pd.DateOffset(months=train_months)
            test_start = train_end + pd.DateOffset(days=1)
            test_end = test_start + pd.DateOffset(months=test_months)
            
            # 確保不超過總日期範圍
            if train_end > end_dt:
                break
            if test_end > end_dt:
                test_end = end_dt
            
            if test_start >= test_end:
                break
            
            fold += 1
            
            if progress_callback:
                progress_callback(
                    fold,
                    f"Fold {fold}: Train {actual_train_start.strftime('%Y-%m-%d')} ~ {train_end.strftime('%Y-%m-%d')}, "
                    f"Test {test_start.strftime('%Y-%m-%d')} ~ {test_end.strftime('%Y-%m-%d')}"
                )
            
            try:
                # 訓練集回測（使用實際訓練期開始日期）
                train_report = self.backtest_service.run_backtest(
                    stock_code=stock_code,
                    start_date=actual_train_start.strftime('%Y-%m-%d'),
                    end_date=train_end.strftime('%Y-%m-%d'),
                    strategy_spec=strategy_spec,
                    capital=capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct
                )
                
                # 測試集回測
                test_report = self.backtest_service.run_backtest(
                    stock_code=stock_code,
                    start_date=test_start.strftime('%Y-%m-%d'),
                    end_date=test_end.strftime('%Y-%m-%d'),
                    strategy_spec=strategy_spec,
                    capital=capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct
                )
                
                # 計算退化程度（測試期相對於訓練期的表現）
                train_sharpe = train_report.sharpe_ratio if train_report.sharpe_ratio != 0 else 0.01
                test_sharpe = test_report.sharpe_ratio
                degradation = (test_sharpe - train_sharpe) / abs(train_sharpe) if train_sharpe != 0 else 0
                
                result = WalkForwardResult(
                    train_period=(actual_train_start.strftime('%Y-%m-%d'), train_end.strftime('%Y-%m-%d')),
                    test_period=(test_start.strftime('%Y-%m-%d'), test_end.strftime('%Y-%m-%d')),
                    train_metrics={
                        'total_return': train_report.total_return,
                        'annual_return': train_report.annual_return,
                        'sharpe_ratio': train_report.sharpe_ratio,
                        'max_drawdown': train_report.max_drawdown,
                        'win_rate': train_report.win_rate,
                        'total_trades': train_report.total_trades
                    },
                    test_metrics={
                        'total_return': test_report.total_return,
                        'annual_return': test_report.annual_return,
                        'sharpe_ratio': test_report.sharpe_ratio,
                        'max_drawdown': test_report.max_drawdown,
                        'win_rate': test_report.win_rate,
                        'total_trades': test_report.total_trades
                    },
                    degradation=degradation,
                    params=strategy_spec.config.get('params', {}),
                    warmup_days=warmup_days
                )
                results.append(result)
                
            except Exception as e:
                print(f"[WalkForwardService] Fold {fold} 失敗: {e}")
                continue
            
            # 移動到下一個窗口
            current_start = current_start + pd.DateOffset(months=step_months)
        
        return results
    
    def summarize_walkforward(self, results: List[WalkForwardResult]) -> Dict[str, Any]:
        """
        總結 Walk-forward 結果
        
        Args:
            results: Walk-forward 結果列表
        
        Returns:
            摘要字典
        """
        if not results:
            return {}
        
        # 計算平均指標
        avg_train_sharpe = sum(r.train_metrics['sharpe_ratio'] for r in results) / len(results)
        avg_test_sharpe = sum(r.test_metrics['sharpe_ratio'] for r in results) / len(results)
        avg_degradation = sum(r.degradation for r in results) / len(results)
        
        # 計算一致性（測試期表現穩定的比例）
        positive_test_count = sum(1 for r in results if r.test_metrics['sharpe_ratio'] > 0)
        consistency = positive_test_count / len(results) if results else 0
        
        return {
            'total_folds': len(results),
            'avg_train_sharpe': avg_train_sharpe,
            'avg_test_sharpe': avg_test_sharpe,
            'avg_degradation': avg_degradation,
            'consistency': consistency,
            'positive_test_ratio': consistency
        }

