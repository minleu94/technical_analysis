# Gate 2–7 Engineering Control Center

> 狀態：純工程 closeout 已完成（35/35）；外部人工、時間、授權、evidence maturity 與正式接受項目仍維持待驗證，不會被工程完成狀態覆蓋。

> 15 capability、canonical lineage verifier 與 operations handoff 見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本控制中心仍是外部 Gate hub。

## Forward Clock current projection（2026-07-27）

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `week2_cadence_reconciled_no_new_research_artifact` | Dataset `terra-development-v0:terra-v0-canonical-2025-dev-20260714` 與 sanitized Research Console projection SHA-256 `06BED1ABF3222EA1CA35DF8A25EDB8950025FA2314B4493A1AAEFEB18CA3614E` 均未變；P0 source evidence readiness CLI／文件 hardening 已由本次 invocation 前的 commits `ed5e4e1`、`266a90a` 完成 | 本次沒有新的 owner/reviewer revision、自然成熟 outcome、MOPS 季報 artifact、官方 probe evidence 或獨立 research artifact；未重跑 P0 audit/probe、Phase 3C apply、來源連線或任何資料寫入 | 等待真實 MOPS artifact、具名 owner/reviewer revision、bounded official probe evidence 或自然成熟 outcome；輸入未變時不得重做既有工程 |
| Formal evidence | `formal_week2_closed_zero_credit_source_review_pending` | `HoldoutConsumptionRegistry.jsonl` v2 binding（owner=`archi`；formal trading session=`2026-07-21`；SHA-256 `9B606C35438B5153DBE2968E4E1A96CBF8694D39AC78865F61C6C512781DB00B`）；Fubon owner decision `decision:fubon.marketdata:20260721-r1` 仍為 `deferred`／eligibility=`none`；TEMP shadow snapshot `snapshot:2330:20260721:6bec1c3d03ebae5e`；Formal Week 2 why-not revision `formal-week-2-20260726-r1` | 本次 snapshot count=`0`；既有 shadow `manual_observed` count=`1`；outcome revision count=`0`；matured denominator increment=`0`；formal credit increment=`0`；missing=`new decision-time manual_observed artifact`、`accepted Fubon source decision`；degraded=`first_observed_only`、`official publication timestamp missing`、`no documented full-delivery indicator`；capture failure=`none in this invocation` | 維持 Rule-only `DEFER`；不得把 shadow snapshot、approved weekly projection、invocation 或 pending outcome 換算為 observed day、holdout consumption、denominator 或 formal credit |

截至本次 **2026-07-27** projection refresh，Formal Week 2（2026-07-20 至 2026-07-26）已自然結束，故 External Validation Register append 一次 `formal-week-2-20260726-r1` why-not revision；這只是自然週 close 記錄，不是 observed day 或 formal credit。週內唯一 decision-time artifact 仍是 2026-07-21 的 TEMP/shadow `DEFER` snapshot（`snapshot:2330:20260721:6bec1c3d03ebae5e`）；read-only preflight 驗證 owner decision、binding 與 snapshot 結構有效，但因 Fubon source decision `decision:fubon.marketdata:20260721-r1` 維持 `deferred`、eligibility=`none`，固定回報 `fubon_source_not_accepted_for_formal_clock`，故 `formal_readiness=false`、formal credit snapshot count=`0`。其 dossier canonical content hash `sha256:8275ef80b6a409d3da4f9372569246abe0d28cabc60d322634c5d9a639715a60` 與 serialized file SHA-256 `3b7b2e925ff2ae3a6b6952ea4c68fce9d39c4ff375d1cacc7cd54cee58da8882` 均未變；既有 sidecar 仍只有 1 筆 shadow snapshot、0 筆 outcome revision。本次未建立 snapshot、未宣稱 holdout consumption、未重跑 P0/Phase 3C、未寫入任何 DB；2026 年 7 月尚未自然結束，故未新增月度 Gate Review。

操作載體為 Codex App automation `terra-forward-clock-12`（顯示名稱 `Terra Continuous Development／Forward Clock`），狀態 `ACTIVE`，每日本機時間 23:30 執行且無截止日。每次 invocation 最多推進一個由 automation memory 去重的 research-only Development increment；同日可多次手動執行並從既有游標續跑，但 invocation count 不得換算 elapsed days、Formal observed snapshots、週期或 forward credit。若沒有新的合格 increment，必須記錄 `no_op`，不得捏造進度。2026-10-05 只保留為第 12 週 formal readiness checkpoint，checkpoint 後兩條 clock 仍按相同邊界持續。這只是一個 Codex local automation，不是 repository scheduler、Windows Task Scheduler、background trading job 或正式 ingestion 排程。

安全旗標維持 `formal_oos_allowed=false`、`production_blend_alpha_bp=0` 與 Rule-only formal path；本次未 training、retraining、promotion、unblind 或 production blend。

## Agent 接手入口

1. 先讀 [Pure Engineering Closeout](GATE_2_TO_7_PURE_ENGINEERING_CLOSEOUT_2026_07_12.md)，確認已完成工程範圍與禁止重做事項。
2. 再讀 [External Validation Register](GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)，選擇一個尚未完成的 item，依 owner、最早驗證日、required artifacts 與 completion rule 執行。
3. 若 item 類型是 `ml_revalidation`，必須同時遵循 [Gate 7 ML Shadow Engineering](GATE_7_ML_SHADOW_ENGINEERING.md)，不得自動 retrain、promotion 或取代 rule signal。
4. 完成驗證後以 registry CLI 新增 revision，不覆寫既有歷史；工程完成不等於 formal product approval。

控制中心使用 append-only gate revisions 持續標註下列類別：

- `human_input`：需要人工補件或輸入。
- `human_approval`：需要 owner/reviewer 正式決議。
- `waiting_for_time`：需要真實日曆或交易日經過。
- `data_license`：需要資料授權與使用條款審查。
- `evidence_maturity`：需要 forward outcomes 或週期性 evidence 成熟。
- `ml_revalidation`：需要新資料重跑 ML shadow validation。

每個 item 必須記錄 owner、最早驗證日、progress bp、required artifacts、validation commands、completion rules、prohibited actions 與 notes。更新時新增 revision，不覆寫歷史；`complete` 必須有 10,000 bp progress 與 completion evidence。

## ML 更新與重驗

`scripts/build_ml_revalidation_runbook.py` 可依 new matured evidence、source/schema change、major drift 或 scheduled review 產生十步 runbook：freeze dataset、available-date validation、purged walk-forward、challenger training、OOF calibration、shadow prediction、drift、champion comparison、review package、shadow boundary。Runbook 可轉為 `ml_revalidation` gate revision，且固定禁止 auto retrain/promotion、rule signal replacement 與 trading advice。

## Closeout verifier

`scripts/verify_gate_2_to_7_closeout.py --output <json>` 逐項檢查必要 artifact 與獨立 commit subject，輸出 `engineering_package_status`；人工、時間、授權與 ML 重驗狀態另列為 `external_validation_status`。Verifier 固定 `formal_product_closeout=false`，工程完整不會被解讀成正式產品 Gate 核准。

## Workbench read-only projection

`EngineeringClosureDashboardService` 把 closeout report 與最新 gate revisions 投影成唯讀 DTO，顯示 package/external 狀態、category/status counts、owner、最早驗證日、progress、next command、artifacts、completion rules 與 prohibited actions。未完成 gate 可轉成既有 `WorkbenchActionItem`，固定 `write_intent=false`，只導向 Evidence Review，不提供更新或 apply 路徑。

## Registry CLI

使用下列命令維護控制中心；更新既有 item 時建立 revision+1 的新 JSON，不得覆寫舊 revision：

```powershell
.\.venv\Scripts\python.exe scripts\manage_engineering_gate_registry.py --db <control.sqlite> append --input <gate-revision.json>
.\.venv\Scripts\python.exe scripts\manage_engineering_gate_registry.py --db <control.sqlite> list-latest
.\.venv\Scripts\python.exe scripts\manage_engineering_gate_registry.py --db <control.sqlite> history --item-id <item-id>
```
