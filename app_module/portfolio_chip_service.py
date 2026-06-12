"""Portfolio Chip Service
負責持倉個股的券商分點籌碼分析、風險評估與指標計算。
"""

import logging
from typing import Any, Dict, List, Optional
import pandas as pd
from decimal import Decimal

from data_module.config import TWStockConfig
from app_module.broker_flow_service import BrokerFlowService


class PortfolioChipService:
    """提供持倉個股的籌碼分析與風險判定服務"""

    def __init__(self, config: TWStockConfig, broker_flow_service: Optional[BrokerFlowService] = None):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.broker_flow_service = broker_flow_service or BrokerFlowService(config)
        self._registry_cache: Dict[str, str] = {}
        self._load_registry_mapping()

    def _load_registry_mapping(self):
        """讀取分點註冊表，建立系統 Key 到顯示名稱的對照"""
        registry_file = self.config.broker_branch_registry_file
        if not registry_file.exists():
            return
        try:
            dtype_dict = {
                'branch_system_key': str,
                'branch_display_name': str
            }
            df = pd.read_csv(registry_file, encoding='utf-8-sig', dtype=dtype_dict)
            for _, row in df.iterrows():
                key = str(row.get('branch_system_key', '')).strip()
                name = str(row.get('branch_display_name', '')).strip()
                if key and name:
                    self._registry_cache[key] = name
        except Exception as e:
            self.logger.warning("載入分點註冊表失敗: %s", e)

    def get_display_name(self, system_key: str) -> str:
        """獲取分點的顯示名稱"""
        return self._registry_cache.get(system_key, system_key)

    def get_stock_chip_summary(self, stock_code: str, period_days: int = 5) -> Dict[str, Any]:
        """
        獲取特定個股近 N 天的籌碼統計數據 (SQLite 優先，CSV 降級)

        Args:
            stock_code: 證券代號
            period_days: 計算週期天數 (如 5 日、20 日)

        Returns:
            Dict 包含累計買賣超、集中度、分點明細與風險警示
        """
        stock_code = str(stock_code).strip().zfill(4)

        if getattr(self.config, 'use_sqlite', False):
            return self._get_chip_summary_from_sqlite(stock_code, period_days)
        else:
            return self._get_chip_summary_from_csv(stock_code, period_days)

    def _get_chip_summary_from_sqlite(self, stock_code: str, period_days: int) -> Dict[str, Any]:
        """從 SQLite 載入籌碼數據"""
        from data_module.db_manager import DBManager
        db = DBManager(self.config)

        try:
            # 1. 取得最近的交易日期列表
            dates_df = db.execute_query(
                "SELECT DISTINCT 日期 FROM broker_flows WHERE 證券代號 = ? ORDER BY 日期 DESC LIMIT ?;",
                (stock_code, period_days)
            )
            if dates_df.empty:
                return self._empty_summary(stock_code, period_days)

            dates = dates_df['日期'].dropna().tolist()
            placeholders = ",".join("?" for _ in dates)

            # 2. 取得明細
            query = f"""
                SELECT 日期, 分點名稱, 買進股數, 賣出股數, 買賣超股數,
                       買進金額千元, 賣出金額千元, 買賣超金額千元
                FROM broker_flows
                WHERE 證券代號 = ? AND 日期 IN ({placeholders})
                ORDER BY 日期 DESC;
            """
            params = (stock_code, *dates)
            flows_df = db.execute_query(query, params)
            return self._aggregate_flow_dataframe(flows_df, stock_code, period_days, dates)

        except Exception as e:
            self.logger.error("從 SQLite 獲取個股 %s 籌碼數據失敗: %s", stock_code, e)
            # 嘗試降級到 CSV
            return self._get_chip_summary_from_csv(stock_code, period_days)

    def _get_chip_summary_from_csv(self, stock_code: str, period_days: int) -> Dict[str, Any]:
        """從 CSV 降級載入籌碼數據"""
        try:
            events = self.broker_flow_service._load_data()
            # 過濾此個股事件
            stock_events = [e for e in events if e.stock_code == stock_code]
            if not stock_events:
                return self._empty_summary(stock_code, period_days)

            # 找出最近 N 個交易日
            unique_dates = sorted(list({e.date for e in stock_events}), reverse=True)[:period_days]
            filtered_events = [e for e in stock_events if e.date in unique_dates]

            if not filtered_events:
                return self._empty_summary(stock_code, period_days)

            # 轉換為 DataFrame 進行聚合
            data = []
            for e in filtered_events:
                buy_vol = e.buy_qty * 1000 if e.buy_qty is not None else None
                sell_vol = e.sell_qty * 1000 if e.sell_qty is not None else None
                net_vol = e.net_qty * 1000 if e.net_qty is not None else None
                data.append({
                    '日期': e.date,
                    '分點名稱': e.branch_system_key,
                    '買進股數': buy_vol,
                    '賣出股數': sell_vol,
                    '買賣超股數': net_vol,
                    '買進金額千元': e.buy_amount_k_twd,
                    '賣出金額千元': e.sell_amount_k_twd,
                    '買賣超金額千元': e.net_amount_k_twd,
                    'lots_available': e.lots_available,
                    'has_estimated_lots': e.has_estimated_lots
                })
            df = pd.DataFrame(data)
            return self._aggregate_flow_dataframe(df, stock_code, period_days, unique_dates)

        except Exception as e:
            self.logger.error("從 CSV 獲取個股 %s 籌碼數據失敗: %s", stock_code, e)
            return self._empty_summary(stock_code, period_days)

    def _empty_summary(self, stock_code: str, period_days: int) -> Dict[str, Any]:
        return {
            'stock_code': stock_code,
            'period_days': period_days,
            'accumulated_buy': 0,
            'accumulated_sell': 0,
            'accumulated_net': 0,
            'concentration': 0.0,
            'consecutive_days': 0,
            'branch_details': [],
            'risk_level': 'neutral',
            'risk_reasons': ['無主力分點交易數據']
        }

    def _aggregate_flow_dataframe(
        self,
        df: pd.DataFrame,
        stock_code: str,
        period_days: int,
        dates: List[str]
    ) -> Dict[str, Any]:
        """聚合籌碼 DataFrame，計算集中度、連續天數與評估風險"""
        if df.empty:
            return self._empty_summary(stock_code, period_days)

        # 取得日期價格 Map
        price_map = {}
        if getattr(self.config, 'use_sqlite', False) and dates:
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)
                placeholders = ",".join("?" for _ in dates)
                query = f"SELECT 日期, 收盤價 FROM daily_prices WHERE 證券代號 = ? AND 日期 IN ({placeholders});"
                price_df = db.execute_query(query, (stock_code, *dates))
                for _, row in price_df.iterrows():
                    d_val = str(row['日期']).strip()
                    try:
                        price_map[d_val] = float(row['收盤價'])
                    except:
                        continue
            except Exception as e:
                self.logger.warning("查詢收盤價對照失敗: %s", e)

        from decimal import Decimal, ROUND_HALF_UP

        has_estimated_lots = False
        lots_available = True

        resolved_rows = []
        for _, row in df.iterrows():
            d_val = str(row['日期']).strip()
            db_date = d_val.replace('-', '').replace('/', '')

            row_lots_available = row.get('lots_available', True)
            row_has_estimated_lots = row.get('has_estimated_lots', False)

            buy_vol = row['買進股數']
            sell_vol = row['賣出股數']
            net_vol = row['買賣超股數']

            # 如果是 SQLite 缺失股數 (NULL)
            is_missing = (
                pd.isna(buy_vol) or buy_vol is None or
                pd.isna(sell_vol) or sell_vol is None or
                pd.isna(net_vol) or net_vol is None
            )

            if is_missing and '買進金額千元' in row:
                buy_amt = row.get('買進金額千元', 0)
                sell_amt = row.get('賣出金額千元', 0)
                buy_amt = 0 if pd.isna(buy_amt) or buy_amt is None else int(buy_amt)
                sell_amt = 0 if pd.isna(sell_amt) or sell_amt is None else int(sell_amt)

                close_price = price_map.get(db_date)
                if close_price is not None and close_price > 0:
                    try:
                        d_buy_amt = Decimal(str(buy_amt)) * Decimal('1000')
                        d_sell_amt = Decimal(str(sell_amt)) * Decimal('1000')
                        d_close = Decimal(str(close_price))

                        buy_vol = int((d_buy_amt / d_close).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                        sell_vol = int((d_sell_amt / d_close).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                        net_vol = buy_vol - sell_vol

                        row_has_estimated_lots = True
                        row_lots_available = True
                    except Exception as e:
                        self.logger.warning(f"折算股數失敗 for {stock_code} on {d_val}: {e}")
                        buy_vol = 0
                        sell_vol = 0
                        net_vol = 0
                        row_lots_available = False
                        row_has_estimated_lots = False
                else:
                    buy_vol = 0
                    sell_vol = 0
                    net_vol = 0
                    row_lots_available = False
                    row_has_estimated_lots = False
            else:
                buy_vol = 0 if pd.isna(buy_vol) or buy_vol is None else int(buy_vol)
                sell_vol = 0 if pd.isna(sell_vol) or sell_vol is None else int(sell_vol)
                net_vol = 0 if pd.isna(net_vol) or net_vol is None else int(net_vol)

            if not row_lots_available:
                lots_available = False
            if row_has_estimated_lots:
                has_estimated_lots = True

            resolved_rows.append({
                '分點名稱': row['分點名稱'],
                '買進股數': buy_vol,
                '賣出股數': sell_vol,
                '買賣超股數': net_vol,
                '日期': d_val
            })

        df_resolved = pd.DataFrame(resolved_rows)

        # 1. 計算總額
        total_buy = int(df_resolved['買進股數'].sum())
        total_sell = int(df_resolved['賣出股數'].sum())
        total_net = int(df_resolved['買賣超股數'].sum())

        # 集中度計算 (用 Decimal 避免浮點精度誤差)
        concentration = 0.0
        total_volume = total_buy + total_sell
        if total_volume > 0:
            concentration = float(Decimal(str(total_net)) / Decimal(str(total_volume)))

        # 2. 按分點名稱聚合明細
        branch_agg = df_resolved.groupby('分點名稱').agg({
            '買進股數': 'sum',
            '賣出股數': 'sum',
            '買賣超股數': 'sum'
        }).reset_index()

        branch_details: List[Dict[str, Any]] = []
        for _, row in branch_agg.iterrows():
            sys_key = str(row['分點名稱'])
            branch_details.append({
                'system_key': sys_key,
                'display_name': self.get_display_name(sys_key),
                'buy_qty': int(row['買進股數']),
                'sell_qty': int(row['賣出股數']),
                'net_qty': int(row['買賣超股數'])
            })

        # 排序：淨買賣超降序
        branch_details.sort(key=lambda x: int(x['net_qty']), reverse=True)

        # 3. 計算連續買賣超天數
        daily_net = df_resolved.groupby('日期')['買賣超股數'].sum().reset_index()
        daily_net = daily_net.sort_values(by='日期', ascending=False) # 由新到舊

        consecutive_days = 0
        if not daily_net.empty:
            latest_net = int(daily_net.iloc[0]['買賣超股數'])
            if latest_net != 0:
                is_positive = latest_net > 0
                for _, row in daily_net.iterrows():
                    net = int(row['買賣超股數'])
                    if (net > 0) == is_positive and net != 0:
                        consecutive_days += 1 if is_positive else -1
                    else:
                        break

        # 4. 判定風險評級與警示原因
        risk_level = 'neutral'
        risk_reasons = []

        if has_estimated_lots:
            risk_reasons.append("⚠️ 此期間包含歷史金額與股價折算之估計股數資料。")

        # 規則 A: 連續賣出警示
        if consecutive_days <= -3:
            risk_level = 'bearish'
            risk_reasons.append(f"主力分點連續 {abs(consecutive_days)} 日淨出貨")
        elif consecutive_days >= 3:
            risk_level = 'bullish'
            risk_reasons.append(f"主力分點連續 {consecutive_days} 日淨吸籌")

        # 規則 B: 大額拋售/吸籌警示 (若包含估算資料，警示門檻提高一倍至 1,000,000 股，即 1000 張)
        large_threshold = 1000000 if has_estimated_lots else 500000
        if total_net <= -large_threshold:
            risk_level = 'bearish'
            risk_reasons.append(f"近 {len(dates)} 日主力累計大額拋售達 {abs(total_net) / 1000:,.1f} 張")
        elif total_net >= large_threshold:
            # 若無連續賣出警示，則可維持偏多
            if risk_level != 'bearish':
                risk_level = 'bullish'
            risk_reasons.append(f"近 {len(dates)} 日主力累計大額買進達 {total_net / 1000:,.1f} 張")

        # 規則 C: 籌碼渙散 (累計淨買賣超小，無主力買盤支撐)
        if risk_level == 'neutral':
            if len(dates) >= 5 and abs(total_net) < 50000: # 50張以內
                risk_reasons.append("主力分點近幾日交易清淡，無明確方向")
            else:
                risk_reasons.append("主力分點多空分歧或買賣超幅度溫和")

        return {
            'stock_code': stock_code,
            'period_days': period_days,
            'accumulated_buy': total_buy,
            'accumulated_sell': total_sell,
            'accumulated_net': total_net,
            'concentration': concentration,
            'consecutive_days': consecutive_days,
            'branch_details': branch_details,
            'risk_level': risk_level,
            'risk_reasons': risk_reasons
        }
