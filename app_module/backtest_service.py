"""
回測服務 (Backtest Service)
提供回測分析的業務邏輯
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Callable
from datetime import date, datetime
from pathlib import Path
import logging
from decimal import Decimal, InvalidOperation
from dataclasses import replace
import sqlite3
from app_module.recommendation_portfolio_dates import parse_stock_dates

logger = logging.getLogger(__name__)

from app_module.strategy_spec import StrategySpec, StrategyExecutor
from app_module.strategy_registry import StrategyRegistry
from app_module.daily_signal import DailySignalFrame
from app_module.dtos import BacktestReportDTO, ValidationStatus
from app_module.sop_validator import SOPValidator
from backtest_module.broker_simulator import BrokerSimulator, BrokerConfig, NEXT_OPEN_CONTRACT, LEGACY_CLOSE_CONTRACT
from backtest_module.performance_metrics import PerformanceAnalyzer
from decision_module.factors.factor_adapters import build_technical_total_score_factor
from decision_module.factors.factor_dtos import FactorRecord
from app_module.backtest_report_support import create_empty_report, date_from_index, factor_decision_date, score_factor_records
from app_module.backtest_contracts import WalkForwardResultContract
from app_module.exceptions import BacktestCancelledError


class BacktestService:
    """回測服務類"""
    
    def __init__(self, config):
        """
        初始化回測服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.sop_validator = SOPValidator()  # Phase 3.5 SOP 驗證器
    
    def run_backtest(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        strategy_spec: StrategySpec,
        strategy_executor: Optional[StrategyExecutor] = None,
        capital: float = 1000000.0,
        fee_bps: float = 14.25,
        slippage_bps: float = 5.0,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        stop_loss_atr_mult: Optional[float] = None,
        take_profit_atr_mult: Optional[float] = None,
        execution_price: str = "next_open",
        sizing_mode: str = "全倉",
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
        preloaded_data: Optional[pd.DataFrame] = None,
        actual_start_date: Optional[str] = None,
        actual_end_date: Optional[str] = None,
        walkforward_results: Optional[List[WalkForwardResultContract]] = None,
        enable_overfitting_risk: bool = True,
        changed_layers: Optional[List[str]] = None,
        walkforward_executed: bool = False,
        signal_context_start_date: Optional[str] = None,
        check_cancel: Callable[[], bool] | None = None,
    ) -> BacktestReportDTO:
        """
        執行回測
        
        Args:
            stock_code: 股票代號
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            strategy_spec: 策略規格
            strategy_executor: 策略執行器
            capital: 初始資金
            fee_bps: 手續費（基點）
            slippage_bps: 滑價（基點）
            stop_loss_pct: 停損百分比（可選）
            take_profit_pct: 停利百分比（可選）
            sizing_mode: 部位 sizing 模式（"全倉"/"固定金額"/"風險百分比"）
            fixed_amount: 固定金額（當 sizing_mode="固定金額" 時使用）
            risk_pct: 風險百分比（當 sizing_mode="風險百分比" 時使用）
            enable_limit_up_down: 啟用漲跌停限制
            enable_volume_constraint: 啟用成交量約束
            max_participation_rate: 最大參與率（0.05 = 5%）
            changed_layers: 本次研究中被修改的層級（Phase 3.5 SOP 護欄）
            walkforward_executed: 是否已執行 Walk-Forward 驗證（Phase 3.5 SOP 護欄）
            signal_context_start_date: 產生訊號時可讀取的歷史起點；撮合仍從 start_date 開始
        
        Returns:
            BacktestReportDTO: 回測報告
        """
        # 1. 載入股票數據和技術指標（自動調整日期範圍）
        # ✅ 優化：如果提供了預載入的數據，直接使用
        if preloaded_data is not None:
            df = preloaded_data
            # 使用提供的實際日期範圍，或從數據中推斷
            if actual_start_date is None:
                actual_start_date = df.index.min().strftime('%Y-%m-%d')
            if actual_end_date is None:
                actual_end_date = df.index.max().strftime('%Y-%m-%d')
            logger.debug(f"[BacktestService] 使用預載入的數據（股票 {stock_code}，共 {len(df)} 筆）")
        else:
            load_start_date = signal_context_start_date or start_date
            df, actual_start_date, actual_end_date = self._load_stock_data(
                stock_code,
                load_start_date,
                end_date,
            )
            
            if df is None or len(df) == 0:
                # 提供更詳細的錯誤信息
                error_msg = f"無法載入股票數據\n"
                error_msg += f"股票代號: {stock_code}\n"
                error_msg += f"日期範圍: {start_date} 到 {end_date}\n"
                error_msg += f"請確認:\n"
                error_msg += f"1. stock_data_whole.csv 是否存在\n"
                error_msg += f"2. 股票代號是否正確\n"
                error_msg += f"3. 日期範圍內是否有數據"
                return self._create_empty_report(error_msg)
        
        # ✅ 記錄日期調整信息（只在第一次載入時顯示）
        date_adjusted_msg = None
        if (
            signal_context_start_date is None
            and (actual_start_date != start_date or actual_end_date != end_date)
        ):
            date_adjusted_msg = f"日期範圍已自動調整: 請求 {start_date}~{end_date} → 實際 {actual_start_date}~{actual_end_date}"
            if preloaded_data is None:  # 只在第一次載入時顯示警告
                logger.warning(f"[BacktestService] {date_adjusted_msg}")
        
        # 2. 使用 StrategyRegistry 獲取策略執行器
        try:
            # 如果傳入的是 executor 實例，直接使用（向後兼容）
            if isinstance(strategy_executor, StrategyExecutor):
                executor = strategy_executor
            else:
                # 否則從 registry 獲取
                executor = StrategyRegistry.get_executor(strategy_spec)
            
            signal_frame = executor.generate_signals(
                df,
                strategy_spec,
                execution_start_date=start_date
                if signal_context_start_date is not None
                else None,
            )
        except Exception as e:
            return self._create_empty_report(f"生成信號失敗: {str(e)}")
        
        if signal_frame is None or len(signal_frame) == 0:
            return self._create_empty_report("未生成任何信號")

        if signal_context_start_date is not None:
            execution_start = pd.to_datetime(start_date)
            execution_end = pd.to_datetime(end_date)
            signal_frame = signal_frame.loc[
                (signal_frame.index >= execution_start)
                & (signal_frame.index <= execution_end)
            ]
            df = df.loc[(df.index >= execution_start) & (df.index <= execution_end)]
            if signal_frame.empty or df.empty:
                return self._create_empty_report("訊號歷史存在，但指定測試期間沒有可撮合資料")
            actual_start_date = df.index.min().strftime("%Y-%m-%d")
            actual_end_date = df.index.max().strftime("%Y-%m-%d")
            if actual_start_date != start_date or actual_end_date != end_date:
                date_adjusted_msg = (
                    f"日期範圍已自動調整: 請求 {start_date}~{end_date} "
                    f"→ 實際 {actual_start_date}~{actual_end_date}"
                )
                logger.warning(f"[BacktestService] {date_adjusted_msg}")
        
        # 3. 使用 BrokerSimulator 執行撮合
        broker_config = BrokerConfig(
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            stop_loss_atr_mult=stop_loss_atr_mult,
            take_profit_atr_mult=take_profit_atr_mult,
            execution_price=execution_price,
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
        broker = BrokerSimulator(broker_config)
        
        try:
            trades, equity_curve = broker.run(signal_frame, capital, check_cancel=check_cancel)
        except InterruptedError as error:
            raise BacktestCancelledError(str(error)) from error
        except Exception as e:
            return self._create_empty_report(f"撮合模擬失敗: {str(e)}")
        
        # 4. 使用 PerformanceAnalyzer 計算績效
        analyzer = PerformanceAnalyzer(risk_free_rate=0.0)
        
        try:
            metrics = analyzer.summarize(trades, equity_curve, capital)
            trade_list = analyzer.create_trade_list(trades, capital)
        except Exception as e:
            return self._create_empty_report(f"績效計算失敗: {str(e)}")
        
        # 5. 計算 Baseline 對比（Buy & Hold）
        baseline_comparison = None
        try:
            # 計算 Buy & Hold Baseline
            if execution_price == "next_open":
                baseline_frame = signal_frame.copy()
                baseline_frame["signal"] = 0
                baseline_frame.iloc[0, baseline_frame.columns.get_loc("signal")] = 1
                baseline_config = replace(broker_config, sizing_mode="all_in", stop_loss_pct=None,
                    take_profit_pct=None, stop_loss_atr_mult=None, take_profit_atr_mult=None,
                    allow_pyramid=False)
                baseline_trades, baseline_equity = BrokerSimulator(baseline_config).run(baseline_frame, capital, check_cancel=check_cancel)
                baseline_metrics = analyzer.summarize(baseline_trades, baseline_equity, capital)
                baseline_result = {"total_return": baseline_metrics.total_return,
                    "sharpe_ratio": baseline_metrics.sharpe_ratio, "max_drawdown": baseline_metrics.max_drawdown}
            else:
                baseline_result = analyzer.calculate_buy_hold_return(
                    df=df, start_date=actual_start_date, end_date=actual_end_date)
            
            # 確保 baseline_result 中的值都是數值類型
            baseline_returns = float(baseline_result.get('total_return', 0.0))
            baseline_sharpe = float(baseline_result.get('sharpe_ratio', 0.0))
            baseline_max_drawdown = float(baseline_result.get('max_drawdown', 0.0))
            
            # 計算 Baseline 對比
            baseline_comparison = analyzer.calculate_baseline_comparison(
                strategy_returns=float(metrics.total_return),
                strategy_sharpe=float(metrics.sharpe_ratio),
                strategy_max_drawdown=float(metrics.max_drawdown),
                baseline_returns=baseline_returns,
                baseline_sharpe=baseline_sharpe,
                baseline_max_drawdown=baseline_max_drawdown
            )
        except InterruptedError as error:
            raise BacktestCancelledError(str(error)) from error
        except Exception as e:
            import traceback
            logger.warning(f"[BacktestService] Baseline 對比計算失敗: {e}")
            logger.debug(f"[BacktestService] Baseline 對比計算失敗詳細信息: {traceback.format_exc()}")
            # Baseline 對比失敗不影響回測報告，僅記錄警告
        
        # 6. 計算過擬合風險（如果啟用且提供了 Walk-Forward 結果）
        overfitting_risk = None
        if enable_overfitting_risk:
            try:
                overfitting_risk = self._calculate_overfitting_risk(
                    analyzer=analyzer,
                    walkforward_results=walkforward_results
                )
            except Exception as e:
                logger.warning(f"[BacktestService] 過擬合風險計算失敗: {e}")
                # 過擬合風險計算失敗不影響回測報告，僅記錄警告
        
        # 7. Phase 3.5 SOP 驗證
        validation_result = self.sop_validator.validate_backtest_result(
            total_trades=metrics.total_trades,
            start_date=actual_start_date,
            end_date=actual_end_date,
            walkforward_results=walkforward_results,
            changed_layers=changed_layers,
            walkforward_executed=walkforward_executed
        )
        
        # 計算策略分數診斷
        strategy_params = strategy_spec.config.get('params', {})
        threshold_mode = strategy_params.get('threshold_mode', 'fixed')
        
        buy_score = strategy_params.get('buy_score', strategy_spec.default_params.get('buy_score', 60.0))
        sell_score = strategy_params.get('sell_score', strategy_spec.default_params.get('sell_score', 40.0))
        
        score_series = signal_frame.get('score', pd.Series(50.0, index=signal_frame.index))
        factor_records = self._build_score_factor_records(
            stock_code=stock_code,
            score_series=score_series,
        )
        factor_decision_date = self._factor_decision_date(signal_frame)
        
        score_diagnostics = {
            'max_score': float(score_series.max()) if not score_series.empty else 50.0,
            'min_score': float(score_series.min()) if not score_series.empty else 50.0,
            'avg_score': float(score_series.mean()) if not score_series.empty else 50.0,
            'total_days': int(len(score_series)),
            'threshold_mode': threshold_mode
        }
        
        if threshold_mode == 'fixed':
            score_diagnostics.update({
                'buy_hit_days': int((score_series >= buy_score).sum()),
                'sell_hit_days': int((score_series <= sell_score).sum()),
                'buy_score': float(buy_score),
                'sell_score': float(sell_score)
            })
        else:  # quantile
            warmup_ready_days = int(signal_frame['threshold_warmup_ready'].sum()) if 'threshold_warmup_ready' in signal_frame.columns else 0
            buy_hit_days = int(signal_frame['buy_threshold_hit'].sum()) if 'buy_threshold_hit' in signal_frame.columns else 0
            sell_hit_days = int(signal_frame['sell_threshold_hit'].sum()) if 'sell_threshold_hit' in signal_frame.columns else 0
            
            score_diagnostics.update({
                'buy_quantile_bp': int(strategy_params.get('buy_quantile_bp', 8000)),
                'sell_quantile_bp': int(strategy_params.get('sell_quantile_bp', 4000)),
                'quantile_warmup_observations': int(strategy_params.get('quantile_warmup_observations', 60)),
                'quantile_method': strategy_params.get('quantile_method', 'nearest_rank'),
                'warmup_ready_days': warmup_ready_days,
                'buy_hit_days': buy_hit_days,
                'sell_hit_days': sell_hit_days
            })
        
        # 8. 構建 BacktestReportDTO
        return BacktestReportDTO(
            total_return=metrics.total_return,
            annual_return=metrics.annual_return,
            sharpe_ratio=metrics.sharpe_ratio,
            max_drawdown=metrics.max_drawdown,
            win_rate=metrics.win_rate,
            total_trades=metrics.total_trades,
            expectancy=metrics.expectancy,
            baseline_comparison=baseline_comparison,
            overfitting_risk=overfitting_risk,
            # Phase 3.5 SOP 護欄欄位
            changed_layers=changed_layers if changed_layers else [],
            validation_status=validation_result['validation_status'],
            sample_insufficient_flags=validation_result['sample_insufficient_flags'],
            validation_messages=validation_result['validation_messages'],
            details={
                'stock_code': stock_code,
                'start_date': actual_start_date,  # ✅ 使用實際日期
                'end_date': actual_end_date,  # ✅ 使用實際日期
                'requested_start_date': start_date,  # ✅ 記錄請求的日期
                'requested_end_date': end_date,  # ✅ 記錄請求的日期
                'date_adjusted': date_adjusted_msg,  # ✅ 記錄調整訊息
                'strategy_id': strategy_spec.strategy_id,
                'strategy_version': strategy_spec.strategy_version,
                'initial_capital': capital,
                'execution_price': execution_price,
                'execution_contract': NEXT_OPEN_CONTRACT if execution_price == "next_open" else LEGACY_CLOSE_CONTRACT,
                'data_manifest': {'execution_contract': NEXT_OPEN_CONTRACT if execution_price == "next_open" else LEGACY_CLOSE_CONTRACT},
                'execution_diagnostics': broker.execution_diagnostics,
                'terminal_position': int(equity_curve['position'].iloc[-1]) if 'position' in equity_curve else 0,
                'benchmark_results': {'execution_contract': NEXT_OPEN_CONTRACT if execution_price == "next_open" else LEGACY_CLOSE_CONTRACT,
                    'policy': 'same_costs_next_open_mark_terminal' if execution_price == 'next_open' else 'legacy_close_to_close',
                    'comparison': baseline_comparison},
                'final_equity': equity_curve['equity'].iloc[-1],
                'profit_factor': metrics.profit_factor,
                'avg_win': metrics.avg_win,
                'avg_loss': metrics.avg_loss,
                'largest_win': metrics.largest_win,
                'largest_loss': metrics.largest_loss,
                'equity_curve': equity_curve,
                'trade_list': trade_list,
                'factor_records': factor_records,
                'factor_decision_date': factor_decision_date,
                'can_promote': validation_result['can_promote'],  # 記錄是否可以 Promote
                'score_diagnostics': score_diagnostics
            }
        )
    
    def load_recommendation_portfolio_history(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        """應用層唯讀載入研究切片；保留開盤與量，不初始化 DB writer。"""
        if self.config is None:
            raise ValueError("配置未初始化")
        if getattr(self.config, "use_sqlite", False):
            path = Path(self.config.db_file).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"市場 SQLite 不存在：{path}")
            connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            try:
                connection.execute("PRAGMA query_only=ON")
                clauses, params = [], []
                if start_date:
                    clauses.append("REPLACE(CAST(日期 AS TEXT), '-', '') >= ?")
                    params.append((pd.Timestamp(start_date) - pd.Timedelta(days=365)).strftime("%Y%m%d"))
                if end_date:
                    clauses.append("REPLACE(CAST(日期 AS TEXT), '-', '') <= ?")
                    params.append(pd.Timestamp(end_date).strftime("%Y%m%d"))
                query = "SELECT * FROM daily_prices"
                if clauses:
                    query += " WHERE " + " AND ".join(clauses)
                history = pd.read_sql_query(query, connection, params=params)
            finally:
                connection.close()
        else:
            csv_path = next((Path(p) for p in (self.config.all_stocks_data_file, self.config.stock_data_file) if Path(p).is_file()), None)
            if csv_path is None:
                raise FileNotFoundError("找不到歷史資料檔")
            history = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False, dtype={"證券代號": str, "股票代號": str})
        aliases = {"股票代號": "證券代號", "股票名稱": "證券名稱", "Close": "收盤價", "Open": "開盤價"}
        history = history.rename(columns={old: new for old, new in aliases.items() if new not in history.columns})
        if not {"日期", "證券代號", "收盤價"}.issubset(history.columns):
            raise ValueError("歷史資料缺少日期、證券代號或收盤價")
        history["日期"] = parse_stock_dates(history["日期"])
        if history["日期"].isna().any():
            raise ValueError("歷史日期不可解析")
        history["證券代號"] = history["證券代號"].astype(str).str.strip()
        if start_date:
            history = history[history["日期"] >= pd.Timestamp(start_date) - pd.Timedelta(days=365)]
        if end_date:
            history = history[history["日期"] <= pd.Timestamp(end_date)]
        return history.sort_values(["日期", "證券代號"]).reset_index(drop=True)

    def _build_score_factor_records(
        self,
        *,
        stock_code: str,
        score_series: pd.Series,
    ) -> list[FactorRecord]:
        return score_factor_records(stock_code, score_series)

    def _factor_decision_date(self, signal_frame: pd.DataFrame) -> date | None:
        return factor_decision_date(signal_frame)

    def _date_from_index(self, value: Any) -> date | None:
        return date_from_index(value)

    def _load_stock_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> tuple[Optional[pd.DataFrame], str, str]:
        """
        載入股票數據和技術指標（自動調整日期範圍）
        
        Args:
            stock_code: 股票代號
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
        
        Returns:
            tuple: (合併後的 DataFrame, 實際開始日期, 實際結束日期)
        """
        try:
            # 1. 載入價格數據
            price_df = self._load_price_data(stock_code, start_date, end_date)
            if price_df is None or len(price_df) == 0:
                logger.warning(f"[BacktestService] 無法載入價格數據（股票 {stock_code}，日期範圍 {start_date} 到 {end_date}）")
                return None, start_date, end_date
            
            # 2. 載入技術指標數據
            indicator_df = self._load_indicator_data(stock_code, start_date, end_date)
            
            # 3. 合併數據
            if indicator_df is not None and len(indicator_df) > 0:
                # 確保日期索引一致
                if '日期' in indicator_df.columns:
                    indicator_df = indicator_df.set_index('日期')
                
                # 合併（以價格數據為主）
                df = price_df.join(indicator_df, how='left', rsuffix='_indicator')
            else:
                # 如果沒有技術指標數據，只使用價格數據（仍然可以回測）
                logger.warning(f"[BacktestService] 警告: 找不到技術指標數據（股票 {stock_code}），將只使用價格數據")
                df = price_df
            
            if len(df) == 0:
                logger.warning(f"[BacktestService] 合併後數據為空（股票 {stock_code}）")
                return None, start_date, end_date
            
            # 4. ✅ 自動調整日期範圍到實際數據範圍
            actual_start = df.index.min()
            actual_end = df.index.max()
            requested_start = pd.to_datetime(start_date)
            requested_end = pd.to_datetime(end_date)
            
            # 檢查是否需要調整
            date_adjusted = False
            if actual_start > requested_start:
                logger.warning(f"[BacktestService] 請求的開始日期 {start_date} 早於實際數據，調整為 {actual_start.strftime('%Y-%m-%d')}")
                date_adjusted = True
            if actual_end < requested_end:
                logger.warning(f"[BacktestService] 請求的結束日期 {end_date} 晚於實際數據，調整為 {actual_end.strftime('%Y-%m-%d')}")
                date_adjusted = True
            
            # 過濾到實際可用範圍
            df = df[(df.index >= actual_start) & (df.index <= actual_end)]
            
            actual_start_str = actual_start.strftime('%Y-%m-%d')
            actual_end_str = actual_end.strftime('%Y-%m-%d')
            
            if date_adjusted:
                logger.info(f"[BacktestService] ⚠️ 日期範圍已自動調整: 請求 {start_date}~{end_date} → 實際 {actual_start_str}~{actual_end_str}")
            else:
                logger.info(f"[BacktestService] 成功載入數據（股票 {stock_code}，共 {len(df)} 筆，日期範圍 {actual_start_str} 到 {actual_end_str}）")
            
            return df, actual_start_str, actual_end_str
            
        except Exception as e:
            import traceback
            logger.error(f"[BacktestService] 載入數據失敗（股票 {stock_code}）: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None, start_date, end_date
    
    def _load_price_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """
        載入價格數據
        
        Args:
            stock_code: 股票代號
            start_date: 開始日期
            end_date: 結束日期
        
        Returns:
            價格數據 DataFrame
        """
        try:
            # ✅ 新增：如果使用 SQLite，直接從 daily_prices 庫表讀取，提速 270 倍！
            if getattr(self.config, 'use_sqlite', False):
                try:
                    from data_module.db_manager import DBManager
                    db = DBManager(self.config)
                    
                    # 標準化日期格式為 YYYYMMDD 字串以配合 SQLite 主鍵
                    start_date_str = start_date.replace('-', '').replace('/', '')
                    end_date_str = end_date.replace('-', '').replace('/', '')
                    stock_code_str = str(stock_code).strip().zfill(4)
                    
                    sql = """
                        SELECT * FROM daily_prices 
                        WHERE 證券代號 = ? AND 日期 BETWEEN ? AND ? 
                        ORDER BY 日期 ASC;
                    """
                    df = db.execute_query(sql, (stock_code_str, start_date_str, end_date_str))
                    
                    if not df.empty:
                        # 欄位型態轉換以相容原有業務 DTO
                        numeric_cols = ['成交股數', '成交筆數', '成交金額', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差',
                                        '最後揭示買價', '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']
                        for col in numeric_cols:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col], errors='coerce')
                        
                        # 處理日期索引
                        df['日期'] = pd.to_datetime(df['日期'].astype(str), format='%Y%m%d', errors='coerce')
                        df = df[df['日期'].notna()]
                        df = df.set_index('日期').sort_index()
                        
                        logger.info(f"[BacktestService] 成功從 SQLite 高速載入價格數據（股票 {stock_code_str}，共 {len(df)} 筆）")
                        return df

                    logger.warning(f"[BacktestService] SQLite 中找不到股票 {stock_code_str} 於 {start_date_str}~{end_date_str} 的價格資料，將降級讀取 CSV")
                except Exception as sql_err:
                    logger.warning(f"[BacktestService] SQLite 價格資料載入失敗: {sql_err}，將降級讀取 CSV")

            # 讀取 stock_data_whole.csv
            stock_data_file = self.config.stock_data_file
            if not stock_data_file.exists():
                logger.error(f"[BacktestService] 找不到股票數據文件: {stock_data_file}")
                return None
            
            # 讀取數據
            df = pd.read_csv(
                stock_data_file,
                dtype={'證券代號': str},
                low_memory=False
            )
            
            # 檢查欄位
            if '證券代號' not in df.columns:
                logger.error(f"[BacktestService] 找不到 '證券代號' 欄位，可用欄位: {list(df.columns)}")
                return None
            
            # 過濾股票代號（確保格式一致）
            df['證券代號'] = df['證券代號'].astype(str).str.strip()
            stock_code = str(stock_code).strip()
            
            df_filtered = df[df['證券代號'] == stock_code]
            if len(df_filtered) == 0:
                # 提供更詳細的錯誤信息
                available_codes = df['證券代號'].unique()[:10]
                logger.warning(f"[BacktestService] 找不到股票 {stock_code} 的數據")
                logger.warning(f"[BacktestService] 文件路徑: {stock_data_file}")
                logger.warning(f"[BacktestService] 文件總筆數: {len(df)}")
                logger.warning(f"[BacktestService] 文件中的股票代號示例: {list(available_codes)}")
                return None
            
            df = df_filtered
            
            # 處理日期
            if '日期' in df.columns:
                # 先保存原始日期欄位
                date_col = df['日期'].copy()
                
                # 嘗試多種日期格式轉換
                # 1. 嘗試 YYYYMMDD 格式（整數）
                if date_col.dtype in ['int64', 'int32', 'float64']:
                    df['日期'] = pd.to_datetime(date_col.astype(str), errors='coerce', format='%Y%m%d')
                else:
                    # 2. 嘗試字符串格式 YYYYMMDD
                    df['日期'] = pd.to_datetime(date_col.astype(str), errors='coerce', format='%Y%m%d')
                
                # 3. 如果還是失敗，嘗試自動解析
                if df['日期'].isna().any():
                    df['日期'] = pd.to_datetime(date_col, errors='coerce')
                
                # 移除無法解析的日期
                df = df[df['日期'].notna()]
                
                # 過濾日期範圍
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df['日期'] >= start_dt) & (df['日期'] <= end_dt)]
                
                # 設置日期索引
                df = df.set_index('日期').sort_index()
            else:
                logger.error(f"[BacktestService] 找不到日期欄位")
                return None
            
            if len(df) == 0:
                logger.warning(f"[BacktestService] 警告: 日期範圍 {start_date} 到 {end_date} 內沒有價格數據（股票 {stock_code}）")
                logger.warning(f"[BacktestService] 這可能是因為日期範圍過小或數據文件不完整")
                return None
            
            return df
            
        except Exception as e:
            logger.error(f"[BacktestService] 載入價格數據失敗: {e}")
            return None
    
    def _load_indicator_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """
        載入技術指標數據
        
        Args:
            stock_code: 股票代號
            start_date: 開始日期
            end_date: 結束日期
        
        Returns:
            技術指標數據 DataFrame
        """
        try:
            # ✅ 新增：如果使用 SQLite，直接從 technical_indicators 庫表讀取，提速 270 倍！
            if getattr(self.config, 'use_sqlite', False):
                try:
                    from data_module.db_manager import DBManager
                    db = DBManager(self.config)
                    
                    start_date_str = start_date.replace('-', '').replace('/', '')
                    end_date_str = end_date.replace('-', '').replace('/', '')
                    stock_code_str = str(stock_code).strip().zfill(4)
                    
                    sql = """
                        SELECT * FROM technical_indicators 
                        WHERE 證券代號 = ? AND 日期 BETWEEN ? AND ? 
                        ORDER BY 日期 ASC;
                    """
                    df = db.execute_query(sql, (stock_code_str, start_date_str, end_date_str))
                    
                    if not df.empty:
                        # 除了日期與證券代號外，其餘技術指標皆轉為 Float 型態以相容後續策略計算
                        for col in df.columns:
                            if col not in ['日期', '證券代號']:
                                df[col] = pd.to_numeric(df[col], errors='coerce')
                            
                        # 處理日期並排序
                        df['日期'] = pd.to_datetime(df['日期'].astype(str), format='%Y%m%d', errors='coerce')
                        df = df[df['日期'].notna()]
                        
                        logger.info(f"[BacktestService] 成功從 SQLite 高速載入技術指標數據（股票 {stock_code_str}，共 {len(df)} 筆）")
                        return df

                    logger.warning(f"[BacktestService] SQLite 中找不到股票 {stock_code_str} 於 {start_date_str}~{end_date_str} 的技術指標，將降級讀取 CSV")
                except Exception as sql_err:
                    logger.warning(f"[BacktestService] SQLite 技術指標載入失敗: {sql_err}，將降級讀取 CSV")

            # 讀取技術指標文件
            indicator_file = self.config.get_technical_file(stock_code)
            logger.info(f"[BacktestService] 嘗試載入技術指標文件: {indicator_file}")
            logger.info(f"[BacktestService] 文件是否存在: {indicator_file.exists()}")
            
            if not indicator_file.exists():
                logger.warning(f"[BacktestService] 找不到技術指標文件: {indicator_file}")
                logger.warning(f"[BacktestService] 技術指標目錄: {self.config.technical_dir}")
                logger.warning(f"[BacktestService] 技術指標目錄是否存在: {self.config.technical_dir.exists()}")
                return None
            
            # 讀取數據
            df = pd.read_csv(indicator_file, encoding='utf-8-sig')
            logger.info(f"[BacktestService] 成功讀取技術指標文件，共 {len(df)} 筆原始數據")
            
            # 處理日期
            if '日期' in df.columns:
                # ✅ 修復：正確處理 YYYYMMDD 整數格式的日期
                date_col = df['日期'].copy()
                
                # 如果是整數或浮點數，可能是 YYYYMMDD 格式（如 20140407）
                if date_col.dtype in ['int64', 'int32', 'float64']:
                    # 轉換為字符串後使用 YYYYMMDD 格式解析
                    df['日期'] = pd.to_datetime(date_col.astype(str), format='%Y%m%d', errors='coerce')
                else:
                    # 字符串格式，嘗試自動解析
                    df['日期'] = pd.to_datetime(date_col, errors='coerce')
                
                df = df[df['日期'].notna()]
                logger.info(f"[BacktestService] 日期欄位處理後，共 {len(df)} 筆有效數據")
                
                if len(df) > 0:
                    logger.info(f"[BacktestService] 數據日期範圍: {df['日期'].min()} 到 {df['日期'].max()}")
                
                # 過濾日期範圍
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                logger.info(f"[BacktestService] 請求的日期範圍: {start_dt} 到 {end_dt}")
                
                df = df[(df['日期'] >= start_dt) & (df['日期'] <= end_dt)]
                logger.info(f"[BacktestService] 日期範圍過濾後，共 {len(df)} 筆數據")
            else:
                logger.error(f"[BacktestService] 技術指標文件沒有日期欄位，可用欄位: {list(df.columns)}")
                return None
            
            if len(df) == 0:
                logger.warning(f"[BacktestService] 日期範圍內沒有技術指標數據（股票 {stock_code}，日期範圍 {start_date} 到 {end_date}）")
                return None
            
            return df
            
        except Exception as e:
            logger.error(f"[BacktestService] 載入技術指標數據失敗: {e}")
            return None
    
    def _calculate_overfitting_risk(
        self,
        analyzer: PerformanceAnalyzer,
        walkforward_results: Optional[List[WalkForwardResultContract]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        計算過擬合風險
        
        Args:
            analyzer: PerformanceAnalyzer 實例
            walkforward_results: Walk-Forward 結果列表（可選）
        
        Returns:
            過擬合風險字典，如果資料不足則返回 None
        """
        # 如果沒有提供 Walk-Forward 結果，無法計算過擬合風險
        if not walkforward_results or len(walkforward_results) == 0:
            return None
        
        # 計算退化程度（使用第一個 Fold 的結果，或計算平均退化程度）
        degradation = None
        if len(walkforward_results) > 0:
            # 計算平均退化程度
            degradations = []
            for wf_result in walkforward_results:
                fold_degradation = analyzer.calculate_walkforward_degradation(
                    train_performance=wf_result.train_metrics,
                    test_performance=wf_result.test_metrics
                )
                degradations.append(fold_degradation)
            
            if degradations:
                degradation = sum(degradations) / len(degradations)
        
        # 計算一致性（需要至少 2 個 Fold）
        consistency_std = None
        if len(walkforward_results) >= 2:
            # 提取所有 Fold 的測試期績效
            fold_performances = [wf_result.test_metrics for wf_result in walkforward_results]
            consistency_std = analyzer.calculate_consistency(fold_performances)
        
        # 參數敏感性（需要最佳化結果，目前不支援，設為 None）
        parameter_sensitivity = None
        
        # 計算整體過擬合風險
        overfitting_risk = analyzer.calculate_overfitting_risk(
            degradation=degradation,
            consistency_std=consistency_std,
            parameter_sensitivity=parameter_sensitivity
        )
        
        # 添加計算時間
        from datetime import datetime
        overfitting_risk['calculated_at'] = datetime.now().isoformat()
        
        return overfitting_risk
    
    def _create_empty_report(self, error_message: str) -> BacktestReportDTO:
        return create_empty_report(error_message)
