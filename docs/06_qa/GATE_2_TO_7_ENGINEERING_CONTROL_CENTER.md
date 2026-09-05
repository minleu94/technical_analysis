# Gate 2–7 Engineering Control Center

> 狀態：純工程 closeout 已完成（35/35）；外部人工、時間、授權、evidence maturity 與正式接受項目仍維持待驗證，不會被工程完成狀態覆蓋。

> 15 capability、canonical lineage verifier 與 operations handoff 見 [V3.3 Engineering Closeout](V3_3_ENGINEERING_CLOSEOUT_2026_07_12.md)；本控制中心仍是外部 Gate hub。

## Current Forward Clock projection（2026-09-05）

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `DEV-144-week7-august-gate-current-projection-20260905 / documented_zero_credit_boundary` | 正式 weekly sidecar 以 SQLite URI `mode=ro` 重驗為 10 筆 append-only records，最新 `ewc_0033db6f63592542` 自然涵蓋 `2026-08-24..2026-08-30`，last trading date=`2026-08-28`、status=`pending_human_review`；sidecar hash=`sha256:A6A7746FE40F6CA4D3C00D4BCB4D6C706A39F8B370BE32973DE7E4F361A5B7AA`。既有具名 approved projection 維持 `3/3`、hash=`sha256:02eb67ff812c17f604c34f4eb30c1b87941596af6aa9ebaff6ec1d555b64b4d8`；本次只在自然週／月結束後補登 Week 7 why-not 與 August Gate Review | pending sidecar=`10`，全部仍需具名 owner／reviewer；pending 不進 approved weekly count、Formal snapshot、matured denominator、elapsed day 或 credit。8/28 prospective one-shot 維持已消耗、`0/3` formal publication 且不可重跑；本次未執行 collector、scheduler、producer、publisher 或 one-shot | 由具名 owner／reviewer 逐期審核 pending rows；只有另行產生可引用的 approved weekly projection 才能更新 weekly UI disclosure，且仍不得授予 Formal credit |
| Formal evidence | `formal-rule-only-20260807-r1 / zero_credit` | owner decision 與四筆 consumption-registry binding 維持有效且未消耗；formal session=`2026-08-07`，snapshot=`missing`，唯一 blocker=`manual_observed_snapshot_missing`，`formal_readiness=false`。Shadow evidence SQLite 仍只有 decision snapshot=`1`、outcome revision=`0`；Week 7 revision 與 August Gate Review 都只記錄 why-not，不是 decision-time Rule-only snapshot | 本次 snapshot count、outcome revision、matured denominator、Formal credit、consumption 與 elapsed-day increment 全部為 `0`；missing=`genuine decision-time Rule-only manual_observed artifact for 2026-08-07`；degraded=`none for the latest bound Rule-only lane`；capture failure=`no qualifying decision-time artifact supplied or found`。歷史 `manual_observed_20260729.json` 與 2026-08-27／28 prospective artifacts 都不重用、不回填 | 不重綁或消耗 2026-08-07，不把 pending weekly rows、approved UI disclosure、prospective clock、one-shot、staging／dry-run、development invocation、replay、fixture 或事後審核換算為 observed day。新 holdout 仍須先有可引用 owner 決議時間 artifact，且綁定前重新檢查 registry |

截至 **2026-09-05 14:32（Asia/Taipei）**，Formal Week 7（2026-08-24 至 2026-08-30）與 August 月界線均已自然結束，External Register 已各保留唯一 Week 1～7 revision，Project Snapshot 已補登單一 August Gate Review。Formal Week 8（2026-08-31 至 2026-09-06）仍在自然進行中，不得提前追加；weekly sidecar 仍只有 10 筆且全數 pending human review。本次文件補登不產生 Formal observed day 或 credit；安全旗標維持 `formal_oos_allowed=false`、`formal_evidence_credit_authorized=false`、`production_blend_alpha_bp=0`、Rule-only Formal path、`promotion_eligible=false`、`broker_order_allowed=false`。

## Prospective formal restart direction（2026-08-19）

Owner 已鎖定新的執行方向，完整決策見 [Prospective Formal Restart Direction](PROSPECTIVE_FORMAL_RESTART_DIRECTION_2026_08_19.md)：舊 `clock:prospective:20260819:v1` 只保留歷史追溯，不重建、不沿用、不回填；下一個長任務依官方 TWSE／TPEX 共同交易日與至少一個完整準備日建立新未來 clock，由 Codex 先提出唯一首選 Rule Champion，再以 TWSE `t187ap03_L`／TPEX `t187ap03_O` 建立 prospective first-seen 產業歸屬。Broker 固定關閉。

此方向已解除「尚未決定採哪條路」的需求 blocker，但沒有解除證據 Gate。唯一預定的 owner checkpoint 是：Codex 交付具完整設定與 hashes 的 Rule Champion proposal 後，由 owner 接受特定 Champion identity。Clock preflight、官方來源接線、三個 producers、tests、文件與 strict readiness 由 Codex 完成；自然成熟 shadow 日不能加速，promotion 簽章與非零 alpha 仍是日後獨立 owner gate。

本文件更新沒有建立 clock bytes、source acceptance、Rule snapshot、Portfolio transition、PIT sidecar、Formal OOS、shadow day、promotion credit、scheduler 或 broker 權限；安全旗標維持 `formal_oos_allowed=false`、production alpha 0、`broker_order_allowed=false`。

`clock:prospective:20260825:v1` 與 rejected v2 bytes 只保留 immutable 歷史追溯，不重建、不沿用、不回填。最新 successor 是 `clock:prospective:20260827:v3`；Rule Champion 已接受，TWSE／TPEX raw source 只完成 preactivation staging。三份正式 inputs 仍為 `0/3`，strict readiness 維持 fail-closed；此狀態不產生 Formal OOS、shadow maturity、promotion 或 broker credit。

## Prospective formal simulation track（2026-08-14）

Owner 已決定不以測試持倉、research causal ledger、歷史 replay 或 current-company sector snapshot 回填既有 Formal Gate，改採從未來交易日起算的受治理模擬持倉 clock。執行 SSOT 是 [Prospective Formal Simulated Portfolio Execution Plan](PROSPECTIVE_FORMAL_SIMULATED_PORTFOLIO_EXECUTION_PLAN_2026_08_14.md)：先完成 clock contract、三條 append-only capture producer、prospective PIT source acceptance、calibration policy 與 capture-only 護欄，再把既有 candidate／policies 凍結後選仍在未來的台灣交易日開始累積。預設不重訓；clock 期間禁止以已消費的 Formal OOS 日期重訓或替換 frozen identities。

此 owner 決議只建立後續工程方向，不產生 snapshot、elapsed day、source acceptance、Formal OOS 或 promotion credit。既有 `2014–2026` Direct／OOC 留在 research/history；`formal_oos_allowed=false`、production alpha 0、broker disabled 與 append-only external Gate 規則不變。`PFS-01`～`PFS-10` 已完成 strict clock／fixture-only capture／prospective PIT custody／inference calibration policy／capture-only readiness／frozen activation contract／shadow maturity gate／frozen OOS evidence／promotion review focused QA；程式面已完成。[Prospective Formal Clock Activation Handoff](PROSPECTIVE_FORMAL_CLOCK_ACTIVATION_2026_08_18.md) 現已記錄 owner 的 `2026-08-17T13:30:00-07:00` activation decision 與其選定的未來 `2026-08-19` 台灣決策日，但三個 formal paths 目前只完成環境配置，對應 manifests 仍全部 `file_missing`；不得把 deferred staging、文件中的 hash 或既有 heavy watcher 當成 strict readiness、capture 或 Formal evidence。

## Historical Forward Clock projection（2026-08-18）

下表保留 2026-08-18 當時的 projection，供追溯舊 clock 為何沒有成立；它已被 2026-08-19 restart direction 取代，不是目前下一步。

| Clock | 今日狀態 | 可引用證據 | 缺失／degraded／failure | 下一步 |
|---|---|---|---|---|
| Development | `DEV-126-prospective-activation-handoff-lineage-validation-20260818` | 新 owner-authored handoff 已由 commit `ffe667d` 納入，文件 hash=`sha256:1fa6506741d4137881390f46767dceaf836145461eacf9322879192a35b4026b`；它記錄 owner activation timestamp、`clock:prospective:20260819:v1` 與 owner 選定的未來 2026-08-19 決策日。唯讀 activation-environment／execution-plan inspectors 仍分別為 `waiting_for_controlled_environment`／`waiting_for_owner_inputs`，controlled store 與 secret store 只確認 configured，未輸出 secret | 三個 `BALDR_ML_*_PATH` 雖已配置，但 manifests 全部 `file_missing`；clock／activation manifest bytes 未在 repository 或既有 TEMP root 找到，僅有 handoff 內的 hash 引用，不能升格為 strict readiness、Formal OOS 或 capture evidence。沒有新 Dataset、Rule snapshot、PIT source acceptance、model promotion、training 或 product state mutation | 只等待 owner-controlled producers 建立三份真實 append-only manifests，再以 strict readiness 唯讀重驗；本 automation 不發布／啟動 clock，不執行 capture、watcher、scheduler、Direct、OOC、training 或 promotion |
| Formal evidence | `prospective_owner_handoff_observed / rule_only_zero_credit` | 獨立 Rule-only lane `formal-rule-only-20260807-r1` 的 owner decision 與四筆 registry binding 仍有效，formal session=`2026-08-07`、snapshot=`missing`，四筆皆未消耗。新 prospective activation handoff 是 Development clock 的未來模擬 clock 決議，不是 Rule-only decision-time `manual_observed`，也未寫入或消耗既有 registry | 本次 snapshot count=`0`；outcome revision／matured denominator／formal credit／consumption／elapsed-day increment 皆為 `0`；missing=`manual_observed_snapshot_missing`；degraded=`prospective_input_manifests_file_missing`；capture failure=`no qualifying decision-time artifact supplied or found`；歷史 `manual_observed_20260729.json` 不重用、不回填 | 不重綁或消耗 2026-08-07，也不把 prospective activation handoff 轉成 Rule-only observed day。任何新 Formal holdout 仍須可引用、屬於該 Formal lane 的 owner 決議時間 artifact，並在綁定前重新檢查 consumption registry；否則 Formal credit 維持 0 |

截至本次 **2026-08-18 14:35（Asia/Taipei）** projection refresh，Formal Week 6（2026-08-17 至 2026-08-23）仍在自然進行中，因此不追加 weekly revision；Week 1～5 各保留一份 revision。August 尚未完成，因此本次不新增或更新當月 Gate Review。Owner 已在新的 activation handoff 選定仍屬未來的 2026-08-19，但三份受控 manifests 尚未存在；此狀態不是 snapshot、elapsed day、source acceptance、Formal OOS 或 promotion credit。

## Historical Forward Clock safety constraints（through DEV-119）

`DEV-102-datagov-history-target-detail-probe-20260805` 與 `DEV-105-ml-raw-publication-refresh-current-sqlite-20260805` 的既有證據仍適用；DEV-79 至 DEV-119 的工程安全約束仍全部適用：
1. **ML-universe bounded numeric acquisition** owner development-plan activation 不改 source acceptance；以 ML raw PIT 11-symbol scope 的未嘗試缺口新嘗試 1216、2412、2881、6505，僅 2412／6505 產生 immutable candidate bundle；一個 DNS 與一個缺 listing failure 均 fail-closed，沒有猜測、補值或將 failed item 視為 coverage。
2. **Aggregate coverage remains blocked** 50 個 immutable candidates 為 2,128 個 PIT-eligible rows、118 bp coverage；固定 8,000 bp 門檻仍未達成，未建立 feature materialization。
3. **Research-only boundary** 新增 raw/source/candidate/run manifest/aggregate 均位於 TEMP，`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`downstream_eligibility=none`。
4. **No applying acceptance** Owner bounded acquisition 與正式 development-plan authorization 都不轉換成 source acceptance；license、quality/PIT、coverage、具名 reviewer 與 registry applying revision 仍待補齊。
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
27. **ML-universe backfill handoff boundary** DEV-115 的 2412／6505 2025-Q1 MOPS candidate 已補進 TEMP research evidence，令 ML raw scope 的 valid candidate coverage 由 7/11 提升至 9/11；但 current raw publication `pit-1b53e73127a5246d3255ee95` 未改寫，因 aggregate coverage=118 bp 且缺 license、具名 reviewer/applying decision 與 allowed use case，materialization preflight 固定 `false`，`direct_training_input=false`。因此不得將兩筆 candidate 併入 formal／research dataset、assembler、fit、training、promotion 或 Formal path。
28. **Foreground Rule-only source boundary** DEV-119 只提供 owner 在 bound session 的真實台北盤中手動觸發入口；固定使用 `daily_prices.date < decision_session_date` 的唯讀 60-session input、20-session Decimal／整數 bp ranking 與既有受控 HMAC Rule Champion 契約。輸出只寫 TEMP immutable artifacts，且需另一條既有人工 capture 命令才可 append shadow sidecar。它不建立 formal credit、elapsed day、holdout consumption、source acceptance、推薦、交易、scheduler、training、promotion、unblind 或 production blend；任何時間／lane／registry／key／PIT 失敗都維持 snapshot=`0`。

以上工程 hardening 不等於 coverage 達標、不等於來源方授權／License 核准、更不等於 Formal credit。Owner 已將工作正式納入 development plan 並授權 bounded research acquisition，但 P0/P13 的逐來源 applying source acceptance 仍等待可引用 license、quality/PIT、coverage、rollback 與具名 reviewer evidence；最新 aggregate 為 118 bp／8,000 bp（gap 7,882 bp）。Formal lane 已具備受控 source producer，但仍缺真實 decision-time Rule-only `manual_observed` artifact；本次 snapshot、elapsed formal day、outcome revision、matured denominator、formal credit 與 consumption increments 均為 0。


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
