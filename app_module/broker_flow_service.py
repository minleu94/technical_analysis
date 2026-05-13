"""
Broker Flow Orchestration Service
負責資料讀取、聚合管線 (Pipeline)，以及串接決策模組的 FlowSignalEngine
"""

import logging
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict
from datetime import datetime, timedelta

from app_module.dtos.broker_flow_dtos import BrokerFlowEvent, StockFlowAggregation, BranchFlowAggregation
from app_module.dtos.flow_signal_dtos import FlowSignalDTO, SmartMoneySummaryDTO
from decision_module.flow_signal_engine import FlowSignalEngine

class BrokerFlowService:
    """Smart Money Flow 服務編排層"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.signal_engine = FlowSignalEngine()
        
        # 記憶體快取
        self._cached_events: List[BrokerFlowEvent] = []
        self._last_load_time = None
        
    def _load_data(self, force_reload: bool = False) -> List[BrokerFlowEvent]:
        """從檔案系統載入所有追蹤分點的原始事件資料"""
        
        # 簡單快取機制：如果已經載入且不強制重新載入，直接返回
        if not force_reload and self._cached_events:
            return self._cached_events
            
        events = []
        flow_dir = getattr(self.config, 'broker_flow_dir', Path(self.config.data_dir) / 'broker_flow')
        
        if not flow_dir.exists():
            self.logger.warning(f"分點資料目錄不存在: {flow_dir}")
            return []
            
        # 遍歷所有分點目錄
        for branch_dir in flow_dir.iterdir():
            if not branch_dir.is_dir():
                continue
                
            merged_file = branch_dir / 'meta' / 'merged.csv'
            if not merged_file.exists():
                continue
                
            try:
                # 讀取合併的 CSV
                df = pd.read_csv(merged_file)
                # 轉換為 BrokerFlowEvent 列表
                for _, row in df.iterrows():
                    # 嘗試各種可能的對手券商/股票代號欄位名稱
                    stock_code = str(row.get('counterparty_broker_code', ''))
                    stock_name = str(row.get('counterparty_broker_name', ''))
                    
                    if not stock_code or stock_code == 'nan' or stock_code == 'UNKNOWN':
                        continue
                        
                    event = BrokerFlowEvent(
                        date=str(row.get('date', '')),
                        branch_system_key=str(row.get('branch_system_key', branch_dir.name)),
                        branch_display_name=str(row.get('branch_display_name', branch_dir.name)),
                        stock_code=stock_code,
                        stock_name=stock_name,
                        buy_qty=int(float(row.get('buy_qty', 0))),
                        sell_qty=int(float(row.get('sell_qty', 0))),
                        net_qty=int(float(row.get('net_qty', 0)))
                    )
                    events.append(event)
                    
            except Exception as e:
                self.logger.error(f"讀取分點資料失敗 {merged_file}: {e}")
                
        self._cached_events = events
        self._last_load_time = datetime.now()
        self.logger.info(f"成功載入 {len(events)} 筆分點交易事件")
        return events
        
    def _filter_events_by_period(self, events: List[BrokerFlowEvent], period: str) -> List[BrokerFlowEvent]:
        """過濾特定時間範圍的事件"""
        if not events:
            return []
            
        # 找出最新日期 (作為基準點)
        latest_date_str = max(e.date for e in events)
        try:
            latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d")
        except ValueError:
            latest_date = datetime.now()
            
        if period == 'day':
            start_date = latest_date
        elif period == 'week':
            start_date = latest_date - timedelta(days=7)
        elif period == 'month':
            start_date = latest_date - timedelta(days=30)
        else:
            return events # All time
            
        start_date_str = start_date.strftime("%Y-%m-%d")
        return [e for e in events if e.date >= start_date_str]

    def get_stock_flow_signals(self, period: str = 'week', force_reload: bool = False) -> List[FlowSignalDTO]:
        """
        [Overview Mode] 取得以「股票」為中心的 Smart Money 流向信號
        
        Args:
            period: 'day', 'week', 'month'
            force_reload: 是否重新讀取 CSV
            
        Returns:
            FlowSignalDTO 列表，按主力分數降序排列
        """
        events = self._load_data(force_reload)
        filtered_events = self._filter_events_by_period(events, period)
        
        # 聚合資料
        # dict key: stock_code
        agg_map: Dict[str, StockFlowAggregation] = {}
        
        for e in filtered_events:
            if e.stock_code not in agg_map:
                agg_map[e.stock_code] = StockFlowAggregation(
                    stock_code=e.stock_code,
                    stock_name=e.stock_name
                )
                
            agg = agg_map[e.stock_code]
            agg.total_buy_qty += e.buy_qty
            agg.total_sell_qty += e.sell_qty
            agg.total_net_qty += e.net_qty
            agg.events.append(e)
            
            if e.net_qty > 0 and e.branch_display_name not in agg.buying_branches:
                agg.buying_branches.append(e.branch_display_name)
            elif e.net_qty < 0 and e.branch_display_name not in agg.selling_branches:
                agg.selling_branches.append(e.branch_display_name)
                
        # 轉換為信號
        aggregations = list(agg_map.values())
        signals = self.signal_engine.generate_signals(aggregations)
        
        # 過濾掉分數太低的，或是總淨量為負的
        filtered_signals = [s for s in signals if s.smart_money_score > 0 and s.aggregation.total_net_qty > 0]
        return filtered_signals

    def get_branch_flow_details(self, period: str = 'week', force_reload: bool = False) -> List[BranchFlowAggregation]:
        """
        [Branch Tracker Mode] 取得以「分點」為中心的聚合流向
        
        Args:
            period: 'day', 'week', 'month'
            force_reload: 是否重新讀取 CSV
            
        Returns:
            BranchFlowAggregation 列表，通常用於 UI 分群顯示
        """
        events = self._load_data(force_reload)
        filtered_events = self._filter_events_by_period(events, period)
        
        # 聚合資料
        # dict key: (branch_key, stock_code)
        agg_map: Dict[tuple, BranchFlowAggregation] = {}
        
        for e in filtered_events:
            key = (e.branch_system_key, e.stock_code)
            if key not in agg_map:
                agg_map[key] = BranchFlowAggregation(
                    branch_system_key=e.branch_system_key,
                    branch_display_name=e.branch_display_name,
                    stock_code=e.stock_code,
                    stock_name=e.stock_name
                )
                
            agg = agg_map[key]
            agg.total_buy_qty += e.buy_qty
            agg.total_sell_qty += e.sell_qty
            agg.total_net_qty += e.net_qty
            agg.events.append(e)
            
        return list(agg_map.values())
        
    def get_stock_detail_by_branches(self, stock_code: str, period: str = 'week') -> List[BranchFlowAggregation]:
        """取得特定股票的所有分點進出明細 (供 Overview Mode 的 Master-Detail Drill-down 使用)"""
        # 利用現有方法取得所有分點資料，然後過濾
        all_branch_flows = self.get_branch_flow_details(period=period, force_reload=False)
        return [b for b in all_branch_flows if b.stock_code == stock_code]

    def get_tracked_branches(self) -> List[Dict[str, str]]:
        """取得目前有資料的分點清單 (供 Branch Tracker 模式選單使用)"""
        events = self._load_data()
        
        branches = {}
        for e in events:
            if e.branch_system_key not in branches:
                branches[e.branch_system_key] = e.branch_display_name
                
        # 轉換為 list of dicts 方便 UI 使用
        return [{"system_key": k, "display_name": v} for k, v in branches.items()]

    def get_market_flow_summary(self, signals: List[FlowSignalDTO] = None, period: str = 'week') -> SmartMoneySummaryDTO:
        """
        根據信號計算整體市場的主力流向摘要
        """
        if signals is None:
            signals = self.get_stock_flow_signals(period=period)
            
        summary = SmartMoneySummaryDTO()
        
        # 統計多空股票數量
        for s in signals:
            if s.aggregation.total_net_qty > 0:
                summary.bullish_stock_count += 1
                if s.smart_money_score >= 50:
                    summary.abnormal_signal_count += 1
            elif s.aggregation.total_net_qty < 0:
                summary.bearish_stock_count += 1
                if s.aggregation.total_net_qty <= -500:
                    summary.abnormal_signal_count += 1
                    
        # 計算市場熱度 (粗略算法)
        total_stocks = summary.bullish_stock_count + summary.bearish_stock_count
        if total_stocks > 0:
            bull_ratio = summary.bullish_stock_count / total_stocks
            summary.market_heat_score = bull_ratio * 100.0
            
        # 這裡的 market_regime, strong_industries 等可由外部 (例如 RegimeService) 提供或覆寫
        # 我們目前提供預設骨架，UI 呈現時若有需要可進一步擴充
        if summary.market_heat_score > 60:
            summary.market_regime = "Bullish Flow"
        elif summary.market_heat_score < 40:
            summary.market_regime = "Bearish Flow"
        else:
            summary.market_regime = "Neutral"
            
        return summary

