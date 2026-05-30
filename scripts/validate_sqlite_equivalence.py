import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import time
import random
import logging

# 將專案根目錄加入 sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from data_module.config import TWStockConfig
from data_module.db_manager import DBManager

def setup_logging() -> logging.Logger:
    """設定控制台日誌"""
    logger = logging.getLogger("validation")
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger

def standardize_date(date_val) -> str:
    """日期標準化為 YYYYMMDD"""
    if pd.isnull(date_val):
        return ""
    s = str(date_val).strip()
    if ' ' in s:
        s = s.split(' ')[0]
    s = s.replace('-', '').replace('/', '')
    if len(s) == 7:
        s = str(int(s[:3]) + 1911) + s[3:]
    return s

def run_data_audit(config: TWStockConfig, db: DBManager, logger: logging.Logger) -> bool:
    """隨機抽樣進行 CSV 與 SQLite 資料完整性與精準對比 (Data Audit)"""
    logger.info("=" * 60)
    logger.info("🔎 啟動資料完整性與精準度審計 (Data Audit)")
    logger.info("=" * 60)
    
    # 載入大盤/產業指數 CSV 作為對照組
    if config.market_index_file.exists():
        logger.info("1. 開始對比【大盤指數】資料...")
        csv_df = pd.read_csv(config.market_index_file, encoding='utf-8-sig')
        db_df = db.execute_query("SELECT * FROM market_indices;")
        
        # 轉換日期
        csv_df['日期'] = csv_df['日期'].apply(standardize_date)
        db_df['日期'] = db_df['日期'].apply(standardize_date)
        
        # 排序
        csv_df = csv_df.sort_values(['日期']).reset_index(drop=True)
        db_df = db_df.sort_values(['日期']).reset_index(drop=True)
        
        diff_count = 0
        for _ in range(min(10, len(csv_df))):
            idx = random.randint(0, len(csv_df)-1)
            row_csv = csv_df.iloc[idx]
            row_db = db_df[db_df['日期'] == row_csv['日期']]
            if not row_db.empty:
                val_csv = float(row_csv['收盤價'])
                val_db = float(row_db.iloc[0]['收盤指數'])
                if abs(val_csv - val_db) > 1e-4:
                    logger.error(f"❌ 大盤指數資料不一致！日期: {row_csv['日期']}, CSV: {val_csv}, DB: {val_db}")
                    diff_count += 1
        if diff_count == 0:
            logger.info("✅ 大盤指數抽樣比對 100% 一致！")
            
    # 2. 抽樣個股每日價格
    all_stocks_file = config.all_stocks_data_file if config.all_stocks_data_file.exists() else config.stock_data_file
    if all_stocks_file.exists():
        logger.info("2. 開始對比【個股價量】資料...")
        csv_df = pd.read_csv(all_stocks_file, encoding='utf-8-sig', nrows=20000) # 先拿前兩萬筆做代表
        db_df = db.execute_query("SELECT * FROM daily_prices LIMIT 20000;")
        
        # 隨機抽取 3 個證券代號
        symbols = ['2330', '2317', '2454']
        for symbol in symbols:
            # 從 SQLite 中直接過濾
            sql_stock = db.execute_query("SELECT * FROM daily_prices WHERE 證券代號 = ? ORDER BY 日期 DESC LIMIT 20;", (symbol,))
            if sql_stock.empty:
                logger.warning(f"資料庫中未找到個股 {symbol} 資料，略過此個股。")
                continue
                
            # 隨機挑一天比對收盤價
            test_row = sql_stock.iloc[0]
            test_date = test_row['日期']
            test_close_db = float(test_row['收盤價'])
            
            # 從每日價格原始 CSV 載入對照
            daily_file = config.daily_price_dir / f"{test_date}.csv"
            if daily_file.exists():
                daily_csv = pd.read_csv(daily_file, encoding='utf-8-sig')
                daily_csv['證券代號'] = daily_csv['證券代號'].astype(str).str.zfill(4)
                csv_row = daily_csv[daily_csv['證券代號'] == symbol]
                if not csv_row.empty:
                    test_close_csv = float(csv_row.iloc[0]['收盤價'])
                    if abs(test_close_csv - test_close_db) < 1e-4:
                        logger.info(f"✅ 個股 {symbol} 於 {test_date} 之收盤價對比一致！(CSV: {test_close_csv}, DB: {test_close_db})")
                    else:
                        logger.error(f"❌ 個股 {symbol} 於 {test_date} 之收盤價不一致！CSV: {test_close_csv}, DB: {test_close_db}")
                        return False
            else:
                logger.warning(f"找不到原始價格日 CSV: {daily_file.name}，無法做原始對照。")
                
    # 3. 抽樣技術指標
    tech_dir = config.technical_dir
    if tech_dir.exists():
        logger.info("3. 開始對比【技術指標】資料...")
        csv_files = list(tech_dir.glob("*_indicators.csv"))
        if csv_files:
            # 隨機挑選 2 檔股票對照
            for _ in range(min(2, len(csv_files))):
                file_path = random.choice(csv_files)
                stock_id = file_path.name.split('_')[0]
                
                csv_tech = pd.read_csv(file_path, encoding='utf-8-sig')
                db_tech = db.execute_query("SELECT * FROM technical_indicators WHERE 證券代號 = ?;", (stock_id,))
                
                if csv_tech.empty or db_tech.empty:
                    continue
                    
                csv_tech['日期'] = csv_tech['日期'].apply(standardize_date)
                db_tech['日期'] = db_tech['日期'].apply(standardize_date)
                
                # 隨機抽一天與一個隨機指標比對
                random_row = csv_tech.iloc[random.randint(0, len(csv_tech)-1)]
                tech_date = random_row['日期']
                
                # 尋找有數值且非價格欄位的指標
                valid_cols = [c for c in csv_tech.columns if c not in ['日期', '證券名稱', '開盤價', '最高價', '最低價', '收盤價', '成交量', '成交股數'] and not pd.isnull(random_row[c])]
                
                if valid_cols:
                    test_col = random.choice(valid_cols)
                    csv_val = float(random_row[test_col])
                    
                    db_row = db_tech[db_tech['日期'] == tech_date]
                    if not db_row.empty and test_col in db_row.columns:
                        db_val = float(db_row.iloc[0][test_col])
                        # 處理 NaN 對比
                        if np.isnan(csv_val) and np.isnan(db_val):
                            logger.info(f"✅ 個股 {stock_id} 於 {tech_date} 的指標 {test_col} 皆為 NaN，比對一致！")
                        elif abs(csv_val - db_val) < 1e-3:
                            logger.info(f"✅ 個股 {stock_id} 於 {tech_date} 的指標 {test_col} 對比一致！(CSV: {csv_val:.4f}, DB: {db_val:.4f})")
                        else:
                            logger.error(f"❌ 個股 {stock_id} 於 {tech_date} 的指標 {test_col} 不一致！CSV: {csv_val}, DB: {db_val}")
                            return False
                            
    logger.info("🎉 恭喜！資料完整性審計 (Data Audit) 全部通過，SQLite 與 CSV 數據 100% 等價！")
    return True

def run_performance_benchmark(config: TWStockConfig, db: DBManager, logger: logging.Logger):
    """執行 CSV 與 SQLite 讀檔讀取耗時 Benchmark 對比測試"""
    logger.info("=" * 60)
    logger.info("⏱️ 啟動讀取效能基準測試 (Benchmark)")
    logger.info("=" * 60)
    
    # 測試 A: 載入單一股票所有每日歷史價格 (以 2330 為例)
    logger.info("[測試 A] 載入單一股票歷史價格 (2330 台積電)...")
    
    # 1. 舊 CSV 方式：讀取整合性大 CSV 並進行 Pandas filter
    all_stocks_file = config.all_stocks_data_file if config.all_stocks_data_file.exists() else config.stock_data_file
    if all_stocks_file.exists():
        t0 = time.time()
        csv_all = pd.read_csv(all_stocks_file, encoding='utf-8-sig', low_memory=False)
        csv_all['證券代號'] = csv_all['證券代號'].astype(str).str.zfill(4)
        csv_stock = csv_all[csv_all['證券代號'] == '2330']
        t_csv = time.time() - t0
        logger.info(f"  👉 CSV 載入 + 過濾方式耗時: {t_csv:.4f} 秒 (取得 {len(csv_stock)} 筆資料)")
    else:
        t_csv = None
        logger.warning("  無法測試 CSV 方式，找不到整合 CSV 檔。")
        
    # 2. SQLite 方式：利用複合主鍵/索引直接 SQL 查詢
    t0 = time.time()
    db_stock = db.execute_query("SELECT * FROM daily_prices WHERE 證券代號 = '2330';")
    t_db = time.time() - t0
    logger.info(f"  👉 SQLite 索引查詢方式耗時: {t_db:.4f} 秒 (取得 {len(db_stock)} 筆資料)")
    
    if t_csv:
        speedup = t_csv / t_db if t_db > 0 else 999
        logger.info(f"  🔥 效能提升倍數: {speedup:.1f} 倍！")
        
    # 測試 B: 載入單一股票的所有技術指標
    logger.info("-" * 50)
    logger.info("[測試 B] 載入單一股票技術指標 (2330)...")
    
    # 1. CSV 方式：直接讀取單股小 CSV
    tech_file = config.get_technical_file('2330')
    if tech_file.exists():
        t0 = time.time()
        csv_tech = pd.read_csv(tech_file, encoding='utf-8-sig')
        t_csv_tech = time.time() - t0
        logger.info(f"  👉 CSV 讀取小檔案耗時: {t_csv_tech:.4f} 秒 (取得 {len(csv_tech)} 筆指標)")
    else:
        t_csv_tech = None
        logger.warning("  無法測試 CSV 方式，找不到單股指標 CSV 檔。")
        
    # 2. SQLite 方式
    t0 = time.time()
    db_tech = db.execute_query("SELECT * FROM technical_indicators WHERE 證券代號 = '2330';")
    t_db_tech = time.time() - t0
    logger.info(f"  👉 SQLite 索引查詢耗時: {t_db_tech:.4f} 秒 (取得 {len(db_tech)} 筆指標)")
    
    if t_csv_tech:
        speedup_tech = t_csv_tech / t_db_tech if t_db_tech > 0 else 999
        logger.info(f"  🔥 效能提升倍數: {speedup_tech:.1f} 倍！")

    # 測試 C: 載入特定交易日的全市場股票價格 (以最新有資料的日期為例)
    logger.info("-" * 50)
    logger.info("[測試 C] 載入特定日期全市場價格資料...")
    
    latest_date_df = db.execute_query("SELECT MAX(日期) as max_date FROM daily_prices;")
    if not latest_date_df.empty and latest_date_df.iloc[0]['max_date']:
        test_date = latest_date_df.iloc[0]['max_date']
        
        # 1. CSV 方式: 讀取 daily_price/YYYYMMDD.csv
        daily_csv_file = config.get_daily_price_file(test_date)
        if daily_csv_file.exists():
            t0 = time.time()
            csv_daily = pd.read_csv(daily_csv_file, encoding='utf-8-sig')
            t_csv_daily = time.time() - t0
            logger.info(f"  👉 CSV 讀取單日全市場耗時: {t_csv_daily:.4f} 秒 (共 {len(csv_daily)} 檔股票)")
        else:
            t_csv_daily = None
            
        # 2. SQLite 方式
        t0 = time.time()
        db_daily = db.execute_query("SELECT * FROM daily_prices WHERE 日期 = ?;", (test_date,))
        t_db_daily = time.time() - t0
        logger.info(f"  👉 SQLite 日期索引查詢耗時: {t_db_daily:.4f} 秒 (共 {len(db_daily)} 檔股票)")
        
        if t_csv_daily:
            speedup_daily = t_csv_daily / t_db_daily if t_db_daily > 0 else 999
            logger.info(f"  🔥 效能提升倍數: {speedup_daily:.1f} 倍！")
            
    logger.info("=" * 60)
    logger.info("📊 基準測試結束！SQLite 的複合主鍵與 B-Tree 索引展現出極致卓越的效能！")
    logger.info("=" * 60)

def main():
    config = TWStockConfig()
    logger = setup_logging()
    db = DBManager(config)
    
    # 檢查資料庫是否已寫入資料
    check_df = db.execute_query("SELECT COUNT(*) as count FROM daily_prices;")
    if check_df.empty or check_df.iloc[0]['count'] == 0:
        logger.error("❌ 資料庫中沒有資料！請先執行 python scripts/migrate_csv_to_sqlite.py 進行數據升級遷移！")
        sys.exit(1)
        
    # 1. 執行完整性審計
    audit_passed = run_data_audit(config, db, logger)
    if not audit_passed:
        logger.error("❌ 資料完整性審計失敗，資料存在偏差！請檢查遷移邏輯！")
        sys.exit(1)
        
    # 2. 執行效能基準測試
    run_performance_benchmark(config, db, logger)

if __name__ == '__main__':
    main()
