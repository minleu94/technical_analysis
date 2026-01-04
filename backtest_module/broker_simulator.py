"""
撮合模擬器
模擬交易撮合、成本計算、風控
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class BrokerConfig:
    """券商配置"""
    fee_bps: float = 14.25  # 手續費（基點），台股一般 0.1425% = 14.25 bps
    slippage_bps: float = 5.0  # 滑價（基點），假設 0.05%
    # 停損停利（百分比模式）
    stop_loss_pct: Optional[float] = None  # 停損百分比（例如 0.05 = 5%）
    take_profit_pct: Optional[float] = None  # 停利百分比（例如 0.10 = 10%）
    # 停損停利（ATR 倍數模式，優先於百分比模式）
    stop_loss_atr_mult: Optional[float] = None  # 停損 ATR 倍數（例如 2.0 = 2倍ATR）
    take_profit_atr_mult: Optional[float] = None  # 停利 ATR 倍數（例如 3.0 = 3倍ATR）
    atr_period: int = 14  # ATR 週期（用於 ATR-based 停損停利和 risk_based sizing）
    # 執行價格
    execution_price: str = "next_open"  # "next_open"（下一根K開盤）或 "close"（當根K收盤）
    # 市場限制
    enable_limit_up_down: bool = True  # 啟用漲跌停限制
    limit_up_down_pct: float = 0.10  # 漲跌停幅度（台股一般 10%）
    enable_volume_constraint: bool = True  # 啟用成交量約束
    max_participation_rate: float = 0.05  # 最大參與率（例如 5%）
    # 部位 sizing
    sizing_mode: str = "all_in"  # 全倉 / fixed_amount / risk_based
    fixed_amount: Optional[float] = None  # 固定金額（sizing_mode = "fixed_amount"）
    risk_pct: Optional[float] = None  # 風險百分比（sizing_mode = "risk_based"，例如 0.02 = 2%）
    # 部位管理
    max_positions: Optional[int] = None  # 最多同時持有幾檔（None = 不限制）
    position_sizing: str = "equal_weight"  # 等權 / score_weight / volatility_adjusted
    allow_pyramid: bool = False  # 是否允許加碼
    allow_reentry: bool = True  # 是否允許重新進場
    reentry_cooldown_days: int = 0  # 重新進場冷卻期（天數）


@dataclass
class Trade:
    """交易記錄"""
    date: pd.Timestamp
    type: str  # 'buy' 或 'sell'
    price: float  # 成交價格
    shares: int  # 股數
    value: float  # 交易金額
    fee: float  # 手續費
    slippage: float  # 滑價成本
    reason_tags: str  # 理由標籤（逗號分隔）
    signal: int  # 信號（1=買入, -1=賣出）


class BrokerSimulator:
    """撮合模擬器"""
    
    def __init__(self, config: BrokerConfig):
        """
        初始化撮合模擬器
        
        Args:
            config: 券商配置
        """
        self.config = config
    
    def run(
        self,
        signal_frame: pd.DataFrame,
        initial_capital: float,
        price_col: str = '收盤價'
    ) -> Tuple[List[Trade], pd.DataFrame]:
        """
        執行撮合模擬
        
        Args:
            signal_frame: DailySignalFrame（必須包含日期索引、signal、price_col）
            initial_capital: 初始資金
            price_col: 價格欄位名稱（預設 '收盤價'）
        
        Returns:
            (trades, equity_curve)
            - trades: 交易列表
            - equity_curve: 權益曲線 DataFrame (date, equity, cash, position_value)
        """
        # 確保日期索引
        if not isinstance(signal_frame.index, pd.DatetimeIndex):
            if '日期' in signal_frame.columns:
                signal_frame = signal_frame.set_index('日期')
            else:
                raise ValueError("signal_frame 必須有日期索引或日期欄位")
        
        # 確保排序
        signal_frame = signal_frame.sort_index()
        
        # 獲取價格欄位
        if price_col not in signal_frame.columns:
            # 嘗試其他可能的欄位名稱
            for col in ['收盤價', 'Close', 'close', '收盤']:
                if col in signal_frame.columns:
                    price_col = col
                    break
            else:
                raise ValueError(f"找不到價格欄位，嘗試過的欄位: {['收盤價', 'Close', 'close', '收盤']}")
        
        # 獲取開盤價欄位（用於下一根K開盤成交）
        open_col = None
        for col in ['開盤價', 'Open', 'open', '開盤']:
            if col in signal_frame.columns:
                open_col = col
                break
        
        # 獲取成交量欄位（用於成交量約束）
        volume_col = None
        for col in ['成交量', 'Volume', 'volume', '成交股數']:
            if col in signal_frame.columns:
                volume_col = col
                break
        
        # 獲取前一日收盤價（用於漲跌停判斷）
        prev_close_col = None
        for col in ['前收', 'PrevClose', 'prev_close']:
            if col in signal_frame.columns:
                prev_close_col = col
                break
        
        # 初始化狀態（統一持倉狀態來源）
        cash = initial_capital
        in_position = False  # 是否持倉（唯一狀態標記）
        qty = 0  # 持股數
        entry_price = None  # 進場價格
        entry_date = None  # 進場日期
        last_exit_date = None  # 最後出場日期（用於 reentry cooldown）
        
        trades: List[Trade] = []
        equity_records = []
        
        # 獲取信號欄位
        if 'signal' not in signal_frame.columns:
            raise ValueError("signal_frame 必須包含 'signal' 欄位")
        
        # 獲取理由標籤欄位
        reason_tags_col = 'reason_tags' if 'reason_tags' in signal_frame.columns else None
        
        # 逐日處理
        for i, (date, row) in enumerate(signal_frame.iterrows()):
            current_price = row[price_col]
            signal = row['signal']
            
            # 獲取理由標籤
            reason_tags = row.get(reason_tags_col, '') if reason_tags_col else ''
            
            # 檢查風控（停損/停利）
            if in_position and entry_price is not None:
                # 優先使用 ATR-based 停損停利
                if self.config.stop_loss_atr_mult is not None or self.config.take_profit_atr_mult is not None:
                    # 計算 ATR（如果尚未計算）
                    if 'ATR' not in row.index:
                        # 嘗試從 signal_frame 獲取 ATR
                        if 'ATR' in signal_frame.columns:
                            atr_value = row.get('ATR', None)
                        else:
                            # 簡單計算 ATR（使用前 atr_period 天的 True Range）
                            if i >= self.config.atr_period:
                                high_col = self._get_column_name(signal_frame, 'High')
                                low_col = self._get_column_name(signal_frame, 'Low')
                                close_col = self._get_column_name(signal_frame, 'Close')
                                if high_col and low_col and close_col:
                                    tr_list = []
                                    for j in range(max(0, i - self.config.atr_period + 1), i + 1):
                                        if j == 0:
                                            tr = signal_frame.iloc[j][high_col] - signal_frame.iloc[j][low_col]
                                        else:
                                            prev_close = signal_frame.iloc[j-1][close_col]
                                            tr = max(
                                                signal_frame.iloc[j][high_col] - signal_frame.iloc[j][low_col],
                                                abs(signal_frame.iloc[j][high_col] - prev_close),
                                                abs(signal_frame.iloc[j][low_col] - prev_close)
                                            )
                                        tr_list.append(tr)
                                    atr_value = np.mean(tr_list) if tr_list else None
                                else:
                                    atr_value = None
                            else:
                                atr_value = None
                    else:
                        atr_value = row['ATR']
                    
                    if atr_value is not None and atr_value > 0:
                        # ATR-based 停損停利
                        price_diff = current_price - entry_price
                        
                        if self.config.stop_loss_atr_mult is not None:
                            stop_loss_threshold = -self.config.stop_loss_atr_mult * atr_value
                            if price_diff <= stop_loss_threshold:
                                signal = -1
                                reason_tags = f"{reason_tags},stop_loss_atr" if reason_tags else "stop_loss_atr"
                        
                        if self.config.take_profit_atr_mult is not None:
                            take_profit_threshold = self.config.take_profit_atr_mult * atr_value
                            if price_diff >= take_profit_threshold:
                                signal = -1
                                reason_tags = f"{reason_tags},take_profit_atr" if reason_tags else "take_profit_atr"
                
                # 如果沒有使用 ATR-based，則使用百分比模式
                if signal != -1:
                    current_return = (current_price - entry_price) / entry_price
                    
                    # 停損檢查
                    if self.config.stop_loss_pct is not None:
                        if current_return <= -self.config.stop_loss_pct:
                            signal = -1
                            reason_tags = f"{reason_tags},stop_loss" if reason_tags else "stop_loss"
                    
                    # 停利檢查
                    if self.config.take_profit_pct is not None:
                        if current_return >= self.config.take_profit_pct:
                            signal = -1
                            reason_tags = f"{reason_tags},take_profit" if reason_tags else "take_profit"
            
            # 獲取前一日收盤價（用於漲跌停判斷和 sizing）
            prev_close = None
            if prev_close_col and prev_close_col in row.index:
                prev_close = row[prev_close_col]
            elif i > 0:
                prev_close = signal_frame.iloc[i - 1][price_col]
            else:
                prev_close = current_price  # 第一天用當天價格
            
            # 處理信號（根據 execution_price 設定）
            next_row = None  # 初始化，避免未定義錯誤
            if self.config.execution_price == "close":
                # 使用當根K收盤價
                execution_price = current_price
                execution_date = date
            elif i < len(signal_frame) - 1:
                # 使用下一根K開盤價（預設，避免偷看）
                next_row = signal_frame.iloc[i + 1]
                execution_date = signal_frame.index[i + 1]
                
                # 使用下一根K的開盤價（如果有的話），否則用收盤價
                if open_col and open_col in next_row.index:
                    execution_price = next_row[open_col]
                else:
                    execution_price = next_row[price_col]
            else:
                # 最後一天，使用收盤價
                execution_price = current_price
                execution_date = date
            
            # 檢查漲跌停（如果啟用且使用 next_open 模式）
            if self.config.execution_price == "next_open" and i < len(signal_frame) - 1 and next_row is not None:
                if self.config.enable_limit_up_down and prev_close is not None and prev_close > 0:
                    limit_up = prev_close * (1 + self.config.limit_up_down_pct)
                    limit_down = prev_close * (1 - self.config.limit_up_down_pct)
                    
                    # 檢查是否觸及漲跌停
                    next_high = next_row.get('最高價', next_row.get('High', execution_price))
                    next_low = next_row.get('最低價', next_row.get('Low', execution_price))
                    
                    # 漲停：開盤價 >= 漲停價 且 最高價 = 漲停價（封死）
                    is_limit_up = (execution_price >= limit_up * 0.999) and (abs(next_high - limit_up) / limit_up < 0.001)
                    # 跌停：開盤價 <= 跌停價 且 最低價 = 跌停價（封死）
                    is_limit_down = (execution_price <= limit_down * 1.001) and (abs(next_low - limit_down) / limit_down < 0.001)
                    
                    # 如果方向不利且封死，無法成交
                    if (signal == 1 and is_limit_up) or (signal == -1 and is_limit_down):
                        # 無法成交，跳過此信號
                        execution_price = None
            
            # 如果無法成交（漲跌停），跳過交易
            if execution_price is None:
                # 記錄權益（無變化）
                position_value = qty * current_price if in_position else 0.0
                equity = cash + position_value
                equity_records.append({
                    'date': date,
                    'equity': equity,
                    'cash': cash,
                    'position': qty,
                    'position_value': position_value,
                    'price': current_price
                })
                continue
            
            # 檢查 reentry cooldown
            can_reenter = True
            if last_exit_date is not None and self.config.reentry_cooldown_days > 0:
                days_since_exit = (date - last_exit_date).days
                if days_since_exit < self.config.reentry_cooldown_days:
                    can_reenter = False
            
            # 執行交易（統一的進出場邏輯）
            # 進場：只做一次（除非允許加碼）
            if signal == 1:
                if not in_position:
                    # 檢查是否可以重新進場
                    if not can_reenter:
                        # 仍在 cooldown 期間，跳過
                        position_value = qty * current_price if in_position else 0.0
                        equity = cash + position_value
                        equity_records.append({
                            'date': date,
                            'equity': equity,
                            'cash': cash,
                            'position': qty,
                            'position_value': position_value,
                            'price': current_price
                        })
                        continue
                    
                    # 正常進場
                    # 獲取成交量（用於約束）
                    volume = None
                    if volume_col and i < len(signal_frame) - 1:
                        volume = signal_frame.iloc[i + 1].get(volume_col)
                    
                    trade = self._execute_buy(
                        date=execution_date,
                        price=execution_price,
                        capital=cash,
                        reason_tags=reason_tags,
                        signal=signal,
                        volume=volume,
                        prev_close=prev_close
                    )
                    if trade:
                        trades.append(trade)
                        cash -= (trade.value + trade.fee + trade.slippage)
                        qty = trade.shares
                        entry_price = execution_price
                        entry_date = execution_date
                        in_position = True
                elif self.config.allow_pyramid:
                    # 允許加碼
                    # 獲取成交量（用於約束）
                    volume = None
                    if volume_col and i < len(signal_frame) - 1:
                        volume = signal_frame.iloc[i + 1].get(volume_col)
                    
                    trade = self._execute_buy(
                        date=execution_date,
                        price=execution_price,
                        capital=cash,
                        reason_tags=reason_tags,
                        signal=signal,
                        volume=volume,
                        prev_close=prev_close
                    )
                    if trade:
                        trades.append(trade)
                        cash -= (trade.value + trade.fee + trade.slippage)
                        qty += trade.shares  # 累加股數
                        entry_price = execution_price  # 更新進場價（可選：加權平均）
                        entry_date = execution_date
                        in_position = True
            
            # 出場：一定要 append trade
            elif signal == -1 and in_position:
                trade = self._execute_sell(
                    date=execution_date,
                    price=execution_price,
                    shares=qty,
                    entry_price=entry_price,
                    reason_tags=reason_tags,
                    signal=signal
                )
                if trade:
                    trades.append(trade)
                    cash += (trade.value - trade.fee - trade.slippage)
                    qty = 0
                    entry_price = None
                    entry_date = None
                    last_exit_date = execution_date  # 記錄出場日期
                    in_position = False
            
            # 記錄權益（只能用這個公式）
            position_value = qty * current_price if in_position else 0.0
            equity = cash + position_value
            
            equity_records.append({
                'date': date,
                'equity': equity,
                'cash': cash,
                'position': qty,
                'position_value': position_value,
                'price': current_price
            })
        
        # 最後一天強制平倉（如果還有持倉）
        if in_position and entry_price is not None and entry_date is not None:
            # 使用最後一天的收盤價強制平倉
            final_price = signal_frame.iloc[-1][price_col]
            trade = self._execute_sell(
                date=signal_frame.index[-1],
                price=final_price,
                shares=qty,
                entry_price=entry_price,
                reason_tags="強制平倉",
                signal=-1
            )
            if trade:
                trades.append(trade)
                cash += (trade.value - trade.fee - trade.slippage)
                # 更新最後一天的權益記錄
                if equity_records:
                    equity_records[-1]['equity'] = cash
                    equity_records[-1]['cash'] = cash
                    equity_records[-1]['position'] = 0
                    equity_records[-1]['position_value'] = 0.0
        
        # 構建權益曲線 DataFrame
        equity_curve = pd.DataFrame(equity_records)
        equity_curve = equity_curve.set_index('date')
        
        # 一致性檢查（debug 時期必須有）
        if len(trades) == 0:
            # 沒交易 → 權益必須固定
            final_equity = equity_curve['equity'].iloc[-1]
            if abs(final_equity - initial_capital) > 0.01:  # 允許小數點誤差
                raise ValueError(
                    f"一致性錯誤：沒有交易但權益變動了！"
                    f"初始資金: {initial_capital}, 最終權益: {final_equity}, "
                    f"差異: {final_equity - initial_capital}"
                )
        
        return trades, equity_curve
    
    def _execute_buy(
        self,
        date: pd.Timestamp,
        price: float,
        capital: float,
        reason_tags: str,
        signal: int,
        volume: Optional[float] = None,
        prev_close: Optional[float] = None
    ) -> Optional[Trade]:
        """
        執行買入
        
        Args:
            date: 交易日期
            price: 價格
            capital: 可用資金
            reason_tags: 理由標籤
            signal: 信號
        
        Returns:
            Trade 對象或 None（如果資金不足）
        """
        if capital <= 0 or price <= 0:
            return None
        
        # 計算滑價
        slippage_pct = self.config.slippage_bps / 10000
        execution_price = price * (1 + slippage_pct)
        
        # 根據 sizing 模式計算目標股數
        if self.config.sizing_mode == "fixed_amount" and self.config.fixed_amount is not None:
            # 固定金額
            target_value = self.config.fixed_amount
            shares = int(target_value / execution_price / 1000) * 1000
        elif self.config.sizing_mode == "risk_based" and self.config.risk_pct is not None:
            # 風險百分比 sizing（需要 ATR 或固定停損距離）
            # 簡化：使用固定停損距離（例如 2%）
            stop_distance_pct = self.config.risk_pct
            risk_per_share = execution_price * stop_distance_pct
            if risk_per_share > 0:
                total_risk = capital * self.config.risk_pct
                shares = int((total_risk / risk_per_share) / 1000) * 1000
            else:
                shares = 0
        else:
            # 全倉（預設）
            shares = int(capital / execution_price / 1000) * 1000
        
        # 成交量約束（如果啟用）
        if self.config.enable_volume_constraint and volume is not None and volume > 0:
            max_shares = int(volume * self.config.max_participation_rate)
            shares = min(shares, max_shares)
            # 調整為1000股單位
            shares = int(shares / 1000) * 1000
        
        if shares <= 0:
            return None
        
        # 計算交易金額
        value = shares * execution_price
        
        # 計算手續費（台股手續費率 0.1425%，最低20元）
        fee = max(value * self.config.fee_bps / 10000, 20.0)
        
        # 計算滑價成本
        slippage_cost = shares * price * slippage_pct
        
        # 總成本
        total_cost = value + fee + slippage_cost
        
        if total_cost > capital:
            # 資金不足，調整股數
            shares = int((capital - fee) / execution_price / 1000) * 1000
            if shares <= 0:
                return None
            value = shares * execution_price
            fee = max(value * self.config.fee_bps / 10000, 20.0)
            slippage_cost = shares * price * slippage_pct
        
        return Trade(
            date=date,
            type='buy',
            price=execution_price,
            shares=shares,
            value=value,
            fee=fee,
            slippage=slippage_cost,
            reason_tags=reason_tags,
            signal=signal
        )
    
    def _execute_sell(
        self,
        date: pd.Timestamp,
        price: float,
        shares: int,
        entry_price: float,
        reason_tags: str,
        signal: int
    ) -> Optional[Trade]:
        """
        執行賣出
        
        Args:
            date: 交易日期
            price: 價格
            shares: 持股數
            entry_price: 進場價格
            reason_tags: 理由標籤
            signal: 信號
        
        Returns:
            Trade 對象或 None
        """
        if shares <= 0 or price <= 0:
            return None
        
        # 計算滑價
        slippage_pct = self.config.slippage_bps / 10000
        execution_price = price * (1 - slippage_pct)
        
        # 計算交易金額
        value = shares * execution_price
        
        # 計算手續費（台股手續費率 0.1425%，最低20元）
        fee = max(value * self.config.fee_bps / 10000, 20.0)
        
        # 計算證券交易稅（台股賣出時 0.3%）
        tax = value * 0.003
        
        # 計算滑價成本
        slippage_cost = shares * price * slippage_pct
        
        return Trade(
            date=date,
            type='sell',
            price=execution_price,
            shares=shares,
            value=value,
            fee=fee + tax,  # 手續費 + 證交稅
            slippage=slippage_cost,
            reason_tags=reason_tags,
            signal=signal
        )

