# Gate 2–7 Engineering Control Center

> 狀態：純工程 closeout 已完成（35/35）；外部人工、時間、授權、evidence maturity 與正式接受項目仍維持待驗證，不會被工程完成狀態覆蓋。

> 15 capability、canonical lineage verifier 與 operations handoff 見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本控制中心仍是外部 Gate hub。

## Forward Clock current projection（2026-08-04）

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `DEV-98-datagov-history-page-client-route-discovery-20260805` | 由官方 history page 直接引用的 client bundle 與兩個 route component 執行三個 bounded read-only GET，均 HTTP `200`：主 bundle 373,641 bytes、SHA=`sha256:187e859c60a8aa5265a089f5e535b1fdb0428433aeaa7a439e33008106bc1d92`；history page component 9,855 bytes、SHA=`sha256:23d8bf2ea11c936d7b2278ee76a5f0bf3e278f370427d3ec071674b141c06a6c`；history detail component 79,544 bytes、SHA=`sha256:a2a5f54fd90411010b29d2d82a92d84ed8b4c3c6e0a3856d4ccf51b1272615fa`。程式明確宣告 `/datasets/history/:id`，history page 使用 `status=history`、日期／機關 filters、`unpubdate.date_desc`，並從直接 import 的 `C_Q17jct.js` 呼叫 history API；本 increment 尚未取得該 module 或 API response，沒有 dataset-specific record、numeric payload 或 PIT lineage；result SHA=`sha256:715f546b727547a54800e89b16df27c8dda793709953b6c8d078e08daf1d8c1f`、manifest SHA=`sha256:b1836f44ac88b1c482c71e9e729bde8c181a01d0a8fbb0db87a64bfb53bf0464`；未建立 candidate，aggregate 維持 `candidate_count=47`、`matching_decision_row_count=5,363`、`eligible_rows=1,987`、`denominator=179,271`、`coverage=110 bp`、`gap=7,890 bp` | 這是 route-discovery evidence，不是 PIT evidence：沒有 API response、歷史 bytes、announcement／available_at、revision 或 correction lineage；不能把 route shape、目前 CSV 或日期欄位當作 2025-Q1 可得資料。coverage、license／quality／rollback 與具名 reviewer acceptance 仍缺失，`downstream_eligibility=none`、`formal_acceptance_applied=false`、`materialization_ready=false` | 保留 TEMP bundle/component/result/manifest；不下載或 materialize 未驗證 numeric payload、不補值、不建立 candidate、不寫正式 DB／feature／fit／training；下一步只在新 preflight 後抓取直接 import 的 `C_Q17jct.js`，再依其明確 route 決定是否有可引用 history response，仍不得 promotion |
| Formal evidence | `rule_only_20260805_snapshot_missing` | `holdout_id=formal-rule-only-20260805-r1` 與 Rule-only source whitelist 仍有效；該 lane 尚無可引用的 decision-time `manual_observed` artifact | 本次 snapshot count=`0`；outcome revision count=`0`；matured denominator/formal credit/consumption increment=`0`；missing=`decision-time Rule-only manual_observed artifact`；degraded/capture failure=`no genuine observed artifact supplied`。固定 timestamp、source hash 或 score 組裝的 TEMP JSON 不計入 Formal evidence | 等待下一個有 owner 決議且 registry 尚未 consumption 的真實 decision-time artifact；不得回填、重綁或將同日 invocation 換算 elapsed day／credit |

截至本次 **2026-08-04** projection refresh，`DEV-98-datagov-history-page-client-route-discovery-20260805` 完成一個可獨立驗證的 research-only official route-discovery capability probe；DEV-79 至 DEV-97 的工程安全約束仍全部適用：
1. **Bounded numeric acquisition** 新嘗試 1240、1259、1264、1268、1336；0/5 產生 candidate bundle，timeout、DNS 與 numeric response identity mismatch 均 fail-closed，沒有猜測或補值。
2. **Aggregate coverage remains blocked** 既有 47 個 immutable candidates 維持 1,987 個 PIT-eligible rows、110 bp coverage；固定 8,000 bp 門檻仍未達成，未建立 feature materialization。
3. **Research-only boundary** 新增 raw/source/candidate/run manifest/aggregate 均位於 TEMP，`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`downstream_eligibility=none`。
4. **No applying acceptance** Owner bounded acquisition authorization 不轉換成 source acceptance；license、quality/PIT、coverage、具名 reviewer 與 registry applying revision 仍待補齊。
5. **Aggregate contract** 強制 source identity、canonical hash、candidate hash、coverage count conservation 與固定 8,000 bp policy；不接受呼叫端自報 coverage。
6. **Materialization gate** 必須同時具備合約有效 aggregate、具名 owner/reviewer dossier 與 append-only decision registry 的 applying revision；revision、evidence、timestamp、rollback 與 use case 不一致即拒絕。
7. **TEMP containment** 驗證 run_id 與 candidate output 皆在 development root，aggregate/readiness package 以 staging + atomic rename 發布。
8. **Foreground resume** 僅在既有 candidate hash 與 manifest 預期 hash 完全相同時 skip；缺 hash 或衝突均在 fetch 前 fail，revision 另行處理。
9. **Overlay lineage** 只接受 aggregate 已列出的 candidate hash，並按 decision date 選取最新適用 available date；formal／production flag 固定關閉。
10. **Availability separation** `mops.ezsearch.statement_publication` 只作受治理 availability sidecar；本次沒有成功 row，不能替代 numeric source、不能替代 t57 listing lineage，也不能授予 source acceptance。
11. **Paid-source boundary** 官方 TWSE Data E-Shop 公開頁面只證明 S02-2 等歷史財報產品與訂閱條款存在；沒有取得授權檔案前，不得把產品目錄、價格或 sample 當作 2025-Q1 PIT numeric artifact，也不得自行購買、登入或推定公告／可得時間。
12. **Numeric-only boundary** FinMind `TaiwanStockFinancialStatements` 的 `date` 是期間日期，API row 沒有 announcement／available／revision／correction 欄位；這些 2025-Q1 rows 只能作 numeric-only research evidence，不能進 PIT candidate、正式 feature 或 Formal path。
13. **Official latest-only boundary** DEV-95 的 TWSE OpenAPI catalog 與 `mopsfin` CSV 端點雖帶有 `出表日期`、`年度`、`季別` 欄位，但本次兩個一般業端點只回傳 `ROC 115-Q2` 最新批次，金融業端點是空內容列，五個目標的 2025-Q1 match 為 0；`1150805` 不得被解讀成歷史 announcement／available date，也不能用最新批次或空列替代 PIT。
14. **Data.gov metadata-only boundary** DEV-96 的官方 dataset `94829` metadata/page 只提供目前單一 CSV 與更新／授權／品質欄位；dataset record `modify_history=[]`、`history_note=""`，通用 `/datasets/history` 連結不能自行視為該 dataset 的歷史版本或 2025-Q1 PIT。沒有 announcement／available_at、revision／correction 與歷史 bytes 前，不得補值、建立 candidate 或 materialize。
15. **Data.gov history-index boundary** DEV-97 的官方 `/datasets/history` response 只呈現通用日期／機關篩選頁並顯示 `No data`；本次 server-rendered response 沒有 dataset 94829、歷史 record 或 detail link。這不能推論未查詢的後端日期結果不存在，也不能當作 PIT evidence；沒有 dataset-specific bytes 與公告／可得／revision lineage 前，不得補值、建立 candidate 或 materialize。
16. **Data.gov client-route boundary** DEV-98 的官方程式碼雖直接宣告 `/datasets/history/:id` 並引用 `C_Q17jct.js` 作 history API module，但本次只取得 route components，沒有 API response 或 numeric/history artifact；route shape、`unpubdate` sort 與日期 filters 不得被解讀成 announcement／available lineage。

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
