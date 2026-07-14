import sys
import os
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import logging
from typing import Callable

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_module.config import TWStockConfig
from data_module.db_manager import DBManager
from data_module.p0_candidate_repository import validate_candidate_working_copy_path
from data_module.official_phase3c_fetcher import (
    fetch_institutional_flows,
    fetch_credit_transactions,
    fetch_tdcc_shareholding,
    safe_request,
)
from data_module.p0_official_source_parsers import (
    OfficialParserResult,
    RawFetchEnvelope,
    parse_tdcc_shareholding,
    parse_twse_credit,
    parse_twse_institutional,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def run_bounded_official_probe(probe_date: date) -> dict:
    """對三個官方端點做單日、唯讀、無落盤 probe，僅回報工程 diagnostics。"""
    date_ce = probe_date.strftime("%Y%m%d")
    probe_requests: tuple[
        tuple[
            str,
            str,
            str,
            str,
            dict[str, str],
            Callable[[RawFetchEnvelope], OfficialParserResult],
        ],
        ...,
    ] = (
        (
            "twse_institutional",
            "twse-T86.v1",
            "twse:T86",
            "https://www.twse.com.tw/fund/T86",
            {"response": "json", "date": date_ce, "selectType": "ALL"},
            parse_twse_institutional,
        ),
        (
            "twse_credit",
            "twse-MI_MARGN.v1",
            "twse:MI_MARGN",
            "https://www.twse.com.tw/exchangeReport/MI_MARGN",
            {"response": "json", "date": date_ce, "selectType": "ALL"},
            parse_twse_credit,
        ),
        (
            "tdcc_shareholding",
            "tdcc-1-5.v1",
            "tdcc:1-5",
            "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5",
            {},
            parse_tdcc_shareholding,
        ),
    )
    diagnostics: list[dict] = []
    for source_id, source_version, endpoint_id, url, params, parser in probe_requests:
        fetched_at = datetime.now(timezone.utc)
        try:
            response = safe_request(url, params or None)
            payload = bytes(response.content)
        except Exception as exc:
            diagnostics.append(
                {
                    "source_id": source_id,
                    "endpoint_id": endpoint_id,
                    "network_status": "failed",
                    "http_status": None,
                    "payload_sha256": None,
                    "payload_size_bytes": 0,
                    "fetched_at": fetched_at.isoformat(),
                    "schema_status": "unavailable",
                    "timestamp_evidence": "unavailable",
                    "raw_row_count": 0,
                    "accepted_row_count": 0,
                    "duplicate_row_count": 0,
                    "quarantine_row_count": 0,
                    "blocked_row_count": 0,
                    "quarantine_reasons": [],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue

        envelope = RawFetchEnvelope(
            source_id=source_id,
            source_version=source_version,
            endpoint_id=endpoint_id,
            request_parameters=params,
            fetched_at=fetched_at,
            http_status=int(response.status_code),
            http_headers=dict(response.headers),
            payload=payload,
        )
        raw_evidence = {
            "source_id": source_id,
            "endpoint_id": endpoint_id,
            "network_status": "reachable",
            "http_status": int(response.status_code),
            "payload_sha256": sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "fetched_at": fetched_at.isoformat(),
        }
        try:
            result = parser(envelope)
            evidence_kinds = {
                row.availability_evidence_kind for row in result.accepted
            }
            timestamp_evidence = (
                next(iter(evidence_kinds))
                if len(evidence_kinds) == 1
                else "mixed_or_unavailable"
            )
            diagnostics.append(
                {
                    **raw_evidence,
                    "schema_status": "matched",
                    "timestamp_evidence": timestamp_evidence,
                    "raw_row_count": result.raw_row_count,
                    "accepted_row_count": result.accepted_row_count,
                    "duplicate_row_count": result.duplicate_row_count,
                    "quarantine_row_count": result.quarantine_row_count,
                    "blocked_row_count": result.blocked_row_count,
                    "quarantine_reasons": sorted(
                        {record.reason_code for record in result.quarantine}
                    ),
                }
            )
        except Exception as exc:
            diagnostics.append(
                {
                    **raw_evidence,
                    "schema_status": "mismatch",
                    "timestamp_evidence": "unavailable",
                    "raw_row_count": 0,
                    "accepted_row_count": 0,
                    "duplicate_row_count": 0,
                    "quarantine_row_count": 0,
                    "blocked_row_count": 0,
                    "quarantine_reasons": [],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return {
        "probe_date": probe_date.isoformat(),
        "probe_mode": "bounded_official_read_only",
        "sources": diagnostics,
        "license_accepted": False,
        "source_accepted": False,
        "downstream_eligibility": "none",
        "production_scheduler_allowed": False,
        "human_decision": "requires_human_acceptance",
    }

def update_phase3c_candidates(decision_date: date, dry_run: bool = True, db_path: str = None):
    """
    抓取 Phase 3C 資料。
    注意：不屬於 V3.0 closeout gate，不是 production scheduler。
    """
    logger.info(f"=== 開始 Phase 3C 資料更新 ({decision_date}) ===")
    logger.info("access_boundary: writes_allowed=" + ("true" if not dry_run else "false"))
    logger.info("access_boundary: production_scheduler_allowed=false")
    logger.info("access_boundary: scoring_engine_write_allowed=false")
    logger.info("access_boundary: investment_effectiveness_claim=false")
    logger.info("access_boundary: v3_closeout_gate_credit=false")

    if not dry_run:
        if not db_path:
            logger.error("apply 必須提供 explicit working-copy DB；未提供時不建立 DB。")
            return
        production_data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data"))
        candidate_db = validate_candidate_working_copy_path(
            db_path,
            production_data_root=production_data_root,
            production_db_path=production_data_root / "sqlite" / "twstock.db",
        )
        if not candidate_db.exists():
            logger.error(f"資料庫 {candidate_db} 不存在，dry-run / apply 不建立新 DB。")
            return
        config = TWStockConfig()
        config.db_file = candidate_db
        config.db_path = candidate_db
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
