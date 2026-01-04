"""
市場狀態判斷器（Market Regime Detector）
判斷當前市場應該使用哪種策略：Trend、Reversion、Breakout

改進版本（2025-12-20）：
1. 使用真正的 ADX（通過 ta 套件）
2. 添加 PLUS_DI 和 MINUS_DI 判斷趨勢方向
3. 改進 Trend 判斷：使用線性回歸斜率、趨勢距離
4. 改進 Breakout 判斷：使用 Bollinger Bandwidth 判斷壓縮
5. 改進 Reversion 判斷：添加均值回歸特徵
6. 實現動態 confidence 計算
7. 添加 Regime 抖動防護（連續確認機制）
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import json
import logging
import warnings

# 嘗試導入 ta 套件
try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logging.warning("ta 套件不可用，將使用簡化版 ADX 計算")

logger = logging.getLogger(__name__)


class MarketRegimeDetector:
    """市場狀態判斷器"""
    
    def __init__(self, config):
        """初始化市場狀態判斷器
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        
        # Regime 抖動防護：保存歷史狀態
        # 注意：resolve_output_path 用於目錄，對於文件需要手動構建路徑
        output_dir = config.resolve_output_path('')  # 獲取輸出目錄
        self.regime_history_file = output_dir / 'regime_history.json'
        self.regime_history = self._load_regime_history()
        
        # 抖動防護參數
        self.min_confirm_days = 2  # 至少連續 N 天才切換
        self.cooldown_days = 3  # 切換後至少鎖定 M 天
    
    def _load_regime_history(self) -> dict:
        """載入歷史 Regime 狀態"""
        if self.regime_history_file.exists():
            try:
                with open(self.regime_history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_regime_history(self, date: str, regime: str):
        """保存 Regime 歷史（使用原子寫入避免權限問題）"""
        self.regime_history[date] = {
            'regime': regime,
            'timestamp': datetime.now().isoformat()
        }
        try:
            # 確保目錄存在
            self.regime_history_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 先寫入臨時文件，然後重命名（原子操作）
            temp_file = self.regime_history_file.with_suffix('.json.tmp')
            
            # 寫入臨時文件
            json_str = json.dumps(self.regime_history, ensure_ascii=False, indent=2)
            temp_file.write_text(json_str, encoding='utf-8')
            
            # 驗證 JSON 是否有效
            json.loads(json_str)
            
            # 原子操作：直接重命名臨時文件為正式文件（不備份，避免權限問題）
            # 如果原文件存在且無法刪除，嘗試直接覆蓋
            if self.regime_history_file.exists():
                try:
                    # 嘗試刪除原文件
                    self.regime_history_file.unlink()
                except (PermissionError, OSError) as e:
                    # 如果無法刪除（文件被占用），嘗試直接覆蓋
                    logger.debug(f"無法刪除原文件，嘗試直接覆蓋: {e}")
                    try:
                        # 直接寫入原文件（覆蓋）
                        self.regime_history_file.write_text(json_str, encoding='utf-8')
                        # 刪除臨時文件
                        if temp_file.exists():
                            temp_file.unlink()
                        logger.debug(f"成功保存 Regime 歷史（直接覆蓋）: {self.regime_history_file}")
                        return
                    except Exception as e2:
                        logger.warning(f"直接覆蓋也失敗: {e2}")
                        raise
            
            # 如果原文件不存在或已刪除，重命名臨時文件
            try:
                temp_file.rename(self.regime_history_file)
                logger.debug(f"成功保存 Regime 歷史: {self.regime_history_file}")
            except Exception as e:
                # 如果重命名失敗，嘗試直接覆蓋
                logger.debug(f"重命名失敗，嘗試直接覆蓋: {e}")
                self.regime_history_file.write_text(json_str, encoding='utf-8')
                if temp_file.exists():
                    temp_file.unlink()
                logger.debug(f"成功保存 Regime 歷史（直接覆蓋）: {self.regime_history_file}")
                
        except Exception as e:
            logger.warning(f"保存 Regime 歷史失敗: {e}")
            # 清理臨時文件
            temp_file = self.regime_history_file.with_suffix('.json.tmp')
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except:
                    pass
    
    def _calculate_adx_and_di(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
        """計算真正的 ADX、PLUS_DI 和 MINUS_DI
        
        Args:
            high: 最高價序列
            low: 最低價序列
            close: 收盤價序列
            period: 計算週期
            
        Returns:
            tuple: (adx, plus_di, minus_di)
        """
        if TA_AVAILABLE:
            try:
                # 使用 ta 套件計算 ADX（抑制 RuntimeWarning）
                # ta 套件內部可能出現除以零的情況，這是正常的（會自動處理）
                adx = None
                plus_di = None
                minus_di = None
                
                # 抑制 RuntimeWarning（ta 套件內部會處理除以零的情況）
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*invalid value encountered.*')
                    
                    # 嘗試使用 length 參數
                    try:
                        adx = ta.trend.adx(high, low, close, length=period)
                    except TypeError:
                        # 嘗試不帶參數（使用默認值）
                        try:
                            adx = ta.trend.adx(high, low, close)
                        except TypeError:
                            # 如果還是不行，嘗試其他可能的參數名
                            try:
                                # 某些版本的 ta 可能使用 period 參數
                                adx = ta.trend.adx(high, low, close, period=period)
                            except:
                                raise
                
                # 如果 ta 套件沒有直接提供 DI，需要自己計算
                # ta 套件的 ADX 計算可能包含 DI，但我們需要自己計算以確保一致性
                # 計算 True Range
                tr1 = high - low
                tr2 = abs(high - close.shift(1))
                tr3 = abs(low - close.shift(1))
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                
                # 計算方向移動
                plus_dm = high.diff()
                minus_dm = -low.diff()
                
                # 只保留正向移動
                plus_dm[plus_dm < 0] = 0
                minus_dm[minus_dm < 0] = 0
                
                # 平滑處理（避免除以零）
                atr = tr.rolling(window=period, min_periods=1).mean()
                plus_dm_smooth = plus_dm.rolling(window=period, min_periods=1).mean()
                minus_dm_smooth = minus_dm.rolling(window=period, min_periods=1).mean()
                
                # 計算 DI（避免除以零）
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*invalid value encountered.*')
                    plus_di = 100 * (plus_dm_smooth / atr.replace(0, np.nan))
                    minus_di = 100 * (minus_dm_smooth / atr.replace(0, np.nan))
                
                # 處理 NaN 和 Inf
                plus_di = plus_di.replace([np.inf, -np.inf], np.nan).fillna(0)
                minus_di = minus_di.replace([np.inf, -np.inf], np.nan).fillna(0)
                adx = adx.replace([np.inf, -np.inf], np.nan).fillna(0) if adx is not None else pd.Series(0, index=high.index)
                
                return adx, plus_di, minus_di
            except Exception as e:
                logger.warning(f"使用 ta 套件計算 ADX 失敗: {e}，使用簡化版")
        
        # 簡化版（如果 ta 不可用）
        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=period, min_periods=1).mean()
        
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        plus_dm_smooth = plus_dm.rolling(window=period, min_periods=1).mean()
        minus_dm_smooth = minus_dm.rolling(window=period, min_periods=1).mean()
        
        plus_di = 100 * (plus_dm_smooth / atr.replace(0, np.nan)).fillna(0)
        minus_di = 100 * (minus_dm_smooth / atr.replace(0, np.nan)).fillna(0)
        
        # 簡化版 ADX（使用 DI 的差異）
        di_diff = abs(plus_di - minus_di)
        di_sum = plus_di + minus_di
        adx = 100 * (di_diff / di_sum.replace(0, np.nan)).fillna(0)
        adx = adx.rolling(window=period, min_periods=1).mean()
        
        return adx, plus_di, minus_di
    
    def _calculate_ma_slope(self, ma_series: pd.Series, period: int = 7) -> float:
        """計算移動平均線的斜率（使用線性回歸）
        
        Args:
            ma_series: 移動平均線序列
            period: 計算週期
            
        Returns:
            float: 斜率（正數表示上升，負數表示下降）
        """
        if len(ma_series) < period:
            return 0.0
        
        recent = ma_series.iloc[-period:].values
        x = np.arange(len(recent))
        
        # 線性回歸
        coeffs = np.polyfit(x, recent, 1)
        slope = coeffs[0]
        
        # 標準化為百分比變化
        if len(recent) > 0 and recent[0] != 0:
            slope_pct = (slope * period) / recent[0] * 100
        else:
            slope_pct = 0.0
        
        return slope_pct
    
    def _calculate_bollinger_bandwidth(self, close: pd.Series, window: int = 20, std_dev: float = 2) -> pd.Series:
        """計算布林帶寬度（用於判斷壓縮）
        
        Args:
            close: 收盤價序列
            window: 移動平均週期
            std_dev: 標準差倍數
            
        Returns:
            Series: 帶寬序列（百分比）
        """
        ma = close.rolling(window=window, min_periods=1).mean()
        std = close.rolling(window=window, min_periods=1).std()
        
        upper = ma + (std * std_dev)
        lower = ma - (std * std_dev)
        
        # 帶寬 = (上軌 - 下軌) / 中軌
        bandwidth = ((upper - lower) / ma.replace(0, np.nan)) * 100
        return bandwidth.fillna(0)
    
    def detect_regime(self, date: str = None) -> dict:
        """檢測市場狀態
        
        Args:
            date: 日期（YYYY-MM-DD格式），如果為None則使用最新日期
            
        Returns:
            dict: {
                'regime': 'Trend' | 'Reversion' | 'Breakout',
                'confidence': float,  # 0-1
                'details': dict  # 詳細判斷依據
            }
        """
        # 讀取大盤數據
        market_file = self.config.market_index_file
        if not market_file.exists():
            return {
                'regime': 'Trend',  # 預設
                'confidence': 0.5,
                'details': {'error': '找不到大盤數據文件'}
            }
        
        try:
            df = pd.read_csv(market_file, encoding='utf-8-sig')
            
            # 處理日期欄位
            date_col = None
            for col in ['Date', '日期', 'date']:
                if col in df.columns:
                    date_col = col
                    break
            
            if date_col is None:
                return {
                    'regime': 'Trend',
                    'confidence': 0.5,
                    'details': {'error': '找不到日期欄位'}
                }
            
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            df = df[df[date_col].notna()].sort_values(date_col)
            
            # 如果指定日期，篩選到該日期
            if date:
                target_date = pd.to_datetime(date)
                df = df[df[date_col] <= target_date]
            else:
                # 使用最新日期
                date = df[date_col].iloc[-1].strftime('%Y-%m-%d')
            
            if len(df) < 60:
                return {
                    'regime': 'Trend',
                    'confidence': 0.5,
                    'details': {'error': '數據不足'}
                }
            
            # 獲取價格欄位
            close_col = None
            high_col = None
            low_col = None
            volume_col = None
            
            for col in ['Close', '收盤價', 'close']:
                if col in df.columns:
                    close_col = col
                    break
            for col in ['High', '最高價', 'high']:
                if col in df.columns:
                    high_col = col
                    break
            for col in ['Low', '最低價', 'low']:
                if col in df.columns:
                    low_col = col
                    break
            for col in ['Volume', '成交量', 'volume', '成交股數']:
                if col in df.columns:
                    volume_col = col
                    break
            
            if close_col is None:
                return {
                    'regime': 'Trend',
                    'confidence': 0.5,
                    'details': {'error': '找不到收盤價欄位'}
                }
            
            # 獲取價格序列
            close = pd.to_numeric(df[close_col], errors='coerce')
            high = pd.to_numeric(df[high_col], errors='coerce') if high_col else close
            low = pd.to_numeric(df[low_col], errors='coerce') if low_col else close
            volume = pd.to_numeric(df[volume_col], errors='coerce') if volume_col else None
            
            # 填充 NaN
            close = close.ffill().bfill()
            high = high.fillna(close) if high_col else close
            low = low.fillna(close) if low_col else close
            
            # 計算技術指標
            ma20 = close.rolling(window=20, min_periods=1).mean()
            ma60 = close.rolling(window=60, min_periods=1).mean()
            
            # 計算真正的 ADX 和 DI
            adx, plus_di, minus_di = self._calculate_adx_and_di(high, low, close, period=14)
            
            # 計算 ATR
            if high_col and low_col:
                tr = pd.concat([
                    high - low,
                    abs(high - close.shift(1)),
                    abs(low - close.shift(1))
                ], axis=1).max(axis=1)
                atr = tr.rolling(window=14, min_periods=1).mean()
            else:
                price_change = abs(close.pct_change())
                atr = price_change.rolling(window=14, min_periods=1).mean() * close
            
            # 計算 MA20 斜率（使用線性回歸）
            ma20_slope = self._calculate_ma_slope(ma20, period=7)
            
            # 計算布林帶寬度
            bb_bandwidth = self._calculate_bollinger_bandwidth(close, window=20, std_dev=2)
            
            # 計算 RSI（用於 Reversion 判斷）
            if TA_AVAILABLE:
                try:
                    rsi = ta.momentum.rsi(close, window=14)
                except:
                    rsi = None
            else:
                rsi = None
            
            # 獲取最新值
            latest_close = close.iloc[-1]
            latest_ma20 = ma20.iloc[-1]
            latest_ma60 = ma60.iloc[-1]
            latest_atr = atr.iloc[-1] if len(atr) > 0 else 0
            latest_adx = adx.iloc[-1] if len(adx) > 0 else 0
            latest_plus_di = plus_di.iloc[-1] if len(plus_di) > 0 else 0
            latest_minus_di = minus_di.iloc[-1] if len(minus_di) > 0 else 0
            latest_bb_bandwidth = bb_bandwidth.iloc[-1] if len(bb_bandwidth) > 0 else 0
            latest_rsi = rsi.iloc[-1] if rsi is not None and len(rsi) > 0 else None
            
            # 計算趨勢距離（相對於 MA60）
            trend_distance = (latest_close - latest_ma60) / latest_atr if latest_atr > 0 else 0
            
            # 判斷 Regime（帶抖動防護）
            regime_result = self._classify_regime(
                latest_close, latest_ma20, latest_ma60,
                ma20_slope, latest_adx, latest_plus_di, latest_minus_di,
                latest_atr, atr, latest_bb_bandwidth, bb_bandwidth,
                latest_rsi, trend_distance, volume, date
            )
            
            return regime_result
            
        except Exception as e:
            logger.error(f"檢測市場狀態失敗: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'regime': 'Trend',
                'confidence': 0.5,
                'details': {'error': str(e)}
            }
    
    def _apply_regime_hysteresis(self, new_regime: str, date: str) -> str:
        """應用 Regime 抖動防護（hysteresis）- 改進版
        
        實現「兩天確認」和「切換冷卻」機制：
        1. 今日新 regime ≠ 昨日 regime 時 → 先標記為 candidate_regime
        2. 連續 2 天一致才正式切換
        3. 切換後鎖 3 天不切回（cooldown）
        
        Args:
            new_regime: 新檢測到的 Regime
            date: 當前日期
            
        Returns:
            str: 最終的 Regime（可能被防護機制修改）
        """
        # 獲取最近 N 天的 Regime 歷史（按日期排序）
        sorted_history = sorted(self.regime_history.items(), reverse=True)
        
        if len(sorted_history) == 0:
            # 沒有歷史，直接保存
            self._save_regime_history(date, new_regime)
            return new_regime
        
        # 獲取最近幾天的 Regime 和日期
        recent_regimes = []
        recent_dates = []
        for hist_date, hist_data in sorted_history[:self.min_confirm_days + self.cooldown_days]:
            recent_regimes.append(hist_data.get('regime'))
            recent_dates.append(hist_date)
        
        # 檢查 cooldown：如果最近切換過，鎖定當前 Regime
        if len(recent_regimes) >= self.cooldown_days:
            # 檢查最近 cooldown_days 天內是否有切換
            for i in range(min(self.cooldown_days, len(recent_regimes) - 1)):
                if recent_regimes[i] != recent_regimes[i + 1]:
                    # 發現切換，檢查是否在 cooldown 期內
                    # 如果切換發生在 cooldown 期內，保持當前 Regime
                    if recent_regimes[0] != new_regime:
                        logger.debug(f"Regime 切換在 cooldown 期內（{self.cooldown_days}天），保持當前 Regime: {recent_regimes[0]}")
                        return recent_regimes[0]
                    break
        
        # 檢查連續確認：如果新 Regime 與昨日不同，需要連續確認
        if len(recent_regimes) > 0:
            last_regime = recent_regimes[0]
            if last_regime != new_regime:
                # 新檢測的與昨日不同，檢查是否有 candidate_regime
                # 如果最近有 candidate_regime 且與新檢測一致，則確認切換
                if len(recent_regimes) >= 2:
                    # 檢查是否有 candidate_regime（昨天可能是 candidate）
                    # 如果昨天是 candidate 且今天一致，則確認切換
                    if recent_regimes[1] == new_regime:
                        # 連續兩天一致，確認切換
                        logger.debug(f"Regime 連續兩天確認，從 {last_regime} 切換到 {new_regime}")
                        self._save_regime_history(date, new_regime)
                        return new_regime
                    else:
                        # 昨天不是 candidate，今天標記為 candidate（但還不切換）
                        logger.debug(f"Regime 首次檢測到 {new_regime}，標記為 candidate（昨日: {last_regime}）")
                        # 保存為 candidate（在 details 中標記）
                        self._save_regime_history(date, new_regime)
                        # 但返回原 Regime（需要明天確認）
                        return last_regime
                else:
                    # 歷史不足，標記為 candidate
                    logger.debug(f"歷史不足，標記 {new_regime} 為 candidate")
                    self._save_regime_history(date, new_regime)
                    return last_regime
        
        # 沒有切換，直接保存
        self._save_regime_history(date, new_regime)
        return new_regime
    
    def _classify_regime(
        self, close, ma20, ma60, ma20_slope, adx_value, plus_di, minus_di,
        latest_atr, atr_series, latest_bb_bandwidth, bb_bandwidth_series,
        rsi_value, trend_distance, volume_series, date: str
    ):
        """分類市場狀態（改進版）"""
        details = {}
        
        # 1. Trend（趨勢追蹤）- 結構分 + 強度分設計
        trend_conditions = {}
        
        # ===== A. Structure Score（結構分，0~1）=====
        # 判斷是否具備趨勢結構，每項權重相等
        structure_conditions = []
        
        # 條件 1: close > ma60
        close_above_ma60 = close > ma60
        structure_conditions.append(close_above_ma60)
        trend_conditions['close_above_ma60'] = close_above_ma60
        
        # 條件 2: ma20_slope > 0.1
        ma20_slope_positive = ma20_slope > 0.1
        structure_conditions.append(ma20_slope_positive)
        trend_conditions['ma20_slope_positive'] = ma20_slope_positive
        
        # 條件 3: plus_di > minus_di
        plus_di_above_minus_di = plus_di > minus_di
        structure_conditions.append(plus_di_above_minus_di)
        trend_conditions['plus_di_above_minus_di'] = plus_di_above_minus_di
        
        # 計算結構分：條件成立數量 / 3
        structure_score = sum(structure_conditions) / 3.0
        trend_conditions['structure_score'] = structure_score
        
        # ===== B. Strength Score（強度分，0~1）=====
        # 判斷趨勢強度，來源：ADX 強度 + 趨勢距離
        
        # ADX 強度（連續函數）
        # ADX 20 → 0.6
        # ADX 25 → 0.8
        # ADX 30 → 1.0
        if adx_value >= 30:
            adx_contribution = 1.0
        elif adx_value >= 25:
            # 25-30 之間：0.8 到 1.0
            adx_contribution = 0.8 + (adx_value - 25) / 5 * 0.2
        elif adx_value >= 20:
            # 20-25 之間：0.6 到 0.8
            adx_contribution = 0.6 + (adx_value - 20) / 5 * 0.2
        elif adx_value >= 15:
            # 15-20 之間：0.3 到 0.6
            adx_contribution = 0.3 + (adx_value - 15) / 5 * 0.3
        else:
            # < 15：趨勢很弱
            adx_contribution = adx_value / 15 * 0.3
        
        trend_conditions['adx_value'] = adx_value
        trend_conditions['adx_contribution'] = adx_contribution
        
        # 趨勢距離（ATR 標準化）
        # trend_distance / 2.0，上限 capped 在 1.0（2 ATR 視為滿分）
        distance_contribution = min(trend_distance / 2.0, 1.0)
        trend_conditions['trend_distance'] = trend_distance
        trend_conditions['distance_contribution'] = distance_contribution
        
        # 強度分 = (ADX 強度 + 趨勢距離) / 2
        strength_score = (adx_contribution + distance_contribution) / 2.0
        trend_conditions['strength_score'] = strength_score
        
        # ===== C. 最終 Trend Confidence =====
        # 使用加權平均：0.65 * structure_score + 0.35 * strength_score
        trend_confidence = 0.65 * structure_score + 0.35 * strength_score
        trend_conditions['trend_confidence'] = trend_confidence
        
        # ===== Trend 判斷門檻 =====
        # 必須同時滿足：
        # 1. structure_score >= 0.67（至少 3 個結構條件中有 2 個成立）
        # 2. trend_confidence >= 0.70
        trend_condition = (structure_score >= 0.67) and (trend_confidence >= 0.70)
        
        if trend_condition:
            details.update({
                'close': close,
                'ma20': ma20,
                'ma60': ma60,
                'ma20_slope': ma20_slope,
                'adx': adx_value,
                'plus_di': plus_di,
                'minus_di': minus_di,
                **trend_conditions
            })
            
            final_regime = self._apply_regime_hysteresis('Trend', date)
            return {
                'regime': final_regime,
                'confidence': trend_confidence,
                'details': details
            }
        
        # 2. Breakout-ready（突破準備）- 改進版
        breakout_score = 0.0
        breakout_conditions = {}
        
        # 條件 1: 布林帶寬度壓縮（在近 N 天的低分位）
        if len(bb_bandwidth_series) >= 20:
            recent_bandwidth = bb_bandwidth_series.iloc[-20:]
            bandwidth_percentile = (recent_bandwidth < latest_bb_bandwidth).sum() / len(recent_bandwidth)
            if bandwidth_percentile < 0.2:  # 在最低 20% 分位
                breakout_score += 0.4
                breakout_conditions['bandwidth_compressed'] = True
            else:
                breakout_conditions['bandwidth_compressed'] = False
        else:
            breakout_conditions['bandwidth_compressed'] = False
        
        # 條件 2: 價格在區間內
        if abs(close - ma20) / ma20 < 0.03:  # 價格接近 MA20（3% 以內）
            breakout_score += 0.3
            breakout_conditions['price_in_range'] = True
        else:
            breakout_conditions['price_in_range'] = False
        
        # 條件 3: ADX 低（趨勢不強）
        if adx_value < 25:
            breakout_score += 0.2
            breakout_conditions['adx_low'] = True
        else:
            breakout_conditions['adx_low'] = False
        
        # 條件 4: 成交量條件（如果有數據）
        if volume_series is not None and len(volume_series) >= 20:
            recent_volume = volume_series.iloc[-20:].mean()
            current_volume = volume_series.iloc[-1]
            if current_volume > recent_volume * 1.2:  # 成交量放大
                breakout_score += 0.1
                breakout_conditions['volume_expanding'] = True
            else:
                breakout_conditions['volume_expanding'] = False
        else:
            breakout_conditions['volume_expanding'] = False
        
        breakout_confidence = min(breakout_score, 1.0)
        breakout_condition = breakout_confidence >= 0.5  # 至少 50% 的條件滿足
        
        if breakout_condition:
            details.update({
                'close': close,
                'ma20': ma20,
                'bb_bandwidth': latest_bb_bandwidth,
                'adx': adx_value,
                'breakout_score': breakout_score,
                **breakout_conditions
            })
            
            final_regime = self._apply_regime_hysteresis('Breakout', date)
            return {
                'regime': final_regime,
                'confidence': breakout_confidence,
                'details': details
            }
        
        # 3. Reversion（均值回歸）- 改進版
        reversion_score = 0.0
        reversion_conditions = {}
        
        # 條件 1: 價格在 MA20-MA60 區間內
        if (ma20 <= close <= ma60) or (ma60 <= close <= ma20):
            reversion_score += 0.3
            reversion_conditions['price_in_range'] = True
        else:
            reversion_conditions['price_in_range'] = False
        
        # 條件 2: ADX 低（趨勢不強）
        if adx_value < 20:
            reversion_score += 0.3
            reversion_conditions['adx_low'] = True
        else:
            reversion_conditions['adx_low'] = False
        
        # 條件 3: RSI 在極端區間（如果有數據）
        if rsi_value is not None:
            if rsi_value < 30:  # 超賣
                reversion_score += 0.2
                reversion_conditions['rsi_oversold'] = True
            elif rsi_value > 70:  # 超買
                reversion_score += 0.2
                reversion_conditions['rsi_overbought'] = True
            else:
                reversion_conditions['rsi_oversold'] = False
                reversion_conditions['rsi_overbought'] = False
        else:
            reversion_conditions['rsi_oversold'] = False
            reversion_conditions['rsi_overbought'] = False
        
        # 條件 4: 價格偏離 MA20 的 z-score
        if len(close) >= 20:
            price_std = close.iloc[-20:].std()
            if price_std > 0:
                z_score = abs((close - ma20) / price_std)
                if z_score > 1.5:  # 偏離超過 1.5 個標準差
                    reversion_score += 0.2
                    reversion_conditions['price_deviation'] = True
                else:
                    reversion_conditions['price_deviation'] = False
            else:
                reversion_conditions['price_deviation'] = False
        else:
            reversion_conditions['price_deviation'] = False
        
        reversion_confidence = min(reversion_score, 1.0)
        reversion_condition = reversion_confidence >= 0.5  # 至少 50% 的條件滿足
        
        if reversion_condition:
            details.update({
                'close': close,
                'ma20': ma20,
                'ma60': ma60,
                'adx': adx_value,
                'rsi': rsi_value,
                'reversion_score': reversion_score,
                **reversion_conditions
            })
            
            final_regime = self._apply_regime_hysteresis('Reversion', date)
            return {
                'regime': final_regime,
                'confidence': reversion_confidence,
                'details': details
            }
        
        # 預設返回 Reversion（但 confidence 較低）
        details = {
            'close': close,
            'ma20': ma20,
            'ma60': ma60,
            'adx': adx_value,
            'default': True
        }
        
        final_regime = self._apply_regime_hysteresis('Reversion', date)
        return {
            'regime': final_regime,
            'confidence': 0.5,
            'details': details
        }
    
    def get_strategy_config(self, regime: str) -> dict:
        """根據市場狀態獲取對應的策略配置（改進版）
        
        Args:
            regime: 'Trend' | 'Reversion' | 'Breakout'
            
        Returns:
            dict: 策略配置字典
        """
        if regime == 'Trend':
            return {
                'technical': {
                    'momentum': {
                        'enabled': True,
                        'rsi': {'enabled': True, 'period': 14},
                        'macd': {'enabled': True, 'fast': 12, 'slow': 26, 'signal': 9},
                        'kd': {'enabled': False}
                    },
                    'volatility': {
                        'enabled': False,
                        'bollinger': {'enabled': False},
                        'atr': {'enabled': True, 'period': 14}
                    },
                    'trend': {
                        'enabled': True,
                        'adx': {'enabled': True, 'period': 14},
                        'ma': {'enabled': True, 'windows': [5, 10, 20, 60]}
                    }
                },
                'patterns': {
                    'selected': ['旗形', '三角形', '矩形']  # 移除 V形反轉（更適合 Reversion/Breakout）
                },
                'signals': {
                    'technical_indicators': ['momentum', 'trend'],
                    'volume_conditions': ['increasing', 'spike'],
                    'weights': {'pattern': 0.25, 'technical': 0.55, 'volume': 0.20}
                },
                'notes': {
                    'rsi_interpretation': '強勢維持（RSI>50 加分，而非 RSI>70 扣分）',
                    'regime_specific': 'Trend 策略下，RSI 應解讀為趨勢強度而非超買超賣'
                }
            }
        
        elif regime == 'Reversion':
            return {
                'technical': {
                    'momentum': {
                        'enabled': True,
                        'rsi': {'enabled': True, 'period': 14},
                        'macd': {'enabled': False},
                        'kd': {'enabled': True}
                    },
                    'volatility': {
                        'enabled': True,
                        'bollinger': {'enabled': True, 'window': 20, 'std': 2},
                        'atr': {'enabled': False}
                    },
                    'trend': {
                        'enabled': False,
                        'adx': {'enabled': False},
                        'ma': {'enabled': False}
                    }
                },
                'patterns': {
                    'selected': ['W底', '雙底', '圓底']
                },
                'signals': {
                    'technical_indicators': ['momentum', 'volatility'],
                    'volume_conditions': ['decreasing', 'spike'],  # 進場縮量，出場放量
                    'weights': {'pattern': 0.30, 'technical': 0.50, 'volume': 0.20}
                },
                'notes': {
                    'volume_interpretation': '進場：縮量止跌；出場：放量確認反轉',
                    'regime_specific': 'Reversion 策略下，成交量應分兩階段解讀'
                }
            }
        
        else:  # Breakout
            return {
                'technical': {
                    'momentum': {
                        'enabled': True,
                        'rsi': {'enabled': True, 'period': 14},
                        'macd': {'enabled': False},
                        'kd': {'enabled': False}
                    },
                    'volatility': {
                        'enabled': True,
                        'bollinger': {'enabled': True, 'window': 20, 'std': 2},
                        'atr': {'enabled': True, 'period': 14}
                    },
                    'trend': {
                        'enabled': False,
                        'adx': {'enabled': False},
                        'ma': {'enabled': False}
                    }
                },
                'patterns': {
                    'selected': ['矩形', '三角形', '楔形']
                },
                'signals': {
                    'technical_indicators': ['volatility'],
                    'volume_conditions': ['spike'],
                    'weights': {'pattern': 0.35, 'technical': 0.40, 'volume': 0.25}
                }
            }

__all__ = ['MarketRegimeDetector']
