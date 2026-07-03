# V1.3 Evidence Operations & Manual Lifecycle 設計

## 目標

把 Post-V1 evidence layer 從「可檢查」推進到「每週可覆盤、可追蹤 action item、可形成人工 lifecycle 審核包」。

V1.3 不啟用 production scheduler，不自動 promote / demote / retire，不改策略權重、回測績效、portfolio position 或任何交易行為。

## 範圍

### Scope In

- Evidence Operations weekly review service。
- Manual approval package：彙總 scheduler readiness、blocking gaps、manual checks，且固定 `production_scheduler_allowed=false`。
- Decision Quality review / open item / action item 摘要。
- Signal Decay demote / retire candidate 人工審核清單。
- Read-only CLI 輸出 JSON / Markdown 週報。
- QA checklist 與 Manual / Snapshot / Roadmap / Architecture / Index 收尾同步。

### Scope Out

- production write-mode scheduler。
- Windows Task Scheduler production confirm task。
- 自動 lifecycle action。
- 自動交易、portfolio mutation、strategy version deletion。
- 新增策略、推薦或績效計算。

## 架構

新增 `EvidenceOperationsService` 位於 `app_module/` application boundary。它只讀既有 service / repository：

- `evaluate_evidence_scheduler_readiness()`
- `DecisionQualityService`
- `SignalDecayService`

輸出 DTO 位於 `app_module/evidence_operations_dtos.py`，所有欄位都能 JSON serialization。CLI `scripts/build_evidence_operations_weekly_review.py` 預設只讀，輸出週報，不寫 DB；Markdown 輸出只寫使用者指定的報告檔。

## 安全邊界

- `production_scheduler_allowed` 永遠由 V1.3 weekly package 顯示為 `false`。
- Signal Decay candidate 只輸出 `apply_action=false` 的人工審核清單。
- 樣本不足時 status 必須是 `coverage_only`，next action 只能要求累積 evidence，不能輸出策略結論。
- Decision Quality score 是流程 evidence，不是投資能力或責備分數。

## Checkpoints

1. Manual approval package / weekly evidence review service + CLI。
2. Signal Decay / Decision Quality action item loop：把 open review item 轉成可追蹤 action item，仍不套用 lifecycle。
3. QA checklist 與權威文件同步：Manual、Snapshot、6M Roadmap、Version Roadmap、Architecture、Index。

## 驗收

- Focused tests 覆蓋 weekly package、coverage-only 狀態與 CLI JSON。
- action item loop 有 append-only / no-action regression。
- 文件明確揭露 production scheduler 未啟用與 evidence 不等於 alpha。

