"""
統一打分模型
實現 0-100 分的標準化評分系統
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional

class ScoringEngine:
    """統一打分引擎"""
    
    def __init__(self):
        """初始化打分引擎"""
        pass
    
    def calculate_total_score(self, df: pd.DataFrame, config: Dict, regime: str = None, regime_match: bool = None) -> pd.DataFrame:
        """計算總分（含 Regime Match Factor）
        
        TotalScore = W_pattern * PatternScore + W_indicator * IndicatorScore + W_volume * VolumeScore
        FinalScore = TotalScore * RegimeMatchFactor
        
        Args:
            df: 股票數據DataFrame（已包含技術指標）
            config: 策略配置字典
            regime: 市場狀態（'Trend' | 'Reversion' | 'Breakout'）
            regime_match: 股票行為是否匹配市場狀態（True/False），如果為None則自動判斷
            
        Returns:
            DataFrame: 添加了各項分數和總分的DataFrame
        """
        df_result = df.copy()
        
        # 獲取權重（自動normalize）
        weights = self._normalize_weights(config.get('signals', {}).get('weights', {}))
        
        # 計算各項分數（傳遞 regime 信息）
        indicator_score = self.calculate_indicator_score(df_result, config, regime=regime)
        pattern_score = self.calculate_pattern_score(df_result, config)
        volume_score = self.calculate_volume_score(df_result, config)
        
        # 計算總分
        df_result['IndicatorScore'] = indicator_score
        df_result['PatternScore'] = pattern_score
        df_result['VolumeScore'] = volume_score
        
        df_result['TotalScore'] = (
            weights['pattern'] * pattern_score +
            weights['technical'] * indicator_score +
            weights['volume'] * volume_score
        )
        
        # Regime 權重切換（不再使用倍率，改用權重調整）
        # 根據 Regime 調整權重，而不是乘以倍率
        if regime:
            # 自動判斷是否匹配
            if regime_match is None:
                df_result['RegimeMatch'] = self._check_regime_match(df_result, regime, config)
            else:
                df_result['RegimeMatch'] = pd.Series(regime_match, index=df_result.index)
            
            # 根據 Regime 調整權重（而不是倍率）
            regime_weights = self._get_regime_weights(regime, weights)
            
            # 重新計算總分（使用 Regime 權重）
            df_result['TotalScore'] = (
                regime_weights['pattern'] * pattern_score +
                regime_weights['technical'] * indicator_score +
                regime_weights['volume'] * volume_score
            )
            
            # FinalScore = TotalScore（不再使用倍率）
            df_result['FinalScore'] = df_result['TotalScore']
        else:
            # 沒有 Regime 信息，FinalScore = TotalScore
            df_result['FinalScore'] = df_result['TotalScore']
            df_result['RegimeMatch'] = True
        
        return df_result
    
    def _get_regime_weights(self, regime: str, base_weights: Dict) -> Dict:
        """根據 Regime 調整權重
        
        Args:
            regime: 市場狀態（'Trend' | 'Reversion' | 'Breakout'）
            base_weights: 基礎權重字典
            
        Returns:
            Dict: 調整後的權重字典
        """
        # 複製基礎權重
        regime_weights = base_weights.copy()
        
        # 根據不同 Regime 調整權重
        if regime == 'Trend':
            # Trend 策略：重視技術指標和成交量
            regime_weights = {
                'pattern': base_weights.get('pattern', 0.3) * 0.8,  # 降低圖形權重
                'technical': base_weights.get('technical', 0.5) * 1.2,  # 提高技術指標權重
                'volume': base_weights.get('volume', 0.2) * 1.0
            }
        elif regime == 'Reversion':
            # Reversion 策略：重視圖形模式
            regime_weights = {
                'pattern': base_weights.get('pattern', 0.3) * 1.3,  # 提高圖形權重
                'technical': base_weights.get('technical', 0.5) * 0.9,  # 降低技術指標權重
                'volume': base_weights.get('volume', 0.2) * 0.8
            }
        elif regime == 'Breakout':
            # Breakout 策略：重視成交量和技術指標
            regime_weights = {
                'pattern': base_weights.get('pattern', 0.3) * 1.0,
                'technical': base_weights.get('technical', 0.5) * 1.1,
                'volume': base_weights.get('volume', 0.2) * 1.4  # 大幅提高成交量權重
            }
        else:
            # 未知 Regime，使用基礎權重
            regime_weights = base_weights
        
        # 正規化權重（確保總和為 1）
        total = sum(regime_weights.values())
        if total > 0:
            regime_weights = {k: v / total for k, v in regime_weights.items()}
        
        return regime_weights
    
    def _check_regime_match(self, df: pd.DataFrame, regime: str, config: Dict) -> pd.Series:
        """檢查股票行為是否匹配市場狀態
        
        Args:
            df: 股票數據DataFrame
            regime: 市場狀態
            
        Returns:
            Series: 布林值，表示是否匹配
        """
        match = pd.Series(True, index=df.index)  # 預設匹配
        
        if regime == 'Trend':
            # Trend 策略：檢查是否為趨勢股
            # 條件：均線多頭排列、ADX > 25、MACD 在0軸以上
            if 'ADX' in df.columns:
                match = match & (df['ADX'] > 25)
            
            # 檢查均線多頭排列
            ma_cols = []
            for col in df.columns:
                if col.startswith('MA') and col[2:].isdigit():
                    ma_cols.append((int(col[2:]), col))
            if len(ma_cols) >= 2:
                ma_cols.sort()
                for i in range(len(ma_cols) - 1):
                    short_col = ma_cols[i][1]
                    long_col = ma_cols[i+1][1]
                    match = match & (df[short_col] > df[long_col])
        
        elif regime == 'Reversion':
            # Reversion 策略：檢查是否超賣或觸及下軌
            if 'RSI' in df.columns:
                match = match & (df['RSI'] < 40)  # 偏超賣
            
            if 'lowerband' in df.columns:
                close_col = None
                for col in ['收盤價', 'Close', 'close']:
                    if col in df.columns:
                        close_col = col
                        break
                if close_col:
                    # 價格接近下軌
                    band_width = df.get('upperband', df[close_col]) - df['lowerband']
                    position = (df[close_col] - df['lowerband']) / band_width.replace(0, np.nan)
                    match = match & (position < 0.3)  # 在下軌附近
        
        elif regime == 'Breakout':
            # Breakout 策略：檢查是否有突破跡象
            # 條件：成交量放大、價格接近關鍵區間
            if '成交股數' in df.columns:
                volume_ma = df['成交股數'].rolling(window=20, min_periods=1).mean()
                volume_ratio = df['成交股數'] / volume_ma.replace(0, np.nan)
                match = match & (volume_ratio > 1.5)  # 成交量放大
        
        return match
    
    def _normalize_weights(self, weights: Dict) -> Dict:
        """正規化權重，確保總和為1.0"""
        total = sum(weights.values())
        if total == 0:
            # 預設權重
            return {'pattern': 0.3, 'technical': 0.5, 'volume': 0.2}
        return {k: v / total for k, v in weights.items()}
    
    def calculate_indicator_score(self, df: pd.DataFrame, config: Dict, regime: str = None) -> pd.Series:
        """計算技術指標分數（0-100）
        
        Args:
            df: 股票數據DataFrame
            config: 策略配置
            regime: 市場狀態（可選，用於調整評分邏輯）
            
        Returns:
            Series: 技術指標分數（0-100）
        """
        scores = []
        tech_config = config.get('technical', {})
        
        # RSI 分數
        if tech_config.get('momentum', {}).get('rsi', {}).get('enabled', False):
            rsi_score = self._calculate_rsi_score(df, regime)
            if rsi_score is not None:
                scores.append(rsi_score)
        
        # MACD 分數
        if tech_config.get('momentum', {}).get('macd', {}).get('enabled', False):
            macd_score = self._calculate_macd_score(df, regime)
            if macd_score is not None:
                scores.append(macd_score)
        
        # KD 分數
        if tech_config.get('momentum', {}).get('kd', {}).get('enabled', False):
            kd_score = self._calculate_kd_score(df)
            if kd_score is not None:
                scores.append(kd_score)
        
        # ADX 分數
        if tech_config.get('trend', {}).get('adx', {}).get('enabled', False):
            adx_score = self._calculate_adx_score(df)
            if adx_score is not None:
                scores.append(adx_score)
        
        # 均線系統分數
        if tech_config.get('trend', {}).get('ma', {}).get('enabled', False):
            ma_score = self._calculate_ma_score(df, tech_config.get('trend', {}).get('ma', {}))
            if ma_score is not None:
                scores.append(ma_score)
        
        # 布林通道分數
        if tech_config.get('volatility', {}).get('bollinger', {}).get('enabled', False):
            bb_score = self._calculate_bollinger_score(df)
            if bb_score is not None:
                scores.append(bb_score)
        
        # 平均所有啟用的指標分數
        if len(scores) == 0:
            return pd.Series(50.0, index=df.index)  # 預設中性分數
        
        # 加權平均（可以根據重要性調整權重）
        indicator_scores = pd.concat(scores, axis=1)
        return indicator_scores.mean(axis=1)
    
    def _calculate_rsi_score(self, df: pd.DataFrame, regime: str = None) -> Optional[pd.Series]:
        """計算 RSI 分數（0-100），根據 Regime 調整邏輯
        
        Trend: RSI 50-70 加分（趨勢延續）
        Reversion: RSI < 30 加分最高（超賣反彈）
        Breakout: RSI 40-60 中性（避免過熱）
        """
        rsi_col = None
        for col in ['RSI', 'rsi', 'RSI_14']:
            if col in df.columns:
                rsi_col = col
                break
        
        if rsi_col is None:
            return None
        
        rsi = df[rsi_col]
        score = pd.Series(50.0, index=df.index)  # 預設中性
        
        if regime == 'Trend':
            # Trend 策略：RSI 解讀為「動能維持」而非「超買超賣」
            # RSI > 50：加分（多頭動能）
            # RSI 40-50：中性
            # RSI < 40：扣分（動能轉弱）
            # RSI > 70：不一定扣分（強趨勢可以長期 70+）
            
            # RSI >= 50：多頭動能，加分
            mask_bullish = rsi >= 50
            # 50-70：理想區間，60-85分
            mask_ideal = (rsi >= 50) & (rsi <= 70)
            score[mask_ideal] = 60 + (rsi[mask_ideal] - 50) / 20 * 25  # 50時60分，70時85分
            
            # 70-80：強趨勢可能持續，不扣分，維持高分
            mask_strong = (rsi > 70) & (rsi <= 80)
            score[mask_strong] = 85 - (rsi[mask_strong] - 70) / 10 * 10  # 70時85分，80時75分
            
            # 80+：可能過熱，但強趨勢仍可能持續，輕微扣分
            mask_very_high = rsi > 80
            score[mask_very_high] = 75 - (rsi[mask_very_high] - 80) / 20 * 25  # 80時75分，100時50分
            
            # RSI 40-50：中性偏弱
            mask_neutral = (rsi >= 40) & (rsi < 50)
            score[mask_neutral] = 50 + (rsi[mask_neutral] - 40) / 10 * 10  # 40時50分，50時60分
            
            # RSI < 40：動能轉弱，扣分
            mask_weak = rsi < 40
            score[mask_weak] = 30 + (rsi[mask_weak] / 40) * 20  # 0時30分，40時50分
        
        elif regime == 'Reversion':
            # Reversion 策略：RSI < 30 加分最高（超賣反彈）
            mask_oversold = rsi <= 30
            score[mask_oversold] = 70 + (30 - rsi[mask_oversold]) / 30 * 30  # 30時70分，0時100分
            
            # RSI 30-50：中性偏多
            mask_neutral = (rsi > 30) & (rsi < 50)
            score[mask_neutral] = 50 + (rsi[mask_neutral] - 30) / 20 * 10  # 30時50分，50時60分
            
            # RSI >= 50：偏空
            mask_overbought = rsi >= 50
            score[mask_overbought] = 60 - (rsi[mask_overbought] - 50) / 50 * 30  # 50時60分，100時30分
        
        elif regime == 'Breakout':
            # Breakout 策略：RSI 40-60 中性（避免過熱）
            mask_ideal = (rsi >= 40) & (rsi <= 60)
            score[mask_ideal] = 55  # 中性高分
            
            # RSI < 40 或 > 60：降分
            mask_outside = (rsi < 40) | (rsi > 60)
            score[mask_outside] = 45
        
        else:
            # 預設邏輯（原有邏輯）
            mask_oversold = rsi <= 30
            score[mask_oversold] = 70 + (30 - rsi[mask_oversold]) / 30 * 30
            
            mask_neutral = (rsi > 30) & (rsi < 70)
            score[mask_neutral] = 40 + (rsi[mask_neutral] - 30) / 40 * 20
            
            mask_overbought = rsi >= 70
            score[mask_overbought] = 30 - (rsi[mask_overbought] - 70) / 30 * 30
        
        return score.clip(0, 100)
    
    def _calculate_macd_score(self, df: pd.DataFrame, regime: str = None) -> Optional[pd.Series]:
        """計算 MACD 分數（0-100），根據 Regime 調整邏輯
        
        Trend: 0軸以上金叉加權最高
        Reversion/Breakout: 標準邏輯
        """
        macd_col = None
        signal_col = None
        hist_col = None
        
        for col in ['MACD', 'macd']:
            if col in df.columns:
                macd_col = col
                break
        
        for col in ['MACD_Signal', 'macd_signal', 'Signal']:
            if col in df.columns:
                signal_col = col
                break
        
        for col in ['MACD_hist', 'macd_hist', 'MACD_histogram']:
            if col in df.columns:
                hist_col = col
                break
        
        if macd_col is None or signal_col is None:
            return None
        
        macd = df[macd_col]
        signal = df[signal_col]
        score = pd.Series(50.0, index=df.index)  # 預設中性
        
        # 金叉/死叉判斷
        macd_above_signal = macd > signal
        macd_below_signal = macd < signal
        
        # 金叉加分
        if hist_col and hist_col in df.columns:
            hist = df[hist_col]
            # 金叉且柱狀體擴大（最近3天）
            for i in range(len(df)):
                if i >= 2:
                    if macd_above_signal.iloc[i]:
                        # 在0軸以上加分更多
                        if macd.iloc[i] > 0:
                            base_score = 70
                        else:
                            base_score = 60
                        
                        # 柱狀體擴大加分
                        if hist.iloc[i] > hist.iloc[i-1] > hist.iloc[i-2]:
                            score.iloc[i] = base_score + 20
                        elif hist.iloc[i] > hist.iloc[i-1]:
                            score.iloc[i] = base_score + 10
                        else:
                            score.iloc[i] = base_score
                    elif macd_below_signal.iloc[i]:
                        # 死叉扣分
                        if macd.iloc[i] < 0:
                            base_score = 20
                        else:
                            base_score = 30
                        
                        # 柱狀體擴大扣分更多
                        if hist.iloc[i] < hist.iloc[i-1] < hist.iloc[i-2]:
                            score.iloc[i] = base_score - 20
                        elif hist.iloc[i] < hist.iloc[i-1]:
                            score.iloc[i] = base_score - 10
                        else:
                            score.iloc[i] = base_score
        else:
            # 沒有柱狀體數據，只用金叉/死叉
            score[macd_above_signal] = 70
            score[macd_below_signal] = 30
        
        return score.clip(0, 100)
    
    def _calculate_kd_score(self, df: pd.DataFrame) -> Optional[pd.Series]:
        """計算 KD 分數（0-100）
        
        K 上穿 D 且位於低檔：加分
        高檔鈍化：扣分
        """
        k_col = None
        d_col = None
        
        for col in ['slowk', 'K', 'k']:
            if col in df.columns:
                k_col = col
                break
        
        for col in ['slowd', 'D', 'd']:
            if col in df.columns:
                d_col = col
                break
        
        if k_col is None or d_col is None:
            return None
        
        k = df[k_col]
        d = df[d_col]
        score = pd.Series(50.0, index=df.index)
        
        # K 上穿 D
        k_cross_above_d = (k > d) & (k.shift(1) <= d.shift(1))
        
        # 低檔（< 30）上穿：加分
        low_zone_cross = k_cross_above_d & (k < 30)
        score[low_zone_cross] = 80
        
        # 中檔上穿：中性偏多
        mid_zone_cross = k_cross_above_d & (k >= 30) & (k < 70)
        score[mid_zone_cross] = 60
        
        # 高檔鈍化（> 80）：扣分
        high_zone = (k > 80) & (d > 80)
        score[high_zone] = 20
        
        # K 下穿 D：扣分
        k_cross_below_d = (k < d) & (k.shift(1) >= d.shift(1))
        high_zone_cross = k_cross_below_d & (k > 70)
        score[high_zone_cross] = 30
        
        return score.clip(0, 100)
    
    def _calculate_adx_score(self, df: pd.DataFrame) -> Optional[pd.Series]:
        """計算 ADX 分數（0-100）
        
        ADX > 25：趨勢成立，加分
        ADX < 20：盤整，降權
        """
        adx_col = None
        for col in ['ADX', 'adx']:
            if col in df.columns:
                adx_col = col
                break
        
        if adx_col is None:
            return None
        
        adx = df[adx_col]
        score = pd.Series(50.0, index=df.index)
        
        # ADX > 25：趨勢成立，加分
        strong_trend = adx > 25
        score[strong_trend] = 60 + (adx[strong_trend] - 25) / 25 * 20  # 25時60分，50時80分
        
        # ADX < 20：盤整，降權
        consolidation = adx < 20
        score[consolidation] = 40 - (20 - adx[consolidation]) / 20 * 20  # 20時40分，0時20分
        
        return score.clip(0, 100)
    
    def _calculate_ma_score(self, df: pd.DataFrame, ma_config: Dict) -> Optional[pd.Series]:
        """計算均線系統分數（0-100）
        
        多頭排列（MA5>10>20>60）：高分
        轉折（MA5 上穿 MA20 且 MA20 上彎）：中高分
        空頭排列：低分
        """
        windows = ma_config.get('windows', [5, 10, 20, 60])
        if len(windows) < 2:
            return None
        
        # 檢查是否有均線數據
        ma_cols = []
        for window in windows:
            for col in [f'MA{window}', f'SMA{window}', f'MA_{window}']:
                if col in df.columns:
                    ma_cols.append((window, col))
                    break
        
        if len(ma_cols) < 2:
            return None
        
        score = pd.Series(50.0, index=df.index)
        
        # 按週期排序
        ma_cols.sort(key=lambda x: x[0])
        
        # 多頭排列：短均線 > 長均線
        bullish_alignment = True
        for i in range(len(ma_cols) - 1):
            short_col = ma_cols[i][1]
            long_col = ma_cols[i+1][1]
            bullish_alignment = bullish_alignment & (df[short_col] > df[long_col])
        
        score[bullish_alignment] = 80
        
        # 空頭排列：短均線 < 長均線
        bearish_alignment = True
        for i in range(len(ma_cols) - 1):
            short_col = ma_cols[i][1]
            long_col = ma_cols[i+1][1]
            bearish_alignment = bearish_alignment & (df[short_col] < df[long_col])
        
        score[bearish_alignment] = 20
        
        # 轉折：MA5 上穿 MA20
        if len(ma_cols) >= 2:
            ma5_col = ma_cols[0][1] if ma_cols[0][0] <= 5 else None
            ma20_col = None
            for window, col in ma_cols:
                if window >= 20:
                    ma20_col = col
                    break
            
            if ma5_col and ma20_col:
                ma5_cross_above_ma20 = (df[ma5_col] > df[ma20_col]) & (df[ma5_col].shift(1) <= df[ma20_col].shift(1))
                score[ma5_cross_above_ma20] = 70
        
        return score.clip(0, 100)
    
    def _calculate_bollinger_score(self, df: pd.DataFrame) -> Optional[pd.Series]:
        """計算布林通道分數（0-100）
        
        價格接近下軌：偏多
        價格接近上軌：偏空
        """
        upper_col = None
        lower_col = None
        close_col = None
        
        for col in ['upperband', 'upper_band', 'BB_upper']:
            if col in df.columns:
                upper_col = col
                break
        
        for col in ['lowerband', 'lower_band', 'BB_lower']:
            if col in df.columns:
                lower_col = col
                break
        
        for col in ['收盤價', 'Close', 'close']:
            if col in df.columns:
                close_col = col
                break
        
        if not all([upper_col, lower_col, close_col]):
            return None
        
        upper = df[upper_col]
        lower = df[lower_col]
        close = df[close_col]
        score = pd.Series(50.0, index=df.index)
        
        # 計算價格在通道中的位置（0-1）
        band_width = upper - lower
        position = (close - lower) / band_width.replace(0, np.nan)
        
        # 接近下軌（< 0.2）：偏多
        near_lower = position < 0.2
        score[near_lower] = 70 + (0.2 - position[near_lower]) / 0.2 * 20  # 0時90分，0.2時70分
        
        # 接近上軌（> 0.8）：偏空
        near_upper = position > 0.8
        score[near_upper] = 30 - (position[near_upper] - 0.8) / 0.2 * 20  # 0.8時30分，1時10分
        
        return score.clip(0, 100)
    
    def calculate_pattern_score(self, df: pd.DataFrame, config: Dict) -> pd.Series:
        """計算圖形模式分數（0-100）
        
        PatternScore = Σ (BaseScore(pattern) * confidence * decay(age)) / N
        """
        pattern_types = config.get('patterns', {}).get('selected', [])
        
        if len(pattern_types) == 0:
            return pd.Series(50.0, index=df.index)  # 預設中性
        
        # 基礎分數映射
        base_scores = {
            'W底': 85, '頭肩底': 80, '雙底': 80,
            '矩形': 75, '三角形': 70, '旗形': 70,
            'V形反轉': 75, '圓底': 65,
            '頭肩頂': 20, '雙頂': 20, '圓頂': 25, '楔形': 50
        }
        
        # 這裡需要調用 PatternAnalyzer 來識別模式
        # 暫時返回預設分數，實際需要整合 PatternAnalyzer
        # TODO: 整合 PatternAnalyzer 獲取 pattern 信息
        
        return pd.Series(50.0, index=df.index)
    
    def calculate_volume_score(self, df: pd.DataFrame, config: Dict) -> pd.Series:
        """計算成交量分數（0-100）
        
        成交量增加：VolRatio > 1.5 加分
        成交量尖峰：z-score > 2 高分
        成交量減少：在整理時可能是好事
        """
        volume_conditions = config.get('signals', {}).get('volume_conditions', [])
        
        if len(volume_conditions) == 0:
            return pd.Series(50.0, index=df.index)  # 預設中性
        
        score = pd.Series(50.0, index=df.index)
        
        # 獲取成交量數據
        volume_col = None
        for col in ['成交股數', 'Volume', 'volume']:
            if col in df.columns:
                volume_col = col
                break
        
        if volume_col is None:
            return score
        
        volume = df[volume_col]
        
        # 計算成交量比率（與20日均量比較）
        volume_ma20 = volume.rolling(window=20, min_periods=1).mean()
        volume_ratio = volume / volume_ma20.replace(0, np.nan)
        
        # 成交量增加
        if 'increasing' in volume_conditions:
            vol_increase = volume_ratio > 1.5
            score[vol_increase] = 60 + (volume_ratio[vol_increase] - 1.5) / 1.5 * 30  # 1.5時60分，3時90分
        
        # 成交量尖峰（z-score > 2）
        if 'spike' in volume_conditions:
            volume_std = volume.rolling(window=20, min_periods=1).std()
            volume_zscore = (volume - volume_ma20) / volume_std.replace(0, np.nan)
            spike = volume_zscore > 2
            score[spike] = 70 + (volume_zscore[spike] - 2) / 2 * 20  # 2時70分，4時90分
        
        # 成交量減少（在整理時可能是好事，但需要配合價格）
        if 'decreasing' in volume_conditions:
            vol_decrease = volume_ratio < 0.8
            # 如果價格在均線附近，量縮是好事
            close_col = None
            for col in ['收盤價', 'Close', 'close']:
                if col in df.columns:
                    close_col = col
                    break
            
            if close_col:
                close = df[close_col]
                ma20 = close.rolling(window=20, min_periods=1).mean()
                # 價格在均線附近且量縮：加分
                near_ma = abs(close - ma20) / ma20 < 0.02
                score[vol_decrease & near_ma] = 55
        
        return score.clip(0, 100)
    
    def generate_reasons(self, df: pd.DataFrame, config: Dict) -> List[Dict]:
        """生成推薦理由
        
        Returns:
            List[Dict]: 每個理由包含 {tag, evidence, score_contrib}
        """
        reasons_list = []
        
        # 這裡需要根據實際的分數計算來生成理由
        # TODO: 實現詳細的理由生成邏輯
        
        return reasons_list

