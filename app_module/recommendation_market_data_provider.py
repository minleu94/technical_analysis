"""RecommendationService market-history provider boundary."""

import logging
from typing import Any

import pandas as pd


class DefaultRecommendationMarketDataProvider:
    def __init__(self, config: Any):
        self.config = config

    def __call__(self) -> pd.DataFrame:
        logger = logging.getLogger(__name__)
        from datetime import datetime, timedelta

        # 優先嘗試從 SQLite 資料庫載入
        df = None
        if getattr(self.config, 'use_sqlite', False):
            try:
                from data_module.db_manager import DBManager
                db = DBManager(self.config)
                # 查出最新的交易日
                max_date_df = db.execute_query("SELECT MAX(日期) as max_date FROM daily_prices;")
                if not max_date_df.empty and max_date_df['max_date'].iloc[0]:
                    max_date_str = str(max_date_df['max_date'].iloc[0])
                    latest_date_dt = datetime.strptime(max_date_str, '%Y%m%d')
                    start_date_dt = latest_date_dt - timedelta(days=60)
                    start_date_str = start_date_dt.strftime('%Y%m%d')

                    sql = """
                        SELECT p.*, t.*
                        FROM daily_prices p
                        LEFT JOIN technical_indicators t ON p.證券代號 = t.證券代號 AND p.日期 = t.日期
                        WHERE p.日期 >= ?
                        ORDER BY p.日期 ASC;
                    """
                    sql_df = db.execute_query(sql, params=(start_date_str,))
                    if not sql_df.empty:
                        df = sql_df.loc[:, ~sql_df.columns.duplicated()]

                        # 轉換日期與資料型態
                        df = df.copy()
                        df.loc[:, '日期'] = pd.to_datetime(
                            df['日期'].astype(str),
                            format='%Y%m%d',
                            errors='coerce',
                        )
                        df = df[df['日期'].notna()].copy()
                        df.loc[:, '證券代號'] = df['證券代號'].astype(str).str.strip()

                        numeric_cols = ['收盤價', '開盤價', '最高價', '最低價', '成交股數', '成交金額']
                        for col in numeric_cols:
                            if col in df.columns:
                                df.loc[:, col] = pd.to_numeric(df[col], errors='coerce')

                        logger.info(f"[RecommendationService] 成功從 SQLite 載入 {len(df)} 筆股價及指標資料")
            except Exception as sql_err:
                logger.warning(f"[RecommendationService] 從 SQLite 載入資料失敗: {sql_err}，將降級讀取 CSV 檔案")

        # Fallback 到讀取 CSV
        if df is None:
            # 讀取股票數據（優先使用備用文件，因為它通常更新）
            primary_file = self.config.stock_data_file
            backup_file = self.config.all_stocks_data_file

            if backup_file.exists():
                stock_data_file = backup_file
                logger.info(
                    f"[RecommendationService] 使用備用數據文件（通常較新）: {backup_file}"
                )
            elif primary_file.exists():
                stock_data_file = primary_file
                logger.info(
                    f"[RecommendationService] 使用主要數據文件: {primary_file}"
                )
            else:
                raise FileNotFoundError(
                    f"找不到股票數據文件:\n"
                    f"主要文件: {primary_file} (存在: {primary_file.exists()})\n"
                    f"備用文件: {backup_file} (存在: {backup_file.exists()})\n"
                    f"請確認數據文件是否存在，或執行數據更新"
                )

            logger.info(
                f"[RecommendationService] 使用數據文件: {stock_data_file}, "
                f"文件大小: {stock_data_file.stat().st_size / 1024 / 1024:.2f} MB"
            )

            # 讀取最新數據（最近60天，確保有足夠數據計算技術指標）
            df = pd.read_csv(
                stock_data_file,
                encoding='utf-8-sig',
                on_bad_lines='skip',
                engine='python',
                nrows=500000
            )

            if '日期' in df.columns:
                df = df.copy()
                date_col = df['日期'].copy()
                if date_col.dtype in ['int64', 'int32', 'float64']:
                    df.loc[:, '日期'] = pd.to_datetime(date_col.astype(str), errors='coerce', format='%Y%m%d')
                else:
                    date_str = date_col.astype(str)
                    if date_str.str.len().eq(8).all() and date_str.str.isdigit().all():
                        df.loc[:, '日期'] = pd.to_datetime(date_str, errors='coerce', format='%Y%m%d')
                    else:
                        df.loc[:, '日期'] = pd.to_datetime(date_col, errors='coerce')
            else:
                raise ValueError("找不到日期欄位")

            df = df[df['日期'].notna()].copy()
            if len(df) == 0:
                raise ValueError("沒有找到股票數據")

            # 記錄原始數據的日期範圍
            raw_min_date = df['日期'].min()
            raw_max_date = df['日期'].max()
            logger.info(
                f"[RecommendationService] 原始數據日期範圍: {raw_min_date} ~ {raw_max_date}, "
                f"總筆數={len(df)}"
            )

            latest_date = df['日期'].max()
            # 取最近60天的數據
            df = df[df['日期'] >= (latest_date - pd.Timedelta(days=60))]

            if len(df) == 0:
                raise ValueError("沒有找到足夠的歷史數據")
        return df
