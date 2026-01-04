"""
績效指標計算
計算回測績效指標、生成權益曲線、交易明細
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from backtest_module.broker_simulator import Trade


@dataclass
class PerformanceMetrics:
    """績效指標"""
    total_return: float  # 總報酬率
    annual_return: float  # 年化報酬率 (CAGR)
    sharpe_ratio: float  # 夏普比率
    max_drawdown: float  # 最大回撤
    win_rate: float  # 勝率
    total_trades: int  # 總交易次數
    expectancy: float  # 期望值（平均報酬）
    profit_factor: float  # 獲利因子（總獲利/總虧損）
    avg_win: float  # 平均獲利
    avg_loss: float  # 平均虧損
    largest_win: float  # 最大獲利
    largest_loss: float  # 最大虧損


class PerformanceAnalyzer:
    """績效分析器"""
    
    def __init__(self, risk_free_rate: float = 0.0):
        """
        初始化績效分析器
        
        Args:
            risk_free_rate: 無風險利率（年化）
        """
        self.risk_free_rate = risk_free_rate
    
    def summarize(
        self,
        trades: List[Trade],
        equity_curve: pd.DataFrame,
        initial_capital: float
    ) -> PerformanceMetrics:
        """
        計算績效指標
        
        Args:
            trades: 交易列表
            equity_curve: 權益曲線 DataFrame
            initial_capital: 初始資金
        
        Returns:
            PerformanceMetrics 對象
        """
        # 計算總報酬率（確保是數值類型）
        try:
            final_equity = float(equity_curve['equity'].iloc[-1])
            initial_capital_float = float(initial_capital)
            total_return = (final_equity - initial_capital_float) / initial_capital_float if initial_capital_float > 0 else 0.0
            total_return = float(total_return) if not pd.isna(total_return) else 0.0
        except (ValueError, TypeError, IndexError):
            total_return = 0.0
        
        # 計算年化報酬率 (CAGR)
        try:
            days = (equity_curve.index[-1] - equity_curve.index[0]).days
            years = days / 365.25
            if years > 0:
                annual_return = (final_equity / initial_capital_float) ** (1 / years) - 1
                annual_return = float(annual_return) if not pd.isna(annual_return) else 0.0
            else:
                annual_return = 0.0
        except (ValueError, TypeError, IndexError, ZeroDivisionError):
            annual_return = 0.0
        
        # 計算收益率序列
        try:
            returns = pd.to_numeric(equity_curve['equity'], errors='coerce').pct_change().dropna()
        except Exception:
            returns = pd.Series(dtype=float)
        
        # 計算夏普比率
        try:
            if len(returns) > 0 and returns.std() > 0:
                excess_returns = returns - (self.risk_free_rate / 252)  # 日無風險利率
                sharpe_ratio = np.sqrt(252) * excess_returns.mean() / returns.std()
                sharpe_ratio = float(sharpe_ratio) if not pd.isna(sharpe_ratio) else 0.0
            else:
                sharpe_ratio = 0.0
        except Exception:
            sharpe_ratio = 0.0
        
        # 計算最大回撤
        try:
            equity_series = pd.to_numeric(equity_curve['equity'], errors='coerce').dropna()
            if len(equity_series) > 0:
                max_drawdown = self._calculate_max_drawdown(equity_series)
                max_drawdown = float(max_drawdown) if not pd.isna(max_drawdown) else 0.0
            else:
                max_drawdown = 0.0
        except Exception:
            max_drawdown = 0.0
        
        # 計算交易統計
        trade_stats = self._analyze_trades(trades, initial_capital)
        
        # ✅ 確保所有返回值都是數值類型
        return PerformanceMetrics(
            total_return=float(total_return),
            annual_return=float(annual_return),
            sharpe_ratio=float(sharpe_ratio),
            max_drawdown=float(max_drawdown),
            win_rate=trade_stats['win_rate'],
            total_trades=trade_stats['total_trades'],
            expectancy=trade_stats['expectancy'],
            profit_factor=trade_stats['profit_factor'],
            avg_win=trade_stats['avg_win'],
            avg_loss=trade_stats['avg_loss'],
            largest_win=trade_stats['largest_win'],
            largest_loss=trade_stats['largest_loss']
        )
    
    def _calculate_max_drawdown(self, equity: pd.Series) -> float:
        """
        計算最大回撤
        
        Args:
            equity: 權益序列
        
        Returns:
            最大回撤（負數）
        """
        if len(equity) == 0:
            return 0.0
        
        # 計算累積最高點
        cummax = equity.cummax()
        
        # 計算回撤
        drawdown = (equity - cummax) / cummax
        
        # 返回最大回撤（負數）
        return drawdown.min()
    
    def _analyze_trades(self, trades: List[Trade], initial_capital: float) -> Dict[str, Any]:
        """
        分析交易統計
        
        Args:
            trades: 交易列表
            initial_capital: 初始資金
        
        Returns:
            交易統計字典
        """
        if len(trades) == 0:
            return {
                'win_rate': 0.0,
                'total_trades': 0,
                'expectancy': 0.0,
                'profit_factor': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'largest_win': 0.0,
                'largest_loss': 0.0
            }
        
        # 配對買賣交易
        trade_pairs = []
        buy_trade = None
        
        for trade in trades:
            if trade.type == 'buy':
                buy_trade = trade
            elif trade.type == 'sell' and buy_trade is not None:
                # 計算報酬
                profit = trade.value - buy_trade.value - buy_trade.fee - trade.fee - buy_trade.slippage - trade.slippage
                return_pct = profit / buy_trade.value if buy_trade.value > 0 else 0.0
                
                trade_pairs.append({
                    'entry_date': buy_trade.date,
                    'exit_date': trade.date,
                    'entry_price': buy_trade.price,
                    'exit_price': trade.price,
                    'shares': trade.shares,
                    'profit': profit,
                    'return_pct': return_pct,
                    'reason_tags': trade.reason_tags,
                    'holding_days': (trade.date - buy_trade.date).days
                })
                buy_trade = None
        
        if len(trade_pairs) == 0:
            return {
                'win_rate': 0.0,
                'total_trades': 0,
                'expectancy': 0.0,
                'profit_factor': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'largest_win': 0.0,
                'largest_loss': 0.0
            }
        
        # 計算統計指標
        profits = [t['profit'] for t in trade_pairs]
        returns = [t['return_pct'] for t in trade_pairs]
        
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p < 0]
        
        win_rate = len(wins) / len(trade_pairs) if len(trade_pairs) > 0 else 0.0
        expectancy = np.mean(returns) if len(returns) > 0 else 0.0
        
        total_profit = sum(wins) if wins else 0.0
        total_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = total_profit / total_loss if total_loss > 0 else (total_profit if total_profit > 0 else 0.0)
        
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        largest_win = max(wins) if wins else 0.0
        largest_loss = min(losses) if losses else 0.0
        
        return {
            'win_rate': win_rate,
            'total_trades': len(trade_pairs),
            'expectancy': expectancy,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'largest_win': largest_win,
            'largest_loss': largest_loss,
            'trade_pairs': trade_pairs  # 保留交易配對用於詳細報告
        }
    
    def create_trade_list(self, trades: List[Trade], initial_capital: float) -> pd.DataFrame:
        """
        創建交易明細 DataFrame
        
        Args:
            trades: 交易列表
            initial_capital: 初始資金
        
        Returns:
            交易明細 DataFrame
        """
        trade_pairs = []
        buy_trade = None
        
        for trade in trades:
            if trade.type == 'buy':
                buy_trade = trade
            elif trade.type == 'sell' and buy_trade is not None:
                profit = trade.value - buy_trade.value - buy_trade.fee - trade.fee - buy_trade.slippage - trade.slippage
                return_pct = profit / buy_trade.value if buy_trade.value > 0 else 0.0
                
                trade_pairs.append({
                    '進場日期': buy_trade.date,
                    '出場日期': trade.date,
                    '進場價格': buy_trade.price,
                    '出場價格': trade.price,
                    '股數': trade.shares,
                    '報酬': profit,
                    '報酬率%': return_pct * 100,
                    '持有天數': (trade.date - buy_trade.date).days,
                    '理由標籤': trade.reason_tags
                })
                buy_trade = None
        
        if len(trade_pairs) == 0:
            return pd.DataFrame(columns=['進場日期', '出場日期', '進場價格', '出場價格', '股數', '報酬', '報酬率%', '持有天數', '理由標籤'])
        
        return pd.DataFrame(trade_pairs)
    
    def calculate_buy_hold_return(
        self,
        df: pd.DataFrame,
        start_date: str,
        end_date: str
    ) -> Dict[str, float]:
        """
        計算 Buy & Hold 策略的報酬率
        
        Args:
            df: 股票價格數據（必須包含 '收盤價' 欄位或 'Close' 欄位）
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
        
        Returns:
            包含總報酬率、年化報酬率、最大回撤等指標的字典
        """
        # 確定收盤價欄位名稱
        close_col = '收盤價' if '收盤價' in df.columns else 'Close'
        if close_col not in df.columns:
            raise ValueError(f"數據中找不到收盤價欄位（'收盤價' 或 'Close'）")
        
        # 過濾日期範圍
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        # 確保索引是日期類型
        if not isinstance(df.index, pd.DatetimeIndex):
            if '日期' in df.columns:
                df = df.set_index('日期')
            elif 'Date' in df.columns:
                df = df.set_index('Date')
            else:
                raise ValueError("無法確定日期索引")
        
        df_filtered = df.loc[start_dt:end_dt]
        
        if len(df_filtered) == 0:
            return {
                'total_return': 0.0,
                'annualized_return': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0
            }
        
        # 取得開始和結束價格（確保是數值類型）
        start_price = df_filtered[close_col].iloc[0]
        end_price = df_filtered[close_col].iloc[-1]
        
        # ✅ 確保價格是數值類型
        try:
            start_price = float(start_price)
            end_price = float(end_price)
        except (ValueError, TypeError) as e:
            # 如果轉換失敗，返回默認值
            return {
                'total_return': 0.0,
                'annualized_return': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0
            }
        
        # 計算總報酬率
        total_return = (end_price - start_price) / start_price if start_price > 0 else 0.0
        
        # ✅ 確保 total_return 是數值類型
        total_return = float(total_return) if not pd.isna(total_return) else 0.0
        
        # 計算年化報酬率
        days = (end_dt - start_dt).days
        years = days / 365.25 if days > 0 else 1.0
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
        annualized_return = float(annualized_return) if not pd.isna(annualized_return) else 0.0
        
        # 計算最大回撤
        equity_series = df_filtered[close_col]
        # ✅ 確保 equity_series 是數值類型
        try:
            equity_series = pd.to_numeric(equity_series, errors='coerce')
            equity_series = equity_series.dropna()
            if len(equity_series) == 0:
                max_drawdown = 0.0
            else:
                max_drawdown = self._calculate_max_drawdown(equity_series)
                max_drawdown = float(max_drawdown) if not pd.isna(max_drawdown) else 0.0
        except Exception:
            max_drawdown = 0.0
        
        # 計算 Sharpe Ratio（使用日報酬率）
        try:
            equity_series_numeric = pd.to_numeric(df_filtered[close_col], errors='coerce').dropna()
            returns = equity_series_numeric.pct_change().dropna()
            if len(returns) > 0 and returns.std() > 0:
                excess_returns = returns - (self.risk_free_rate / 252)
                sharpe_ratio = np.sqrt(252) * excess_returns.mean() / returns.std()
                sharpe_ratio = float(sharpe_ratio) if not pd.isna(sharpe_ratio) else 0.0
            else:
                sharpe_ratio = 0.0
        except Exception:
            sharpe_ratio = 0.0
        
        # ✅ 確保所有返回值都是數值類型
        return {
            'total_return': float(total_return),
            'annualized_return': float(annualized_return),
            'max_drawdown': float(max_drawdown),
            'sharpe_ratio': float(sharpe_ratio)
        }
    
    def calculate_baseline_comparison(
        self,
        strategy_returns: float,
        strategy_sharpe: float,
        strategy_max_drawdown: float,
        baseline_returns: float,
        baseline_sharpe: float,
        baseline_max_drawdown: float
    ) -> Dict[str, Any]:
        """
        計算策略相對於 Baseline 的對比結果
        
        Args:
            strategy_returns: 策略總報酬率
            strategy_sharpe: 策略 Sharpe Ratio
            strategy_max_drawdown: 策略最大回撤
            baseline_returns: Baseline 總報酬率
            baseline_sharpe: Baseline Sharpe Ratio
            baseline_max_drawdown: Baseline 最大回撤
        
        Returns:
            包含對比結果的字典（超額報酬率、相對 Sharpe、相對回撤等）
        """
        # ✅ 確保所有參數都是數值類型（更嚴格的轉換）
        try:
            # 先轉換為字符串再轉換為 float，處理可能的混合類型
            strategy_returns = float(str(strategy_returns).replace(',', '')) if strategy_returns is not None else 0.0
            strategy_sharpe = float(str(strategy_sharpe).replace(',', '')) if strategy_sharpe is not None else 0.0
            strategy_max_drawdown = float(str(strategy_max_drawdown).replace(',', '')) if strategy_max_drawdown is not None else 0.0
            baseline_returns = float(str(baseline_returns).replace(',', '')) if baseline_returns is not None else 0.0
            baseline_sharpe = float(str(baseline_sharpe).replace(',', '')) if baseline_sharpe is not None else 0.0
            baseline_max_drawdown = float(str(baseline_max_drawdown).replace(',', '')) if baseline_max_drawdown is not None else 0.0
            
            # 檢查是否為 NaN 或 Inf
            if pd.isna(strategy_returns) or np.isinf(strategy_returns):
                strategy_returns = 0.0
            if pd.isna(strategy_sharpe) or np.isinf(strategy_sharpe):
                strategy_sharpe = 0.0
            if pd.isna(strategy_max_drawdown) or np.isinf(strategy_max_drawdown):
                strategy_max_drawdown = 0.0
            if pd.isna(baseline_returns) or np.isinf(baseline_returns):
                baseline_returns = 0.0
            if pd.isna(baseline_sharpe) or np.isinf(baseline_sharpe):
                baseline_sharpe = 0.0
            if pd.isna(baseline_max_drawdown) or np.isinf(baseline_max_drawdown):
                baseline_max_drawdown = 0.0
        except (ValueError, TypeError) as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Baseline 對比計算參數類型轉換失敗: {e}, 使用默認值 0.0")
            # 如果轉換失敗，使用默認值
            strategy_returns = 0.0
            strategy_sharpe = 0.0
            strategy_max_drawdown = 0.0
            baseline_returns = 0.0
            baseline_sharpe = 0.0
            baseline_max_drawdown = 0.0
        
        # 計算超額報酬率
        excess_returns = float(strategy_returns) - float(baseline_returns)
        
        # 計算相對 Sharpe
        relative_sharpe = float(strategy_sharpe) - float(baseline_sharpe)
        
        # 計算相對回撤（策略回撤 - Baseline 回撤，負數表示策略回撤更小）
        relative_drawdown = float(strategy_max_drawdown) - float(baseline_max_drawdown)
        
        # 判斷是否優於 Baseline（策略報酬率 > Baseline 報酬率）
        outperforms = float(strategy_returns) > float(baseline_returns)
        
        return {
            'baseline_type': 'buy_hold',
            'baseline_returns': baseline_returns,
            'baseline_sharpe': baseline_sharpe,
            'baseline_max_drawdown': baseline_max_drawdown,
            'excess_returns': excess_returns,
            'relative_sharpe': relative_sharpe,
            'relative_drawdown': relative_drawdown,
            'outperforms': outperforms
        }
    
    def calculate_walkforward_degradation(
        self,
        train_performance: Dict[str, float],
        test_performance: Dict[str, float]
    ) -> float:
        """
        計算 Walk-Forward 退化程度
        
        計算測試期表現相對於訓練期的退化程度。退化程度越大，表示策略在樣本外表現越差。
        
        Args:
            train_performance: 訓練期績效指標（包含 sharpe_ratio, total_return 等）
            test_performance: 測試期績效指標
        
        Returns:
            退化程度（0.0 - 1.0）
            - 0.0：無退化（測試期優於或等於訓練期）
            - 1.0：完全退化（測試期表現為 0）
        """
        # 優先使用 Sharpe Ratio 作為主要指標
        train_sharpe = train_performance.get('sharpe_ratio', 0.0)
        test_sharpe = test_performance.get('sharpe_ratio', 0.0)
        
        # 如果 Sharpe Ratio 為 0 或不存在，使用總報酬率
        if train_sharpe == 0.0:
            train_metric = train_performance.get('total_return', 0.0)
            test_metric = test_performance.get('total_return', 0.0)
        else:
            train_metric = train_sharpe
            test_metric = test_sharpe
        
        # 處理除零錯誤（訓練期指標為 0 的情況）
        if abs(train_metric) < 1e-10:
            # 如果訓練期指標為 0，無法計算退化程度，返回 0（視為無退化）
            return 0.0
        
        # 計算退化程度：degradation = (train_metric - test_metric) / abs(train_metric)
        degradation = (train_metric - test_metric) / abs(train_metric)
        
        # 如果退化為負數（測試期優於訓練期），視為 0（無退化）
        if degradation < 0:
            degradation = 0.0
        
        # 限制返回值範圍在 0.0 - 1.0 之間
        return min(max(degradation, 0.0), 1.0)
    
    def calculate_consistency(
        self,
        fold_performances: List[Dict[str, float]]
    ) -> Optional[float]:
        """
        計算 Walk-Forward 一致性
        
        計算多個 Fold 之間表現的一致性。一致性越高，表示策略在不同市場環境下表現穩定。
        
        Args:
            fold_performances: 多個 Fold 的績效指標列表
        
        Returns:
            一致性標準差（0.0 - 1.0），如果 Fold 數量不足則返回 None
            - 0.0：完全一致（理想）
            - 1.0：極度不一致（高風險）
        """
        # 如果 Fold 數量 < 2，返回 None
        if len(fold_performances) < 2:
            return None
        
        # 提取所有 Fold 的 Sharpe Ratio
        sharpe_ratios = []
        for fold_perf in fold_performances:
            sharpe = fold_perf.get('sharpe_ratio', 0.0)
            sharpe_ratios.append(sharpe)
        
        # 如果所有 Sharpe Ratio 都為 0，使用總報酬率
        if all(s == 0.0 for s in sharpe_ratios):
            sharpe_ratios = [fold_perf.get('total_return', 0.0) for fold_perf in fold_performances]
        
        # 計算標準差
        if len(sharpe_ratios) < 2:
            return None
        
        std_dev = np.std(sharpe_ratios)
        
        # 標準差可能很大，需要正規化到 0.0 - 1.0 範圍
        # 使用絕對值並限制範圍
        normalized_std = min(abs(std_dev), 1.0)
        
        return normalized_std
    
    def calculate_overfitting_risk(
        self,
        degradation: Optional[float] = None,
        consistency_std: Optional[float] = None,
        parameter_sensitivity: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        計算過擬合風險
        
        整合多個風險指標，計算整體過擬合風險等級、風險分數，並生成警告與建議。
        
        Args:
            degradation: Walk-Forward 退化程度（0.0 - 1.0）
            consistency_std: 一致性標準差（0.0 - 1.0）
            parameter_sensitivity: 參數敏感性（0.0 - 1.0，可選）
        
        Returns:
            過擬合風險字典，包含：
            - risk_level: 'low' | 'medium' | 'high'
            - risk_score: 0.0 - 10.0
            - metrics: 各項指標值
            - warnings: 警告訊息列表（繁體中文）
            - recommendations: 改善建議列表（繁體中文）
            - missing_data: 缺少的資料來源列表
        """
        # 初始化指標字典
        metrics = {
            'parameter_sensitivity': parameter_sensitivity,
            'degradation': degradation,
            'consistency_std': consistency_std
        }
        
        # 追蹤缺少的資料
        missing_data = []
        if parameter_sensitivity is None:
            missing_data.append('參數最佳化結果')
        if degradation is None:
            missing_data.append('Walk-Forward 結果')
        if consistency_std is None:
            missing_data.append('Walk-Forward 多個 Fold 結果')
        
        # 計算風險分數（0.0 - 10.0）
        risk_score = 0.0
        
        # 參數敏感性（0-2 分）
        if parameter_sensitivity is not None:
            if parameter_sensitivity >= 0.30:
                risk_score += 2.0
            elif parameter_sensitivity >= 0.15:
                risk_score += 1.0
        
        # 退化程度（0-2 分）
        if degradation is not None:
            if degradation >= 0.40:
                risk_score += 2.0
            elif degradation >= 0.20:
                risk_score += 1.0
        
        # 一致性（0-2 分）
        if consistency_std is not None:
            if consistency_std >= 0.50:
                risk_score += 2.0
            elif consistency_std >= 0.30:
                risk_score += 1.0
        
        # 限制最大值為 10.0
        risk_score = min(risk_score, 10.0)
        
        # 判斷風險等級
        if risk_score >= 4.0:
            risk_level = 'high'
        elif risk_score >= 2.0:
            risk_level = 'medium'
        else:
            risk_level = 'low'
        
        # 生成警告訊息
        warnings = []
        if degradation is not None and degradation >= 0.40:
            warnings.append(f"Walk-Forward 退化程度過高（{degradation:.1%}），策略在樣本外表現明顯下降")
        elif degradation is not None and degradation >= 0.20:
            warnings.append(f"Walk-Forward 退化程度中等（{degradation:.1%}），建議進一步驗證策略穩健性")
        
        if consistency_std is not None and consistency_std >= 0.50:
            warnings.append(f"Walk-Forward 一致性較差（標準差 {consistency_std:.2f}），策略在不同市場環境下表現不穩定")
        elif consistency_std is not None and consistency_std >= 0.30:
            warnings.append(f"Walk-Forward 一致性中等（標準差 {consistency_std:.2f}），建議增加測試 Fold 數量")
        
        if parameter_sensitivity is not None and parameter_sensitivity >= 0.30:
            warnings.append(f"參數敏感性過高（{parameter_sensitivity:.1%}），策略可能過度依賴特定參數組合")
        elif parameter_sensitivity is not None and parameter_sensitivity >= 0.15:
            warnings.append(f"參數敏感性中等（{parameter_sensitivity:.1%}），建議進行參數穩健性測試")
        
        # 生成改善建議
        recommendations = []
        if risk_level == 'high':
            recommendations.append("策略過擬合風險較高，建議：")
            recommendations.append("1. 增加訓練樣本數量或使用更長的歷史數據")
            recommendations.append("2. 簡化策略邏輯，減少參數數量")
            recommendations.append("3. 進行更多樣本外測試（Walk-Forward 驗證）")
            recommendations.append("4. 考慮使用參數穩健性測試（參數網格搜索）")
        elif risk_level == 'medium':
            recommendations.append("策略過擬合風險中等，建議：")
            recommendations.append("1. 進行更多 Walk-Forward 驗證以確認策略穩健性")
            recommendations.append("2. 考慮簡化策略邏輯或減少參數依賴")
            recommendations.append("3. 在實盤前進行小額測試")
        else:
            recommendations.append("策略過擬合風險較低，但建議：")
            recommendations.append("1. 持續監控策略在實盤中的表現")
            recommendations.append("2. 定期進行 Walk-Forward 驗證")
        
        if missing_data:
            recommendations.append(f"缺少以下資料來源：{', '.join(missing_data)}，建議補充以獲得更完整的風險評估")
        
        return {
            'risk_level': risk_level,
            'risk_score': risk_score,
            'metrics': metrics,
            'warnings': warnings,
            'recommendations': recommendations,
            'missing_data': missing_data
        }

