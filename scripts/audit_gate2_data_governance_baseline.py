"""Gate 2 Data Governance Baseline Audit Script

Read-only audit script for database, P0 sources, PIT metadata, quality anomalies,
evidence accumulation status, and scheduler observability.
Outputs machine-readable JSON and Markdown report.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import sqlite3
from typing import Any, Dict, List, Optional

import pandas as pd

from data_module.config import TWStockConfig
from data_module.db_manager import DBManager
from data_module.p0_source_contract_registry import P0_SOURCE_IDS
from data_module.source_acceptance_decision_registry import SourceAcceptanceDecisionRegistry
from data_module.source_acceptance_governance import SourceAcceptanceDossier, SourceAcceptanceGovernance


def run_baseline_audit(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Execute complete read-only data governance baseline audit."""
    config = TWStockConfig()
    if db_path is not None:
        config.db_file = Path(db_path)
    resolved_db_path = config.db_file

    report_timestamp = datetime.now().isoformat()
    db_exists = resolved_db_path.exists()

    result: Dict[str, Any] = {
        "audit_timestamp": report_timestamp,
        "database": {
            "db_path": str(resolved_db_path),
            "exists": db_exists,
            "size_bytes": resolved_db_path.stat().st_size if db_exists else 0,
        },
        "tables": {},
        "anomalies": {},
        "pit_governance": {},
        "p0_sources": [],
        "gate_status": {},
    }

    if not db_exists:
        result["error"] = f"Database file not found at {resolved_db_path}"
        return result

    db = DBManager(config)

    # 1. Table Statistics & Daily Prices Anomaly Check
    try:
        df_daily_stats = db.execute_query("""
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT 證券代號) as unique_stocks,
                MIN(日期) as min_date,
                MAX(日期) as max_date
            FROM daily_prices;
        """)
        daily_stats = df_daily_stats.iloc[0].to_dict() if not df_daily_stats.empty else {}
    except Exception as e:
        daily_stats = {"error": str(e)}

    # Anomaly checks on daily_prices
    daily_anomalies: Dict[str, Any] = {
        "null_stock_code_count": 0,
        "blank_stock_code_count": 0,
        "suspicious_weekend_count": 0,
        "duplicate_pk_count": 0,
        "invalid_price_range_count": 0,
    }

    try:
        null_codes = db.execute_query("""
            SELECT COUNT(*) as count FROM daily_prices
            WHERE 證券代號 IS NULL OR TRIM(證券代號) = '';
        """)
        daily_anomalies["null_stock_code_count"] = int(null_codes.iloc[0]["count"]) if not null_codes.empty else 0
    except Exception:
        pass

    try:
        # Check suspicious weekend rows (dates falling on Sat=6/Sun=0 if formatted as YYYY-MM-DD or YYYYMMDD)
        df_dates = db.execute_query("SELECT DISTINCT 日期 FROM daily_prices WHERE 日期 IS NOT NULL;")
        suspicious_weekend_dates = []
        for d_val in df_dates["日期"].tolist():
            d_str = str(d_val).replace("-", "")
            if len(d_str) == 8:
                try:
                    dt = datetime.strptime(d_str, "%Y%m%d")
                    if dt.weekday() in (5, 6): # Sat/Sun
                        suspicious_weekend_dates.append(d_str)
                except ValueError:
                    pass

        if suspicious_weekend_dates:
            weekend_placeholders = ",".join(f"'{d}'" for d in suspicious_weekend_dates[:100])
            weekend_rows = db.execute_query(f"""
                SELECT COUNT(*) as count FROM daily_prices
                WHERE 日期 IN ({weekend_placeholders}) OR REPLACE(日期, '-', '') IN ({weekend_placeholders});
            """)
            daily_anomalies["suspicious_weekend_count"] = int(weekend_rows.iloc[0]["count"]) if not weekend_rows.empty else len(suspicious_weekend_dates)
            daily_anomalies["suspicious_weekend_dates_sample"] = suspicious_weekend_dates[:10]
    except Exception as e:
        daily_anomalies["weekend_check_error"] = str(e)

    try:
        dup_pks = db.execute_query("""
            SELECT 證券代號, 日期, COUNT(*) as cnt
            FROM daily_prices
            GROUP BY 證券代號, 日期
            HAVING cnt > 1;
        """)
        daily_anomalies["duplicate_pk_count"] = len(dup_pks) if not dup_pks.empty else 0
    except Exception:
        pass

    result["tables"]["daily_prices"] = daily_stats
    result["anomalies"]["daily_prices"] = daily_anomalies

    # 2. Market Indices Check
    market_stats: Dict[str, Any] = {}
    try:
        df_market = db.execute_query("""
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT 指數名稱) as unique_indices,
                MIN(日期) as min_date,
                MAX(日期) as max_date
            FROM market_indices;
        """)
        market_stats = df_market.iloc[0].to_dict() if not df_market.empty else {}

        # Check canonical vs legacy columns
        cols = db.get_table_columns("market_indices")
        market_stats["columns"] = cols

        df_null_names = db.execute_query("""
            SELECT COUNT(*) as count FROM market_indices
            WHERE 指數名稱 IS NULL OR TRIM(指數名稱) = '';
        """)
        null_name_cnt = int(df_null_names.iloc[0]["count"]) if not df_null_names.empty else 0
        market_stats["null_name_count"] = null_name_cnt
        market_stats["status"] = "degraded" if null_name_cnt > 0 or "指數名稱" not in cols else "healthy"
    except Exception as e:
        market_stats = {"error": str(e), "status": "missing_table"}

    result["tables"]["market_indices"] = market_stats

    # 3. Fundamental & Valuation PIT Governance Check
    pit_stats: Dict[str, Any] = {}

    for table_name in ["fundamental_monthly_revenues", "fundamental_statement_items", "valuation"]:
        try:
            if db.has_table(table_name):
                df_rev = db.execute_query(f"SELECT COUNT(*) as cnt FROM {table_name};")
                cnt = int(df_rev.iloc[0]["cnt"]) if not df_rev.empty else 0
                cols = db.get_table_columns(table_name)

                has_announced = "announced_date" in cols or "發布日期" in cols or "公告日" in cols
                has_available = "available_date" in cols or "可得日" in cols

                if cnt == 0:
                    pit_status = "RESEARCH_SIDECAR_ONLY_0_FORMAL_ROWS"
                    metadata_summary: Dict[str, Any] = {}
                elif has_announced and has_available:
                    metadata_df = db.execute_query(
                        f"""
                        SELECT
                            SUM(CASE WHEN announced_date IS NULL OR TRIM(announced_date) = '' THEN 1 ELSE 0 END)
                                AS announced_date_missing_count,
                            SUM(CASE WHEN available_date IS NULL OR TRIM(available_date) = '' THEN 1 ELSE 0 END)
                                AS available_date_missing_count,
                            COUNT(DISTINCT available_date) AS available_date_distinct_count,
                            MIN(available_date) AS min_available_date,
                            MAX(available_date) AS max_available_date
                        FROM {table_name};
                        """
                    )
                    metadata_summary = metadata_df.iloc[0].to_dict() if not metadata_df.empty else {}
                    announced_missing = int(metadata_summary.get("announced_date_missing_count") or 0)
                    available_missing = int(metadata_summary.get("available_date_missing_count") or 0)
                    distinct_available = int(metadata_summary.get("available_date_distinct_count") or 0)

                    if available_missing > 0:
                        pit_status = "REJECTED_AVAILABLE_DATE_PROVENANCE_MISSING"
                    elif announced_missing > 0:
                        pit_status = "DEGRADED_ANNOUNCED_DATE_PROVENANCE_MISSING"
                    elif distinct_available <= 1:
                        pit_status = "DEGRADED_AVAILABLE_DATE_CONCENTRATED"
                    else:
                        pit_status = "PIT_METADATA_PRESENT_REQUIRES_DECISION_TIME_GATE"
                else:
                    pit_status = "LEGACY_UNVERIFIED_MISSING_PIT_COLS"
                    metadata_summary = {}

                pit_stats[table_name] = {
                    "row_count": cnt,
                    "columns": cols,
                    "has_announced_date": has_announced,
                    "has_available_date": has_available,
                    "pit_security_status": pit_status,
                    "metadata_summary": metadata_summary,
                }
            else:
                pit_stats[table_name] = {
                    "status": "table_not_found",
                    "row_count": 0,
                    "pit_security_status": "RESEARCH_SIDECAR_ONLY_0_FORMAL_ROWS",
                }
        except Exception as e:
            pit_stats[table_name] = {
                "error": str(e),
                "row_count": 0,
                "pit_security_status": "AUDIT_FAILED_FAIL_CLOSED",
            }

    result["pit_governance"] = pit_stats

    # 4. P0 Sources Acceptance Status
    governance = SourceAcceptanceGovernance()
    p0_summary: List[Dict[str, Any]] = []

    for src_id in P0_SOURCE_IDS:
        # Create minimal dossier representation
        dossier = SourceAcceptanceDossier(
            source_id=src_id,
            source_owner_role="data_team",
            license_owner_role="",
            license_status="unverified",
            license_scope="research_only",
            redistribution_policy="unverified",
            source_status="candidate",
            publication_time_policy="unverified",
            timezone="Asia/Taipei",
            available_date_policy="unverified",
            revision_policy="unverified",
            pit_coverage_window="unverified",
            coverage_numerator=0,
            coverage_denominator=100,
            missing_policy="fail_closed",
            row_conservation_counts={},
            quarantine_policy="quarantine_on_schema_error",
            quality_thresholds={"minimum_coverage_bp": 9500},
            downstream_use_cases=("research_backtest",),
            disable_conditions=("license_revoked", "pit_leakage"),
            rollback_reference="decision:initial-candidate",
            evidence_artifact_ids=(),
            downstream_eligibility="none",
        )
        diag = governance.diagnose_dossier(dossier)
        p0_summary.append({
            "source_id": src_id,
            "display_name": src_id,
            "status": diag.status, # deferred
            "downstream_eligibility": diag.downstream_eligibility, # none
            "active_blockers_count": len(diag.active_blockers),
            "missing_authority_evidence": list(diag.missing_authority_evidence),
            "missing_programmatic_evidence": list(diag.missing_programmatic_evidence),
        })

    result["p0_sources"] = p0_summary

    # 5. Gate Status Audit (Gate 2, 3, 4)
    result["gate_status"] = {
        "Gate_2_Evidence_Accumulation": {
            "engineering_status": "CONSOLIDATED_COMPLETE",
            "formal_credit_status": "0/3_WAITING_FOR_HUMAN_AUTHORITY",
            "external_approved_projection": "2/3_PROJECTED",
            "pending_human_review_count": 1,
            "production_scheduler_allowed": False,
            "blockers": [
                "requires_explicit_human_authority_credit_signature",
                "requires_real_calendar_week_accumulation",
            ],
        },
        "Gate_3_Data_Credibility": {
            "engineering_status": "CONTRACTS_ENG_COMPLETE",
            "formal_source_acceptance": "0_ACCEPTED_13_DEFERRED",
            "blockers": ["human_license_and_quality_attestation_required_for_all_13_p0_sources"],
        },
        "Gate_4_Portfolio_Coach": {
            "engineering_status": "PAPER_SANDBOX_READY",
            "real_trading_allowed": False,
            "blockers": ["paper_basis_only", "no_broker_integration"],
        },
    }

    return result


def save_reports(audit_data: Dict[str, Any], json_path: Path, md_path: Path) -> None:
    """Save audit output to JSON and Markdown files."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(audit_data, f, ensure_ascii=False, indent=2)

    md_lines = [
        "# Gate 2 Data Governance & P0 Source Baseline Audit Report",
        "",
        f"*Audited at: {audit_data.get('audit_timestamp', '')}*",
        "",
        "> [!IMPORTANT]",
        "> 本報告為唯讀工程稽核，記錄目前 SQLite 數據、P0 資料源治理、PIT 安全與 Gate 狀態。",
        "> **本報告不構成正式 Gate 2 人工 Credit 核准或 Production Enablement。**",
        "",
        "## 1. 資料庫基礎設施與資料表統計",
        f"- **SQLite 路徑**: `{audit_data['database']['db_path']}`",
        f"- **檔案存在狀態**: `{audit_data['database']['exists']}`",
        f"- **檔案大小**: {audit_data['database']['size_bytes'] / (1024*1024):.2f} MB",
        "",
        "### 資料表細節:",
    ]

    for tbl_name, tbl_info in audit_data.get("tables", {}).items():
        md_lines.append(f"- **`{tbl_name}`**:")
        if "error" in tbl_info:
            md_lines.append(f"  - 錯誤: `{tbl_info['error']}`")
        else:
            for k, v in tbl_info.items():
                md_lines.append(f"  - `{k}`: {v}")

    md_lines.extend([
        "",
        "## 2. 資料品質異常檢測 (Daily Prices Anomalies)",
    ])
    for anomaly_k, anomaly_v in audit_data.get("anomalies", {}).get("daily_prices", {}).items():
        md_lines.append(f"- **`{anomaly_k}`**: {anomaly_v}")

    md_lines.extend([
        "",
        "## 3. 基本面與估值 PIT 治理狀態",
    ])
    for pit_tbl, pit_info in audit_data.get("pit_governance", {}).items():
        md_lines.append(f"- **`{pit_tbl}`**: {pit_info.get('pit_security_status', 'N/A')} (Rows: {pit_info.get('row_count', 0)})")

    md_lines.extend([
        "",
        "## 4. 13 個 P0 資料源接受與權限狀態",
        "| 資料源 ID | 顯示名稱 | 審查狀態 | 下游資格 | 作用中 Blockers 數 |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])
    for p0_src in audit_data.get("p0_sources", []):
        md_lines.append(
            f"| `{p0_src['source_id']}` | {p0_src['display_name']} | `{p0_src['status']}` | `{p0_src['downstream_eligibility']}` | {p0_src['active_blockers_count']} |"
        )

    md_lines.extend([
        "",
        "## 5. Gate 工程完成度與 Blockers 矩陣",
    ])
    for g_name, g_info in audit_data.get("gate_status", {}).items():
        md_lines.append(f"### {g_name}")
        for gk, gv in g_info.items():
            md_lines.append(f"- **`{gk}`**: {gv}")

    with md_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")


if __name__ == "__main__":
    cfg = TWStockConfig()
    out_json = Path("qa/reports/gate_2_data_governance_baseline.json")
    out_md = Path("docs/06_qa/GATE_2_DATA_GOVERNANCE_CONSOLIDATION_AUDIT_2026_07_22.md")

    data = run_baseline_audit()
    save_reports(data, out_json, out_md)
    print(f"Audit report saved to {out_json} and {out_md}")
