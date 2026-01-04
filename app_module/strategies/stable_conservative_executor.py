"""
穩健策略執行器 (Stable Conservative Strategy)
適用於均值回歸市場，追求穩定報酬，風險較低
"""

import pandas as pd
import numpy as np
from app_module.strategy_spec import StrategySpec, StrategyExecutor
from app_module.daily_signal import DailySignalFrame
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.scoring_engine import ScoringEngine
# from ui_app.reason_engine import ReasonEngine
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.scoring_engine import ScoringEngine
from decision_module.reason_engine import ReasonEngine
from app_module.reason_tags import ReasonTagGenerator


class StableConservativeExecutor(StrategyExecutor):
    """
    穩健策略（Stable Conservative）
    
    策略理念（Why）：
    - 在均值回歸市場中，尋找被低估的機會，追求穩定報酬
    - 適合風險承受度低的投資者
    - 等待明確的進場信號，避免頻繁交易
    
    適用 Regime: Reversion
    不適用 Regime: Trend, Breakout
    風險等級: low
    """
    
    @staticmethod
    def get_meta():
        """獲取策略元數據"""
        from app_module.strategy_spec import StrategyMeta
        from datetime import datetime
        
        return StrategyMeta(
            strategy_id='stable_conservative_v1',
            strategy_version='1.0.0',
            name='穩健策略',
            description='在均值回歸市場中尋找被低估的機會，追求穩定報酬。適合風險承受度低的投資者。',
            regime=['Reversion'],
            not_suitable_regime=['Trend', 'Breakout'],
            risk_level='low',
            risk_description='低風險策略，追求穩定報酬。但可能錯過快速上漲的機會。',
            target_type='stock',
            default_params={
                'buy_score': 55,  # 較低的買入閾值（尋找被低估）
                'sell_score': 45,  # 較低的賣出閾值（穩定獲利）
                'buy_confirm_days': 3,  # 較長的確認期（避免假信號）
                'sell_confirm_days': 3,  # 較長的確認期
                'cooldown_days': 5  # 較長的冷卻期（避免頻繁交易）
            }
        )
    
    def __init__(self, spec: StrategySpec):
        self.spec = spec
        self.configurator = StrategyConfigurator()
        self.scoring_engine = ScoringEngine()
        self.reason_engine = ReasonEngine()
        
        params = spec.config.get('params', {})
        self.buy_score = params.get('buy_score', 55)
        self.sell_score = params.get('sell_score', 45)
        self.buy_confirm_days = params.get('buy_confirm_days', 3)
        self.sell_confirm_days = params.get('sell_confirm_days', 3)
        self.cooldown_days = params.get('cooldown_days', 5)
    
    def generate_signals(self, df: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
        """生成每日信號"""
        if '日期' in df.columns:
            df = df.set_index('日期')
        elif not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame 必須有日期索引或日期欄位")
        
        df = df.sort_index()
        df = self._prepare_dataframe(df)
        
        config = spec.config
        
        # 配置技術指標
        df = self.configurator.configure_technical_indicators(df, config.get('technical', {}))
        
        # 識別圖形模式
        pattern_types = config.get('patterns', {}).get('selected', [])
        self.configurator.identify_patterns(df, pattern_types)
        
        # 計算分數
        regime = config.get('regime', None)
        df = self.scoring_engine.calculate_total_score(df, config, regime=regime)
        
        # 生成信號
        signals = self._generate_signals(df)
        
        # 生成理由標籤
        reason_tags_list = []
        for idx, row in df.iterrows():
            reasons = self.reason_engine.generate_reasons(row, config)
            tags = ReasonTagGenerator.generate_tags(reasons)
            reason_tags_list.append(tags)
        
        reason_tags = pd.Series(reason_tags_list, index=df.index)
        regime_match = df.get('RegimeMatch', pd.Series(True, index=df.index))
        
        scores = {
            'score': df.get('TotalScore', pd.Series(50.0, index=df.index)),
            'indicator_score': df.get('IndicatorScore', pd.Series(50.0, index=df.index)),
            'pattern_score': df.get('PatternScore', pd.Series(50.0, index=df.index)),
            'volume_score': df.get('VolumeScore', pd.Series(50.0, index=df.index))
        }
        
        return DailySignalFrame.create(
            df=df,
            signals=signals,
            scores=scores,
            reason_tags=reason_tags,
            regime_match=regime_match
        )
    
    def _generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """生成信號（穩健進出）"""
        signals = pd.Series(0, index=df.index)
        in_position = False
        last_trade_date = None
        last_trade_type = None
        
        buy_confirmed = self._calculate_confirmed_signals(
            df['TotalScore'] >= self.buy_score,
            self.buy_confirm_days
        )
        sell_confirmed = self._calculate_confirmed_signals(
            df['TotalScore'] <= self.sell_score,
            self.sell_confirm_days
        )
        
        for i, (date, row) in enumerate(df.iterrows()):
            in_cooldown = False
            if last_trade_date is not None:
                days_since_trade = (date - last_trade_date).days
                if days_since_trade < self.cooldown_days:
                    if (last_trade_type == 'buy' and sell_confirmed.iloc[i]) or \
                       (last_trade_type == 'sell' and buy_confirmed.iloc[i]):
                        in_cooldown = True
            
            if not in_position and buy_confirmed.iloc[i] and not in_cooldown:
                signals.iloc[i] = 1
                in_position = True
                last_trade_date = date
                last_trade_type = 'buy'
            elif in_position and sell_confirmed.iloc[i] and not in_cooldown:
                signals.iloc[i] = -1
                in_position = False
                last_trade_date = date
                last_trade_type = 'sell'
        
        return signals
    
    def _calculate_confirmed_signals(self, condition: pd.Series, confirm_days: int) -> pd.Series:
        """計算連續確認信號"""
        if confirm_days <= 1:
            return condition
        
        confirmed = pd.Series(False, index=condition.index)
        for i in range(confirm_days - 1, len(condition)):
            if condition.iloc[i - confirm_days + 1:i + 1].all():
                confirmed.iloc[i] = True
        return confirmed
    
    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """準備 DataFrame"""
        df = df.copy()
        price_columns = ['開盤價', '最高價', '最低價', '收盤價', 'Open', 'High', 'Low', 'Close']
        for col in price_columns:
            if col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace('--', '')
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
                df[col] = df[col].ffill().bfill().fillna(0.0)
        
        volume_columns = ['成交股數', '成交筆數', '成交金額', 'Volume', 'volume']
        for col in volume_columns:
            if col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace(',', '').str.replace('--', '')
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
                df[col] = df[col].ffill().bfill().fillna(0.0)
        
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if df[col].dtype != 'float64':
                df[col] = df[col].astype('float64')
            df[col] = df[col].replace([np.inf, -np.inf], np.nan).ffill().bfill().fillna(0.0)
        
        return df

