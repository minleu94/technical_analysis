"""
DailySignalFrame 統一輸出格式
推薦和回測共用同一條 signal pipeline
"""

import pandas as pd
from typing import List, Dict, Any, Optional
import numpy as np


class DailySignalFrame:
    """每日信號框架（統一輸出格式）"""
    
    @staticmethod
    def create(
        df: pd.DataFrame,
        signals: pd.Series,
        scores: Dict[str, pd.Series],
        reason_tags: pd.Series,
        regime_match: Optional[pd.Series] = None
    ) -> pd.DataFrame:
        """
        創建 DailySignalFrame
        
        Args:
            df: 原始數據 DataFrame（必須有日期索引或日期欄位）
            signals: 信號序列（1=買入, 0=持有, -1=賣出）
            scores: 分數字典 {'score': Series, 'indicator_score': Series, 'pattern_score': Series, 'volume_score': Series}
            reason_tags: 理由標籤序列（每個元素是 List[str] 或 str）
            regime_match: Regime 匹配序列（bool，可選）
        
        Returns:
            DailySignalFrame: index=date，欄位含 signal, score breakdown, reason tags
        """
        result = df.copy()
        
        # 確保日期索引
        date_index = None
        if isinstance(result.index, pd.DatetimeIndex):
            date_index = result.index
        elif '日期' in result.columns:
            result['日期'] = pd.to_datetime(result['日期'])
            date_index = result['日期']
            result = result.set_index('日期')
        else:
            raise ValueError("DataFrame 必須有日期索引或日期欄位")
        
        # 確保 signals 和 scores 的索引匹配
        if not signals.index.equals(date_index):
            signals = signals.reindex(date_index, fill_value=0)
        for key in scores:
            if not scores[key].index.equals(date_index):
                scores[key] = scores[key].reindex(date_index, fill_value=0.0)
        
        # 添加信號
        result['signal'] = signals
        
        # 添加分數
        for key, value in scores.items():
            result[key] = value
        
        # 添加理由標籤（轉換為字符串以便序列化）
        if reason_tags is not None:
            if not reason_tags.index.equals(date_index):
                reason_tags = reason_tags.reindex(date_index, fill_value=[])
            
            def format_reason_tags(x):
                if isinstance(x, list):
                    return ','.join(x)
                elif isinstance(x, str):
                    return x
                else:
                    return ''
            
            result['reason_tags'] = reason_tags.apply(format_reason_tags)
        else:
            result['reason_tags'] = ''
        
        # 添加 Regime 匹配
        if regime_match is not None:
            if not regime_match.index.equals(date_index):
                regime_match = regime_match.reindex(date_index, fill_value=False)
            result['regime_match'] = regime_match
        else:
            result['regime_match'] = False
        
        return result
    
    @staticmethod
    def get_latest_signals(signal_frame: pd.DataFrame, days: int = 1) -> pd.DataFrame:
        """
        獲取最新的信號（用於推薦）
        
        Args:
            signal_frame: DailySignalFrame
            days: 獲取最近幾天（預設1天）
        
        Returns:
            最新的信號 DataFrame
        """
        return signal_frame.tail(days)
    
    @staticmethod
    def parse_reason_tags(reason_tags_str: str) -> List[str]:
        """
        解析理由標籤字符串為列表
        
        Args:
            reason_tags_str: 理由標籤字符串（逗號分隔）
        
        Returns:
            理由標籤列表
        """
        if not reason_tags_str or reason_tags_str == '':
            return []
        return [tag.strip() for tag in reason_tags_str.split(',') if tag.strip()]

