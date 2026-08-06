# Gate 2–7 Engineering Control Center

> 狀態：純工程 closeout 已完成（35/35）；外部人工、時間、授權、evidence maturity 與正式接受項目仍維持待驗證，不會被工程完成狀態覆蓋。

> 15 capability、canonical lineage verifier 與 operations handoff 見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本控制中心仍是外部 Gate hub。

## Forward Clock current projection（2026-08-05）

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `DEV-113-weekly-custody-and-scheduled-diagnostics-hardening` | weekly evidence custody 改為 `pending_human_review`、sidecar schema v3 migration／readiness 排除 pending 已完成；scheduled dry-run 加入 deterministic clock、resolved root forwarding、natural-maturity/actionable warning 分流與 Decision Desk SQLite `mode=ro/query_only`；兩批 commit=`3568f853d7734d062677dddd74253e5b0b425437`、`7c7479ff6c4db7e41d4973a4f2c0d7bf05afb6e0`；target tests `51+44 passed`、mypy／py_compile／diff checks PASS | 無新正式資料、無 source acceptance、無 snapshot／registry／formal DB／training／promotion／unblind／blend；scheduled 只寫 status／sidecar，不代表 Gate credit | 只可把 owner 審核後的具名 `approved-weekly-history-projection` 視為週證據；Formal 仍等待 genuine current-session `manual_observed` artifact，禁止歷史回填、replay、fixture 或 invocation credit |
| Formal evidence | `rule_only_20260805_snapshot_missing` | owner-attested `holdout_id=formal-rule-only-20260805-r1` binding valid、Rule-only source whitelist 有效、formal session=`2026-08-05`；readiness result=`sha256:8366d828a62930b1f967fc0b007473157da87f09bb41e315d7d19eae8095b5d0` | 本次 snapshot count=`0`；outcome revision count=`0`；matured denominator/formal credit/consumption increment=`0`；missing=`manual_observed_snapshot_missing`；歷史 2026-07-29 artifact=`invalid`（`manual_observed_decision_output_lineage_missing`），不回填；degraded=`none`；capture failure=`no qualifying current-session artifact supplied` | 等待 owner 決議後該 session 真正保存、具 hash-addressed decision-output lineage 且 source whitelist 完全符合的 `manual_observed` artifact；不得回填、重綁或將同日 invocation 換算 elapsed day／credit |

截至本次 **2026-08-05** projection refresh，`DEV-102-datagov-history-target-detail-probe-20260805` 的 official target-detail capability probe 與 `DEV-105-ml-raw-publication-refresh-current-sqlite-20260805` 的 current SQLite TEMP raw PIT refresh 均已完成；DEV-79 至 DEV-101 的工程安全約束仍全部適用：
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
17. **Data.gov API-response boundary** DEV-99 依官方 module 的 exact `POST /api/front/dataset/simple-list` contract 取得一頁 generic history listing；`search_count=36,144` 與第一頁 10 rows 不等於 dataset 94829 的歷史版本。因 response charset/capture bytes 不一致，且沒有 dataset-specific numeric、announcement、available、revision 或 correction fields，本次不得建立 PIT candidate 或補值；下一次只能使用新 preflight、明確 dataset filter/detail route 與 wire-preserving capture。
18. **Data.gov targeted-filter boundary** DEV-100 以官方 metadata title 建立新的 `fulltext` filter，wire-preserving response 為 `search_count=0`；這是該 exact filter 的 negative capability result，不是全域歷史空集合，也不是 target 94829 的 PIT 證據。沒有 numeric、announcement、available、revision 或 correction lineage 前，不得補值、建立 candidate 或 materialize；下一次只能用新 filter/detail route 與同樣 wire-preserving 邊界。
19. **Data.gov short-token boundary** DEV-101 的 `資產負債表` token 回傳 4 筆與 target 無關的 history rows；fulltext 命中不是 dataset identity，`unpubdate` 不是 announcement/available time。沒有 target-specific numeric 與 lineage 前，不得補值、建立 candidate 或 materialize；下一步只能用新 preflight 的 nid-oriented/detail probe。
20. **Data.gov target-detail boundary** DEV-102 的 target detail route 只回傳 current metadata、64 欄位定義與一個 current CSV resource，`modify_history=[]` 且無 numeric rows；`pubdate`、metadata changed time、resource `last_update_time` 均不能替代 announcement/available/revision lineage。不得下載或把 current CSV 升格為 PIT；後續只能等待新可歸屬的歷史/version artifact 或授權 PIT export。
21. **ML raw PIT custody boundary** DEV-103 的既有 ML raw PIT publication 已完成唯讀 custody 驗證：142,535 rows／9 shards，兩份 52-feature formal-labelled raw dataset 與一份隔離的 32-feature research-shadow dataset 的 manifest、compressed/content hash、row/value/mask/schema 與 conservation checks 全部 PASS；formal rows 沒有 announcement／revision lineage，shadow 內 268 個 fundamental values 仍全部 research_shadow 且 formal_training_eligible=false，故沒有 numeric backfill、candidate 或 aggregate 變更。training adapter 仍為 `direct_training_input=false`，待 as-of join、causal portfolio state、matured labels、purged folds 與 per-decision staleness recomputation。TEMP result／manifest／self-check 已保留，未啟動 scheduler、network、DB write、materialization 或 training。

22. **ML raw source-drift boundary** DEV-104 的原始比較曾把 current SQLite file SHA 與 publication 的 logical `database_fingerprint` 混用；兩者不是同一 identity。以 exporter 同一公式重算 current logical fingerprint=`sha256:08ea4743b54e82da5a3d343cf73de9a15dafa5f76c1224933315ae55e2669160`，與既有 publication=`sha256:23ad4fb019ac76d1eca0ea36a6b33e4d7719e7530a9bab1187d565a332480665` 不同，原因是 eligibility hash／size 相同但 mtime 較新。這只表示需 refresh custody，不宣稱 value change；沒有回補正式 DB、沒有 candidate、沒有 materialize、沒有 scheduler rerun。
23. **ML raw publication refresh boundary** DEV-105 以 current SQLite、bounded 11 symbols／2024–2026 scope 在 TEMP 建立 `pit-1b53e73127a5246d3255ee95`，9 shards／186,710 raw rows，publication、dataset、compressed/content shard、row/value/mask/schema、source logical fingerprint、availability／lineage 與 training-adapter checks PASS；formal／shadow 仍分離，`direct_training_input=false`，沒有 numeric backfill、formal credit、candidate 或 aggregate mutation。
24. **ML raw delta／as-of assembly boundary** DEV-106 只比較 DEV-105 新舊 TEMP raw publication 並稽核 6,798 個 T-1 potential pairs、618 個 eligible decision dates、5 個 purged folds 與 h5／h10／h20／h60 matured labels；available_at／future-feature checks 均 PASS，但 sector membership、corporate-action custody、causal portfolio ledger sidecars 尚未由 owner/reviewer bound，且 `PortfolioMLDatasetAssembler` 未 invoked、`direct_training_input=false`。前一版 label 0 已標記為 PowerShell Unicode literal encoding correction；修正版 result／manifest／self-check 均 PASS。這不是 numeric backfill、formal training eligibility、source acceptance 或 materialization，不得寫正式 DB。
25. **ML sidecar custody／current-lineage boundary** DEV-107 證實 current official-market event publication 已有新 revision（current canonical `4fe0…`）而 causal／portfolio sidecar 仍綁定舊 canonical `40436…`；causal ledger／training `training_as_of` 停在 2026-07-30，sector membership 為 zero hash／0 rows，portfolio ledger absent 且只允許 cash-only fallback。scheduled shadow input、shadow lane 與 evidence collector 是 machine background，不能轉成 decision-time `manual_observed` 或 Formal credit；無 owner/reviewer/source-acceptance/applying revision 即不得重組、materialize 或訓練，不得寫正式 DB。
26. **Formal lane／observed snapshot custody boundary** DEV-108 驗證新 lane decision 與 v3 registry binding 可證明 `2026-08-05` 是決議後第一個未消費 session，但 binding 不等於 snapshot 或 Formal credit；current session 沒有 `manual_observed`，而唯一歷史 `2026-07-29` 檔案因缺 hash-addressed decision-output lineage 被 readiness validator 拒絕。不得用歷史檔、replay、fixture、scheduler sidecar、固定 timestamp／score 或 invocation 次數補成 observed day、denominator、outcome 或 credit；只有真正 current-session decision-time artifact 且 source whitelist／session 完全相符時才能進入後續人工審核。

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
