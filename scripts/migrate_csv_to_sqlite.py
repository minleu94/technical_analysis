import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import time
import logging
from tqdm import tqdm

# 將專案根目錄加入 sys.path 以載入 data_module
sys.path.append(str(Path(__file__).resolve().parents[1]))

from data_module.config import TWStockConfig
from data_module.db_manager import DBManager

def setup_logging(config: TWStockConfig) -> logging.Logger:
    """設定日誌格式"""
    logger = logging.getLogger("migration")
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        file_handler = logging.FileHandler(
            config.log_dir / "migration.log",
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
    return logger

def standardize_date(date_series: pd.Series) -> pd.Series:
    """統一日期格式為 YYYYMMDD 字串，相容多種常見格式"""
    def convert_single(x):
        if pd.isnull(x):
            return None
        x_str = str(x).strip()
        if not x_str or x_str == 'nan':
            return None
            
        # 移除時間部分（如果存在）
        if ' ' in x_str:
            x_str = x_str.split(' ')[0]
            
        # 1. 處理帶 - 或 / 分隔符的日期
        parts = []
        if '-' in x_str:
            parts = x_str.split('-')
        elif '/' in x_str:
            parts = x_str.split('/')
            
        if len(parts) == 3:
            y, m, d = parts[0], parts[1], parts[2]
            # 民國年判斷 (長度 <= 3 且小於 200，例如 113/05/12)
            if len(y) <= 3 and int(y) < 200:
                y = str(int(y) + 1911)
            return f"{int(y):04d}{int(m):02d}{int(d):02d}"
            
        # 2. 處理 7 位純數字 (如 1130512)
        if len(x_str) == 7 and x_str.isdigit():
            year = int(x_str[:3]) + 1911
            return f"{year}{x_str[3:]}"
            
        # 3. 處理 8 位純數字 (如 20260512)
        if len(x_str) == 8 and x_str.isdigit():
            return x_str
            
        # 4. Fallback 採用 pd.to_datetime 進行解析
        try:
            parsed = pd.to_datetime(x_str, errors='coerce')
            if pd.notna(parsed):
                return parsed.strftime('%Y%m%d')
        except:
            pass
            
        return x_str

    return date_series.apply(convert_single)

def migrate_market_and_industry_indices(config: TWStockConfig, db: DBManager, logger: logging.Logger):
    """遷移大盤指數與產業指數 CSV 資料"""
    # 1. 大盤指數
    market_file = config.market_index_file
    if market_file.exists():
        logger.info(f"開始遷移大盤指數: {market_file.name}...")
        try:
            df = pd.read_csv(market_file, encoding='utf-8-sig')
            if not df.empty:
                df['日期'] = standardize_date(df['日期'])
                
                # 欄位映射與重構以解決大盤指數欄位 KeyError Bug
                if '收盤指數' not in df.columns and '收盤價' in df.columns:
                    df['收盤指數'] = df['收盤價']
                if '指數名稱' not in df.columns:
                    df['指數名稱'] = '加權指數'
                
                # 確保其他 table columns 不會容缺報錯
                if '漲跌' not in df.columns:
                    df['漲跌'] = '+'
                if '漲跌點數' not in df.columns:
                    df['漲跌點數'] = 0.0
                if '漲跌百分比' not in df.columns:
                    df['漲跌百分比'] = 0.0
                
                # 篩選所需的欄位寫入資料庫
                cols_to_keep = ['日期', '指數名稱', '收盤指數', '漲跌', '漲跌點數', '漲跌百分比']
                df_to_write = df[[c for c in cols_to_keep if c in df.columns]]
                
                # 保證寫入時覆蓋/新增，使用 replace
                success = db.write_dataframe('market_indices', df_to_write, if_exists='replace')
                if success:
                    logger.info(f"大盤指數遷移成功，共 {len(df_to_write)} 筆資料！")
                else:
                    logger.error("大盤指數寫入 SQLite 失敗！")
            else:
                logger.warning("大盤指數 CSV 為空，略過。")
        except Exception as e:
            logger.error(f"大盤指數遷移發生異常: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    else:
        logger.warning(f"未找到大盤指數 CSV 檔: {market_file}")

    # 2. 產業指數
    industry_file = config.industry_index_file
    if industry_file.exists():
        logger.info(f"開始遷移產業指數: {industry_file.name}...")
        try:
            df = pd.read_csv(industry_file, encoding='utf-8-sig')
            if not df.empty:
                df['日期'] = standardize_date(df['日期'])
                df['收盤指數'] = pd.to_numeric(df['收盤指數'], errors='coerce')
                df['漲跌點數'] = pd.to_numeric(df['漲跌點數'], errors='coerce')
                df['漲跌百分比'] = pd.to_numeric(df['漲跌百分比'], errors='coerce')
                
                # 篩選寫入
                cols_to_keep = ['日期', '指數名稱', '收盤指數', '漲跌', '漲跌點數', '漲跌百分比']
                df_to_write = df[[c for c in cols_to_keep if c in df.columns]]
                
                success = db.write_dataframe('industry_indices', df_to_write, if_exists='replace')
                if success:
                    logger.info(f"產業指數遷移成功，共 {len(df_to_write)} 筆資料！")
                else:
                    logger.error("產業指數寫入 SQLite 失敗！")
            else:
                logger.warning("產業指數 CSV 為空，略過。")
        except Exception as e:
            logger.error(f"產業指數遷移發生異常: {str(e)}")
    else:
        logger.warning(f"未找到產業指數 CSV 檔: {industry_file}")

def migrate_daily_prices(config: TWStockConfig, db: DBManager, logger: logging.Logger):
    """遷移個股每日價量 CSV 資料 (all_stocks_data.csv)"""
    all_stocks_file = config.all_stocks_data_file
    if not all_stocks_file.exists():
        # 退而求其次，檢查 stock_data_file (舊版整合檔)
        all_stocks_file = config.stock_data_file
        
    if not all_stocks_file.exists():
        logger.warning(f"未找到整合個股價量 CSV 檔 (all_stocks_data.csv 或 stock_data_whole.csv)！")
        return
        
    logger.info(f"開始遷移個股每日價格歷史: {all_stocks_file.name}...")
    start_time = time.time()
    
    try:
        # 由於此檔案可能很大，我們採用分批 (chunksize) 方式讀取與寫入，以防止記憶體崩潰
        chunk_size = 50000
        total_rows = 0
        
        # 先清空原本的 Table，以便進行全新且乾淨的寫入
        with db.connect() as conn:
            conn.execute("DELETE FROM daily_prices;")
            
        chunks = pd.read_csv(all_stocks_file, encoding='utf-8-sig', chunksize=chunk_size, low_memory=False)
        
        # 為了進度條，先取得總行數（可選，若檔案太大可跳過，這裡採用快速概估或 tqdm 計數）
        for chunk in chunks:
            # 轉換日期
            chunk['日期'] = standardize_date(chunk['日期'])
            # 確保證券代號是4位數字字串
            chunk['證券代號'] = chunk['證券代號'].astype(str).str.zfill(4)
            
            # 清理與轉換數值
            numeric_cols = ['成交股數', '成交筆數', '成交金額', '開盤價', '最高價', '最低價', '收盤價', '漲跌價差',
                            '最後揭示買價', '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']
            for col in numeric_cols:
                if col in chunk.columns:
                    chunk[col] = pd.to_numeric(chunk[col], errors='coerce')
            
            # 寫入 SQLite
            success = db.write_dataframe('daily_prices', chunk, if_exists='append')
            if not success:
                logger.error("個股每日價格 chunk 寫入 SQLite 失敗！")
                
            total_rows += len(chunk)
            logger.info(f"已遷移 {total_rows} 筆個股每日價格資料...")
            
        elapsed = time.time() - start_time
        logger.info(f"個股每日價格歷史遷移完成！共 {total_rows} 筆，耗時 {elapsed:.1f} 秒！")
        
    except Exception as e:
        logger.error(f"個股每日價格歷史遷移發生異常: {str(e)}")

def migrate_technical_indicators(config: TWStockConfig, db: DBManager, logger: logging.Logger):
    """遷移 technical_analysis/ 目錄下的所有個股技術指標 CSV """
    tech_dir = config.technical_dir
    if not tech_dir.exists():
        logger.warning(f"未找到技術指標目錄: {tech_dir}")
        return
        
    # 搜尋所有 *_indicators.csv 檔案
    csv_files = list(tech_dir.glob("*_indicators.csv"))
    if not csv_files:
        logger.warning("技術指標目錄下沒有 CSV 檔案。")
        return
        
    logger.info(f"開始遷移技術指標，共偵測到 {len(csv_files)} 檔個股指標 CSV...")
    start_time = time.time()
    
    # 清空現有 table 進行全新載入
    with db.connect() as conn:
        conn.execute("DELETE FROM technical_indicators;")
        
    success_count = 0
    
    # 使用 tqdm 顯示精美進度條
    for file_path in tqdm(csv_files, desc="遷移個股技術指標"):
        # 檔名格式為 {stock_id}_indicators.csv
        stock_id = file_path.name.split('_')[0]
        if len(stock_id) != 4 or not stock_id.isdigit():
            continue
            
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            if df.empty:
                continue
                
            # 標準化欄位與日期
            df['日期'] = standardize_date(df['日期'])
            df['證券代號'] = stock_id
            
            # 技術指標通常會包含開高低收等欄位，為了保持 tables 解耦，
            # 我們在 technical_indicators 表中僅儲存 '日期', '證券代號' 和「所有技術指標欄位」（排除價格重複欄位）
            cols_to_drop = [c for c in ['證券名稱', '開盤價', '最高價', '最低價', '收盤價', '成交股數', '成交量'] if c in df.columns]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)
                
            # 確保除了日期與證券代號外，其餘所有指標欄位皆為數值型 Real
            for col in df.columns:
                if col not in ['日期', '證券代號']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
            # 寫入 SQLite (write_dataframe 會自動進行 schema 欄位對齊升級)
            success = db.write_dataframe('technical_indicators', df, if_exists='append')
            if success:
                success_count += 1
            else:
                logger.error(f"股票 {stock_id} 技術指標寫入 SQLite 失敗")
                
        except Exception as e:
            logger.error(f"遷移股票 {stock_id} 技術指標發生異常: {str(e)}")
            
    elapsed = time.time() - start_time
    logger.info(f"技術指標遷移完成！成功遷移 {success_count} 檔個股，共耗時 {elapsed:.1f} 秒！")

def migrate_broker_flows(config: TWStockConfig, db: DBManager, logger: logging.Logger):
    """遷移券商分點資料 (broker_flow)"""
    broker_dir = config.broker_flow_dir
    if not broker_dir.exists():
        logger.warning(f"未找到券商分點目錄: {broker_dir}")
        return
        
    logger.info("開始遷移券商分點歷史資料...")
    start_time = time.time()
    
    # 遍歷各分點目錄下 meta/merged.csv 檔案
    # 分點結構通常為: broker_flow/{branch_system_key}/meta/merged.csv
    merged_files = list(broker_dir.glob("**/meta/merged.csv"))
    
    if not merged_files:
        logger.warning("未偵測到任何分點的合併 merged.csv 檔案。")
        return
        
    # 清空現有 table 進行全新載入
    with db.connect() as conn:
        conn.execute("DELETE FROM broker_flows;")
        
    success_count = 0
    total_records = 0
    
    for file_path in merged_files:
        # 從路徑取得 branch_system_key (即父資料夾的父資料夾)
        branch_key = file_path.parent.parent.name
        
        try:
            logger.info(f"正在遷移分點 [{branch_key}] 的合併歷史數據...")
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            if df.empty:
                continue
                
            # 重命名映射以支援英文小寫欄位 (MoneyDJ 爬蟲輸出格式)
            rename_mapping = {
                'date': '日期',
                'counterparty_broker_code': '證券代號',
                'counterparty_broker_name': '證券名稱',
                'buy_lots': '買進張數',
                'sell_lots': '賣出張數',
                'net_lots': '買賣超張數',
                'buy_amount_k_twd': '買進金額千元',
                'sell_amount_k_twd': '賣出金額千元',
                'net_amount_k_twd': '買賣超金額千元',
                # 舊版 c=B CSV 的 generic qty 欄位實際是仟元。
                'buy_qty': '買進金額千元',
                'sell_qty': '賣出金額千元',
                'net_qty': '買賣超金額千元',
            }
            df = df.rename(columns=rename_mapping)
            
            # 標準化欄位與日期
            df['日期'] = standardize_date(df['日期'])
            df['分點名稱'] = branch_key
            df['證券代號'] = df['證券代號'].astype(str).str.zfill(4)
            
            for lot_col in ['買進張數', '賣出張數', '買賣超張數']:
                if lot_col not in df.columns:
                    df[lot_col] = 0
                df[lot_col] = pd.to_numeric(
                    df[lot_col],
                    errors='coerce',
                ).fillna(0).astype(int)

            df['買進股數'] = df['買進張數'] * 1000
            df['賣出股數'] = df['賣出張數'] * 1000
            df['買賣超股數'] = df['買賣超張數'] * 1000
                
            # 轉換數值型
            numeric_cols = [
                '買進股數', '賣出股數', '買賣超股數',
                '買進金額千元', '賣出金額千元', '買賣超金額千元',
            ]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            
            # 保留所需的欄位寫入
            cols_to_keep = [
                '日期', '分點名稱', '證券代號', '證券名稱',
                '買進股數', '賣出股數', '買賣超股數',
                '買進金額千元', '賣出金額千元', '買賣超金額千元',
            ]
            df_to_write = df[[c for c in cols_to_keep if c in df.columns]]
            
            # 移除重複資料以滿足 SQLite 複合主鍵的 UNIQUE 限制
            df_to_write = df_to_write.drop_duplicates(subset=['日期', '分點名稱', '證券代號'], keep='last')
            
            success = db.write_dataframe('broker_flows', df_to_write, if_exists='append')
            if success:
                success_count += 1
                total_records += len(df_to_write)
            else:
                logger.error(f"分點 {branch_key} 寫入 SQLite 失敗")
                
        except Exception as e:
            logger.error(f"遷移分點 {branch_key} 發生異常: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
    elapsed = time.time() - start_time
    logger.info(f"券商分點遷移完成！成功遷移 {success_count} 個分點，共 {total_records} 筆記錄，耗時 {elapsed:.1f} 秒！")

def main():
    # 1. 取得專案配置
    config = TWStockConfig()
    
    # 2. 設定日誌
    logger = setup_logging(config)
    logger.info("=" * 60)
    logger.info("台股 CSV 升級至 SQLite 資料庫遷移工具啟動")
    logger.info(f"目標資料庫位置: {config.db_file}")
    logger.info("=" * 60)
    
    # 3. 實例化資料庫管理員
    db = DBManager(config)
    
    # 4. 開始遷移工作
    try:
        # A. 遷移指數資料
        migrate_market_and_industry_indices(config, db, logger)
        
        # B. 遷移個股每日價量資料
        migrate_daily_prices(config, db, logger)
        
        # C. 遷移個股技術指標資料
        migrate_technical_indicators(config, db, logger)
        
        # D. 遷移券商分點資料
        migrate_broker_flows(config, db, logger)
        
        logger.info("=" * 60)
        logger.info("🎉 恭喜！台股 CSV 數據全部成功升級為 SQLite 儲存！")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.critical(f"遷移過程發生重大崩潰: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
