"""
理由標籤系統
將推薦理由轉換為可回測的標籤，用於統計分析
"""

from typing import List, Dict, Set
import pandas as pd


class ReasonTagGenerator:
    """理由標籤生成器"""
    
    # 標準化的理由標籤映射
    TAG_MAPPING = {
        # RSI 相關
        'RSI超賣': 'rsi_oversold',
        'RSI超買': 'rsi_overbought',
        
        # MACD 相關
        'MACD金叉(0軸上)': 'macd_golden_cross_above_zero',
        'MACD金叉(0軸下)': 'macd_golden_cross_below_zero',
        'MACD死叉(0軸上)': 'macd_death_cross_above_zero',
        'MACD死叉(0軸下)': 'macd_death_cross_below_zero',
        'MACD金叉': 'macd_golden_cross',
        'MACD死叉': 'macd_death_cross',
        
        # KD 相關
        'KD低檔金叉': 'kd_golden_cross_oversold',
        'KD高檔鈍化': 'kd_overbought',
        
        # ADX 相關
        'ADX趨勢成立': 'adx_trend_established',
        'ADX盤整': 'adx_consolidation',
        
        # 均線相關
        '均線多頭排列': 'ma_alignment_bullish',
        '均線空頭排列': 'ma_alignment_bearish',
        
        # 成交量相關
        '成交量放大': 'volume_surge',
        '成交量尖峰': 'volume_spike',
        
        # 價格相關
        '突破20日新高': 'breakout_20d_high',
        '突破60日新高': 'breakout_60d_high',
        '創新高': 'new_high',
        
        # 產業相關
        '產業強勢': 'industry_strength',
        
        # Regime 相關
        '市場狀態為【趨勢追蹤】': 'regime_trend',
        '市場狀態為【均值回歸】': 'regime_reversion',
        '市場狀態為【突破準備】': 'regime_breakout',
    }
    
    @classmethod
    def generate_tags(cls, reasons: List[Dict]) -> List[str]:
        """
        從理由列表生成標準化的理由標籤
        
        Args:
            reasons: 理由列表，每個理由包含 {'tag': str, 'evidence': str, 'score_contrib': float}
        
        Returns:
            標準化的理由標籤列表
        """
        tags = []
        
        for reason in reasons:
            tag = reason.get('tag', '')
            if not tag:
                continue
            
            # 查找標準化標籤
            standardized_tag = cls.TAG_MAPPING.get(tag)
            if standardized_tag:
                tags.append(standardized_tag)
            else:
                # 如果沒有映射，嘗試從 tag 生成標準化標籤
                normalized = cls._normalize_tag(tag)
                if normalized:
                    tags.append(normalized)
        
        # 去重並排序
        return sorted(list(set(tags)))
    
    @classmethod
    def _normalize_tag(cls, tag: str) -> str:
        """
        標準化標籤名稱（將中文轉換為英文標籤）
        
        Args:
            tag: 原始標籤
        
        Returns:
            標準化標籤（如果無法標準化則返回 None）
        """
        # 簡單的標準化規則
        tag_lower = tag.lower()
        
        # 移除特殊字符
        tag_clean = tag_lower.replace('【', '').replace('】', '').replace('（', '').replace('）', '')
        
        # 如果已經是英文格式，直接返回
        if tag_clean.replace('_', '').replace('-', '').isalnum():
            return tag_clean.replace(' ', '_')
        
        return None
    
    @classmethod
    def extract_tags_from_evidence(cls, evidence: str) -> List[str]:
        """
        從證據字符串中提取標籤
        
        Args:
            evidence: 證據字符串
        
        Returns:
            提取的標籤列表
        """
        tags = []
        
        # 簡單的關鍵詞匹配
        keywords = {
            '突破': 'breakout',
            '新高': 'new_high',
            '量能': 'volume',
            '放大': 'surge',
            '金叉': 'golden_cross',
            '死叉': 'death_cross',
            '超賣': 'oversold',
            '超買': 'overbought',
            '多頭': 'bullish',
            '空頭': 'bearish',
        }
        
        evidence_lower = evidence.lower()
        for keyword, tag in keywords.items():
            if keyword in evidence_lower:
                tags.append(tag)
        
        return tags
    
    @classmethod
    def combine_tags(cls, tag_lists: List[List[str]]) -> List[str]:
        """
        合併多個標籤列表
        
        Args:
            tag_lists: 標籤列表的列表
        
        Returns:
            合併後的標籤列表（去重）
        """
        all_tags = []
        for tag_list in tag_lists:
            all_tags.extend(tag_list)
        
        return sorted(list(set(all_tags)))
    
    @classmethod
    def analyze_tag_statistics(
        cls,
        trades: List[Dict],
        tag_field: str = 'reason_tags'
    ) -> Dict[str, Dict]:
        """
        分析理由標籤統計
        
        Args:
            trades: 交易列表，每個交易包含 reason_tags 欄位
            tag_field: 標籤欄位名稱
        
        Returns:
            標籤統計字典 {tag: {'count': int, 'win_rate': float, 'avg_return': float, ...}}
        """
        tag_stats = {}
        
        for trade in trades:
            tags_str = trade.get(tag_field, '')
            if not tags_str:
                continue
            
            # 解析標籤
            tags = [t.strip() for t in tags_str.split(',') if t.strip()]
            
            # 獲取交易結果
            is_win = trade.get('profit', 0) > 0
            return_pct = trade.get('return_pct', 0)
            
            # 統計每個標籤
            for tag in tags:
                if tag not in tag_stats:
                    tag_stats[tag] = {
                        'count': 0,
                        'win_count': 0,
                        'total_return': 0.0,
                        'returns': []
                    }
                
                tag_stats[tag]['count'] += 1
                if is_win:
                    tag_stats[tag]['win_count'] += 1
                tag_stats[tag]['total_return'] += return_pct
                tag_stats[tag]['returns'].append(return_pct)
        
        # 計算統計指標
        for tag, stats in tag_stats.items():
            stats['win_rate'] = stats['win_count'] / stats['count'] if stats['count'] > 0 else 0.0
            stats['avg_return'] = stats['total_return'] / stats['count'] if stats['count'] > 0 else 0.0
            
            # 計算期望值（平均報酬）
            stats['expectancy'] = stats['avg_return']
            
            # 計算勝率加權報酬
            if stats['returns']:
                import numpy as np
                stats['std_return'] = float(np.std(stats['returns']))
            else:
                stats['std_return'] = 0.0
        
        return tag_stats

