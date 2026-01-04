"""
推薦理由引擎
生成可解釋的推薦理由，包含標籤、證據和分數貢獻
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional

class ReasonEngine:
    """推薦理由引擎"""
    
    def __init__(self):
        """初始化理由引擎"""
        pass
    
    def generate_reasons(self, row: pd.Series, config: Dict) -> List[Dict]:
        """生成推薦理由（包含市場狀態信息）
        
        Args:
            row: 單一股票的數據行（包含所有指標和分數）
            config: 策略配置（包含 regime 信息）
            
        Returns:
            List[Dict]: 理由列表，每個理由包含 {tag, evidence, score_contrib}
        """
        reasons = []
        
        # 0. 市場狀態理由（優先顯示）
        regime = config.get('regime')
        if regime:
            regime_name_map = {
                'Trend': '趨勢追蹤',
                'Reversion': '均值回歸',
                'Breakout': '突破準備'
            }
            regime_name = regime_name_map.get(regime, regime)
            regime_confidence = config.get('regime_confidence', 0.5)
            
            regime_match = row.get('RegimeMatch', True)
            if regime_match:
                reasons.append({
                    'tag': f'市場狀態為【{regime_name}】',
                    'evidence': f'適合{regime_name}策略，信心度{regime_confidence:.0%}',
                    'score_contrib': 10  # 匹配市場狀態加分
                })
            else:
                reasons.append({
                    'tag': f'市場狀態為【{regime_name}】',
                    'evidence': f'但股票行為不完全匹配，已降權',
                    'score_contrib': -5
                })
        
        # 1. 技術指標理由
        reasons.extend(self._generate_indicator_reasons(row, config))
        
        # 2. 圖形模式理由
        reasons.extend(self._generate_pattern_reasons(row, config))
        
        # 3. 成交量理由
        reasons.extend(self._generate_volume_reasons(row, config))
        
        # 4. 分數貢獻理由
        reasons.extend(self._generate_score_contrib_reasons(row))
        
        # 按貢獻分數排序
        reasons.sort(key=lambda x: abs(x.get('score_contrib', 0)), reverse=True)
        
        return reasons
    
    def _generate_indicator_reasons(self, row: pd.Series, config: Dict) -> List[Dict]:
        """生成技術指標理由"""
        reasons = []
        tech_config = config.get('technical', {})
        
        # RSI 理由
        if tech_config.get('momentum', {}).get('rsi', {}).get('enabled', False):
            rsi_val = None
            for col in ['RSI', 'rsi', 'RSI_14']:
                if col in row.index and pd.notna(row[col]):
                    rsi_val = row[col]
                    break
            
            if rsi_val is not None:
                if rsi_val < 30:
                    contrib = (30 - rsi_val) / 30 * 30  # 最多30分貢獻
                    reasons.append({
                        'tag': 'RSI超賣',
                        'evidence': f'RSI({tech_config.get("momentum", {}).get("rsi", {}).get("period", 14)})={rsi_val:.1f} < 30',
                        'score_contrib': contrib
                    })
                elif rsi_val > 70:
                    contrib = -(rsi_val - 70) / 30 * 30  # 負貢獻
                    reasons.append({
                        'tag': 'RSI超買',
                        'evidence': f'RSI({tech_config.get("momentum", {}).get("rsi", {}).get("period", 14)})={rsi_val:.1f} > 70',
                        'score_contrib': contrib
                    })
        
        # MACD 理由
        if tech_config.get('momentum', {}).get('macd', {}).get('enabled', False):
            macd_val = None
            signal_val = None
            hist_val = None
            
            for col in ['MACD', 'macd']:
                if col in row.index and pd.notna(row[col]):
                    macd_val = row[col]
                    break
            
            for col in ['MACD_Signal', 'macd_signal', 'Signal']:
                if col in row.index and pd.notna(row[col]):
                    signal_val = row[col]
                    break
            
            for col in ['MACD_hist', 'macd_hist', 'MACD_histogram']:
                if col in row.index and pd.notna(row[col]):
                    hist_val = row[col]
                    break
            
            if macd_val is not None and signal_val is not None:
                regime = config.get('regime')
                
                if macd_val > signal_val:
                    if regime == 'Trend':
                        # Trend 策略：0軸以上金叉加權最高
                        if macd_val > 0:
                            contrib = 30  # Trend 策略中0軸上金叉高分
                            tag = 'MACD金叉(0軸上)'
                        else:
                            contrib = 15
                            tag = 'MACD金叉(0軸下)'
                    else:
                        contrib = 20
                        if macd_val > 0:
                            contrib += 10
                            tag = 'MACD金叉(0軸上)'
                        else:
                            tag = 'MACD金叉(0軸下)'
                    
                    if hist_val is not None and hist_val > 0:
                        contrib += 5
                        tag += '柱狀體擴大'
                    
                    reasons.append({
                        'tag': tag,
                        'evidence': f'MACD({macd_val:.2f}) > Signal({signal_val:.2f})',
                        'score_contrib': contrib
                    })
                elif macd_val < signal_val:
                    contrib = -15
                    if macd_val < 0:
                        contrib -= 5
                        tag = 'MACD死叉(0軸下)'
                    else:
                        tag = 'MACD死叉(0軸上)'
                    
                    reasons.append({
                        'tag': tag,
                        'evidence': f'MACD({macd_val:.2f}) < Signal({signal_val:.2f})',
                        'score_contrib': contrib
                    })
        
        # KD 理由
        if tech_config.get('momentum', {}).get('kd', {}).get('enabled', False):
            k_val = None
            d_val = None
            
            for col in ['slowk', 'K', 'k']:
                if col in row.index and pd.notna(row[col]):
                    k_val = row[col]
                    break
            
            for col in ['slowd', 'D', 'd']:
                if col in row.index and pd.notna(row[col]):
                    d_val = row[col]
                    break
            
            if k_val is not None and d_val is not None:
                if k_val > d_val and k_val < 30:
                    reasons.append({
                        'tag': 'KD低檔金叉',
                        'evidence': f'K({k_val:.1f}) > D({d_val:.1f}) 且位於低檔',
                        'score_contrib': 15
                    })
                elif k_val > 80 and d_val > 80:
                    reasons.append({
                        'tag': 'KD高檔鈍化',
                        'evidence': f'K({k_val:.1f}) 和 D({d_val:.1f}) 均 > 80',
                        'score_contrib': -10
                    })
        
        # ADX 理由
        if tech_config.get('trend', {}).get('adx', {}).get('enabled', False):
            adx_val = None
            for col in ['ADX', 'adx']:
                if col in row.index and pd.notna(row[col]):
                    adx_val = row[col]
                    break
            
            if adx_val is not None:
                if adx_val > 25:
                    reasons.append({
                        'tag': 'ADX趨勢成立',
                        'evidence': f'ADX({adx_val:.1f}) > 25，趨勢強度高',
                        'score_contrib': 10
                    })
                elif adx_val < 20:
                    reasons.append({
                        'tag': 'ADX盤整',
                        'evidence': f'ADX({adx_val:.1f}) < 20，處於盤整狀態',
                        'score_contrib': -5
                    })
        
        # 均線系統理由
        if tech_config.get('trend', {}).get('ma', {}).get('enabled', False):
            windows = tech_config.get('trend', {}).get('ma', {}).get('windows', [5, 10, 20, 60])
            ma_values = []
            ma_cols = []
            
            for window in windows:
                for col in [f'MA{window}', f'SMA{window}', f'MA_{window}']:
                    if col in row.index and pd.notna(row[col]):
                        ma_values.append(row[col])
                        ma_cols.append((window, col))
                        break
            
            if len(ma_values) >= 2:
                # 檢查多頭/空頭排列
                is_bullish = all(ma_values[i] > ma_values[i+1] for i in range(len(ma_values)-1))
                is_bearish = all(ma_values[i] < ma_values[i+1] for i in range(len(ma_values)-1))
                
                if is_bullish:
                    reasons.append({
                        'tag': '均線多頭排列',
                        'evidence': f'短均線 > 長均線，趨勢向上',
                        'score_contrib': 15
                    })
                elif is_bearish:
                    reasons.append({
                        'tag': '均線空頭排列',
                        'evidence': f'短均線 < 長均線，趨勢向下',
                        'score_contrib': -10
                    })
        
        return reasons
    
    def _generate_pattern_reasons(self, row: pd.Series, config: Dict) -> List[Dict]:
        """生成圖形模式理由"""
        reasons = []
        pattern_types = config.get('patterns', {}).get('selected', [])
        
        # TODO: 整合 PatternAnalyzer 獲取實際的模式信息
        # 目前先返回空列表，等待 PatternAnalyzer 整合
        
        return reasons
    
    def _generate_volume_reasons(self, row: pd.Series, config: Dict) -> List[Dict]:
        """生成成交量理由"""
        reasons = []
        volume_conditions = config.get('signals', {}).get('volume_conditions', [])
        
        if len(volume_conditions) == 0:
            return reasons
        
        # 獲取成交量數據
        volume_col = None
        for col in ['成交股數', 'Volume', 'volume']:
            if col in row.index and pd.notna(row[col]):
                volume_col = col
                break
        
        if volume_col is None:
            return reasons
        
        # 計算成交量比率（需要歷史數據，這裡簡化處理）
        # 實際應該從歷史數據計算
        
        regime = config.get('regime')
        
        if 'increasing' in volume_conditions:
            # 假設有成交量變化率數據
            vol_change = row.get('成交量變化率%', 0)
            if vol_change > 50:
                contrib = min(vol_change / 50 * 10, 20)
                if regime == 'Trend':
                    contrib = min(vol_change / 50 * 12, 25)  # Trend 策略中成交量放大加分更多
                reasons.append({
                    'tag': '成交量放大',
                    'evidence': f'成交量變化率 {vol_change:.1f}%',
                    'score_contrib': contrib
                })
        
        if 'spike' in volume_conditions:
            # 成交量尖峰
            vol_change = row.get('成交量變化率%', 0)
            if vol_change > 100:
                contrib = 20 if regime == 'Breakout' else 15  # Breakout 策略中尖峰必須
                reasons.append({
                    'tag': '成交量尖峰',
                    'evidence': f'成交量變化率 {vol_change:.1f}%，異常放大',
                    'score_contrib': contrib
                })
        
        return reasons
    
    def _generate_score_contrib_reasons(self, row: pd.Series) -> List[Dict]:
        """生成分數貢獻理由"""
        reasons = []
        
        # 如果有各項分數，顯示分數貢獻
        if 'IndicatorScore' in row.index and pd.notna(row['IndicatorScore']):
            contrib = row['IndicatorScore'] - 50  # 相對於中性的貢獻
            if abs(contrib) > 5:
                reasons.append({
                    'tag': '技術指標分數',
                    'evidence': f'IndicatorScore={row["IndicatorScore"]:.1f}',
                    'score_contrib': contrib
                })
        
        if 'PatternScore' in row.index and pd.notna(row['PatternScore']):
            contrib = row['PatternScore'] - 50
            if abs(contrib) > 5:
                reasons.append({
                    'tag': '圖形模式分數',
                    'evidence': f'PatternScore={row["PatternScore"]:.1f}',
                    'score_contrib': contrib
                })
        
        if 'VolumeScore' in row.index and pd.notna(row['VolumeScore']):
            contrib = row['VolumeScore'] - 50
            if abs(contrib) > 5:
                reasons.append({
                    'tag': '成交量分數',
                    'evidence': f'VolumeScore={row["VolumeScore"]:.1f}',
                    'score_contrib': contrib
                })
        
        return reasons
    
    def format_reason_text(self, reasons: List[Dict], max_reasons: int = 4) -> str:
        """格式化理由文字（用於UI顯示）
        
        Args:
            reasons: 理由列表
            max_reasons: 最多顯示幾個理由
            
        Returns:
            str: 格式化的理由文字
        """
        if len(reasons) == 0:
            return "符合策略條件"
        
        # 只顯示前N個最有貢獻的理由
        top_reasons = reasons[:max_reasons]
        
        reason_texts = []
        for reason in top_reasons:
            tag = reason.get('tag', '')
            contrib = reason.get('score_contrib', 0)
            
            # 根據貢獻分數添加符號
            if contrib > 0:
                symbol = '+'
            elif contrib < 0:
                symbol = '-'
            else:
                symbol = ''
            
            reason_texts.append(f"{tag}{symbol}")
        
        return "、".join(reason_texts)

