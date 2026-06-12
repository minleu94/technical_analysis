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

        # 0. 處理張數不可用 (usable_event_count == 0)
        if not agg.lots_available or agg.usable_event_count == 0:
            return FlowSignalDTO(
                stock_code=agg.stock_code,
                stock_name=agg.stock_name,
                aggregation=agg,
                smart_money_score=0.0,
                confidence=0.0,
                signal_tags=["無張數數據"],
                explainable_reasons=["此期間內之張數資料因價格缺失無法計算或未提供"],
                branch_concentration=0.0,
                sparkline_data=[],
                intensity_level=0,
                lots_available=False,
                has_estimated_lots=False,
                observed_event_count=agg.observed_event_count,
                estimated_event_count=agg.estimated_event_count,
                unavailable_event_count=agg.unavailable_event_count,
                usable_event_count=agg.usable_event_count,
                lots_coverage_ratio=agg.lots_coverage_ratio
            )

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
        elif sell_branch_count >= 2 and agg.total_net_qty < 0:
            tags.append("主力一致賣超")
            reasons.append(f"共有 {sell_branch_count} 家追蹤主力同步賣出")

        # 3. 連續吸籌 / 出貨 (Continuous Accumulation / Distribution)
        # 按日期加總每日的淨量
        daily_net_map: defaultdict[str, int] = defaultdict(int)
        for event in agg.events:
            if event.net_qty is not None:
                daily_net_map[event.date] += event.net_qty

        sorted_dates = sorted(daily_net_map.keys(), reverse=True) # 由新到舊

        continuous_days = 0
        continuous_sell_days = 0

        if sorted_dates:
            latest_date = sorted_dates[0]
            latest_net = daily_net_map[latest_date]

            if latest_net > 0:
                # 計算連續買超天數
                for d in sorted_dates:
                    if daily_net_map[d] > 0:
                        continuous_days += 1
                    else:
                        break
            elif latest_net < 0:
                # 計算連續賣超天數
                for d in sorted_dates:
                    if daily_net_map[d] < 0:
                        continuous_sell_days += 1
                    else:
                        break

        if continuous_days >= 2 and agg.total_net_qty > 0:
            score += min(20.0, continuous_days * 5.0)
            tags.append("連續吸籌")
            reasons.append(f"主力在過去期間內連續 {continuous_days} 天呈現淨買超")
        elif continuous_sell_days >= 2 and agg.total_net_qty < 0:
            tags.append("連續出貨")
            reasons.append(f"主力在過去期間內連續 {continuous_sell_days} 天呈現淨賣超")

        # 4. 籌碼集中度 (Branch Concentration)
        # 計算買超/賣超最大的分點佔總買超/賣超的比例
        concentration = 0.0
        if agg.total_net_qty > 0 and agg.events:
            branch_net_buy: defaultdict[str, int] = defaultdict(int)
            for event in agg.events:
                if event.net_qty is not None and event.net_qty > 0:
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
        elif agg.total_net_qty < 0 and agg.events:
            branch_net_sell: defaultdict[str, int] = defaultdict(int)
            for event in agg.events:
                if event.net_qty is not None and event.net_qty < 0:
                    branch_net_sell[event.branch_display_name] += abs(event.net_qty)

            if branch_net_sell:
                max_branch_sell = max(branch_net_sell.values())
                total_negative_sell = sum(branch_net_sell.values())
                if total_negative_sell > 0:
                    concentration = max_branch_sell / total_negative_sell

                    if concentration >= 0.7:
                        tags.append("高度集中")
                        top_branch = max(branch_net_sell.items(), key=lambda x: x[1])[0]
                        reasons.append(f"籌碼高度集中於特定賣方主力 ({top_branch} 佔 {concentration:.0%})")

        from decimal import Decimal

        # 限制最高 100 分
        final_score = min(100.0, score)

        # 信心度計算 (基於資料點的多寡與一致性)
        if agg.total_net_qty > 0:
            base_confidence = 0.5
            if buy_branch_count >= 3: base_confidence += 0.2
            if continuous_days >= 3: base_confidence += 0.2
            if sell_branch_count == 0: base_confidence += 0.1
            confidence = min(1.0, base_confidence)
        else:
            confidence = 0.1

        # 覆蓋率與估計比例折舊 (Decimal)
        total_events = len(agg.events)
        if total_events > 0:
            coverage_ratio = Decimal(str(agg.usable_event_count)) / Decimal(str(total_events))
        else:
            coverage_ratio = Decimal('1')

        if agg.usable_event_count > 0:
            estimated_ratio = Decimal(str(agg.estimated_event_count)) / Decimal(str(agg.usable_event_count))
        else:
            estimated_ratio = Decimal('0')

        confidence_dec = Decimal(str(confidence)) * coverage_ratio
        max_confidence = Decimal('1.0') - Decimal('0.4') * estimated_ratio
        confidence_dec = min(confidence_dec, max_confidence)
        confidence = float(confidence_dec)  # numeric-boundary: dto

        # 若包含任何估計值，加入警告與標記
        if agg.has_estimated_lots:
            tags.append("金額估算")
            total_dec = Decimal(total_events)
            obs_pct = int(Decimal(agg.observed_event_count) * 100 / total_dec) if total_events > 0 else 0
            est_pct = int(Decimal(agg.estimated_event_count) * 100 / total_dec) if total_events > 0 else 0
            unavail_pct = int(Decimal(agg.unavailable_event_count) * 100 / total_dec) if total_events > 0 else 0
            reasons.append(
                f"⚠️ 注意：此期間包含金額估算張數（真實 {obs_pct}%｜估算 {est_pct}%｜不可用 {unavail_pct}%）。"
            )
        elif agg.unavailable_event_count > 0:
            coverage_pct = int(coverage_ratio * 100)
            reasons.append(f"⚠️ 張數資料覆蓋率 {coverage_pct}%，榜外且無價格資料已排除。")

        # 5. 計算 Sparkline 資料 (依日期排序的每日淨買賣超序列)
        daily_net: defaultdict[str, int] = defaultdict(int)
        for event in agg.events:
            if event.net_qty is not None:
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
            # 賣超時，由於分數預設為0，依據賣超張數來決定負向強度 (取消硬編碼估值加倍)
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
            intensity_level=intensity_level,
            lots_available=agg.lots_available,
            has_estimated_lots=agg.has_estimated_lots,
            observed_event_count=agg.observed_event_count,
            estimated_event_count=agg.estimated_event_count,
            unavailable_event_count=agg.unavailable_event_count,
            usable_event_count=agg.usable_event_count,
            lots_coverage_ratio=agg.lots_coverage_ratio
        )
