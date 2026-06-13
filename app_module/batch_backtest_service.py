"""
批次回測服務 (Batch Backtest Service)
支援多檔股票批次回測，生成排行榜和整體統計
"""

import os
import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from uuid import uuid4

from app_module.backtest_service import BacktestService
from app_module.backtest_repository import BacktestRunRepository
from app_module.strategy_spec import StrategySpec
from app_module.dtos import BacktestReportDTO
from app_module.exceptions import BacktestCancelledError

logger = logging.getLogger(__name__)


def _run_batch_backtest_worker(
    config,
    stock_code: str,
    start_date: str,
    end_date: str,
    strategy_spec: StrategySpec,
    capital: float,
    fee_bps: float,
    slippage_bps: float,
    execution_price: str,
    stop_loss_pct: Optional[float],
    take_profit_pct: Optional[float],
    stop_loss_atr_mult: Optional[float],
    take_profit_atr_mult: Optional[float],
    sizing_mode: str,
    fixed_amount: Optional[float],
    risk_pct: Optional[float],
    max_positions: Optional[int],
    position_sizing: str,
    allow_pyramid: bool,
    allow_reentry: bool,
    reentry_cooldown_days: int,
    enable_limit_up_down: bool,
    enable_volume_constraint: bool,
    max_participation_rate: float
) -> BacktestReportDTO:
    """在子進程中執行單檔回測的 Worker 函數 (Windows spawn 相容)"""

    import app_module.strategies  # 確保子進程載入並註冊所有內建策略
    from app_module.backtest_service import BacktestService
    # 為防止多行程連線衝突，每個子行程重新實例化
    service = BacktestService(config)
    report = service.run_backtest(
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
    return report


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
        run_repository: Optional[BacktestRunRepository] = None,
        worker_callable: Callable = _run_batch_backtest_worker
    ):
        """
        初始化批次回測服務

        Args:
            backtest_service: 單檔回測服務
            run_repository: 回測結果儲存庫（可選，用於保存結果）
            worker_callable: 用於並行計算的 Worker 函數
        """
        self.backtest_service = backtest_service
        self.run_repository = run_repository
        self.worker_callable = worker_callable

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
        progress_callback: Optional[Any] = None,
        check_cancel: Optional[Callable[[], bool]] = None,
        parallel_threshold: Optional[int] = None,
        max_workers: Optional[int] = None
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
            check_cancel: 取消檢查回調 (返回 bool)
            parallel_threshold: 啟用並行計算的起點門檻 (None 或股票數比此值大才並行)
            max_workers: 最大工作進程數

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

        # 判斷是否需要啟用並行
        should_parallel = False
        if parallel_threshold is not None and len(stock_codes) >= parallel_threshold:
            should_parallel = True

        if not should_parallel:
            # ==================== 1. 循序路徑 (預設) ====================
            for idx, stock_code in enumerate(stock_codes, 1):
                # 每個股票處理前，先檢查取消
                if check_cancel and check_cancel():
                    raise BacktestCancelledError("批次回測任務已被使用者取消")

                if progress_callback:
                    progress_callback(idx, total, stock_code, f"正在回測 {stock_code} (循序)...")

                try:

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

                    success = True
                    error_reason = None
                    if 'error' in report.details:
                        success = False
                        error_reason = report.details['error']
                    elif report.total_trades == 0:
                        success = False
                        error_reason = "無交易信號"
                    elif report.total_return == 0 and report.total_trades == 0:
                        success = False
                        error_reason = "資料不足"

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
                        report=report
                    )

                    should_save = (report.total_trades > 0 or report is not None) and save_runs and self.run_repository
                    if should_save and self.run_repository is not None:
                        try:
                            # 循序路徑也必須顯式傳遞唯一 run_id，防止秒級覆寫
                            unique_run_id = f"run_{batch_id}_{stock_code}_{uuid4().hex[:8]}"
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
                                notes=f"批次回測：{batch_name}" + (f" ({error_reason})" if error_reason else ""),
                                run_id=unique_run_id
                            )
                            result.run_id = run_id
                            logger.info(f"[BatchBacktestService] 已保存 {stock_code} 的回測結果 (run_id: {run_id})")
                        except Exception as e:
                            logger.error(f"[BatchBacktestService] 保存 {stock_code} 失敗: {e}")

                    stock_results.append(result)

                except Exception as e:
                    error_msg = str(e)
                    error_reason = f"回測失敗: {error_msg[:50]}"
                    result = StockBacktestResult(
                        stock_code=stock_code,
                        run_id=None,
                        success=False,
                        error_reason=error_reason
                    )
                    stock_results.append(result)
        else:
            # ==================== 2. 並行路徑 (ProcessPool) ====================
            if max_workers is None:
                max_workers = min(os.cpu_count() or 4, 8)

            # 手動初始化 ProcessPoolExecutor，避開 with 語意以利安全軟取消
            executor = ProcessPoolExecutor(max_workers=max_workers)

            max_in_flight = max_workers * 2
            submitted_idx = 0
            futures = {}
            cancellation_requested = False

            # 提交首批
            while submitted_idx < min(len(stock_codes), max_in_flight):
                code = stock_codes[submitted_idx]
                fut = executor.submit(
                    self.worker_callable,
                    self.backtest_service.config,
                    code, start_date, end_date, strategy_spec, capital,
                    fee_bps, slippage_bps, execution_price, stop_loss_pct,
                    take_profit_pct, stop_loss_atr_mult, take_profit_atr_mult,
                    sizing_mode, fixed_amount, risk_pct, max_positions,
                    position_sizing, allow_pyramid, allow_reentry,
                    reentry_cooldown_days, enable_limit_up_down,
                    enable_volume_constraint, max_participation_rate
                )
                futures[fut] = code
                submitted_idx += 1

            pending = set(futures.keys())
            completed_count = 0

            try:
                while pending:
                    # 1. 檢查取消旗標
                    if not cancellation_requested and check_cancel and check_cancel():
                        cancellation_requested = True
                        for fut in pending:
                            fut.cancel()
                        executor.shutdown(wait=False, cancel_futures=True)

                    # 2. wait 輪詢 (0.1 秒即時輪詢)
                    done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)

                    # 3. 處理已完成的結果 (若已取消則直接丟棄，不進行 DB 寫入)
                    for fut in done:
                        code = futures[fut]
                        completed_count += 1

                        if progress_callback and not cancellation_requested:
                            progress_callback(completed_count, total, code, f"正在回測 {code} (並行)...")

                        try:
                            report = fut.result()
                            if not cancellation_requested:
                                success = True
                                error_reason = None
                                if 'error' in report.details:
                                    success = False
                                    error_reason = report.details['error']
                                elif report.total_trades == 0:
                                    success = False
                                    error_reason = "無交易信號"
                                elif report.total_return == 0 and report.total_trades == 0:
                                    success = False
                                    error_reason = "資料不足"

                                result = StockBacktestResult(
                                    stock_code=code,
                                    run_id=None,
                                    success=success,
                                    error_reason=error_reason,
                                    cagr=report.annual_return,
                                    sharpe=report.sharpe_ratio,
                                    mdd=report.max_drawdown,
                                    total_trades=report.total_trades,
                                    win_rate=report.win_rate,
                                    profit_factor=report.details.get('profit_factor', 0.0),
                                    report=report
                                )

                                should_save = (report.total_trades > 0 or report is not None) and save_runs and self.run_repository
                                if should_save and self.run_repository is not None:
                                    try:
                                        # 並行路徑也必須顯式傳遞唯一 run_id
                                        unique_run_id = f"run_{batch_id}_{code}_{uuid4().hex[:8]}"
                                        run_id = self.run_repository.save_run(
                                            run_name=f"{batch_name}_{code}",
                                            stock_code=code,
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
                                            notes=f"批次回測：{batch_name}" + (f" ({error_reason})" if error_reason else ""),
                                            run_id=unique_run_id
                                        )
                                        result.run_id = run_id
                                    except Exception as e:
                                        logger.error(f"[BatchBacktestService] 保存 {code} 失敗: {e}")
                                stock_results.append(result)
                        except Exception as e:
                            logger.error(f"{code} 並行回測異常: {e}")
                            if not cancellation_requested:
                                result = StockBacktestResult(
                                    stock_code=code,
                                    run_id=None,
                                    success=False,
                                    error_reason=f"回測失敗: {str(e)[:50]}"
                                )
                                stock_results.append(result)

                    # 4. 動態補進新任務 (補任務前雙重檢查取消)
                    if not cancellation_requested and not (check_cancel and check_cancel()):
                        while len(pending) < max_in_flight and submitted_idx < len(stock_codes):
                            code = stock_codes[submitted_idx]
                            fut = executor.submit(
                                self.worker_callable,
                                self.backtest_service.config,
                                code, start_date, end_date, strategy_spec, capital,
                                fee_bps, slippage_bps, execution_price, stop_loss_pct,
                                take_profit_pct, stop_loss_atr_mult, take_profit_atr_mult,
                                sizing_mode, fixed_amount, risk_pct, max_positions,
                                position_sizing, allow_pyramid, allow_reentry,
                                reentry_cooldown_days, enable_limit_up_down,
                                enable_volume_constraint, max_participation_rate
                            )
                            futures[fut] = code
                            pending.add(fut)
                            submitted_idx += 1

                # 當所有 running 任務完全清空退出
                if cancellation_requested:
                    raise BacktestCancelledError("批次回測任務已被使用者取消")

            finally:
                # 只有在未取消時才需要同步等待關閉。若已取消，已呼叫 shutdown(wait=False)
                if not cancellation_requested:
                    executor.shutdown(wait=True)

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

