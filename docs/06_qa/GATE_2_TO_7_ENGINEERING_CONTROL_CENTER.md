# Gate 2–7 Engineering Control Center

> 狀態：純工程 closeout 已完成（35/35）；外部人工、時間、授權、evidence maturity 與正式接受項目仍維持待驗證，不會被工程完成狀態覆蓋。

> 15 capability、canonical lineage verifier 與 operations handoff 見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本控制中心仍是外部 Gate hub。

## Forward Clock current projection（2026-07-16）

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `development_observed_degraded` | Dataset `terra-development-v0:terra-v0-canonical-2025-dev-20260714`；Research run `sha256:36e57e0c370ce0f08eb625de0871ffa49699bfdb469272f4c5d7bacaf8d910c5`；projection SHA-256 `06BED1ABF3222EA1CA35DF8A25EDB8950025FA2314B4493A1AAEFEB18CA3614E`；DEV-13 harden staging CLI invalid as-of date diagnostic | fit rows=`179271`；evaluation rows=`0`；OOF samples=`53559`；`research_only_degraded` corporate-action coverage、formal attested Rule snapshot missing；不是 formal OOS／promotion／投資有效性證據 | UI 僅可由 `RESEARCH_CONSOLE_PROJECTION` 顯式指向 `C:\Temp\technical_analysis_development_output\research_runs\terra-v0-canonical-2025-dev-20260714\ResearchConsoleProjection.json`；2026 matured outcomes 僅 evaluation，不得 fit |
| Formal evidence | `capture_failed_deferred` | EV1 manual CLI 僅接受明確 `manual_observed` artifact，且只可寫 TEMP／shadow sidecar | snapshot count=`0`；missing=`manual_observed decision artifact`；degraded=`none`；capture failure=`no decision-time snapshot supplied` | 等真正 decision-time observed snapshot；禁止歷史回填、synthetic day、replay／fixture credit 與 pending denominator |

本日未建立 **Formal observed day**；snapshot count=`0`，missing=`manual_observed decision artifact`，degraded=`none`，capture failure=`no decision-time snapshot supplied`。Development artifacts 只從外部 development root 唯讀驗證，未掃描或寫入正式 market DB，也未啟用專案 scheduler。B 方案 owner 決議 artifact 已存在於 `C:\Temp\technical_analysis_development_output\governance\DevelopmentDataUsageDecision.jsonl`（file SHA-256 `88D853DE58791F2D8482FE2C8D61013E0556518D22C6F52ED168FE863AE14B7B`；effective `2026-07-14T05:07:25.0061485Z`），`new_holdout_start=2026-07-15`；2026-07-16 綁定前重新檢查仍未找到 `HoldoutConsumptionRegistry.jsonl`，因此不得宣稱 holdout 已綁定、已消費或 formal readiness 已成立。週報、人工 why-not 與月 Gate Review 僅在自然週／月到期時 append；第 12 週即使 eligible 也不得 unblind 或啟動 Task 6。

操作載體為 Codex App automation `terra-forward-clock-12`（顯示名稱 `Terra Continuous Development／Forward Clock`），狀態 `ACTIVE`，每日本機時間 23:30 執行且無截止日。每次 invocation 最多推進一個由 automation memory 去重的 research-only Development increment；同日可多次手動執行並從既有游標續跑，但 invocation count 不得換算 elapsed days、Formal observed snapshots、週期或 forward credit。若沒有新的合格 increment，必須記錄 `no_op`，不得捏造進度。2026-10-05 只保留為第 12 週 formal readiness checkpoint，checkpoint 後兩條 clock 仍按相同邊界持續。這只是一個 Codex local automation，不是 repository scheduler、Windows Task Scheduler、background trading job 或正式 ingestion 排程。

安全旗標維持 `formal_oos_allowed=false`、`production_blend_alpha_bp=0` 與 Rule-only formal path；本日未 training、retraining、promotion、unblind 或 production blend。

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
