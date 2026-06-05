"""
Flow Signal Engine
負責計算 Smart Money Score、信心度以及可解釋性訊號標籤
"""

import math
from typing import List, Dict, Any
from collections import defaultdict

from app_module.dtos.broker_flow_dtos import StockFlowAggregation, BrokerFlowEvent
from app_module.dtos.flow_signal_dtos import FlowSignalDTO

class FlowSignalEngine:
    """Smart Money Flow 信號引擎"""
    
    def __init__(self):
        pass
        
    def generate_signals(self, aggregations: List[StockFlowAggregation]) -> List[FlowSignalDTO]:
        """
        將股票的聚合流向資料轉換為交易信號
        
        Args:
            aggregations: 股票的流向聚合資料
            
        Returns:
            信號列表，依據 smart_money_score 降冪排序
        """
        signals = []
        for agg in aggregations:
            signal = self._process_single_stock(agg)
            signals.append(signal)
            
        # 依照主力分數排序
        signals.sort(key=lambda x: x.smart_money_score, reverse=True)
        return signals
        
    def _process_single_stock(self, agg: StockFlowAggregation) -> FlowSignalDTO:
        """處理單一股票的信號邏輯"""
        
        score = 0.0
        confidence = 0.0
        tags = []
        reasons = []
        
        # 1. 基礎流量分數 (Base Flow Score)
        # 依據淨買超張數給予基礎分數 (非線性，避免極端值主導)
        if agg.total_net_qty > 0:
            # 買超
            base_score = min(40.0, math.sqrt(agg.total_net_qty) / 2.0)
            score += base_score
        elif agg.total_net_qty < 0:
            # 賣超 (如果是賣超，分數可以是負的或極低，這裡設計 0~100，所以賣超為 0)
            base_score = 0
            
        # 2. 主力一致性 (Branch Consensus)
        buy_branch_count = len(agg.buying_branches)
        sell_branch_count = len(agg.selling_branches)
        
        if buy_branch_count >= 2 and agg.total_net_qty > 0:
            score += min(30.0, buy_branch_count * 5.0)
            tags.append("主力一致買超")
            reasons.append(f"共有 {buy_branch_count} 家追蹤主力同步買進")
            
        # 3. 連續吸籌 (Continuous Accumulation)
        # 計算買超天數
        buy_dates = set()
        for event in agg.events:
            if event.net_qty > 0:
                buy_dates.add(event.date)
                
        continuous_days = len(buy_dates)
        if continuous_days >= 2 and agg.total_net_qty > 0:
            score += min(20.0, continuous_days * 5.0)
            tags.append("連續吸籌")
            reasons.append(f"主力在過去期間內有 {continuous_days} 天呈現淨買超")
            
        # 4. 籌碼集中度 (Branch Concentration)
        # 計算買超最大的分點佔總買超的比例
        concentration = 0.0
        if agg.total_net_qty > 0 and agg.events:
            branch_net_buy: defaultdict[str, int] = defaultdict(int)
            for event in agg.events:
                if event.net_qty > 0:
                    branch_net_buy[event.branch_display_name] += event.net_qty
            
            if branch_net_buy:
                max_branch_buy = max(branch_net_buy.values())
                total_positive_buy = sum(branch_net_buy.values())
                if total_positive_buy > 0:
                    concentration = max_branch_buy / total_positive_buy
                    
                    if concentration >= 0.7:
                        score += 10.0
                        tags.append("高度集中")
                        top_branch = max(branch_net_buy.items(), key=lambda x: x[1])[0]
                        reasons.append(f"籌碼高度集中於特定主力 ({top_branch} 佔 {concentration:.0%})")
        
        # 限制最高 100 分
        final_score = min(100.0, score)
        
        # 信心度計算 (基於資料點的多寡與一致性)
        if agg.total_net_qty > 0:
            base_confidence = 0.5
            # 多家分點買進提升信心
            if buy_branch_count >= 3: base_confidence += 0.2
            # 多天連續買進提升信心
            if continuous_days >= 3: base_confidence += 0.2
            # 賣方力量小提升信心
            if sell_branch_count == 0: base_confidence += 0.1
            confidence = min(1.0, base_confidence)
        else:
            confidence = 0.1
            
        # 5. 計算 Sparkline 資料 (依日期排序的每日淨買賣超序列)
        daily_net: defaultdict[str, int] = defaultdict(int)
        for event in agg.events:
            daily_net[event.date] += event.net_qty
        
        # 依照日期排序，抽出淨買賣超數值
        sorted_dates = sorted(daily_net.keys())
        sparkline_data = [float(daily_net[d]) for d in sorted_dates]
        
        # 6. 計算強度等級 Intensity Level (-3 到 3)
        intensity_level = 0
        if agg.total_net_qty > 0:
            if final_score >= 80: intensity_level = 3
            elif final_score >= 50: intensity_level = 2
            elif final_score >= 20: intensity_level = 1
        elif agg.total_net_qty < 0:
            # 賣超時，由於分數預設為0，依據賣超張數來決定負向強度
            if agg.total_net_qty <= -500: intensity_level = -3
            elif agg.total_net_qty <= -200: intensity_level = -2
            else: intensity_level = -1
            
        return FlowSignalDTO(
            stock_code=agg.stock_code,
            stock_name=agg.stock_name,
            aggregation=agg,
            smart_money_score=round(final_score, 1),
            confidence=round(confidence, 2),
            signal_tags=tags,
            explainable_reasons=reasons,
            branch_concentration=round(concentration, 2),
            sparkline_data=sparkline_data,
            intensity_level=intensity_level
        )
