"""
策略執行器適配器（已棄用，請使用 BaselineScoreExecutor）
保留此檔案僅為向後兼容
"""

import pandas as pd
import numpy as np
from typing import List
from app_module.strategy_spec import StrategySpec, StrategyExecutor
from app_module.daily_signal import DailySignalFrame
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.scoring_engine import ScoringEngine
# from ui_app.reason_engine import ReasonEngine
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.scoring_engine import ScoringEngine
from decision_module.reason_engine import ReasonEngine
from app_module.reason_tags import ReasonTagGenerator


class SimpleStrategyExecutor:
    """
    簡單策略執行器（已棄用）
    
    注意：此執行器沒有 cooldown 防護，不建議使用。
    請使用 BaselineScoreExecutor 替代。
    """
    """簡單策略執行器（適配 StrategyConfigurator）"""
    
    def __init__(self):
        """初始化執行器"""
        self.configurator = StrategyConfigurator()
        self.scoring_engine = ScoringEngine()
        self.reason_engine = ReasonEngine()
    
    def generate_signals(
        self,
        df: pd.DataFrame,
        spec: StrategySpec
    ) -> pd.DataFrame:
        """
        生成每日信號
        
        Args:
            df: 股票數據 DataFrame
            spec: 策略規格
        
        Returns:
            DailySignalFrame
        """
        # 確保日期索引
        if '日期' in df.columns:
            df = df.set_index('日期')
        elif not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame 必須有日期索引或日期欄位")
        
        df = df.sort_index()
        
        # 數據清理和類型轉換（確保技術指標計算所需的欄位是 float64）
        df = self._prepare_dataframe(df)
        
        # 獲取策略配置
        config = spec.config
        
        # 1. 配置技術指標
        df = self.configurator.configure_technical_indicators(df, config.get('technical', {}))
        
        # 2. 識別圖形模式
        pattern_types = config.get('patterns', {}).get('selected', [])
        patterns_found = self.configurator.identify_patterns(df, pattern_types)
        
        # 3. 計算分數
        regime = config.get('regime', None)
        df = self.scoring_engine.calculate_total_score(df, config, regime=regime)
        
        # 4. 生成信號（基於總分）
        # 簡單規則：總分 > 60 買入，總分 < 40 賣出，否則持有
        signals = pd.Series(0, index=df.index)  # 預設持有
        
        # 買入信號：總分 > 60 且前一日 <= 60（避免重複信號）
        buy_mask = (df['TotalScore'] > 60) & (df['TotalScore'].shift(1) <= 60)
        signals[buy_mask] = 1
        
        # 賣出信號：總分 < 40 且前一日 >= 40（避免重複信號）
        sell_mask = (df['TotalScore'] < 40) & (df['TotalScore'].shift(1) >= 40)
        signals[sell_mask] = -1
        
        # 5. 生成理由標籤
        reason_tags_list = []
        for idx, row in df.iterrows():
            reasons = self.reason_engine.generate_reasons(row, config)
            tags = ReasonTagGenerator.generate_tags(reasons)
            reason_tags_list.append(tags)
        
        reason_tags = pd.Series(reason_tags_list, index=df.index)
        
        # 6. 獲取 Regime 匹配
        regime_match = df.get('RegimeMatch', pd.Series(True, index=df.index))
        
        # 7. 構建 DailySignalFrame
        scores = {
            'score': df.get('TotalScore', pd.Series(50.0, index=df.index)),
            'indicator_score': df.get('IndicatorScore', pd.Series(50.0, index=df.index)),
            'pattern_score': df.get('PatternScore', pd.Series(50.0, index=df.index)),
            'volume_score': df.get('VolumeScore', pd.Series(50.0, index=df.index))
        }
        
        signal_frame = DailySignalFrame.create(
            df=df,
            signals=signals,
            scores=scores,
            reason_tags=reason_tags,
            regime_match=regime_match
        )
        
        return signal_frame
    
    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        準備 DataFrame，確保數據類型正確（float64）以供 talib 使用
        
        Args:
            df: 原始 DataFrame
        
        Returns:
            處理後的 DataFrame
        """
        df = df.copy()
        
        # 價格欄位轉換為 float64
        price_columns = ['開盤價', '最高價', '最低價', '收盤價', 'Open', 'High', 'Low', 'Close']
        for col in price_columns:
            if col in df.columns:
                # 先轉為字符串，移除逗號和特殊字符
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace('--', '').str.replace('', '')
                # 轉為數值
                df[col] = pd.to_numeric(df[col], errors='coerce')
                # 確保是 float64 類型
                df[col] = df[col].astype('float64')
                # 前向填充 NaN
                df[col] = df[col].ffill().bfill()
                # 如果還有 NaN，用 0 填充
                df[col] = df[col].fillna(0.0)
        
        # 成交量欄位轉換為 float64
        volume_columns = ['成交股數', '成交筆數', '成交金額', 'Volume', 'volume']
        for col in volume_columns:
            if col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace('--', '').str.replace('', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
                df[col] = df[col].astype('float64')
                df[col] = df[col].ffill().bfill()
                df[col] = df[col].fillna(0.0)
        
        # 處理所有數值欄位
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            # 確保是 float64
            if df[col].dtype != 'float64':
                df[col] = df[col].astype('float64')
            # 處理無限值
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)
            # 填充 NaN
            df[col] = df[col].ffill().bfill()
            df[col] = df[col].fillna(0.0)
        
        # 確保所有價格欄位都有值（不能全為 0）
        for col in price_columns:
            if col in df.columns:
                if (df[col] == 0).all():
                    raise ValueError(f"價格欄位 {col} 全為 0，無法計算技術指標")
        
        return df

