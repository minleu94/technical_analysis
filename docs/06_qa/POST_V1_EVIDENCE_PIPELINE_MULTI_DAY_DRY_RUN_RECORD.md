# Post-V1 Evidence Pipeline Multi-day Dry-run Record

## Purpose

這份紀錄用於正式 scheduler 前的穩定性觀察。它不代表 production scheduler 已啟用，也不代表任何 evidence dashboard 能證明策略有效。

使用方式：

1. 每個觀察日先完成資料更新或確認資料 freshness。
2. 執行 source coverage inspection。
3. 執行 manual evidence pipeline dry-run。
4. 在 working-copy DB 執行 confirm smoke。
5. 開啟 Research Lab `Evidence Review` 做人工 dashboard review。
6. 將結果填入下表。

## Required Commands

範例命令，日期與 DB path 依當日 QA 調整：

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --dry-run --json-output
.\.venv\Scripts\python.exe scripts\run_evidence_pipeline.py --decision-date 2026-06-30 --dry-run --report-output output\evidence_pipeline\reports\evidence_pipeline_2026-06-30.md
.\.venv\Scripts\python.exe scripts\smoke_evidence_pipeline_working_copy.py --source-db-path <source-db> --working-copy-db-path <working-copy-db> --decision-date 2026-06-30 --repeat 2 --json-output
.\.venv\Scripts\python.exe scripts\evaluate_evidence_scheduler_readiness.py --db-path <working-copy-db> --decision-date 2026-06-30 --json-output
```

## Record Fields

| Date | Data update status | Source coverage status | Dry-run pipeline status | Working-copy confirm smoke status | Events seen | Events inserted in working copy | Outcomes created in working copy | Summary groups | Warnings count | Blocking gaps | Dashboard review completed | Human reviewer notes | Decision |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|
| 2026-07-02 | passed | degraded | passed | N/A | 7 | 0 | 0 | 0 | 23 | decision_desk_snapshot_missing; why_not_exclusion_payload_missing; liquidity_gate_payload_missing | N/A | Windows Task Scheduler 05:00 / 05:15 manual trigger 成功，Last Result = 0；dry-run 為 read-only，confirm = false，未寫 production evidence DB。 | continue dry-run |
| YYYY-MM-DD |  |  |  |  |  |  |  |  |  |  |  |  | continue dry-run / fix gaps / approve next stage |
| YYYY-MM-DD |  |  |  |  |  |  |  |  |  |  |  |  | continue dry-run / fix gaps / approve next stage |
| YYYY-MM-DD |  |  |  |  |  |  |  |  |  |  |  |  | continue dry-run / fix gaps / approve next stage |
| YYYY-MM-DD |  |  |  |  |  |  |  |  |  |  |  |  | continue dry-run / fix gaps / approve next stage |
| YYYY-MM-DD |  |  |  |  |  |  |  |  |  |  |  |  | continue dry-run / fix gaps / approve next stage |

## Decision Values

- `continue dry-run`：沒有 blocking gap，但尚未累積足夠觀察日。
- `fix gaps`：source coverage、pipeline、working-copy smoke 或 dashboard review 有 blocking gap。
- `approve next stage`：只代表可進入 production scheduler 設計 / 實作審查，不代表可直接啟用 production scheduler。

## Stability Criteria Before Next Stage

進入 production scheduler implementation 前，至少需要：

- 3-5 個交易日 dry-run record。
- 每日 source coverage 無未解 blocking gap。
- working-copy confirm smoke 可重複通過且 idempotent。
- Dashboard review 已完成且無 read-only / boundary issue。
- diagnostics report 已人工確認。
- backup / rollback / recovery path 已在 checklist 中確認。

## Boundary

這份紀錄是正式 scheduler 前的穩定性觀察，不代表 production scheduler 已啟用。任何 production scheduler 未來仍必須先 dry-run，再 confirm；production confirm 需要 backup、rollback、diagnostics 與 explicit human approval。
