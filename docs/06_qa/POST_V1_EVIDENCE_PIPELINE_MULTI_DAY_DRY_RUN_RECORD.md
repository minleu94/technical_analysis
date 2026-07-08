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

2026-07-08 起，V2 closeout 可接受「修正後歷史觀察日」：若當日或指定觀察日已重新產出可追溯 dry-run report / scheduled `latest_status.json`，且 `dry_run=true`、`writes_evidence_db=false`、source coverage / pipeline blocking gaps 皆為空，可先作為 read-only closeout 觀察證據登記。此類紀錄必須在 notes 中標示 report / latest_status 來源；它不代表正式 evidence DB 已 confirm，也不代表 production scheduler approval。

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
| 2026-07-07 | passed | ready / no blocking gaps | passed | passed, repeat=2, idempotent | 933 scheduled dry-run / 1130 working-copy | 1130 | 4520 | 9 | 1865 scheduled dry-run | none | completed by human UI review | Data freshness passed with latest data 20260707; Evidence Review scheduler status showed evidence dry-run passed for decision date 2026-07-07. Safety boundary remained read-only: dry_run=true, confirm=false/unknown in UI, writes_evidence_db=false, production write risk=false, and no auto-trading or lifecycle action was observed. Scheduled dry-run report had blocking_gaps=[] and readiness_after=ready_for_manual_confirm. The scheduled recommendation_snapshot latest_status file was still missing, but the reviewer manually ran a recommendation snapshot/result afterward and reviewed it as acceptable: result_id=rec_20260707_113744, created_at=2026-07-07T11:37:44, recommendations=4, excluded_candidates=196, exclusion_quality=observed, exclusion_warnings=screening_matrix_persisted_v1. This is recorded as a manually resolved observation residual for the day; it does not make the scheduled latest_status healthy, and production scheduler remains disabled. | continue dry-run |
| 2026-07-08 | passed | ready / no blocking gaps | passed | N/A (scheduled dry-run closeout only) | 1130 | 0 | 0 | 0 | 1863 scheduled dry-run | none | read-only report and latest_status reviewed | Corrected historical observation accepted for V2 closeout evidence: `D:\Min\Python\Project\FA_Data\output\scheduled\evidence_pipeline_dry_run\latest_status.json` and report `reports\20260708_evidence_pipeline_dry_run.md` show decision_date=2026-07-08, dry_run=true, writes_evidence_db=false, source_coverage_blocking_gaps=[], pipeline_blocking_gaps=[], scheduler_readiness_after=ready_for_manual_confirm. Recommendation snapshot task was re-run and Task Scheduler Last Result was verified as 0 at 2026-07-08 13:56; result_id=scheduled_rec_20260708_135603, writes_evidence_db=false. This does not write formal evidence DB and does not approve production scheduler. | continue dry-run |
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
