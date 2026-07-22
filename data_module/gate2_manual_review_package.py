"""Gate 2 Manual Review Package & Operational Governance Support.

Defines:
1. Gate 2 Readiness Checklist
2. Owner Manual Review Template Generator
3. Working-Copy Backup & Recovery Drill Runbook
4. Emergency Rollback Checklist
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class Gate2ReadinessStatus:
    projected_approved_count: int
    formal_credited_count: int
    pending_human_review_count: int
    next_natural_week: str
    missing_human_evidence: Tuple[str, ...]
    is_ready_for_human_gate: bool
    formal_credit_authorized: bool = False


class Gate2ManualReviewPackage:
    """Gate 2 工程包與運作指南。"""

    def evaluate_gate2_readiness(
        self,
        projected_approved_count: int,
        formal_credited_count: int,
        pending_human_review_count: int,
        next_natural_week: str,
        has_owner_signature: bool = False,
    ) -> Gate2ReadinessStatus:
        missing: List[str] = []

        if formal_credited_count < 3:
            missing.append("formal_credited_count_under_threshold_3")
        if not has_owner_signature:
            missing.append("missing_explicit_human_authority_credit_signature")
        if pending_human_review_count > 0:
            missing.append("unreviewed_weekly_evidence_records_pending")

        is_ready = len(missing) == 0

        return Gate2ReadinessStatus(
            projected_approved_count=projected_approved_count,
            formal_credited_count=formal_credited_count,
            pending_human_review_count=pending_human_review_count,
            next_natural_week=next_natural_week,
            missing_human_evidence=tuple(missing),
            is_ready_for_human_gate=is_ready,
            formal_credit_authorized=False,  # ALWAYS False until human owner signature
        )

    def generate_weekly_review_template(
        self,
        period_start: str,
        period_end: str,
        review_id: str,
        owner_role: str = "portfolio_manager",
    ) -> str:
        return f"""# Gate 2 週次證據人工審查紀錄表 (Weekly Review Form)

> **[靜態安全警示]** 此為人工審查紀錄表範本。填寫完成後僅儲存至專用 working-copy DB，**絕不自動寫入或合併正式 DB**。

## 1. 審查基本資訊
- **週次週期 (Period)**: {period_start} ~ {period_end}
- **審查識別碼 (Review ID)**: `{review_id}`
- **審查權責角色 (Owner Role)**: `{owner_role}`
- **目前正式 Credit 授權狀態**: `formal_credit_authorized=false`

## 2. 週次品質與現象檢核
- [ ] 本週市場價格與技術數據採集完整無缺行
- [ ] 本週無未隔離之 NULL 代碼或異常週末 OHLC
- [ ] 推薦清單與訊號無 Future Look-Ahead Bias
- [ ] 持倉警示與風險提示符合實際行情

## 3. 人工核准簽名欄
- **核准狀態 (Review Status)**: [ ] APPROVED  [ ] REJECTED  [ ] PENDING
- **人工審查者 (Reviewer Name)**: ___________________
- **簽署日期 (Date)**: ___________________
- **核准備註 (Notes)**: ___________________
"""

    def generate_backup_restore_runbook(self) -> str:
        return r"""# Gate 2 Working-Copy Backup & Recovery Drill Runbook

> **[作業原則]** 正式 DB (`twstock.db`) 為唯讀保護標的。所有週次演練與備份均針對專用 working-copy DB 執行。

## Step 1: 建立 Working-Copy DB 副本
```powershell
$SourceDB = "D:/Min/Python/Project/FA_Data/sqlite/twstock.db"
$WorkingDB = "D:/Min/Python/Project/FA_Data/sqlite/twstock_working_copy.db"
Copy-Item $SourceDB $WorkingDB -Force
```

## Step 2: 執行 Working-Copy DB Confirm Smoke
```powershell
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline_working_copy.py --confirm --db-path $WorkingDB
```

## Step 3: SQLite 完整性與 Checksum 驗證
```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; conn=sqlite3.connect('$WorkingDB'); print(conn.execute('PRAGMA quick_check;').fetchall())"
```

## Step 4: 回滾復原演練 (Rollback Drill)
若演練失敗，直接刪除 working-copy DB 並重新從唯讀正式 DB 複製：
```powershell
Remove-Item $WorkingDB -Force
Copy-Item $SourceDB $WorkingDB -Force
```
"""

    def generate_rollback_checklist(self) -> str:
        return """# Gate 2 Emergency Rollback Checklist

1. [ ] **隔離正式 DB**: 確認正式 DB (`DATA_ROOT/sqlite/twstock.db`) SHA-256 未受任何污染。
2. [ ] **停止排程工作**: 停用非正式週日 collection 或歷史 projection 工作。
3. [ ] **清除 Working-Copy 檔案**: 刪除 `twstock_working_copy.db` 及暫存 JSON 檔案。
4. [ ] **重置 UI Projection 變數**: 移除或重置 `WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH` 環境變數。
5. [ ] **執行 Healthcheck 重驗**: 執行 `python scripts/run_full_app_healthcheck.py` 確認系統回復純淨唯讀狀態。
"""
