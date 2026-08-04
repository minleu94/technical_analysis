# Gate 2–7 Engineering Control Center

> 狀態：純工程 closeout 已完成（35/35）；外部人工、時間、授權、evidence maturity 與正式接受項目仍維持待驗證，不會被工程完成狀態覆蓋。

> 15 capability、canonical lineage verifier 與 operations handoff 見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本控制中心仍是外部 Gate hub。

## Forward Clock current projection（2026-08-04）

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `gemini_mops_numeric_pit_engineering_blockers_closed` | 程式化 `resolve_mops_numeric_pit_source_mapping` 對齊 `pit.quarterly_financials`；`build_mops_numeric_pit_aggregate` 確定性聚合 4 份既有 immutable candidates（`candidate_count=4`, `unique_identities=4`, `eligible_rows=174`, `denominator=179,271`, `coverage=9 bp`, `gap=7,991 bp`）；`build_mops_readiness_package` 自動匯出 non-applying readiness package；`acquire_mops_numeric_pit_batch` 前景受控 batch 工具；`check_mops_materialization_readiness` fail-closed 預檢 | 工程 blockers 已全部排除。但 readiness 仍為 `blocked`：`coverage_below_minimum`（`9 bp` vs 門檻 `8,000 bp`）、`missing_license_evidence`、`missing_owner_reviewer_decision`、`unauthorized_use_case`。`downstream_eligibility=none`、`formal_acceptance_applied=false`、`materialization_ready=false`。沒有 feature materialization、2026 fit、training 或 promotion | 等待具名 Source Owner / Reviewer 授權與 license 決議；在前景受控批次（`acquire_mops_numeric_pit_batch`）安全累積 8,000 bp 覆蓋率 |
| Formal evidence | `rule_only_20260729_snapshot_missing` | `holdout_id=formal-rule-only-20260729-r1` 與 4 個 Rule-only source whitelist 仍有效；2026-07-29 沒有可引用的 decision-time `manual_observed` artifact | snapshot count=`0`；既有 shadow `manual_observed` count=`1`；outcome revision count=`0`；matured denominator/formal credit increment=`0`；missing=`2026-07-29 decision-time Rule-only manual_observed artifact`；degraded=`none for the lane`；capture failure=`no genuine observed artifact supplied`。以固定 timestamp、固定 source hash 或固定 score 組裝的 TEMP JSON 僅是 synthetic fixture，已排除於 Formal evidence | 等待下一個具 owner 決議與未消費 registry session 的真實 decision-time artifact；不得回填、重綁或把同日 invocation 換算 credit |

截至本次 **2026-08-04** projection refresh，`GEMINI-MOPS-NUMERIC-PIT-ENGINEERING-BLOCKER-CLOSURE-V1` 任務已完整排除 MOPS numeric PIT／P0 source acceptance／research-only materialization 的所有工程 blocker：
1. **Source Identity Mapping Contract** 已程式化且 fail-closed，嚴格保護四層 source identity，現有 4 份 v1 candidates 相向相容。
2. **Multi-Candidate Aggregator & Lineage Validator** 已確定性產出 aggregate 報告（4 candidates, 174 eligible rows, 9 bp coverage, 7,991 bp gap）。
3. **P0 Source Acceptance Readiness Bridge** 已自動由 mapping contract 導出 `source_id = pit.quarterly_financials` 並產出 non-applying 診斷與 owner review template（缺 license 固定 `blocked`，`downstream_eligibility=none`）。
4. **Bounded Foreground Batch Acquisition Tooling** 已建立前景 bounded 批次工具（`--max-items` 必填，自動比對 candidate SHA-256 跳過重複，無背景排程）。
5. **Materialization Readiness Gate** 已建置 fail-closed 預檢，於當前真實 4 份 candidate 條件下明確拒絕 materialization（`materialization_ready = false`）。

四者嚴格區分：工程 blocker 閉環不等於 coverage 達標、不等於授權/License 核准、更不等於 Formal credit。Formal lane 仍缺 2026-07-29 真實 decision-time Rule-only `manual_observed` artifact；本次 invocation snapshot count、elapsed formal day、outcome revision、matured denominator、formal credit 與 consumption increments 均為 0。


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
