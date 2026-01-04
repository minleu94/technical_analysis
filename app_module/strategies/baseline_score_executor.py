"""
Baseline Score Threshold Strategy Executor
回歸測試基準策略：總分閾值策略（帶 cooldown 防護）
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


class BaselineScoreExecutor(StrategyExecutor):
    """
    Baseline Score Threshold Strategy
    
    策略邏輯：
    - 進場：總分 >= buy_score 且連續 buy_confirm_days 天
    - 出場：總分 <= sell_score 且連續 sell_confirm_days 天
    - Cooldown：交易後 cooldown_days 天內禁止反向操作
    
    用途：回歸測試基準策略，用於驗證回測引擎的正確性
    """
    
    @staticmethod
    def get_meta():
        """獲取策略元數據"""
        return {
            'strategy_id': 'baseline_score_threshold',
            'name': 'Baseline Score Threshold',
            'version': '1.0',
            'description': '總分閾值策略（帶 cooldown 防護），用於回歸測試',
            'category': 'baseline',
            'params': {
                'buy_score': {'type': 'float', 'default': 60, 'description': '買入閾值'},
                'sell_score': {'type': 'float', 'default': 40, 'description': '賣出閾值'},
                'buy_confirm_days': {'type': 'int', 'default': 2, 'description': '買入確認天數'},
                'sell_confirm_days': {'type': 'int', 'default': 2, 'description': '賣出確認天數'},
                'cooldown_days': {'type': 'int', 'default': 3, 'description': '交易後冷卻天數'}
            }
        }
    
    def __init__(self, spec: StrategySpec):
        """
        初始化策略執行器
        
        Args:
            spec: 策略規格
        """
        self.spec = spec
        self.configurator = StrategyConfigurator()
        self.scoring_engine = ScoringEngine()
        self.reason_engine = ReasonEngine()
        
        # 從 spec 獲取參數
        params = spec.config.get('params', {})
        self.buy_score = params.get('buy_score', 60)
        self.sell_score = params.get('sell_score', 40)
        self.buy_confirm_days = params.get('buy_confirm_days', 2)
        self.sell_confirm_days = params.get('sell_confirm_days', 2)
        self.cooldown_days = params.get('cooldown_days', 3)
    
    def generate_signals(
        self,
        df: pd.DataFrame,
        spec: StrategySpec
    ) -> pd.DataFrame:
        """
        生成每日信號（帶 cooldown 和連續確認）
        
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
        
        # 數據清理和類型轉換
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
        
        # 4. 生成信號（帶連續確認和 cooldown）
        signals = self._generate_signals_with_cooldown(df)
        
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
    
    def _generate_signals_with_cooldown(self, df: pd.DataFrame) -> pd.Series:
        """
        生成信號（帶連續確認和 cooldown）
        
        Args:
            df: 包含 TotalScore 的 DataFrame
        
        Returns:
            信號序列（1=買入, 0=持有, -1=賣出）
        """
        signals = pd.Series(0, index=df.index)  # 預設持有
        
        in_position = False  # 是否持倉
        last_trade_date = None  # 最後交易日期
        last_trade_type = None  # 最後交易類型（'buy' 或 'sell'）
        
        # 計算連續確認
        buy_confirmed = self._calculate_confirmed_signals(
            df['TotalScore'] >= self.buy_score,
            self.buy_confirm_days
        )
        sell_confirmed = self._calculate_confirmed_signals(
            df['TotalScore'] <= self.sell_score,
            self.sell_confirm_days
        )
        
        for i, (date, row) in enumerate(df.iterrows()):
            # 檢查 cooldown
            in_cooldown = False
            if last_trade_date is not None:
                days_since_trade = (date - last_trade_date).days
                if days_since_trade < self.cooldown_days:
                    # 在 cooldown 期間，禁止反向操作
                    if (last_trade_type == 'buy' and sell_confirmed.iloc[i]) or \
                       (last_trade_type == 'sell' and buy_confirmed.iloc[i]):
                        in_cooldown = True
            
            # 進場邏輯
            if not in_position and buy_confirmed.iloc[i] and not in_cooldown:
                signals.iloc[i] = 1
                in_position = True
                last_trade_date = date
                last_trade_type = 'buy'
            
            # 出場邏輯
            elif in_position and sell_confirmed.iloc[i] and not in_cooldown:
                signals.iloc[i] = -1
                in_position = False
                last_trade_date = date
                last_trade_type = 'sell'
        
        return signals
    
    def _calculate_confirmed_signals(self, condition: pd.Series, confirm_days: int) -> pd.Series:
        """
        計算連續確認信號
        
        Args:
            condition: 條件序列（布林值）
            confirm_days: 需要連續確認的天數
        
        Returns:
            確認後的信號序列
        """
        if confirm_days <= 1:
            return condition
        
        confirmed = pd.Series(False, index=condition.index)
        
        for i in range(confirm_days - 1, len(condition)):
            # 檢查是否連續 confirm_days 天都滿足條件
            if condition.iloc[i - confirm_days + 1:i + 1].all():
                # 只在最後一天標記為確認
                confirmed.iloc[i] = True
        
        return confirmed
    
    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        準備 DataFrame，確保數據類型正確（float64）以供 talib 使用
        
        Args:
            df: 原始 DataFrame
        
        Returns:
            處理後的 DataFrame
        """
        import numpy as np
        
        df = df.copy()
        
        # 價格欄位轉換為 float64
        price_columns = ['開盤價', '最高價', '最低價', '收盤價', 'Open', 'High', 'Low', 'Close']
        for col in price_columns:
            if col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace('--', '').str.replace('', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
                df[col] = df[col].astype('float64')
                df[col] = df[col].ffill().bfill()
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
            if df[col].dtype != 'float64':
                df[col] = df[col].astype('float64')
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)
            df[col] = df[col].ffill().bfill()
            df[col] = df[col].fillna(0.0)
        
        return df

