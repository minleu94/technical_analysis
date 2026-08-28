# baldr 程式整體 Readiness Audit（2026-08-27）

## 2026-08-28 台灣市場日期刷新（唯讀）

本次重新執行時間為 `2026-08-27T17:55Z`，`taiwan_market_today()` 已進入 `2026-08-28`。因此前一版在台北 `2026-08-27` 觀測到的 `2026-08-28` Paper／Decision row，現在已是當日資料，不再列為 future blocker；原始 row 仍維持不可刪除、不可回填的稽核原則。

- Paper Portfolio readiness：`status=partial`、21 筆 raw snapshot，最新 `2026-08-28`／`490950.00` 可作當日 current projection；以 baseline／T-1 行情建立的 staging Equal Weight preview 已成功產生 21 筆觀測（最新 `472302.39`，`write_performed=true` 但只寫入 QA output），正式檢查仍未配置該 ledger，交易成本 ledger 也仍缺少。
- Decision Desk：22 筆 snapshot，最新 active `2026-08-28`、quality=`degraded`；以 `--latest-before-or-on 2026-08-28` 查詢時 `future_decision_desk_snapshot_dates=[]`。品質降級與 source gap 仍需 owner／來源證據處理。
- Pre-V2：owner-approved weekly projection `3/3`、multi-day dry-run `3/3`，overall=`ready`；`production_scheduler_allowed=false` 不變。
- Gate 3 P0：仍為 13 個 `contract_only`，未提供完整 `p0-source-intake.v1` dossier 與 acceptance decision；本次只產生空白 intake template，沒有推導或套用 Fubon 單一來源封包。
- Gate 7 ML：`waiting_for_formal_inputs`，三份 owner-controlled manifest 均不存在，`formal_oos_allowed=false`、`broker_order_allowed=false`。
- Runtime：正式 logs／Research Registry 既有檔案 write-handle 仍 `Permission denied`，overall=`attention`；檢查 `side_effect_free=true`。

本次唯讀輸出保留於 `output/qa/readiness_refresh_20260827/`：`paper_portfolio.json`、`decision_desk.json`、`pre_v2.json`、`ml_formal_input.json`、`p0_source_control_center.json` 與未填寫的 `p0_source_intake_template.json`。

另修正 Gate 4 操作入口的 Windows 可用性：`export_paper_trade_csv_template.py --help` 現在會先設定 UTF-8 console，即使 CP1252 主控台也能顯示繁中說明；新增 subprocess 回歸測試，範本產製仍只寫明確指定的空白 CSV，不建立 Paper ledger。

## 結論

目前 baldr 是「可重跑、可觀測、研究／紙上模式可用」的工程版本，不是可以宣稱投資有效性、正式 OOS、production scheduler 或 broker execution 的完整產品。半成品感主要來自真實 evidence、來源治理、紙上成交與時間 Gate 尚未累積，不是主視窗缺少一個按鈕就能解決的問題。Decision Desk／Evidence readiness 的 current 查詢現在也會以台灣市場今日為上限，future snapshot 只保留診斷，不會進入 Workbench 或正式 evidence coverage。資料更新頁的日期控件也統一採台灣市場日期，localized `不可用` 會顯示為異常；全域狀態檢查失敗時，六個核心來源與三個候選資料源的頁內摘要都會同步清除舊內容並保留共同錯誤原因。

本稽核涵蓋程式檢視、唯讀 readiness inspectors、真實 MainWindow smoke、UI 回歸與型別／語法檢查。沒有寫入正式市場資料、沒有改 SQLite schema，也沒有啟用 broker 或 production scheduler。

本輪已補上排程寫入端的時間防線：Paper／Decision Desk 的排程預設選最近已到達的台北 08:30 cutoff；Paper 對明確未到達的 `--decision-at` 會以 `skipped_future_decision` 結束，且在開啟 state／market DB 前停止。既有 future raw row 不會被自動刪除或回填，仍須 owner 追查與決定後續處置。

推薦 Explain 的另一個半成品缺口也已補齊：`ScoringEngine` 會把 rolling PatternScore 的已確認型態、方向與衰減日數投影到結果列，`ReasonEngine` 只消費這份 evidence；若只有方向訊號而沒有可核對的型態名稱，畫面會保守顯示 generic 訊號，不從分數臆測具體圖形。此變更不改既有分數與 look-ahead 防線。

同一輪也移除了推薦與四個策略 executor 中未使用的全歷史圖形預掃描，避免在 scoring 已做 rolling identification 後重複呼叫 PatternAnalyzer；策略分數與交易訊號契約不變。

資料更新流程另修正 SQLite 輸入的欄位別名正規化與重複條件：英文／中文日期、股票代號、股票名稱會在寫入副本上映射至 canonical 欄位並統一格式，raw CSV 不被改寫；缺必要欄位仍 fail-closed。

## 八個主工作區現況

| 工作區 | 現在可用的部分 | 尚未準備好／原因 | 狀態 |
|---|---|---|---|
| 決策工作台 | 顯示 data freshness、manual queue、Gate warnings、Paper／Evidence 摘要；空資料與 degraded 會揭露；目前環境載入 owner-approved weekly projection 後可揭露 weekly `3/3`；current Decision Desk snapshot 會排除未來日期 | projection 只供 UI／Pre-V2 readiness 揭露，不授予 formal credit；未載入 projection 時仍如實顯示正式 DB legacy history（目前 `0/3`）；future snapshot 會以 warning／source gap blocker 揭露 | `read_only_ready` |
| 市場探索 | 強弱勢個股／產業、Regime、空結果／錯誤清空與筆數狀態列 | 真實人工畫面 review 仍需操作員確認；不把排名當交易建議 | `usable_with_disclosure` |
| 推薦分析 | Rule-only／研究結果與 replay/read-only evidence 可查看 | scheduled evidence pipeline `degraded`；不能把 dry-run、replay 或 candidate 當 formal Advice | `research_only` |
| 策略回測 | 回測計算、唯讀 Evidence Review、Registry compare 介面；Registry 不可寫時 fail-soft | 正式 `OUTPUT_ROOT` 若唯讀，保存／歷史比較停用；需修正環境權限，不應建立空 registry 假裝成功 | `usable_if_writable` |
| 觀察清單 | 候選池載入中／已更新／空清單／錯誤狀態清楚，空池時批次入口停用 | 沒有候選不代表策略失敗；仍需來源與人工研究流程 | `guarded` |
| 持倉管理 | 手動 Portfolio、Paper Portfolio readiness、Trade Import、Stress Lab／history foundation | 正式輸出有 21 筆 raw snapshot，最新 `2026-08-28` 已等於本次檢查的台北市場日，可作當日 current projection；仍無正式成本帳、Equal Weight benchmark、完整 fills／partial-fill／override／execution-gap，因此週報不可計算 | `degraded` |
| 數據更新 | daily、market、industry、broker、technical 的狀態與錯誤可見；日期控件以台灣市場日期為「今日」；TPEX 背景狀態可見且失敗時 fail-closed；寫入型工作有可見 SQLite 同步結果、合作式取消與大型合併／匯出批次進度；增量合併沒有新 CSV 時會明確回報 `no_op=true`／「資料已是最新」，且不先建立整合檔備份；全域錯誤會清除六個來源頁的舊摘要並保留錯誤原因；窄版導覽、狀態卡與操作按鈕已改為可捲動可讀排列 | 真實下載／合併測試刻意跳過以保護資料；大型合併現在可在檔案／讀取批次／寫入批次安全邊界取消，匯出可在資料批次邊界取消；券商分點受控並行、技術指標多核心＋單 writer 尚未完成設計 | `operational_with_gaps` |
| Runtime | 排程順序、write intent、dry-run／sidecar 狀態可稽核；正式路徑環境卡片與唯讀 CLI 會顯示 DATA_ROOT／OUTPUT_ROOT／logs／Research Registry，並對既有 logger／Registry 檔案做不寫入內容的 handle probe | formal path readiness 實測為 `attention`（`config.log`、Research Registry write-handle 被拒絕）；evidence dry-run `DEGRADED`；正式 scheduler 維持關閉；staging probe 不能代替正式 ACL／鎖定修復 | `observability_only` |

## Gate readiness

| Gate | 實測狀態 | 尚缺的東西 |
|---|---|---|
| Gate 1 Advice | bounded read-only contract 已完成 | 不等於投資有效性、broker 或正式 scheduler |
| Gate 2 Evidence loop | 目前 CLI／UI 載入 owner-approved projection 時為 `ready`；weekly `3/3`、multi-day dry-run `3/3 ready`；未載入 projection 的 formal DB legacy path 仍為 `0/3`；Evidence source coverage 與 snapshot inspector 已能在正式唯讀 DB 上 query-only 執行 | projection 仍不是 formal credit；仍需維持 review／dismissed／follow-up action rhythm、backup／rollback／recovery 證據與正式 scheduler approval；當日 Decision Desk row quality 仍為 `degraded`，source gap 仍需 owner 追查 |
| Gate 3 P0 data | 13 個 source 全為 `contract_only`；accepted `0`、limited `0`、downstream eligible `0`。2026-08-27 bounded audit 可重跑，但受控環境官方 endpoint 全部 network failed；外部 Fubon projection 僅補出 35 筆除權息、1 筆漲跌停鎖死的 research supplement | 每來源真實 publication／available-date、coverage／quality、license、missing／outage、具名 owner／reviewer 決議；Fubon 仍 `research_only/degraded/first_observed_only`，不解除任何 P0 acceptance |
| Gate 4 Portfolio | `degraded/partial`；正式輸出有 21 筆 raw paper snapshot（2026-07-12～2026-08-28），本次台北市場日為 `2026-08-28`，沒有 future blocker；最新當日 projection 為 `490950.00`。staging Equal Weight preview 已成功，但未套用正式 output；寫入端仍防止新的 future row | 仍需 owner review 後把 Equal Weight ledger 配置到正式 output、成本 ledger、真實 fill／partial／reject／override、execution gap、可計算週報與 forward outcome；當日 snapshot quality 仍需持續 review |
| Gate 5 Signal pruning | 工程 scaffold 可用 | 真實 OOS／forward／paper 樣本、benchmark 對齊、第一批 retain／restrict／downweight／retire 決議 |
| Gate 6 Position health／exit | read model／contract foundation 可用 | 每個 active position 的 thesis／invalidation／review state、真實 transition evidence、人工 override 與 post-alert／post-exit 結果 |
| Gate 7 ML | shadow-only | formal OOS、shadow days、revalidation、promotion review；所有 production blend／scheduler／trading flags 仍為 false |

## 實測 blocker 與環境問題

1. **正式輸出權限**：曾實測正式 `OUTPUT_ROOT` 唯讀會讓 `ResearchRunRepository.ensure_schema()` 在回測頁初始化時拋 `sqlite3.OperationalError`。Runtime 卡片與 CLI 現在會揭露路徑存在、可讀性、`os.access` hint，並對已存在的 `config.log`／Research Registry 執行不寫入內容的 write-handle probe；本次正式程序實測兩者的 write-handle 開啟均為 `Permission denied`，因此 readiness 應維持 `attention`，不能被 `os.access` 誤標為 ready。需由 owner 在正式執行環境確認 ACL／鎖定／程序權限。CLI 另提供明確確認、禁止指向正式根目錄的 ephemeral file／SQLite staging probe；尚未在正式根目錄執行實際寫入，故 Gate 仍不解除。`BacktestView` 會顯示實際原因並停用保存／比較；QA smoke 使用報告目錄下 `_isolated_app/data`／`_isolated_app/output`，不代表正式環境權限已修好。
2. **Evidence dry-run 降級**：最新狀態為 `degraded`，警告包含 `insufficient_future_data=6700`、`missing_event_price=8` 與一筆 portfolio alerts chip-data 缺口；需資料／人工判讀，不可直接改成 passed。
3. **Weekly collection 與 projection 邊界**：sidecar 的 `collection_status=pending_human_review`、`gate_credit_status=pending_human_review`、`source_write_allowed=false` 仍不會自動補 Gate credit；目前環境另外載入 3 筆具名 owner-approved projection，CLI／UI 可顯示 weekly `3/3`，但 projection 固定 `formal_credit_authorized=false`，不可用 replay、fixture 或手動改表補正式 Gate credit。
4. **Formal clock**：`formal_readiness=false`；缺 owner decision、manual observed snapshot，且 holdout binding 需要 owner authority。這是責任與可稽核輸入缺口，不是 UI 缺陷。
5. **尚未開放的效能工程**：`UPDATE-ISSUE-013`（MoneyDJ／Selenium／retry／rate-limit 的券商分點並行）與 `UPDATE-ISSUE-014`（技術指標多核心計算＋SQLite／CSV single writer）仍需獨立設計，不能直接把 thread 數拉高；大型合併／匯出已能回報檔案／資料批次進度，合併也已補到讀取批次取消，但仍不做逐列／逐筆中斷，必須完成目前安全批次後才離開。
6. **P0 外部封包尚未達 intake schema**：目前 `C:\Temp\external-evidence-shadow` 的 Fubon dossier 是單一來源 `source-acceptance-dossier.v1` projection，不能直接餵給要求完整 13 列的 `p0-source-intake.v1`；owner decision 是 `source-acceptance-owner-review-decision.v1` 且狀態 `deferred`，不含可套用的 canonical evidence IDs。現已可在 UI／CLI 唯讀投影這類非套用決議，但不會自動 append 或升級。
7. **Paper Portfolio clock integrity（已由日期刷新解除當次 blocker）**：前一版在台北 `2026-08-27` 觀測到 `paper-main-20260828`／daily status `2026-08-28`，因此暫時排除 current projection；本次 `2026-08-28` 唯讀重查已沒有 `paper_snapshot_future_dated`／`paper_daily_status_future_dated`，最新當日 projection 為 `490950.00`。排程入口仍採最近已到達 cutoff，Paper writer 對明確 future `--decision-at` 仍在開啟 DB 前停止；既有正式 row 不刪除或回填。現階段 blocker 已轉為 Equal Weight benchmark、成本 ledger 與真實 fills／forward outcome。
8. **Decision Desk future row 與檢查器邊界（已由日期刷新解除當次 blocker）**：前一版觀測到 active `2026-08-28` row；本次 `inspect_decision_desk_snapshots.py --latest-before-or-on 2026-08-28` 回報 `future_decision_desk_snapshot_dates=[]`，latest active 仍為 `2026-08-28`，quality=`degraded`。Pre-V2、Workbench、Evidence source coverage 與 snapshot inspector 仍以台灣今日為上限，future row guard 保留，並持續要求 source gap／quality 的 owner 處理；Evidence source coverage 維持 query-only，不會因唯讀 DB 初始化 schema。

## 驗證證據

- MainWindow non-destructive smoke：最新 run `20260827_104105`；8 個 workspace 全部建立／切換，cancel-only probe 未呼叫 destructive action；`startup.png` 顯示目前環境的 weekly projection `3/3`；`1366x768` 與 `390x844` 實際均符合 requested viewport（`matched`）。Runtime 小於 720px 時已改為垂直治理欄並可捲動，status strip 也會省略長 session context，UpdateView 窄版導覽／卡片／操作鈕可讀重排；結果：[result.json](../../output/qa/full_app_healthcheck_20260827_update_responsive_final/20260827_104105/result.json)。
- Runtime environment readiness：正式根目錄 `DATA_ROOT`、`OUTPUT_ROOT`、logs、Research Run Registry 皆存在且可讀；新增的既有檔案 write-handle probe 已實際觀測 `config.log` 與 Research Registry 開啟均為 `Permission denied`，CLI 回報 `overall_state=attention`、`side_effect_free=true`，因此正式 readiness 不再只依賴 `os.access`。檢查不建立缺少路徑或寫入正式檔案。另以 isolated temp staging 驗證了 ephemeral file／SQLite probe 的受控流程與清理（file／SQLite／cleanup 均 true）；正式 Registry 寫入成功仍未被宣稱。
- Pre-V2 readiness CLI／Workbench projection consistency：在目前 `WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH` 指向通過 schema／安全旗標驗證的 owner-approved projection 時，CLI 與 UI 均回報 weekly `3/3`、multi-day `3/3`、overall `ready`；`production_scheduler_allowed=false` 與 `formal_credit_authorized=false` 維持不變。清除該環境變數後，兩者均回到正式 DB legacy history `0/3 waiting_for_time`，不會互相矛盾。
- P0 external evidence read-only validation：`inspect_fubon_dossier.py` 將 Fubon projection 判定為 `deferred`，缺 9 類 authority／programmatic evidence；`run_p0_candidate_audit.py --fubon-projection` 在 2026-08-27 受控環境中保留 35 筆除權息與 1 筆漲跌停 research supplement，但 12 個官方 endpoint 因 `WinError 10013` network socket 限制未觀測，整體仍 `machine_verified=0`、`degraded=12`、`unavailable=1`、`downstream_eligibility=none`。owner decision preview 現已可被 UI／CLI 讀取為 deferred，沒有 registry append。
- Paper Portfolio clock／look-ahead guard：本次台北市場日 `2026-08-28` 的唯讀檢查得到 21 筆 raw snapshot，最新 raw `2026-08-28`、總值 `490950.00`；沒有 future blocker，readiness 為 `partial`，正式 blocker 只剩 benchmark 尚未配置與成本 ledger 缺少。`build_paper_equal_weight_benchmark.py` 已在 `output/qa/readiness_refresh_20260827/paper_equal_weight_preview.sqlite` 產生 21 筆 staging observation（最新 `472302.39`），但未指向正式 `PAPER_EQUAL_WEIGHT_BENCHMARK_PATH`；Paper weekly `build_latest()` 與 Equal Weight builder 對未來期間／snapshot 仍 fail-closed，本次未刪除或改寫原始 row。
- Paper／Decision 排程 future-write guard：`test_run_paper_portfolio_daily.py` 與 `test_scheduled_decision_evidence_capture.py` 共 `28 passed / 1 warning`；覆蓋最近已到達 cutoff、明確 future `--decision-at` 不初始化 Paper state／market DB，以及排程 capture 不再選隔日 cutoff。未對正式 output 執行 writer。
- Decision Desk clock／read-only coverage guard：本次正式 `twstock.db` 唯讀檢查觀測到 22 筆 snapshot，latest active `2026-08-28`、quality=`degraded`，以台北 `2026-08-28` cutoff 查詢時沒有 future dates。`inspect_evidence_source_coverage.py` 與 `inspect_decision_desk_snapshots.py` 已在正式唯讀 DB 實際跑通，不建立 schema 或資料庫；future row guard 仍保留，source gap／degraded quality 仍需 owner 追查。
- Data Update QA：`23 passed / 0 failed / 4 skipped`；跳過項目是避免實際下載／合併正式資料的保護邊界，不是誤報通過。更新頁新增取消按鈕、TWSE／TPEX／券商／技術指標安全邊界取消、SQLite 結果卡，以及每日合併／CSV 匯出的檔案／資料批次進度；增量合併無新 CSV 時會以結構化 `no_op=true` 與「資料已是最新」呈現，且不先建立整合檔備份；大型合併讀取已支援檔案／讀取批次取消，匯出仍在資料批次邊界取消並保留原子目標檔，尚不提供逐列／逐筆中斷。UpdateView focused UI regression 最新為 `59 passed / 1 warning`，連同候選資料源頁狀態回歸共 `61 passed / 1 warning`；另以隔離 MainWindow visual probe 覆蓋 1366×768／390×844 的導覽、卡片欄數與垂直捲動；原有台灣市場日期控件、localized `不可用` 異常燈號、全域錯誤清除六個核心與三個候選來源摘要，以及候選資料源分頁狀態投影仍維持覆蓋。
- SQLite input normalization regression：`test_update_data_normalization.py` 與 `test_update_service_status.py` 目前覆蓋 canonical／英文欄位 aliases、日期／四碼代號格式、來源副本不變與 daily-price sync 實際寫入 canonical schema；未觸碰正式資料。
- Recommendation／Pattern Explain regression：rolling pattern confirmation metadata 與 generic fallback 已由 `test_pattern_score_confirm_logic_no_look_ahead`、`test_total_score_projects_confirmed_pattern_summary_without_guessing`、`test_reason_engine_consumes_confirmed_pattern_evidence_only` 覆蓋；既有 score 與 prefix-invariance tests 維持通過。Pattern evidence 只供 Explain／reason tags，不是下單訊號。
- 本輪 Update no-op、日期／錯誤可見性、長檔讀取批次取消、候選資料源頁內摘要與窄版重排修正後 focused regression：`test_update_service_status.py` + `test_ui_qt_update_view_workbench.py` 共 `118 passed / 1 warning`；另加候選資料源頁狀態測試共 `61 passed / 1 warning`；未觸碰正式資料。
- 既有集中回歸基準（環境／Runtime／Update／healthcheck）：`177 passed`；本輪受影響的 Update／UI／coordinator targeted suite：`151 passed / 1 warning`；P0 intake validator：`9 passed`；P0 decision append CLI：`7 passed`；Pre-V2 CLI／Workbench projection consistency：`38 passed / 1 warning`；Simulation projection consistency：`5 passed / 1 warning`；P0 decision projection／parser focused suite：`72 passed / 1 warning`；Paper future-date／Equal Weight builder／Portfolio UI focused suite：`43 passed / 1 warning`；Decision Desk／Evidence coverage future-date + query-only focused suite：`54 passed / 1 warning`；Runtime handle probe／UI focused suite：`25 passed / 1 warning`；Paper／Decision 排程 future-write guard：`28 passed / 1 warning`；Recommendation Pattern Explain／score compatibility：`3 passed / 1 warning`；文件編碼檢查：`4 passed`；全域 mypy：`510 source files` 無錯；最新 collection：`3563 tests collected`。
- 最新完整 pytest 證據（`output/qa/full_pytest_20260827_paper_gate4_cli_utf8_final2.xml`）：`3562 passed / 1 skipped / 26 warnings`（`532.59s`）；inventory audit（`output/qa/test_inventory_audit_20260827_paper_gate4_cli_utf8_final2.json`）回報 `overall_status=passed`、無 machine-checkable blocker，最新 collection=`3563`。Warnings 主要是既有 joblib 核心數偵測、研究回測同日成交理想化假設與 pytest cache 權限提示，沒有 failure。
- 本輪 Update no-op、日期／錯誤可見性、長檔讀取批次取消、候選資料源頁內摘要、窄版重排與 Paper fills template／append CLI UTF-8 修正後 focused regression：`test_update_service_status.py` + `test_ui_qt_update_view_workbench.py` 共 `118 passed / 1 warning`；`test_append_paper_trade_csv_cli.py` 共 `9 passed / 1 warning`；未觸碰正式資料。
- 本輪 Update no-op、日期／錯誤可見性、長檔讀取批次取消、候選資料源頁內摘要與窄版重排修正後 focused regression：`test_update_service_status.py` + `test_ui_qt_update_view_workbench.py` 共 `118 passed / 1 warning`；另加候選資料源頁狀態測試共 `61 passed / 1 warning`；未觸碰正式資料。
- Scheduler report：[SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md](SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md)。

## 可以如何持續推進

1. **先修環境**：先執行 Runtime environment readiness CLI 並閱讀每一路徑 diagnostic；若既有檔案 write-handle probe 或正式 Registry 實際寫入失敗，確認 `OUTPUT_ROOT`、logs 與 research registry 的 ACL／鎖定狀態，或明確指定可寫 output root，完成後再做一次不碰原始資料的正式 UI 啟動檢查。不要把 `os.access` 或 staging probe 直接當成正式寫入已成功。
2. **維持 Gate 2 真實節奏與 projection 邊界**：目前 owner-approved projection 已讓 UI／Pre-V2 顯示 `3/3`，但仍由具名 owner 維護 review、action item 與 recovery evidence；projection 不得被當成 formal credit，也不以 replay／fixture 折抵正式 scheduler approval。
3. **補 Gate 3 來源證據**：逐一提供 P0 license、PIT／available-date、coverage／quality、outage／retry 與 owner decision；Control Center 只在具體 revision 通過驗證後反映 accepted／limited。
4. **補 Gate 4 紙上證據**：staging Equal Weight preview 已先驗證可重建 21 個觀測；接下來由 owner review 後才把 ledger 配置到正式 output，再用成交範本匯入真實 fills、配置成本 ledger，依同 universe／現金政策／成本假設累積可計算週報與 forward outcome。
5. **再處理 Formal clock 與 ML**：owner 提供 manual snapshot／holdout binding 後才重新檢查 formal readiness；ML 保持 shadow-only，直到 Gate 5 evidence 與 promotion review 有足夠證據。
6. **最後才做受控效能工程**：先完成 single-writer／rate-limit／retry 設計與壓測，再考慮券商分點並行或技術指標多核心。

這個順序可以持續推進，但每一步的「完成」必須由相應的資料、人工決議或真實時間證據解除 blocker；單純新增 UI、測試或一次 dry-run 不會自動升級 Gate。
