"""
回測服務 (Backtest Service)
提供回測分析的業務邏輯
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

from app_module.strategy_spec import StrategySpec, StrategyExecutor
from app_module.strategy_registry import StrategyRegistry
from app_module.daily_signal import DailySignalFrame
from app_module.dtos import BacktestReportDTO, ValidationStatus
from app_module.sop_validator import SOPValidator
from backtest_module.broker_simulator import BrokerSimulator, BrokerConfig
from backtest_module.performance_metrics import PerformanceAnalyzer

if TYPE_CHECKING:
    from app_module.walkforward_service import WalkForwardResult


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
        walkforward_results: Optional[List['WalkForwardResult']] = None,
        enable_overfitting_risk: bool = True,
        changed_layers: Optional[List[str]] = None,
        walkforward_executed: bool = False
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
            df, actual_start_date, actual_end_date = self._load_stock_data(stock_code, start_date, end_date)
            
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
        if actual_start_date != start_date or actual_end_date != end_date:
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
            
            signal_frame = executor.generate_signals(df, strategy_spec)
        except Exception as e:
            return self._create_empty_report(f"生成信號失敗: {str(e)}")
        
        if signal_frame is None or len(signal_frame) == 0:
            return self._create_empty_report("未生成任何信號")
        
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
            trades, equity_curve = broker.run(signal_frame, capital)
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
            baseline_result = analyzer.calculate_buy_hold_return(
                df=df,
                start_date=actual_start_date,
                end_date=actual_end_date
            )
            
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
                'final_equity': equity_curve['equity'].iloc[-1],
                'profit_factor': metrics.profit_factor,
                'avg_win': metrics.avg_win,
                'avg_loss': metrics.avg_loss,
                'largest_win': metrics.largest_win,
                'largest_loss': metrics.largest_loss,
                'equity_curve': equity_curve,
                'trade_list': trade_list,
                'can_promote': validation_result['can_promote']  # 記錄是否可以 Promote
            }
        )
    
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
            return None
    
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
        walkforward_results: Optional[List['WalkForwardResult']] = None
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
        """
        創建空報告（用於錯誤情況）
        
        Args:
            error_message: 錯誤訊息
        
        Returns:
            空的 BacktestReportDTO
        """
        return BacktestReportDTO(
            total_return=0.0,
            annual_return=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            total_trades=0,
            expectancy=0.0,
            baseline_comparison=None,
            overfitting_risk=None,
            # Phase 3.5 SOP 護欄欄位（錯誤情況直接標記為 FAIL）
            changed_layers=[],
            validation_status=ValidationStatus.FAIL,
            sample_insufficient_flags={'error': True},
            validation_messages=[f"❌ 錯誤：{error_message}"],
            details={
                'error': error_message,
                'equity_curve': pd.DataFrame(),
                'trade_list': pd.DataFrame(),
                'can_promote': False
            }
        )
