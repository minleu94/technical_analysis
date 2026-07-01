"""
強勢股/產業篩選模組
用於識別本周/本日強勢股和產業
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import logging
import warnings

# 抑制 pandas 和 numpy 的 RuntimeWarning（這些警告通常是正常的，會自動處理）
warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*invalid value encountered.*')
warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*divide by zero.*')

# 設置 logger（避免編碼問題）
logger = logging.getLogger(__name__)

class StockScreener:
    """強勢股篩選器"""
    
    def __init__(self, config, industry_mapper=None, volume_lookback=20, min_price=5.0, min_liquidity=None):
        """初始化篩選器
        
        Args:
            config: TWStockConfig 實例
            industry_mapper: IndustryMapper 實例（可選，用於獲取產業信息）
            volume_lookback: 量能均線用幾天（預設 20）
            min_price: 過濾低價股（預設 5 元）
            min_liquidity: 最小成交金額門檻（可選）
        """
        self.config = config
        self.industry_mapper = industry_mapper
        self.volume_lookback = volume_lookback
        self.min_price = min_price
        self.min_liquidity = min_liquidity

    def _sqlite_readonly_connection(self):
        db_file = Path(getattr(self.config, 'db_file', ''))
        if not db_file.exists():
            return None

        conn = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _sqlite_recent_date_values(self, conn, table_name, date_column, limit):
        sql = f"""
            SELECT DISTINCT {date_column} AS date_value
            FROM {table_name}
            WHERE {date_column} IS NOT NULL
            ORDER BY {date_column} DESC
            LIMIT ?
        """
        rows = conn.execute(sql, (limit,)).fetchall()
        return [row[0] for row in rows if row and row[0]]

    def _load_sqlite_recent_stock_prices(self, period):
        if not getattr(self.config, 'use_sqlite', False):
            return None

        lookback_limit = max(self.volume_lookback + 8, 32 if period == 'day' else 48)
        try:
            conn = self._sqlite_readonly_connection()
            if conn is None:
                return None

            with conn:
                date_values = self._sqlite_recent_date_values(
                    conn, "daily_prices", "日期", lookback_limit
                )
                if not date_values:
                    return None

                placeholders = ",".join("?" for _ in date_values)
                sql = f"""
                    SELECT
                        日期,
                        證券代號,
                        證券名稱,
                        收盤價,
                        開盤價,
                        最高價,
                        最低價,
                        成交股數,
                        成交金額
                    FROM daily_prices
                    WHERE 日期 IN ({placeholders})
                    ORDER BY 日期 ASC, 證券代號 ASC
                """
                return pd.read_sql_query(sql, conn, params=date_values)
        except Exception as sql_err:
            logger.warning(f"SQLite 快速載入強弱勢個股資料失敗: {sql_err}，將降級為既有路徑")
            return None

    def _load_sqlite_recent_industry_indices(self, period):
        if not getattr(self.config, 'use_sqlite', False):
            return None

        lookback_limit = 45 if period == 'day' else 90
        try:
            conn = self._sqlite_readonly_connection()
            if conn is None:
                return None

            with conn:
                date_values = self._sqlite_recent_date_values(
                    conn, "industry_indices", "日期", lookback_limit
                )
                if not date_values:
                    return None

                placeholders = ",".join("?" for _ in date_values)
                sql = f"""
                    SELECT 日期, 指數名稱, 收盤指數
                    FROM industry_indices
                    WHERE 日期 IN ({placeholders})
                    ORDER BY 日期 ASC, 指數名稱 ASC
                """
                return pd.read_sql_query(sql, conn, params=date_values)
        except Exception as sql_err:
            logger.warning(f"SQLite 快速載入強弱勢產業資料失敗: {sql_err}，將降級為 CSV")
            return None

    def _try_get_sqlite_stock_screen(self, period, top_n, min_volume, direction):
        df = self._load_sqlite_recent_stock_prices(period)
        if df is None:
            return None

        result = self._build_stock_screen_from_frame(df, period, top_n, min_volume, direction)
        logger.info(
            "[StockScreener] SQLite 快速路徑完成: direction=%s, period=%s, rows=%s",
            direction,
            period,
            len(df),
        )
        return result

    def _build_stock_screen_from_frame(self, df, period, top_n, min_volume, direction):
        if len(df) == 0 or '日期' not in df.columns or '證券代號' not in df.columns:
            return pd.DataFrame(), 0

        df = df.copy()
        df['日期'] = pd.to_datetime(
            df['日期'].astype(str).str.replace("-", "", regex=False).str.replace("/", "", regex=False),
            format='%Y%m%d',
            errors='coerce',
        )
        df = df[df['日期'].notna()]
        if len(df) == 0:
            return pd.DataFrame(), 0

        df['證券代號'] = df['證券代號'].astype(str).str.strip()
        numeric_cols = ['收盤價', '開盤價', '最高價', '最低價', '成交股數', '成交金額']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        all_stocks_data = []
        processed_count = 0
        skipped_count = 0

        for stock_code, stock_df in df.groupby('證券代號'):
            try:
                if not (len(stock_code) == 4 and stock_code.isdigit()):
                    continue

                stock_df = stock_df.sort_values('日期')
                if period == 'day':
                    if len(stock_df) < 2:
                        skipped_count += 1
                        continue
                    compare_row = stock_df.iloc[-2]
                else:
                    if len(stock_df) >= 6:
                        compare_row = stock_df.iloc[-6]
                    elif len(stock_df) >= 3:
                        compare_row = stock_df.iloc[-3]
                    else:
                        skipped_count += 1
                        continue

                latest_row = stock_df.iloc[-1]
                latest_price = latest_row.get('收盤價')
                compare_price = compare_row.get('收盤價')
                if pd.isna(latest_price) or pd.isna(compare_price) or compare_price == 0:
                    skipped_count += 1
                    continue

                if latest_price < self.min_price:
                    skipped_count += 1
                    continue

                volume = latest_row.get('成交股數', 0)
                if min_volume and volume < min_volume:
                    continue

                if self.min_liquidity is not None:
                    turnover = latest_row.get('成交金額', 0)
                    if pd.isna(turnover) or turnover < self.min_liquidity:
                        skipped_count += 1
                        continue

                price_change = (latest_price - compare_price) / compare_price * 100
                volume_change = 0
                volume_ratio = 1.0
                if '成交股數' in stock_df.columns:
                    latest_volume = latest_row.get('成交股數', 0)
                    if len(stock_df) >= 21:
                        volume_ma = stock_df['成交股數'].iloc[-21:-1].mean()
                    elif len(stock_df) >= 6:
                        volume_ma = stock_df['成交股數'].iloc[-6:-1].mean()
                    elif len(stock_df) >= 2:
                        volume_ma = stock_df['成交股數'].iloc[:-1].mean()
                    else:
                        volume_ma = 0

                    if volume_ma > 0:
                        volume_ratio = latest_volume / volume_ma
                        with np.errstate(divide='ignore', invalid='ignore'):
                            volume_change = np.log1p(max(0, volume_ratio - 1)) * 100

                vol_factor = np.log1p(max(0, volume_ratio - 1))
                score = price_change * 0.6 + vol_factor * 100 * 0.4
                stock_name = latest_row.get('證券名稱', stock_code)
                if pd.isna(stock_name):
                    stock_name = stock_code

                if direction == "strong":
                    reasons = self._generate_strong_stock_reasons(
                        stock_df, latest_row, price_change, volume_ratio, period, stock_code
                    )
                else:
                    reasons = self._generate_weak_stock_reasons(
                        stock_df, latest_row, price_change, volume_ratio, period, stock_code
                    )

                all_stocks_data.append({
                    '證券代號': stock_code,
                    '證券名稱': stock_name,
                    '收盤價': latest_price,
                    '漲幅%': price_change,
                    '成交量變化率%': volume_change,
                    '評分': score,
                    '推薦理由': reasons
                })
                processed_count += 1
            except Exception as err:
                skipped_count += 1
                logger.debug(f"[StockScreener] SQLite 快速路徑跳過 {stock_code}: {err}")

        logger.info(
            "[StockScreener] SQLite 快速路徑處理完成: 成功=%s, 跳過=%s",
            processed_count,
            skipped_count,
        )
        return self._format_stock_screen_result(all_stocks_data, top_n, direction)

    def _format_stock_screen_result(self, all_stocks_data, top_n, direction):
        if len(all_stocks_data) == 0:
            return pd.DataFrame(), 0

        result_df = pd.DataFrame(all_stocks_data)
        if len(result_df) > 1:
            price_mean = result_df['漲幅%'].mean()
            price_std = result_df['漲幅%'].std()
            vol_mean = result_df['成交量變化率%'].mean()
            vol_std = result_df['成交量變化率%'].std()

            price_z = (
                (result_df['漲幅%'] - price_mean) / price_std
                if price_std > 0
                else pd.Series(0, index=result_df.index)
            )
            vol_z = (
                (result_df['成交量變化率%'] - vol_mean) / vol_std
                if vol_std > 0
                else pd.Series(0, index=result_df.index)
            )
            result_df['評分'] = price_z * 0.6 + vol_z * 0.4

        total_stocks = len(result_df)
        if total_stocks > 1:
            score_values = result_df['評分'].copy()
            ascending = direction == "weak"
            sorted_scores = score_values.sort_values(ascending=ascending).values
            percentile_labels = []
            for score in score_values:
                if direction == "weak":
                    percentile = (sorted_scores <= score).sum() / total_stocks * 100
                    prefix = "Bottom"
                else:
                    better_or_equal = (sorted_scores >= score).sum()
                    percentile = (total_stocks - better_or_equal + 1) / total_stocks * 100
                    prefix = "Top"

                if percentile <= 1.0:
                    percentile_labels.append(f"{prefix} 1%")
                elif percentile <= 3.0:
                    percentile_labels.append(f"{prefix} 3%")
                elif percentile <= 5.0:
                    percentile_labels.append(f"{prefix} 5%")
                elif percentile <= 10.0:
                    percentile_labels.append(f"{prefix} 10%")
                elif percentile <= 20.0:
                    percentile_labels.append(f"{prefix} 20%")
                elif percentile <= 50.0:
                    percentile_labels.append(f"{prefix} 50%")
                else:
                    percentile_labels.append(f"{prefix} {int(percentile)}%")
            result_df['評分'] = percentile_labels
            result_df = result_df.iloc[score_values.sort_values(ascending=ascending).index].copy()
        else:
            result_df['評分'] = "Bottom 1%" if direction == "weak" else "Top 1%"

        result_df = result_df.head(top_n).copy()
        result_df['排名'] = range(1, len(result_df) + 1)
        return (
            result_df[['排名', '證券代號', '證券名稱', '收盤價', '漲幅%', '成交量變化率%', '評分', '推薦理由']],
            total_stocks,
        )

    def _try_get_sqlite_industry_screen(self, period, top_n, direction):
        df = self._load_sqlite_recent_industry_indices(period)
        if df is None:
            return None

        result = self._build_industry_screen_from_frame(df, top_n, direction)
        logger.info(
            "[StockScreener] SQLite 快速路徑完成: industry_direction=%s, period=%s, rows=%s",
            direction,
            period,
            len(df),
        )
        return result

    def _build_industry_screen_from_frame(self, df, top_n, direction):
        if len(df) == 0 or '日期' not in df.columns:
            return pd.DataFrame()

        df = df.copy()
        df['日期'] = pd.to_datetime(
            df['日期'].astype(str).str.replace("-", "", regex=False).str.replace("/", "", regex=False),
            format='%Y%m%d',
            errors='coerce',
        )
        df['收盤指數'] = pd.to_numeric(df.get('收盤指數'), errors='coerce')
        df = df[df['日期'].notna()]
        if len(df) == 0:
            return pd.DataFrame()

        latest_date = df['日期'].max()
        oldest_date = df['日期'].min()
        latest_df = df[df['日期'] == latest_date].copy()
        oldest_df = df[df['日期'] == oldest_date].copy()
        merged = latest_df.merge(
            oldest_df[['指數名稱', '收盤指數']],
            on='指數名稱',
            suffixes=('_latest', '_oldest'),
            how='left'
        )
        merged['漲幅%'] = (
            (merged['收盤指數_latest'] - merged['收盤指數_oldest']) /
            merged['收盤指數_oldest'] * 100
        )
        merged = merged.dropna(subset=['收盤指數_oldest', '收盤指數_latest'])
        merged = merged[merged['收盤指數_oldest'] != 0]

        if direction == "weak":
            result = merged.nsmallest(top_n, '漲幅%')[
                ['指數名稱', '收盤指數_latest', '漲幅%']
            ].copy()
        else:
            result = merged.nlargest(top_n, '漲幅%')[
                ['指數名稱', '收盤指數_latest', '漲幅%']
            ].copy()

        result.columns = ['指數名稱', '收盤指數', '漲幅%']
        result['排名'] = range(1, len(result) + 1)
        return result[['排名', '指數名稱', '收盤指數', '漲幅%']]
    
    def get_strong_stocks(self, period='day', top_n=20, min_volume=None):
        """獲取強勢股
        
        從 technical_analysis 目錄讀取所有個股技術指標文件
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名
            min_volume: 最小成交量（可選）
            
        Returns:
            tuple: (DataFrame, universe_count)
                - DataFrame: 強勢股列表，包含評分和排名
                - universe_count: Universe 股票數量（有效數據的股票數）
        """
        sqlite_result = self._try_get_sqlite_stock_screen(period, top_n, min_volume, "strong")
        if sqlite_result is not None:
            return sqlite_result

        today = datetime.now()
        if period == 'day':
            days_back = 30
        else:  # week
            days_back = 60
        start_date = today - timedelta(days=days_back)
        
        # 優先嘗試從 SQLite 資料庫載入
        grouped_list = []
        db_success = False
        
        if getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)
                max_date_df = db.execute_query("SELECT MAX(日期) as max_date FROM daily_prices;")
                if not max_date_df.empty and max_date_df['max_date'].iloc[0]:
                    max_date_str = str(max_date_df['max_date'].iloc[0])
                    latest_date = datetime.strptime(max_date_str, '%Y%m%d')
                    
                    if period == 'day':
                        days_back_db = 45
                    else:
                        days_back_db = 90
                    
                    start_date_db = latest_date - timedelta(days=days_back_db)
                    start_date_str = start_date_db.strftime('%Y%m%d')
                    
                    # 更新 start_date 給後續 python 過濾使用
                    start_date = start_date_db
                    
                    # 執行 JOIN 查詢，因為 technical_indicators 不一定有全部股票，使用 LEFT JOIN
                    sql = """
                        SELECT p.*, t.*
                        FROM daily_prices p
                        LEFT JOIN technical_indicators t ON p.證券代號 = t.證券代號 AND p.日期 = t.日期
                        WHERE p.日期 >= ?
                        ORDER BY p.日期 ASC;
                    """
                    sql_df = db.execute_query(sql, params=(start_date_str,))
                    if not sql_df.empty:
                        # 去除因 * 導致的重複欄位（如 日期, 證券代號）
                        sql_df = sql_df.loc[:, ~sql_df.columns.duplicated()]
                        
                        # 轉換日期格式
                        sql_df['日期'] = pd.to_datetime(sql_df['日期'].astype(str), format='%Y%m%d', errors='coerce')
                        sql_df = sql_df[sql_df['日期'].notna()]
                        
                        sql_df['證券代號'] = sql_df['證券代號'].astype(str).str.strip()
                        
                        # 轉換型態
                        numeric_cols = ['收盤價', '開盤價', '最高價', '最低價', '成交股數', '成交金額']
                        for col in numeric_cols:
                            if col in sql_df.columns:
                                sql_df[col] = pd.to_numeric(sql_df[col], errors='coerce')
                        
                        # 按證券代號分組
                        for stock_code, g_df in sql_df.groupby('證券代號'):
                            if len(stock_code) == 4 and stock_code.isdigit():
                                grouped_list.append((stock_code, g_df.sort_values('日期')))
                                
                        db_success = True
                        logger.info(f"成功從 SQLite 載入 {len(grouped_list)} 支股票數據進行強勢股篩選")
            except Exception as db_err:
                logger.warning(f"從 SQLite 載入篩選數據失敗: {db_err}，將降級為 CSV 掃描")
                
        data_source = []
        indicator_files = []
        if db_success:
            data_source = grouped_list
        else:
            # 掃描 technical_analysis 目錄下的所有 *_indicators.csv 文件
            technical_dir = self.config.technical_dir
            if not technical_dir.exists():
                logger.warning(f"錯誤：技術指標目錄不存在: {technical_dir}")
                return pd.DataFrame()
            
            # 查找所有指標文件
            indicator_files = list(technical_dir.glob("*_indicators.csv"))
            if len(indicator_files) == 0:
                logger.warning(f"錯誤：在 {technical_dir} 中找不到任何指標文件")
                return pd.DataFrame()
                
            for indicator_file in indicator_files:
                stock_code = indicator_file.stem.replace('_indicators', '')
                data_source.append((stock_code, indicator_file))
                
            logger.info(f"[StockScreener] period={period}, days_back={days_back}, start_date={start_date.strftime('%Y-%m-%d')}")
            logger.info(f"[StockScreener] 找到 {len(indicator_files)} 個指標文件")
        
        all_stocks_data = []
        skipped_count = 0
        processed_count = 0
        
        # 讀取每個股票的指標數據
        for stock_code, data_item in data_source:
            try:
                # 讀取數據
                if isinstance(data_item, pd.DataFrame):
                    df = data_item.copy()
                else:
                    df = pd.read_csv(data_item, encoding='utf-8-sig')
                
                # 轉換日期格式（支持多種格式）
                if '日期' in df.columns:
                    original_count = len(df)
                    original_dates = df['日期'].head(3).tolist() if len(df) > 0 else []
                    
                    # 嘗試多種日期格式
                    if df['日期'].dtype == 'object':
                        # 先嘗試 YYYYMMDD 格式（8位數字）
                        sample_date = str(df['日期'].iloc[0]).strip() if len(df) > 0 else ''
                        
                        # 檢查是否為純數字（可能是 YYYYMMDD 格式）
                        if sample_date.isdigit() and len(sample_date) == 8:
                            # 強制使用 YYYYMMDD 格式解析
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y%m%d')
                        elif '/' in sample_date:
                            # 嘗試 YYYY/MM/DD 格式
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y/%m/%d')
                        elif '-' in sample_date:
                            # 嘗試 YYYY-MM-DD 格式
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y-%m-%d')
                        else:
                            # 自動解析其他格式（但先轉為字符串避免數字解析錯誤）
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce')
                    elif pd.api.types.is_integer_dtype(df['日期']):
                        # 如果是整數類型，可能是 YYYYMMDD 格式的數字
                        # 先轉為字符串，再解析
                        df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y%m%d')
                    else:
                        # 其他類型，直接解析
                        df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
                    
                    # 檢查日期解析結果
                    na_count = df['日期'].isna().sum()
                    df = df[df['日期'].notna()]
                    
                    if len(df) == 0:
                        skipped_count += 1
                        if skipped_count <= 3:
                            logger.debug(f"[StockScreener] 跳過 {stock_code}: 日期解析失敗 (原始: {original_count}筆, 無效日期: {na_count}筆, 原始日期樣本: {original_dates})")
                        continue
                    
                    # 先排序，再過濾日期範圍
                    df = df.sort_values('日期')
                    before_filter_count = len(df)
                    min_date = df['日期'].min()
                    max_date = df['日期'].max()
                    
                    # 只保留日期範圍內的數據
                    df = df[df['日期'] >= pd.Timestamp(start_date)]
                    
                    if len(df) == 0:
                        skipped_count += 1
                        if skipped_count <= 3:  # 只記錄前3個被跳過的，避免輸出太多
                            logger.debug(f"[StockScreener] 跳過 {stock_code}: 日期過濾後無數據 (原始: {original_count}筆, 過濾前: {before_filter_count}筆, 過濾後: 0筆, 數據日期範圍: {min_date}~{max_date}, 要求日期: >={start_date.strftime('%Y-%m-%d')})")
                        continue
                else:
                    continue
                
                # 獲取最新和比較日期的數據
                latest_row = df.iloc[-1]
                
                # 根據period選擇比較日期
                if period == 'day':
                    # 本日：與前一個交易日比較（倒數第二筆）
                    if len(df) < 2:
                        skipped_count += 1
                        if skipped_count <= 3:
                            logger.debug(f"[StockScreener] 跳過 {stock_code}: 數據不足2筆 (僅有{len(df)}筆)")
                        continue
                    compare_row = df.iloc[-2]
                else:  # week
                    # 近5個交易日：與5個交易日之前比較
                    # 優先使用倒數第6筆（5個交易日之前），如果數據不足則降級處理
                    if len(df) >= 6:
                        compare_row = df.iloc[-6]  # 5個交易日之前
                    elif len(df) >= 3:
                        # 降級：使用倒數第3筆（2個交易日之前）
                        compare_row = df.iloc[-3]
                        if processed_count < 3:  # 只打印前3個降級處理的
                            logger.debug(f"[StockScreener] {stock_code}: 數據不足6筆，降級使用3筆數據 (實際有{len(df)}筆)")
                    else:
                        # 數據不足，跳過
                        skipped_count += 1
                        if skipped_count <= 3:
                            logger.debug(f"[StockScreener] 跳過 {stock_code}: 數據不足3筆 (僅有{len(df)}筆)")
                        continue
                
                if compare_row is None:
                    continue
                
                # 獲取收盤價
                close_col = None
                for col in ['收盤價', 'Close', 'close']:
                    if col in latest_row.index:
                        close_col = col
                        break
                
                if close_col is None:
                    continue
                
                latest_price = latest_row[close_col]
                compare_price = compare_row[close_col]
                
                if pd.isna(latest_price) or pd.isna(compare_price) or compare_price == 0:
                    skipped_count += 1
                    if skipped_count <= 3:
                        logger.debug(f"[StockScreener] 跳過 {stock_code}: 價格數據無效 (latest={latest_price}, compare={compare_price})")
                    continue
                
                # 價格篩選
                if latest_price < self.min_price:
                    skipped_count += 1
                    continue
                
                # 計算漲幅百分比
                price_change = (latest_price - compare_price) / compare_price * 100
                
                # 計算成交量變化率（使用 volume_lookback 日均量）
                volume_change = 0
                volume_ratio = 1.0
                if '成交股數' in df.columns:
                    latest_volume = latest_row.get('成交股數', 0)
                    # 使用前 volume_lookback 日均量（不含最新日）
                    lookback_window = min(self.volume_lookback + 1, len(df))
                    if lookback_window >= 2:
                        volume_ma = df['成交股數'].iloc[-lookback_window:-1].mean()
                    else:
                        volume_ma = 0
                    
                    if volume_ma > 0:
                        volume_ratio = latest_volume / volume_ma
                        # 使用 log1p 壓縮量變（避免極端值）
                        try:
                            with np.errstate(divide='ignore', invalid='ignore'):
                                volume_change = np.log1p(max(0, volume_ratio - 1)) * 100
                        except:
                            volume_change = 0
                    else:
                        volume_change = 0
                        volume_ratio = 1.0
                
                # 成交金額篩選（如果設定）
                if self.min_liquidity is not None:
                    turnover = latest_row.get('成交金額', 0)
                    if turnover < self.min_liquidity:
                        skipped_count += 1
                        continue
                
                # 計算標準化分數（使用 z-score 標準化）
                vol_factor = np.log1p(max(0, volume_ratio - 1))
                
                # 標準化評分（改進版：使用壓縮後的量變）
                score = price_change * 0.6 + vol_factor * 100 * 0.4
                
                # 獲取證券名稱
                stock_name = latest_row.get('證券名稱', stock_code)
                if pd.isna(stock_name):
                    stock_name = stock_code
                
                # 獲取成交量
                volume = latest_row.get('成交股數', 0)
                
                # 篩選條件
                if min_volume and volume < min_volume:
                    continue
                
                # 計算20日均量（用於成交量比率計算，不含最新日）
                if '成交股數' in df.columns:
                    latest_volume = latest_row.get('成交股數', 0)
                    # 使用前20日均量（不含最新日），避免稀釋爆量
                    if len(df) >= 21:
                        volume_ma20 = df['成交股數'].iloc[-21:-1].mean()  # 前20日，不含最新
                    elif len(df) >= 6:
                        volume_ma20 = df['成交股數'].iloc[-6:-1].mean()  # 退化：前5日
                    elif len(df) >= 2:
                        volume_ma20 = df['成交股數'].iloc[:-1].mean()  # 退化：所有歷史數據
                    else:
                        volume_ma20 = 0
                    
                    if volume_ma20 > 0:
                        volume_ratio = latest_volume / volume_ma20
                    else:
                        volume_ratio = 1.0
                
                # 生成推薦理由
                reasons = self._generate_strong_stock_reasons(
                    df, latest_row, price_change, volume_ratio, period, stock_code
                )
                
                all_stocks_data.append({
                    '證券代號': stock_code,
                    '證券名稱': stock_name,
                    '收盤價': latest_price,
                    '漲幅%': price_change,
                    '成交量變化率%': volume_change,
                    '評分': score,
                    '推薦理由': reasons
                })
                processed_count += 1
                if processed_count <= 3:  # 只打印前3個成功處理的
                    logger.debug(f"[StockScreener] 成功處理 {stock_code}: 漲幅={price_change:.2f}%, 評分={score:.2f}")
                
            except Exception as e:
                # 記錄錯誤以便除錯，然後跳過
                item_name = data_item if isinstance(data_item, pd.DataFrame) else (data_item.name if hasattr(data_item, 'name') else str(data_item))
                logger.debug(f"[StockScreener] 跳過 {item_name}: {e}")
                continue
        
        total_source_count = len(grouped_list) if db_success else len(indicator_files)
        logger.info(f"[StockScreener] 處理完成: 成功={processed_count}, 跳過={skipped_count}, 總股票/文件數={total_source_count}")
        
        if len(all_stocks_data) == 0:
            logger.warning(f"[StockScreener] 警告: 沒有找到任何強勢股數據")
            return pd.DataFrame(), 0
        
        # 轉換為DataFrame
        result_df = pd.DataFrame(all_stocks_data)
        
        # 標準化評分（使用 z-score 標準化）
        if len(result_df) > 1:
            # 計算 z-score
            price_mean = result_df['漲幅%'].mean()
            price_std = result_df['漲幅%'].std()
            vol_mean = result_df['成交量變化率%'].mean()
            vol_std = result_df['成交量變化率%'].std()
            
            # 避免除零
            if price_std > 0:
                price_z = (result_df['漲幅%'] - price_mean) / price_std
            else:
                price_z = pd.Series(0, index=result_df.index)
            
            if vol_std > 0:
                vol_z = (result_df['成交量變化率%'] - vol_mean) / vol_std
            else:
                vol_z = pd.Series(0, index=result_df.index)
            
            # 重新計算標準化分數
            result_df['評分'] = price_z * 0.6 + vol_z * 0.4
        
        # 保存所有股票的總數（用於計算 Percentile）
        total_stocks = len(result_df)
        
        # 將評分轉換為 Percentile（基於所有股票的分布）
        if total_stocks > 1:
            score_values = result_df['評分'].copy()
            sorted_scores = score_values.sort_values(ascending=False).values
            percentile_labels = []
            for score in score_values:
                better_or_equal = (sorted_scores >= score).sum()
                percentile = (total_stocks - better_or_equal + 1) / total_stocks * 100
                
                if percentile <= 1.0:
                    percentile_labels.append("Top 1%")
                elif percentile <= 3.0:
                    percentile_labels.append("Top 3%")
                elif percentile <= 5.0:
                    percentile_labels.append("Top 5%")
                elif percentile <= 10.0:
                    percentile_labels.append("Top 10%")
                elif percentile <= 20.0:
                    percentile_labels.append("Top 20%")
                elif percentile <= 50.0:
                    percentile_labels.append("Top 50%")
                else:
                    percentile_labels.append(f"Top {int(percentile)}%")
            result_df['評分'] = percentile_labels
        elif total_stocks == 1:
            result_df['評分'] = "Top 1%"
        else:
            result_df['評分'] = ""
        
        # 按原始評分值降序排序
        if total_stocks > 1:
            result_df = result_df.iloc[score_values.sort_values(ascending=False).index].copy()
        
        # 只保留前 top_n 名
        result_df = result_df.head(top_n).copy()
        
        # 添加排名
        result_df['排名'] = range(1, len(result_df) + 1)
        
        # 重新排列欄位順序
        result_df = result_df[['排名', '證券代號', '證券名稱', '收盤價', '漲幅%', '成交量變化率%', '評分', '推薦理由']]
        
        return result_df, total_stocks
    
    def get_weak_stocks(self, period='day', top_n=20, min_volume=None):
        """獲取弱勢股（與強勢股同架構，反向排名）
        
        從 technical_analysis 目錄讀取所有個股技術指標文件，按評分升序排序
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名（最弱的）
            min_volume: 最小成交量（可選）
            
        Returns:
            tuple: (DataFrame, universe_count)
                - DataFrame: 弱勢股列表，包含評分和排名
                - universe_count: Universe 股票數量（有效數據的股票數）
        """
        sqlite_result = self._try_get_sqlite_stock_screen(period, top_n, min_volume, "weak")
        if sqlite_result is not None:
            return sqlite_result

        today = datetime.now()
        if period == 'day':
            days_back = 30
        else:  # week
            days_back = 60
        start_date = today - timedelta(days=days_back)
        
        # 優先嘗試從 SQLite 資料庫載入
        grouped_list = []
        db_success = False
        
        if getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)
                max_date_df = db.execute_query("SELECT MAX(日期) as max_date FROM daily_prices;")
                if not max_date_df.empty and max_date_df['max_date'].iloc[0]:
                    max_date_str = str(max_date_df['max_date'].iloc[0])
                    latest_date = datetime.strptime(max_date_str, '%Y%m%d')
                    
                    if period == 'day':
                        days_back_db = 45
                    else:
                        days_back_db = 90
                    
                    start_date_db = latest_date - timedelta(days=days_back_db)
                    start_date_str = start_date_db.strftime('%Y%m%d')
                    
                    # 更新 start_date 給後續 python 過濾使用
                    start_date = start_date_db
                    
                    # 執行 JOIN 查詢
                    sql = """
                        SELECT p.*, t.*
                        FROM daily_prices p
                        LEFT JOIN technical_indicators t ON p.證券代號 = t.證券代號 AND p.日期 = t.日期
                        WHERE p.日期 >= ?
                        ORDER BY p.日期 ASC;
                    """
                    sql_df = db.execute_query(sql, params=(start_date_str,))
                    if not sql_df.empty:
                        sql_df = sql_df.loc[:, ~sql_df.columns.duplicated()]
                        
                        # 轉換日期格式
                        sql_df['日期'] = pd.to_datetime(sql_df['日期'].astype(str), format='%Y%m%d', errors='coerce')
                        sql_df = sql_df[sql_df['日期'].notna()]
                        
                        sql_df['證券代號'] = sql_df['證券代號'].astype(str).str.strip()
                        
                        # 轉換型態
                        numeric_cols = ['收盤價', '開盤價', '最高價', '最低價', '成交股數', '成交金額']
                        for col in numeric_cols:
                            if col in sql_df.columns:
                                sql_df[col] = pd.to_numeric(sql_df[col], errors='coerce')
                        
                        # 按證券代號分組
                        for stock_code, g_df in sql_df.groupby('證券代號'):
                            if len(stock_code) == 4 and stock_code.isdigit():
                                grouped_list.append((stock_code, g_df.sort_values('日期')))
                                
                        db_success = True
                        logger.info(f"成功從 SQLite 載入 {len(grouped_list)} 支股票數據進行弱勢股篩選")
            except Exception as db_err:
                logger.warning(f"從 SQLite 載入篩選數據失敗: {db_err}，將降級為 CSV 掃描")
                
        data_source = []
        indicator_files = []
        if db_success:
            data_source = grouped_list
        else:
            # 掃描 technical_analysis 目錄下的所有 *_indicators.csv 文件
            technical_dir = self.config.technical_dir
            if not technical_dir.exists():
                logger.warning(f"錯誤：技術指標目錄不存在: {technical_dir}")
                return pd.DataFrame()
            
            # 查找所有指標文件
            indicator_files = list(technical_dir.glob("*_indicators.csv"))
            if len(indicator_files) == 0:
                logger.warning(f"錯誤：在 {technical_dir} 中找不到任何指標文件")
                return pd.DataFrame()
                
            for indicator_file in indicator_files:
                stock_code = indicator_file.stem.replace('_indicators', '')
                data_source.append((stock_code, indicator_file))
                
            logger.info(f"[StockScreener] period={period}, days_back={days_back}, start_date={start_date.strftime('%Y-%m-%d')}")
            logger.info(f"[StockScreener] 找到 {len(indicator_files)} 個指標文件")
        
        all_stocks_data = []
        skipped_count = 0
        processed_count = 0
        
        # 讀取每個股票的指標數據
        for stock_code, data_item in data_source:
            try:
                # 讀取數據
                if isinstance(data_item, pd.DataFrame):
                    df = data_item.copy()
                else:
                    df = pd.read_csv(data_item, encoding='utf-8-sig')
                
                # 轉換日期格式
                if '日期' in df.columns:
                    if df['日期'].dtype == 'object':
                        sample_date = str(df['日期'].iloc[0]).strip() if len(df) > 0 else ''
                        if sample_date.isdigit() and len(sample_date) == 8:
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y%m%d')
                        elif '/' in sample_date:
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y/%m/%d')
                        elif '-' in sample_date:
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y-%m-%d')
                        else:
                            df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce')
                    elif pd.api.types.is_integer_dtype(df['日期']):
                        df['日期'] = pd.to_datetime(df['日期'].astype(str), errors='coerce', format='%Y%m%d')
                    else:
                        df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
                    
                    df = df[df['日期'].notna()]
                    if len(df) == 0:
                        skipped_count += 1
                        continue
                    
                    df = df.sort_values('日期')
                    df = df[df['日期'] >= pd.Timestamp(start_date)]
                    if len(df) == 0:
                        skipped_count += 1
                        continue
                else:
                    continue
                
                # 獲取最新和比較日期的數據
                latest_row = df.iloc[-1]
                
                if period == 'day':
                    if len(df) < 2:
                        skipped_count += 1
                        continue
                    compare_row = df.iloc[-2]
                else:
                    if len(df) >= 6:
                        compare_row = df.iloc[-6]
                    elif len(df) >= 3:
                        compare_row = df.iloc[-3]
                    else:
                        skipped_count += 1
                        continue
                
                # 獲取收盤價
                close_col = None
                for col in ['收盤價', 'Close', 'close']:
                    if col in latest_row.index:
                        close_col = col
                        break
                
                if close_col is None:
                    continue
                
                latest_price = latest_row[close_col]
                compare_price = compare_row[close_col]
                
                if pd.isna(latest_price) or pd.isna(compare_price) or compare_price == 0:
                    skipped_count += 1
                    continue
                
                # 價格篩選
                if latest_price < self.min_price:
                    skipped_count += 1
                    continue
                
                # 計算漲幅百分比（負數表示下跌）
                price_change = (latest_price - compare_price) / compare_price * 100
                
                # 計算成交量變化率
                volume_change = 0
                volume_ratio = 1.0
                if '成交股數' in df.columns:
                    latest_volume = latest_row.get('成交股數', 0)
                    lookback_window = min(self.volume_lookback + 1, len(df))
                    if lookback_window >= 2:
                        volume_ma = df['成交股數'].iloc[-lookback_window:-1].mean()
                    else:
                        volume_ma = 0
                    
                    if volume_ma > 0:
                        volume_ratio = latest_volume / volume_ma
                        try:
                            with np.errstate(divide='ignore', invalid='ignore'):
                                volume_change = np.log1p(max(0, volume_ratio - 1)) * 100
                        except:
                            volume_change = 0
                    else:
                        volume_change = 0
                        volume_ratio = 1.0
                
                # 成交金額篩選
                if self.min_liquidity is not None:
                    turnover = latest_row.get('成交金額', 0)
                    if turnover < self.min_liquidity:
                        skipped_count += 1
                        continue
                
                # 計算標準化評分
                vol_factor = np.log1p(max(0, volume_ratio - 1))
                score = price_change * 0.6 + vol_factor * 100 * 0.4
                
                # 獲取證券名稱
                stock_name = latest_row.get('證券名稱', stock_code)
                if pd.isna(stock_name):
                    stock_name = stock_code
                
                volume = latest_row.get('成交股數', 0)
                
                # 篩選條件
                if min_volume and volume < min_volume:
                    continue
                
                # 計算20日均量
                if '成交股數' in df.columns:
                    latest_volume = latest_row.get('成交股數', 0)
                    if len(df) >= 21:
                        volume_ma20 = df['成交股數'].iloc[-21:-1].mean()
                    elif len(df) >= 6:
                        volume_ma20 = df['成交股數'].iloc[-6:-1].mean()
                    elif len(df) >= 2:
                        volume_ma20 = df['成交股數'].iloc[:-1].mean()
                    else:
                        volume_ma20 = 0
                    
                    if volume_ma20 > 0:
                        volume_ratio = latest_volume / volume_ma20
                    else:
                        volume_ratio = 1.0
                
                # 生成弱勢股理由
                reasons = self._generate_weak_stock_reasons(
                    df, latest_row, price_change, volume_ratio, period, stock_code
                )
                
                all_stocks_data.append({
                    '證券代號': stock_code,
                    '證券名稱': stock_name,
                    '收盤價': latest_price,
                    '漲幅%': price_change,
                    '成交量變化率%': volume_change,
                    '評分': score,
                    '推薦理由': reasons
                })
                processed_count += 1
                
            except Exception as e:
                # 記錄錯誤以便除錯，然後跳過
                item_name = data_item if isinstance(data_item, pd.DataFrame) else (data_item.name if hasattr(data_item, 'name') else str(data_item))
                logger.debug(f"[StockScreener] 跳過 {item_name}: {e}")
                continue
        
        total_source_count = len(grouped_list) if db_success else len(indicator_files)
        logger.info(f"[StockScreener] 處理完成: 成功={processed_count}, 跳過={skipped_count}, 總股票/文件數={total_source_count}")
        
        if len(all_stocks_data) == 0:
            return pd.DataFrame(), 0
        
        # 轉換為DataFrame
        result_df = pd.DataFrame(all_stocks_data)
        
        # 標準化評分
        if len(result_df) > 1:
            price_mean = result_df['漲幅%'].mean()
            price_std = result_df['漲幅%'].std()
            vol_mean = result_df['成交量變化率%'].mean()
            vol_std = result_df['成交量變化率%'].std()
            
            if price_std > 0:
                price_z = (result_df['漲幅%'] - price_mean) / price_std
            else:
                price_z = pd.Series(0, index=result_df.index)
            
            if vol_std > 0:
                vol_z = (result_df['成交量變化率%'] - vol_mean) / vol_std
            else:
                vol_z = pd.Series(0, index=result_df.index)
            
            result_df['評分'] = price_z * 0.6 + vol_z * 0.4
        
        # 保存所有股票的總數（用於計算 Percentile）
        total_stocks = len(result_df)
        
        # 將評分轉換為 Percentile（從底部算起，越低越弱）
        if total_stocks > 1:
            score_values = result_df['評分'].copy()
            sorted_scores = score_values.sort_values(ascending=True).values
            percentile_labels = []
            for score in score_values:
                worse_or_equal = (sorted_scores <= score).sum()
                percentile = worse_or_equal / total_stocks * 100
                
                if percentile <= 1.0:
                    percentile_labels.append("Bottom 1%")
                elif percentile <= 3.0:
                    percentile_labels.append("Bottom 3%")
                elif percentile <= 5.0:
                    percentile_labels.append("Bottom 5%")
                elif percentile <= 10.0:
                    percentile_labels.append("Bottom 10%")
                elif percentile <= 20.0:
                    percentile_labels.append("Bottom 20%")
                elif percentile <= 50.0:
                    percentile_labels.append("Bottom 50%")
                else:
                    percentile_labels.append(f"Bottom {int(percentile)}%")
            result_df['評分'] = percentile_labels
        elif total_stocks == 1:
            result_df['評分'] = "Bottom 1%"
        else:
            result_df['評分'] = ""
        
        # 按原始評分值升序排序
        if total_stocks > 1:
            result_df = result_df.iloc[score_values.sort_values(ascending=True).index].copy()
        
        # 只保留前 top_n 名
        result_df = result_df.head(top_n).copy()
        
        # 添加排名
        result_df['排名'] = range(1, len(result_df) + 1)
        
        # 重新排列欄位順序
        result_df = result_df[['排名', '證券代號', '證券名稱', '收盤價', '漲幅%', '成交量變化率%', '評分', '推薦理由']]
        
        return result_df, total_stocks
    
    def _generate_strong_stock_reasons(self, df, latest_row, price_change, volume_ratio, period, stock_code):
        """生成強勢股推薦理由（改進版：主因 Tag + 差異化摘要）
        
        Args:
            df: 股票歷史數據DataFrame
            latest_row: 最新一筆數據
            price_change: 漲幅百分比
            volume_ratio: 成交量比率（今日量/20日均量）
            period: 'day' 或 'week'
            stock_code: 股票代號（用於獲取產業信息）
            
        Returns:
            str: 推薦理由文字（格式：【主因Tag】漲幅 +X%；量比 X 倍；背景）
        """
        # ===== 1. 生成主因 Tag =====
        main_tag = ""
        
        # 檢查創新高（優先）
        close_col = None
        for col in ['收盤價', 'Close', 'close']:
            if col in df.columns:
                close_col = col
                break
        
        is_new_high = False
        if close_col and len(df) >= 20:
            latest_price = latest_row[close_col]
            max_20d = df[close_col].tail(20).max()
            if latest_price >= max_20d * 0.999:  # 允許0.1%誤差
                is_new_high = True
        
        # 檢查連續收紅
        consecutive_days = 0
        if close_col and len(df) >= 3:
            recent_closes = df[close_col].tail(3).values
            if len(recent_closes) >= 3:
                consecutive_up = all(recent_closes[i] > recent_closes[i-1] for i in range(1, len(recent_closes)))
                if consecutive_up:
                    consecutive_days = len(recent_closes)
        
        # 獲取產業漲幅（用於判斷族群共振）
        industry_change = None
        industry_name = None
        if self.industry_mapper:
            stock_industries = self.industry_mapper.get_stock_industries(stock_code)
            if stock_industries:
                industry_name = stock_industries[0]
                industry_perf = self.industry_mapper.get_industry_performance(industry_name)
                if industry_perf:
                    industry_change_raw = industry_perf.get('漲跌百分比', 0)
                    if isinstance(industry_change_raw, str):
                        try:
                            industry_change = float(industry_change_raw.replace('%', '').replace('+', ''))
                        except:
                            industry_change = None
                    else:
                        industry_change = industry_change_raw
        
        # 選擇主因 Tag（按固定優先順序，避免同時命中時不穩定）
        # 優先順序：漲停系列 > 突破新高 > 連紅 > 爆量 > 族群
        if period == 'day':
            # 1. 【漲停爆量】（最優先，且具台股特徵）
            if price_change >= 9.0 and volume_ratio >= 1.5:
                # 添加量比子標記
                if volume_ratio >= 6.0:
                    main_tag = f"【漲停爆量・極({volume_ratio:.1f}x)】"
                elif volume_ratio >= 3.0:
                    main_tag = f"【漲停爆量・強({volume_ratio:.1f}x)】"
                else:
                    main_tag = f"【漲停爆量・中({volume_ratio:.1f}x)】"
            # 2. 【漲停但量縮】（風險提醒也很重要）
            elif price_change >= 9.0 and volume_ratio < 1.5:
                main_tag = "【漲停但量縮】"
            # 3. 【突破新高】
            elif is_new_high:
                main_tag = "【突破新高】"
            # 4. 【連N紅續強】
            elif consecutive_days >= 3:
                main_tag = f"【連{consecutive_days}紅續強】"
            # 5. 【爆量拉抬】（注意：此條件不會與漲停爆量衝突，因為已優先檢查漲停）
            elif volume_ratio >= 3.0 and price_change > 0:
                main_tag = "【爆量拉抬】"
            # 6. 【族群共振】
            elif industry_change is not None and industry_change > 1.0:
                main_tag = "【族群共振】"
        else:  # week
            # 週期版本，優先順序相同
            if price_change >= 8.0 and volume_ratio >= 1.5:
                if volume_ratio >= 6.0:
                    main_tag = f"【週漲爆量・極({volume_ratio:.1f}x)】"
                elif volume_ratio >= 3.0:
                    main_tag = f"【週漲爆量・強({volume_ratio:.1f}x)】"
                else:
                    main_tag = f"【週漲爆量・中({volume_ratio:.1f}x)】"
            elif is_new_high:
                main_tag = "【突破新高】"
            elif consecutive_days >= 3:
                main_tag = f"【連{consecutive_days}紅續強】"
            elif volume_ratio >= 3.0 and price_change > 0:
                main_tag = "【爆量拉抬】"
            elif industry_change is not None and industry_change > 1.0:
                main_tag = "【族群共振】"
        
        # 如果沒有匹配的主因 Tag，留空（不強制）
        
        # ===== 2. 生成價格動能理由（改進文案）=====
        price_reason = ""
        if period == 'day':
            if price_change >= 9.0:
                price_reason = f"漲幅 +{price_change:.1f}%（接近漲停，買盤非常積極）"
            elif price_change >= 3.0:
                price_reason = f"漲幅 +{price_change:.1f}%（強勁）"
            elif price_change >= 1.0:
                price_reason = f"漲幅 +{price_change:.1f}%"
            else:
                price_reason = f"漲幅 +{price_change:.1f}%"
        else:  # week
            if price_change >= 8.0:
                price_reason = f"週漲幅 +{price_change:.1f}%（強勁）"
            elif price_change >= 3.0:
                price_reason = f"週漲幅 +{price_change:.1f}%"
            else:
                price_reason = f"週漲幅 +{price_change:.1f}%"
        
        # ===== 3. 生成成交量理由 =====
        volume_reason = ""
        if volume_ratio >= 1.5:
            volume_reason = f"量比 {volume_ratio:.1f} 倍（放大）"
        elif volume_ratio >= 1.2:
            volume_reason = f"量比 {volume_ratio:.1f} 倍"
        elif volume_ratio >= 1.0 and price_change > 0:
            # 量比不夠強，但價漲量增仍有意義
            volume_reason = "價漲量增"
        
        # ===== 4. 生成背景理由（產業或趨勢）=====
        background_reason = ""
        
        # 優先產業（但要有門檻）
        if industry_change is not None and industry_name:
            if industry_change >= 0.8:
                background_reason = f"族群 +{industry_change:.1f}%"
            elif industry_change > 0:
                background_reason = f"族群 +{industry_change:.1f}%（弱）"
        
        # 如果沒有產業理由或產業漲幅太小，使用趨勢結構
        if not background_reason:
            # 檢查均線
            ma20_col = None
            ma60_col = None
            for col in df.columns:
                if col in ['MA20', 'SMA20', 'MA_20']:
                    ma20_col = col
                if col in ['MA60', 'SMA60', 'MA_60']:
                    ma60_col = col
            
            if close_col and ma20_col and ma20_col in latest_row.index:
                latest_price = latest_row[close_col]
                ma20 = latest_row[ma20_col]
                if latest_price > ma20:
                    background_reason = "站上 MA20"
            
            # 檢查多頭排列
            if not background_reason and close_col and ma20_col and ma60_col:
                if (ma20_col in latest_row.index and ma60_col in latest_row.index):
                    ma5_col = None
                    for col in df.columns:
                        if col in ['MA5', 'SMA5', 'MA_5']:
                            ma5_col = col
                            break
                    
                    if ma5_col and ma5_col in latest_row.index:
                        ma5 = latest_row[ma5_col]
                        ma20 = latest_row[ma20_col]
                        ma60 = latest_row[ma60_col]
                        if ma5 > ma20 > ma60:
                            background_reason = "多頭排列"
        
        # ===== 5. 組合最終理由 =====
        parts = []
        
        # 添加主因 Tag（如果有）
        if main_tag:
            parts.append(main_tag)
        
        # 添加價格理由（必須有）
        if price_reason:
            parts.append(price_reason)
        
        # 添加成交量理由（如果有）
        if volume_reason:
            parts.append(volume_reason)
        
        # 添加背景理由（如果有）
        if background_reason:
            parts.append(background_reason)
        
        # 組合（用分號分隔）
        if parts:
            result = "；".join(parts)
            return result
        else:
            return "符合強勢股條件"
    
    def _generate_weak_stock_reasons(self, df, latest_row, price_change, volume_ratio, period, stock_code):
        """生成弱勢股推薦理由（與強勢股相反）
        
        Args:
            df: 股票歷史數據DataFrame
            latest_row: 最新一筆數據
            price_change: 漲幅百分比（負數表示下跌）
            volume_ratio: 成交量比率（今日量/20日均量）
            period: 'day' 或 'week'
            stock_code: 股票代號（用於獲取產業信息）
            
        Returns:
            str: 推薦理由文字（最多3條，用「；」分隔）
        """
        reasons = []
        
        # 1. 價格動能類（最重要，優先）
        if period == 'day':
            # 當日跌幅
            if price_change < -3:
                reasons.append(f"股價今日下跌 {price_change:.1f}%，價格動能疲弱")
            elif price_change < -1:
                reasons.append(f"股價今日下跌 {price_change:.1f}%")
        else:  # week
            # 近5個交易日跌幅
            if price_change < -5:
                reasons.append(f"近5個交易日下跌 {price_change:.1f}%，價格動能疲弱")
            elif price_change < -2:
                reasons.append(f"近5個交易日下跌 {price_change:.1f}%")
        
        # 檢查連續收黑
        if '收盤價' in df.columns:
            close_col = '收盤價'
        elif 'Close' in df.columns:
            close_col = 'Close'
        elif 'close' in df.columns:
            close_col = 'close'
        else:
            close_col = None
        
        if close_col and len(df) >= 3:
            # 檢查最近3日是否連續收黑
            recent_closes = df[close_col].tail(3).values
            if len(recent_closes) >= 3:
                consecutive_down = all(recent_closes[i] < recent_closes[i-1] for i in range(1, len(recent_closes)))
                if consecutive_down:
                    reasons.append(f"連續 {len(recent_closes)} 日收黑，短期走勢偏空")
        
        # 檢查創新低
        if close_col and len(df) >= 20:
            latest_price = latest_row[close_col]
            min_20d = df[close_col].tail(20).min()
            if latest_price <= min_20d * 1.001:  # 允許0.1%誤差
                reasons.append("收盤價創 20 日新低")
        
        # 2. 成交量動能類
        if volume_ratio < 0.7:
            reasons.append(f"成交量為 20 日均量的 {volume_ratio:.1f} 倍，資金明顯萎縮")
        elif volume_ratio < 0.9:
            reasons.append(f"成交量為 20 日均量的 {volume_ratio:.1f} 倍")
        
        # 價跌量縮
        if price_change < 0 and volume_ratio < 1.0:
            reasons.append("股價下跌同時成交量減少，動能持續疲弱")
        
        # 3. 趨勢結構類
        ma20_col = None
        ma60_col = None
        for col in df.columns:
            if col in ['MA20', 'SMA20', 'MA_20']:
                ma20_col = col
            if col in ['MA60', 'SMA60', 'MA_60']:
                ma60_col = col
        
        if close_col and ma20_col and ma20_col in latest_row.index:
            latest_price = latest_row[close_col]
            ma20 = latest_row[ma20_col]
            if latest_price < ma20:
                reasons.append("股價跌破 20 日均線，短期趨勢偏空")
        
        # 檢查空頭排列
        if close_col and ma20_col and ma60_col:
            if (ma20_col in latest_row.index and ma60_col in latest_row.index):
                ma5_col = None
                for col in df.columns:
                    if col in ['MA5', 'SMA5', 'MA_5']:
                        ma5_col = col
                        break
                
                if ma5_col and ma5_col in latest_row.index:
                    ma5 = latest_row[ma5_col]
                    ma20 = latest_row[ma20_col]
                    ma60 = latest_row[ma60_col]
                    if ma5 < ma20 < ma60:
                        reasons.append("均線呈空頭排列，結構偏弱")
        
        # 4. 產業一致性
        if self.industry_mapper:
            stock_industries = self.industry_mapper.get_stock_industries(stock_code)
            if stock_industries:
                industry = stock_industries[0]
                industry_perf = self.industry_mapper.get_industry_performance(industry)
                if industry_perf:
                    industry_change = industry_perf.get('漲跌百分比', 0)
                    if isinstance(industry_change, str):
                        try:
                            industry_change = float(industry_change.replace('%', '').replace('+', ''))
                        except:
                            industry_change = 0
                    
                    if industry_change < 0:
                        reasons.append(f"所屬{industry}指數下跌 {industry_change:.1f}%，族群同步轉弱")
        
        # 選擇前3條理由（優先順序：價格動能 > 成交量 > 趨勢或產業）
        price_reasons = [r for r in reasons if '下跌' in r or '收黑' in r or '新低' in r]
        volume_reasons = [r for r in reasons if '成交量' in r or '資金' in r or ('動能' in r and '價格' not in r)]
        trend_reasons = [r for r in reasons if '均線' in r or '趨勢' in r or '排列' in r]
        industry_reasons = [r for r in reasons if '指數' in r or '族群' in r or '產業' in r]
        
        final_reasons = []
        
        # 1. 價格動能（必須有）
        if price_reasons:
            final_reasons.append(price_reasons[0])
        
        # 2. 成交量
        if volume_reasons and len(final_reasons) < 3:
            final_reasons.append(volume_reasons[0])
        
        # 3. 趨勢或產業（擇一，優先產業）
        if len(final_reasons) < 3:
            if industry_reasons:
                final_reasons.append(industry_reasons[0])
            elif trend_reasons:
                final_reasons.append(trend_reasons[0])
        
        # 如果還不夠3條，補充其他理由
        if len(final_reasons) < 3:
            all_used = set(final_reasons)
            for r in reasons:
                if r not in all_used:
                    final_reasons.append(r)
                    if len(final_reasons) >= 3:
                        break
        
        final_reasons = final_reasons[:3]
        
        return "；".join(final_reasons) if final_reasons else "符合弱勢股條件"
    
    def get_strong_industries(self, period='day', top_n=10):
        """獲取強勢產業
        
        Args:
            period: 'day' 或 'week'
            top_n: 返回前N名
            
        Returns:
            DataFrame: 強勢產業列表
        """
        sqlite_result = self._try_get_sqlite_industry_screen(period, top_n, "strong")
        if sqlite_result is not None:
            return sqlite_result

        df = None
        if getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)
                sql_df = db.execute_query("SELECT * FROM industry_indices ORDER BY 日期 ASC;")
                if not sql_df.empty:
                    df = sql_df
                    df['日期'] = pd.to_datetime(df['日期'].astype(str), format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d')
                    logger.info("成功從 SQLite 載入產業指數數據進行強勢產業篩選")
            except Exception as sql_err:
                logger.warning(f"從 SQLite 載入產業指數數據失敗: {sql_err}，將降級讀取 CSV")
                
        if df is None:
            industry_file = self.config.industry_index_file
            
            # 如果不存在，嘗試其他可能的路徑
            if not industry_file.exists():
                # 嘗試 technical_analysis 目錄
                alt_path = self.config.technical_dir / 'industry_index.csv'
                if alt_path.exists():
                    industry_file = alt_path
                else:
                    # 嘗試 meta_data 目錄
                    alt_path2 = self.config.meta_data_dir / 'industry_index.csv'
                    if alt_path2.exists():
                        industry_file = alt_path2
                    else:
                        # 調試：記錄所有嘗試的路徑
                        logger.warning(f"錯誤：找不到 industry_index.csv")
                        logger.warning(f"嘗試的路徑：")
                        logger.warning(f"  1. {self.config.industry_index_file}")
                        logger.warning(f"  2. {alt_path}")
                        logger.warning(f"  3. {alt_path2}")
                        return pd.DataFrame()
            
            try:
                df = pd.read_csv(industry_file, encoding='utf-8-sig')
            except Exception as e:
                logger.error(f"讀取文件失敗: {industry_file}")
                logger.error(f"錯誤: {str(e)}")
                return pd.DataFrame()
        
        if len(df) == 0:
            logger.warning(f"產業指數數據為空")
            return pd.DataFrame()
        
        # 處理日期欄位（支持多種格式）
        if '日期' not in df.columns:
            logger.error(f"錯誤：產業指數數據缺少「日期」欄位")
            return pd.DataFrame()
        
        # 先轉換為字符串，然後嘗試解析
        df['日期'] = df['日期'].astype(str)
        # 過濾掉無效日期
        df = df[df['日期'].notna() & (df['日期'] != 'nan') & (df['日期'] != '')]
        
        if len(df) == 0:
            logger.error(f"錯誤：產業指數數據中沒有有效的日期數據")
            return pd.DataFrame()
        
        # 嘗試解析日期（支持 YYYYMMDD 和標準格式）
        def parse_date(date_str):
            try:
                # 嘗試 YYYYMMDD 格式（8位數字）
                if len(date_str) == 8 and date_str.isdigit():
                    return pd.to_datetime(date_str, format='%Y%m%d')
                # 嘗試標準格式
                return pd.to_datetime(date_str, errors='coerce')
            except:
                return pd.NaT
        
        df['日期'] = df['日期'].apply(parse_date)
        # 過濾掉解析失敗的日期
        df = df[df['日期'].notna()]
        
        if len(df) == 0:
            logger.error(f"錯誤：無法解析產業指數數據中的日期")
            return pd.DataFrame()
        
        # 計算日期範圍（使用更寬鬆的範圍，確保能匹配到數據）
        today = datetime.now()
        if period == 'day':
            # 本日：使用最近30天的數據來計算（確保有足夠數據）
            start_date = today - timedelta(days=30)
        else:
            # 本周：使用最近60天的數據
            start_date = today - timedelta(days=60)
        
        # 只保留最近範圍內的數據
        df_filtered = df[df['日期'] >= pd.Timestamp(start_date)]
        
        if len(df_filtered) == 0:
            logger.warning(f"警告：在最近30/60天內沒有找到產業指數數據")
            if len(df) > 0:
                logger.warning(f"數據中的日期範圍：{df['日期'].min()} 到 {df['日期'].max()}")
                logger.warning(f"當前日期：{today.strftime('%Y-%m-%d')}")
                logger.warning(f"使用全部數據（降級方案）")
                # 如果沒有最近數據，使用全部數據（降級方案）
                df_filtered = df
            else:
                logger.error(f"錯誤：沒有可用的產業指數數據")
                return pd.DataFrame()
        
        # 使用過濾後的數據
        df = df_filtered
        
        # 計算各產業的漲幅
        latest_date = df['日期'].max()
        oldest_date = df['日期'].min()
        
        latest_df = df[df['日期'] == latest_date].copy()
        oldest_df = df[df['日期'] == oldest_date].copy()
        
        # 合併計算漲幅
        merged = latest_df.merge(
            oldest_df[['指數名稱', '收盤指數']],
            on='指數名稱',
            suffixes=('_latest', '_oldest'),
            how='left'
        )
        
        # 計算漲幅百分比
        merged['漲幅%'] = (
            (merged['收盤指數_latest'] - merged['收盤指數_oldest']) / 
            merged['收盤指數_oldest'] * 100
        )
        
        # 清理 NaN 和無效數據
        merged = merged.dropna(subset=['收盤指數_oldest', '收盤指數_latest'])
        merged = merged[merged['收盤指數_oldest'] != 0]
        
        # 排序並取前N名
        result = merged.nlargest(top_n, '漲幅%')[
            ['指數名稱', '收盤指數_latest', '漲幅%']
        ].copy()
        
        result.columns = ['指數名稱', '收盤指數', '漲幅%']
        result['排名'] = range(1, len(result) + 1)
        
        # 重新排列欄位順序（與強勢個股一致：排名在前）
        result = result[['排名', '指數名稱', '收盤指數', '漲幅%']]
        
        return result
    
    def get_weak_industries(self, period='day', top_n=10):
        """獲取弱勢產業（與強勢產業同架構，反向排名）
        
        Args:
            period: 'day' 或 'week'
            top_n: 返回前N名（最弱的）
            
        Returns:
            DataFrame: 弱勢產業列表
        """
        sqlite_result = self._try_get_sqlite_industry_screen(period, top_n, "weak")
        if sqlite_result is not None:
            return sqlite_result

        df = None
        if getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)
                sql_df = db.execute_query("SELECT * FROM industry_indices ORDER BY 日期 ASC;")
                if not sql_df.empty:
                    df = sql_df
                    df['日期'] = pd.to_datetime(df['日期'].astype(str), format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d')
                    logger.info("成功從 SQLite 載入產業指數數據進行弱勢產業篩選")
            except Exception as sql_err:
                logger.warning(f"從 SQLite 載入產業指數數據失敗: {sql_err}，將降級讀取 CSV")
                
        if df is None:
            industry_file = self.config.industry_index_file
            
            if not industry_file.exists():
                alt_path = self.config.technical_dir / 'industry_index.csv'
                if alt_path.exists():
                    industry_file = alt_path
                else:
                    alt_path2 = self.config.meta_data_dir / 'industry_index.csv'
                    if alt_path2.exists():
                        industry_file = alt_path2
                    else:
                        return pd.DataFrame()
            
            try:
                df = pd.read_csv(industry_file, encoding='utf-8-sig')
            except Exception as e:
                return pd.DataFrame()
        
        if len(df) == 0:
            return pd.DataFrame()
        
        if '日期' not in df.columns:
            return pd.DataFrame()
        
        df['日期'] = df['日期'].astype(str)
        df = df[df['日期'].notna() & (df['日期'] != 'nan') & (df['日期'] != '')]
        
        if len(df) == 0:
            return pd.DataFrame()
        
        def parse_date(date_str):
            try:
                if len(date_str) == 8 and date_str.isdigit():
                    return pd.to_datetime(date_str, format='%Y%m%d')
                return pd.to_datetime(date_str, errors='coerce')
            except:
                return pd.NaT
        
        df['日期'] = df['日期'].apply(parse_date)
        df = df[df['日期'].notna()]
        
        if len(df) == 0:
            return pd.DataFrame()
        
        today = datetime.now()
        if period == 'day':
            start_date = today - timedelta(days=30)
        else:
            start_date = today - timedelta(days=60)
        
        df_filtered = df[df['日期'] >= pd.Timestamp(start_date)]
        
        if len(df_filtered) == 0:
            if len(df) > 0:
                df_filtered = df
            else:
                return pd.DataFrame()
        
        df = df_filtered
        
        latest_date = df['日期'].max()
        oldest_date = df['日期'].min()
        
        latest_df = df[df['日期'] == latest_date].copy()
        oldest_df = df[df['日期'] == oldest_date].copy()
        
        merged = latest_df.merge(
            oldest_df[['指數名稱', '收盤指數']],
            on='指數名稱',
            suffixes=('_latest', '_oldest'),
            how='left'
        )
        
        merged['漲幅%'] = (
            (merged['收盤指數_latest'] - merged['收盤指數_oldest']) / 
            merged['收盤指數_oldest'] * 100
        )
        
        merged = merged.dropna(subset=['收盤指數_oldest', '收盤指數_latest'])
        merged = merged[merged['收盤指數_oldest'] != 0]
        
        # 排序並取前N名（按漲幅%升序，最弱的在前）
        result = merged.nsmallest(top_n, '漲幅%')[
            ['指數名稱', '收盤指數_latest', '漲幅%']
        ].copy()
        
        result.columns = ['指數名稱', '收盤指數', '漲幅%']
        result['排名'] = range(1, len(result) + 1)
        
        result = result[['排名', '指數名稱', '收盤指數', '漲幅%']]
        
        return result

