# Gate 2–7 Engineering Control Center

> 狀態：純工程 closeout 已完成（35/35）；外部人工、時間、授權、evidence maturity 與正式接受項目仍維持待驗證，不會被工程完成狀態覆蓋。

> 15 capability、canonical lineage verifier 與 operations handoff 見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本控制中心仍是外部 Gate hub。

## Forward Clock current projection（2026-08-04）

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `DEV-86-mops-numeric-pit-bounded-coverage-expansion-20260805` | DEV-85 的 31 個候選保持有效；本批新嘗試 1233、1234、1235、1236、1256 五個 2025-Q1 上市身份，4/5 取得並通過 immutable raw/source/candidate/PIT lineage 驗證；累計 `candidate_count=35`、`matching_decision_row_count=4,037`、`eligible_rows=1,540`、`denominator=179,271`、`coverage=85 bp`、`gap=7,915 bp`；aggregate hash=`sha256:d8a6354933d99d6d8cfccd9f399164685e3b0414b6188d6256a5497dde3ace1c` | 1256 MOPS numeric request timeout，未產生 candidate bundle，未補值；DEV-84 的四個 timeout／DNS diagnostics 仍保留且未重跑；coverage 仍遠低於固定 8,000 bp，且 license、quality/PIT、具名 reviewer 與 applying registry revision 仍缺；`downstream_eligibility=none`、`formal_acceptance_applied=false`、`materialization_ready=false` | 保留四個新 candidate hashes、1256 failure diagnostics 與 cumulative aggregate；不把 research candidate materialize 或送入正式 DB／feature／fit／training；下一批只選新的未嘗試身份或新的可驗證官方 artifact，仍不得 promotion |
| Formal evidence | `rule_only_20260805_snapshot_missing` | `holdout_id=formal-rule-only-20260805-r1` 與 Rule-only source whitelist 仍有效；該 lane 尚無可引用的 decision-time `manual_observed` artifact | 本次 snapshot count=`0`；outcome revision count=`0`；matured denominator/formal credit/consumption increment=`0`；missing=`decision-time Rule-only manual_observed artifact`；degraded/capture failure=`no genuine observed artifact supplied`。固定 timestamp、source hash 或 score 組裝的 TEMP JSON 不計入 Formal evidence | 等待下一個有 owner 決議且 registry 尚未 consumption 的真實 decision-time artifact；不得回填、重綁或將同日 invocation 換算 elapsed day／credit |

截至本次 **2026-08-04** projection refresh，`DEV-86-mops-numeric-pit-bounded-coverage-expansion-20260805` 完成一個可獨立驗證的 research-only numeric PIT acquisition 增量；DEV-79 至 DEV-85 的工程安全約束仍全部適用：
1. **Bounded numeric acquisition** 新嘗試 1233、1234、1235、1236、1256；4/5 通過 official MOPS numeric／listing raw hash 與 PIT lineage 驗證，1256 timeout fail-closed，沒有猜測或補值。
2. **Aggregate coverage increased but remains blocked** 35 個 immutable candidates 聚合為 1,540 個 PIT-eligible rows、85 bp coverage；固定 8,000 bp 門檻仍未達成，未建立 feature materialization。
3. **Research-only boundary** 新增 raw/source/candidate/run manifest/aggregate 均位於 TEMP，`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`downstream_eligibility=none`。
4. **No applying acceptance** Owner bounded acquisition authorization 不轉換成 source acceptance；license、quality/PIT、coverage、具名 reviewer 與 registry applying revision 仍待補齊。
5. **Aggregate contract** 強制 source identity、canonical hash、candidate hash、coverage count conservation 與固定 8,000 bp policy；不接受呼叫端自報 coverage。
6. **Materialization gate** 必須同時具備合約有效 aggregate、具名 owner/reviewer dossier 與 append-only decision registry 的 applying revision；revision、evidence、timestamp、rollback 與 use case 不一致即拒絕。
7. **TEMP containment** 驗證 run_id 與 candidate output 皆在 development root，aggregate/readiness package 以 staging + atomic rename 發布。
8. **Foreground resume** 僅在既有 candidate hash 與 manifest 預期 hash 完全相同時 skip；缺 hash 或衝突均在 fetch 前 fail，revision 另行處理。
9. **Overlay lineage** 只接受 aggregate 已列出的 candidate hash，並按 decision date 選取最新適用 available date；formal／production flag 固定關閉。
10. **Availability separation** `mops.ezsearch.statement_publication` 只作受治理 availability sidecar；本次沒有成功 row，不能替代 numeric source、不能替代 t57 listing lineage，也不能授予 source acceptance。

以上工程 hardening 不等於 coverage 達標、不等於來源方授權／License 核准、更不等於 Formal credit。Owner 已授權 bounded research acquisition，但 P0/P13 的逐來源 applying source acceptance 仍等待可引用 license、quality/PIT、coverage、rollback 與具名 reviewer evidence；Formal lane 仍缺真實 decision-time Rule-only `manual_observed` artifact，本次 snapshot、elapsed formal day、outcome revision、matured denominator、formal credit 與 consumption increments 均為 0。


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
