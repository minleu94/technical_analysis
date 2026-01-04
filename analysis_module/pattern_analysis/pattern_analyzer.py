import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks, argrelextrema
from scipy.spatial.distance import euclidean
from fastdtw import fastdtw
from scipy.optimize import curve_fit

class PatternAnalyzer:
    """價格圖形模式分析類"""
    
    def __init__(self):
        """初始化圖形模式分析器"""
        # 定義列名映射，將中文列名映射到英文列名
        self.column_mapping = {
            # 中文列名 -> 英文列名
            '收盤價': 'Close',
            '開盤價': 'Open',
            '最高價': 'High',
            '最低價': 'Low',
            '成交量': 'Volume',
            '成交股數': 'Volume'
        }
        # 反向映射，將英文列名映射到中文列名
        self.reverse_mapping = {v: k for k, v in self.column_mapping.items()}
        
        # 定義各種圖形模式的參數
        self.patterns = {
            'W底': {
                'description': '兩個相近的低點，中間有一個高點，形成W形狀',
                'bullish': True,  # 看漲形態
                'min_points': 5,  # 至少需要5個點來形成W底
                'max_points': 15  # 最多考慮15個點
            },
            '頭肩頂': {
                'description': '三個高點，中間的高點（頭）高於兩側的高點（肩），形成頭肩頂形態',
                'bullish': False,  # 看跌形態
                'min_points': 7,  # 至少需要7個點來形成頭肩頂
                'max_points': 20  # 最多考慮20個點
            },
            '頭肩底': {
                'description': '三個低點，中間的低點（頭）低於兩側的低點（肩），形成頭肩底形態',
                'bullish': True,  # 看漲形態
                'min_points': 7,  # 至少需要7個點來形成頭肩底
                'max_points': 20  # 最多考慮20個點
            },
            '雙頂': {
                'description': '兩個相近的高點，形成M形狀',
                'bullish': False,  # 看跌形態
                'min_points': 5,  # 至少需要5個點來形成雙頂
                'max_points': 15  # 最多考慮15個點
            },
            '雙底': {
                'description': '兩個相近的低點，形成W形狀',
                'bullish': True,  # 看漲形態
                'min_points': 5,  # 至少需要5個點來形成雙底
                'max_points': 15  # 最多考慮15個點
            },
            '三角形': {
                'description': '價格波動範圍逐漸縮小，形成三角形',
                'bullish': None,  # 可能是看漲或看跌，取決於三角形的類型
                'min_points': 5,  # 至少需要5個點來形成三角形
                'max_points': 30  # 最多考慮30個點
            },
            '旗形': {
                'description': '短期價格趨勢與主要趨勢相反，形成旗形',
                'bullish': None,  # 可能是看漲或看跌，取決於旗形的類型
                'min_points': 5,  # 至少需要5個點來形成旗形
                'max_points': 20  # 最多考慮20個點
            },
            'V形反轉': {
                'description': '價格快速下跌後立即快速上漲，形成V形',
                'bullish': True,  # 看漲形態
                'min_points': 3,  # 至少需要3個點來形成V形反轉
                'max_points': 10  # 最多考慮10個點
            },
            '圓頂': {
                'description': '價格緩慢上漲後緩慢下跌，形成圓弧形頂部',
                'bullish': False,  # 看跌形態
                'min_points': 7,  # 至少需要7個點來形成圓頂
                'max_points': 30  # 最多考慮30個點
            },
            '圓底': {
                'description': '價格緩慢下跌後緩慢上漲，形成圓弧形底部',
                'bullish': True,  # 看漲形態
                'min_points': 7,  # 至少需要7個點來形成圓底
                'max_points': 30  # 最多考慮30個點
            },
            '矩形': {
                'description': '價格在兩條平行的水平線之間波動，形成矩形',
                'bullish': None,  # 可能是看漲或看跌，取決於突破方向
                'min_points': 5,  # 至少需要5個點來形成矩形
                'max_points': 30  # 最多考慮30個點
            },
            '楔形': {
                'description': '價格在兩條收斂的趨勢線之間波動，形成楔形',
                'bullish': None,  # 可能是看漲或看跌，取決於楔形的類型
                'min_points': 5,  # 至少需要5個點來形成楔形
                'max_points': 30  # 最多考慮30個點
            }
        }
    
    def _get_column_name(self, df, eng_name):
        """獲取對應的列名，優先使用中文列名，如果不存在則使用英文列名
        
        Args:
            df: 數據DataFrame
            eng_name: 英文列名
            
        Returns:
            str: 對應的列名
        """
        # 檢查中文列名是否存在
        if self.reverse_mapping.get(eng_name) in df.columns:
            return self.reverse_mapping.get(eng_name)
        # 檢查英文列名是否存在
        elif eng_name in df.columns:
            return eng_name
        # 都不存在，返回None
        return None
    
    def find_peaks_and_troughs(self, df, price_col=None, window=5, prominence=1.0, prominence_atr_mult=None):
        """找出價格序列中的峰和谷
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 用於平滑的窗口大小
            prominence: 峰值的顯著性閾值（百分比模式，已棄用，保留向後兼容）
            prominence_atr_mult: 峰值的顯著性閾值（ATR 倍數模式，推薦使用）
            
        Returns:
            list: 包含峰和谷的列表，每個元素是一個字典，包含 type 和 idx 字段
        """
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 獲取價格數據並確保轉換為數值類型
        prices = pd.to_numeric(df[price_col], errors='coerce').values
        # 移除 NaN（使用前向填充和後向填充）
        if np.isnan(prices).any():
            prices_series = pd.Series(prices)
            prices_series = prices_series.ffill().bfill()
            prices = prices_series.values
        # 確保是 float 類型
        prices = prices.astype(float)
        
        # 優先使用 ATR-based prominence
        if prominence_atr_mult is not None:
            # 計算 ATR
            if 'ATR' in df.columns:
                atr_value = df['ATR'].mean()  # 使用平均 ATR
            else:
                # 簡單計算 ATR（使用 True Range）
                high_col = self._get_column_name(df, 'High')
                low_col = self._get_column_name(df, 'Low')
                if high_col and low_col:
                    tr_list = []
                    for i in range(len(df)):
                        if i == 0:
                            tr = df.iloc[i][high_col] - df.iloc[i][low_col]
                        else:
                            prev_close = df.iloc[i-1][price_col]
                            tr = max(
                                df.iloc[i][high_col] - df.iloc[i][low_col],
                                abs(df.iloc[i][high_col] - prev_close),
                                abs(df.iloc[i][low_col] - prev_close)
                            )
                        tr_list.append(tr)
                    atr_value = np.mean(tr_list) if tr_list else None
                else:
                    atr_value = None
            
            if atr_value is not None and atr_value > 0:
                relative_prominence = prominence_atr_mult * atr_value
            else:
                # 回退到百分比模式
                price_range = np.max(prices) - np.min(prices)
                relative_prominence = prominence * (price_range / 100)
        else:
            # 使用百分比模式（向後兼容）
            price_range = np.max(prices) - np.min(prices)
            relative_prominence = prominence * (price_range / 100)
        
        # 找出峰和谷，使用更高的prominence值來減少檢測到的峰和谷數量
        peaks, _ = find_peaks(prices, prominence=relative_prominence)
        troughs, _ = find_peaks(-prices, prominence=relative_prominence)
        
        # 將峰和谷組合成一個列表
        peaks_troughs = []
        for idx in peaks:
            peaks_troughs.append({'type': 'peak', 'idx': idx})
        for idx in troughs:
            peaks_troughs.append({'type': 'trough', 'idx': idx})
        
        # 按索引排序
        peaks_troughs.sort(key=lambda x: x['idx'])
        
        return peaks_troughs
    
    def identify_w_bottom(self, df, price_col=None, window=20, threshold=0.05, prominence=0.8, 
                          threshold_atr_mult=None, prominence_atr_mult=None):
        """識別W底形態
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 分析窗口大小
            threshold: 兩個低點之間的最大差異閾值（百分比模式，已棄用）
            prominence: 峰值的顯著性閾值（百分比模式，已棄用）
            threshold_atr_mult: 兩個低點之間的最大差異閾值（ATR 倍數模式，推薦使用）
            prominence_atr_mult: 峰值的顯著性閾值（ATR 倍數模式，推薦使用）
            
        Returns:
            list: 識別出的W底形態的位置列表，每個元素是字典格式
        """
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 獲取價格數據並確保轉換為數值類型
        prices = pd.to_numeric(df[price_col], errors='coerce').values
        # 移除 NaN（使用新的 API）
        if np.isnan(prices).any():
            prices_series = pd.Series(prices)
            prices_series = prices_series.ffill().bfill()
            prices = prices_series.values
        # 確保是 float 類型
        prices = prices.astype(float)
        
        # 找出峰和谷（優先使用 ATR-based prominence）
        peaks_troughs = self.find_peaks_and_troughs(
            df, price_col, prominence=prominence, prominence_atr_mult=prominence_atr_mult
        )
        
        # 分離峰和谷
        peaks = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'peak']
        troughs = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'trough']
        
        # 尋找W底形態
        w_bottoms = []
        
        # 計算 ATR（如果使用 ATR-based threshold）
        atr_value = None
        if threshold_atr_mult is not None:
            if 'ATR' in df.columns:
                atr_value = df['ATR'].mean()
            else:
                # 簡單計算 ATR
                high_col = self._get_column_name(df, 'High')
                low_col = self._get_column_name(df, 'Low')
                if high_col and low_col:
                    tr_list = []
                    for i in range(len(df)):
                        if i == 0:
                            tr = df.iloc[i][high_col] - df.iloc[i][low_col]
                        else:
                            prev_close = df.iloc[i-1][price_col]
                            tr = max(
                                df.iloc[i][high_col] - df.iloc[i][low_col],
                                abs(df.iloc[i][high_col] - prev_close),
                                abs(df.iloc[i][low_col] - prev_close)
                            )
                        tr_list.append(tr)
                    atr_value = np.mean(tr_list) if tr_list else None
        
        for i in range(len(troughs) - 1):
            # 檢查兩個谷之間是否有一個峰
            trough1_idx = troughs[i]
            trough2_idx = troughs[i + 1]
            
            # 檢查兩個谷之間的距離是否合適
            if trough2_idx - trough1_idx > window or trough2_idx - trough1_idx < 3:
                continue
            
            # 檢查兩個谷之間是否有峰
            peaks_between = [p for p in peaks if trough1_idx < p < trough2_idx]
            if not peaks_between:
                continue
            
            # 檢查兩個谷的價格是否相近（優先使用 ATR-based）
            if threshold_atr_mult is not None and atr_value is not None and atr_value > 0:
                price_diff_threshold = threshold_atr_mult * atr_value
                if abs(prices[trough1_idx] - prices[trough2_idx]) > price_diff_threshold:
                    continue
            else:
                # 使用百分比模式（向後兼容）
                price_range = np.max(prices) - np.min(prices)
                if abs(prices[trough1_idx] - prices[trough2_idx]) > threshold * price_range:
                    continue
            
            # 檢查峰的價格是否高於兩個谷
            peak_idx = peaks_between[0]  # 取第一個峰
            if prices[peak_idx] <= prices[trough1_idx] * 1.01 or prices[peak_idx] <= prices[trough2_idx] * 1.01:  # 要求峰比谷高至少1%
                continue
            
            # 檢查第一個谷之前是否有下跌趨勢
            if trough1_idx > 5:  # 只需要5個點來判斷趨勢
                pre_trough_prices = prices[trough1_idx-5:trough1_idx]
                if np.mean(pre_trough_prices[:3]) <= np.mean(pre_trough_prices[3:]):  # 使用更短的窗口來判斷趨勢
                    continue
            
            # 找到W底形態
            w_bottoms.append({
                'start_idx': trough1_idx,
                'end_idx': trough2_idx,
                'trough1_idx': trough1_idx,
                'trough2_idx': trough2_idx,
                'peak_idx': peak_idx,
                'pattern': 'W底',
                'direction': 'bullish'  # W底通常是看漲信號
            })
        
        return w_bottoms
    
    def identify_head_and_shoulders(self, df, price_col=None, window=30, threshold=0.1):
        """識別頭肩頂形態
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 分析窗口大小
            threshold: 兩個肩的高度差異閾值（相對於價格範圍）
            
        Returns:
            list: 識別出的頭肩頂形態的位置列表，每個元素是(開始索引, 結束索引)
        """
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 找出峰和谷
        peaks_troughs = self.find_peaks_and_troughs(df, price_col)
        
        # 分離峰和谷
        peaks = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'peak']
        troughs = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'trough']
        
        # 尋找頭肩頂形態
        hs_tops = []
        for i in range(len(peaks) - 2):
            # 檢查三個峰的位置是否合適
            left_shoulder_idx = peaks[i]
            head_idx = peaks[i + 1]
            right_shoulder_idx = peaks[i + 2]
            
            # 檢查三個峰之間的距離是否合適
            if right_shoulder_idx - left_shoulder_idx > window:
                continue
            
            # 檢查頭是否高於兩個肩
            if prices[head_idx] <= prices[left_shoulder_idx] or prices[head_idx] <= prices[right_shoulder_idx]:
                continue
            
            # 檢查兩個肩的高度是否相近
            price_range = np.max(prices) - np.min(prices)
            if abs(prices[left_shoulder_idx] - prices[right_shoulder_idx]) > threshold * price_range:
                continue
            
            # 檢查兩個肩之間是否有一個谷
            troughs_between_shoulders = [t for t in troughs if left_shoulder_idx < t < right_shoulder_idx]
            if len(troughs_between_shoulders) < 2:
                continue
            
            # 檢查頸線
            neckline_left_idx = troughs_between_shoulders[0]
            neckline_right_idx = troughs_between_shoulders[-1]
            
            # 找到頭肩頂形態
            hs_tops.append({
                'start_idx': left_shoulder_idx,
                'end_idx': right_shoulder_idx,
                'left_shoulder_idx': left_shoulder_idx,
                'head_idx': head_idx,
                'right_shoulder_idx': right_shoulder_idx,
                'neckline_left_idx': neckline_left_idx,
                'neckline_right_idx': neckline_right_idx,
                'pattern': '頭肩頂',
                'direction': 'bearish'  # 頭肩頂通常是看跌信號
            })
        
        return hs_tops
    
    def identify_double_top(self, df, price_col=None, window=30, threshold=0.05, prominence=1.5):
        """識別雙頂形態
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 分析窗口大小
            threshold: 兩個高點之間的最大差異閾值（相對於價格範圍）
            prominence: 峰值的顯著性閾值，用於find_peaks_and_troughs
            
        Returns:
            list: 識別出的雙頂形態的位置列表，每個元素是字典格式
        """
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 找出峰和谷，使用較高的prominence值以減少檢測到的雙頂
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, prominence=prominence)
        
        # 分離峰和谷
        peaks = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'peak']
        troughs = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'trough']
        
        # 尋找雙頂形態
        double_tops = []
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 計算價格範圍
        price_range = np.max(prices) - np.min(prices)
        
        for i in range(len(peaks) - 1):
            # 檢查兩個峰的位置是否合適
            peak1_idx = peaks[i]
            peak2_idx = peaks[i + 1]
            
            # 檢查兩個峰之間的距離是否合適
            if peak2_idx - peak1_idx > window or peak2_idx - peak1_idx < 5:  # 添加最小距離檢查
                continue
            
            # 檢查兩個峰之間是否有谷
            troughs_between = [t for t in troughs if peak1_idx < t < peak2_idx]
            if not troughs_between:
                continue
            
            # 檢查兩個峰的價格是否相近
            if abs(prices[peak1_idx] - prices[peak2_idx]) > threshold * price_range:
                continue
            
            # 檢查谷的價格是否低於兩個峰
            trough_idx = troughs_between[0]  # 取第一個谷
            if prices[trough_idx] >= prices[peak1_idx] * 0.98 or prices[trough_idx] >= prices[peak2_idx] * 0.98:  # 要求谷比峰低至少2%
                continue
            
            # 檢查第一個峰之前是否有明顯的上漲趨勢
            if peak1_idx > 10:  # 確保有足夠的數據點來判斷趨勢
                pre_peak_prices = prices[peak1_idx-10:peak1_idx]
                if np.mean(pre_peak_prices[:5]) >= np.mean(pre_peak_prices[5:]):  # 檢查趨勢是否向上
                    continue
            
            # 找到雙頂形態
            double_tops.append({
                'start_idx': peak1_idx,
                'end_idx': peak2_idx,
                'peak1_idx': peak1_idx,
                'peak2_idx': peak2_idx,
                'trough_idx': trough_idx,
                'pattern': '雙頂',
                'direction': 'bearish'  # 雙頂通常是看跌信號
            })
        
        return double_tops
    
    def identify_double_bottom(self, df, price_col=None, window=30, threshold=0.05, prominence=1.5):
        """識別雙底形態
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 分析窗口大小
            threshold: 兩個低點之間的最大差異閾值（相對於價格範圍）
            prominence: 峰值的顯著性閾值，用於find_peaks_and_troughs
            
        Returns:
            list: 識別出的雙底形態的位置列表，每個元素是字典格式
        """
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 找出峰和谷，使用較高的prominence值以減少檢測到的雙底
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, prominence=prominence)
        
        # 分離峰和谷
        peaks = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'peak']
        troughs = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'trough']
        
        # 尋找雙底形態
        double_bottoms = []
        
        # 計算價格範圍
        price_range = np.max(prices) - np.min(prices)
        
        for i in range(len(troughs) - 1):
            # 檢查兩個谷的位置是否合適
            trough1_idx = troughs[i]
            trough2_idx = troughs[i + 1]
            
            # 檢查兩個谷之間的距離是否合適
            if trough2_idx - trough1_idx > window or trough2_idx - trough1_idx < 5:  # 添加最小距離檢查
                continue
            
            # 檢查兩個谷之間是否有峰
            peaks_between = [p for p in peaks if trough1_idx < p < trough2_idx]
            if not peaks_between:
                continue
            
            # 檢查兩個谷的價格是否相近
            if abs(prices[trough1_idx] - prices[trough2_idx]) > threshold * price_range:
                continue
            
            # 檢查峰的價格是否高於兩個谷
            peak_idx = peaks_between[0]  # 取第一個峰
            if prices[peak_idx] <= prices[trough1_idx] * 1.02 or prices[peak_idx] <= prices[trough2_idx] * 1.02:  # 要求峰比谷高至少2%
                continue
                
            # 檢查第一個谷之前是否有明顯的下跌趨勢
            if trough1_idx > 10:  # 確保有足夠的數據點來判斷趨勢
                pre_trough_prices = prices[trough1_idx-10:trough1_idx]
                if np.mean(pre_trough_prices[:5]) <= np.mean(pre_trough_prices[5:]):  # 檢查趨勢是否向下
                    continue
            
            # 找到雙底形態
            double_bottoms.append({
                'start_idx': trough1_idx,
                'end_idx': trough2_idx,
                'trough1_idx': trough1_idx,
                'trough2_idx': trough2_idx,
                'peak_idx': peak_idx,
                'pattern': '雙底',
                'direction': 'bullish'  # 雙底通常是看漲信號
            })
        
        return double_bottoms
    
    def identify_triangle(self, df, price_col=None, volume_col=None, window=20, threshold=0.1, min_points=5, min_r_squared=0.6, min_height_ratio=0.02, max_height_converge=0.7):
        """識別三角形形態
        
        三角形形態有三種類型：對稱三角形、上升三角形和下降三角形。
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            volume_col: 成交量列名，如果為None則自動尋找
            window: 窗口大小，用於尋找局部極值
            threshold: 閾值，用於判斷價格變化是否顯著
            min_points: 最小數據點數，用於確保形態足夠明顯
            min_r_squared: 趨勢線擬合的最小R方值，用於確保趨勢線的可靠性
            min_height_ratio: 三角形高度與價格範圍的最小比例，用於確保三角形足夠明顯
            max_height_converge: 三角形高度收斂的最大比例，用於確保三角形足夠明顯
            
        Returns:
            list: 識別出的三角形形態的信息列表
        """
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 嘗試找到成交量列
        if volume_col is None:
            volume_col = self._get_column_name(df, 'Volume')
        
        # 找出所有的峰和谷
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, window=window)
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 計算價格範圍用於後續比較
        price_range = np.max(prices) - np.min(prices)
        
        # 初始化結果列表
        triangles = []
        
        # 遍歷所有可能的起始點，至少保證有足夠的點形成三角形
        for start_idx in range(len(peaks_troughs) - min_points + 1):
            # 嘗試不同的窗口大小，但不要過大以避免過度擬合
            for end_idx in range(start_idx + min_points - 1, min(start_idx + 30, len(peaks_troughs))):
                # 獲取窗口內的所有峰和谷
                window_points = peaks_troughs[start_idx:end_idx+1]
                
                # 如果窗口內的點太少，則跳過
                if len(window_points) < min_points:
                    continue
                
                # 獲取窗口內的所有峰值和谷值
                peaks = [p for p in window_points if p['type'] == 'peak']
                troughs = [p for p in window_points if p['type'] == 'trough']
                
                # 如果峰或谷太少，則跳過
                if len(peaks) < 2 or len(troughs) < 2:
                    continue
                
                # 獲取峰值和谷值的索引和價格
                peak_indices = [p['idx'] for p in peaks]
                peak_prices = [df.iloc[idx][price_col] for idx in peak_indices]
                trough_indices = [p['idx'] for p in troughs]
                trough_prices = [df.iloc[idx][price_col] for idx in trough_indices]
                
                # 實際窗口的起始和結束索引
                actual_start_idx = window_points[0]['idx']
                actual_end_idx = window_points[-1]['idx']
                
                # 確保窗口足夠大
                if actual_end_idx - actual_start_idx < min_points:
                    continue
                
                # 使用線性回歸擬合上下趨勢線
                try:
                    # 上趨勢線（連接峰值）
                    upper_slope, upper_intercept = np.polyfit(peak_indices, peak_prices, 1)
                    upper_line = upper_slope * np.array(peak_indices) + upper_intercept
                    upper_r_squared = 1 - np.sum((peak_prices - upper_line) ** 2) / np.sum((peak_prices - np.mean(peak_prices)) ** 2)
                    
                    # 下趨勢線（連接谷值）
                    lower_slope, lower_intercept = np.polyfit(trough_indices, trough_prices, 1)
                    lower_line = lower_slope * np.array(trough_indices) + lower_intercept
                    lower_r_squared = 1 - np.sum((trough_prices - lower_line) ** 2) / np.sum((trough_prices - np.mean(trough_prices)) ** 2)
                except:
                    # 如果擬合失敗，則跳過
                    continue
                
                # 檢查R方值是否達到最低要求
                if upper_r_squared < min_r_squared or lower_r_squared < min_r_squared:
                    continue
                
                # 檢查趨勢線的交點是否在合理範圍內
                try:
                    intersection_x = (lower_intercept - upper_intercept) / (upper_slope - lower_slope)
                except:
                    # 如果趨勢線平行，則不是三角形
                    continue
                
                # 檢查交點是否在窗口內或窗口後不遠處
                # 三角形的收斂點通常在形態結束後不遠處
                triangle_length = actual_end_idx - actual_start_idx
                if intersection_x < actual_start_idx or intersection_x > actual_end_idx + triangle_length:
                    continue
                
                # 計算三角形起點和終點的高度（上下趨勢線之間的距離）
                start_height = abs((upper_slope * actual_start_idx + upper_intercept) - (lower_slope * actual_start_idx + lower_intercept))
                end_height = abs((upper_slope * actual_end_idx + upper_intercept) - (lower_slope * actual_end_idx + lower_intercept))
                
                # 檢查三角形是否足夠收斂（終點高度應顯著小於起點高度）
                if end_height > start_height or end_height / start_height > max_height_converge:
                    continue
                
                # 檢查三角形高度是否足夠明顯
                if start_height < min_height_ratio * price_range:
                    continue
                
                # 檢查是否有足夠的接觸點
                upper_touches = 0
                lower_touches = 0
                price_indices = list(range(actual_start_idx, actual_end_idx + 1))
                
                for idx in price_indices:
                    if idx < len(prices):
                        price = prices[idx]
                        # 計算點到上下趨勢線的距離
                        upper_line_val = upper_slope * idx + upper_intercept
                        lower_line_val = lower_slope * idx + lower_intercept
                        
                        # 使用相對閾值
                        rel_threshold = threshold * price
                        
                        # 如果價格接近上趨勢線，則計為一次上趨勢線接觸
                        if abs(price - upper_line_val) < rel_threshold:
                            upper_touches += 1
                        
                        # 如果價格接近下趨勢線，則計為一次下趨勢線接觸
                        if abs(price - lower_line_val) < rel_threshold:
                            lower_touches += 1
                
                # 確保上下趨勢線都有足夠的接觸點
                if upper_touches < 2 or lower_touches < 2:
                    continue
                
                # 根據趨勢線的斜率確定三角形的類型
                if abs(upper_slope) < 0.0005 and abs(lower_slope) > 0.001:
                    # 上趨勢線幾乎水平，下趨勢線向上 -> 上升三角形（看漲）
                    pattern_type = '上升三角形'
                    direction = 'bullish'
                elif abs(lower_slope) < 0.0005 and abs(upper_slope) > 0.001:
                    # 下趨勢線幾乎水平，上趨勢線向下 -> 下降三角形（看跌）
                    pattern_type = '下降三角形'
                    direction = 'bearish'
                elif upper_slope < -0.001 and lower_slope > 0.001:
                    # 上趨勢線向下，下趨勢線向上 -> 對稱三角形
                    # 對稱三角形的突破方向取決於之前的趨勢
                    pattern_type = '對稱三角形'
                    
                    # 判斷之前的趨勢
                    pre_window = min(20, actual_start_idx)
                    if pre_window > 0:
                        pre_prices = prices[actual_start_idx-pre_window:actual_start_idx]
                        pre_slope = np.polyfit(range(len(pre_prices)), pre_prices, 1)[0]
                        if pre_slope > 0:
                            direction = 'bullish'  # 之前是上升趨勢，可能繼續上升
                        else:
                            direction = 'bearish'  # 之前是下降趨勢，可能繼續下降
                    else:
                        direction = 'unknown'  # 無法判斷之前的趨勢
                else:
                    # 不符合任何三角形模式
                    continue
                
                # 檢查成交量模式（如果有成交量數據）
                volume_pattern = 'unknown'
                if volume_col and volume_col in df.columns:
                    # 獲取窗口內的成交量
                    volumes = df.iloc[actual_start_idx:actual_end_idx+1][volume_col].values
                    
                    if len(volumes) > 0:
                        # 檢查成交量是否隨時間遞減（三角形形成過程中成交量通常遞減）
                        volume_slope = np.polyfit(range(len(volumes)), volumes, 1)[0]
                        
                        if volume_slope < 0:
                            volume_pattern = 'decreasing'  # 成交量遞減，符合三角形成交量特徵
                        else:
                            volume_pattern = 'increasing'  # 成交量遞增，不太符合三角形成交量特徵
                
                # 添加到結果列表
                triangles.append({
                    'start_idx': actual_start_idx,
                    'end_idx': actual_end_idx,
                    'upper_slope': upper_slope,
                    'upper_intercept': upper_intercept,
                    'upper_r_squared': upper_r_squared,
                    'lower_slope': lower_slope,
                    'lower_intercept': lower_intercept,
                    'lower_r_squared': lower_r_squared,
                    'intersection_x': intersection_x,
                    'start_height': start_height,
                    'end_height': end_height,
                    'height_ratio': start_height / price_range,
                    'convergence_ratio': end_height / start_height,
                    'upper_touches': upper_touches,
                    'lower_touches': lower_touches,
                    'volume_pattern': volume_pattern,
                    'pattern': '三角形',
                    'type': pattern_type,
                    'direction': direction
                })
        
        # 合併重疊的三角形
        i = 0
        while i < len(triangles):
            j = i + 1
            while j < len(triangles):
                # 如果兩個三角形重疊，則合併它們
                if (triangles[i]['start_idx'] <= triangles[j]['end_idx'] and 
                    triangles[j]['start_idx'] <= triangles[i]['end_idx']):
                    # 保留較長的三角形
                    if (triangles[j]['end_idx'] - triangles[j]['start_idx'] > 
                        triangles[i]['end_idx'] - triangles[i]['start_idx']):
                        triangles[i] = triangles[j]
                    triangles.pop(j)
                else:
                    j += 1
            i += 1
        
        return triangles
    
    def identify_flag(self, df, price_col=None, window=30, threshold=0.1, prominence=0.5, min_trend_strength=0.01):
        """識別旗形形態
        
        旗形是一種短期價格趨勢與主要趨勢相反的形態，形成旗形。
        通常出現在強勁的價格趨勢中的短暫停頓。
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 分析窗口大小
            threshold: 閾值參數，用於判斷趨勢線的平行性和價格接觸趨勢線的程度
            prominence: 峰谷檢測的顯著性參數，較小的值可以檢測到更多的峰和谷
            min_trend_strength: 最小趨勢強度，用於確保前期趨勢足夠顯著
            
        Returns:
            list: 識別出的旗形形態的位置列表，每個元素是字典格式
        """
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 找出峰和谷，使用較小的prominence值來檢測更多的波動
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, prominence=prominence)
        
        # 分離峰和谷
        peaks = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'peak']
        troughs = [pt['idx'] for pt in peaks_troughs if pt['type'] == 'trough']
        
        # 尋找旗形形態
        flags = []
        
        # 檢查每個可能的窗口
        for i in range(len(prices) - window):
            window_end = i + window
            
            # 獲取窗口前的價格趨勢
            if i < 20:
                continue  # 需要足夠的前期數據來確定趨勢
            
            # 計算前期趨勢
            pre_window_prices = prices[i-20:i]
            trend_coef = np.polyfit(range(20), pre_window_prices, 1)
            trend = trend_coef[0]
            
            # 檢查趨勢是否足夠顯著
            if abs(trend) < min_trend_strength * np.mean(pre_window_prices):
                continue  # 趨勢不夠顯著
            
            # 獲取窗口內的價格
            window_prices = prices[i:window_end]
            
            # 計算窗口內價格的趨勢線
            window_coef = np.polyfit(range(len(window_prices)), window_prices, 1)
            window_slope = window_coef[0]
            
            # 確保窗口內趨勢線的斜率與前期趨勢相反
            if (trend > 0 and window_slope >= 0) or (trend < 0 and window_slope <= 0):
                continue
            
            # 檢查窗口內價格是否在兩條平行線之間波動
            window_peaks = [p for p in peaks if i <= p < window_end]
            window_troughs = [t for t in troughs if i <= t < window_end]
            
            # 旗形只需要至少1個峰和1個谷，或者足夠的價格點來形成旗形
            if (len(window_peaks) < 1 or len(window_troughs) < 1) and len(window_prices) < 10:
                continue
            
            # 如果有足夠的峰和谷，則計算趨勢線
            if len(window_peaks) >= 1 and len(window_troughs) >= 1:
                try:
                    # 計算峰的趨勢線
                    peak_x = np.array([p - i for p in window_peaks])
                    peak_y = prices[window_peaks]
                    peak_slope, peak_intercept = np.polyfit(peak_x, peak_y, 1)
                    
                    # 計算谷的趨勢線
                    trough_x = np.array([t - i for t in window_troughs])
                    trough_y = prices[window_troughs]
                    trough_slope, trough_intercept = np.polyfit(trough_x, trough_y, 1)
                    
                    # 檢查兩條趨勢線是否近似平行
                    # 使用斜率的相對差異來判斷
                    slope_diff = abs(peak_slope - trough_slope)
                    avg_slope = (abs(peak_slope) + abs(trough_slope)) / 2
                    if avg_slope > 0 and slope_diff / avg_slope > 0.3:  # 斜率相對差異不超過30%
                        continue
                    
                    # 計算通道寬度
                    width = abs(peak_intercept - trough_intercept)
                    
                    # 如果通道寬度太窄或太寬，則不是有效的旗形
                    avg_price = np.mean(window_prices)
                    if width < 0.01 * avg_price or width > 0.1 * avg_price:
                        continue
                    
                    # 檢查價格是否在通道中波動
                    in_channel = 0
                    for j in range(len(window_prices)):
                        price = window_prices[j]
                        x = j
                        upper_line = peak_slope * x + peak_intercept
                        lower_line = trough_slope * x + trough_intercept
                        if lower_line - threshold * price <= price <= upper_line + threshold * price:
                            in_channel += 1
                    
                    # 如果超過70%的價格在通道中，則認為是有效的旗形
                    if in_channel < 0.7 * len(window_prices):
                        continue
                except:
                    # 如果計算失敗，則跳過
                    continue
            
            # 確定旗形類型和方向
            if trend > 0:
                flag_type = '看漲旗形'
                direction = 'bullish'  # 看漲旗形預示著上漲趨勢將繼續
            else:
                flag_type = '看跌旗形'
                direction = 'bearish'  # 看跌旗形預示著下跌趨勢將繼續
            
            # 找到旗形形態
            flag_data = {
                'start_idx': i,
                'end_idx': window_end,
                'pre_trend': trend,
                'flag_slope': window_slope,
                'type': flag_type,
                'direction': direction,
                'pattern': '旗形'
            }
            
            # 如果計算了趨勢線，則添加趨勢線信息
            if len(window_peaks) >= 1 and len(window_troughs) >= 1:
                flag_data.update({
                    'peak_slope': peak_slope,
                    'peak_intercept': peak_intercept,
                    'trough_slope': trough_slope,
                    'trough_intercept': trough_intercept,
                    'channel_width': width
                })
            
            flags.append(flag_data)
        
        # 合併重疊的旗形
        i = 0
        while i < len(flags):
            j = i + 1
            while j < len(flags):
                # 如果兩個旗形重疊，則合併它們
                if (flags[i]['start_idx'] <= flags[j]['end_idx'] and 
                    flags[j]['start_idx'] <= flags[i]['end_idx']):
                    # 保留較長的旗形
                    if (flags[j]['end_idx'] - flags[j]['start_idx'] > 
                        flags[i]['end_idx'] - flags[i]['start_idx']):
                        flags[i] = flags[j]
                    flags.pop(j)
                else:
                    j += 1
            i += 1
        
        return flags
    
    def identify_v_reversal(self, df, price_col=None, window=15, threshold=0.1):
        """識別V形反轉形態
        
        V形反轉是一種價格快速下跌後立即快速上漲的形態，形成V形。
        這種形態通常表示市場情緒從極度悲觀迅速轉變為樂觀。
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 窗口大小，用於尋找局部極值
            threshold: 閾值，用於判斷價格變化是否顯著
            
        Returns:
            list: 識別出的V形反轉的位置列表
        """
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 找出所有的峰和谷
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, window=window)
        
        # 初始化結果列表
        v_reversals = []
        
        # 遍歷所有的谷，尋找V形反轉
        for i in range(len(peaks_troughs) - 1):
            # 只考慮谷點
            if peaks_troughs[i]['type'] != 'trough':
                continue
            
            # 獲取當前谷點和下一個點
            current_trough = peaks_troughs[i]
            next_point = peaks_troughs[i + 1]
            
            # 如果下一個點是峰，且價格上漲顯著，則可能是V形反轉
            if next_point['type'] == 'peak':
                # 計算價格變化百分比
                price_change = (df.iloc[next_point['idx']][price_col] - df.iloc[current_trough['idx']][price_col]) / df.iloc[current_trough['idx']][price_col]
                
                # 如果價格上漲顯著，則識別為V形反轉
                if price_change > threshold:
                    # 計算V形反轉的起始和結束索引
                    start_idx = max(0, current_trough['idx'] - window // 2)
                    end_idx = min(len(df) - 1, next_point['idx'] + window // 2)
                    
                    # 計算V形反轉的深度（從前一個峰到谷的跌幅）
                    depth = 0
                    if i > 0 and peaks_troughs[i - 1]['type'] == 'peak':
                        prev_peak = peaks_troughs[i - 1]
                        depth = (df.iloc[prev_peak['idx']][price_col] - df.iloc[current_trough['idx']][price_col]) / df.iloc[prev_peak['idx']][price_col]
                    
                    # 計算V形反轉的高度（從谷到下一個峰的漲幅）
                    height = price_change
                    
                    # 計算V形反轉的角度（使用價格變化率的斜率）
                    angle = np.arctan(height / (next_point['idx'] - current_trough['idx'])) * 180 / np.pi
                    
                    # 添加到結果列表
                    v_reversals.append({
                        'start_idx': start_idx,
                        'end_idx': end_idx,
                        'trough_idx': current_trough['idx'],
                        'peak_idx': next_point['idx'],
                        'depth': depth,
                        'height': height,
                        'angle': angle,
                        'pattern': 'V形反轉',
                        'direction': 'bullish'  # V形反轉通常是看漲信號
                    })
        
        return v_reversals
    
    def identify_rounding_top(self, df, price_col=None, volume_col=None, window=30, min_width=15, min_curve=0.6, min_r_squared=0.7, min_height_ratio=0.03):
        """識別圓頂形態
        
        圓頂是一種價格曲線形成類似倒U型的反轉形態，通常是看跌信號。
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            volume_col: 成交量列名，如果為None則自動尋找
            window: 窗口大小，用於尋找局部極值
            min_width: 最小寬度，圓頂應至少具有的時間跨度
            min_curve: 最小曲率參數，確保形態足夠圓潤
            min_r_squared: 二次函數擬合的最小R方值，用於確保形態確實是曲線
            min_height_ratio: 圓頂高度與價格範圍的最小比例，用於確保圓頂足夠明顯
            
        Returns:
            list: 識別出的圓頂形態的信息列表
        """
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 尋找成交量列
        if volume_col is None:
            volume_col = self._get_column_name(df, 'Volume')
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 計算價格範圍用於後續比較
        price_range = np.max(prices) - np.min(prices)
        
        # 初始化結果列表
        rounding_tops = []
        
        # 找出所有的峰
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, window=window)
        peaks = [pt for pt in peaks_troughs if pt['type'] == 'peak']
        
        # 遍歷每個峰，檢查其是否形成圓頂
        for peak in peaks:
            peak_idx = peak['idx']
            
            # 確保有足夠的數據點在峰的兩側
            if peak_idx < min_width // 2 or peak_idx >= len(prices) - min_width // 2:
                continue
            
            # 嘗試不同的窗口大小來識別圓頂
            for w in range(min_width, min(window * 2, peak_idx, len(prices) - peak_idx - 1), 5):
                start_idx = max(0, peak_idx - w)
                end_idx = min(len(prices) - 1, peak_idx + w)
                
                # 如果窗口太小，則跳過
                if end_idx - start_idx < min_width:
                    continue
                
                # 獲取窗口內的價格和對應的時間索引
                window_prices = prices[start_idx:end_idx+1]
                window_indices = np.arange(len(window_prices))
                
                # 使用二次函數擬合窗口內的價格數據
                try:
                    # 二次函數擬合: y = ax^2 + bx + c
                    popt, _ = curve_fit(lambda x, a, b, c: a * x**2 + b * x + c, window_indices, window_prices)
                    a, b, c = popt
                    
                    # 生成擬合曲線
                    fitted_curve = a * window_indices**2 + b * window_indices + c
                    
                    # 計算R方值
                    ss_tot = np.sum((window_prices - np.mean(window_prices))**2)
                    ss_res = np.sum((window_prices - fitted_curve)**2)
                    r_squared = 1 - (ss_res / ss_tot)
                    
                except:
                    continue
                
                # 圓頂必須是向下彎曲的，即二次項係數a必須為負
                if a >= 0:
                    continue
                
                # 檢查擬合度是否足夠高
                if r_squared < min_r_squared:
                    continue
                
                # 計算曲線的最高點
                max_idx = -b / (2 * a)
                
                # 最高點應該接近窗口中間
                if max_idx < 0.3 * len(window_indices) or max_idx > 0.7 * len(window_indices):
                    continue
                
                # 計算圓頂的高度
                min_price = min(window_prices[0], window_prices[-1])
                max_price = window_prices[int(len(window_prices) // 2)]
                height = max_price - min_price
                
                # 檢查高度是否足夠明顯
                if height < min_height_ratio * price_range:
                    continue
                
                # 檢查曲率是否足夠（a值的絕對值越大，曲線越陡峭）
                curvature = abs(a)
                if curvature < min_curve / (window_indices[-1] ** 2):
                    continue
                
                # 檢查成交量模式（如果有成交量數據）
                volume_pattern = 'unknown'
                if volume_col and volume_col in df.columns:
                    # 獲取窗口內的成交量
                    volumes = df.iloc[start_idx:end_idx+1][volume_col].values
                    
                    if len(volumes) > 0:
                        # 檢查成交量是否在價格下降前達到高點（理想的圓頂成交量模式）
                        try:
                            # 分割窗口為前半部分（上升）和後半部分（下降）
                            mid_idx = len(window_indices) // 2
                            
                            # 前半部分成交量的趨勢
                            left_volumes = volumes[:mid_idx]
                            left_indices = np.arange(len(left_volumes))
                            left_slope = np.polyfit(left_indices, left_volumes, 1)[0]
                            
                            # 後半部分成交量的趨勢
                            right_volumes = volumes[mid_idx:]
                            right_indices = np.arange(len(right_volumes))
                            right_slope = np.polyfit(right_indices, right_volumes, 1)[0]
                            
                            if left_slope > 0 and right_slope < 0:
                                volume_pattern = 'rising_left_falling_right'  # 理想的圓頂成交量特徵
                            elif left_slope > 0:
                                volume_pattern = 'rising_left'  # 不完全符合圓頂成交量特徵
                            elif right_slope < 0:
                                volume_pattern = 'falling_right'  # 不完全符合圓頂成交量特徵
                            else:
                                volume_pattern = 'flat'  # 不符合圓頂成交量特徵
                        except:
                            pass
                
                # 添加到結果列表
                rounding_tops.append({
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'peak_idx': peak_idx,
                    'a_coef': a,  # 二次項係數
                    'b_coef': b,  # 一次項係數
                    'c_coef': c,  # 常數項
                    'r_squared': r_squared,  # 擬合度
                    'max_idx': max_idx,  # 最高點位置
                    'height': height,  # 圓頂高度
                    'height_ratio': height / price_range,  # 高度比例
                    'curvature': curvature,  # 曲率
                    'volume_pattern': volume_pattern,  # 成交量模式
                    'pattern': '圓頂',
                    'type': '圓頂',
                    'direction': 'bearish'  # 圓頂通常是看跌信號
                })
        
        # 合併重疊的圓頂
        i = 0
        while i < len(rounding_tops):
            j = i + 1
            while j < len(rounding_tops):
                # 如果兩個圓頂重疊，則合併它們
                if (rounding_tops[i]['start_idx'] <= rounding_tops[j]['end_idx'] and 
                    rounding_tops[j]['start_idx'] <= rounding_tops[i]['end_idx']):
                    # 保留擬合度較高的圓頂
                    if rounding_tops[j]['r_squared'] > rounding_tops[i]['r_squared']:
                        rounding_tops[i] = rounding_tops[j]
                    rounding_tops.pop(j)
                else:
                    j += 1
            i += 1
        
        return rounding_tops
    
    def identify_rounding_bottom(self, df, price_col=None, volume_col=None, window=30, min_width=15, min_curve=0.6, min_r_squared=0.7, min_depth_ratio=0.03):
        """識別圓底形態
        
        圓底是一種價格曲線形成類似U型的反轉形態，通常是看漲信號。
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            volume_col: 成交量列名，如果為None則自動尋找
            window: 窗口大小，用於尋找局部極值
            min_width: 最小寬度，圓底應至少具有的時間跨度
            min_curve: 最小曲率參數，確保形態足夠圓潤
            min_r_squared: 二次函數擬合的最小R方值，用於確保形態確實是曲線
            min_depth_ratio: 圓底深度與價格範圍的最小比例，用於確保圓底足夠明顯
            
        Returns:
            list: 識別出的圓底形態的信息列表
        """
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 尋找成交量列
        if volume_col is None:
            volume_col = self._get_column_name(df, 'Volume')
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 計算價格範圍用於後續比較
        price_range = np.max(prices) - np.min(prices)
        
        # 初始化結果列表
        rounding_bottoms = []
        
        # 找出所有的谷
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, window=window)
        troughs = [pt for pt in peaks_troughs if pt['type'] == 'trough']
        
        # 遍歷每個谷，檢查其是否形成圓底
        for trough in troughs:
            trough_idx = trough['idx']
            
            # 確保有足夠的數據點在谷的兩側
            if trough_idx < min_width // 2 or trough_idx >= len(prices) - min_width // 2:
                continue
            
            # 嘗試不同的窗口大小來識別圓底
            for w in range(min_width, min(window * 2, trough_idx, len(prices) - trough_idx - 1), 5):
                start_idx = max(0, trough_idx - w)
                end_idx = min(len(prices) - 1, trough_idx + w)
                
                # 如果窗口太小，則跳過
                if end_idx - start_idx < min_width:
                    continue
                
                # 獲取窗口內的價格和對應的時間索引
                window_prices = prices[start_idx:end_idx+1]
                window_indices = np.arange(len(window_prices))
                
                # 使用二次函數擬合窗口內的價格數據
                try:
                    # 二次函數擬合: y = ax^2 + bx + c
                    popt, _ = curve_fit(lambda x, a, b, c: a * x**2 + b * x + c, window_indices, window_prices)
                    a, b, c = popt
                    
                    # 生成擬合曲線
                    fitted_curve = a * window_indices**2 + b * window_indices + c
                    
                    # 計算R方值
                    ss_tot = np.sum((window_prices - np.mean(window_prices))**2)
                    ss_res = np.sum((window_prices - fitted_curve)**2)
                    r_squared = 1 - (ss_res / ss_tot)
                    
                except:
                    continue
                
                # 圓底必須是向上彎曲的，即二次項係數a必須為正
                if a <= 0:
                    continue
                
                # 檢查擬合度是否足夠高
                if r_squared < min_r_squared:
                    continue
                
                # 計算曲線的最低點
                min_idx = -b / (2 * a)
                
                # 最低點應該接近窗口中間
                if min_idx < 0.3 * len(window_indices) or min_idx > 0.7 * len(window_indices):
                    continue
                
                # 計算圓底的深度
                max_price = max(window_prices[0], window_prices[-1])
                min_price = window_prices[int(len(window_prices) // 2)]
                depth = max_price - min_price
                
                # 檢查深度是否足夠明顯
                if depth < min_depth_ratio * price_range:
                    continue
                
                # 檢查曲率是否足夠（a值越大，曲線越陡峭）
                curvature = abs(a)
                if curvature < min_curve / (window_indices[-1] ** 2):
                    continue
                
                # 檢查成交量模式（如果有成交量數據）
                volume_pattern = 'unknown'
                if volume_col and volume_col in df.columns:
                    # 獲取窗口內的成交量
                    volumes = df.iloc[start_idx:end_idx+1][volume_col].values
                    
                    if len(volumes) > 0:
                        # 檢查成交量是否隨價格上升而增加（理想的圓底成交量模式）
                        try:
                            # 分割窗口為前半部分（下降）和後半部分（上升）
                            mid_idx = len(window_indices) // 2
                            
                            # 後半部分成交量的趨勢
                            right_volumes = volumes[mid_idx:]
                            right_indices = np.arange(len(right_volumes))
                            right_slope = np.polyfit(right_indices, right_volumes, 1)[0]
                            
                            if right_slope > 0:
                                volume_pattern = 'rising_right'  # 右側成交量上升，符合圓底成交量特徵
                            elif right_slope < 0:
                                volume_pattern = 'falling_right'  # 右側成交量下降，不太符合圓底成交量特徵
                            else:
                                volume_pattern = 'flat'
                        except:
                            pass
                
                # 添加到結果列表
                rounding_bottoms.append({
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'trough_idx': trough_idx,
                    'a_coef': a,  # 二次項係數
                    'b_coef': b,  # 一次項係數
                    'c_coef': c,  # 常數項
                    'r_squared': r_squared,  # 擬合度
                    'min_idx': min_idx,  # 最低點位置
                    'depth': depth,  # 圓底深度
                    'depth_ratio': depth / price_range,  # 深度比例
                    'curvature': curvature,  # 曲率
                    'volume_pattern': volume_pattern,  # 成交量模式
                    'pattern': '圓底',
                    'type': '圓底',
                    'direction': 'bullish'  # 圓底通常是看漲信號
                })
        
        # 合併重疊的圓底
        i = 0
        while i < len(rounding_bottoms):
            j = i + 1
            while j < len(rounding_bottoms):
                # 如果兩個圓底重疊，則合併它們
                if (rounding_bottoms[i]['start_idx'] <= rounding_bottoms[j]['end_idx'] and 
                    rounding_bottoms[j]['start_idx'] <= rounding_bottoms[i]['end_idx']):
                    # 保留擬合度較高的圓底
                    if rounding_bottoms[j]['r_squared'] > rounding_bottoms[i]['r_squared']:
                        rounding_bottoms[i] = rounding_bottoms[j]
                    rounding_bottoms.pop(j)
                else:
                    j += 1
            i += 1
        
        return rounding_bottoms
    
    def identify_rectangle(self, df, price_col=None, window=30, threshold=0.05, min_touches=4):
        """識別矩形形態
        
        矩形是一種價格在兩條平行的水平線之間波動的形態，形成矩形。
        這種形態通常表示市場處於整理階段，等待突破。
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 窗口大小，用於尋找局部極值
            threshold: 閾值，用於判斷價格變化是否顯著
            min_touches: 最小接觸次數，價格至少需要接觸上下邊界的總次數
            
        Returns:
            list: 識別出的矩形形態的位置列表
        """
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 找出所有的峰和谷
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, window=window)
        
        # 初始化結果列表
        rectangles = []
        
        # 遍歷所有可能的起始點
        for start_idx in range(len(peaks_troughs) - min_touches + 1):
            # 嘗試不同的窗口大小
            for end_idx in range(start_idx + min_touches - 1, min(start_idx + 20, len(peaks_troughs))):
                # 獲取窗口內的所有峰和谷
                window_points = peaks_troughs[start_idx:end_idx+1]
                
                # 如果窗口內的點太少，則跳過
                if len(window_points) < min_touches:
                    continue
                
                # 獲取窗口內的所有峰值和谷值
                peaks = [p for p in window_points if p['type'] == 'peak']
                troughs = [p for p in window_points if p['type'] == 'trough']
                
                # 如果峰或谷太少，則跳過
                if len(peaks) < 2 or len(troughs) < 2:
                    continue
                
                # 計算峰值的平均值和標準差
                peak_values = [df.iloc[p['idx']][price_col] for p in peaks]
                peak_mean = np.mean(peak_values)
                peak_std = np.std(peak_values)
                
                # 計算谷值的平均值和標準差
                trough_values = [df.iloc[p['idx']][price_col] for p in troughs]
                trough_mean = np.mean(trough_values)
                trough_std = np.std(trough_values)
                
                # 如果峰值或谷值的標準差太大，則不是矩形
                if peak_std / peak_mean > threshold or trough_std / trough_mean > threshold:
                    continue
                
                # 計算矩形的高度
                height = peak_mean - trough_mean
                
                # 如果高度太小，則不是矩形
                if height / peak_mean < threshold:
                    continue
                
                # 檢查是否有足夠的接觸點
                touches = 0
                for p in window_points:
                    price = df.iloc[p['idx']][price_col]
                    # 如果價格接近上邊界或下邊界，則計為一次接觸
                    if abs(price - peak_mean) < threshold * peak_mean or abs(price - trough_mean) < threshold * trough_mean:
                        touches += 1
                
                # 如果接觸次數不夠，則不是矩形
                if touches < min_touches:
                    continue
                
                # 確定矩形的實際起始和結束索引
                actual_start_idx = window_points[0]['idx']
                actual_end_idx = window_points[-1]['idx']
                
                # 確定矩形的類型（看漲或看跌）
                # 如果最後一個點是向上突破，則是看漲矩形
                # 如果最後一個點是向下突破，則是看跌矩形
                last_idx = min(actual_end_idx + window, len(df) - 1)
                if last_idx > actual_end_idx:
                    last_price = df.iloc[last_idx][price_col]
                    if last_price > peak_mean + threshold * peak_mean:
                        direction = 'bullish'
                        pattern_type = '看漲矩形'
                    elif last_price < trough_mean - threshold * trough_mean:
                        direction = 'bearish'
                        pattern_type = '看跌矩形'
                    else:
                        direction = 'neutral'
                        pattern_type = '中性矩形'
                else:
                    direction = 'neutral'
                    pattern_type = '中性矩形'
                
                # 添加到結果列表
                rectangles.append({
                    'start_idx': actual_start_idx,
                    'end_idx': actual_end_idx,
                    'upper_bound': peak_mean,
                    'lower_bound': trough_mean,
                    'height': height,
                    'touches': touches,
                    'pattern': '矩形',
                    'type': pattern_type,
                    'direction': direction
                })
        
        # 合併重疊的矩形
        i = 0
        while i < len(rectangles):
            j = i + 1
            while j < len(rectangles):
                # 如果兩個矩形重疊，則合併它們
                if (rectangles[i]['start_idx'] <= rectangles[j]['end_idx'] and 
                    rectangles[j]['start_idx'] <= rectangles[i]['end_idx']):
                    # 保留較長的矩形
                    if (rectangles[j]['end_idx'] - rectangles[j]['start_idx'] > 
                        rectangles[i]['end_idx'] - rectangles[i]['start_idx']):
                        rectangles[i] = rectangles[j]
                    rectangles.pop(j)
                else:
                    j += 1
            i += 1
        
        return rectangles
    
    def identify_wedge(self, df, price_col=None, window=30, threshold=0.1, min_touches=4, min_r_squared=0.6, min_slope=0.005, min_height_ratio=0.03):
        """識別楔形形態
        
        楔形是一種價格在兩條收斂的趨勢線之間波動的形態，形成楔形。
        上升楔形通常是看跌信號，下降楔形通常是看漲信號。
        
        Args:
            df: 數據DataFrame
            price_col: 價格列名，如果為None則自動尋找
            window: 窗口大小，用於尋找局部極值
            threshold: 閾值，用於判斷價格變化是否顯著
            min_touches: 最小接觸次數，價格至少需要接觸上下趨勢線的總次數
            min_r_squared: 趨勢線擬合的最小R方值，用於確保趨勢線的可靠性
            min_slope: 趨勢線斜率的最小絕對值，用於確保趨勢線不是水平的
            min_height_ratio: 楔形高度與價格範圍的最小比例，用於確保楔形足夠明顯
            
        Returns:
            list: 識別出的楔形形態的位置列表
        """
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 找出所有的峰和谷
        peaks_troughs = self.find_peaks_and_troughs(df, price_col, window=window)
        
        # 獲取價格數據
        prices = df[price_col].values
        
        # 計算價格範圍用於後續比較
        price_range = np.max(prices) - np.min(prices)
        
        # 初始化結果列表
        wedges = []
        
        # 遍歷所有可能的起始點
        for start_idx in range(len(peaks_troughs) - min_touches + 1):
            # 嘗試不同的窗口大小
            for end_idx in range(start_idx + min_touches - 1, min(start_idx + 20, len(peaks_troughs))):
                # 獲取窗口內的所有峰和谷
                window_points = peaks_troughs[start_idx:end_idx+1]
                
                # 如果窗口內的點太少，則跳過
                if len(window_points) < min_touches:
                    continue
                
                # 獲取窗口內的所有峰值和谷值
                peaks = [p for p in window_points if p['type'] == 'peak']
                troughs = [p for p in window_points if p['type'] == 'trough']
                
                # 如果峰或谷太少，則跳過
                if len(peaks) < 2 or len(troughs) < 2:
                    continue
                
                # 獲取峰值和谷值的索引和價格
                peak_indices = [p['idx'] for p in peaks]
                peak_prices = [df.iloc[idx][price_col] for idx in peak_indices]
                trough_indices = [p['idx'] for p in troughs]
                trough_prices = [df.iloc[idx][price_col] for idx in trough_indices]
                
                # 使用線性回歸擬合上下趨勢線
                try:
                    # 上趨勢線
                    upper_slope, upper_intercept = np.polyfit(peak_indices, peak_prices, 1)
                    upper_line = upper_slope * np.array(peak_indices) + upper_intercept
                    upper_r_squared = 1 - np.sum((peak_prices - upper_line) ** 2) / np.sum((peak_prices - np.mean(peak_prices)) ** 2)
                    
                    # 下趨勢線
                    lower_slope, lower_intercept = np.polyfit(trough_indices, trough_prices, 1)
                    lower_line = lower_slope * np.array(trough_indices) + lower_intercept
                    lower_r_squared = 1 - np.sum((trough_prices - lower_line) ** 2) / np.sum((trough_prices - np.mean(trough_prices)) ** 2)
                except:
                    # 如果擬合失敗，則跳過
                    continue
                
                # 檢查R方值是否達到最低要求
                if upper_r_squared < min_r_squared or lower_r_squared < min_r_squared:
                    continue
                
                # 檢查趨勢線斜率是否顯著
                if abs(upper_slope) < min_slope or abs(lower_slope) < min_slope:
                    continue
                
                # 檢查趨勢線是否收斂
                if abs(upper_slope - lower_slope) < 0.0001:
                    # 如果趨勢線平行，則不是楔形
                    continue
                
                # 計算收斂點的x坐標
                try:
                    convergence_x = (lower_intercept - upper_intercept) / (upper_slope - lower_slope)
                except:
                    continue
                
                # 實際窗口的起始和結束索引
                actual_start_idx = window_points[0]['idx']
                actual_end_idx = window_points[-1]['idx']
                
                # 檢查收斂點是否在合理範圍內
                # 楔形的收斂點通常在形態結束後不遠處
                wedge_length = actual_end_idx - actual_start_idx
                if convergence_x < actual_start_idx or convergence_x > actual_end_idx + wedge_length * 2:
                    continue
                
                # 計算楔形起點的高度（上下趨勢線之間的距離）
                start_height = abs((upper_slope * actual_start_idx + upper_intercept) - (lower_slope * actual_start_idx + lower_intercept))
                end_height = abs((upper_slope * actual_end_idx + upper_intercept) - (lower_slope * actual_end_idx + lower_intercept))
                
                # 檢查楔形是否足夠收斂（起點高度應顯著大於終點高度）
                if start_height < end_height or end_height / start_height > 0.7:  # 至少要收斂30%
                    continue
                
                # 檢查楔形高度是否足夠明顯
                if start_height < min_height_ratio * price_range:
                    continue
                
                # 計算上下趨勢線的夾角
                angle = abs(np.arctan(upper_slope) - np.arctan(lower_slope)) * 180 / np.pi
                
                # 如果夾角太大或太小，則不是楔形
                if angle > 30 or angle < 5:  # 楔形的夾角通常在5-30度之間
                    continue
                
                # 檢查是否有足夠的接觸點
                touches = 0
                upper_touches = 0
                lower_touches = 0
                price_indices = list(range(actual_start_idx, actual_end_idx + 1))
                
                for idx in price_indices:
                    if idx < len(prices):
                        price = prices[idx]
                        # 計算點到上下趨勢線的距離
                        upper_line_val = upper_slope * idx + upper_intercept
                        lower_line_val = lower_slope * idx + lower_intercept
                        
                        # 使用相對閾值
                        rel_threshold = threshold * price
                        
                        # 如果價格接近上趨勢線，則計為一次上趨勢線接觸
                        if abs(price - upper_line_val) < rel_threshold:
                            touches += 1
                            upper_touches += 1
                        
                        # 如果價格接近下趨勢線，則計為一次下趨勢線接觸
                        if abs(price - lower_line_val) < rel_threshold:
                            touches += 1
                            lower_touches += 1
                
                # 確保上下趨勢線都有足夠的接觸點
                if touches < min_touches or upper_touches < 2 or lower_touches < 2:
                    continue
                
                # 確定楔形的類型（上升楔形或下降楔形）
                if upper_slope > 0 and lower_slope > 0 and upper_slope < lower_slope:
                    # 上升楔形：兩條趨勢線都向上，但下趨勢線的斜率大於上趨勢線
                    pattern_type = '上升楔形'
                    direction = 'bearish'  # 上升楔形通常是看跌信號
                elif upper_slope < 0 and lower_slope < 0 and upper_slope < lower_slope:
                    # 下降楔形：兩條趨勢線都向下，但下趨勢線的斜率大於上趨勢線
                    pattern_type = '下降楔形'
                    direction = 'bullish'  # 下降楔形通常是看漲信號
                else:
                    # 如果不符合上述類型，則不是標準的楔形
                    continue
                
                # 添加到結果列表
                wedges.append({
                    'start_idx': actual_start_idx,
                    'end_idx': actual_end_idx,
                    'upper_slope': upper_slope,
                    'upper_intercept': upper_intercept,
                    'upper_r_squared': upper_r_squared,
                    'lower_slope': lower_slope,
                    'lower_intercept': lower_intercept,
                    'lower_r_squared': lower_r_squared,
                    'convergence_x': convergence_x,
                    'angle': angle,
                    'start_height': start_height,
                    'end_height': end_height,
                    'height_ratio': start_height / price_range,
                    'convergence_ratio': end_height / start_height,
                    'touches': touches,
                    'upper_touches': upper_touches,
                    'lower_touches': lower_touches,
                    'pattern': '楔形',
                    'type': pattern_type,
                    'direction': direction
                })
        
        # 合併重疊的楔形
        i = 0
        while i < len(wedges):
            j = i + 1
            while j < len(wedges):
                # 如果兩個楔形重疊，則合併它們
                if (wedges[i]['start_idx'] <= wedges[j]['end_idx'] and 
                    wedges[j]['start_idx'] <= wedges[i]['end_idx']):
                    # 保留較長的楔形
                    if (wedges[j]['end_idx'] - wedges[j]['start_idx'] > 
                        wedges[i]['end_idx'] - wedges[i]['start_idx']):
                        wedges[i] = wedges[j]
                    wedges.pop(j)
                else:
                    j += 1
            i += 1
        
        return wedges
    
    def identify_pattern(self, df, pattern_type, price_col=None, **kwargs):
        """識別指定類型的圖形模式
        
        Args:
            df: 數據DataFrame
            pattern_type: 圖形模式類型，如'W底'、'頭肩頂'等
            price_col: 價格列名，如果為None則自動尋找
            **kwargs: 其他參數
            
        Returns:
            list: 識別出的圖形模式的位置列表
        """
        if pattern_type == 'W底':
            return self.identify_w_bottom(df, price_col, **kwargs)
        elif pattern_type == '頭肩頂':
            return self.identify_head_and_shoulders(df, price_col, **kwargs)
        elif pattern_type == '頭肩底':
            # 頭肩底是頭肩頂的倒置形式，可以通過將價格取反來識別
            if price_col is None:
                price_col = self._get_column_name(df, 'Close')
                if price_col is None:
                    raise ValueError("無法找到價格列")
            
            # 創建一個新的DataFrame，將價格取反
            df_inverted = df.copy()
            df_inverted[price_col] = -df_inverted[price_col]
            
            # 使用頭肩頂的方法識別頭肩底
            return self.identify_head_and_shoulders(df_inverted, price_col, **kwargs)
        elif pattern_type == '雙頂':
            return self.identify_double_top(df, price_col, **kwargs)
        elif pattern_type == '雙底':
            return self.identify_double_bottom(df, price_col, **kwargs)
        elif pattern_type == '三角形':
            return self.identify_triangle(df, price_col, **kwargs)
        elif pattern_type == '旗形':
            return self.identify_flag(df, price_col, **kwargs)
        elif pattern_type == 'V形反轉':
            return self.identify_v_reversal(df, price_col, **kwargs)
        elif pattern_type == '圓頂':
            return self.identify_rounding_top(df, price_col, **kwargs)
        elif pattern_type == '圓底':
            return self.identify_rounding_bottom(df, price_col, **kwargs)
        elif pattern_type == '矩形':
            return self.identify_rectangle(df, price_col, **kwargs)
        elif pattern_type == '楔形':
            return self.identify_wedge(df, price_col, **kwargs)
        else:
            raise ValueError(f"不支持的圖形模式類型: {pattern_type}")
    
    def plot_pattern(self, df, pattern_positions, pattern_type, price_col=None):
        """繪製識別出的圖形模式
        
        Args:
            df: 數據DataFrame
            pattern_positions: 圖形模式的位置列表
            pattern_type: 圖形模式類型
            price_col: 價格列名，如果為None則自動尋找
        """
        if not pattern_positions:
            print(f"未找到 {pattern_type} 形態")
            return
        
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 設置中文字體
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False
        
        # 繪製價格圖
        plt.figure(figsize=(12, 6))
        plt.plot(df.index, df[price_col], label=price_col)
        
        # 標記識別出的圖形模式
        for pos in pattern_positions:
            # 處理不同格式的模式位置
            if isinstance(pos, tuple) and len(pos) == 2:
                # 元組格式：(start_idx, end_idx)
                start_idx, end_idx = pos
            elif isinstance(pos, dict) and 'start_idx' in pos and 'end_idx' in pos:
                # 字典格式：{'start_idx': start_idx, 'end_idx': end_idx, ...}
                start_idx = pos['start_idx']
                end_idx = pos['end_idx']
            else:
                print(f"無法識別的模式位置格式: {pos}")
                continue
            
            plt.axvspan(df.index[start_idx], df.index[end_idx], alpha=0.2, color='red')
            plt.text(df.index[start_idx], df[price_col].iloc[start_idx], pattern_type, 
                     fontsize=12, color='red')
        
        plt.title(f'{pattern_type} 形態識別')
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
    
    def predict_from_pattern(self, df, pattern_positions, pattern_type, price_col=None, forecast_periods=20):
        """根據識別出的圖形模式進行預測
        
        Args:
            df: 數據DataFrame
            pattern_positions: 圖形模式的位置列表
            pattern_type: 圖形模式類型
            price_col: 價格列名，如果為None則自動尋找
            forecast_periods: 預測的期數
            
        Returns:
            DataFrame: 包含預測結果的DataFrame
        """
        if not pattern_positions:
            print(f"未找到 {pattern_type} 形態，無法進行預測")
            return None
        
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 設置中文字體
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False
        
        # 繪製價格圖
        plt.figure(figsize=(12, 6))
        plt.plot(df.index, df[price_col], label=price_col)
        
        # 預測結果
        forecasts = []
        
        # 對每個識別出的圖形模式進行預測
        for pos in pattern_positions:
            # 處理不同格式的模式位置
            if isinstance(pos, tuple) and len(pos) == 2:
                # 元組格式：(start_idx, end_idx)
                start_idx, end_idx = pos
                pattern_dict = {'start_idx': start_idx, 'end_idx': end_idx}
            elif isinstance(pos, dict) and 'start_idx' in pos and 'end_idx' in pos:
                # 字典格式：{'start_idx': start_idx, 'end_idx': end_idx, ...}
                pattern_dict = pos
                start_idx = pos['start_idx']
                end_idx = pos['end_idx']
            else:
                print(f"無法識別的模式位置格式: {pos}")
                continue
            
            # 根據圖形模式類型進行預測
            forecast = None
            if pattern_type == 'W底':
                # W底通常是看漲信號
                forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '頭肩頂':
                # 頭肩頂通常是看跌信號
                forecast = self._forecast_bearish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '頭肩底':
                # 頭肩底通常是看漲信號
                forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '雙頂':
                # 雙頂通常是看跌信號
                forecast = self._forecast_bearish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '雙底':
                # 雙底通常是看漲信號
                forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '三角形':
                # 三角形可能是看漲或看跌信號，根據類型決定
                if 'type' in pattern_dict and pattern_dict['type'] == 'ascending':
                    forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
                elif 'type' in pattern_dict and pattern_dict['type'] == 'descending':
                    forecast = self._forecast_bearish(df, end_idx, price_col, forecast_periods)
                else:
                    # 對稱三角形，根據突破方向決定
                    forecast = self._forecast_neutral(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '旗形':
                # 旗形可能是看漲或看跌信號，根據類型決定
                if 'direction' in pattern_dict and pattern_dict['direction'] == 'bullish':
                    forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
                else:
                    forecast = self._forecast_bearish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == 'V形反轉':
                # V形反轉通常是看漲信號
                forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '圓頂':
                # 圓頂通常是看跌信號
                forecast = self._forecast_bearish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '圓底':
                # 圓底通常是看漲信號
                forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '矩形':
                # 矩形可能是看漲或看跌信號，根據突破方向決定
                forecast = self._forecast_neutral(df, end_idx, price_col, forecast_periods)
            elif pattern_type == '楔形':
                # 楔形可能是看漲或看跌信號，根據類型決定
                if 'direction' in pattern_dict and pattern_dict['direction'] == 'bullish':
                    forecast = self._forecast_bullish(df, end_idx, price_col, forecast_periods)
                else:
                    forecast = self._forecast_bearish(df, end_idx, price_col, forecast_periods)
            else:
                print(f"未知的圖形模式類型: {pattern_type}")
                continue
            
            if forecast is not None:
                # 標記圖形模式
                plt.axvspan(df.index[start_idx], df.index[end_idx], alpha=0.2, color='red')
                plt.text(df.index[start_idx], df[price_col].iloc[start_idx], pattern_type, 
                         fontsize=12, color='red')
                
                # 繪製預測
                forecast_start = min(len(df) - 1, end_idx)
                forecast_end = min(len(df) - 1, end_idx + forecast_periods)
                
                if forecast_end > forecast_start:
                    forecast_index = df.index[forecast_start:forecast_end]
                    # 確保 forecast_index 和 forecast 長度匹配
                    if len(forecast_index) > len(forecast):
                        forecast_index = forecast_index[:len(forecast)]
                    elif len(forecast_index) < len(forecast):
                        forecast = forecast[:len(forecast_index)]
                    
                    plt.plot(forecast_index, forecast, 'g--', linewidth=2)
                
                # 添加到預測結果列表
                forecasts.append({
                    'pattern_type': pattern_type,
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'forecast': forecast
                })
        
        plt.title(f'{pattern_type} 形態預測')
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        
        return forecasts
    
    def evaluate_pattern_accuracy(self, df, pattern_type, pattern_positions=None, price_col=None, window=30, threshold=0.1, test_size=0.3):
        """評估圖形模式預測的準確性
        
        Args:
            df: 數據DataFrame
            pattern_type: 圖形模式類型
            pattern_positions: 圖形模式的位置列表，如果為None則自動識別
            price_col: 價格列名，如果為None則自動尋找
            window: 分析窗口大小
            threshold: 閾值
            test_size: 測試集大小
            
        Returns:
            dict: 包含準確性評估結果的字典
        """
        # 獲取價格列名
        if price_col is None:
            price_col = self._get_column_name(df, 'Close')
            if price_col is None:
                raise ValueError("無法找到價格列")
        
        # 如果沒有提供模式位置，則自動識別
        if pattern_positions is None:
            pattern_positions = self.identify_pattern(df, pattern_type, price_col)
        
        if not pattern_positions:
            print(f"未識別出 {pattern_type} 形態，無法評估準確性")
            return None
        
        # 評估每個模式的準確性
        direction_correct = 0
        magnitude_errors = []
        
        for pos in pattern_positions:
            # 處理不同格式的模式位置
            if isinstance(pos, tuple) and len(pos) == 2:
                # 元組格式：(start_idx, end_idx)
                start_idx, end_idx = pos
                pattern_dict = {'start_idx': start_idx, 'end_idx': end_idx}
            elif isinstance(pos, dict) and 'start_idx' in pos and 'end_idx' in pos:
                # 字典格式：{'start_idx': start_idx, 'end_idx': end_idx, ...}
                pattern_dict = pos
                start_idx = pos['start_idx']
                end_idx = pos['end_idx']
            else:
                print(f"無法識別的模式位置格式: {pos}")
                continue
            
            # 確保有足夠的後續數據來評估
            if end_idx + window >= len(df):
                continue
            
            # 獲取模式結束後的實際價格變化
            actual_future_prices = df[price_col].iloc[end_idx:end_idx+window]
            actual_price_change = actual_future_prices.iloc[-1] - actual_future_prices.iloc[0]
            
            # 預測價格變化的方向
            expected_direction = None
            
            # 根據圖形模式類型確定預期方向
            if pattern_type in ['W底', '頭肩底', '雙底', 'V形反轉', '圓底']:
                expected_direction = 'up'  # 看漲
            elif pattern_type in ['頭肩頂', '雙頂', '圓頂']:
                expected_direction = 'down'  # 看跌
            elif pattern_type == '三角形':
                # 三角形的方向取決於其類型
                if 'type' in pattern_dict:
                    if pattern_dict['type'] == 'ascending':
                        expected_direction = 'up'
                    elif pattern_dict['type'] == 'descending':
                        expected_direction = 'down'
                    else:  # 對稱三角形
                        # 對稱三角形的方向取決於突破方向，這裡簡單地根據最近的趨勢來預測
                        if start_idx > 20:
                            recent_trend = df[price_col].iloc[start_idx-20:start_idx].mean() < df[price_col].iloc[start_idx:end_idx+1].mean()
                            expected_direction = 'up' if recent_trend else 'down'
                        else:
                            expected_direction = 'up'  # 默認向上
            elif pattern_type == '旗形':
                # 旗形的方向取決於其類型
                if 'direction' in pattern_dict:
                    expected_direction = 'up' if pattern_dict['direction'] == 'bullish' else 'down'
                else:
                    expected_direction = 'up'  # 默認向上
            elif pattern_type == '矩形':
                # 矩形的方向取決於突破方向，這裡簡單地根據最近的趨勢來預測
                if start_idx > 20:
                    recent_trend = df[price_col].iloc[start_idx-20:start_idx].mean() < df[price_col].iloc[start_idx:end_idx+1].mean()
                    expected_direction = 'up' if recent_trend else 'down'
                else:
                    expected_direction = 'up'  # 默認向上
            elif pattern_type == '楔形':
                # 楔形的方向取決於其類型
                if 'direction' in pattern_dict:
                    expected_direction = 'up' if pattern_dict['direction'] == 'bullish' else 'down'
                else:
                    expected_direction = 'down'  # 默認向下
            else:
                print(f"未知的圖形模式類型: {pattern_type}")
                continue
            
            # 檢查預測方向是否正確
            actual_direction = 'up' if actual_price_change > 0 else 'down'
            if expected_direction == actual_direction:
                direction_correct += 1
            
            # 計算預測誤差
            # 使用預測方法生成預測
            if expected_direction == 'up':
                forecast = self._forecast_bullish(df, end_idx, price_col, window)
            else:
                forecast = self._forecast_bearish(df, end_idx, price_col, window)
            
            # 計算預測誤差
            forecast_errors = [abs(forecast[i] - actual_future_prices.iloc[i+1]) for i in range(min(len(forecast), len(actual_future_prices)-1))]
            if forecast_errors:
                magnitude_errors.append(sum(forecast_errors) / len(forecast_errors))
            
            # 將預測結果添加到模式字典中
            if isinstance(pos, dict):
                pos['forecast_direction'] = expected_direction
                pos['actual_direction'] = actual_direction
                pos['direction_correct'] = expected_direction == actual_direction
                pos['forecast_return'] = (forecast[-1] - actual_future_prices.iloc[0]) / actual_future_prices.iloc[0] * 100 if len(forecast) > 0 else 0
                pos['actual_return'] = actual_price_change / actual_future_prices.iloc[0] * 100
        
        # 計算準確性指標
        if len(pattern_positions) > 0:
            direction_accuracy = direction_correct / len(pattern_positions)
            mean_magnitude_error = sum(magnitude_errors) / len(magnitude_errors) if magnitude_errors else None
            
            return {
                'direction_accuracy': direction_accuracy,
                'mean_magnitude_error': mean_magnitude_error,
                'num_patterns': len(pattern_positions),
                'num_evaluated': len(magnitude_errors)
            }
        else:
            print(f"無法評估 {pattern_type} 形態的準確性，沒有足夠的後續數據")
            return None 
    
    def _forecast_bullish(self, df, end_idx, price_col, forecast_periods):
        """生成看漲預測
        
        Args:
            df: 數據DataFrame
            end_idx: 結束索引
            price_col: 價格列名
            forecast_periods: 預測的期數
            
        Returns:
            list: 預測價格列表
        """
        # 計算模式的高度
        if end_idx > 20:
            pattern_prices = df[price_col].iloc[end_idx-20:end_idx+1]
        else:
            pattern_prices = df[price_col].iloc[:end_idx+1]
        
        pattern_height = pattern_prices.max() - pattern_prices.min()
        last_price = df[price_col].iloc[end_idx]
        
        # 預測價格將上漲一個模式高度
        forecast = [last_price + pattern_height * (i / forecast_periods) for i in range(1, forecast_periods + 1)]
        
        return forecast
    
    def _forecast_bearish(self, df, end_idx, price_col, forecast_periods):
        """生成看跌預測
        
        Args:
            df: 數據DataFrame
            end_idx: 結束索引
            price_col: 價格列名
            forecast_periods: 預測的期數
            
        Returns:
            list: 預測價格列表
        """
        # 計算模式的高度
        if end_idx > 20:
            pattern_prices = df[price_col].iloc[end_idx-20:end_idx+1]
        else:
            pattern_prices = df[price_col].iloc[:end_idx+1]
        
        pattern_height = pattern_prices.max() - pattern_prices.min()
        last_price = df[price_col].iloc[end_idx]
        
        # 預測價格將下跌一個模式高度
        forecast = [last_price - pattern_height * (i / forecast_periods) for i in range(1, forecast_periods + 1)]
        
        return forecast
    
    def _forecast_neutral(self, df, end_idx, price_col, forecast_periods):
        """生成中性預測，根據最近趨勢決定方向
        
        Args:
            df: 數據DataFrame
            end_idx: 結束索引
            price_col: 價格列名
            forecast_periods: 預測的期數
            
        Returns:
            list: 預測價格列表
        """
        # 計算模式的高度
        if end_idx > 20:
            pattern_prices = df[price_col].iloc[end_idx-20:end_idx+1]
            # 根據最近的趨勢來預測
            recent_trend = df[price_col].iloc[end_idx-20:end_idx-10].mean() < df[price_col].iloc[end_idx-10:end_idx+1].mean()
        else:
            pattern_prices = df[price_col].iloc[:end_idx+1]
            # 如果沒有足夠的數據，則假設趨勢向上
            recent_trend = True
        
        pattern_height = pattern_prices.max() - pattern_prices.min()
        last_price = df[price_col].iloc[end_idx]
        
        # 根據趨勢預測價格
        if recent_trend:
            # 趨勢向上，預測價格將上漲
            forecast = [last_price + pattern_height * (i / forecast_periods) for i in range(1, forecast_periods + 1)]
        else:
            # 趨勢向下，預測價格將下跌
            forecast = [last_price - pattern_height * (i / forecast_periods) for i in range(1, forecast_periods + 1)]
        
        return forecast