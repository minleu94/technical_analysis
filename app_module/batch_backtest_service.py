"""
批次回測服務 (Batch Backtest Service)
支援多檔股票批次回測，生成排行榜和整體統計
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from app_module.backtest_service import BacktestService
from app_module.backtest_repository import BacktestRunRepository
from app_module.strategy_spec import StrategySpec
from app_module.dtos import BacktestReportDTO


@dataclass
class StockBacktestResult:
    """單檔股票回測結果"""
    stock_code: str
    run_id: Optional[str]  # 保存後的 run_id
    success: bool  # 是否成功
    error_reason: Optional[str] = None  # 失敗原因
    # 績效指標
    cagr: Optional[float] = None
    sharpe: Optional[float] = None
    mdd: Optional[float] = None
    total_trades: Optional[int] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    # 原始報告（用於保存）
    report: Optional[BacktestReportDTO] = None


@dataclass
class BatchBacktestResultDTO:
    """批次回測結果 DTO"""
    batch_id: str
    batch_name: str
    stock_results: List[StockBacktestResult]
    overall_stats: Dict[str, Any]
    created_at: str


class BatchBacktestService:
    """批次回測服務"""
    
    def __init__(
        self,
        backtest_service: BacktestService,
        run_repository: Optional[BacktestRunRepository] = None
    ):
        """
        初始化批次回測服務
        
        Args:
            backtest_service: 單檔回測服務
            run_repository: 回測結果儲存庫（可選，用於保存結果）
        """
        self.backtest_service = backtest_service
        self.run_repository = run_repository
    
    def run_batch_backtest(
        self,
        stock_codes: List[str],
        start_date: str,
        end_date: str,
        strategy_spec: StrategySpec,
        capital: float = 1000000.0,
        fee_bps: float = 14.25,
        slippage_bps: float = 5.0,
        execution_price: str = "next_open",
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        stop_loss_atr_mult: Optional[float] = None,
        take_profit_atr_mult: Optional[float] = None,
        sizing_mode: str = "all_in",
        fixed_amount: Optional[float] = None,
        risk_pct: Optional[float] = None,
        max_positions: Optional[int] = None,
        position_sizing: str = "equal_weight",
        allow_pyramid: bool = False,
        allow_reentry: bool = True,
        reentry_cooldown_days: int = 0,
        enable_limit_up_down: bool = True,
        enable_volume_constraint: bool = True,
        max_participation_rate: float = 0.05,
        save_runs: bool = True,
        batch_name: Optional[str] = None,
        progress_callback: Optional[Any] = None
    ) -> BatchBacktestResultDTO:
        """
        執行批次回測
        
        Args:
            stock_codes: 股票代號列表
            start_date: 開始日期
            end_date: 結束日期
            strategy_spec: 策略規格
            capital: 初始資金（每檔獨立）
            fee_bps: 手續費
            slippage_bps: 滑價
            stop_loss_pct: 停損百分比
            take_profit_pct: 停利百分比
            sizing_mode: 部位 sizing 模式
            fixed_amount: 固定金額
            risk_pct: 風險百分比
            enable_limit_up_down: 啟用漲跌停限制
            enable_volume_constraint: 啟用成交量約束
            max_participation_rate: 最大參與率
            save_runs: 是否保存每個 run
            batch_name: 批次名稱（可選）
            progress_callback: 進度回調函數 (current, total, stock_code, message)
        
        Returns:
            BatchBacktestResultDTO: 批次回測結果
        """
        if not stock_codes:
            raise ValueError("股票代號列表不能為空")
        
        # 生成批次 ID 和名稱
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not batch_name:
            batch_name = f"批次回測_{len(stock_codes)}檔_{datetime.now().strftime('%Y%m%d_%H%M')}"
        
        stock_results = []
        total = len(stock_codes)
        
        for idx, stock_code in enumerate(stock_codes, 1):
            if progress_callback:
                progress_callback(idx, total, stock_code, f"正在回測 {stock_code}...")
            
            try:
                # 執行單檔回測
                report = self.backtest_service.run_backtest(
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    strategy_spec=strategy_spec,
                    capital=capital,
                    fee_bps=fee_bps,
                    slippage_bps=slippage_bps,
                    execution_price=execution_price,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    stop_loss_atr_mult=stop_loss_atr_mult,
                    take_profit_atr_mult=take_profit_atr_mult,
                    sizing_mode=sizing_mode,
                    fixed_amount=fixed_amount,
                    risk_pct=risk_pct,
                    max_positions=max_positions,
                    position_sizing=position_sizing,
                    allow_pyramid=allow_pyramid,
                    allow_reentry=allow_reentry,
                    reentry_cooldown_days=reentry_cooldown_days,
                    enable_limit_up_down=enable_limit_up_down,
                    enable_volume_constraint=enable_volume_constraint,
                    max_participation_rate=max_participation_rate
                )
                
                # 判斷是否成功（用於統計和顯示）
                success = True
                error_reason = None
                
                # 檢查是否有錯誤
                if 'error' in report.details:
                    success = False
                    error_reason = report.details['error']
                # 檢查是否有交易
                elif report.total_trades == 0:
                    success = False
                    error_reason = "無交易信號"
                # 檢查是否資料不足
                elif report.total_return == 0 and report.total_trades == 0:
                    success = False
                    error_reason = "資料不足"
                
                # 提取績效指標（即使失敗也提取，用於顯示）
                result = StockBacktestResult(
                    stock_code=stock_code,
                    run_id=None,
                    success=success,
                    error_reason=error_reason,
                    cagr=report.annual_return if report.annual_return is not None else None,
                    sharpe=report.sharpe_ratio if report.sharpe_ratio is not None else None,
                    mdd=report.max_drawdown if report.max_drawdown is not None else None,
                    total_trades=report.total_trades,
                    win_rate=report.win_rate if report.win_rate is not None else None,
                    profit_factor=report.details.get('profit_factor', 0.0) if report.details.get('profit_factor') is not None else None,
                    report=report  # 總是保存 report，即使失敗也保存（用於查看詳細信息）
                )
                
                # 保存 run（只要有交易就保存，即使結果不好也保存，方便後續分析）
                # 條件：有交易 或 有 report（即使失敗也保存，方便查看錯誤原因）
                should_save = (report.total_trades > 0 or report is not None) and save_runs and self.run_repository
                if should_save:
                    try:
                        run_id = self.run_repository.save_run(
                            run_name=f"{batch_name}_{stock_code}",
                            stock_code=stock_code,
                            start_date=start_date,
                            end_date=end_date,
                            strategy_id=strategy_spec.strategy_id,
                            strategy_params=strategy_spec.config.get('params', {}),
                            capital=capital,
                            fee_bps=fee_bps,
                            slippage_bps=slippage_bps,
                            stop_loss_pct=stop_loss_pct,
                            take_profit_pct=take_profit_pct,
                            report=report,
                            notes=f"批次回測：{batch_name}" + (f" ({error_reason})" if error_reason else "")
                        )
                        result.run_id = run_id
                        print(f"[BatchBacktestService] 已保存 {stock_code} 的回測結果 (run_id: {run_id})")
                    except Exception as e:
                        import traceback
                        print(f"[BatchBacktestService] 保存 {stock_code} 失敗: {e}")
                        traceback.print_exc()
                
                stock_results.append(result)
                
            except Exception as e:
                # 處理異常
                error_msg = str(e)
                if "無法載入股票數據" in error_msg or "數據" in error_msg:
                    error_reason = "資料不足"
                elif "未生成任何信號" in error_msg or "信號" in error_msg:
                    error_reason = "無交易信號"
                else:
                    error_reason = f"回測失敗: {error_msg[:50]}"
                
                result = StockBacktestResult(
                    stock_code=stock_code,
                    run_id=None,
                    success=False,
                    error_reason=error_reason
                )
                stock_results.append(result)
        
        # 計算整體統計
        overall_stats = self._calculate_overall_stats(stock_results)
        
        # 構建結果 DTO
        return BatchBacktestResultDTO(
            batch_id=batch_id,
            batch_name=batch_name,
            stock_results=stock_results,
            overall_stats=overall_stats,
            created_at=datetime.now().isoformat()
        )
    
    def _calculate_overall_stats(self, stock_results: List[StockBacktestResult]) -> Dict[str, Any]:
        """
        計算整體統計
        
        Args:
            stock_results: 股票結果列表
        
        Returns:
            整體統計字典
        """
        # 過濾成功的結果
        successful_results = [r for r in stock_results if r.success]
        
        if not successful_results:
            return {
                'total_stocks': len(stock_results),
                'successful_stocks': 0,
                'profitable_stocks': 0,
                'win_rate': 0.0,
                'cagr_median': 0.0,
                'mdd_median': 0.0
            }
        
        # 計算賺錢的股票數（CAGR > 0）
        profitable_stocks = sum(1 for r in successful_results if r.cagr and r.cagr > 0)
        
        # 計算股票層級勝率
        win_rate = profitable_stocks / len(successful_results) if successful_results else 0.0
        
        # 提取 CAGR 和 MDD
        cagr_values = [r.cagr for r in successful_results if r.cagr is not None]
        mdd_values = [r.mdd for r in successful_results if r.mdd is not None]
        
        # 計算 median
        cagr_median = np.median(cagr_values) if cagr_values else 0.0
        mdd_median = np.median(mdd_values) if mdd_values else 0.0
        
        return {
            'total_stocks': len(stock_results),
            'successful_stocks': len(successful_results),
            'profitable_stocks': profitable_stocks,
            'win_rate': win_rate,
            'cagr_median': cagr_median,
            'mdd_median': mdd_median
        }
    
    def create_leaderboard_dataframe(
        self,
        batch_result: BatchBacktestResultDTO,
        sort_by: str = "cagr_mdd"
    ) -> pd.DataFrame:
        """
        創建排行榜 DataFrame
        
        Args:
            batch_result: 批次回測結果
            sort_by: 排序方式（"cagr", "sharpe", "mdd", "cagr_mdd"）
        
        Returns:
            排行榜 DataFrame
        """
        data = []
        
        for result in batch_result.stock_results:
            row = {
                '股票代號': result.stock_code,
                'CAGR%': result.cagr * 100 if result.cagr is not None else None,
                'Sharpe': result.sharpe if result.sharpe is not None else None,
                'MDD%': result.mdd * 100 if result.mdd is not None else None,
                'Trades': result.total_trades if result.total_trades is not None else 0,
                'WinRate%': result.win_rate * 100 if result.win_rate is not None else None,
                'PF': result.profit_factor if result.profit_factor is not None else None,
                '是否成交': '是' if result.total_trades and result.total_trades > 0 else '否',
                '失敗原因': result.error_reason if not result.success else '',
                'RunID': result.run_id if result.run_id else ''
            }
            data.append(row)
        
        df = pd.DataFrame(data)
        
        # 排序
        if sort_by == "cagr":
            df = df.sort_values('CAGR%', ascending=False, na_position='last')
        elif sort_by == "sharpe":
            df = df.sort_values('Sharpe', ascending=False, na_position='last')
        elif sort_by == "mdd":
            df = df.sort_values('MDD%', ascending=True, na_position='last')  # MDD 越小越好
        elif sort_by == "cagr_mdd":
            # CAGR - MDD 權衡（CAGR 越高越好，MDD 越小越好）
            df['Score'] = df.apply(
                lambda row: (row['CAGR%'] if pd.notna(row['CAGR%']) else -999) - 
                           (abs(row['MDD%']) if pd.notna(row['MDD%']) else 999),
                axis=1
            )
            df = df.sort_values('Score', ascending=False, na_position='last')
            df = df.drop('Score', axis=1)
        else:
            # 預設按 CAGR-MDD 排序
            df['Score'] = df.apply(
                lambda row: (row['CAGR%'] if pd.notna(row['CAGR%']) else -999) - 
                           (abs(row['MDD%']) if pd.notna(row['MDD%']) else 999),
                axis=1
            )
            df = df.sort_values('Score', ascending=False, na_position='last')
            df = df.drop('Score', axis=1)
        
        return df

