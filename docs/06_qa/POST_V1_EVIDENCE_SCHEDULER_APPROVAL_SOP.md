# Post-V1 Evidence Scheduler Approval SOP

## Purpose

本 SOP 定義 Evidence Pipeline 從手動 dry-run 走向未來 production scheduler implementation 的人工核准路徑。現在不啟用 production scheduler、cron 或 production background job。例外是 V2.2 的 `baldr-v2-2-weekly-collection` Windows Task：它只將週期資料收集至 sidecar，結果只能是 `pending_human_review` 或 `collection_failed`；它不是人工 review、不寫 weekly history，也不改 `production_scheduler_allowed=false`。

## Stage 1：Manual Evidence Pipeline Run

目標：由人手動執行 pipeline dry-run，確認 source coverage、snapshot capture、event capture、outcome calculation、summary 與 diagnostics report 可被產出。

要求：

- 預設 `--dry-run`。
- 不寫 production DB。
- diagnostics report 必須人工閱讀。
- 有 blocking gap 時停止進入下一 stage。

## Stage 2：Multi-day Dry-run Record

目標：連續 3-5 個交易日建立 dry-run record，觀察資料 freshness、source coverage、warnings、blocking gaps 與 dashboard review。

紀錄位置：

- `docs/06_qa/POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md`

要求：

- 每日記錄 Data update status。
- 每日記錄 Dry-run pipeline status。
- 每日記錄 Dashboard review completed。
- 每日填入 decision：continue dry-run / fix gaps / approve next stage。

## Stage 3：Working-copy Confirm Smoke

目標：在 working-copy DB 驗證 confirm path、idempotency 與 diagnostics，不碰 production DB。

要求：

- source DB 與 working-copy DB 必須不同路徑。
- working-copy DB 不得是 production DB path。
- repeat 至少 2 次。
- source DB 應保持 read-only。
- confirm smoke 失敗時不得進入下一 stage。

## Stage 4：Dashboard Human Review

目標：由人打開 Research Lab `Evidence Review`，檢查四個 read-only dashboard。

使用 checklist：

- `docs/06_qa/POST_V1_EVIDENCE_REVIEW_UI_SMOKE_CHECKLIST_2026_07_12.md`

要求：

- Boundary banner 可見。
- Empty / degraded / insufficient sample states 清楚。
- 無買賣建議語言。
- 無自動 action button。
- 無寫入 DB 行為。

## Stage 5：Manual Approval Checklist

目標：人工確認 production scheduler 前置條件。

參考：

- `docs/06_qa/POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md`

要求：

- source coverage 完整。
- diagnostics report 無 blocking gap。
- backup path 已確認。
- rollback / recovery path 已確認。
- owner / reviewer 已記錄。
- explicit human approval 已記錄。
- `pending_human_review` sidecar record 不得當作 dashboard human review、manual approval 或 weekly history 的替代證據。

機器 gate 也必須讀到明確指定的 `evidence-production-scheduler-approval.v1` JSON；其中需包含具名 `owner`、`approval_id`、有時區且不晚於現在的 `approved_at`、有時區且尚未過期的 `expires_at`、`scope=evidence_capture_scheduler`、`production_scheduler_allowed=true`，以及 source coverage、dry-run、working-copy smoke、diagnostics、backup、rollback、recovery 七項 checks 全部為 `true`。`scripts/evaluate_evidence_scheduler_readiness.py --approval-artifact <PATH>` 只讀取並重驗這份 artifact；缺少、過期、未核准或格式錯誤時一律 fail-closed，不會因 source coverage 或 smoke 通過而自行放行。

## Stage 6：Production Scheduler Design

目標：只設計 production scheduler，不立即啟用。

設計必須包含：

- dry-run-first mode。
- confirm gate。
- backup / rollback / diagnostics。
- failure notification。
- idempotency policy。
- source DB / working-copy DB / production DB boundary。

## Stage 7：Production Scheduler Implementation Only After Explicit Human Approval

目標：只有在 Stage 1-6 通過且使用者明確批准後，才可實作 production scheduler。

硬性限制：

- scheduler 不得自動 lifecycle action。
- scheduler 不得自動交易。
- scheduler 不得改 portfolio position。
- scheduler 不得改 ScoringEngine 或推薦權重。
- scheduler 不得把 dashboard summary 包裝成買賣建議。
- scheduler 不得宣稱 alpha 或策略有效。
- weekly sidecar collection 若要停止或回復，只能停用或解除註冊 Windows task；禁止以自動 drop sidecar table 作為 rollback。

## Current Status

截至本 SOP 建立日：

- production scheduler 未啟用。
- 仍需人工 Evidence Review UI smoke。
- 仍需 multi-day dry-run record。
- readiness 不能視為 production-ready。
- `baldr-v2-2-weekly-collection` 只提供 pending-human-review collection，沒有改變上述 production scheduler gate。
