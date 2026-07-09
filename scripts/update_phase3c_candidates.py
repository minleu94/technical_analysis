import sys
import os
from pathlib import Path
from datetime import date, timedelta
import logging

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from data_module.db_manager import DBManager
from data_module.official_phase3c_fetcher import (
    fetch_institutional_flows,
    fetch_credit_transactions,
    fetch_tdcc_shareholding
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def update_phase3c_candidates(decision_date: date, dry_run: bool = True, db_path: str = None):
    """
    抓取 Phase 3C 資料。
    注意：不屬於 V3.0 closeout gate，不是 production scheduler。
    """
    config = TWStockConfig()
    config.db_path = config.db_file
    if db_path:
        config.db_file = Path(db_path)
        config.db_path = config.db_file

    logger.info(f"=== 開始 Phase 3C 資料更新 ({decision_date}) ===")
    logger.info("access_boundary: writes_allowed=" + ("true" if not dry_run else "false"))
    logger.info("access_boundary: production_scheduler_allowed=false")
    logger.info("access_boundary: scoring_engine_write_allowed=false")
    logger.info("access_boundary: investment_effectiveness_claim=false")
    logger.info("access_boundary: v3_closeout_gate_credit=false")

    if not dry_run:
        if not os.path.exists(config.db_file):
            logger.error(f"資料庫 {config.db_path} 不存在，dry-run / apply 不建立新 DB。")
            return
        db_manager = DBManager(config)
        db_manager.ensure_phase3c_candidate_tables()
    else:
        logger.info("Dry-run 模式：不建立 DB / Table，僅產生 diagnostics")
        db_manager = None

    # 1. 三大法人
    logger.info("-> 抓取三大法人...")
    df_inst = fetch_institutional_flows(decision_date)
    if df_inst is None or df_inst.empty:
        logger.warning(f"  [三大法人] {decision_date} 無資料或抓取失敗")
    else:
        logger.info(f"  [三大法人] 取得 {len(df_inst)} 筆資料")
        if not dry_run:
            db_manager.write_dataframe("institutional_flows", df_inst, if_exists="append")

    # 2. 信用交易
    logger.info("-> 抓取信用交易...")
    df_credit = fetch_credit_transactions(decision_date)
    if df_credit is None or df_credit.empty:
        logger.warning(f"  [信用交易] {decision_date} 無資料或抓取失敗")
    else:
        logger.info(f"  [信用交易] 取得 {len(df_credit)} 筆資料")
        if not dry_run:
            db_manager.write_dataframe("credit_transactions", df_credit, if_exists="append")

    # 3. TDCC 集保庫存
    logger.info("-> 抓取 TDCC 集保庫存...")
    df_tdcc = fetch_tdcc_shareholding(decision_date)
    if df_tdcc is None or df_tdcc.empty:
        logger.warning("  [TDCC] 無資料、日期不符或抓取失敗")
    else:
        logger.info(f"  [TDCC] 取得 {len(df_tdcc)} 筆資料")
        if not dry_run:
            db_manager.write_dataframe("tdcc_shareholding", df_tdcc, if_exists="append")

    logger.info("=== Phase 3C 資料更新完成 ===")

def update_phase3c_candidates_range(start_date: str, end_date: str, dry_run: bool = True, db_path: str = None, progress_callback=None):
    """區間抓取 Phase 3C 資料。"""
    import pandas as pd
    dates = pd.bdate_range(start=start_date, end=end_date)
    total = len(dates)

    if total == 0:
        if progress_callback:
            progress_callback("無工作日需更新", 100)
        return {"success": True, "message": "無工作日需更新"}

    for idx, dt in enumerate(dates):
        d = dt.date()
        if progress_callback:
            progress_callback(f"Phase 3C 籌碼更新 ({d})...", int((idx / total) * 100))
        try:
            update_phase3c_candidates(d, dry_run=dry_run, db_path=db_path)
        except Exception as e:
            logger.error(f"更新 {d} 時發生錯誤: {e}")

    if progress_callback:
        progress_callback("Phase 3C 籌碼更新完成", 100)
    return {"success": True, "message": f"成功更新 {total} 天的 Phase 3C 資料"}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Update Phase 3C Source Candidates (Institutional, Credit, TDCC)")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD, 預設為今天", default=None)
    parser.add_argument("--start-date", type=str, help="YYYY-MM-DD 起始日", default=None)
    parser.add_argument("--end-date", type=str, help="YYYY-MM-DD 結束日", default=None)
    parser.add_argument("--db-path", type=str, help="指定寫入的資料庫路徑", default=None)
    parser.add_argument("--confirm", type=str, help="必須填入 apply-phase3c-candidate-ingestion 才能實際寫入 DB", default=None)
    parser.add_argument("--dry-run", action="store_true", help="強制 dry-run", default=True)
    args = parser.parse_args()

    is_dry_run = True
    if args.confirm == "apply-phase3c-candidate-ingestion":
        is_dry_run = False

    if args.start_date:
        end_date = args.end_date if args.end_date else date.today().isoformat()
        update_phase3c_candidates_range(args.start_date, end_date, dry_run=is_dry_run, db_path=args.db_path)
    else:
        target_date = date.fromisoformat(args.date) if args.date else date.today()
        update_phase3c_candidates(target_date, dry_run=is_dry_run, db_path=args.db_path)
