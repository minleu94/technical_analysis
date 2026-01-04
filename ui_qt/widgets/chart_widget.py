"""
圖表組件
使用 matplotlib 整合到 PySide6
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt
import matplotlib
matplotlib.use('QtAgg')  # 使用 Qt 後端
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import logging

# 嘗試導入 mplcursors（用於 hover tooltip）
try:
    import mplcursors
    HAS_MPLCURSORS = True
except ImportError:
    HAS_MPLCURSORS = False
    logging.warning("[ChartWidget] mplcursors 未安裝，將使用基本 tooltip 功能")

# 設定中文字體（支援繁體中文）
def setup_chinese_font():
    """設定 matplotlib 中文字體"""
    try:
        # Windows 常見的中文字體
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Microsoft YaHei', 'SimHei', 'Arial Unicode MS', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False  # 解決負號顯示問題
    except Exception as e:
        print(f"[ChartWidget] 設定中文字體失敗: {e}")

# 初始化字體設定
setup_chinese_font()


class EquityCurveWidget(QWidget):
    """權益曲線圖表（支援買賣點 marker、hover tooltip、十字線）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # 互動相關變數
        self._crosshair_vline = None  # 十字線垂直線
        self._crosshair_hline = None  # 十字線水平線（可選）
        self._crosshair_info_box = None  # 資訊框
        self._cursor_connections = []  # 事件連接 ID（用於清理）
        self._mplcursors_handles = []  # mplcursors 句柄（用於清理）
        self._ax2 = None  # 右側 Y 軸（用於基準線）
        # 數據快取（用於 crosshair 和 tooltip）
        self._equity_series = None
        self._benchmark_normalized = None
        self._buy_scatter = None
        self._sell_scatter = None
        self._buy_meta = {}  # {index: {date, price, shares, tags}}
        self._sell_meta = {}  # {index: {date, price, shares, profit, return_pct, holding_days, tags}}
        self._equity_line = None
        self._bench_line = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 圖表（使用較大的初始尺寸，但會隨窗口調整）
        self.figure = Figure(figsize=(12, 8))  # 增大初始尺寸
        self.canvas = FigureCanvas(self.figure)
        # 設置 canvas 可以隨窗口大小調整
        self.canvas.setMinimumSize(400, 300)  # 設置最小尺寸，但允許更大
        layout.addWidget(self.canvas)
        
        self.ax = self.figure.add_subplot(111)
        # 確保使用中文字體
        self.ax.set_title('權益曲線 (Equity Curve)', fontsize=12, fontweight='bold')
        self.ax.set_xlabel('日期')
        self.ax.set_ylabel('權益 ($)')
        self.ax.grid(True, alpha=0.3)
    
    def plot(
        self, 
        equity_series: pd.Series, 
        benchmark_series: Optional[pd.Series] = None, 
        cagr: Optional[float] = None,
        trade_list: Optional[pd.DataFrame] = None
    ):
        """
        繪製權益曲線（含買賣點、hover tooltip、十字線）
        
        Args:
            equity_series: 權益序列（日期索引）
            benchmark_series: 基準序列（可選）
            cagr: 年化報酬率（可選，用於顯示）
            trade_list: 交易明細 DataFrame（可選，欄位：進場日期、出場日期、進場價格、出場價格、股數、報酬、報酬率%、持有天數、理由標籤）
        """
        # 清理舊的事件連接
        self._cleanup_interactions()
        
        self.ax.clear()
        
        if equity_series is None or len(equity_series) == 0:
            self.ax.text(0.5, 0.5, '無資料', ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw()
            return
        
        # 確保索引是 DatetimeIndex
        if not isinstance(equity_series.index, pd.DatetimeIndex):
            try:
                equity_series.index = pd.to_datetime(equity_series.index)
            except Exception as e:
                logging.warning(f"[EquityCurveWidget] 無法轉換索引為日期: {e}")
                self.ax.text(0.5, 0.5, '日期索引格式錯誤', ha='center', va='center', transform=self.ax.transAxes)
                self.canvas.draw()
                return
        
        # 1. 找出第一個買點（用於基準線對齊）
        first_buy_date = None
        first_buy_equity = None
        if trade_list is not None and len(trade_list) > 0:
            # 檢查必要欄位並建立欄位映射
            required_cols = {
                '進場日期': ['進場日期', 'buy_date', 'Buy Date'],
                '出場日期': ['出場日期', 'sell_date', 'Sell Date'],
                '進場價格': ['進場價格', 'buy_price', 'Buy Price'],
                '出場價格': ['出場價格', 'sell_price', 'Sell Price'],
                '股數': ['股數', 'shares', 'Shares']
            }
            
            col_mapping = {}
            missing_cols = []
            for required_name, possible_names in required_cols.items():
                found = False
                for possible_name in possible_names:
                    if possible_name in trade_list.columns:
                        col_mapping[required_name] = possible_name
                        found = True
                        break
                if not found:
                    missing_cols.append(required_name)
            
            # 如果有進場日期欄位，找出第一個買點
            if '進場日期' in col_mapping and len(missing_cols) == 0:
                first_buy_date_raw = trade_list[col_mapping['進場日期']].iloc[0]
                if not pd.isna(first_buy_date_raw):
                    try:
                        if not isinstance(first_buy_date_raw, pd.Timestamp):
                            first_buy_date = pd.to_datetime(first_buy_date_raw)
                        else:
                            first_buy_date = first_buy_date_raw
                        
                        # 對齊到 equity_series 索引
                        first_buy_date = self._align_date_to_index(first_buy_date, equity_series.index)
                        if first_buy_date is not None and first_buy_date in equity_series.index:
                            first_buy_equity = equity_series.loc[first_buy_date]
                    except Exception as e:
                        logging.warning(f"[EquityCurveWidget] 無法解析第一個買點日期: {e}")
        
        # 如果沒有買點，使用權益曲線的起始點
        if first_buy_date is None or first_buy_equity is None:
            first_buy_date = equity_series.index[0] if len(equity_series) > 0 else None
            first_buy_equity = equity_series.iloc[0] if len(equity_series) > 0 else None
        
        # 2. 繪製權益曲線和基準線（返回歸一化後的基準序列和原始基準序列）
        benchmark_normalized, benchmark_original = self._plot_equity_and_benchmark(
            equity_series, 
            benchmark_series,
            first_buy_date,
            first_buy_equity
        )
        
        # 3. 繪製買賣點 marker
        buy_scatter, sell_scatter = self._plot_trade_markers(equity_series, trade_list)
        
        # 3. 格式化座標軸
        self._format_axes(cagr)
        
        # 4. 啟用十字線（傳入原始基準序列，用於顯示原始點數）
        self._enable_crosshair(equity_series, benchmark_original)
        
        # 5. 啟用 hover tooltip
        self._enable_hover_tooltip(
            equity_series, 
            benchmark_original, 
            buy_scatter, 
            sell_scatter
        )
        
        # 保存數據快取（用於互動功能）
        self._equity_series = equity_series
        self._benchmark_normalized = benchmark_normalized  # 歸一化後的序列（用於繪圖）
        self._benchmark_original = benchmark_original  # 原始序列（用於十字線顯示原始點數）
        self._buy_scatter = buy_scatter
        self._sell_scatter = sell_scatter
        
        # 格式化 x 軸日期
        self.figure.autofmt_xdate()
        
        self.canvas.draw()
    
    def _align_date_to_index(self, target_date: pd.Timestamp, index: pd.DatetimeIndex, method: str = 'asof') -> Optional[pd.Timestamp]:
        """
        將目標日期對齊到索引中的最近有效交易日
        
        Args:
            target_date: 目標日期
            index: 日期索引
            method: 'asof' 表示向前對齊（取 <= target_date 的最大者）
        
        Returns:
            對齊後的日期，找不到則返回 None
        """
        # 統一時區處理
        if index.tz is None:
            # index 是 naive，確保 target_date 也是 naive
            if target_date.tz is not None:
                target_date = target_date.tz_localize(None)
        else:
            # index 有時區，確保 target_date 也有相同時區
            if target_date.tz is None:
                target_date = target_date.tz_localize(index.tz)
            elif target_date.tz != index.tz:
                target_date = target_date.tz_convert(index.tz)
        
        if method == 'asof':
            # 使用 asof 方法：找 <= target_date 的最大者
            try:
                aligned = index.asof(target_date)
                if pd.isna(aligned):
                    # 如果找不到，嘗試找第一個 >= target_date 的日期
                    mask = index >= target_date
                    if mask.any():
                        aligned = index[mask][0]
                    else:
                        logging.warning(f"[EquityCurveWidget] 無法對齊日期 {target_date.strftime('%Y-%m-%d')}，跳過")
                        return None
                return pd.Timestamp(aligned)
            except Exception as e:
                logging.warning(f"[EquityCurveWidget] 日期對齊失敗: {e}")
                return None
        else:
            # 其他方法可以擴展
            return None
    
    def _plot_equity_and_benchmark(
        self, 
        equity_series: pd.Series, 
        benchmark_series: Optional[pd.Series],
        first_buy_date: Optional[pd.Timestamp] = None,
        first_buy_equity: Optional[float] = None
    ) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
        """
        繪製權益曲線和基準線（單一 Y 軸，基準線歸一化後轉成等值資金）
        
        Args:
            equity_series: 權益序列
            benchmark_series: 基準序列
            first_buy_date: 第一個買點日期（用於基準線對齊）
            first_buy_equity: 第一個買點時的權益值（用於基準線對齊）
        
        Returns:
            (benchmark_normalized, benchmark_original) - 歸一化後的基準序列和原始基準序列
        """
        # 繪製權益曲線
        self._equity_line, = self.ax.plot(
            equity_series.index, 
            equity_series.values, 
            label='策略權益', 
            linewidth=2, 
            color='#2196F3'
        )
        
        benchmark_normalized = None
        benchmark_original = None
        
        # 繪製基準（如果提供）- 歸一化後轉成等值資金，使用同一 Y 軸
        if benchmark_series is not None and len(benchmark_series) > 0:
            # 確保索引是 DatetimeIndex
            if not isinstance(benchmark_series.index, pd.DatetimeIndex):
                try:
                    benchmark_series.index = pd.to_datetime(benchmark_series.index)
                except:
                    logging.warning("[EquityCurveWidget] 基準序列日期索引轉換失敗")
                    benchmark_series = None
            
            if benchmark_series is not None:
                # 保存原始序列（用於十字線顯示）
                benchmark_original = benchmark_series.copy()
                
                # 確定對齊點：如果有第一個買點，使用買點；否則使用權益曲線起始點
                if first_buy_date is not None and first_buy_equity is not None:
                    # 對齊到第一個買點
                    align_date = first_buy_date
                    align_equity = first_buy_equity
                    
                    # 找到基準序列中對應買點日期的值
                    if align_date in benchmark_series.index:
                        align_benchmark = benchmark_series.loc[align_date]
                    else:
                        # 如果買點日期不在基準序列中，找最近的日期
                        align_date_bench = self._align_date_to_index(align_date, benchmark_series.index)
                        if align_date_bench is not None:
                            align_benchmark = benchmark_series.loc[align_date_bench]
                            align_date = align_date_bench
                        else:
                            # 如果找不到，使用基準序列起始點
                            align_date = benchmark_series.index[0]
                            align_equity = equity_series.iloc[0]
                            align_benchmark = benchmark_series.iloc[0]
                else:
                    # 使用權益曲線起始點
                    align_date = equity_series.index[0]
                    align_equity = equity_series.iloc[0]
                    align_benchmark = benchmark_series.iloc[0]
                
                # 歸一化基準（對齊到買點或起始點，轉成等值資金）
                # benchmark_normalized = benchmark / benchmark[align_date] * equity[align_date]
                benchmark_normalized = benchmark_series / align_benchmark * align_equity
                
                # 對齊日期範圍（只取與 equity_series 重疊的部分）
                common_index = equity_series.index.intersection(benchmark_normalized.index)
                if len(common_index) > 0:
                    benchmark_normalized = benchmark_normalized.reindex(common_index).interpolate(method='time')
                    benchmark_original = benchmark_original.reindex(common_index).interpolate(method='time')
                    
                    self._bench_line, = self.ax.plot(
                        benchmark_normalized.index, 
                        benchmark_normalized.values, 
                        label='基準 (TAIEX)', 
                        linewidth=1.5, 
                        linestyle='--', 
                        color='#757575', 
                        alpha=0.7
                    )
        
        # 清除右側軸引用（不再使用）
        self._ax2 = None
        
        # 確保返回兩個值（即使為 None）
        return benchmark_normalized, benchmark_original
    
    def _plot_trade_markers(
        self, 
        equity_series: pd.Series, 
        trade_list: Optional[pd.DataFrame]
    ) -> Tuple[Optional[Any], Optional[Any]]:
        """
        繪製買賣點 marker
        
        Returns:
            (buy_scatter, sell_scatter) - matplotlib scatter 物件
        """
        self._buy_meta = {}
        self._sell_meta = {}
        
        if trade_list is None or len(trade_list) == 0:
            return None, None
        
        # 檢查必要欄位（允許使用替代欄位名稱）
        required_cols = {
            '進場日期': ['進場日期', 'buy_date', 'Buy Date'],
            '出場日期': ['出場日期', 'sell_date', 'Sell Date'],
            '進場價格': ['進場價格', 'buy_price', 'Buy Price'],
            '出場價格': ['出場價格', 'sell_price', 'Sell Price'],
            '股數': ['股數', 'shares', 'Shares']
        }
        
        # 建立欄位映射
        col_mapping = {}
        missing_cols = []
        
        for required_name, possible_names in required_cols.items():
            found = False
            for possible_name in possible_names:
                if possible_name in trade_list.columns:
                    col_mapping[required_name] = possible_name
                    found = True
                    break
            if not found:
                missing_cols.append(required_name)
        
        if missing_cols:
            logging.warning(
                f"[EquityCurveWidget] trade_list 缺少必要欄位: {missing_cols}\n"
                f"  需要的欄位: {list(required_cols.keys())}\n"
                f"  實際有的欄位: {list(trade_list.columns)}"
            )
            return None, None
        
        buy_dates = []
        buy_equity_values = []
        sell_dates = []
        sell_equity_values = []
        
        # 統計同一天的交易數量（用於 offset）
        date_counts = {}
        
        for idx, row in trade_list.iterrows():
            # 處理買點（使用欄位映射）
            buy_date_raw = row[col_mapping['進場日期']]
            if pd.isna(buy_date_raw):
                continue
            
            # 轉換為 Timestamp
            if not isinstance(buy_date_raw, pd.Timestamp):
                try:
                    buy_date = pd.to_datetime(buy_date_raw)
                except:
                    logging.warning(f"[EquityCurveWidget] 無法解析買點日期: {buy_date_raw}")
                    continue
            else:
                buy_date = buy_date_raw
            
            # 對齊到 equity_series 索引
            aligned_buy_date = self._align_date_to_index(buy_date, equity_series.index)
            if aligned_buy_date is None:
                continue
            
            # 獲取該日的權益值
            if aligned_buy_date not in equity_series.index:
                continue
            
            equity_val = equity_series.loc[aligned_buy_date]
            
            # 計算 offset（同一天多筆交易時避免重疊）
            date_key = aligned_buy_date.strftime('%Y-%m-%d')
            same_day_count = date_counts.get(date_key, 0)
            date_counts[date_key] = same_day_count + 1
            offset = equity_val * 0.001 * same_day_count  # 小幅偏移
            
            buy_dates.append(aligned_buy_date)
            buy_equity_values.append(equity_val + offset)
            
            # 保存 metadata（使用列表索引作為 key）
            buy_index = len(buy_dates) - 1
            buy_meta = {
                'date': aligned_buy_date,
                'price': row.get(col_mapping.get('進場價格', '進場價格'), 0),
                'shares': row.get(col_mapping.get('股數', '股數'), 0),
                'tags': row.get('理由標籤', '')
            }
            self._buy_meta[buy_index] = buy_meta
            
            # 處理賣點（使用欄位映射）
            sell_date_raw = row[col_mapping['出場日期']]
            if pd.isna(sell_date_raw):
                continue
            
            if not isinstance(sell_date_raw, pd.Timestamp):
                try:
                    sell_date = pd.to_datetime(sell_date_raw)
                except:
                    logging.warning(f"[EquityCurveWidget] 無法解析賣點日期: {sell_date_raw}")
                    continue
            else:
                sell_date = sell_date_raw
            
            aligned_sell_date = self._align_date_to_index(sell_date, equity_series.index)
            if aligned_sell_date is None:
                continue
            
            if aligned_sell_date not in equity_series.index:
                continue
            
            equity_val_sell = equity_series.loc[aligned_sell_date]
            
            # 計算 offset
            date_key_sell = aligned_sell_date.strftime('%Y-%m-%d')
            same_day_count_sell = date_counts.get(date_key_sell, 0)
            date_counts[date_key_sell] = same_day_count_sell + 1
            offset_sell = equity_val_sell * 0.001 * same_day_count_sell
            
            sell_dates.append(aligned_sell_date)
            sell_equity_values.append(equity_val_sell + offset_sell)
            
            # 保存 metadata（使用列表索引作為 key）
            sell_index = len(sell_dates) - 1
            # 注意：報酬率% 欄位可能已經是百分比值（0-100），需要判斷
            return_pct_raw = row.get('報酬率%', 0)
            if return_pct_raw is None or pd.isna(return_pct_raw):
                return_pct = 0.0
            else:
                # 如果值 > 1，可能是百分比（例如 5.5 表示 5.5%）
                # 如果值 <= 1，可能是小數（例如 0.055 表示 5.5%）
                # 這裡假設欄位名是「報酬率%」，所以值應該是百分比
                return_pct = float(return_pct_raw)
            
            sell_meta = {
                'date': aligned_sell_date,
                'price': row.get(col_mapping.get('出場價格', '出場價格'), 0),
                'shares': row.get(col_mapping.get('股數', '股數'), 0),
                'profit': row.get('報酬', 0),
                'return_pct': return_pct,  # 已經是百分比
                'holding_days': row.get('持有天數', 0),
                'tags': row.get('理由標籤', '')
            }
            self._sell_meta[sell_index] = sell_meta
        
        # 繪製買點
        buy_scatter = None
        if len(buy_dates) > 0:
            buy_scatter = self.ax.scatter(
                buy_dates, 
                buy_equity_values, 
                marker='^', 
                s=100, 
                color='#4CAF50', 
                edgecolors='darkgreen',
                linewidths=1.5,
                alpha=0.8,
                label='買點',
                zorder=5
            )
        
        # 繪製賣點
        sell_scatter = None
        if len(sell_dates) > 0:
            sell_scatter = self.ax.scatter(
                sell_dates, 
                sell_equity_values, 
                marker='v', 
                s=100, 
                color='#F44336', 
                edgecolors='darkred',
                linewidths=1.5,
                alpha=0.8,
                label='賣點',
                zorder=5
            )
        
        return buy_scatter, sell_scatter
    
    def _format_axes(self, cagr: Optional[float]):
        """格式化座標軸"""
        # 顯示 CAGR（如果提供）
        if cagr is not None:
            title = f'權益曲線 (Equity Curve) - CAGR: {cagr*100:.2f}%'
        else:
            title = '權益曲線 (Equity Curve)'
        
        self.ax.set_title(title, fontsize=12, fontweight='bold')
        self.ax.set_xlabel('日期')
        self.ax.set_ylabel('權益 ($)')
        self.ax.legend(loc='best')
        self.ax.grid(True, alpha=0.3)
    
    def _enable_crosshair(self, equity_series: pd.Series, benchmark_original: Optional[pd.Series]):
        """啟用十字線互動（benchmark_original 是原始序列，用於顯示原始點數）"""
        # 創建十字線（初始隱藏）
        self._crosshair_vline = self.ax.axvline(
            x=equity_series.index[0] if len(equity_series) > 0 else 0,
            color='gray',
            linestyle='--',
            linewidth=1.5,
            alpha=0.8,
            zorder=100,  # 確保在最上層，高於所有其他元素
            visible=False
        )
        
        # 資訊框（初始隱藏）
        self._crosshair_info_box = self.ax.text(
            0.98, 0.98, '',
            transform=self.ax.transAxes,
            fontsize=9,
            verticalalignment='top',
            horizontalalignment='right',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='gray', linewidth=1),
            zorder=101,  # 確保資訊框也在最上層
            visible=False
        )
        
        # 綁定滑鼠移動事件
        def on_mouse_move(event):
            # 檢查滑鼠是否在任何軸上（包括右側軸）
            if event.inaxes is None:
                # 滑鼠不在圖表區域，隱藏十字線
                self._crosshair_vline.set_visible(False)
                self._crosshair_info_box.set_visible(False)
                self.canvas.draw_idle()
                return
            
            # 如果滑鼠在右側軸上，也應該顯示十字線（因為是同一張圖）
            if event.inaxes != self.ax and not (hasattr(self, '_ax2') and self._ax2 and event.inaxes == self._ax2):
                # 滑鼠不在主軸或右側軸上，隱藏十字線
                self._crosshair_vline.set_visible(False)
                self._crosshair_info_box.set_visible(False)
                self.canvas.draw_idle()
                return
            
            # 將 x 座標轉換為日期
            if event.xdata is None:
                return
            
            # matplotlib 的日期是數字，需要轉換
            try:
                target_date = mdates.num2date(event.xdata)
                target_timestamp = pd.Timestamp(target_date)
                # 統一時區處理：確保 target_timestamp 與 equity_series.index 的時區狀態一致
                # 如果 equity_series.index 是 naive（無時區），則移除 target_timestamp 的時區
                if equity_series.index.tz is None:
                    # equity_series.index 是 naive，確保 target_timestamp 也是 naive
                    if target_timestamp.tz is not None:
                        target_timestamp = target_timestamp.tz_localize(None)
                else:
                    # equity_series.index 有時區，確保 target_timestamp 也有相同時區
                    if target_timestamp.tz is None:
                        target_timestamp = target_timestamp.tz_localize(equity_series.index.tz)
                    elif target_timestamp.tz != equity_series.index.tz:
                        target_timestamp = target_timestamp.tz_convert(equity_series.index.tz)
            except Exception as e:
                logging.warning(f"[EquityCurveWidget] 日期轉換失敗: {e}")
                return
            
            # 在 equity_series.index 中找最近的日期
            if len(equity_series.index) == 0:
                return
            
            # 使用 searchsorted 找插入位置
            try:
                idx = equity_series.index.searchsorted(target_timestamp)
            except Exception as e:
                logging.warning(f"[EquityCurveWidget] searchsorted 失敗: {e}")
                return
            
            # 決定使用哪個日期（比較左右兩個）
            if idx == 0:
                nearest_date = equity_series.index[0]
            elif idx >= len(equity_series.index):
                nearest_date = equity_series.index[-1]
            else:
                left_date = equity_series.index[idx - 1]
                right_date = equity_series.index[idx]
                # 選擇距離較近的
                left_diff = abs((target_timestamp - left_date).total_seconds())
                right_diff = abs((target_timestamp - right_date).total_seconds())
                nearest_date = left_date if left_diff < right_diff else right_date
            
            # 更新垂直線位置
            try:
                if self._crosshair_vline is not None:
                    self._crosshair_vline.set_xdata([nearest_date, nearest_date])
                    self._crosshair_vline.set_visible(True)
            except Exception as e:
                logging.warning(f"[EquityCurveWidget] 更新十字線失敗: {e}")
                return
            
            # 獲取該日的權益值和基準值
            equity_val = equity_series.loc[nearest_date]
            
            # 獲取歸一化後的基準值（用於顯示在圖上）
            bench_norm_val = None
            if hasattr(self, '_benchmark_normalized') and self._benchmark_normalized is not None:
                if nearest_date in self._benchmark_normalized.index:
                    bench_norm_val = self._benchmark_normalized.loc[nearest_date]
            
            # 獲取原始基準值（用於顯示原始點數）
            bench_raw_val = None
            if benchmark_original is not None and nearest_date in benchmark_original.index:
                bench_raw_val = benchmark_original.loc[nearest_date]
            
            # 格式化數值（千分位）
            def format_currency(val):
                return f"{val:,.2f}"
            
            def format_index(val):
                return f"{val:,.0f}"
            
            # 更新資訊框
            info_text = f"日期: {nearest_date.strftime('%Y-%m-%d')}\n"
            info_text += f"Equity: ${format_currency(equity_val)}"
            if bench_norm_val is not None:
                info_text += f"\nBenchmark(norm $): ${format_currency(bench_norm_val)}"
            if bench_raw_val is not None:
                info_text += f"\nTAIEX Close (raw points): {format_index(bench_raw_val)}"
            
            try:
                if self._crosshair_info_box is not None:
                    self._crosshair_info_box.set_text(info_text)
                    self._crosshair_info_box.set_visible(True)
            except Exception as e:
                logging.warning(f"[EquityCurveWidget] 更新資訊框失敗: {e}")
            
            self.canvas.draw_idle()
        
        # 綁定事件
        cid = self.canvas.mpl_connect('motion_notify_event', on_mouse_move)
        self._cursor_connections.append(cid)
    
    def _enable_hover_tooltip(
        self,
        equity_series: pd.Series,
        benchmark_normalized: Optional[pd.Series],
        buy_scatter: Optional[Any],
        sell_scatter: Optional[Any]
    ):
        """啟用 hover tooltip"""
        if HAS_MPLCURSORS:
            # 使用 mplcursors 實現 tooltip
            # 買點 tooltip
            if buy_scatter is not None and len(self._buy_meta) > 0:
                def buy_formatter(sel):
                    idx = sel.target.index
                    if idx in self._buy_meta:
                        meta = self._buy_meta[idx]
                        text = f"BUY @ {meta['date'].strftime('%Y-%m-%d')}\n"
                        text += f"Buy Price: ${meta['price']:,.2f}\n"
                        text += f"Shares: {int(meta['shares']):,}\n"
                        if meta['tags']:
                            text += f"Tags: {meta['tags']}"
                        return text
                    return ""
                
                cursor_buy = mplcursors.cursor(buy_scatter, hover=True)
                cursor_buy.connect("add", lambda sel: sel.annotation.set_text(buy_formatter(sel)))
                self._mplcursors_handles.append(cursor_buy)
            
            # 賣點 tooltip
            if sell_scatter is not None and len(self._sell_meta) > 0:
                def sell_formatter(sel):
                    idx = sel.target.index
                    if idx in self._sell_meta:
                        meta = self._sell_meta[idx]
                        text = f"SELL @ {meta['date'].strftime('%Y-%m-%d')}\n"
                        text += f"Sell Price: ${meta['price']:,.2f}\n"
                        text += f"Shares: {int(meta['shares']):,}\n"
                        text += f"Profit: ${meta['profit']:,.2f}\n"
                        text += f"Return%: {meta['return_pct']:.2f}%\n"
                        text += f"Holding Days: {int(meta['holding_days'])}\n"
                        if meta['tags']:
                            text += f"Tags: {meta['tags']}"
                        return text
                    return ""
                
                cursor_sell = mplcursors.cursor(sell_scatter, hover=True)
                cursor_sell.connect("add", lambda sel: sel.annotation.set_text(sell_formatter(sel)))
                self._mplcursors_handles.append(cursor_sell)
        else:
            # 使用基本 matplotlib annotation（較簡單的實現）
            logging.info("[EquityCurveWidget] 使用基本 tooltip（mplcursors 未安裝）")
            # 這裡可以實現基本的 annotation，但功能較有限
            # 為了簡化，暫時跳過
    
    def _cleanup_interactions(self):
        """清理互動事件連接"""
        # 斷開 matplotlib 事件連接
        for cid in self._cursor_connections:
            try:
                self.canvas.mpl_disconnect(cid)
            except:
                pass
        self._cursor_connections.clear()
        
        # 清理 mplcursors
        for handle in self._mplcursors_handles:
            try:
                handle.remove()
            except:
                pass
        self._mplcursors_handles.clear()
        
        # 重置十字線和資訊框
        if self._crosshair_vline:
            self._crosshair_vline.set_visible(False)
        if self._crosshair_info_box:
            self._crosshair_info_box.set_visible(False)


class DrawdownCurveWidget(QWidget):
    """回撤曲線圖表"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.figure = Figure(figsize=(12, 8))  # 增大初始尺寸
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumSize(400, 300)  # 設置最小尺寸，但允許更大
        layout.addWidget(self.canvas)
        
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title('回撤曲線 (Drawdown Curve)', fontsize=12, fontweight='bold', fontfamily='sans-serif')
        self.ax.set_xlabel('日期', fontfamily='sans-serif')
        self.ax.set_ylabel('回撤 (%)', fontfamily='sans-serif')
        self.ax.grid(True, alpha=0.3)
    
    def plot(self, drawdown_series: pd.Series, max_dd_info: Optional[Dict[str, Any]] = None):
        """
        繪製回撤曲線
        
        Args:
            drawdown_series: 回撤序列（日期索引，負數）
            max_dd_info: 最大回撤資訊（可選）
        """
        self.ax.clear()
        
        if drawdown_series is None or len(drawdown_series) == 0:
            self.ax.text(0.5, 0.5, '無資料', ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw()
            return
        
        # 轉換為百分比
        drawdown_pct = drawdown_series * 100
        
        # 填充回撤區域
        self.ax.fill_between(drawdown_pct.index, drawdown_pct.values, 0, 
                            color='#F44336', alpha=0.3, label='回撤')
        self.ax.plot(drawdown_pct.index, drawdown_pct.values, 
                    color='#F44336', linewidth=1.5, label='回撤曲線')
        
        # 標記最大回撤（如果提供）
        if max_dd_info:
            max_dd_date = max_dd_info.get('max_drawdown_date')
            max_dd_value = max_dd_info.get('max_drawdown', 0) * 100
            peak_date = max_dd_info.get('peak_date')
            recovery_date = max_dd_info.get('recovery_date')
            recovery_days = max_dd_info.get('recovery_days')
            
            if max_dd_date and max_dd_value:
                # 標記最大回撤點
                self.ax.plot(max_dd_date, max_dd_value, 'ro', markersize=8, label='最大回撤')
                self.ax.annotate(
                    f'最大回撤: {max_dd_value:.2f}%\n日期: {max_dd_date.strftime("%Y-%m-%d")}',
                    xy=(max_dd_date, max_dd_value),
                    xytext=(10, -30),
                    textcoords='offset points',
                    bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0')
                )
            
            # 標記回撤區間
            if peak_date and max_dd_date:
                self.ax.axvspan(peak_date, max_dd_date, alpha=0.2, color='red', label='回撤區間')
            
            # 標記恢復日期（如果有）
            if recovery_date:
                self.ax.axvline(recovery_date, color='green', linestyle='--', linewidth=1, alpha=0.7, label='恢復日期')
                if recovery_days:
                    self.ax.text(0.02, 0.98, f'恢復天數: {recovery_days} 天', 
                               transform=self.ax.transAxes, verticalalignment='top',
                               bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.7))
        
        self.ax.set_title('回撤曲線 (Drawdown Curve)', fontsize=12, fontweight='bold')
        self.ax.set_xlabel('日期')
        self.ax.set_ylabel('回撤 (%)')
        self.ax.legend(loc='best')
        self.ax.grid(True, alpha=0.3)
        
        self.figure.autofmt_xdate()
        self.canvas.draw()


class TradeReturnHistogramWidget(QWidget):
    """交易報酬分佈直方圖"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.figure = Figure(figsize=(12, 8))  # 增大初始尺寸
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumSize(400, 300)  # 設置最小尺寸，但允許更大
        layout.addWidget(self.canvas)
        
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title('交易報酬分佈 (Trade Return Distribution)', fontsize=12, fontweight='bold')
        self.ax.set_xlabel('報酬率 (%)')
        self.ax.set_ylabel('頻率')
        self.ax.grid(True, alpha=0.3, axis='y')
    
    def plot(self, returns: np.ndarray, stats: Optional[Dict[str, float]] = None):
        """
        繪製交易報酬分佈
        
        Args:
            returns: 報酬率陣列（百分比）
            stats: 統計資訊（可選）
        """
        self.ax.clear()
        
        if returns is None or len(returns) == 0:
            self.ax.text(0.5, 0.5, '無資料', ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw()
            return
        
        # 繪製直方圖（單筆交易時使用較少的 bins）
        num_bins = min(30, max(5, len(returns)))  # 至少5個bins，最多30個
        n, bins, patches = self.ax.hist(returns, bins=num_bins, alpha=0.7, color='#2196F3', edgecolor='black')
        
        # 根據正負值設定顏色
        for i, (patch, bin_val) in enumerate(zip(patches, bins[:-1])):
            if bin_val < 0:
                patch.set_facecolor('#F44336')  # 紅色（虧損）
            else:
                patch.set_facecolor('#4CAF50')  # 綠色（獲利）
        
        # 顯示統計資訊
        if stats:
            mean = stats.get('mean', 0)
            median = stats.get('median', 0)
            var_95 = stats.get('var_95', 0)
            
            # 標記平均值和中位數
            self.ax.axvline(mean, color='blue', linestyle='--', linewidth=2, label=f'平均值: {mean:.2f}%')
            self.ax.axvline(median, color='orange', linestyle='--', linewidth=2, label=f'中位數: {median:.2f}%')
            
            # 標記 95% VaR
            if var_95 is not None:
                self.ax.axvline(var_95, color='red', linestyle=':', linewidth=2, label=f'95% VaR: {var_95:.2f}%')
        
        self.ax.set_title('交易報酬分佈 (Trade Return Distribution)', fontsize=12, fontweight='bold')
        self.ax.set_xlabel('報酬率 (%)')
        self.ax.set_ylabel('頻率')
        self.ax.legend(loc='best')
        self.ax.grid(True, alpha=0.3, axis='y')
        
        self.canvas.draw()


class HoldingDaysHistogramWidget(QWidget):
    """持有天數分佈直方圖"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.figure = Figure(figsize=(12, 8))  # 增大初始尺寸
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumSize(400, 300)  # 設置最小尺寸，但允許更大
        layout.addWidget(self.canvas)
        
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title('持有天數分佈 (Holding Period Distribution)', fontsize=12, fontweight='bold')
        self.ax.set_xlabel('持有天數')
        self.ax.set_ylabel('頻率')
        self.ax.grid(True, alpha=0.3, axis='y')
    
    def plot(self, holding_days: np.ndarray):
        """
        繪製持有天數分佈
        
        Args:
            holding_days: 持有天數陣列
        """
        self.ax.clear()
        
        if holding_days is None or len(holding_days) == 0:
            self.ax.text(0.5, 0.5, '無資料', ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw()
            return
        
        # 計算統計
        mean_days = np.mean(holding_days)
        median_days = np.median(holding_days)
        
        # 繪製直方圖（單筆交易時使用較少的 bins）
        max_days = int(np.max(holding_days)) if len(holding_days) > 0 else 1
        num_bins = min(30, max(5, max_days))  # 至少5個bins，最多30個
        self.ax.hist(holding_days, bins=num_bins, alpha=0.7, color='#9C27B0', edgecolor='black')
        
        # 標記平均值和中位數
        self.ax.axvline(mean_days, color='blue', linestyle='--', linewidth=2, 
                       label=f'平均: {mean_days:.1f} 天')
        self.ax.axvline(median_days, color='orange', linestyle='--', linewidth=2, 
                       label=f'中位數: {median_days:.1f} 天')
        
        # 判斷策略類型
        if mean_days <= 5:
            strategy_type = "短打策略"
        elif mean_days <= 20:
            strategy_type = "短線策略"
        elif mean_days <= 60:
            strategy_type = "波段策略"
        else:
            strategy_type = "長期策略"
        
        self.ax.set_title(f'持有天數分佈 (Holding Period Distribution) - {strategy_type}', 
                         fontsize=12, fontweight='bold')
        self.ax.set_xlabel('持有天數')
        self.ax.set_ylabel('頻率')
        self.ax.legend(loc='best')
        self.ax.grid(True, alpha=0.3, axis='y')
        
        self.canvas.draw()

