"""
Broker Flow Orchestration Service
負責資料讀取、聚合管線 (Pipeline)，以及串接決策模組的 FlowSignalEngine
"""

import logging
import pandas as pd
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Dict, Optional
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

    @staticmethod
    def _int_value(value: Any) -> int:
        if value is None or pd.isna(value):
            return 0
        return int(value)

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

        # 第一步先遍歷 CSV 並記錄缺失 Lots 欄位事件的 (date_str, stock_code)
        temp_events = []
        missing_keys = set()

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
                lot_columns = {'buy_lots', 'sell_lots', 'net_lots'}
                # 如果連這幾欄都沒有，則視為全部缺失
                has_cols = lot_columns.issubset(df.columns)

                for _, row in df.iterrows():
                    stock_code = str(row.get('counterparty_broker_code', '')).strip()
                    stock_name = str(row.get('counterparty_broker_name', '')).strip()

                    if not stock_code or stock_code == 'nan' or stock_code == 'UNKNOWN':
                        continue

                    raw_date = str(row.get('date', '')).strip()
                    db_date = raw_date.replace('-', '').replace('/', '')

                    # 嘗試讀取 observed metadata
                    lots_observed = row.get('lots_observed')
                    amount_observed = row.get('amount_observed')
                    lots_rank = row.get('lots_rank')
                    amount_rank = row.get('amount_rank')

                    buy_lots = row.get('buy_lots') if has_cols else None
                    sell_lots = row.get('sell_lots') if has_cols else None
                    net_lots = row.get('net_lots') if has_cols else None

                    is_missing = (
                        pd.isna(buy_lots) or buy_lots is None or
                        pd.isna(sell_lots) or sell_lots is None or
                        pd.isna(net_lots) or net_lots is None
                    )

                    if pd.isna(lots_observed) or lots_observed is None:
                        lots_observed = not is_missing
                    else:
                        lots_observed = bool(lots_observed)

                    if pd.isna(amount_observed) or amount_observed is None:
                        amount_observed = not pd.isna(row.get('buy_amount_k_twd'))
                    else:
                        amount_observed = bool(amount_observed)

                    lots_rank = None if pd.isna(lots_rank) or lots_rank is None else int(lots_rank)
                    amount_rank = None if pd.isna(amount_rank) or amount_rank is None else int(amount_rank)

                    if not lots_observed:
                        missing_keys.add((db_date, stock_code))

                    temp_events.append({
                        'raw_date': raw_date,
                        'db_date': db_date,
                        'branch_system_key': str(row.get('branch_system_key', branch_dir.name)),
                        'branch_display_name': str(row.get('branch_display_name', branch_dir.name)),
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'buy_lots': buy_lots,
                        'sell_lots': sell_lots,
                        'net_lots': net_lots,
                        'buy_amount_k_twd': row.get('buy_amount_k_twd'),
                        'sell_amount_k_twd': row.get('sell_amount_k_twd'),
                        'net_amount_k_twd': row.get('net_amount_k_twd'),
                        'lots_observed': lots_observed,
                        'amount_observed': amount_observed,
                        'lots_rank': lots_rank,
                        'amount_rank': amount_rank
                    })

            except Exception as e:
                self.logger.error(f"讀取分點資料失敗 {merged_file}: {e}")

        # 第二步：批次向 SQLite 查詢收盤價對照表 (優化為按日期分組 + IN 查詢)
        price_map = {}
        if missing_keys and getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)

                # 按日期分組收集股票代號
                date_to_stocks = defaultdict(set)
                for d, s in missing_keys:
                    date_to_stocks[d].add(s)

                # 每日執行一次 IN 查詢
                for d_val, stocks in date_to_stocks.items():
                    stocks_list = list(stocks)
                    chunk_size = 200
                    for k in range(0, len(stocks_list), chunk_size):
                        sub_stocks = stocks_list[k:k + chunk_size]
                        placeholders = ",".join("?" for _ in sub_stocks)
                        query = f"SELECT 證券代號, 收盤價 FROM daily_prices WHERE 日期 = ? AND 證券代號 IN ({placeholders})"
                        df_prices = db.execute_query(query, (d_val, *sub_stocks))
                        for _, row_p in df_prices.iterrows():
                            s_val = str(row_p['證券代號']).strip()
                            price_map[(d_val, s_val)] = str(row_p['收盤價']).strip()
            except Exception as e:
                self.logger.warning(f"分組查詢收盤價失敗: {e}")

        # 第三步：套用 Decimal 與 ROUND_HALF_UP 折算
        from decimal import Decimal, ROUND_HALF_UP

        for item in temp_events:
            buy_amount_k = item['buy_amount_k_twd']
            sell_amount_k = item['sell_amount_k_twd']
            net_amount_k = item['net_amount_k_twd']

            lots_observed = item['lots_observed']
            amount_observed = item['amount_observed']
            lots_rank = item['lots_rank']
            amount_rank = item['amount_rank']

            buy_amount_k = None if pd.isna(buy_amount_k) or buy_amount_k is None else int(buy_amount_k)
            sell_amount_k = None if pd.isna(sell_amount_k) or sell_amount_k is None else int(sell_amount_k)
            net_amount_k = None if pd.isna(net_amount_k) or net_amount_k is None else int(net_amount_k)

            if lots_observed:
                buy_qty = None if pd.isna(item['buy_lots']) or item['buy_lots'] is None else int(item['buy_lots'])
                sell_qty = None if pd.isna(item['sell_lots']) or item['sell_lots'] is None else int(item['sell_lots'])
                net_qty = None if pd.isna(item['net_lots']) or item['net_lots'] is None else int(item['net_lots'])
                lots_quality = "observed"

                if not amount_observed:
                    buy_amount_k = None
                    sell_amount_k = None
                    net_amount_k = None
                    amount_quality = "unavailable"
                else:
                    amount_quality = "observed"
            else:
                amount_quality = "observed" if amount_observed else "unavailable"
                key = (item['db_date'], item['stock_code'])
                close_price_str = price_map.get(key)

                if amount_observed and close_price_str is not None:
                    try:
                        d_buy = Decimal(str(self._int_value(buy_amount_k)))
                        d_sell = Decimal(str(self._int_value(sell_amount_k)))
                        d_close = Decimal(close_price_str)

                        if d_close.is_finite() and d_close > 0:
                            buy_qty = int((d_buy / d_close).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                            sell_qty = int((d_sell / d_close).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                            net_qty = buy_qty - sell_qty
                            lots_quality = "estimated"
                        else:
                            buy_qty = None
                            sell_qty = None
                            net_qty = None
                            lots_quality = "unavailable"
                    except Exception as e:
                        self.logger.warning(f"折算張數失敗 for {item['stock_code']} on {item['db_date']}: {e}")
                        buy_qty = None
                        sell_qty = None
                        net_qty = None
                        lots_quality = "unavailable"
                else:
                    buy_qty = None
                    sell_qty = None
                    net_qty = None
                    lots_quality = "unavailable"

            lots_available = lots_quality != "unavailable"
            has_estimated_lots = lots_quality == "estimated"

            event = BrokerFlowEvent(
                date=item['raw_date'],
                branch_system_key=item['branch_system_key'],
                branch_display_name=item['branch_display_name'],
                stock_code=item['stock_code'],
                stock_name=item['stock_name'],
                buy_qty=buy_qty,
                sell_qty=sell_qty,
                net_qty=net_qty,
                buy_amount_k_twd=buy_amount_k,
                sell_amount_k_twd=sell_amount_k,
                net_amount_k_twd=net_amount_k,
                lots_available=lots_available,
                has_estimated_lots=has_estimated_lots,
                lots_observed=lots_observed,
                amount_observed=amount_observed,
                lots_rank=lots_rank,
                amount_rank=amount_rank,
                lots_quality=lots_quality,
                amount_quality=amount_quality,
            )
            events.append(event)

        self._cached_events = events
        self._last_load_time = datetime.now()
        self.logger.info(f"成功載入 {len(events)} 筆分點交易事件")
        return events

    def get_events(self, force_reload: bool = False) -> List[BrokerFlowEvent]:
        """回傳分點事件快照，供唯讀語意層與 dashboard 使用。"""
        return list(self._load_data(force_reload=force_reload))

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
            agg.events.append(e)

            if e.lots_quality == "observed":
                agg.observed_event_count += 1
                agg.usable_event_count += 1
            elif e.lots_quality == "estimated":
                agg.estimated_event_count += 1
                agg.usable_event_count += 1
            else:
                agg.unavailable_event_count += 1

            if e.buy_qty is not None:
                agg.total_buy_qty += e.buy_qty
            if e.sell_qty is not None:
                agg.total_sell_qty += e.sell_qty
            if e.net_qty is not None:
                agg.total_net_qty += e.net_qty

            if e.net_qty is not None:
                if e.net_qty > 0 and e.branch_display_name not in agg.buying_branches:
                    agg.buying_branches.append(e.branch_display_name)
                elif e.net_qty < 0 and e.branch_display_name not in agg.selling_branches:
                    agg.selling_branches.append(e.branch_display_name)

        for agg in agg_map.values():
            total_events = len(agg.events)
            if total_events > 0:
                agg.lots_coverage_ratio = Decimal(agg.usable_event_count) / Decimal(total_events)
            else:
                agg.lots_coverage_ratio = Decimal("1")
            agg.lots_available = agg.usable_event_count > 0
            agg.has_estimated_lots = agg.estimated_event_count > 0

        # 轉換為信號
        aggregations = list(agg_map.values())
        signals = self.signal_engine.generate_signals(aggregations)

        # 計算不論過濾週期、所有歷史事件的每日淨量作為近期 5 筆交易紀錄
        stock_all_daily_net: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for e in events:
            if e.net_qty is not None:
                stock_all_daily_net[e.stock_code][e.date] += e.net_qty

        for s in signals:
            daily_map = stock_all_daily_net[s.stock_code]
            sorted_dates = sorted(daily_map.keys())
            last_5_dates = sorted_dates[-5:]
            s.sparkline_data = [float(daily_map[d]) for d in last_5_dates]
            s.sparkline_details = [(d, daily_map[d]) for d in last_5_dates]

        # 過濾掉沒有訊號的個股。偏多股票要求主力分數大於零；偏空股票要求強度等級小於零 (淨量小於零)
        filtered_signals = [
            s for s in signals
            if (s.smart_money_score > 0 and s.aggregation.total_net_qty > 0) or (s.intensity_level < 0)
        ]
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
            agg.events.append(e)

            if e.lots_quality == "observed":
                agg.observed_event_count += 1
                agg.usable_event_count += 1
            elif e.lots_quality == "estimated":
                agg.estimated_event_count += 1
                agg.usable_event_count += 1
            else:
                agg.unavailable_event_count += 1

            if e.buy_qty is not None:
                agg.total_buy_qty += e.buy_qty
            if e.sell_qty is not None:
                agg.total_sell_qty += e.sell_qty
            if e.net_qty is not None:
                agg.total_net_qty += e.net_qty

        for agg in agg_map.values():
            total_events = len(agg.events)
            if total_events > 0:
                agg.lots_coverage_ratio = Decimal(agg.usable_event_count) / Decimal(total_events)
            else:
                agg.lots_coverage_ratio = Decimal("1")
            agg.lots_available = agg.usable_event_count > 0
            agg.has_estimated_lots = agg.estimated_event_count > 0

        # 計算不論過濾週期、所有歷史事件的每日淨量作為近期 5 筆交易紀錄
        branch_stock_all_daily_net: Dict[tuple, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for e in events:
            if e.net_qty is not None:
                branch_stock_all_daily_net[(e.branch_system_key, e.stock_code)][e.date] += e.net_qty

        for key, agg in agg_map.items():
            daily_map = branch_stock_all_daily_net[key]
            sorted_dates = sorted(daily_map.keys())
            last_5_dates = sorted_dates[-5:]
            agg.sparkline_data = [float(daily_map[d]) for d in last_5_dates]
            agg.sparkline_details = [(d, daily_map[d]) for d in last_5_dates]

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
        根據信號計算整體市場的主力流向摘要 (統計全部多空個股與熱度)
        """
        # 重新獲取全部信號 (不進行淨量大於零之過濾)，以獲得正確的多空總家數與市場熱度
        events = self._load_data()
        filtered_events = self._filter_events_by_period(events, period)

        agg_map: Dict[str, StockFlowAggregation] = {}
        for e in filtered_events:
            if e.stock_code not in agg_map:
                agg_map[e.stock_code] = StockFlowAggregation(
                    stock_code=e.stock_code,
                    stock_name=e.stock_name
                )
            agg = agg_map[e.stock_code]
            agg.events.append(e)

            if e.lots_quality == "observed":
                agg.observed_event_count += 1
                agg.usable_event_count += 1
            elif e.lots_quality == "estimated":
                agg.estimated_event_count += 1
                agg.usable_event_count += 1
            else:
                agg.unavailable_event_count += 1

            if e.buy_qty is not None:
                agg.total_buy_qty += e.buy_qty
            if e.sell_qty is not None:
                agg.total_sell_qty += e.sell_qty
            if e.net_qty is not None:
                agg.total_net_qty += e.net_qty

        for agg in agg_map.values():
            total_events = len(agg.events)
            if total_events > 0:
                agg.lots_coverage_ratio = Decimal(agg.usable_event_count) / Decimal(total_events)
            else:
                agg.lots_coverage_ratio = Decimal("1")
            agg.lots_available = agg.usable_event_count > 0
            agg.has_estimated_lots = agg.estimated_event_count > 0

        aggregations = list(agg_map.values())
        all_signals = self.signal_engine.generate_signals(aggregations)

        summary = SmartMoneySummaryDTO()

        # 統計多空個股數量與異常警示數
        for s in all_signals:
            net_qty = s.aggregation.total_net_qty
            if net_qty > 0:
                summary.bullish_stock_count += 1
                # 偏多異常警示：主力分數高 (>= 80) 且大額淨買進 (>= 500張) ➔ 指標型重倉佈局
                if s.smart_money_score >= 80 and net_qty >= 500:
                    summary.abnormal_signal_count += 1
            elif net_qty < 0:
                summary.bearish_stock_count += 1
                # 偏空異常警示：大額淨賣出 (<= -500張) ➔ 指標型出貨倒貨
                if net_qty <= -500:
                    summary.abnormal_signal_count += 1

        # 計算市場熱度 (偏多個股佔多空個股比例)
        total_stocks = summary.bullish_stock_count + summary.bearish_stock_count
        if total_stocks > 0:
            bull_ratio = summary.bullish_stock_count / total_stocks
            summary.market_heat_score = bull_ratio * 100.0

        if summary.market_heat_score > 60:
            summary.market_regime = "Bullish Flow"
        elif summary.market_heat_score < 40:
            summary.market_regime = "Bearish Flow"
        else:
            summary.market_regime = "Neutral"

        return summary
