# V4 資料恢復紀錄（2026-09-07）

## 範圍與安全邊界

本輪處理基本面資料更新路徑的盤點，以及官方月營收與季度財報的 bounded 抓取、驗證、隔離候選物化。正式資料根目錄依 `TWStockConfig` 為 `D:/Min/Python/Project/FA_Data`；本輪對該根目錄與正式 SQLite 只做唯讀查詢，沒有改寫原始 CSV、availability mapping 或正式 DB，也沒有執行正式 backfill。1849 筆月營收明確 accepted scope 已由 coordinator 在 repo 隔離雙根驗證；季度候選同樣只留在隔離 output；正式 D 槽 apply 未執行。季度 SQLite materializer 另外要求 TEMP／repo output 受控路徑與 research-only marker，避免呼叫端誤把隔離入口指向正式 DB。

測試與 live candidate 輸出使用 repo 內隔離路徑；live CLI 只寫入被 `.gitignore` 排除的 `output/v4_data_recovery_2026-09-07/`。

## 正式資料現況與實際更新路徑

以 SQLite `mode=ro` 查詢 `D:/Min/Python/Project/FA_Data/sqlite/twstock.db` 的結果如下：

| 資料表 | 列數 | 期別範圍 | `as_of_date` 範圍 | `available_date` 範圍 | 來源版本狀態 |
|---|---:|---|---|---|---|
| `fundamental_monthly_revenues` | 246,331 | 2014-04 ～ 2026-06 | 2014-04-30 ～ 2026-06-30 | 2026-06-17 ～ 2026-07-15 | 2026-06 的 MOPS snapshot 已存在，但沒有 2026-07 候選的正式回填 |
| `fundamental_statement_items` | 1,645,555 | 2014-Q2 ～ 2024-Q1 | 2014-06-30 ～ 2024-03-31 | 全部為 2026-06-17 | 3 類 statement 都是 `financial-data-statements-2026-06-17`、`degraded` |

月營收目前的正式候選路徑是：

```text
MOPS redirectToOld
  → mopsov popup（window.open 相對路徑）
  → mopsov /nas/t21/{sii|otc}/t21sc03_*.html
  → monthly_revenue_snapshot_harvester
  → output/monthly_revenue_mops_snapshots/*.csv
  → availability validator / controlled backfill（後續流程）
```

現有正式輸出只有 `mops_monthly_revenue_snapshot_2026-06_2026-06_2026-07-14.csv`（2026-06，1,832 列）及較早的 2026-05／歷史 snapshot。`UpdateService` 與更新頁的候選按鈕雖會依市場日期推算應查期別，但 candidate snapshot 不會自動寫入正式 SQLite；因此沒有新 snapshot 或正式 mapping/backfill 時，正式表會停留在 2026-06。這是資料週期未完成 intake/materialization 的缺口，不能用舊期別補成新期別。本輪已沿既有 CLI 完成 candidate → official availability candidate → validator → 隔離 backfill 的實際路徑；完整 candidate 缺兩筆公告日證據時會阻擋完整 scope，只有以 manifest 綁定全量 candidate、accepted subset 與 excluded keys 的 1,849 筆 partial scope 才能進隔離 coordinator。

基線核對也確認，HEAD 版本的單引號正規表示式對本次官方 popup 的現行單引號 `window.open('/nas/t21/sii/t21sc03_115_7_0.html','')` 可以匹配；本次在未升權環境看到的 `WinError 10013` 是執行環境封鎖網路 socket，不是產品 parser 失敗。修補保留既有可用形狀，補上雙引號／空白變體與正式來源、指定市場、期別及 body marker 的 fail-closed 驗證，避免把未來的回應形狀或錯期別回應誤納入。

季度財報的實際路徑是：

```text
financial_data/*_income_statement.csv
financial_data/*_balance_sheet.csv
financial_data/*_cash_flows_statement.csv
  → parse_statement_rows
  → fundamental_statement_availability.csv
  → scripts/backfill_fundamental_statement_items.py
  → fundamental_statement_items
```

本機 raw statement CSV 目前仍只到 2024-Q1，且 `D:/Min/Python/Project/FA_Data/meta_data/fundamental_statement_availability.csv` 不存在。逐檔串流核對的實際分佈是：income 1,563 檔／391,545 列，2024-Q1 僅 15 列、4 stocks；balance 1,565 檔／407,990 列，2024-Q1 僅 19 列、4 stocks；cash flow 1,562 檔／846,020 列，2024-Q1 僅 55 列、4 stocks。三類 raw 的最大 `date` 都是 2024-03-31；2023-Q4 仍分別有 1,524／1,521／1,520 stocks。檔案修改時間集中在 2024-04-16 至 2024-05-23，只作更新停滯的佐證，沒有拿來推定公告日或可得日。backfill 會在 availability mapping 缺失時 fail-closed；既有資料是 2026-06-17 以 degraded 狀態導入的舊候選。

`scripts/fetch_mops_statement_availability.py`／MOPS EZSearch 只能取得公告事件候選，受 1,000 列查詢上限與 research-only contract 限制，不能直接產生季度財報數值列。本輪新增的隔離入口使用同一官方 MOPS host 的 `ajax_t164sb03`（合併資產負債表）、`ajax_t164sb04`（合併綜合損益表）與 `ajax_t164sb05`（合併現金流量表），再以 `doc.twse.com.tw/server-java/t57sb01` 的 IFRSs 合併財報 listing 綁公告事件與更正狀態；XBRL row code 回應只接受 `ix:nonNumeric` 的精確公司、年度、季度、合併範圍與市場 metadata，不能以正文數字或比較欄位判斷身分。它只輸出研究候選，仍需逐來源 provenance、coverage、revision 與 materialization gate；不能以本輪 bounded 值直接補正式季度表。

## 本輪修復

修改的程式與測試如下：

| 檔案 | 類型 | 內容 |
|---|---|---|
| `data_module/monthly_revenue_availability_history.py` | 修改 | 解析 MOPS redirect 的單/雙引號 `window.open(path, target)` 形狀；只接受 HTTPS `mopsov.twse.com.tw`、`/nas/t21/` 相對路徑；確認路徑市場、ROC 年月與回應 body 期別都符合請求，避免把錯期別回應貼上請求期別。 |
| `data_module/monthly_revenue_snapshot_harvester.py` | 修改 | 每個市場／期別以 HTML UTF-8 解碼內容 SHA-256 建立 `source_version`，格式為 `mops-static-{market}-{period}-sha256-{digest}`，讓來源版本保留實際期別與內容身份。 |
| `data_module/monthly_revenue_backfill.py` | 修改 | 以 snapshot 全量列數為分母，揭露缺 mapping、重複、無效列與抓取 session 時間不一致；缺證據時 fail-closed；保留批次與市場／期別 HTML lineage，並拒絕把較晚抓取的值標成較早可得日。 |
| `data_module/monthly_revenue_availability_merge.py` | 修改 | 以 append-only revision merge 保留既有 mapping；apply 具 target SHA-256 CAS、任務專用備份與既有 OS advisory lock，避免並行 writer 被覆蓋。 |
| `data_module/monthly_revenue_recovery.py`、`scripts/apply_monthly_revenue_recovery.py` | 新增 | 將 accepted scope 的 mapping 與 SQLite apply 置於 durable journal、線上 SQLite backup、transaction rollback 與 mapping CAS 補償流程；journal 以 resolved 路徑、輸入檔 hash 與 source version 綁定，只能同 operation resume。 |
| `data_module/fundamental_sqlite_provider.py` | 修改 | 同一股票／月份有多個正式 source version 時只回傳決策日可見的最新可用版本；同日不同內容沒有序時證據時整個月份 fail-closed，避免聚合重複或隨插入順序改變。 |
| `data_module/monthly_revenue_availability_history.py`、`scripts/build_monthly_revenue_availability_history.py` | 修改 | availability candidate 可帶實際 ISO-8601 抓取時間，轉為下一個台北曆日的 date-only 保守可用日；不把公告月份或查詢日期當成可得日。 |
| `scripts/build_mops_statement_pit_candidate.py` | 新增 | 以 MOPS t164 sb03／sb04／sb05 取得單一公司、單一期別的合併資產負債／綜合損益／現金流量 numeric rows；逐表驗證官方期別 marker、target header、listing 期別與 correction，保留原始回應 hash、完整 named-row 分母、excluded rows、period basis、Decimal 整數單位與帶時區 capture；XBRL 對官方 Big5-HKSCS 擴充採嚴格解碼；保存的 t57 raw 可另以官方 HTTP evidence 做 hash／請求／公司／期別綁定，並以完成時間計算 numeric cutoff。 |
| `scripts/enrich_mops_statement_item_codes.py` | 新增 | 以既有 immutable t164 raw 與官方 XBRL 隱藏 metadata 精確驗證公司／期別／市場，再補上官方 row code；新 run 排除 `run-manifest.json` 自引用，並逐一核對頂層與 raw file hash。 |
| `data_module/mops_statement_candidate_adapter.py` | 新增 | 隔離轉換 research candidate 的 unit／scale 與 period semantics；EPS cents 轉為 consumer 可讀的 Decimal TWD/share，一般仟元金額保留完整 TWD，並保留 numeric／announcement timestamp 與 raw lineage；materializer 只允許 TEMP／repo output，拒絕 DATA_ROOT、formal DB、symlink／junction alias 與未標記既有 DB，不修改正式 consumer schema。 |
| `scripts/materialize_mops_statement_candidates.py` | 新增 | 提供明確的多 candidate、決策日與 evidence output 入口，呼叫上述隔離 materializer；不提供正式 DB fallback。 |
| `scripts/build_mops_statement_batch.py` | 新增 | 接受明確的 `STOCK:MARKET:YYYY-Qn` 清單，單批上限 8；每家公司獨立記錄成功／失敗、child hash 與錯誤，批次可用 `--resume` 驗證既有 immutable child 並只重試未完成項，沿用單公司官方 fetcher；`--listing-raw` 可配對 `--listing-evidence`，把 saved response 的官方證據帶入單公司入口。 |
| `scripts/plan_mops_statement_universe.py` | 新增 | 以保存的官方 registry 計算 eligible 分母與排除原因；首批 `representative_initial` 保留 2881／兩市場／產業覆蓋條件，後續 `continuation` 依 verified child hash 穩定選取下一批，caller exclusion 不計完成。 |
| `scripts/diagnose_mops_failed_quarterly.py` | 新增 | 以有界官方唯讀請求保存失敗公司的 t164／XBRL raw、HTTP metadata、公司／期別／科目診斷與 SHA-256；alternate host 404 與原始 doc DNS 失敗分開記錄。 |
| `tests/test_monthly_revenue_availability_history.py` | 修改 | 加入第二參數、雙引號、外部 URL、錯誤 `/nas/t21/` 路徑、path traversal、錯市場／錯期別與 redirect chain 的回歸測試。 |
| `tests/test_monthly_revenue_snapshot_harvester.py` | 修改 | 驗證 snapshot source version 由市場、期別與回應內容 hash 組成。 |
| `tests/test_monthly_revenue_backfill.py`、`tests/test_monthly_revenue_backfill_cli.py` | 修改 | 驗證完整 snapshot 分母、缺單筆 mapping、缺 source lineage、抓取 session 早於 mapping、舊版本保留及 CLI 受控入口。 |
| `tests/test_fundamental_sqlite_provider.py` | 修改 | 驗證同日不同 source version 會在正向／反向插入順序下同樣 fail-closed。 |
| `tests/test_monthly_revenue_recovery.py` | 新增 | 驗證 partial apply 冪等、crash/retry、DB commit 後 journal/evidence 失敗、並行 mapping writer 補償，以及不同輸入重用 journal 時不取用舊 backup。 |
| `tests/test_build_mops_statement_pit_candidate.py` | 新增 | 驗證三類 t164 表格的實際期別欄位、TWD 仟元轉整數、EPS 正負值的 TWD/share cents、空白列分母、selector 母子公司精確匹配、已核對 alias 的唯一性／金額匹配、XBRL exact identity（含錯公司數字碰撞／錯期別比較欄）與 manifest 全檔 hash fail-closed。 |
| `tests/test_mops_statement_candidate_adapter.py` | 新增 | 驗證 EPS 與仟元金額的 consumer Decimal 轉換、單季／年初至季末／期末快照語意、date-only 次日可見性、unit/scale fail-closed、隔離 marker／正式路徑／alias 防護與 CLI。 |
| `tests/test_build_mops_statement_batch.py` | 新增 | 驗證批次 request 必須明確指定公司／市場／期別、上限先於 fetch 檢查、單一公司失敗不阻塞同批其他公司、部分 manifest／錯誤保存，以及 resume 只重試 failed child 並拒絕不同 operation identity。 |
| `tests/test_plan_mops_statement_universe.py` | 新增 | 驗證首批代表性條件、continuation 自動選取、單市場尾批、verified artifact hash 綁定與 caller exclusion 不冒充完成。 |
| `docs/06_qa/V4_DATA_RECOVERY_2026_09_07.md` | 新增 | 本輪資料現況、根因、差異、測試與剩餘工作。 |

這個修復保持 candidate-only 邊界：抓取成功只代表官方 HTML 已取得並解析，不代表公告日 mapping、PIT 可用日或正式 SQLite 已完成。`available_date` 沒有由營收月份或請求日期推算。若使用 MOPS static snapshot 物化，`fetched_at` 必須是帶時區的 ISO-8601 時間；date-only consumer 一律使用捕捉時間轉換後的下一個台北曆日，若要在同日判斷則必須明確比較完整 timestamp。季度 candidate 另外保存 `announcement_event_timestamp`（listing 事件）、`numeric_available_at`（實際 capture timestamp）與 `numeric_available_date`（date-only 的下一個台北曆日）；目前值只表示本次捕捉所觀察到的內容，沒有宣稱歷史首次公告 PIT。收入表標示 `quarter_single`（單季），現金流標示 `year_to_date`（年初至季末），資產負債表標示 `period_end_snapshot`；EPS 使用 `TWD_per_share`、整數 cents，仟元報表金額則使用整數 TWD／`value_scale=1000`。舊版季度輸出因單位與可得日 schema 不正確，保留原始 bytes 並由 `quarterly/legacy_candidate_status.json` 標示 invalid/superseded，不得再作 numeric use。

### 正式來源接受依賴

目前 gate worker 要沿用以下順序，任何一層失敗都不能進入正式 DB：

1. Snapshot harvester 先驗證 redirect 只導向 `mopsov.twse.com.tw` 的 `/nas/t21/{sii|otc}/t21sc03_<ROC年月>_0.html`，再驗證 body 的市場／期別 marker；每個 row 必須保留 `fetched_at`、市場／期別與 HTML SHA-256 lineage。
2. Availability builder 只從官方 TWSE／TPEx OpenAPI 的 `資料年月`、`公司代號`、`出表日期` 建立 mapping，並以 `source_hash`、`revision=1`、`formal-availability.v2` 和 `official_announcement` 保存證據。對 snapshot candidate 要傳入實際 `--snapshot-captured-at`，以 Asia/Taipei session 可用日作保守 `available_date`。
3. `scripts/validate_monthly_revenue_availability.py` 透過 `load_monthly_revenue_availability_overrides_csv` 檢查允許 source、正式 provenance contract、64 碼 SHA-256、公告／可得日順序、revision chain，以及 `as_of_date + 45 days` 揭露窗口；validator accepted 才能進 backfill。
4. `plan_mops_snapshot_monthly_revenue_backfill` 以 snapshot CSV 全量列數為分母，要求每個唯一 `(stock_code, period)` 都有 mapping、沒有重複／無效列、source lineage 不為空，且 mapping 可得日不早於抓取 session。partial scope 另外要求 manifest 的 candidate／accepted 檔案 SHA-256、自然鍵 SHA-256、accepted／excluded 鍵集合與完整分母一致；任何 diagnostic 都使 `ready_for_apply=false`；CLI apply 仍需明確 confirm 並先備份。
5. 物化後由 `FundamentalSQLiteProvider` 再以獨立正式 mapping 比對 `as_of_date`、`announced_date`、`available_date`；同一月份多個 source version 只選較晚可用日，若同一可用日有不同內容且沒有序時證據則不回傳該月份。apply 保留舊 source version，讓新 hash 不會刪掉舊證據。
6. partial mapping／SQLite 由 `apply_monthly_revenue_recovery` 先寫 `prepared` journal，再在同一 mapping OS lock 下使用 mapping target hash CAS 與 SQLite online backup；DB commit 成功旗標獨立於後續 journal/evidence 寫入，mapping 補償只在未觀測到 commit 且 target hash 未被其他 writer 改變時執行。輸入、目標 resolved path、內容 hash 與 `source_version` 不同時忽略舊 journal／backup，建立新 operation。

季度 numeric candidate 的 source acceptance 仍有明確前置條件：

1. `ajax_t164sb03/04/05` 的 POST 必須固定 `TYPEK`、`co_id`、ROC 年度與季別；每個 response 要驗證官方表名、民國期別 marker、目標欄位 header 與 `t57sb01` listing 的實際期別一致。不能只因 HTTP 200 或 query 參數成功就接受。若 listing 由已保存 raw 提供，`--listing-evidence` 必須記錄 HTTP 200、完整 request URL、raw byte count／SHA-256，並以 parser 重新核對公司、期別、公告列 hash；沒有這份證據的 saved response 只標 `unverified_saved_response`，adapter 不接受為 consumer input。
2. 每張表都要以 response table 的 named-row 分母揭露 accepted／excluded rows；空白或 `-` 只可列為 excluded 並保留科目名稱、列號與原因，不能補成 0 或宣稱完整財報 coverage。未經 XBRL enrichment 的原始 candidate 只有官方中文 item label，不能直接寫入 `fundamental_statement_items`；本輪 1301 新 child 的官方 row code 與 `item_code_lineage_sha256` 已經過隔離 consumer 驗證，但仍屬 research-only。
3. 公告事件與 numeric capture 必須分開：`announcement_event_timestamp` 來自官方 listing；`numeric_available_at` 來自完成所有 numeric／XBRL／listing 讀取與驗證後、帶時區的 `capture_completed_at`，`numeric_available_date` 對 date-only consumer 固定採下一個台北曆日；同日使用必須明確比較 timestamp。`capture_started_at` 與 `capture_completed_at` 都保留，跨台北午夜時不得使用開始時間計算 date-only cutoff。現抓回的內容若日後發生修訂，要以 immutable raw／item hash 與可證明序時建立新 revision；不能把現抓值回填到 listing 首次公告日。
4. 收入單季、現金流年初至季末、資產負債表期末快照的 `period_basis`、`period_start`、`period_end` 必須隨每筆 item 保存，避免把不同累計口徑混成同一個 Q2 值。通過上述檢查後仍須經 source acceptance dossier／readiness gate，這次沒有正式 materialization。

## 官方取數證據

2026-09-07 以現有 MOPS redirect path 做有界唯讀請求，沒有使用替代資料源：

| 市場 | 請求期別 | redirect / static 結果 | HTML 解析列數 | diagnostics | 回應身份 |
|---|---|---|---:|---:|---|
| TWSE | 2026-07 | `200`；`/nas/t21/sii/t21sc03_115_7_0.html` | 992 | 0 | `mops-static-twse-2026-07-sha256-b3f6cdc88c09d3916918a1484a135fd0e07e62e13b7d9d7ad98912a00cc5ae82` |
| TPEx | 2026-07 | `200`；`/nas/t21/otc/t21sc03_115_7_0.html` | 859 | 0 | `mops-static-tpex-2026-07-sha256-a72ae1709b4834bac8330a1158523674c08fd3248ab9c8e0325cf089b6c711b6` |

兩份小型原始回應證據（狀態、官方 static path、body 長度、解碼內容 hash、期別標記與 snippet）位於：

- `output/v4_data_recovery_2026-09-07/twse_2026-07_mops_redirect_evidence.json`
- `output/v4_data_recovery_2026-09-07/tpex_2026-07_mops_redirect_evidence.json`

使用現有 CLI 的 end-to-end candidate 輸出為：

`output/v4_data_recovery_2026-09-07/live_snapshot/mops_monthly_revenue_snapshot_2026-07_2026-07_2026-09-07.csv`

該檔共 1,851 列（TWSE 992、TPEx 859），唯一資料期別為 2026-07，檔案 SHA-256 為 `585ddfcae282030f66459abd997b58294fb4b7a3e0dff3045d7c6540a3b67336`；它是 repo output candidate，不是正式 DB 寫入。

官方 OpenAPI 公告日交集也以隔離 JSON 保存：TWSE 原始回應 1,085 列、TPEx 890 列，與 candidate 的自然鍵交集分別為 990、859。TWSE candidate 的 `2850|2026-07`、`2883|2026-07` 沒有出現在該官方 OpenAPI 回應，沒有可核實的公告日，因此仍保留在完整 candidate、未被補日期：

- `output/v4_data_recovery_2026-09-07/official_api_2026-07/twse.json`
- `output/v4_data_recovery_2026-09-07/official_api_2026-07/tpex.json`
- `output/v4_data_recovery_2026-09-07/official_api_2026-07_evidence.json`

以實際 candidate `fetched_at=2026-09-07T07:17:53Z` 轉為 Asia/Taipei 後，時間落在 15:17、盤後 session 尚未開始；availability candidate 因此把 2026-07 的保守 `available_date` 設為 2026-09-08。validator accepted 1,849 列、0 diagnostics。完整 1,851 列 backfill dry-run 也以全量為分母，顯示 `normalized_record_count=1849`、`snapshot_unmatched_mapping_count=2`、`ready_for_apply=false`，沒有部分寫入。

為驗證可物化的明確子集，另以 mapping 自然鍵產生 `accepted_scope`（1,849 列；排除的兩列與原因寫在 `scope_manifest.json`）。manifest 綁定完整 candidate 1,851 列、accepted 1,849 列、excluded 2 鍵集合及 candidate／accepted 檔案與鍵集合 hash；candidate 與 accepted 的自然鍵集合相加後完整相等，沒有只靠 row count 的自填證明。只在 repo output 的隔離 SQLite 測試：coordinator dry-run `ready_for_apply=true`、normalized 1,849；apply 1,849，使用相同 source identity 再 apply 一次仍為 1,849，最終 SQLite 仍為 1,849 列、1,849 個 `(stock_code, period)`、唯一期別 2026-07、唯一可得 session 日 2026-09-08。`FundamentalSQLiteProvider` 對 `decision_date=2026-09-07` 回傳 0 筆，對 2026-09-08 回傳 1 筆（以 `1101` 抽查），證明沒有在 session 前提前使用。隔離 DB、備份、journal 與 evidence 位於 `output/v4_data_recovery_2026-09-07/isolated/`，不涉及正式 DB。

### 季度財報 numeric 證據

本輪以同一官方 MOPS host 做兩個公司的 bounded 唯讀請求；三個 t164 numeric response 都以表名、民國期別 marker、目標欄位 header 與 t57 listing 期別交叉確認為 2026-Q2／2026-06-30。每個 accepted row 的原始表格單位是「新台幣仟元」；一般金額轉成整數 TWD（`value_scale=1000`），EPS 以整數 cents/share（`value_scale=100`）保存。完整 statement source、listing、candidate、manifest 與 SHA-256 位於各 run 目錄；摘要位於 `output/v4_data_recovery_2026-09-07/quarterly/quarterly_probe_summary.json`。XBRL hidden metadata 的公司、年度、季度、合併範圍與市場均以 parser 精確比對，正文出現另一公司代號或比較期年份不會放行。

| 市場／公司 | 官方請求 | t57 公告事件 | 實際 numeric capture | date-only `available_date` | accepted／excluded（資產／損益／現金流） | candidate rows |
|---|---|---|---|---|---:|---:|
| TWSE／2330 | `TYPEK=sii`、`ajax_t164sb03/04/05`、115 年第 2 季 | `2026-08-14T13:59:44+08:00` | `2026-09-07T08:58:27.223577+00:00` | `2026-09-08` | `57/9`、`37/7`、`78/3` | 172 |
| TPEx／6488 | `TYPEK=otc`、`ajax_t164sb03/04/05`、115 年第 2 季 | `2026-08-07T15:22:28+08:00` | `2026-09-07T08:58:04.544945+00:00` | `2026-09-08` | `48/9`、`32/6`、`59/3` | 139 |

兩個候選均保留原始列分母與空白列 excluded 清單，沒有把空白值補成 0，也沒有將 t57 公告事件時間回填為 numeric 可得時間。隔離 consumer adapter 以 `numeric_available_at`／date-only `available_date` 驗證：TWSE 172 列與 TPEx 139 列在 2026-09-07 都是 0 列可見，在 2026-09-08 分別是 172 與 139 列可見。

代表值由 adapter 轉換後如下，並可在 `quarterly/quarterly_isolated_materialization_evidence.json` 的兩次 CLI evidence 逐列核對：

| 市場／公司 | 財報／科目 | raw value | consumer value | unit／scale | period start ～ end／basis |
|---|---|---:|---:|---|---|
| TWSE／2330 | 資產負債表／現金及約當現金 | 3,134,218,213 | 3,134,218,213,000 | `TWD`／1000 | — ～ 2026-06-30／`period_end_snapshot` |
| TWSE／2330 | 綜合損益表／營業收入合計 | 1,270,380,250 | 1,270,380,250,000 | `TWD`／1000 | 2026-04-01 ～ 2026-06-30／`quarter_single` |
| TWSE／2330 | 綜合損益表／基本每股盈餘 | 27.25 | `27.25` | `TWD_per_share`／100 | 2026-04-01 ～ 2026-06-30／`quarter_single` |
| TWSE／2330 | 現金流量表／繼續營業單位稅前淨利（淨損） | 1,550,229,773 | 1,550,229,773,000 | `TWD`／1000 | 2026-01-01 ～ 2026-06-30／`year_to_date` |
| TPEx／6488 | 資產負債表／現金及約當現金 | 23,776,098 | 23,776,098,000 | `TWD`／1000 | — ～ 2026-06-30／`period_end_snapshot` |
| TPEx／6488 | 綜合損益表／基本每股盈餘 | 7.90 | `7.90` | `TWD_per_share`／100 | 2026-04-01 ～ 2026-06-30／`quarter_single` |
| TPEx／6488 | 現金流量表／繼續營業單位稅前淨利（淨損） | 6,931,628 | 6,931,628,000 | `TWD`／1000 | 2026-01-01 ～ 2026-06-30／`year_to_date` |

舊版 TWSE／TPEx statement candidates 的 raw bytes 沒有改寫；因原 schema 把仟元／EPS 混用且把公告日期當可得日，`quarterly/legacy_candidate_status.json` 將其標記為 invalid 或 superseded。具官方 row code 的新版 immutable runs 為 `v4-quarterly-statement-2026q2-twse-2330-r8`（172）與 `v4-quarterly-statement-2026q2-tpex-6488-r6`（139）；兩包的 `files`／`raw_files` 共 9 個 hash 均核對成功，且 `files` 排除 `run-manifest.json` 自引用。新版 candidate 仍固定 `research_only=true`、`formal_oos_allowed=false`、`downstream_eligibility=none`，沒有寫入正式 `fundamental_statement_items`。

用 `scripts/materialize_mops_statement_candidates.py` 將這兩包寫入 repo output 的 `isolated_statement_consumer_v4.db` 後，第一次 materialization 為 311 inserted／311 sidecar，第二次為 0 inserted／311 idempotent existing；同一 provider 對 2026-09-07 回傳 0 rows、對 2026-09-08 回傳 311 rows（2330=172、6488=139）。provider 讀回 EPS 為 TWSE／2330=`Decimal("27.25")`、TPEx／6488=`Decimal("7.90")`，並保留 `period_basis`、單位與 raw hash 在 sidecar。SQLite 檔旁的 `.research-only.json` marker、candidate hash 與完整 evidence 均在同一 output 目錄；正式 DB 與 D 槽 raw 未寫入。

第二個 bounded slice 實際執行新版批次入口，明確輸入 2317／sii／2026-Q2 與 5274／otc／2026-Q2。第一個批次 manifest `v4-quarterly-batch-2026q2-slice2r1-manifest.json`（SHA-256 `b5b881bd2ff25fd67bd34aae0cbb1e6b99138f7aa6b7736690191185f9c5d282`）保存 5274 成功 127 列與 2317 兩次 `NameResolutionError`／errno 11001；`--resume` 只再次嘗試失敗的 2317，沒有重抓已成功 child。該 5274 child 是較早缺 `item_code_lineage_sha256` 的 contract 版本，保留但沒有送入 materializer。

以官方 t57 raw fallback 重跑後，`v4-quarterly-batch-2026q2-2317-fallback-r1-manifest.json`（SHA-256 `a79a2e64564a89ab83706cb87a8c527f219eadbbde03d3c974e4397a6abcd9f1`）保留第一次 row-code alias 失敗與第二次成功，產生 2317／2026-Q2 189 列；`v4-quarterly-batch-2026q2-5274-contract-r1-manifest.json`（SHA-256 `86b6baa531499ddd52ca1b322bbeb07b3967af65575a3c3b53733601ab798966`）產生修正 contract 的 5274／2026-Q2 127 列。兩個新版 candidate SHA-256 分別為 `3a46aa23c6b6db29cda434b865c0ee665723c6b4454878a676e33dbc4706f14c` 與 `4e6f25cb2c9a97210863c6281259becfed650253b701dd713bd0c71e95a40010`；合計 316 列、三類 statement、每列均有官方 XBRL row code 與 `item_code_lineage_sha256`。這只是 2 家公司的研究切片，不能推論全市場 coverage。

2317 fallback 的官方來源 custody 另以一次受控的單一 GET 取得可重現時間：`official-fallback-t57-2317-115q2/t57sb01_2317_115_refetch.html` HTTP 200、4,584 bytes、SHA-256 `8933607bab446cdb2c246d55edef4a679f12532f1a0d813f9e8a379ad941907c`；請求起訖為 `2026-09-07T10:38:39.565732+00:00` ～ `2026-09-07T10:38:40.401662+00:00`。HTML parser 實際解析出 2317／2026-Q2／period end 2026-06-30，官方上傳事件為 `2026-08-14T17:47:54+08:00`、文件 `202602_2317_AI1.pdf`、correction `none`，沒有用請求日期推算公告日。合法 JSON `evidence.v3.json`（SHA-256 `a5e85b8ac38a0205186b97db0e03e36c72d971345965166e696e356b896eb847`）以 request URL、HTTP metadata、raw hash、listing row hash、fallback candidate SHA 與 child manifest SHA 綁定；同資料夾原有 evidence.json／xbrl-evidence.json 的內容尾端含字面反斜線 n，保留作歷史輸入，不能再當機器 JSON。

XBRL raw `mops_t164sb01_xbrl_2317_115Q2.html` 為 1,825,073 bytes、SHA-256 `db265198cec14339a542d7e85ddea907eeec2c7ddb2c9be278aea509feb1d9b4`；隱藏 metadata 精確為公司 2317、年度 2026、季度 2、`Consolidated report`、`Listed company`。合法 `xbrl-evidence.v2.json`（SHA-256 `286df0c19c609c25954d829fe44c5031808f2ad4a97c15ec9ac2faf29889f12d`）明列 raw／candidate／child manifest hash；其原始檔案建立時間只作本機觀察，HTTP capture timestamp 未知，沒有冒充官方抓取時間。

以兩個新版 candidate 送入隔離 consumer：`quarterly/quarterly_isolated_materialization_slice2_first.json` 回報 316 main／316 sidecar、inserted 316、duplicate 0；同候選重跑的 `quarterly/quarterly_isolated_materialization_slice2_retry.json` 回報 inserted 0／existing 316。provider 在 decision date 2026-09-07 回傳 0 列，在 2026-09-08 回傳 316 列（2317=189、5274=127），所有 316 列的 item-code source 為官方 XBRL row code。代表 EPS 讀回為 2317=`Decimal("4.27")`、5274=`Decimal("44.27")`，period basis／unit metadata 留在 sidecar；root coordinator 另在全新 TEMP consumer 交叉核對相同 316 main／sidecar、9/7=0、9/8=316 與重跑 inserted=0。合併證據 `quarterly/quarterly_isolated_materialization_slice2_evidence.v2.json` SHA-256 為 `09637106ee90c894c9fabdb907861cc56dee04b687c10d4b7199371b6e86346c`。

本輪 evidence-aware replay 與隔離 consumer 交接：

- v4-quarterly-batch-2026q2-2317-replay-r1-manifest.json 最終 SHA-256 為 6500b1fde7a05313be6725f53f91f3fd8cb312e1c7c734bef1dbee0a34478dd9；同一 operation identity 的第 1 次 child commit 在 immutable 目錄替換階段遇到 Windows WinError 5，manifest 保留該 failed attempt，第一次 --resume 成功建立 2317 child，第 2 次 --resume 只做既有 child hash／manifest 驗證並記錄 last_verified_at。最終 batch 為 succeeded_count=1、failed_count=0，沒有再次抓取已保存的資料。
- 新 child 路徑為 quarterly/v4-quarterly-batch-2026q2-2317-replay-r1-sii-2317-2026q2/statement-pit-candidate.json，candidate SHA-256 為 daff6e3689a40e75e58462adefc413a941cf82dfef09ba8f3a20e78a4edd1f8c，child manifest SHA-256 為 68fc2d720cfe66f85e9058cb2d6865e25959082f4558cf1fc9b254fc3bdb16e0；189 rows、6 個 raw／evidence 檔。statement raw 由既有 immutable 官方 response replay，capture_mode=previously_saved_official_response；本次約 0.16 秒是離線解析與驗證，不是重新 live 抓三張 t164 表。
- 新 candidate 的 capture_started_at=2026-09-07T10:51:59.031271+00:00、capture_completed_at=2026-09-07T10:51:59.198874+00:00，numeric available_date=2026-09-08；t57 listing 使用合法 evidence.v3.json 的 verified_saved_response，其官方 raw／HTTP metadata／2317-Q2 listing event／candidate lineage 綁定均通過。
- 將 replay 2317 child 與既有 contract 5274 child 寫入新的 quarterly/isolated_statement_consumer_v4_slice2_replay.db：quarterly/quarterly_isolated_materialization_slice2_replay_first.json 回報 316 inserted／316 sidecar、duplicate 0，retry quarterly/quarterly_isolated_materialization_slice2_replay_retry.json 回報 0 inserted／316 existing；SQLite quick_check=ok。provider 在 2026-09-07 回傳 0、2026-09-08 回傳 316（2317=189、5274=127），EPS 讀回 2317=Decimal("4.27")、5274=Decimal("44.27")，unit／period basis 仍在 sidecar；兩個候選與 DB 都維持 research-only，未觸碰正式 DB 或 D 槽 raw。

### 2026-Q2 universe 首批、金融型態修復與可持續續跑

本片使用已保存的官方公司 registry `D:/Min/Python/Project/FA_Data/meta_data/companies.csv` 建立可重跑 universe plan；檔案 SHA-256 為 `a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`，2343 rows（TWSE 1094、TPEx 890、emerging 359）。依 plan 的 eligible 規則，TWSE／TPEx 四位股票代號共 1974 家；排除 emerging 359、非四位／DR 6、DR 產業 4，沒有把 ETF 或其他非公司資料混入。這是 registry 分母，並不表示已完成全市場財報 coverage。

首批 plan `quarterly/mops-statement-universe-2026q2-initial-r1.json`（檔案 SHA-256 `aa20788c91dab99afe189a583a0360ba554bda9029851dedd6e65243dbe3b11c`；content `sha256:33b88b8b4348fcdb7c10bc485be5df5d8df897d8169fad42300cf459d40162c1`）採 `representative_initial` profile，8 個 request 為 2881／1101／1301／2603／2303（TWSE）及 3105／3293／6547（TPEx），涵蓋兩市場、7 個產業並包含金融保險 2881。batch driver 固定每批最多 8 家、每家公司最多 2 次，逐列先 checkpoint 再 fetch，成功 child 以 candidate／manifest／raw hash 綁定；首批 manifest `quarterly/v4-quarterly-batch-2026q2-universe-initial-r1-manifest.json`（SHA-256 `ec250303c1184121a0bbc3db255900ef7b7f128781359f9503503b393e4c3f17`）最後為 6 succeeded、2 failed，12／16 attempts，成功 rows 912（1101=175、2603=178、2303=179、3105=145、3293=122、6547=113）。因此不能把首批寫成 8/8；2881 與 1301 的初次失敗均保留在 manifest。

失敗診斷保留實際官方回應。2881 的 `quarterly/failed-quarterly-diagnostic-r1/2881-sii-2026q2-balance-sheet.html` 為 mopsov `ajax_t164sb03` HTTP 200、9603 bytes、SHA-256 `1a8297e2011c95f63666efab04aef22f0e277a563dd700814747086d9783bef2`；正文是公司選擇表，同時列出精確母公司 2881 與子公司 28810001，故 selector 只接受顯示代碼精確等於請求代碼且唯一的 onclick `co_id`。另一次官方 mopsov step=2 詳細表 raw 位於 `quarterly/failed-quarterly-diagnostic-r3/2881-sii-2026q2-balance-sheet-step2.html`，其有效 JSON evidence 為 `evidence.v2.json`（SHA-256 `38fd5fd2c6ed44491be24c14f45f36fc15437b677b8967e04233062bd0101eaa`）：HTTP 200、56083 bytes、raw SHA-256 `0d144dd69e8ca1ede1ef8f84dac34a74288422c7c2c33cb37a8bb4d0e78a178b`，實際表名「合併資產負債表」、期別 `115年06月30日`、accepted numeric rows 56；這證明 selector follow-up 可取得母公司詳細表。原 `doc.twse.com.tw` listing 仍因本機 DNS `Errno 11001` 無 HTTP response；mopsov／mops alternate t57 probes 的 HTTP 404 只記為 alternate host probe，不能據此宣稱官方原始公告不存在。2881 尚未完成 t57 listing gate，不能列入 verified completed。

另以系統 `Resolve-DnsName` 觀察到 `doc.twse.com.tw` 的 A record 為 `163.29.17.136`，同一工作階段普通 requests 在連線前被 `WinError 10013` 阻擋；依標準升權審核重跑既有 `_fetch_listing_response` 的單一 2881 listing GET，仍在連線前以 `NameResolutionError`／`Errno 11001` 失敗，沒有 HTTP response 或 raw。此結果保存在有效 JSON `quarterly/failed-quarterly-diagnostic-r4/evidence.json`（SHA-256 `0d63b93aef09260dfb506be3ed52281bd72c4275bc6e25a88ddfd75e4823a612`）；該 evidence 明確標示 `response_received=false`、`raw_saved=false`，只能作 transport 診斷，不能作公告事件或可得日證據。這確認阻塞在執行環境 transport，不是官方公告不存在。

另以 Chrome 對同一官方 URL 做一次唯讀 GET，先成功呈現「電子資料查詢作業」並以精確欄位列出 `2881／富邦金` 及 48 家相關公司／子公司；沿該官方頁面的單一母公司查詢按鈕續查後，返回真正 publication listing：`2881`、`115 年 第二季`、`IFRSs合併財報`、`202602_2881_AI1.pdf`、4,099,984 bytes、上傳 `115/08/28 14:09:26`、更補正「無」。selector DOM 保存於 `quarterly/browser-doc-2881-r1/2881-sii-2026q2-browser-dom.html`（SHA-256 `07454f41f32554a807e74068fe226a3cce810d633210a9e3119484d1207438fd`），publication DOM 保存於 `2881-sii-2026q2-browser-announcement-dom.html`（SHA-256 `7807695fd25840d2347f32d2d321fab6541c040a443e63a291d698c8f5ae7e04`），機器欄位與 hash 綁定於 `evidence.json`。瀏覽器 DOM 序列化不等同 HTTP raw bytes；因此這段記錄的是 r13 前的 numeric selector staging，當時仍維持 `listing_gate=publication_listing_observed_browser_only`、`pit_credit=none`，只有 balance sheet 56 rows，不能交給 custody adapter。

1301 的 `quarterly/failed-quarterly-diagnostic-r1/1301-sii-2026q2-xbrl.html` 為官方 XBRL HTTP 200、759611 bytes、SHA-256 `8de9d8c66c65cf639da8d109787ae4fea426d0f13dfe1a395ec58e390d0e8423`，hidden metadata 精確為公司 1301／2026／Q2／Consolidated report／Listed company；虛擬通貨列的官方 code 是 3199，顯示名稱為 `權益─具證券性質之虛擬通貨合計`、reported value 0。原 1301 income raw `failed-quarterly-diagnostic-r2/1301-sii-2026q2-income.html` HTTP 200、32606 bytes、SHA-256 `f5c9b20071fab6537eb12f2fc83eed16e43a646a096f77648bffe8aabfebfda7`，同名 continuing EPS 列有 9710 basic／9810 diluted；修補 parser 只對此已核對名稱在 income statement 的出現序號消歧，並將其視為 `TWD_per_share` cents，沒有把一般金額列乘錯 1000。

修補後建立新 immutable child `quarterly/v4-quarterly-universe-2026q2-1301-codefix-r1-sii-1301-2026q2/`。batch manifest `quarterly/v4-quarterly-batch-2026q2-1301-codefix-r1-manifest.json` SHA-256 為 `616b631a5dbcc77961ffd12d31b6f3b6122b0978cff947f2de5cf20432aaf1f1`，1 request／1 successful attempt；child candidate 158 rows，candidate SHA-256 `471a3db0c8a1b437536414ce235dc39420ab59ed459242aebdac7b856acacefa`，child manifest SHA-256 `302ec89d8c8223470b88e8260d225c5d1bc25c9cbe4a017799edb668e3c64e5f`。三類 accepted rows 為 balance 56、income 35、cash flow 67；period 分別為 2026-06-30 `period_end_snapshot`、2026-04-01～06-30 `quarter_single`、2026-01-01～06-30 `year_to_date`，所有 numeric rows 的保守 `available_date` 為 2026-09-08。1301 EPS 9710／9750／9810／9850 均以 raw `1.67`、integer cents `167`、consumer `Decimal("1.67")` 保存；3199 以 TWD／scale 1000 保存。

以首批 6 個成功 child 加入 1301 新 child 建立隔離 consumer：`quarterly/isolated_statement_consumer_v4_universe_codefix_r1.db`（檔案 SHA-256 `857f9f8b07eed76dca7733d93f9de9d3d315570c178fc5ebe4cefda371ad269d`）及 marker。這裡的 7 家是本輪 universe slice（首批 6 家加 1301 修正版）；既有 2330／6488／2317／5274 四家另有先前已驗收的 immutable child，故 plan 的 verified 總數為 11，不應把本輪 7 誤報成全體只有 7。第一次 evidence `quarterly/universe_codefix_materialization_first.json` SHA-256 `4f8dec3ed9e4c3fb2908d0b002be6f30b180f66a983a495b46517548cab60947` 回報 input／main／sidecar 1070／1070／1070、duplicate 0、inserted 1070；第二次 `quarterly/universe_codefix_materialization_retry.json` SHA-256 `1d8857fc86c07d8999237d996d11183e7389bac64871dbf07fd91432b3e0a71e` 回報 inserted 0／existing 1070。所有 1070 rows 的 item-code source 是官方 `mops.t164sb01.xbrl.row_code`；provider 2026-09-07 為 0、2026-09-08 為 1070（1301=158），1301 provider EPS 讀回 1.67，sidecar 保留 unit、period basis 與 raw lineage。正式 DB、D 槽 raw 與正式 mapping 均未寫入。

修復後 continuation plan `quarterly/mops-statement-universe-2026q2-continuation-r2.json`（檔案 SHA-256 `3ff3f4ac1f5c9865032741bdaeb63f2437dd56ac6a2db1e16b157792a35f775d`；content `sha256:677c72c76623f21f3add19961c5f88ca8bb556c1e405077bbe9f02a457f8dfca`）是在 2881 child 完成前建立，當時綁定 11 個 verified completed keys（含 1301，不含 2881），eligible 1974、verified 11、remaining selectable 1963、verified coverage 55 bp。未指定公司時依 `(registry_market, stock_code)` 穩定排序自動選出下一批 8 家：1240、1259、1264、1268、1294、1295、1336、1565；該批已建立 checkpoint，僅 1240 消耗一次 transport attempt，其餘 7 家因來源 circuit breaker 保留 pending，沒有成功 child。`caller_excluded` 不計完成；`--resume` 只驗證既有成功 child、重試 pending／failed，且不可重用不同 operation identity。r13 child 完成後，續跑前需重新產生綁定 12 個 verified artifact 的新 plan；後續可逐批續跑，尾批可只有單一市場，不會每批強迫 2881 或兩市場條件。

已依此 plan 執行一次新批次 `quarterly/v4-quarterly-batch-2026q2-universe-continuation-r2-manifest.json`：8 requests、每家公司最多 2 次、每一官方來源 transport 失敗上限 1；manifest SHA-256 `c8c20fba17efb9b006ca0441a88cdc0a1bfeddc7330aecfee38b533201425251`。第一家公司 1240 的 `doc.twse.com.tw` listing 在連線前以 `NameResolutionError`／`Errno 11001` 失敗後，來源 circuit breaker 開啟；因此本輪只消耗 1／16 attempts、保存 1 failed、7 pending，沒有建立 child，也沒有重抓已完成的 7 家。失敗 event、來源、checkpoint 與 pending 原因均在 manifest；下次只可用同一 identity `--resume` 開新 transport window。

### 2881 2026-Q2 完整三表／XBRL child 與隔離 consumer

在先前 browser selector／publication observation 的基礎上，使用同一官方 mopsov t164 三表與 XBRL endpoint，並採已保存的 2881 browser DOM 作 t57 公告事件證據，建立 immutable child `quarterly/v4-quarterly-browser-2881-r13-sii-2881-2026q2/`。child candidate `statement-pit-candidate.json` 的 SHA-256 為 `2d287b16476a29cd826785e352beef0473fcb69a80367471659848217019bcfb`；run manifest 宣告的 11 個 `files`／`raw_files` 均逐一存在且 SHA-256 相符，未包含自引用的 `run-manifest.json`。本 child 保留 `research_only=true`、`formal_oos_allowed=false`，沒有寫入正式資料庫。

候選共 189 筆、189 個唯一官方 XBRL row code，按報表分為資產負債表 56、綜合損益表 51、現金流量表 82；未通過命名／數值條件的 4／3／3 列保留於各表的 excluded coverage，不以跳過列冒充完整報表。資產負債表為 2026-06-30 `period_end_snapshot`；綜合損益表為 2026-04-01～2026-06-30 `quarter_single`；現金流量表為 2026-01-01～2026-06-30 `year_to_date`。EPS 官方 row code `70000` 以 cents/share 保存，candidate raw `4.27`，隔離 consumer 讀回 `Decimal("4.27")`；一般金額列的 scale／unit 與期間語意另在 sidecar 保留。

此 run 的 numeric capture `capture_started_at=2026-09-07T12:31:33.715203+00:00`、`capture_completed_at=2026-09-07T12:31:47.661254+00:00`，numeric `available_date=2026-09-08`。t57 listing 只作 browser DOM observation，不宣稱 HTTP raw custody 或歷史 PIT：官方 URL 為 `https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&mtype=A&co_id=2881&year=115`，結果列為 `202602_2881_AI1.pdf`、上傳 `2026-08-28T14:09:26+08:00`，browser observation 為 `2026-09-07T12:00:36.646Z`；child 內 selector DOM SHA-256 為 `07454f41f32554a807e74068fe226a3cce810d633210a9e3119484d1207438fd`，publication DOM SHA-256 為 `7807695fd25840d2347f32d2d321fab6541c040a443e63a291d698c8f5ae7e04`，兩者的 strict UTF-8／Big5 replay 與官方公司／期別／結果 URL 驗證均通過。

以 `scripts/materialize_mops_statement_candidates.py` 將此 child 寫入隔離資料庫 `quarterly/isolated_statement_consumer_v4_2881_browser_r13.db`：第一次為 189 inserted、189 main／189 sidecar、duplicate 0；同候選重跑為 0 inserted、189 idempotent existing。SQLite `PRAGMA quick_check` 為 `ok`，三類讀回仍為 56／51／82；provider 在 decision date 2026-09-07 回傳 0 筆、2026-09-08 回傳 189 筆，EPS 讀回 `Decimal("4.27")`。首次與重跑 evidence 分別為 `quarterly/quarterly_isolated_materialization_2881_browser_r13_first.json` 與 `quarterly/quarterly_isolated_materialization_2881_browser_r13_retry.json`。這是隔離 research consumer 驗證，未寫入正式 DB、D 槽或原始資料。
因此代表性 initial selection 的 8 家目前均各有通過驗證的 immutable child：原 initial manifest 的 6 家、1301-codefix-r1 與本段 2881-r13；原 initial manifest 保留當時的 6 succeeded／2 failed 歷史狀態，沒有被覆寫成 8/8。這裡的 8/8 是逐家公司後續 child 驗收結果，不是把原批次失敗紀錄改寫。

## 驗證

- 2881-r13 交付後重跑季度 focused suite：`tests/test_build_mops_statement_pit_candidate.py` 與 `tests/test_mops_statement_candidate_adapter.py` 為 45 passed、1 skipped；`tests/test_build_mops_statement_batch.py` 與 `tests/test_plan_mops_statement_universe.py` 為 19 passed。相關 parser／batch／universe／adapter source 以 mypy 檢查無錯誤，執行模組與測試檔 py_compile 通過。這些最新結果取代本節稍早的 31／50 passed 摘要；skip 是 Windows symlink 環境限制，junction 負例已由 coordinator 實測通過。

- 本次 batch driver 回歸測試為 14 passed；新增同一來源 transport 失敗 circuit breaker、pending 保留與 `--resume` 新窗口測試。`failed-quarterly-diagnostic-r4/evidence.json` 另以 `json.loads` 讀回驗證成功。
- universe continuation 實際試跑：以 continuation plan 的 8 家、每家最多 2 次、來源 transport 失敗上限 1 執行；1240 的 `doc.twse.com.tw` `NameResolutionError` 開啟 circuit breaker，結果為 0 succeeded、1 failed、7 pending、1／16 attempts。沒有建立 raw／candidate child；成功的 7 家未重抓，後續可沿 manifest `--resume` 續跑。

- `.\.venv\Scripts\python.exe -m pytest tests/test_build_mops_statement_pit_candidate.py tests/test_mops_statement_candidate_adapter.py -q -o addopts=`：31 passed、1 skipped；涵蓋官方 exact identity、錯公司數字碰撞、錯期別比較欄、保存 t57 evidence 的 raw hash／請求驗證、完成時間跨台北午夜、manifest 全檔／raw hash、隔離路徑 marker、EPS cents、period basis、date-only 次日可見性、既有 provider 讀回與 CLI，以及金融 alias 的唯一性／金額匹配 fail-closed。skip 是 Windows 環境不允許建立 symlink；formal DATA_ROOT 路徑負例仍在同一測試套件通過，junction alias 已由 coordinator 在全新 TEMP/formal 根實測拒絕。
- `.\.venv\Scripts\python.exe -m pytest tests/test_build_mops_statement_batch.py tests/test_plan_mops_statement_universe.py -q -o addopts=`：19 passed；批次 driver 只接受明確公司／市場／期別，單批最多 8 家，逐公司保存 child result／hash／錯誤，並驗證失敗後續跑、saved listing evidence 轉交、不同 operation identity 拒絕與 continuation 尾批／caller exclusion。
- 合併季度 parser／adapter／batch／universe：50 passed、1 skipped；`mypy --explicit-package-bases scripts/build_mops_statement_pit_candidate.py scripts/plan_mops_statement_universe.py scripts/build_mops_statement_batch.py data_module/mops_statement_candidate_adapter.py` 無錯誤，相關執行模組 `py_compile` 通過。

- `.\.venv\Scripts\python.exe -m pytest tests/test_monthly_revenue_snapshot_harvester.py tests/test_monthly_revenue_availability_history.py tests/test_monthly_revenue_availability_merge.py tests/test_monthly_revenue_backfill.py tests/test_monthly_revenue_backfill_cli.py tests/test_monthly_revenue_recovery.py tests/test_fundamental_sqlite_provider.py -q -o addopts=`：既有 coordinator suite 79 passed；另以 mypy 檢查修改後 Python source、以 py_compile 檢查本輪執行模組均通過。
- live CLI：`scripts/fetch_mops_monthly_revenue_snapshot.py --start-period 2026-07 --end-period 2026-07 --markets twse,tpex --output-dir output/v4_data_recovery_2026-09-07/live_snapshot --fetch-date 2026-09-07 --no-save-html --sleep-seconds 0`；官方兩市場均取得，1,851 列、0 diagnostics。
- `scripts/build_monthly_revenue_availability_history.py` 以官方 OpenAPI 交集和 `--snapshot-captured-at 2026-09-07T07:17:53Z` 產生 candidate：1,849 accepted rows、missing 2、0 builder diagnostics；`scripts/validate_monthly_revenue_availability.py` 回報 `valid=true`、accepted 1,849、0 diagnostics。
- 完整 1,851 列 candidate 的 backfill dry-run 回報 `ready_for_apply=false`、raw 1,851、normalized 1,849、unmatched mapping 2；明確 1,849 列 accepted scope 的 recovery dry-run／apply／同 source identity 重跑均成功，兩次 apply 各回報 1,849，隔離 DB 最終仍為 1,849 列。recovery 測試另覆蓋 prepared journal crash/retry、DB commit 後 journal/evidence 失敗、CAS 補償保留並行 writer，以及不同 snapshot／DB identity 不重用舊 mapping backup。
- consumer 查核：隔離 DB 在 `decision_date=2026-09-07` 對 `1101` 回傳 0 筆，在 `2026-09-08` 回傳 1 筆；同一可得日不同內容版本的正、反向插入測試都 fail-closed。
- 季度 adapter live 查核：TWSE／2330 172 rows、TPEx／6488 139 rows 均成功轉成帶 unit／period metadata 的 Decimal rows；兩者在 date-only `decision_date=2026-09-07` 均為 0 rows，`2026-09-08` 分別為 172／139 rows。EPS 27.25／7.90 分別以 2725／790 cents/share 保存。
- 季度新版 immutable run 的 `files` 與 `raw_files` 9 個 hash 逐一核對成功；隔離 materializer CLI 第一次／重跑 evidence 位於 `quarterly/quarterly_isolated_materialization_v4_first.json`、`quarterly/quarterly_isolated_materialization_v4_retry.json`，合併摘要為 `quarterly/quarterly_isolated_materialization_evidence.json`。311 主表／311 sidecar、2330=172、6488=139，EPS 讀回 27.25／7.90。
- 隔離 guard 負例：全新 TEMP 下既有無 marker DB、DATA_ROOT 內 formal DB 與其 symlink 均拒絕且不建立 formal/sqlite 目錄；junction alias 亦由 coordinator 實測拒絕。materializer 的 `formal_db_written=false` 僅在 guard 通過且 research-only marker 綁定後回報。
- 批次擴展試跑以 2317／sii 與 5274／otc 的 2026-Q2 為明確輸入；官方 t164 numeric／XBRL 請求在 2317 先完成後，t57 listing gate 對 `https://doc.twse.com.tw/server-java/t57sb01` 發生 DNS `NameResolutionError`（無 HTTP status，socket host resolution 失敗），新版 driver 將該失敗與 5274 成功 127 列保存在 partial manifest；`--resume` 只重試失敗的 2317。之後以保存的官方 t57 raw 完成 2317 fallback 189 列，再由 contract 修正後的 5274 127 列完成隔離 consumer；失敗 attempt、成功 child hash 與 immutable run 都保留，未把早期缺 contract child 送入 materializer。
- 測試採 `tmp_path` 與 monkeypatch 的隔離雙根；live CLI 的輸出只在 repo `output`，未連接正式 DB。
- 正式 DB 查詢使用 SQLite `mode=ro`；沒有執行 migration、insert、update、delete、vacuum 或 backfill。

## 正式 D 槽切換計畫（本輪只做唯讀）

正式目標固定為：

- D:/Min/Python/Project/FA_Data/meta_data/monthly_revenue_availability.csv（目前 1,832 列、217,652 bytes）。
- D:/Min/Python/Project/FA_Data/sqlite/twstock.db（目前 246,331 列；2026-06 有 1,832 列；檔案 3,403,472,896 bytes）。
- 本任務專用備份目錄為 D:/Min/Python/Project/FA_Data/sqlite/backups/v4_data_recovery_2026_09_07；只建立唯一檔名，不觸發既有 backup retention 清理。SQLite 備份使用 online backup API，失敗時只做 transaction rollback。

對正式 mapping 的直接唯讀 merge dry run：existing=1,832、candidate=1,849、added=1,849、unchanged=0、conflict=0、merged=3,681、ready_for_apply=true。這只表示 2026-07 的 1,849 筆公告 mapping 可合併預覽，沒有寫入 D 槽。

對完整 1,851 筆 snapshot 的 backfill dry run：raw=1,851、normalized=1,849、unmatched_mapping=2、duplicate=0、invalid=0、ready_for_apply=false；2850|2026-07 與 2883|2026-07 仍缺官方公告日證據。受 strict scope manifest 綁定的 1,849 筆 accepted partial scope 則為 raw=1,849、normalized=1,849、unmatched_mapping=0、ready_for_apply=true；可作明確 partial 更新，必須保留 full denominator=1,851 與 excluded=2，不得宣稱完整 candidate 已全數入庫。

以 D 槽實測可用空間 354,755,321,856 bytes 計，單次 mapping 與 DB 備份合計約 3,403,690,548 bytes，低於可用空間。正式切換前仍需重新取得任務專用備份檔名、SHA-256 與 apply 前後 row／period／source_version 差異，並保留 journal／evidence。

正式切換的驗收順序是：先保存現有 mapping／DB 的檔案身份，選定並記錄 accepted partial scope 與 excluded 2 鍵，備份兩個正式目標，再由 recovery coordinator 以同一 OS lock、SQLite online backup、target CAS 與 durable journal 執行；完成後重跑 provider 的歷史 decision invariant、9/7 不可見與 9/8 可見檢查。此輪沒有執行上述 D 槽 apply。

## 剩餘工作

1. 2026-07 月營收已有 1,849 筆通過 validator 的 accepted partial scope，可沿 recovery coordinator 作受控 partial 更新；full denominator 仍是 1,851，2850|2026-07 與 2883|2026-07 仍 excluded，不能宣稱完整更新。本輪不改 D 槽。
2. 2026-08 是否已公告須依實際查詢日與 MOPS 回應確認；不能把月份推算當成已發布證據。
3. 季度財報前段曾記錄 12 家可驗證 child；截至 continuation r3-r20，另有 1570、1580、1584、1586、1591、1593、1595、1599 八家完成隔離 consumer，累計 29 家可驗證 child（前述首批 6 家、1301 修正版、2330／6488／2317／5274，以及本段新增的 2881-r13）；2881 的隔離 consumer 為 189 rows，先前 7 家 slice 的隔離 consumer 為 1,070 rows，兩者皆維持 research-only。2881-r13 的 t57 仍是 browser DOM observation、沒有 raw HTTP listing custody；但三表與 XBRL 已各自通過身份／期別／官方 row code／單位／期間檢查，且已完成隔離物化，因此可列入 verified child，不代表正式 DB 或全市場完成。原 continuation-r2 plan 建立時尚未包含 2881，當時 eligible 分母 1,974、remaining selectable 1,963，下一批 8 家為 1240、1259、1264、1268、1294、1295、1336、1565，並留下 0 succeeded／1 failed／7 pending 的 transport circuit checkpoint；續跑前須另建綁定 12 個 verified artifact 的新 plan。後續沿 `build_mops_statement_batch.py` 對明確列出的公司／市場／期別擴展（每批固定上限、逐 run immutable、`--resume` 僅重試失敗 child、來源 circuit breaker 與 XBRL identity／listing／period gate），再用 `materialize_mops_statement_candidates.py` 在隔離 DB 重跑；只有 item-code、revision、來源證據與完整 coverage dossier 齊全後才交正式 materialization gate。本輪所有 candidate 與 adapter 仍是 research-only，不能把 t57 公告事件直接當成財報數值。
4. 若要讓排程自動承接新月營收 candidate，需另行建立週期 intake、候選重抓 idempotency 與正式 mapping/backfill 的明確 operator flow；本輪只修復並驗證 fetcher。

## 回滾清單

共享工作樹回滾規則：先保存本輪精確 patch（含 binary 內容）並逐 hunk 做反向檢查；使用 `git apply -R --check` 通過後才可套用 `git apply -R`，每個 hunk 後核對現有 diff。不得以整檔 checkout、reset 或清理命令回復，避免移除其他 agent 的未提交變更。

| 檔案 | 類型 | 回滾操作 | 風險 |
|---|---|---|---|
| `data_module/monthly_revenue_availability_history.py` | 修改 | 回滾前先保存本輪已審查的精確 binary patch；逐 hunk 執行 `git apply -R --check` 後再反向套用，核對共享 diff。 | 會移除官方 host/path/期別防護與 redirect 回歸修復；不影響正式資料檔。 |
| `data_module/monthly_revenue_snapshot_harvester.py` | 修改 | 對精確 patch 逐 hunk 執行 `git apply -R --check`／`git apply -R`，每個 hunk 後檢查 `git diff`。 | 會使新 candidate 回到舊來源版本命名；不改既有 SQLite。 |
| `data_module/fundamental_availability_sources.py` | 修改 | 對精確 patch 逐 hunk 執行 `git apply -R --check`／`git apply -R`，並在每步後核對 revision history diff。 | 會移除 mapping revision history 保留。 |
| `data_module/monthly_revenue_availability_merge.py` | 修改 | 對精確 patch 逐 hunk 執行 `git apply -R --check`／`git apply -R`，確認 append-only merge 差異後再繼續。 | 會恢復同 natural key 覆蓋式 merge；可能失去 revision 歷史。 |
| `data_module/fundamental_sqlite_provider.py` | 修改 | 對精確 patch 逐 hunk 執行 `git apply -R --check`／`git apply -R`，回滾後重跑 provider 測試。 | 會移除 cutoff、revision history 與同日歧義防護。 |
| `data_module/monthly_revenue_backfill.py` | 修改 | 對精確 patch 逐 hunk 執行 `git apply -R --check`／`git apply -R`；保留其他 agent hunk。 | 會移除完整 snapshot 分母、lineage 與 session gate。 |
| `scripts/build_monthly_revenue_availability_history.py` | 修改 | 以精確 patch 逐 hunk 反向套用並核對 CLI help／測試。 | 會移除 snapshot capture 時間參數。 |
| `scripts/build_mops_statement_pit_candidate.py`、`scripts/enrich_mops_statement_item_codes.py`、`scripts/materialize_mops_statement_candidates.py`、`scripts/build_mops_statement_batch.py`、`data_module/mops_statement_candidate_adapter.py` | 新增 | 保存本輪精確 patch；逐 hunk 執行 `git apply -R --check` 後再反向套用，並刪除本輪明確新增的檔案。 | 會移除 t164 numeric candidate 解析、XBRL row code custody、單位／period 語意、隔離 consumer adapter 與 bounded batch intake。 |
| `scripts/plan_mops_statement_universe.py`、`scripts/diagnose_mops_failed_quarterly.py` | 新增 | 保存本輪精確 patch；逐 hunk 執行 `git apply -R --check` 後再反向套用，並刪除本輪明確新增的檔案。 | 會移除 registry 分母／continuation plan、失敗回應的 bounded diagnostic 與有效 evidence 產出。 |
| `tests/test_monthly_revenue_availability_history.py` | 修改 | 保存該檔精確 patch 後，使用 `git apply -R --check` 與逐 hunk `git apply -R`；不可整檔還原。 | 只移除回歸測試。 |
| `tests/test_monthly_revenue_snapshot_harvester.py` | 修改 | 保存該檔精確 patch 後，使用 `git apply -R --check` 與逐 hunk `git apply -R`；不可整檔還原。 | 只移除來源版本測試。 |
| `tests/test_fundamental_availability_sources.py`、`tests/test_fundamental_sqlite_provider.py`、`tests/test_monthly_revenue_availability_merge.py`、`tests/test_monthly_revenue_backfill.py`、`tests/test_monthly_revenue_backfill_cli.py` | 修改 | 各自保存精確 patch 後逐 hunk 使用 `git apply -R --check`／`git apply -R`；不要整檔 checkout。 | 只移除本輪的 revision、consumer cutoff、merge、分母與 CLI 回歸測試。 |
| `tests/test_build_mops_statement_pit_candidate.py`、`tests/test_mops_statement_candidate_adapter.py`、`tests/test_build_mops_statement_batch.py` | 新增 | 保存本輪精確 patch；以 `git apply -R --check`／`git apply -R` 逐 hunk 回滾，或只移除本輪新增檔案。 | 只移除季度 parser／adapter／bounded batch 的回歸測試。 |
| `tests/test_plan_mops_statement_universe.py` | 新增 | 保存本輪精確 patch；以 `git apply -R --check`／`git apply -R` 逐 hunk 回滾，或只移除本輪新增檔案。 | 只移除首批代表性條件、continuation 尾批與 verified artifact 綁定測試。 |
| `docs/06_qa/V4_DATA_RECOVERY_2026_09_07.md` | 新增 | 若審查決定移除，只刪除這個明確新增文件並核對 `git status`；不得碰其他 agent 文件。 | 只移除本輪 QA 紀錄。 |

`output/v4_data_recovery_2026-09-07/` 為 ignored candidate/evidence；清理時只可針對此明確目錄處理，不得把 `D:/Min/Python/Project/FA_Data` 或其他 agent 的工作樹變更當作回滾目標。

### 1240 2026-Q2 browser XBRL 與隔離 consumer 交付

本片以已保存的官方來源完成 TPEx／1240 茂生農經 2026-Q2 三表 candidate。t57 listing 的瀏覽器 DOM observation 只用來核對公告列：官方 URL 為 `https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&mtype=A&co_id=1240&year=115`，列出 `202602_1240_AI1.pdf`、上傳時間 `2026-08-13T16:43:20+08:00`、期間 `2026-Q2`、期末 `2026-06-30`。UTF-8 DOM 為 5,050 bytes、SHA-256 `76af9e4f595ace4c9dbd502df7b8050efdb5ca463c07ef730506dcd40b8f0e93`；嚴格 UTF-8 decode／encode Big5 replay 為 4,647 bytes、SHA-256 `2d527b62e2acef918cc6bf522bbb251faa94990444a3cc05e325925c8055e6a2`。這兩者都是 browser observation／encoding replay，沒有宣稱 t57 HTTP raw custody，也沒有把上傳時間回填成 numeric 可得時間。

t164 三份 numeric response 是一次 bounded 官方 POST observation，均為 HTTP 200、`TYPEK=otc`、`co_id=1240`、115 年第 2 季，並以原始表頭和 t57 期末交叉核對。raw files 與 SHA-256 如下：`ajax_t164sb03_1240_115Q2.html` 47,018 bytes／`5b3e2db05fca6ac57817e06ac54f0b1914070697690414dcb5414489bd405988`；`ajax_t164sb04_1240_115Q2.html` 33,864 bytes／`25d3cf4f93b1f67accafa1876c6736371c471351ee3eb780c222637cf8a46b4b`；`ajax_t164sb05_1240_115Q2.html` 20,447 bytes／`19a64a0a7cf25891d52a6086509c70e780c2fc8bad67635f2f562e64ec035c04`。官方 t164 XBRL endpoint 的 Python transport 曾受 `WinError 10013` 限制，改以 Chrome 讀取已觀察官方 URL；保存的 rendered DOM 為 520,114 bytes、SHA-256 `bf4cc6636d42c03ec048f687ea7ed9a6466fa0ddd04293848813635388faebe6`，hidden metadata 精確為公司 `1240`、年度 `2026`、季度 `2`、`Consolidated report`、`Over-the-counter`，共 171 個名稱、181 個 official row entries。XBRL DOM evidence 明確 `raw_http_bytes_saved=false`，所以 row-code 來源被標為 browser DOM、非 HTTP raw。

完整 immutable child 為 `quarterly/v4-quarterly-continuation-r3-1240-browser-xbrl-r2-otc-1240-2026q2/`；candidate SHA-256 為 `9d4ce9daa18f01a5e8bef4a5cd9b6682242593b4d9cb6dbaf3991aea99930aac`，run manifest SHA-256 為 `afe3246b2e035f0c4d814e9684d714810564945f50bf61951249289d42e01758`，宣告的 13 個檔案逐一核對成功。candidate 共 151 筆，按報表為資產負債表 56、綜合損益表 37、現金流量表 58；各表分別保留 `period_end_snapshot`、`quarter_single`（2026-04-01～2026-06-30）及 `year_to_date`（2026-01-01～2026-06-30）語意。空白列未補零，分母與 excluded rows 留在 statement sources。一般金額使用整數 TWD／`value_scale=1000`，EPS 使用整數 cents/share／`TWD_per_share`／`value_scale=100`；1240 的基本每股盈餘 raw cents `196`，consumer 讀回 `Decimal("1.96")`。

candidate 的 numeric `capture_started_at` 為 `2026-09-07T13:32:56.364631+00:00`、完成時間為 `2026-09-07T13:32:56.503201+00:00`，保守 date-only `numeric_available_date`／`available_date` 為 `2026-09-08`。隔離資料庫為 `quarterly/isolated_statement_consumer_v4_continuation_r3_1240_browser_xbrl_r2.db`，marker 與首次／重跑 evidence 同目錄保存；`PRAGMA quick_check=ok`，主表 151、`mops_statement_consumer_metadata` sidecar 151。首次 materialization 為 151 inserted／0 existing，重跑為 0 inserted／151 existing；provider 在 decision date 2026-09-07 回傳 0 筆、2026-09-08 回傳 151 筆。`isolated_statement_consumer_v4_continuation_r3_1240_browser_xbrl_r2_quickcheck.json` 保存了 manifest 全檔 hash、三類筆數、期間／單位分佈、EPS、cutoff 與冪等讀回結果；`formal_db_written=false`、`raw_data_modified=false`。

批次第一次以同一輸入在 Windows staging directory replace 遇到 `WinError 5`，沒有建立 child；該失敗與 network failure 分離保留於 `v4-quarterly-batch-2026q2-continuation-r3-1240-browser-xbrl-r1-manifest.json`。使用新 operation identity 重跑後成功，沒有重發 HTTP，成功 manifest 為 `v4-quarterly-batch-2026q2-continuation-r3-1240-browser-xbrl-r2-manifest.json`。由 12 個既有 verified artifact 加入此 child 後，`mops-statement-universe-2026q2-continuation-r4-1240.json` 的來源分母為 eligible 1,974、verified 13、remaining 1,961；這代表本片新增 1240 的 source-backed coverage，不代表全市場完成。browser XBRL hash negative、external URL negative、strict identity／row-code positive tests 均保留；browser DOM 路徑不會被當成 HTTP raw。




### 1259 2026-Q2 官方三表、XBRL 與隔離 consumer 交付

本片以 Chrome 讀取官方 t57 listing，再以一次有界、升權的官方 MOPS t164 POST 保存 numeric response；沒有寫入正式 DB、D 槽或既有 raw。t57 URL 為 `https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&mtype=A&co_id=1259&year=115`，瀏覽器 DOM 5,141 bytes，SHA-256 `38882283dc22c12df1e58e38bed93c4a4ce9990e86da5a27cd4be2beef68330d`；嚴格 UTF-8→Big5 replay 4,707 bytes，SHA-256 `a3909246b4308d3dfd64fb868baf626241cd0c95b08839a080e68fef3ab7c6e5`。解析到的實際 row 是 1259／2026-Q2／期末 2026-06-30／`202602_1259_AI1.pdf`／檔案 9,081,801 bytes／官方上傳 `2026-08-10T15:37:53+08:00`／更補正「無」；listing evidence 明確為 Chrome DOM observation、`raw_http_bytes_saved=false`、`pit_credit=none`，不把公告日當歷史 numeric 可得日。

三張官方 numeric raw 均 HTTP 200、request `co_id=1259`、`TYPEK=otc`、115 年第 2 季：`ajax_t164sb03_1259_115Q2.html` 46,408 bytes／SHA-256 `6202fd88a1d313d0543d79e1c38abe83bafab7a5826fa84197a5af36d9571180`；`ajax_t164sb04_1259_115Q2.html` 32,524 bytes／SHA-256 `cc143a663934b139dff28205bfd772f8c3fc6107a17a13f110c9336f89a0cf0e`；`ajax_t164sb05_1259_115Q2.html` 20,662 bytes／SHA-256 `f0519c6fe095a4deab50b30fcd538e1fac7e4c780ea0d94705e9b2ef868eb547`。三筆 request／response timestamp、HTTP metadata、raw byte/hash 綁在 `browser-continuation-r3-1259/numeric-http-r1/evidence.json`，validator 回報 `verified_saved_statement_http`。

官方 t164 XBRL 使用瀏覽器 rendered DOM，完整保存 `mops-t164-browser-dom-full-r5.html` 578,399 bytes／SHA-256 `260b6478c268535255051581146709d7a72b86d402212c97d20ab2bf96e8d035`；hidden metadata 精確為 company `1259`、year `2026`、quarter `2`、`Consolidated report`、`Over-the-counter`，解析 168 個名稱／179 個 official row entries。`xbrl-browser-evidence-r2.json` 的 schema、官方 t164 URL、strict UTF-8 round-trip、DOM hash、公司／期別／市場與 row-code count 全部驗證通過，且 `raw_http_bytes_saved=false`。早期 `mops-t164-browser-dom-full-r1.html` 只保存到 CUA 單次回傳上限 200,011 字、在 row 中途截斷；該 immutable 檔保留作失敗擷取證據，沒有被用來建候選或宣稱完整 custody。

候選 child 為 `quarterly/v4-quarterly-continuation-r3-1259-browser-xbrl-r2-otc-1259-2026q2/`：candidate SHA-256 `65e3aebc9875f20f24a4f7c39ddb25e3fecfca35c88eb30d48897dbada5bff84`，run manifest SHA-256 `c0a02b3db0e6ed65b0ab4a389347023e655e0a430a02402e05baaee53d20bb42`，manifest 13 個檔案逐一 hash 相符。共 149 筆唯一官方 code：資產負債表 55、綜合損益表 35、現金流量表 59；空白列分別 9／6／3，均保留在 statement sources 的分母與 excluded rows。BS 為 `period_end_snapshot`（2026-06-30），IS 為 `quarter_single`（2026-04-01～06-30），CF 為 `year_to_date`（2026-01-01～06-30）；145 筆一般金額為 TWD／scale 1000，4 筆 EPS 為 cents/share／`TWD_per_share`／scale 100。建置首次對 `預期信用減損損失（利益）` 無唯一 code 時 fail-closed；依該公司 XBRL 實際列與數值／縮排核對後，加入精確 alias 到 `預期信用減損損失（利益）淨額` code 7055，回歸測試保留唯一性與金額匹配條件，未放寬通用名稱規則。

隔離 DB 為 `quarterly/isolated_statement_consumer_v4_continuation_r3_1259_browser_xbrl_r2.db`，marker、首次／重跑 evidence 與 `..._quickcheck.json` 同目錄保存。quick check=`ok`、manifest 全檔 hash=true、主表／sidecar=149／149；類型回讀 BS55／IS35／CF59，EPS code 9750 回讀 `1.96` `TWD_per_share`，期間 `quarter_single`；numeric capture completed `2026-09-07T14:06:48.145082+00:00`、date-only `available_date=2026-09-08`。provider decision date 2026-09-07=0、2026-09-08=149；首次 materialization 149 inserted／0 existing，重跑 0 inserted／149 existing。`formal_db_written=false`、`raw_data_modified=false`。

批次完成 manifest 為 `quarterly/v4-quarterly-batch-2026q2-continuation-r3-1259-browser-xbrl-r2-manifest.json`：單批 1 家、child 已由既有 immutable 產物復核成功、attempts=1、raw file count=10，未重抓成功 raw。加入此 batch 後新 universe plan `quarterly/mops-statement-universe-2026q2-continuation-r5-1259.json` 綁定 14 個 verified artifacts：eligible 1,974、verified 14、remaining 1,960、下一批 8 家為 1264／1268／1294／1295／1336／1565／1569／1570；verified coverage 70 bp。這是目前可驗證 coverage 與可重跑 queue，不代表全市場完成；下一批仍受每批 8 家、逐家公司 raw／code／period gate、source circuit breaker 與隔離 consumer 條件約束。
### 2026-Q2 continuation r13-r20：1570、1580、1584、1586、1591、1593、1595、1599

本片新增 8 個 immutable child，沿用已驗證的官方 MOPS 路徑：t57 公告列以瀏覽器 DOM observation 保存公司／期別／市場／公告檔案與上傳時間，三張 t164 數值表以一次有界 HTTP 200 response 保存原始 bytes／request metadata／SHA-256，XBRL 以官方 t164 row code response 綁定科目。公告上傳時間只作公告事件證據；數值以全部讀取、身份／期別／單位／官方 code 驗證完成後的 `capture_completed_at` 建立保守 `available_date=2026-09-08`，沒有把公告日回填成歷史 PIT 可得日。

各 child 的 immutable candidate、隔離 SQLite、第一次／重跑 receipt 與 quick check 均已保存；下表的 SHA 是 candidate 與隔離 DB 的完整內容身份：

| 公司 | 市場 | rows（BS／IS／CF） | EPS（TWD/share） | candidate SHA-256 | 隔離 DB SHA-256 |
|---|---|---:|---:|---|---|
| 1570 | TPEx | 126（45／31／50） | 0.31 | `6cdabd287dffe7a975257524b1df8c9a670650abb8104c96c52ade0893531366` | `e2ed8629c14ffc68c4f7967ae0f11a0bff86becffffc999e8932645c036fe6db` |
| 1580 | TPEx | 135（46／36／53） | 1.89 | `a8fdab1b44343f7e75a14e511e74c90a4eae685e8a414c00892d624825ed50d7` | `fcdaca003c63df0d0d902930bac42f3a7bdbedd1367a21ed62000ea26ae84d8a` |
| 1584 | TPEx | 155（60／33／62） | 0.10 | `e6a023ec7997c02b634c2dca063adf68f0555267a96a291a7453f3e3d4ab03f2` | `a32150879ca8cd155b0c2cf2a10e3783ed1b2777d5b92e9159ca76381daa4c37` |
| 1586 | TPEx | 125（48／28／49） | 0.15 | `64cc296eaf0162eb2a23aaf459dad5cad58f540981aeae2218fc40207008e76c` | `a13ae3d8f7d739b53b11fc31fdc476cea4a77d68321c48d2d2eabb5dd2045c84` |
| 1591 | TPEx | 110（41／28／41） | 0.19 | `ee2a6e78841ba370a22b075c7d93c99f0528781c34515b78287d87bd3f6b6dc` | `56a663610ff8dd51d9c8fe674dc8034a5bcedaa1c2e806e41b261220f8a1bbcd` |
| 1593 | TPEx | 145（52／34／59） | 2.03 | `f05fef0f1bbe0eed90635f3960973a770ea0a0670d5ee92f3a4aaadb8f06d357` | `9c00572ec7d7b4d7f4249296e68285db4fda581b467aceaaa73df0968587a8ca` |
| 1595 | TPEx | 146（56／32／58） | -0.24 | `a62bb422e29fc8beca866ebfcf23c33fd362b9cd1f3f9e413b84b4060cf5cb7a` | `e898d318d9de97645f400f9ec2d5054f9d482f8c14a7056bf53739a55db05580` |
| 1599 | TPEx | 143（59／32／52） | -0.19 | `8076dea4949f28ea46c11c385cd5db6e57d7782667e65a52c2c177ad0bfa44cd` | `0d4060a4e03290684a263b642f22666afb0bde034f8f21c2c89363bf672d08e7` |

8 家均有 `sidecar_count == main_count`，`PRAGMA quick_check=ok`，首次寫入為 rows、重跑為 `0 inserted / rows existing`；provider 在 2026-09-07 均為 0、2026-09-08 均為該 child rows。一般金額保留 TWD／scale 1000，EPS 保留 cents/share／`TWD_per_share`／scale 100；BS、IS、CF 分別保留 `period_end_snapshot`、`quarter_single`（2026-04-01～06-30）與 `year_to_date`（2026-01-01～06-30）期間語意。所有 row code 來自官方 XBRL lineage，沒有以名稱猜測 code。

1580 的前兩個 immutable failed child 分別暴露 `勞務收入` 與 `勞務成本` 缺少官方唯一 code；依同一份官方 XBRL 實際列加入窄 alias `勞務收入合計`（4600）與 `勞務成本合計`（5600），並保留唯一性與金額／期間匹配回歸測試後才建立 r3。1584 首次 staging→immutable rename 遇 Windows `WinError 5`，沒有覆寫或重抓 raw；以新 operation identity 從相同 immutable raw resume 後完成。兩者均未將 transport／檔案系統失敗誤報為官方資料缺失。

機器摘要為 `output/v4_data_recovery_2026-09-07/quarterly/v4-quarterly-continuation-r3-r20-consumer-summary.json`，以 8 個 quickcheck、8 個成功 batch manifest 與 r20 plan 的路徑／內容 hash 綁定上述數字；`formal_db_written=false`、`raw_data_modified=false`。r20 universe plan 的 source registry 分母為 eligible 1,974、verified 29、remaining 1,945；下一批自動 queue 為 1742、1777、1780、1781、1784、1785、1788、1796。這是 29 家的 source-backed isolated coverage，不能宣稱全市場完成。

持續更新入口為 `scripts/build_mops_statement_batch.py` 搭配 `scripts/plan_mops_statement_universe.py`：每批最多 8 家，明確設定單家公司 attempt 上限與 source-level circuit breaker，成功 child 由 immutable manifest／candidate hash 驗證後直接沿用，`--resume` 只重試 failed child；`scripts/materialize_mops_statement_candidates.py` 仍只接受受控 research-only DB，不能指向正式 DB 或 D 槽。下一批若遇 doc transport 失敗，保存一次 bounded failure receipt 並延後該 source，讓其他可取得公司繼續進行。

### 2026-Q2 continuation r21：EZSearch 可用性來源與六家隔離 consumer

本片先以同一官方來源完成可用性與數值路徑拆分。`doc.twse.com.tw/server-java/t57sb01` 在系統解析與瀏覽器均無法連線時只記為 transport failure；不把它的失敗解讀成公告不存在。已保存的官方 `mopsov.twse.com.tw/mops/web/ezsearch_query` 三次 POST（F26 資產負債表、F27 綜合損益表、F28 現金流量表）作為公告事件 lane，三個 raw response 均 HTTP 200，raw SHA-256 分別為：F26 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、F27 `a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、F28 `3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`。完整請求／回應 hash 與每家公司 matched row 綁在 `quarterly/ezsearch-continuation-r21-r1/capture-manifest.json` 及 `ezsearch-evidence-<stock>.json`；EZSearch 只核對公告公司、上櫃市場、115 年第 2 季、F26/F27/F28 與官方 detail URL，不產生 numeric row。

本片成功 child 如下；每個 child manifest 的 8 個 raw file、candidate、statement sources 與 availability source 都由 batch validator 重新核對。數值仍來自 MOPS t164 sb03／sb04／sb05 與 XBRL row-code response，`announcement_event_timestamp` 與 `numeric_available_at` 分開保存；numeric capture 完成時間轉出的 date-only `available_date` 為 2026-09-08，沒有把公告日回填成歷史 PIT 可得日。

| 公司 | batch／child | candidate rows | candidate SHA-256 | 數值狀態 |
|---|---|---:|---|---|
| 1742 | `r21-ezsearch-next7` | 134 | `0ede4be5a6f6143d7fe818e3ff509bedef2fab0ec6b1bd8ff754d32832ef61b8` | t164／XBRL／EZSearch matched |
| 1781 | `r21-ezsearch-next5` | 131 | `d2d9f69364dabaecb754b0f13af4aef526e48874ab820da287d4e09f6b282067` | t164／XBRL／EZSearch matched |
| 1784 | `r21-ezsearch-single-1784-r3` | 146 | `bc9362ce775371c3a7a1624086ca66c2cd0707770ccdba462783feb408461dd0` | t164／XBRL／EZSearch matched |
| 1785 | `r21-ezsearch-next3` | 153 | `627abfc62ed418e999cede949fae9800eeb3b05a30e58edc896dd799aa292cdc` | t164／XBRL／EZSearch matched |
| 1788 | `r21-ezsearch-next3` | 141 | `af5a76a50d84df0721e709f6112ee00ddee3df0b7387965ae3882cc2002e172e` | t164／XBRL／EZSearch matched |
| 1796 | `r21-ezsearch-next3` | 128 | `5e45f9e4e3ec09e5c7d772332371c3e67fe76ab06e44525e007fa7d45d1b52e8` | t164／XBRL／EZSearch matched |

六家合計 833 rows。隔離 DB `quarterly/isolated_statement_consumer_v4_continuation_r3_r21_ezsearch_next6.db` 的 SHA-256 為 `c47ea057e5fb4557fda575b25d83102ef83f34a21c656483e81e277e4ac5a995`，`PRAGMA quick_check=ok`，主表／`mops_statement_consumer_metadata` sidecar 各 833。首次 materialization 為 833 inserted／0 existing，重跑為 0 inserted／833 existing；provider 在 2026-09-07 回傳 0、2026-09-08 回傳 833。sidecar 的 EPS row 以官方 code `9750`／`9810` 保存 `TWD_per_share`、scale 100；1742、1781、1784、1785、1788、1796 的基本 EPS 讀回分別為 `-0.06`、`-0.32`、`0.39`、`1.11`、`2.29`、`0.05`，期間均為 `quarter_single`。首次／重跑 receipt 與以上 child／DB hash 綁定於 `quarterly/continuation_r3_r21_ezsearch_next6_consumer_summary-r2.json`，摘要工具為 `scripts/summarize_mops_statement_consumer_batch.py`。

本片失敗與延後狀態也保留在 batch manifest，沒有用 HTTP 200 冒充解析成功：1777 的官方 t164 balance response 是 HTTP 200、38,839 bytes、raw SHA-256 `3caf7c82be203bdf0f1a5c2581e4ded2a6f181d0e4b199bec16feeb0e331c794`，實際標題為「個別資產負債表」，因此 consolidated parser 明確拒絕；這不是把個別報表改名接受。1780 的三個 EZSearch evidence 都是 `no_matching_company_period_row`，而未帶 availability override 的舊嘗試另留下 `doc.twse.com.tw` DNS failure；兩者都未物化。1784 首次長批次在 staging 目錄 publish 遇 `WinError 5`，沒有留下部分 child，改用新 operation identity 完整落盤；未重抓已成功 raw。

本片 universe checkpoint `mops-statement-universe-2026q2-continuation-r21-ezsearch-next6.json` 綁定官方 registry SHA `a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`，eligible 1,974、verified completed 35、remaining selectable 1,939。為避免同一失敗在下一批自動重送，`mops-statement-universe-2026q2-continuation-r22-after-r21.json` 將 1777／1780 標為 caller exclusion（不算完成），scope 為 eligible 1,974、verified 35、caller excluded 2、remaining selectable 1,937，下一批自動選取 1799、1813、1815、2035、2061、2063、2064、2065。這兩家公司仍保留於失敗／待補隊列，不代表已取得資料；本片也不代表全市場完成。

摘要 CLI 的回歸測試為 3 passed；季度 parser、batch、universe、adapter 與摘要整合測試合計 79 passed、1 skipped（平台 alias 測試受環境限制，原因如測試輸出所示），`py_compile` 與摘要 CLI `mypy` 均通過。摘要 CLI 的 output、input、candidate、DB 與 isolation marker 路徑均在 materialization 前做 resolved path／create-only guard，避免 `--output` 與 candidate 或 DB 重疊；所有本片產物仍為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`。

### 2026-Q2 continuation r22：1777 個別報表與四家可重用 HTTP/XBRL 子批次

本片完成一條可重跑的個別報表契約，並把它接到既有 batch、隔離 consumer、provider cutoff 與 universe checkpoint。程式變更集中在 `scripts/build_mops_statement_pit_candidate.py`、`scripts/build_mops_statement_batch.py`、`scripts/validate_mops_quarterly_artifact.py`、`data_module/mops_statement_candidate_adapter.py`、`data_module/fundamental_statement_data.py`、`data_module/fundamental_sqlite_provider.py`、`scripts/plan_mops_statement_universe.py` 與 `scripts/summarize_mops_statement_consumer_batch.py`；相應 parser／batch／adapter／provider／universe／summary 測試均保留。`report_basis` 現在明確區分 `consolidated` 與 `individual`，報表標題、t164 XBRL `REPORT_ID`／category、row code、period basis 與 consumer sidecar 必須一致，個別報表不會冒充合併報表。

1777 的正式官方數值路徑為 t164 individual：`https://mopsov.twse.com.tw/server-java/t164sb01?step=1&CO_ID=1777&SYEAR=2026&SSEASON=2&REPORT_ID=A`，HTTP 200、`Individual report`、response 433,441 bytes，XBRL raw SHA-256 `f015fcb41fc1b9b70a8ffc0647204962475b74235e0d0a4a0d223ba207db0868`。EZSearch 公告事件仍與數值 lane 分離，候選綁定 2026-Q2／上櫃／F26-F28 的三筆 matched 官方紀錄；公告時間只作事件證據，沒有把它回填成數值可得時間。

1777 immutable child 為 `quarterly/v4-quarterly-individual-1777-r1-otc-1777-2026q2/statement-pit-candidate.json`，candidate SHA-256 `e5f9e4d3d51a9d2d8ad2f447c528f78636877f3ba8615cac0d7f1141db84572c`，child manifest 的 `raw_file_count=8`、112 筆 accepted rows，report basis=`individual`。三類報表為 BS 45（response 57、排除 8）、IS 26（response 35、排除 5）、CF 41（response 48、排除 3）；CF 保存 2026-01-01～06-30、`year_to_date`，IS 保存 2026-04-01～06-30、`quarter_single`。EPS 官方 row code `9750`／`9810` 讀回 cents/share `203`，consumer 讀回 `Decimal('2.03')`，unit=`TWD_per_share`、scale=100。候選 capture 完成時間為 `2026-09-07T09:10:55.959784-07:00`，當時已跨台北午夜，故 date-only `available_date=2026-09-09`；這是保守日期，不代表歷史首次公告 PIT。

1777 隔離證據 `quarterly_isolated_materialization_individual_1777_r1_pit_first.json`／`..._pit_retry.json` 綁定相同 candidate hash：DB `quarterly/isolated_statement_consumer_v4_individual_1777_r1_pit.db` SHA-256 `b49cb1151c2ca1608d7ef09e3fcec4d14717b7c7143fd7f88210731f2d84920a`，`PRAGMA quick_check=ok`，主表／sidecar 各 112。首次為 112 inserted／0 existing，重跑為 0 inserted／112 existing；provider 在決策日 2026-09-08 回傳 0、2026-09-09 回傳 112。`formal_db_written=false`、`raw_data_modified=false`。

r22 的 EZSearch availability raw 沿用 immutable r21 response，沒有重抓已成功 raw。reuse manifest 為 `quarterly/ezsearch-continuation-r22-reuse-r1/reuse-manifest.json`，`capture_time_basis` 明列 reused official HTTP raw；來源 manifest SHA-256 `e271fcf2b8772baffffb29338c38c7501f4a351932e060e48538275465f0faf3`，F26/F27/F28 raw SHA 分別為 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、`a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、`3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`。8 家 evidence 各自保存 3 筆 matched／0 parse errors 的 source-bound records。

r22 numeric batch manifest `quarterly/v4-quarterly-batch-2026q2-continuation-r22-http-xbrl-r1-manifest.json` SHA-256 `2a10ad9b47351502b1db125e02f1b0c870d625762cead3ce25f921008fabce11`，8 家、每家最多一次 attempt、status=`partial`。四家成功且已完成 immutable candidate：

| 公司 | basis | rows | candidate SHA-256 | EPS（TWD/share） |
|---|---|---:|---|---:|
| 1813 | consolidated | 122 | `866191d9afa1325071dd2ff1cea4710f66af40d3f17d115c12739fb1d9ef9fd6` | 0.10 |
| 2061 | consolidated | 122 | `2b011f0fcaf0132954d5d1765ead6a918149c6f60d435e81cd536e878b597682` | 0.73 |
| 2064 | consolidated | 126 | `45b85d78900713d6f68f0362936d6bd2dc026dd84be823f374f98e3fc668030f` | -0.04 |
| 2065 | consolidated | 144 | `75181eb75b8609b05183dd71d43bec30367a0d2292439e5d7f67194debf02f41` | 1.35 |

1799、1815 各因官方 XBRL market identity 與 request 不符而 fail-closed；2035 因 t164 balance response 沒有 expected official title；2063 因 response 無法 strict Big5/HKSCS 解碼。四者均保留 batch attempts／reuse evidence，沒有用 HTTP 200 當內容成功，也沒有從 unfinished queue 移除。

1777 加四家合併為 `quarterly/continuation_r23_r22_individual1777_consumer_summary.json`，摘要 SHA-256 `23e82908d1dbb0f9aa3dbcc137f7cb7cee2b07881f671b18950b25a0a25df8c5`；隔離 DB `quarterly/isolated_statement_consumer_v4_continuation_r22_http_r1.db` SHA-256 `31afbcca5683d1a6dbfc2767e241b92ed4ddab5a0b1cd2c6a92d00f94ca62f19`。五家共 626 rows，主表／sidecar 各 626，`quick_check=ok`；首次 626 inserted／0 existing，重跑 0 inserted／626 existing；provider 2026-09-08=0、2026-09-09=626。摘要保存各 child candidate hash、basis、row count、DB receipt 與 cutoff，`formal_db_written=false`、`raw_data_modified=false`。

1780 的 `quarterly/ezsearch-continuation-r21-r1/ezsearch-evidence-1780.json` 仍是 3 筆 HTTP 200 官方 EZSearch response 的 `no_matching_company_period_row`（F26/F27/F28 各一筆，matched=0、errors=3）。這只能證明該查詢窗口沒有匹配列，不能推論公司已停業、當期不適用或公告不存在；1780 維持 deferred unresolved，沒有 caller exclusion 冒充完成，也沒有物化。

Universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r23-after-r22.json` SHA-256 `ba5477a911c4264fd657c5618ec93f7596be0ddc0757d7c8e138214c12e290b4`。r22 前基線為 eligible 1,974／verified 35／deferred unresolved 2（1777、1780）／total unfinished 1,939／selectable 1,937；本片完成 1777 與 1813、2061、2064、2065 後，新的機器計數為 eligible 1,974／verified 40／deferred unresolved 1（1780）／total unfinished 1,934／selectable 1,933。下一個自動 queue 為 1799、1815、2035、2063、2066、2067、2070、2073；四個 r22 失敗鍵仍在 unfinished queue，1780 仍在 deferred queue。

本片驗證包含個別報表標題／XBRL category、EPS 單位與期間語意、sidecar/provider 讀回、manifest／candidate hash custody、SQLite quick check、首次／重跑冪等與 2026-09-08／09-09 cutoff。季度相關 focused tests 為 97 passed、1 skipped；skip 是平台 alias 環境限制，沒有將它算成通過。所有輸出均 research-only，沒有寫入正式 D 槽或正式 SQLite，也沒有刪除或覆寫既有 raw。後續只需依 queue 對 1780 的官方狀態與四個 fail-closed child 做有界修復，並以每批最多 8 家、成功 raw reuse、source circuit breaker 與 immutable resume 持續覆蓋。

### 2026-Q2 continuation r23：四個 fail-closed 修復與三家新公司

本片沿用已保存的 EZSearch 官方公告事件 raw，沒有重抓已成功的三表；數值 lane 只對 2035、2063、2066、2067、2070、2073 做一次有界官方 XBRL GET，並重用既有 t164 numeric raw。官方 XBRL response evidence 位於 `quarterly/repair-r23-official-r2/xbrl-http-evidence-r1.json`（SHA-256 `90f9fd776b928b0596bd95038fc52bd451d56152b9173ce31b92273f21b80117`）與 `quarterly/repair-r23-official-r3/xbrl-http-evidence-r1.json`（SHA-256 `6631f76dd941dd52462fcd0be064ea489e435a391fddc93667a1bb976f0957e3`）。

- 2035 與 2073 的 `REPORT_ID=C` response 都是 HTTP 200、98 bytes、SHA-256 `54112594858a0455d96e7a520f6c4b07c3f4af6bfac128a0628084e32ba6fa61` 的官方「資料不存在」頁，沒有被當成合併報表數值。改以同一官方 endpoint 的 `REPORT_ID=A` 個別報表取得：2035 raw 436,378 bytes、SHA-256 `3be79f21667697b6d8bbfeaf1c4a8f6cc989696b4bf38016bc1fa237171d93a0`；2073 raw 436,954 bytes、SHA-256 `e68d2d7424148664dda70936361ebe4c928cdec4232f2fd4ba821033ec0002b9`。兩者 candidate 都明確標示 `report_basis=individual`，沒有把個別報表冒充合併報表。
- 2063 的官方合併 XBRL raw 為 502,294 bytes、SHA-256 `17859ef06199b4325c352810f819ea4ed9099623eb361e3e754521f5456f4981`，宣告 Big5；嚴格 Big5-HKSCS 解碼只在 6 個偏移遇到 `0x84`，沒有其他 C1 byte。新增的明確 repair policy 只移除這 6 個已定位 byte，raw bytes 原樣保存，candidate lineage 記錄 decoder、repair 名稱、removed count 與 offsets；未知 C1 或未宣告 Big5 仍 fail-closed。
- 1799 的 XBRL hidden market metadata 顯示 Listed company，但官方 EZSearch 以精確公司／期別／上櫃 row 驗證，因此 candidate 保留 `market_identity_conflict` lineage，不改寫 XBRL 原值，也不以 caller 市場欄位單獨放行。1815 的第一次 immutable publish 遇 Windows `WinError 5`，r2 以同來源新 operation 完成，這是檔案發布失敗而非官方內容失敗；2066、2067、2070 的公司／期別／合併 metadata 均通過。

八個成功 child 的 candidate 身份如下；r1／r2 中 1815、2063 的失敗與 pending attempt 仍保留在原 manifest，沒有覆寫歷史：

| 公司 | 報表範圍 | accepted rows | candidate SHA-256 |
|---|---|---:|---|
| 1799 | consolidated | 132 | `3fbb9c7901ce7a03b9bf981b3e357046a072fe6efe861b690b5cf585d346bac5` |
| 1815 | consolidated | 143 | `381fe796b41bc714e4f131edb8d79d9aa57d5697e19b3dac6a303fb055b1eb27` |
| 2063 | consolidated | 136 | `2846a976468351d1b9c028e80c44826761af6925c1b7fd6ef7581f1df22a3f5d` |
| 2035 | individual | 118 | `5e5d546c4fc6d4b6360c31de3d4602048ed651a33d2b2a71015b5492eaaffefd` |
| 2073 | individual | 115 | `4e164373bec355b4e40aad83e68d9f08332a409fc3450a396f5b4552855014d9` |
| 2066 | consolidated | 123 | `a191b06ebcead86bc37da99fdbb6400423203aeb9e36f129799704fb79468624` |
| 2067 | consolidated | 128 | `1da24d3818ae71acce88d2998b6ad012ed5605370f03ba735e1ef75e2a292435` |
| 2070 | consolidated | 143 | `e02490e4f221737d43a72fd9062494a2091722b46b8d15250e8112d0079cdf99` |

對應 batch manifest 依序為 `quarterly/v4-quarterly-batch-2026q2-repair-r23-r1-manifest.json`（SHA-256 `5a6c9df56002041347932350f3dd3198ac95dc0dd654da97ae148a0436a1a8eb`）、`r2`（`81e7a6aa9b5c5b467728156ee3918e5b6e1b6fec783aeff7110c5dbebf2078b0`）、`r3`（`fb9dce269f531767ca8b0996bb15037864fd37871d2b183f700aaa13d2d9ed76`）、`r4-individual`（`ed31b5a8b9729bb71259d9c48cda25654448c36281ff72db1d2a6fbbfd608504`）與 `r5`（`9f147ba3caa4a9e4250ca30e061cd37daec0806992d7dc0d6fb6232df3c7e2bf`）。每個成功 child 的 raw／candidate／run manifest hash 均由 batch validator 綁定；三張表的 `period_basis`、EPS cents/share 與一般金額 scale 隨 candidate 保留。

r1 manifest 中 1815 的舊 `failure_source=network` 是在 PermissionError 尚被通用分類時寫入；其 error 內容明確是 staging 目錄 publish 的 `WinError 5`，不是網路失敗。r2／r3 已以同一來源的 immutable retry 完成，現行 batch driver 已不再把一般 PermissionError 當作 transport circuit 來源；摘要保留舊 attempt 只作歷史沿革。

八個 candidate 實際送入新的隔離 consumer `quarterly/isolated_statement_consumer_repair_r23_r1.db`。首次 receipt `quarterly/repair-r23-consumer-materialization-first.json`（SHA-256 `1c3f0b48b942ae83a3c3dd637d3add9354d4ebd62a6d8310709b0d815ee22627`）回報 1,038 unique rows、duplicate 0、1,038 inserted、main／sidecar 各 1,038；重跑 receipt `quarterly/repair-r23-consumer-materialization-retry.json`（SHA-256 `c9959a3aa0e02e5f2f17284cfcacc1f5715a47a36be6e5914d8f79e3e9999065`）回報 0 inserted／1,038 existing，DB SHA-256 `88009abeb9cad09bc8f29bde291601068945fded9d5a86092c79615c58d38a27`，`PRAGMA quick_check=ok`。由 `FundamentalSQLiteProvider` 讀回時，decision date 2026-09-08 為 0、2026-09-09 為 1,038；這批 numeric capture 在 2026-09-07 16:40 UTC 後完成，故 date-only 使用下一個台北曆日 2026-09-09，沒有把公告日回填成歷史 PIT。EPS 讀回保留 TWD/share Decimal，例如 1799=`-0.10`、1815=`1.45`、2035 個別=`0.22`、2063=`0.52`、2066=`0.98`、2067=`-0.87`、2070=`0.96`、2073 個別=`-0.09`。

機器摘要初版 `quarterly/repair-r23-consumer-summary.json`（SHA-256 `355a433dbf415ff20d9c4fd89d51d3afa80e4c8bfe91f3ba61645fba474b3e16`）已綁定五個 batch manifest、八個成功 child、隔離 DB、首次／重跑 receipt 與 cutoff；型別修補後另建立 immutable 摘要 `quarterly/repair-r23-consumer-summary-r2.json`（SHA-256 `90444790f19d31be1348000a8d783481ff0626fa9237e5fc756fa0b9a962cf6a`），兩者均為 `formal_db_written=false`、`raw_data_modified=false`、`research_only=true`。新 universe plan `quarterly/mops-statement-universe-2026q2-continuation-r24-after-r23.json`（SHA-256 `6f41b83c431cc2afc57807edbdff817c14c8369d2c6c78a4057352f2ee162575`）以同一官方 registry 計算 eligible 1,974、verified completed 48、deferred unresolved 1、total unfinished 1,926、remaining selectable 1,925；下一批自動選出 2221、2230、2235、2596、2640、2641、2643、2718。1780 仍是 deferred unresolved，沒有因查詢無匹配而從完整未完成分母消失。

本片另檢查下游 statement factor adapter：`decision_module/factors/statement_factor_adapters.py` 現在對同一股票／期間混合 `consolidated` 與 `individual` 時直接回傳 `fundamental_statement.report_basis_mixed` 並不產生 factor；未知範圍回傳 `report_basis_invalid`，正常 factor metadata 也保留 `report_basis`。新增負例驗證重複 EPS 不會依 source version 排序被任選。這只保護目前 factor pack 的同期間輸入；ML all-field／跨期間同比資料集仍未接入本 research sidecar，不能宣稱投資 consumer 已全面具備報表範圍可比性，後續必須以明確 `report_basis` 維度篩選或拒絕混合。

本片驗證結果：`tests/test_build_mops_statement_pit_candidate.py tests/test_build_mops_statement_batch.py` 為 67 passed；`tests/test_statement_factor_pack.py tests/test_fundamental_factor_service.py` 為 8 passed；相關 Python `py_compile` 與 `mypy --explicit-package-bases decision_module/factors/statement_factor_adapters.py` 通過。pytest cache 的既有權限 warning 不影響測試。以上產物均在 repo `output/v4_data_recovery_2026-09-07/`，未寫入正式 SQLite、D 槽或原始資料；後續可沿 r24 plan 逐批最多 8 家、成功 raw reuse、source circuit breaker 與 immutable resume 繼續。

### 2063 XBRL 編碼修復校正（r23 encoding-r4）

先前 r23 candidate 的 2063 XBRL 解碼雖保存了六個 offset，但 decoder 使用 `body.replace(b"\x84", b"")`，可能對未知數值／標籤內容作泛刪，因此該版本的 2063 編碼語意不列為已驗收。此問題已以 `<td>12\x8434</td>` 重現；新增測試在即使 caller 提供政策時，也會因位置不是已核實非語意位置而拒絕，沒有合併成 `1234`。

現行 `scripts/build_mops_statement_pit_candidate.py` 的修復契約只接受已核實的官方 raw SHA-256 `17859ef06199b4325c352810f819ea4ed9099623eb361e3e754521f5456f4981`，精確 offset 為 `422759、422935、422998、423354、423751、423827`；六處都必須是 `LF 0x84 0x50`，且 response 必須宣告 `charset=big5`、不得含其他 C1 byte。修復以反向位置刪除這六個 byte，原始 502,294 bytes 不改寫；未知 raw、offset、控制 byte、數值內容注入與來源內容變更均 fail-closed。原文可直接 strict 解碼時 lineage 回報實際 decoder、`repair=null`、`removed_byte_count=0`，不虛報修復。

以既有 immutable raw 離線建立的新 child 為 `quarterly/repair-r23-encoding-r4/v4-quarterly-repair-r23-encoding-r4-otc-2063-2026q2/`：candidate 136 rows，candidate SHA-256 `f5835108a7257a69c0fa9b4fa6e4d4bbdc22a2ee09feabc85db3d0d3ffd0ccba`；run manifest SHA-256 `46e6761905a6f8c9fd6dd997afd5b01863e22b6858431c5924c3d1aba27696df`。實際解碼 metadata 為公司 `2063`、`2026-Q2`，lineage 保存 decoder=`big5hkscs`、repair policy、六個 offset 與原始 SHA；三表 accepted rows 為 BS 51（`period_end_snapshot`）、IS 32（`quarter_single`）、CF 53（`year_to_date`），XBRL official row-code lineage 136/136，沒有以 parser caller period 覆蓋來源期別。

新的隔離 consumer DB `quarterly/isolated_statement_consumer_v4_repair_r23_encoding_r4_2063.db` SHA-256 `8b46ea36ddadf0bf3312a6795b18473c6f255b824540688cb8ea51490ad903ed`，`PRAGMA quick_check=ok`，主表／sidecar 各 136；首次 materialization 136 inserted／0 existing，重跑 0 inserted／136 existing。因本次重建完成時間為 `2026-09-07T17:02:21.583462+00:00`（台北時間已進入 2026-09-08），date-only policy 嚴格給 `available_date=2026-09-09`：provider 2026-09-08 回傳 0、2026-09-09 回傳 136。`1100` 讀回 `345964000` TWD、`4000` 讀回 `239540000` TWD、`9750` 讀回 `0.52` TWD/share；CF `A00010` 讀回 `48822000` TWD，period basis 與 report basis 均保留。首次 receipt SHA-256 `f9f3ca55347a73f2e167dce7965b2e9797b07af5662a65973c0c26119eaca614`，cutoff retry receipt SHA-256 `b6e85c72f49716fd7d39617bc7943ceae49fb6f32a6b55f9c786222e21c03aac`；兩者均明示 `formal_db_written=false`、`raw_data_modified=false`。

本次編碼回歸為 `tests/test_build_mops_statement_pit_candidate.py` 52 passed；包含有效 HKSCS、strict/no-op lineage、數值注入、另一 C1 byte、真實 2063 六 offset 正例與同長度內容變更負例。舊 r23 產物與 raw 均保留 immutable；新 child 只作 research-only 語意驗收，不追認舊版本的 2063 修復，也未執行正式 D 槽或正式 SQLite 寫入。

### r24 staging、2063 replacement 與 ML report basis 交接

2063 的舊候選沒有被覆寫。`quarterly/repair-r23-encoding-r4/2063-supersedes-r1.json`（SHA-256 `6f72001724e1997ca88cb86a5c3d01b82b66360b1d3543195d4f3908c4b6241e`）以 immutable child 路徑、candidate／manifest hash 與原因綁定舊候選 `2846a976468351d1b9c028e80c44826761af6925c1b7fd6ef7581f1df22a3f5d` 和新候選 `f5835108a7257a69c0fa9b4fa6e4d4bbdc22a2ee09feabc85db3d0d3ffd0ccba`。`plan_mops_statement_universe.py` 及 consumer summary 讀取此 record 後只計 replacement，遇到同一公司／期別的舊 hash 會排除，不會把舊廣泛刪除 C1 byte 的候選當成現行完成。更新後的 `quarterly/mops-statement-universe-2026q2-continuation-r26-after-r24-staging-r1.json`（SHA-256 `b0662c65f4a48294826f1df5aef97884643b2e11894884901427ba42b77eb30f`）固定 eligible 1,974、verified 51、deferred unresolved 1（1780）、total unfinished 1,923、selectable 1,922；2063 仍只佔一個完成鍵。

ML all-field／shadow shard 現在把 `report_basis`（`consolidated` 或 `individual`）併入 statement row identity、entity id、snapshot metadata 與 shard identity；舊表沒有此欄時維持合併相容預設。statement factor pack 對同一期間混合範圍、未知範圍及衝突 revision fail-closed；跨期間同比只接受相同 `report_basis`，結果 metadata 會保存 `comparison_period`、`report_basis` 與 `same_basis`。`tests/test_statement_factor_pack.py`、`tests/test_ml_all_field_snapshot_provider.py`、`tests/test_ml_pit_year_shard_exporter.py` 共 19 passed；另相關 factor service、SQLite provider 與季度 parser／batch／plan／summary 套件共 126 passed、1 skipped。skip 是平台 alias 測試限制，沒有當作通過。

r24 staging manifest `quarterly/v4-quarterly-batch-2026q2-continuation-r24-staging-r1-manifest.json`（SHA-256 `8238bfa8150a03991e5b80175c28e71ae566b079e64444cfb3ff1a82b76c5c7f`）是 2026-Q2、每家公司最多一次 attempt 的 bounded run。2596／2640／2641 分別完成 110／146／147 筆，candidate SHA 分別為 `71318f5a4bbb8498dd2ea276dff9ba2c5ae50a9df4e192746ae4267696d2f8e5`、`0ae256bbd963013b6a80d772cfdb9fb09b46f37652f3f3ef67c6747fb5ed6695`、`ed2c4a55130d88e84ff87b25585327448cea35b0c9100d8e743d47ab7d5ac4d4`；三個 child 的 t164 三表、XBRL row-code 與 t57 listing raw 均由各自 run manifest 綁定。2230 的官方 listing 回報 correction，未建立 candidate；2235 回應標題與要求的合併報表不符，未改 caller scope 放行；2643 的 `doc.twse.com.tw` DNS `NameResolutionError` 開啟來源 circuit，2718 因同一 circuit 保留 pending。這些狀態留在 batch manifest，HTTP 200 或列出公司不等於解析完成。

三個成功 child 送入隔離 consumer `quarterly/consumer-r24-staging-r1/consumer.db`；DB SHA-256 `1e7fd6d2ef7595b1bf138a80d11964e96dadfee6846f293aec7f75abfd925303`，marker SHA-256 `eb2c42f7264bd465c7a38c4826abd1b0557fbc207135f30f61a339a08877d2df`，`PRAGMA quick_check=ok`，主表／sidecar 各 403。首次 evidence `first-evidence.json`（SHA-256 `5848dbd63ba3a8393d884773a6d23dbf7f9149769a672a553e1f4750ab92aa4a`）為 403 inserted／0 existing；重跑 evidence `retry-evidence.json`（SHA-256 `7ee96f80e2ca5e434a6748cf5e34bae35a49459f0e81cdcebf2a6fbe0ea5fae8`）為 0 inserted／403 existing。所有 row 的 `report_basis=consolidated`、item code source 為 `mops.t164sb01.xbrl.row_code`，EPS 讀回 2596=`1.81`、2640=`2.49`、2641=`0.54` TWD/share，cash-flow rows 保留 `year_to_date`。本次 capture 已進入台北 2026-09-08，依 date-only 保守規則可用日為 2026-09-09；provider 2026-09-07／09-08 均為 0，2026-09-09 為 403。`formal_db_written=false`、`raw_data_modified=false`。

r26 新公司 bounded HTTP batch `quarterly/v4-quarterly-batch-2026q2-r26-new-http-r1-manifest.json`（檔案 SHA-256 `d806a6041546b31db494089853f0bd2f609a977798654f1dcd3e82ee74fab268`）完成 2719／2724／2726，分別 117／119／125 rows；candidate SHA 分別為 `360632eb1301c49f2f63f998b672badabd883ba024ef26080cc41f86e55257ae`、`b7721ef74f11d132da029d5bcd9116807df1816b7600d2c0fb7e77eb55de5f38`、`82606caf2ed439004758f7df54606f36fbdb7bdd0b20bd6d6c3ce612e1502cd0`。隔離 consumer `quarterly/consumer-r26-new-http-r1/consumer.db`（SHA-256 `2f7c8c191e899c1a1380e3f229d931be307c9097c42cea46a7f8ff7fad5cfa6a`）主表／sidecar 各 361，`PRAGMA quick_check=ok`；首次 361 inserted、重跑 0 inserted／361 existing，provider 9/7／9/8 均 0、9/9 為 361。EPS 為 2719=`-0.20`、2724=`0.33`、2726=`-0.46` TWD/share；period basis 分布為 BS 139、IS 79、CF 143，沒有將單季損益與半年現金流合併。首次／重跑 evidence SHA 分別為 `7f56c93f5ad42037b2c2cadfb83c7165abaeb7c5b33800f26af2911866982088`／`23e597bc41ed699bce8f2e39487b1228afd7729693cf0229c22c6cb4240782aa`。更新後 `quarterly/mops-statement-universe-2026q2-continuation-r27-after-r26-new-http-r1.json`（檔案 SHA-256 `0c15d15047b9f738eb610341b675f469652ea3cca30989f57dea6e3b27c4c60a`；content hash `d7e9628651ec587b94843d81bfb607027ae5be4ae17968ba7f220f9e5c1be3ac`）為 eligible 1,974、verified 54、deferred 1（1780）、total unfinished 1,920、selectable 1,919；下一批自動選取 2221、2230、2235、2643、2718、2729、2732、2734。兩批均僅 research-only，沒有寫入正式 D 槽或正式 SQLite。

本片沒有把瀏覽器 DOM 當成 HTTP raw，也沒有重抓已完成 child。partial staging 修正先建立 `_partial` 父目錄再 rename 發布，新增回歸測試 `test_build_candidate_preserves_replayable_partial_after_listing_failure`；未來 t164／XBRL 已取得而 listing 或驗證失敗時會留下 raw、hash 與 failure phase 供 resume。`tests/test_build_mops_statement_pit_candidate.py tests/test_build_mops_statement_batch.py tests/test_mops_statement_candidate_adapter.py tests/test_plan_mops_statement_universe.py tests/test_summarize_mops_statement_consumer_batch.py tests/test_statement_factor_pack.py tests/test_fundamental_factor_service.py tests/test_fundamental_sqlite_provider.py tests/test_ml_all_field_snapshot_provider.py tests/test_ml_pit_year_shard_exporter.py` 合計 126 passed、1 skipped；py_compile 與相關 mypy 均通過。

`quarterly/r26-new-consumer-summary-r1.json`（SHA-256 `a54fdce3d2ad5b9511470a08ca919704573cafe1388445dac1bd04fcca94d5f`）為本片三家新公司之機器摘要。摘要綁定 r26 batch manifest、三個 child candidate／manifest、隔離 DB、首次／重跑 receipt、cutoff 與 r27 universe；JSON 可直接解析，`quick_check=ok`、361 rows 首次寫入且重跑 0 寫入／361 existing，2026-09-07 與 2026-09-08 均不可見、2026-09-09 可見。r27 universe 已納入 2719、2724、2726 並保留 2221、2230、2235、2643、2718 等 unresolved；摘要沒有把待處理或來源 circuit 的公司算成完成。

### r28 2026-Q2 bounded unresolved recovery、隔離 consumer 與 strict report basis

本片以既有 `ezsearch-r28-unresolved-r1` 官方公告查詢證據作 availability lane，對 `2221`、`2230`、`2235`、`2643`、`2718` 執行一次、每家公司一次的有界 HTTP numeric／XBRL 請求；沒有重抓已完成 child，也沒有寫入正式 D 槽或正式 SQLite。批次 manifest `quarterly/v4-quarterly-batch-2026q2-r28-ezsearch-http-r1-manifest.json` SHA-256 為 `db060d6cc7d9efffb9e99ed8e79ac799bea83bc89b4547fd0bcb51a89d5006f0`，canonical manifest／dataset identity 分別為 `0a9f0a4890b04ff573cf264346e98790065e955a3437c2be7076743870ddb726`／`6afe51a64abc50626cfd411b84e57d8637dec9a50a35985d2724413764ab9777`。五筆 request 全部完成一次 attempt，3 succeeded、2 failed、0 transport failure、0 pending，來源 circuit 沒有被錯誤地當成公告不存在。

成功 child 的 immutable candidate／manifest 與 rows 如下：

| 股票 | candidate rows | candidate SHA-256 | child manifest SHA-256 | EPS raw cents/share | report basis |
|---|---:|---|---|---|---|
| 2230 | 137 | `11271e0dda7de787ddd89f79f6424cfb6e6493ba3d97e5d0d99fd1cb6c4a8a1a` | `f4223c56bffb8e80c8f836e6a7afe02ebc1be2a5d88fe5da12e6a30b8611c1a9` | 9750=`-26` | consolidated |
| 2643 | 120 | `93b9dab2eb0797632c8d7bbd8cbca248ed2a898b270afbeb10bbb17493b90ed4` | `c73525a5fb1a74ff0136a9b7a5bda48f4c2826b669e51cde2b5383391fc1bbe6` | 9750=`211`, 9810=`210` | consolidated |
| 2718 | 139 | `7914499e2fcb12dd3216c50f9562d9ecbd70179c403214a728b10e6f87c1f4f2` | `6c9b15e56555a9563a07e890fec4ece6df95071018b68d8c4c90008a6092051a` | 9750=`8`, 9810=`8` | consolidated |

三個成功 child 的 period semantics 均保留：balance sheet=`period_end_snapshot`、income statement=`quarter_single`（2026-04-01～2026-06-30）、cash flow=`year_to_date`（2026-01-01～2026-06-30）。一般金額沿既有 scale 契約保存，EPS 以 cents/share 保存，隔離 consumer 讀回為 2230=`-0.26`、2643=`2.11`／`2.10`、2718=`0.08` TWD/share。2230 的官方 t57 觀察曾出現 correction 詳細資料入口；本片沒有補做 correction detail custody，因此 `correction_status=unknown`，不能把 2230 列為 correction-cleared，candidate 只作 research-only 待後續補證。2643、2718 同樣未宣稱歷史首次公告 PIT，numeric 可得日只依本次 capture-completion 的保守 date-only 規則處理。

2221 以 fail-closed 保留 partial staging：`MOPS XBRL response has no unique official row code for numeric item; statement_type=income_statement; item_name=停業單位淨利（淨損）`，failure phase=`listing_fetch`，`partial_replay_ready=true`；原始三表、XBRL、EZSearch 與 evidence 仍可重播。2235 的 failure phase=`statement_fetch`，錯誤為 `MOPS statement response does not contain the expected official title; statement_type=balance_sheet`，`partial_replay_ready=false`。兩家公司均保留在 incomplete children，沒有用 HTTP 200、公告列或 caller exclusion 湊成功。

三個成功 candidate 送入隔離 consumer `quarterly/consumer-r28-ezsearch-http-r1.db`；機器摘要 `quarterly/r28-consumer-summary-r1.json` SHA-256 為 `408cfbcde030ef04fcf7c9ca8a29830f47079bc769b3a68e38efa105f23b3cfc`。摘要綁定 r28 batch、三個 child、r27 universe、DB 與首次／重跑 receipt。DB SHA-256=`971ed49f188b2e2cbfcb51d79c952e58720a90aa83c66a23b5efd0fc745ff780`、marker SHA-256=`d945a65fd04c43f9999dfd91e1580f109405361f7ab4b1c1a522bb0eeea06b71`、`PRAGMA quick_check=ok`，主表／sidecar 各 396。首次 receipt `consumer-r28-ezsearch-http-r1-first.json` SHA-256=`c0d39ad9d7bf27cd2a6dc737376aa795b1de851177e60cd4ada83b16a0c720e4` 回報 396 inserted／0 existing；重跑 receipt `consumer-r28-ezsearch-http-r1-retry.json` SHA-256=`036fde75849bfbce01b41b3a4b10b1f4af6512b0837c6ecab7c906b233833188` 回報 0 inserted／396 existing。所有 396 rows 在 decision date 2026-09-08 不可見、2026-09-09 可見；這符合 numeric capture 完成時已進入台北 2026-09-08 後的下一台北曆日，沒有把公告事件日期回填為數值可得日。上述輸出均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`。

r27 universe plan 維持其完整分母與狀態：eligible=1,974、verified completed=54、deferred unresolved=1（1780）、total unfinished=1,920、remaining selectable=1,919。r28 的 consumer 摘要刻意仍綁 r27，因 2230 correction 尚未清除，且 2221／2235 尚未完成；因此本片的 3-child materialized count 不等於 universe verified count，也沒有把 2230、2221、2235 從 unfinished 分母移除。

ML all-field／year-shard 的 report basis 現在採明示契約：明示欄位只能是 `consolidated` 或 `individual`；明示空值、未知值或沒有可證明來源契約的缺欄一律拒絕。缺欄只有在既有 legacy source=`mops.financial_statement.raw` 且 source_version 以 `mops-t164-consolidated-` 開頭時，才可相容解析為 `consolidated`；不再對未知／空 scope 預設合併語意。`tests/test_ml_all_field_snapshot_provider.py`、`tests/test_ml_pit_year_shard_exporter.py` 共 18 passed；`mypy` 檢查三個 source file 及 `py_compile` 均通過。其餘 ML 跨期間比較仍須沿同一 basis 維度，未知範圍不可產生同比或特徵。

r28 之後可由 batch manifest 的 failed child 逐一 resume；成功 child 的 raw／candidate immutable，後續重跑只驗 hash 和重新 materialize，不重抓。下一片應先處理 2221 的唯一官方 row code 與 2235 的正確報表標題／公司狀態證據；在它們完成前，r28 只代表 3 家研究型隔離資料可讀，並非全市場或 correction-cleared 恢復。

### r24 staging、2063 replacement 與 ML report basis 交接

2063 的舊候選沒有被覆寫。`quarterly/repair-r23-encoding-r4/2063-supersedes-r1.json`（SHA-256 `6f72001724e1997ca88cb86a5c3d01b82b66360b1d3543195d4f3908c4b6241e`）以 immutable child 路徑、candidate／manifest hash 與原因綁定舊候選 `2846a976468351d1b9c028e80c44826761af6925c1b7fd6ef7581f1df22a3f5d` 和新候選 `f5835108a7257a69c0fa9b4fa6e4d4bbdc22a2ee09feabc85db3d0d3ffd0ccba`。`plan_mops_statement_universe.py` 及 consumer summary 讀取此 record 後只計 replacement，遇到同一公司／期別的舊 hash 會排除，不會把舊廣泛刪除 C1 byte 的候選當成現行完成。更新後的 `quarterly/mops-statement-universe-2026q2-continuation-r26-after-r24-staging-r1.json`（SHA-256 `b0662c65f4a48294826f1df5aef97884643b2e11894884901427ba42b77eb30f`）固定 eligible 1,974、verified 51、deferred unresolved 1（1780）、total unfinished 1,923、selectable 1,922；2063 仍只佔一個完成鍵。

ML all-field／shadow shard 現在把 `report_basis`（`consolidated` 或 `individual`）併入 statement row identity、entity id、snapshot metadata 與 shard identity；舊表沒有此欄時維持合併相容預設。statement factor pack 對同一期間混合範圍、未知範圍及衝突 revision fail-closed；跨期間同比只接受相同 `report_basis`，結果 metadata 會保存 `comparison_period`、`report_basis` 與 `same_basis`。`tests/test_statement_factor_pack.py`、`tests/test_ml_all_field_snapshot_provider.py`、`tests/test_ml_pit_year_shard_exporter.py` 共 19 passed；另相關 factor service、SQLite provider 與季度 parser／batch／plan／summary 套件共 106 passed、1 skipped。skip 是平台 alias 測試限制，沒有當作通過。

r24 staging manifest `quarterly/v4-quarterly-batch-2026q2-continuation-r24-staging-r1-manifest.json`（SHA-256 `8238bfa8150a03991e5b80175c28e71ae566b079e64444cfb3ff1a82b76c5c7f`）是 2026-Q2、每家公司最多一次 attempt 的 bounded run。2596／2640／2641 分別完成 110／146／147 筆，candidate SHA 分別為 `71318f5a4bbb8498dd2ea276dff9ba2c5ae50a9df4e192746ae4267696d2f8e5`、`0ae256bbd963013b6a80d772cfdb9fb09b46f37652f3f3ef67c6747fb5ed6695`、`ed2c4a55130d88e84ff87b25585327448cea35b0c9100d8e743d47ab7d5ac4d4`；三個 child 的 t164 三表、XBRL row-code 與 t57 listing raw 均由各自 run manifest 綁定。2230 的官方 listing 回報 correction，未建立 candidate；2235 回應標題與要求的合併報表不符，未改 caller scope 放行；2643 的 `doc.twse.com.tw` DNS `NameResolutionError` 開啟來源 circuit，2718 因同一 circuit 保留 pending。這些狀態留在 batch manifest，HTTP 200 或列出公司不等於解析完成。

三個成功 child 送入隔離 consumer `quarterly/consumer-r24-staging-r1/consumer.db`；DB SHA-256 `1e7fd6d2ef7595b1bf138a80d11964e96dadfee6846f293aec7f75abfd925303`，marker SHA-256 `eb2c42f7264bd465c7a38c4826abd1b0557fbc207135f30f61a339a08877d2df`，`PRAGMA quick_check=ok`，主表／sidecar 各 403。首次 evidence `first-evidence.json`（SHA-256 `5848dbd63ba3a8393d884773a6d23dbf7f9149769a672a553e1f4750ab92aa4a`）為 403 inserted／0 existing；重跑 evidence `retry-evidence.json`（SHA-256 `7ee96f80e2ca5e434a6748cf5e34bae35a49459f0e81cdcebf2a6fbe0ea5fae8`）為 0 inserted／403 existing。所有 row 的 `report_basis=consolidated`、item code source 為 `mops.t164sb01.xbrl.row_code`，EPS 讀回 2596=`1.81`、2640=`2.49`、2641=`0.54` TWD/share，cash-flow rows 保留 `year_to_date`。本次 capture 已進入台北 2026-09-08，依 date-only 保守規則可用日為 2026-09-09；provider 2026-09-07／09-08 均為 0，2026-09-09 為 403。`formal_db_written=false`、`raw_data_modified=false`。

本片沒有把瀏覽器 DOM 當成 HTTP raw，也沒有重抓已完成 child。r24 的 partial staging 修正先建立 `_partial` 父目錄再 rename 發布，並新增 listing 失敗後仍保留三張 t164、XBRL、evidence 的回歸測試；此修正避免來源後段失敗丟掉可重播 raw。已在 r26 plan 中納入三個實際完成 child；下一批仍由 continuation 自動選取，不會因 2230／2235／2643／2718 的失敗或 pending 把它們算成完成，也未執行 D 槽正式 apply。

`quarterly/r26-new-consumer-summary-r1.json`（SHA-256 `a54fdce3d2ad5b9511470a08ca919704573cafe1388445dac1bd04fcca94d5f`）為本片三家新公司之機器摘要。摘要綁定 r26 batch manifest、三個 child candidate／manifest、隔離 DB、首次／重跑 receipt、cutoff 與 r27 universe；JSON 可直接解析，`quick_check=ok`、361 rows 首次寫入且重跑 0 寫入／361 existing，2026-09-07 與 2026-09-08 均不可見、2026-09-09 可見。r27 universe 已納入 2719、2724、2726 並保留 2221、2230、2235、2643、2718 等 unresolved；摘要沒有把待處理或來源 circuit 的公司算成完成。

### r28 continuation plan checkpoint

r28 成功的 2643、2718 child 已經過 raw／candidate／manifest hash 驗證，納入新的 continuation plan `quarterly/mops-statement-universe-2026q2-continuation-r28-after-r27-ezsearch-r1.json`；檔案 SHA-256=`bba82ee67ccfbf65e9df242d440fff2362e934c29816fc0ec19ff026dd86ab4d`。plan 綁定官方 companies.csv SHA `a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`，eligible=1,974、verified completed=56、caller_excluded/deferred=2（1780 原 deferred、2230 因 correction detail 尚未驗證而明示暫留）、total unfinished=1,918、remaining selectable=1,916；下一批自動選取 2221、2235、2729、2732、2734、2736、2740、2743。2230 的 r28 candidate 仍保留在 immutable research output 與 r28 consumer summary，但不被這份 universe plan 當作 verified completed；2221／2235 也仍是未完成鍵。

更新後機器摘要 `quarterly/r28-consumer-summary-r2.json` SHA-256=`36b7ee2b6d3d9ba2dcf89a8635985467e3559601b8c471c1b6a61a2c5214ec9b` 綁定 r28 batch、r28 plan、3 個成功 child、隔離 DB、首次／重跑 receipt 與 9/8→9/9 cutoff。摘要的 3-child／396-row 是研究型 materialization scope；universe 的 56 verified 與 2 deferred 是完整來源分母狀態，兩者不可相加成全市場已完成。

r28 availability evidence 的來源檔與 hash 也保留在 `quarterly/ezsearch-r28-unresolved-r1/`：2221=`6ba59946d7b49f47fe2f8641d7f85017b7d74eb142ce24eef544227f0f712afb`、2230=`a5b52777546a2b29c64157e1a20fe4b4882a29fafca9d90a5a651d5a2bddfca4`、2235=`643cdb02e238a2bdbe62fb34d00029d7f7dc3c9285dcd4558f86c2736fe99764`、2643=`e573086bad7f220630c5b10a7a8a7d464e8e89070918791d8b9a992c7a3daf07`、2718=`1c8feae0c9bdc620cfc6e193740fbbfb6ff4b744eee6baf92a6ac3339fc956a7`；每份 evidence 都是官方 EZSearch 回應的 3 筆公司／市場／2026-Q2 匹配，並由 batch identity 綁定。三份共用的官方 numeric listing raw（F26/F27/F28）SHA-256 分別為 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、`a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、`3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`；它們只作來源查詢與 availability 觀測，不把公告事件日當 numeric PIT。

### 2026-Q2 continuation r29–r32：2221 row code、2235 個別 scope、2230 更正來源與有界續跑

本片固定了 r28 之後的三個來源問題，並把成功 child 接到既有隔離 consumer。所有 candidate、batch manifest、SQLite 與 receipt 都是 immutable research output；formal_db_written=false、raw_data_modified=false，沒有寫入 D 槽或正式 SQLite，也沒有改寫既有 r28 raw。

2221 的停業單位 EPS 不再依名稱猜碼。官方 XBRL response 的唯一 row code 為基本 EPS 9720、稀釋 EPS 9820；parser 只在已驗證的收入表列與科目／期間上下文中接受這兩筆，單位為 TWD_per_share、scale 100。r29 candidate 為 quarterly/r29-2221-rowcode-r1/v4-quarterly-r29-2221-rowcode-r1-otc-2221-2026q2/statement-pit-candidate.json，SHA-256=fdce2692e5efee66589c450c4336ad1127b8dbd1582bcd74c3a387637c3ab129；child manifest SHA-256=78f5d4772c99d72cb6fa177faa4f28e5fc7532d51aa64a92d2ecdfe5c0768a06，共 173 筆。隔離 DB quarterly/consumer-r29-2221-rowcode-r1.db SHA-256=c062bbc4058f0303215cff372faf660e4d1cd8a038c3c5f2335cb8f794c055，PRAGMA quick_check=ok；首次 173 inserted、重跑 0 inserted／173 existing，provider 在 2026-09-08 為 0、2026-09-09 為 173。r29 universe checkpoint quarterly/mops-statement-universe-2026q2-continuation-r29-after-r28-2221-r1.json SHA-256=15ad93d87fe47dd6ab053adb43d3c5ad8859d5f0492cd2e5dae20010333eca4b，scope 為 eligible 1,974、verified 57、deferred 2、total unfinished 1,917、selectable 1,915。

2235 的 r30 consolidated 失敗是官方 scope 不符，不是放寬標題防護。保存的 t164 balance response HTTP 200、40,243 bytes，raw SHA-256=53fe42c8c1a97af951d0a1d049c1a674c86a65e9c656831ded54c0120407e267；官方標題精確為「個別資產負債表」、115 年第 2 季、期末 115/06/30，XBRL 連結 REPORT_ID=A。r31 以個別報表契約建立新 immutable child，candidate SHA-256=4383b73b01dfc673213bcf8a21d1a2bd61371cca7a7ce4cd58231c19f62b72af，child manifest SHA-256=36f7500dcc1fe378088481951cf20c4ff30a8aa8be51d60ba9538d2e45d34dbb；122 筆為 BS 47／IS 26／CF 49，分別保存 period_end_snapshot／quarter_single／year_to_date 與 report_basis=individual。隔離 DB quarterly/consumer-r31-2235-individual-r1.db SHA-256=daa934e7ead828b9483abbd652aa445e45c9012a023c2f92d16c8958c139f879，quick_check=ok；首次 122 inserted、重跑 0 inserted／122 existing，2026-09-08 不可見、2026-09-09 可見。EPS row code 9750 讀回 Decimal('0.19')，沒有把個別報表冒充合併報表。

2230 的更正來源已由已觀察的官方 MOPS t56 detail URL 做一次 bounded readonly GET。raw quarterly/browser-correction-2230-r2/mops_t56sb31_q1_2230_202602_r2.html 為 HTTP 200、67,024 bytes，SHA-256=76190484349c2e20eec6ab0c0c6c550d49fb4f79f8f831003dc52dc805aecd48；機器證據 quarterly/browser-correction-2230-r2/evidence-r2.json SHA-256=5f2b19e7deffd03f5b02a7d0a90e5c9924e8a3aa5d5f969989f91549ff445b78，JSON 可解析。官方 URL 為 https://mopsov.twse.com.tw/mops/web/t56sb31_q1?step=2&colorchg=1&TYPEK=sii&kind=&CID=2230&YEAR_SEASON=202602&RID=4&DTYPE=I1&SKEY=1&firstin=1，頁面身份為泰茂（2230）、11502、IFRSs 合併財報；更正內容明示「更正115年度第二季合併財務報告合併現金流量表及附註揭露內容」，範圍為現金流量表第 7 頁及附註第 16、19、21、30、33、34、37 頁，附件 URL 亦保留在 evidence。證據狀態為 correction=reported，request/response 時間為 2026-09-07T18:33:37.880004+00:00／2026-09-07T18:33:39.502710+00:00；更正事件只證明官方更正明細存在，不將公告或更正事件日回填為 numeric PIT。r28 candidate 保持 immutable，2230 仍列 deferred，後續需把更正附件／當期 numeric response 做內容比對後才能清除 deferred。

r30 batch manifest quarterly/v4-quarterly-batch-2026q2-r30-next8-http-r1-manifest.json SHA-256=c9f1bdf31667a1b2c5cf025f43830b3f72af91b3b500b43b267086806a8b9f66，7 家成功、963 筆；summary quarterly/r30-next8-consumer-summary-r1.json SHA-256=080a75322d1ea9148f83ada123b9784887bf243c55e4e3c95fca51c5bd47c598 綁定所有 child、DB、receipt 與 cutoff。r32 batch manifest quarterly/v4-quarterly-batch-2026q2-r32-next8-http-r1-manifest.json SHA-256=77fc160b2bbd3aca377f96815839ab1bc9ea1ce76267f22d6d9f01701638a63c，4 家成功、3 家失敗、1 家 pending；成功 child 為 2751（130，candidate SHA 225721eafd9cebdcb4eaccd8e2211216095caadc90f105ffa5ba7381d4dc660c）、2754（119，91bae90c86116a62d80cdcc29929d7ae6816bf2f0e1b89af04add495994089eb）、2755（137，6f31c0658f03029776435a9071ef465718de9889f15646b2c5d24f1147e436ae）、2756（153，69a92f475bb0de8ecd938141e57b2b23043f7b889ff2590c30d69d4ab89c1eca），合計 539 筆。隔離 DB quarterly/consumer-r32-next8-http-r1.db SHA-256=10901371a863b2d052302560b33935a5d9c9e14e330a05632f3b8a171fac14ac，quick_check=ok；首次 539 inserted、重跑 0 inserted／539 existing，2026-09-08 為 0、2026-09-09 為 539。失敗原因保留為 2752 strict Big5/HKSCS 解碼失敗、2916 balance title 不符、2924 doc.twse.com.tw NameResolutionError 並開啟來源 circuit；2926 因 circuit 保留 pending，沒有把 HTTP 200 或 pending 當作成功。

r32 universe checkpoint quarterly/mops-statement-universe-2026q2-continuation-r32-after-r31-next8-r1.json SHA-256=abc24c31e2606df113eb09c10e89b550fa47f46e13e2cfe06a4c0b73746dbb04 維持完整母數：eligible 1,974、verified 69、deferred 2（1780、2230）、total unfinished 1,905、selectable 1,903；下一自動 queue 為 2752、2916、2924、2926、2937、2941、2947、2948。1780 的 no-match 仍只代表該查詢窗口無匹配列，未推論停業或不適用；2230 的 correction 已有官方 evidence，但仍未清除 deferred。來源 circuit breaker 只對失敗來源限制重試，成功 child 以 manifest/hash 重用，不阻塞後續可取得公司。

ML all-field 與跨期間比較沿用 strict report_basis contract：只有具有既有合併來源契約的 legacy row 才可相容預設為 consolidated；未知或空 scope 會保留 unknown／拒絕，跨期間 individual/consolidated mismatch 會拒絕，不靜默產生同比或混合特徵。所有本片輸出仍是研究證據，未宣稱全市場完成。


r29 的機器 consumer summary 為 quarterly/r29-2221-consumer-summary-r1.json（SHA-256=9ae4f4d322549d83b9eef87e3342b1c81cfeeb6b6cd24606d9d6f9eb65301efc），r31 summary 為 quarterly/r31-2235-consumer-summary-r1.json（SHA-256=4c3970cc6403d15f416403eedeb40a9b98847ad145732bd639de210c55256d39）；兩者均綁定 child／DB／首次與重跑 receipt／provider cutoff，沒有只以資料筆數自填完成。

### r34–r35：2752 browser listing replay、2230 correction 與 failure checkpoint

2752 的舊 r32 numeric 取數在 XBRL 解碼階段失敗，原因是官方 response 宣告 charset=big5，但 raw 內有六個已核對、位於 IFRS18／IAS7 敘述項目符號的孤立 0x84；它們不在數值儲存格。raw quarterly/diagnostic-2752-xbrl-r1/mops_t164sb01_xbrl_2752_115Q2.html 為 499,607 bytes，SHA-256=c4afe7da22e2d4190368e381d798dc4afe6900e0e3538fecffc4e9257952c6d1。本輪保留原始 bytes，只在該 raw SHA 綁定的六個 offset 387793、387967、388033、388399、389169、389253 套用 strip_declared_big5_c1_controls；未核對來源、數值內容或識別欄位的 0x84 不會被刪除。修復後仍以 big5hkscs 嚴格解碼，item code 由官方 XBRL row code 解析，沒有用 caller period 或全文 substring 補身分。

官方 doc t57 頁面由 Chrome 直接觀察，DOM 保存與 Big5 replay 的 custody 分開：quarterly/browser-continuation-r2-2752/listing-browser-evidence-r1.json、publication-listing-dom-r1.html（UTF-8 5,044 bytes，SHA-256=a537e04cc7ed8b2ceaece80154aece698e7561c694072e26912db8797d169f0b）、publication-listing-big5-r1.html（4,643 bytes，SHA-256=4ddf639c08e78bbe706e2cf2687f453bc9ed5d97b8e755b478e52e42b055aa9f）。驗證先嚴格 decode／encode，再逐 bytes 比較 replay；raw_http_bytes_saved=false，因此這是 browser DOM observation，不冒充 HTTP raw。官方 row 是豆府（2752）115 年第二季 IFRSs 合併財報、文件 202602_2752_AI1.pdf、上傳時間 2026-08-13T17:25:17+08:00、檔案大小 1,334,257 bytes，listing row hash=b007449f3e53cdef9221c220dc205ee7d9cb49667c9d59d3e2b384fed172133d。觀察完成時間與 t164/XBRL 數值 capture 分開保存；numeric available_date=2026-09-09 是本次完整驗證完成後的保守 date-only cutoff，沒有回填 2026-08-13 公告日。

2752 新 immutable child 為 quarterly/v4-quarterly-r34-browser-2752-r1-otc-2752-2026q2/，candidate SHA-256=8f3c9f8bf3d4550b78f01e8967096f02b4307ac2c75c34dd1633281dc14e78bf，child manifest 由 run manifest 綁定。共 130 筆 accepted numeric rows：balance sheet 45（response named rows 54、excluded 9）、income statement 34（named 40、excluded 6，官方回應中的 EPS 欄位為空，沒有補值）、cash flow 51（named 54、excluded 3）；現金流保存 year_to_date，損益保存 quarter_single，資產負債表保存 period_end_snapshot。XBRL raw 有 150 個 unique official row codes，candidate 與三張 t164 raw 的 source hash 均保留。候選仍是 research-only，不代表全公司財報所有科目都有數值。

2752 已送入隔離 consumer quarterly/consumer-r34-2752-browser-r1.db：PRAGMA quick_check=ok，fundamental_statement_items／mops_statement_consumer_metadata 各 130。首次 evidence consumer-r34-2752-browser-r1-first.json 為 130 inserted，重跑 consumer-r34-2752-browser-r1-retry.json 為 0 inserted／130 existing；provider 在 2026-09-08 回傳 0、2026-09-09 回傳 130，EPS 未物化（官方三表 EPS row 空白）。DB SHA-256=791f298128ddb237af5eaa735cca78f59d24996d7950374a7ff1e9371e8ba8e6。批次機器摘要 quarterly/r35-quarterly-recovery-summary-r1.json SHA-256=52840b3c30e36679907571522480ca2ddb3d60c088a1dfbfac594d9bbc0d1f9d 綁定 candidate、child manifest、browser DOM／replay、DB、首次／重跑 receipt 及 unresolved failure。

2230 更正附件已完成 numeric 逐項比對。官方 t56 raw HTTP 200、67,024 bytes，SHA-256=76190484349c2e20eec6ab0c0c6c550d49fb4f79f8f831003dc52dc805aecd48；頁面身份是泰茂（2230）、11502、IFRSs 合併財報。第 7 頁七個 row code（A21200、A22500、A20010、A20000、A33100、AAAA、DDDD）的更正後 TWD 值都與既有 numeric candidate 逐項相等；期間均為 2026-01-01～2026-06-30、year_to_date。第 16、19、21、30、33、34、37 頁只列為 disclosure-only，沒有把附註內容猜成 statement row。replacement candidate 保留數值 capture 與 conservative availability，舊 r28 candidate 不覆寫；supersedes record quarterly/r33-2230-correction-r1/2230-supersedes-r28-correction-r1.json 綁定新舊 candidate／manifest hash，replacement candidate SHA-256=b6d1b46eab7210130933840d1f8392f9dea4eea0e9b91dfc05d7a9cf5f952c77，matched item count=7，historical PIT backfill=false。2230 已從 deferred correction 狀態清除，但正式 DB 仍未寫入。

r35 continuation plan quarterly/mops-statement-universe-2026q2-continuation-r35-after-r34-2752-browser-r1.json SHA-256=42c5047d89d33512824a84b9dbb46f0a2a749a4b66ae09570ed66545a1ac6294 綁定 D 槽 companies.csv SHA-256=a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41。目前全 scope 是 eligible=1,974、verified completed=71、caller-excluded/deferred=1（1780:tpex）、remaining selectable=1,902、total unfinished=1,903；下一批為 2916、2924、2926、2937、2941、2947、2948、2949。先前未保留 1780 deferred 的 r34 草稿不作 authoritative plan，r35 為可續跑 checkpoint。

本片 failure checkpoint 仍保留完整分母與具體原因：2916 partial phase=statement_fetch，官方 response 不含要求的合併資產負債表標題，沒有把 HTTP 200 當作成功；2924 phase=listing_fetch，doc.twse.com.tw NameResolutionError，partial replay_ready=true 且保留三張 t164／XBRL raw，來源 circuit 開啟後不重複盲抓；2926 沒有 attempt，維持 pending／source_transport_circuit_open。2752 的舊失敗 partial 也保留，已由 r34 replay child 取代。機器摘要同時綁定上述 partial-failure hash、raw 清單與下一步，不把 unresolved 從欠帳移除。D 原始、正式 availability mapping 與正式 SQLite 本片均為只讀；所有新 candidate／consumer 都是隔離 research output，未刪既有 raw，未執行正式 apply。

### r36：八家 bounded EZSearch fallback、隔離 consumer 與 universe checkpoint

r36 以既有成功的 t164/XBRL HTTP 取數契約重用 numeric lane，對 2916、2924、2926、2937、2941、2947、2948、2949 各只保留一個有界的 EZSearch availability capture。官方 `mopsov.twse.com.tw` EZSearch capture manifest 為 `quarterly/ezsearch-r36-next8-r1/capture-manifest.json`（SHA-256=`29b252969faf78bcf7a3959d05975021c466a6949e596b714bb3af45bd7788c2`），F26／F27／F28 三份原始回應 SHA-256 分別為 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、`a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、`3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`；八份 evidence 均為 stock／market／2026-Q2 三筆匹配且 `errors=0`。這條 lane 只確認官方 publication response，不把公告事件日回填為 numeric PIT；numeric availability 沿用完整 capture 完成後的保守 next-Taipei-day date-only 規則。

| 公司 | scope | rows | candidate SHA-256 | available_date |
| --- | --- | ---: | --- | --- |
| 2916 | individual | 112 | `b727781afcae912cceb2307626c7b4097de26c607e3f8a9b05118d146fae0cb2` | 2026-09-09 |
| 2924 | consolidated | 119 | `885745be16bd42b65509f07fb30688e5d656006a6e5a517088e98b01b1a99195` | 2026-09-09 |
| 2926 | consolidated | 148 | `d3efc8cb3e8d5261bca50b36b8d07626dab4adf7d78c2093589dfaa910ccf9c2` | 2026-09-09 |
| 2937 | consolidated | 120 | `19f43fcb92e70a0b016518e92c929d375c4520bccf55e1558d08a0d562a55627` | 2026-09-09 |
| 2941 | individual | 110 | `4057d56333ffe25c4cb0e1acb22f64674306a3cb9a20f6f2837ca193d46f1084` | 2026-09-09 |
| 2947 | consolidated | 122 | `d29340e2dd94f236040e5e4e94eae90d23fd871b66ea8472de65fa5f8eeeb27d` | 2026-09-09 |
| 2948 | consolidated | 111 | `89fcf8d6ad2d1a20dc8b83ed74539a981257bff04f281825663e72d6ff33f` | 2026-09-09 |
| 2949 | consolidated | 139 | `bc408d6e7cba6844057f7cd78e5632842669cc7f298b6d006b004d2ec1ba7f60` | 2026-09-09 |

八家合計 981 筆。2916 與 2941 的 consolidated 路由因官方 t57 回應標題為個別財報而 fail-closed，改以 individual contract 完成；2926 的 doc host DNS failure、2937 的首次 doc host failure、以及 2947／2948／2949 的初始 circuit pending 均保留在 batch manifest，沒有以 HTTP 200 或 pending 充當成功。2916／2941 的官方 individual scope 也由 report title／period 驗證，沒有把合併報表冒充個別報表。

八個 immutable child 已送入隔離 consumer `quarterly/consumer-r36-next8-ezsearch-r1.db`。DB SHA-256=`faddb6541915ee77486f5a9b26b38e4cab5764dee476d5b0ae1140ed6c5fb1e2`，`PRAGMA quick_check=ok`，`fundamental_statement_items`／`mops_statement_consumer_metadata` 各 981；首次 receipt `quarterly/consumer-r36-next8-ezsearch-r1-first.json`（SHA-256=`cffe6b0f34822c9605d4975e6b007adb90937ddb7710e8690326826c893faafa`）為 981 inserted，重跑 receipt `quarterly/consumer-r36-next8-ezsearch-r1-retry.json`（SHA-256=`b88298c55f426cafc2ca678038aa481263517f06a4b48433fcae1710ad55d7f6`）為 0 inserted／981 existing。provider readback 在 2026-09-07 與 2026-09-08 均為 0，2026-09-09 為 981；八家 EPS 經既有 consumer 讀回且保存 `TWD_per_share`、scale 100、`quarter_single` 及各自 report_basis，沒有把分／股誤讀成元／股。此 DB 的 research-only marker SHA-256=`1da7e6ed85ea4e189440020b9d53d140bba772910ad2cea1cbb024afa2585fd5`。

機器摘要 `quarterly/r36-next8-consumer-summary-r1.json`（SHA-256=`e470a4788395813b48a540950f79fedac81442f6b117aa37380589039efedaba`）綁定七份 r36 batch manifest、八個 child、candidate／manifest hash、隔離 DB、首次／重跑 receipt 及 cutoff；交接封裝 `quarterly/r36-quarterly-recovery-handoff-r1.json`（SHA-256=`b0e27e07ab28af5812e07627beb4612a937d434b5665c3c44a1fee3539f37e5c`）另綁定 EZSearch raw／evidence、失敗沿革及 2230 更正摘要。兩份 JSON 均可直接解析，`formal_db_written=false`、`raw_data_modified=false`。

r36 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r36-after-r35-next8.json`（SHA-256=`7bae22c541e11d72151e76475948305819dc42fc347b1703dc892970687807b2`）維持官方 companies.csv 分母 eligible=1,974；verified completed=79（前序 71 加本批 8）、deferred unresolved=1（1780:tpex）、total unfinished=1,895、remaining selectable=1,894。下一自動 queue 為 3064、3066、3067、3071、3073、3078、3081、3083；1780 未因 caller exclusion 消失，也沒有把本片 bounded slice 宣稱為全市場恢復。

2230 更正的精簡 numeric mapping 與既有 consumer 讀回如下；七列均為 2026-01-01～2026-06-30、`year_to_date`，更正後 TWD 值與 replacement candidate 逐項相等：

| official item code | 更正後 TWD | candidate／consumer |
| --- | ---: | --- |
| `A21200` | -3,678,000 | -3,678,000 |
| `A22500` | 3,000 | 3,000 |
| `A20010` | 25,889,000 | 25,889,000 |
| `A20000` | 206,687,000 | 206,687,000 |
| `A33100` | 3,678,000 | 3,678,000 |
| `AAAA` | 100,826,000 | 100,826,000 |
| `DDDD` | 46,443,000 | 46,443,000 |

2230 correction comparison path 為 `quarterly/r33-2230-correction-r1/v4-quarterly-r33-2230-correction-r1-otc-2230-2026q2/correction-comparison-r1.json`（SHA-256=`bc295095b4fe29eaa895a28661f0d0d878a9d8ceb84c0d4e5e51a5b07f7ba9cd`），supersedes record 為 `quarterly/r33-2230-correction-r1/2230-supersedes-r28-correction-r1.json`（SHA-256=`9afa43640bc76971043b2ef0284ee5d47e41f277189891151c3bd84752488175`）。replacement candidate 不覆寫舊 immutable，`historical_pit_backfill=false`；隔離 consumer `quarterly/consumer-r33-2230-correction-r1.db` 的 main／sidecar 各 137、`quick_check=ok`，EPS item `9750` 讀回 `-0.26 TWD/share`。第 16、19、21、30、33、34、37 頁維持 disclosure-only，沒有猜成 statement row。

本片驗證：`tests/test_build_mops_statement_batch.py`、`tests/test_mops_statement_candidate_adapter.py`、`tests/test_summarize_mops_statement_consumer_batch.py`、`tests/test_plan_mops_statement_universe.py` 共 40 passed、1 skipped；skip 是既有平台 alias 限制，沒有當作成功。另對本片使用的 batch／capture／summary／plan scripts 執行 `py_compile` 成功。所有取數為 bounded official read-only 或既有 raw reuse；D 槽原始資料與正式 DB 維持只讀，未執行正式 apply。

### r37：3064 明確 row-code alias、3081 個別財報與八家公司隔離恢復

r37 先依 continuation plan 自動選取 3064、3066、3067、3071、3073、3078、3081、3083，numeric lane 單批上限 8、每家公司最多 1 次、同一 `doc.twse.com.tw` transport failure 上限 1。首次 HTTP batch 在 3064 發生官方 doc host DNS `NameResolutionError` 後開啟 circuit，後續 7 家保留 pending；利用同批一次的官方 mopsov EZSearch availability capture 重播 numeric 流程，成功 6 家。3064 的 t164 raw 已保留在 partial staging，官方 XBRL 明確列 `4600=勞務收入合計`，顯示表列為 `勞務收入淨額`，同期值均為 19,635（仟元）；新增的 alias 只在 income statement、候選值／scale、縮排與官方 row code 同時匹配時生效，離線 replay 產生 127 筆 consolidated child。3081 的 consolidated balance title 不符而拒絕，個別契約通過後產生 113 筆 individual child。沒有使用通用「合計」替換、caller 期別或 HTTP 200 充當成功。

EZSearch capture manifest `quarterly/ezsearch-r37-next8-r1/capture-manifest.json` SHA-256=`b1b99d86ac7d3e7a074439334c7ff296ed39f7988029f63be3dee874bee87220`，八家公司各有 F26／F27／F28 三筆官方 2026-Q2 匹配；三份共用 raw SHA-256 分別為 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、`a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、`3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`。這些 evidence 只負責 publication／availability lane；numeric capture completion 後採保守 next-Taipei-day date-only 可用日 2026-09-09，沒有回填官方公告日或歷史 PIT。

| 公司 | report_basis | rows | candidate SHA-256 | EPS 讀回（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3064 | consolidated | 127 | `985ac8bad1bffac76a0746569599880c81264eb553b5685f9284730e4e907312` | -0.46 |
| 3066 | consolidated | 146 | `db97178e3652613bb088e15f1400507c2da33c772a95a81c28e8be5db78f5b7d` | 4.89 / 4.86 |
| 3067 | consolidated | 119 | `0616e0a182a3b517cea971caa85db8ed3d625184659795ad7bfd190c37986b87` | 0.00 |
| 3071 | consolidated | 147 | `667d0b1c5683ee29d1cda691018a663b943e3a0efa5e0cdb0ae9b402bce95865` | 0.34 |
| 3073 | consolidated | 133 | `003e8412a5ef1b7f77f1e954bfc673914fcf2bcfc3aace1d7f516358a4697b11` | -0.26 |
| 3078 | consolidated | 116 | `bdc0025858532150a7280f30138a6290ab9c707498a1426fb7362df726a45f8f` | 0.30 |
| 3081 | individual | 113 | `9d2133b942dd490584062ab623d7cf215f91380ed3d9d9e369542ac90e77a5ee` | 4.62 |
| 3083 | consolidated | 121 | `ead9c05c0f2abf91234c612fc5032143247afdef777a8415b4603cb9f74c0d4d` | 0.00 |

八個 immutable child 合計 1,022 筆，均由 `mops.t164sb01.xbrl.row_code` 提供 item-code lineage。隔離 consumer `quarterly/consumer-r37-next8-ezsearch-r1.db` SHA-256=`a168ef059974cf1ef02996fe1181a00d1f0e6a2056f88db4155267c73f0b4ebf`，`PRAGMA quick_check=ok`，主表／sidecar 各 1,022。首次 receipt `quarterly/consumer-r37-next8-ezsearch-r1-first.json` SHA-256=`b6913f3f956939520b8d9e8646b4bd366d2224e31e10d454e63d0c11ce34bbfb` 為 1,022 inserted；重跑 receipt `quarterly/consumer-r37-next8-ezsearch-r1-retry.json` SHA-256=`10e492083295b617aa389a75a692722d3c3f89acbef60bac4ffbf85732e639cd` 為 0 inserted／1,022 existing。provider 在 2026-09-07、2026-09-08 均為 0，2026-09-09 為 1,022；各 row 保留 period basis 與 individual／consolidated scope。research-only marker SHA-256=`c01652c1005613317749b3e7df50edeccce0c713160326ee92cb364526269c5e`。

機器摘要 `quarterly/r37-next8-consumer-summary-r1.json` SHA-256=`6f8f718717b8c224532f2357724af9d4dbc70531cb5f70393f67632e13578b50` 綁定 4 份 r37 batch manifest、8 個 child、所有 candidate／manifest hash、隔離 DB、首次／重跑 receipt 與 cutoff；交接封裝 `quarterly/r37-quarterly-recovery-handoff-r1.json` SHA-256=`f57339dbe800909933b534377a11afe7a374ae224ef9d51d9ca93b92798e1f9e` 另保存 alias／scope 修復契約、失敗沿革與 r36 handoff lineage。r37 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r37-after-r36-next8.json` SHA-256=`5fd42ba5cac37e4c15e9324ee15959de2862bb3fd02b38938775680dd017d582` 維持 eligible=1,974、verified completed=87、deferred unresolved=1（1780:tpex）、total unfinished=1,887、remaining selectable=1,886；下一批自動 queue 為 3085、3086、3088、3093、3095、3114、3115、3118。1780 仍在完整分母，沒有被 caller exclusion 當成完成。

本片程式修正為 `scripts/build_mops_statement_pit_candidate.py` 的 3064 狹義名稱對照，並新增 `tests/test_mops_statement_3064_alias.py`：官方 4600／值匹配正例與錯期別值拒絕負例。批次、adapter、summary、plan、candidate parser 與 alias 定向套件共 97 passed、1 skipped；skip 是既有平台 alias 限制。r37 使用的批次／capture／plan／summary scripts `py_compile` 成功。所有 output 為 workspace research artifact；D 槽原始資料、正式 availability mapping 與正式 DB 維持只讀，未執行正式 apply。

### r38：3088 EZSearch 延伸窗口、八家公司隔離 consumer 與可續跑 checkpoint

r38 依 r37 continuation plan 有界選取 3085、3086、3088、3093、3095、3114、3115、3118 八家，沿用 EZSearch publication lane、t164/XBRL numeric lane、strict company／period／official row-code／unit 驗證與 immutable child。初始 EZSearch 窗口 `2026-08-01..2026-09-07` 的 capture manifest `quarterly/ezsearch-r38-next8-r1/capture-manifest.json` SHA-256=`004ad8eb659524042c803e193373e2d3a26ef3d42c83677ca5918207fe07fb54`；七家及 3118 各有 F26／F27／F28 唯一匹配，但 3088 在該窗口三項均為 `no_matching_company_period_row`。沒有把 HTTP 200 或窗口無匹配推論成公司不存在。

對 3088 只做一次有界延伸窗口 `2026-07-01..2026-09-07`，capture manifest `quarterly/ezsearch-r38-3088-broader-r1/capture-manifest.json` SHA-256=`c4ae944aebdbb7ac8afee52b07d55453a1d82e3e36c95455597e8255ec5fbcbb`；F26／F27／F28 均匹配艾訊（3088）、2026-Q2，官方 `CDATE=115/07/30`。這只證明 publication lane 可觀察；數值 candidate 的 `numeric_available_at` 仍取本次完整 capture completion，沒有把 7/30 回填成歷史 PIT。三份延伸窗口 raw SHA-256 分別為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`；3088 availability evidence SHA-256=`10c7445677d7c368440b9b8cb1689051fe11766901e56461331db65076b55504`。

r38 numeric batch manifest `quarterly/v4-quarterly-batch-2026q2-r38-ezsearch-next8-manifest.json` SHA-256=`1aa9810df191d8377194307c264358d7ac6789a4670bda447888b8030cddca92`。初次 EZSearch evidence 路由完成 6 家、3088 因无匹配失败、3118 因 consolidated balance title 不符而 fail-closed；3118 以個別報表契約重試，individual batch manifest `quarterly/v4-quarterly-batch-2026q2-r38-individual-3118-manifest.json` SHA-256=`07be9dfa972eb55af5f946f046ffcfcb5c3445ad47e167b59186c39f481da84b`，完成 106 筆。3088 使用上列延伸 evidence 重播既有官方 numeric route，建立新 immutable child；batch manifest `quarterly/v4-quarterly-batch-2026q2-r38-3088-broader-r1-manifest.json` SHA-256=`cd67bdcb53d734be3a54dae84c71693eb7818324056557ea53b4f292514fea57`，完成 147 筆。三個 batch 均保留各自 attempt、raw／evidence hash 與 failure 沿革，没有覆寫初始失败目录。

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3085 | consolidated | 113 | `ba593e30add4dfb025e76fb31d9803f42b419522a1e5476b7d856b463471ef2f` | -0.10 |
| 3086 | consolidated | 120 | `cbb9fa455639682e16abe13664fa0929139b7b1d2487c8b0a6cd97c51cd71c52` | -0.05 / -0.05 |
| 3088 | consolidated | 147 | `cd555695edc4dd90f0c056871fa544e10fcd36f101886a51869ac92b12171324` | 2.03 |
| 3093 | consolidated | 130 | `4b40d360c1c2e83697a4ac8005b7629889049f7a67b9d611ce59b909535c60cd` | 0.33 |
| 3095 | consolidated | 127 | `26aea203a45490d890b3e552aca25ff30475119177ebad310d0dc5a59a1a1caf` | 0.98 |
| 3114 | consolidated | 119 | `d5b4236d5b5051215d35df93a8eb5b490aa99e1c8102dbd0b7c1cb9b7b94eb57` | 0.32 |
| 3115 | consolidated | 105 | `8b9b2af2d13f86a741920fbfa610a6ecf22d2efb6a416b7b9fd3983cf314bd4c` | 0.02 |
| 3118 | individual | 106 | `a26ec38a1b8d3b17d2bf09108be281dd98162561bc862062c553429ac1b985b5` | 0.42 |

八個 child 合計 967 筆；三表及 XBRL item code 由官方 raw lineage 綁定，cash flow 保存 `year_to_date`、income 保存 `quarter_single`、balance 保存 `period_end_snapshot`。所有 row 的 numeric capture 在台北日期已進入 2026-09-08 後完成，故 date-only `available_date=2026-09-09`；隔離 consumer 在 2026-09-07／09-08 均讀回 0，2026-09-09 讀回 967。沒有用公告日 2026-07-30 或 8/1 窗口假設作歷史可得日。

八個 candidate 送入 `quarterly/consumer-r38-next8-ezsearch-r1.db`；DB SHA-256=`b56c3ba045702a39cf7c191cbce934b8a84fe078d7d27ed3deb9263b61f550d8`，marker SHA-256=`5c8f1b53506121787efc9d2fa15d0fc050e4026fd3529dc3c014a7ce0443ab0e`，`PRAGMA quick_check=ok`，主表／sidecar 各 967。首次 receipt `quarterly/consumer-r38-next8-ezsearch-r1-first.json` SHA-256=`6d4eafc1590291db0154f6de0ffdf98245ac501fee22f2b9e48553cce2f9e51f` 為 967 inserted／0 existing；重跑 receipt `quarterly/consumer-r38-next8-ezsearch-r1-retry.json` SHA-256=`126bf14a2065678eeeb6b58ab9837d37e07f4e3b773b9f954c45eeb93f891171` 為 0 inserted／967 existing。EPS 由既有 consumer 讀回為 3085=`-0.10`、3086=`-0.05`／`-0.05`、3088=`2.03`、3093=`0.33`、3095=`0.98`、3114=`0.32`、3115=`0.02`、3118=`0.42` TWD/share，且 3118 的 individual scope 保留在 sidecar，沒有混成 consolidated。

r38 機器摘要 `quarterly/r38-next8-consumer-summary-r1.json` SHA-256=`c38ef95d0ecb36f2075f2a22ead670cc39c67cb4a1711fd36d4b3bc0d2454ae2` 綁定三份 r38 batch manifest、八個 child、candidate／manifest hash、隔離 DB、首次／重跑 receipt 與 cutoff。交接封裝 `quarterly/r38-quarterly-recovery-handoff-r1.json` SHA-256=`ee1ec087963599b2da757c63ca14c744f4b1f2672649e6cbb0a5bd0eb314d297` 遞迴核對 37 個 path/hash reference 均一致；相同輸出由 `PRAGMA quick_check=ok` 與 row count 機器檢查重驗。r38 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r38-after-r37-next8.json` SHA-256=`6c1bed9f4611bd499c946d739883c563514121851cd735ac91f280dd77aeeec6` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`，eligible=1,974、verified completed=95、deferred unresolved=1（1780:tpex）、total unfinished=1,879、remaining selectable=1,878；下一自動 queue 為 3122、3128、3131、3141、3147、3152、3158、3162。1780 仍保留在完整未完成分母。

本片定向回歸為 `tests/test_build_mops_statement_batch.py`、`tests/test_mops_statement_candidate_adapter.py`、`tests/test_summarize_mops_statement_consumer_batch.py`、`tests/test_plan_mops_statement_universe.py`、`tests/test_build_mops_statement_pit_candidate.py`、`tests/test_mops_statement_3064_alias.py` 共 97 passed、1 skipped；skip 是既有平台 alias 限制，沒有當作成功。r38 使用的 batch／capture／materialize／summary／plan scripts `py_compile` 成功。所有輸出均為 bounded research evidence，`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 DB 維持只讀，未執行正式 apply。後續沿 r38 plan 每批最多 8 家、成功 raw reuse、source circuit／resume 與 immutable consumer receipt 繼續，不把本片宣稱為全市場恢復。

### r39：3141 延伸公告、3152 個別報表與八家公司隔離恢復

r39 沿 r38 continuation plan 有界選取 3122、3128、3131、3141、3147、3152、3158、3162 八家，先以 EZSearch publication lane 核對 F26／F27／F28，再由 t164/XBRL numeric lane 嚴格驗證公司、期別、官方 row code、單位與 report basis。初始公告 capture `quarterly/ezsearch-r39-next8-r1/capture-manifest.json` SHA-256=`85722f7a3c9113e2c24540f099ab84bfcb77441c2999401e8e72e2ab845b2e12`；3141 在 `2026-08-01..2026-09-07` 無匹配而保留 unresolved，3152 則有 3 筆公告但 consolidated numeric 路由的 balance title 不符，均沒有以 HTTP 200 當成功。

3141 只做一次 `2026-07-01..2026-09-07` EZSearch 延伸查詢，capture `quarterly/ezsearch-r39-3141-broader-r1/capture-manifest.json` SHA-256=`a13c51468a00fed3e903cf148906b49f1713528b6f5aee3484aa1d45fe5aad7b`；F26／F27／F28 均匹配晶宏（3141）、2026-Q2，官方 `CDATE=115/07/31`。延伸 evidence SHA-256=`18b8c344fc12b016cd6228128f475854d3b52a74844c110dca3ae949631d46a7`，共用 raw SHA-256 為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`。3152 的同批公告 evidence 已在 initial capture 严格綁定，後續只改報表 scope 為 individual，沒有猜日期或放寬 title guard。

r39 numeric 初次 batch `quarterly/v4-quarterly-batch-2026q2-r39-ezsearch-next8-manifest.json` SHA-256=`74ae7a5f4b69e1c35360b1d2bd2d9cda52d12ff25806ceb638a829b085d4cb65` 完成 6 家；3141 延伸 batch `quarterly/v4-quarterly-batch-2026q2-r39-3141-broader-r1-manifest.json` SHA-256=`7e6ddf50b09bf18b0c3a75c5db20d1e29a70c0ca9c04d31e88d1a394409051bb` 完成 142 筆；3152 individual batch `quarterly/v4-quarterly-batch-2026q2-r39-3152-individual-r1-manifest.json` SHA-256=`cb9332a5a3e6343beffff7c037777f9249a46831c229d6274916458c2289d29f` 完成 91 筆。原批次的 3141／3152 failure attempt 與 partial artifact 均保留，沒有覆寫；成功 child raw 只在各自 immutable output 建立一次。

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3122 | consolidated | 119 | `d91ed7f8817b331b4dbd967f8b6543a197670911eae8e4eebab7dfb7e06a5857` | -0.44 |
| 3128 | consolidated | 138 | `92843a98cbcf0540f82c005977c609ce09d3237e8e72057123ee9a77db86b8cb` | -0.03 / -0.03 |
| 3131 | consolidated | 169 | `32297c86846b1f799be081c64fbf39eb836a8766df2170748b44554c8b542f26` | 11.18 / 11.07 |
| 3141 | consolidated | 142 | `69ec1fad62adfd6acbe1bce6f63dfd26ad80f15e1c8bcc81f51c76c59ab2a63c` | 1.35 / 1.24 |
| 3147 | consolidated | 147 | `4c4affd52d980d250616d37503f7c8a422012286d7de5e50fc73757e81e7e90c` | 7.60 / 7.60 |
| 3152 | individual | 91 | `832372a16e3c5e6f761a5f81b2fdf84f95b5473669bf080232ea450b7af9ebf7` | 1.89 |
| 3158 | consolidated | 115 | `9880f46c200727014ebed085cc481719f0cff0de73b367abce63a4a36a1e30b2` | 1.98 |
| 3162 | consolidated | 160 | `0b096f4fead4eef90146005c36711310b39a807563b16f4f5918a7b110212b36` | 0.03 / 0.03 |

八個 child 合計 1,081 筆；balance sheet、income statement、cash flow 的 period basis 分別保留 `period_end_snapshot`、`quarter_single`、`year_to_date`，3152 的 individual 範圍留在候選與 sidecar。numeric capture 完成時台北日期已進入 2026-09-08，故 date-only policy 給 `available_date=2026-09-09`，沒有把 3141 公告日 7/31 或 3152 公告日 8/4 回填成歷史 PIT。

八個 candidate 送入 `quarterly/consumer-r39-next8-ezsearch-r1.db`；DB SHA-256=`87ce3c45a07602475d8d8885f5dd16e6af2cc6c592b337eb08ccf0a2d05ec03d`，research-only marker SHA-256=`df965777a97eb3b656962beff2d4be421a3b84b6b9248dcd8d19a6af1d5c3a7d`，`PRAGMA quick_check=ok`，主表／sidecar 各 1,081。首次 receipt `quarterly/consumer-r39-next8-ezsearch-r1-first.json` SHA-256=`002527779bbc65839a0f9a8444a2182491316a42432973299c61503aaafa448a` 為 1,081 inserted／0 existing；重跑 receipt `quarterly/consumer-r39-next8-ezsearch-r1-retry.json` SHA-256=`fdaf8820d4a74a392afda1a47117137bed3ad77f6241bf896bc63954235ebf16` 為 0 inserted／1,081 existing。provider readback 在 2026-09-07／09-08 均為 0，2026-09-09 為 1,081；EPS 讀回均為 TWD/share Decimal，沒有把 cents/share 當元／股，個別與合併 scope 沒有混淆。

r39 機器摘要 `quarterly/r39-next8-consumer-summary-r1.json` SHA-256=`9413e62189f4a7e1371c920ce419722eda578c3029e5bbd0dba4d4fa6f3a1ad9` 綁定 3 份 r39 batch manifest、8 個成功 child、candidate／manifest hash、隔離 DB、首次／重跑 receipt 與 9/8→9/9 cutoff。交接封裝 `quarterly/r39-quarterly-recovery-handoff-r1.json` SHA-256=`7d6c74eeb6908bdc654ea9f153398f6cebce3f6eaaa41a8bae7085cdd26c8c3b` 遞迴核對 37 個 path/hash reference；universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r39-after-r38-next8.json` SHA-256=`4e7ca3e85dd892e3973cdf6de5b2ee396a51497c2695f05d548c6e219d778b8f` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`，eligible=1,974、verified completed=103、deferred unresolved=1（1780:tpex）、total unfinished=1,871、remaining selectable=1,870；下一自動 queue 為 3163、3169、3171、3176、3178、3188、3191、3205。

本片定向 batch／adapter／summary／plan／candidate parser／3064 alias 測試共 97 passed、1 skipped；skip 是既有平台 alias 限制，沒有當作成功。相關 batch、capture、materialize、summary 與 plan scripts `py_compile` 成功。全部輸出仍為 bounded research evidence，`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 DB 只讀，1780 留在未完成分母，後續可沿 r39 plan 每批最多 8 家繼續恢復。

### r40：3169 EZSearch 延伸、八家公司隔離 consumer 與續跑 checkpoint

r40 依 r39 continuation plan 有界選取 3163、3169、3171、3176、3178、3188、3191、3205 八家，先用 MOPS EZSearch publication lane 驗證 F26／F27／F28，再由 t164/XBRL numeric lane 嚴格核對公司、2026-Q2 期別、官方 row code、單位與 `report_basis`。初始 `2026-08-01..2026-09-07` capture `quarterly/ezsearch-r40-next8-r1/capture-manifest.json` SHA-256=`eff12ce790ae1360a7bccbf5a62085ef3bf8a32d921fa6e5207f09fc97a4f1d5`，7 家三項公告均唯一匹配；3169 的 F26／F27／F28 均為 `no_matching_company_period_row`，沒有把 HTTP 200 或查詢窗口無匹配推論成公司不存在。

3169 只做一次有界延伸 `2026-07-01..2026-09-07`，capture `quarterly/ezsearch-r40-3169-broader-r1/capture-manifest.json` SHA-256=`9055dcfc54b4193fb87cb6e0490f064f7c9ca8575545fb89988f9e1bf5a419db`，三項均匹配亞信（3169）、2026-Q2，官方 `CDATE=115/07/22`；延伸 evidence SHA-256=`0b018064f06f5467d08ed3ffcbc6f4923807df723c1802a25d5a2ad99f6cadeb`。三份共用延伸 raw SHA-256 為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`。這只修復 publication lane 的可觀察範圍；3169 numeric candidate 仍以完整 capture completion 計算可得時間，沒有把 7/22 回填成歷史 PIT。

r40 初始 numeric batch `quarterly/v4-quarterly-batch-2026q2-r40-ezsearch-next8-manifest.json` SHA-256=`a8a1022171972fbba8577eb1a5ec5a5ed3e170aeea31a3fe3a9f3519cbcb21d3` 完成 7 家、3169 失敗；3169 延伸 batch `quarterly/v4-quarterly-batch-2026q2-r40-3169-broader-r1-manifest.json` SHA-256=`e95c678f7916fda92f3c83a7be687ec7421030f3787dea1ba004131ff26d052b` 完成 1 家。初始 failure receipt 保留 `EZSearch availability evidence has no unique company/period row`，延伸只重用已保存官方 numeric raw，不覆寫初始目錄或已成功 child。

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3163 | consolidated | 130 | `374e835a23ba027224899190232f29e29e65ed38227cb61b405e6dc3c9945468` | 0.93 / 0.93 |
| 3169 | consolidated | 98 | `43c0e2a98041f1c36b6dc1d925eff75c08e5117fd7850c41950500f92e6ca718` | 0.99 |
| 3171 | consolidated | 141 | `8465b96c1e3657b13b6678d2d360b27003ae98d92def2be2cbed33d67c9a20ce` | 2.35 / 2.15 |
| 3176 | consolidated | 155 | `5808c35b25d0cef35c060e32cb74e6b322dcc9373cec6fa76af80e2137dad1a9` | -0.19 |
| 3178 | consolidated | 137 | `c06fc75d26e70d6f980ecd8e79220fe22f7933e691135d6f2ec5a0ccbec74295` | 0.43 / 0.43 |
| 3188 | consolidated | 110 | `1615aa126c93ba7aa9f53f44a6e18fde8b2610ec3069a3846c76bec2641373dc` | 1.16 |
| 3191 | consolidated | 121 | `81bc179aa3b419ad9014ec53f1be707f9f5c82bdcd348844154c90f6b6036b7f` | 0.06 |
| 3205 | consolidated | 117 | `7cb60aa1c13d2df056bcf28adab6542950269fa01cc7cac0d6ccae4cfa023f98` | -0.02 |

八個 immutable child 合計 1,009 筆，candidate 與 sidecar 均保留 `consolidated` scope；balance sheet、income statement、cash flow 的 period basis 分別保存 `period_end_snapshot`、`quarter_single`、`year_to_date`。隔離 consumer `quarterly/consumer-r40-next8-ezsearch-r1.db` SHA-256=`ce20d665eb2c5afb9253509aaf6013b9b3610918ebdbb01de9a922508303387a`，research-only marker SHA-256=`a726dca9ec10919aaec64d715e3a26a780017964f4ceb47001a09ab5c0b63ed9`，`PRAGMA quick_check=ok`，主表／sidecar 各 1,009。首次 receipt `quarterly/consumer-r40-next8-ezsearch-r1-first.json` SHA-256=`22745f2fba07923d93573586c60b005f283012fae87ea138fa5ae82eb5229fd9` 為 1,009 inserted／0 existing；重跑 receipt `quarterly/consumer-r40-next8-ezsearch-r1-retry.json` SHA-256=`81feeffbdde20a36d8d9bce097d3e53f349816b3dbf3076a4f4e8b7ee98d84be` 為 0 inserted／1,009 existing。provider 在 2026-09-08 讀回 0、2026-09-09 讀回 1,009；全部 EPS 以 TWD/share Decimal 讀回，沒有把 cents/share 當元／股。

r40 機器摘要 `quarterly/r40-next8-consumer-summary-r1.json` SHA-256=`076e51c380e0ba7307f861a915936f993868bad5561535420dfe787ae7b28eda` 綁定兩份 batch manifest、八個 child、candidate／run manifest hash、兩份 EZSearch capture、隔離 DB、首次／重跑 receipt、cutoff 與 universe plan。交接封裝 `quarterly/r40-quarterly-recovery-handoff-r1.json` SHA-256=`467947b960316b7c2570ee2ad435e46cb0b02ada2b50b0efd5db3923d03989f5`，遞迴核對 35 個 workspace path/hash reference 均一致；`quarterly/mops-statement-universe-2026q2-continuation-r40-after-r39-next8.json` SHA-256=`93eb77c4204f4ab853817a75e6ac8ed9878e4894f3560f858aaa4fafa81a766e` 維持官方 companies.csv 完整分母 eligible=1,974、verified completed=111、deferred unresolved=1（1780:tpex）、total unfinished=1,863、remaining selectable=1,862；下一自動 queue 為 3206、3207、3211、3213、3217、3218、3219、3221。1780 仍保留在完整未完成分母。

r40 所有 numeric capture completion 依保守 date-only policy 得 `available_date=2026-09-09`，沒有把 EZSearch `CDATE` 當 numeric availability。3169 的 initial no-match 與 July extension 均留在 handoff 的 `unresolved_attempts`／`repair_contracts` 與 capture evidence；後續批次只可沿來源 circuit、immutable child、成功 raw reuse 與每家公司 bounded attempt 繼續。所有輸出仍為 bounded research evidence，`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 DB 維持只讀，沒有執行正式 apply。

本片定向 batch／adapter／summary／plan／candidate parser／3064 alias 測試共 97 passed、1 skipped；skip 是既有平台 alias 限制，沒有當作成功。r40 使用的 capture、batch、materialize、summary、plan scripts `py_compile` 成功。後續沿 r40 plan 每批最多 8 家，保留 1780 deferred 與所有未完成母數，繼續可恢復市場覆蓋。

### r41：3211 EZSearch 延伸、八家公司隔離 consumer 與續跑 checkpoint

r41 依 r40 continuation plan 有界選取 3206、3207、3211、3213、3217、3218、3219、3221 八家，先由 MOPS EZSearch publication lane 驗證 F26／F27／F28，再由 t164/XBRL numeric lane 嚴格核對公司、2026-Q2 期別、官方 row code、單位與 `report_basis`。初始 `2026-08-01..2026-09-07` capture `quarterly/ezsearch-r41-next8-r1/capture-manifest.json` SHA-256=`179d6fb7fc88bdf4227a10af2a0dc0480fc165b8ae82f4bbe820cd3da4f4a8c9`；7 家三項公告均唯一匹配，3211 的三項均為 `no_matching_company_period_row`，沒有把 HTTP 200 或窗口無匹配推論成公司不存在。

3211 只做一次有界延伸 `2026-07-01..2026-09-07`，capture `quarterly/ezsearch-r41-3211-broader-r1/capture-manifest.json` SHA-256=`3dfa3a502161612862a4c1433b1f014bc52a75514aa3c37e98cc3f191125e4b5`，三項均匹配順達（3211）、2026-Q2，官方 `CDATE=115/07/29`；延伸 evidence SHA-256=`d19bfd3623f71d83183019d1d96ddf2a91575430b3669f0e4deb72d94808a792`。三份共用延伸 raw SHA-256 為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`。延伸只恢復 availability 觀測；numeric candidate 的 `numeric_available_at` 仍取完整 capture completion，沒有把 7/29 回填成歷史 PIT。

r41 初始 numeric batch `quarterly/v4-quarterly-batch-2026q2-r41-ezsearch-next8-manifest.json` SHA-256=`2f58e4645b6f0cfc880635e836f3a03c01244b9c36883784f0da5b2b0184ddd7` 完成 7 家、3211 失敗；3211 延伸 batch `quarterly/v4-quarterly-batch-2026q2-r41-3211-broader-r1-manifest.json` SHA-256=`7790fffd69f8d012a7c45a76a9b626bfb068f6ce502930077d5edf59039bc013` 完成 1 家。初始 failure receipt 保留 EZSearch no-match 原因，延伸只重用已保存官方 numeric raw，沒有覆寫初始失敗目錄或已成功 child。

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3206 | consolidated | 144 | `958a3a91ceaadb382eb9d574a8d586f2e90ec00a95772aa2b013a3f81d72a982` | 0.56 |
| 3207 | consolidated | 152 | `9428a272ebc86cdbcb1b5ea58340f43bd0426f03d1378bd84adba023302ad29c` | -0.64 / -0.64 |
| 3211 | consolidated | 138 | `fb433586b774a4542896879e87205852d6d1a14717ed5dfc5af8716dc6c7bc7e` | 1.35 |
| 3213 | consolidated | 128 | `434ee8404c8047cf2b7f9499e38ee87f088ffa92ebbfb7d0ce0cdaba89793dd9` | 3.02 |
| 3217 | consolidated | 126 | `56a0f7969a898a62c1f1060baa3b7c2a254722872d4c5c499663b3d5fe678f1c` | 2.38 |
| 3218 | consolidated | 132 | `99a1e330ecaff448e33e7bd9bf242d3cf8f876e4dfb4f795adc6abc6166cf0bb` | 2.67 / 2.67 |
| 3219 | consolidated | 125 | `142fa0e4f671d5aa1543af5fc82d6bbbcefdf497b9deccdf5b9b56434b092c0f` | 2.18 / 2.18 |
| 3221 | consolidated | 145 | `9ec8f211e7d009660fce04839b04aa26df524d65bf307bc60c0720fc6391cbc1` | 0.46 |

八個 immutable child 合計 1,090 筆，所有 candidate 與 sidecar 均保留 `consolidated` scope；balance sheet、income statement、cash flow 的 period basis 分別保存 `period_end_snapshot`、`quarter_single`、`year_to_date`。隔離 consumer `quarterly/consumer-r41-next8-ezsearch-r1.db` SHA-256=`f148e295885518714870eab3ce2c26a654bec60b77bba73505f373212c5b159e`，research-only marker SHA-256=`15db1bea9ebe3adf9598c13f066fe6c6d66d2cafc544d5bfd91bb2d198358c2b`，`PRAGMA quick_check=ok`，主表／sidecar 各 1,090。首次 receipt `quarterly/consumer-r41-next8-ezsearch-r1-first.json` SHA-256=`541d2c934608de599d3a1664b89ed274e25c3e1ef165cb6dd71cc48c7a1fe4a6` 為 1,090 inserted／0 existing；重跑 receipt `quarterly/consumer-r41-next8-ezsearch-r1-retry.json` SHA-256=`3ef72350e419d1ac6cc8e634584255582c3c7d859344cd9b14946b185c2153ad` 為 0 inserted／1,090 existing。provider 在 2026-09-08 讀回 0、2026-09-09 讀回 1,090；EPS 以 TWD/share Decimal 讀回，沒有把 cents/share 當元／股。

r41 機器摘要 `quarterly/r41-next8-consumer-summary-r1.json` SHA-256=`0ea77f78bc302a8cb9fb65ad88152e256dd9f4de42132e6c43f4f58499d001e9` 綁定兩份 batch manifest、八個 child、candidate／run manifest hash、兩份 EZSearch capture、隔離 DB、首次／重跑 receipt、cutoff 與 universe plan。交接封裝 `quarterly/r41-quarterly-recovery-handoff-r1.json` SHA-256=`67e9e07a07c3a2d8b0a7d93ed3ca9393dc5ce4c5d4cf5c358cfa38926878a944`，遞迴核對 35 個 workspace path/hash reference 均一致；`quarterly/mops-statement-universe-2026q2-continuation-r41-after-r40-next8.json` SHA-256=`a3dbfd650aa5d43f9f05ca4264f8742370d8e8c233523fc94d7a005f9d6b71c1` 維持官方 companies.csv 完整分母 eligible=1,974、verified completed=119、deferred unresolved=1（1780:tpex）、total unfinished=1,855、remaining selectable=1,854；下一自動 queue 為 3224、3226、3227、3228、3230、3232、3234、3236。1780 仍保留在完整未完成分母。

r41 的 3211 initial no-match 與 July extension 沿 handoff `unresolved_attempts`／`repair_contracts` 保留完整沿革；所有 numeric capture completion 依保守 date-only policy 得 `available_date=2026-09-09`，沒有把 EZSearch `CDATE` 當 numeric availability。所有輸出仍為 bounded research evidence，`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 DB 維持只讀，沒有執行正式 apply。

本片定向 batch／adapter／summary／plan／candidate parser／3064 alias 測試共 97 passed、1 skipped；skip 是既有平台 alias 限制，沒有當作成功。r41 使用的 capture、batch、materialize、summary、plan scripts `py_compile` 成功。後續沿 r41 plan 每批最多 8 家，保留 1780 deferred 與所有未完成母數，繼續可恢復市場覆蓋。

### r42：3226 編碼來源修復、八家公司隔離 consumer 與續跑 checkpoint

r42 依 r41 final continuation plan 有界選取 3224、3226、3227、3228、3230、3232、3234、3236 八家。EZSearch publication capture `quarterly/ezsearch-r42-next8-r1/capture-manifest.json` 的 SHA-256 為 `85169154cf245a35b9c76873a4ec51ce83712b3bfb778f0231245ab7f1a864d9`；F26／F27／F28 原始回應 SHA-256 分別為 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、`a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、`3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`。八家公司均有唯一 2026-Q2 公司／市場／期別匹配；這些公告事件只作 availability lane，不作 numeric PIT 日期。

r42 初始 numeric batch `quarterly/v4-quarterly-batch-2026q2-r42-ezsearch-next8-manifest.json` SHA-256=`1d6f6bfb0dede750803a553f5d5d82ca4b74b68b76e6e523b57d3fce67ccdddc`，完成 6 家、3226／3228 失敗。兩者的 consolidated 路由均收到官方「個別」資產負債表而被 strict title guard 拒絕；沒有用 HTTP 200 當內容成功。`quarterly/v4-quarterly-batch-2026q2-r42-individual-3226-3228-r1-manifest.json` SHA-256=`b245faf1014719639ab96f156aece60f861ac7fc0f0866e91c0ccec220268aea` 以明示 `individual` 重試，3228 完成、3226 在 XBRL strict Big5/HKSCS 解碼失敗，該批 partial raw 與 failure receipt 保留。3226 的官方 XBRL GET diagnostic raw 位於 `quarterly/diagnostic-r42-3226-xbrl-r1/mops_t164sb01_xbrl_3226_115Q2.html`，448,565 bytes、SHA-256=`d1fa3ac461750e6f8dc7e26395196a20d19499e1c140bb5018e7f89e8cabfcbd`；HTTP 200 與 request／response timestamp 由 `evidence.json`（SHA-256=`8616183a88b582826c26675d2c15296ba08411a260770b8a5cccb204c17b277b`）保存。

3226 原文僅有六個 `0x84`，offset 為 `365887、366040、366102、366424、367094、367166`，每一處上下文均是 `\\n\\x84P`，離線核對皆位於 IFRS18／IAS7 敘述項目符號，沒有落在數值儲存格、公司／期別身分或科目標籤。新增的 `strip_declared_big5_c1_controls` 只在完整 raw SHA、六個 offset 與 context 同時吻合時啟用；同數量但改變 context 的負例會拒絕，未知 C1 仍拒絕。已保存 raw 先建立 `quarterly/replay-r42-3226-individual-r1/`，再以 `quarterly/v4-quarterly-batch-2026q2-r42-3226-encoding-r1-manifest.json`（SHA-256=`7926189b248531128fe44ac5c25371beaa2e6842af3c89748f51a7144881581a`）建立新的 immutable 3226 individual child；沒有覆寫先前失敗 raw 或猜測日期。replacement candidate SHA-256=`60ac41f4a724c453c3088ee70c13c80fa1acdf6c38aaa8148e3ca2514868245a`，run manifest SHA-256=`f9d43c2525034efad68785763a55e0338ef960520e698f087be3cc736cb370a1`，共 135 rows。

八個成功 child 的 scope、筆數與 EPS 如下；3226／3228 保留 individual，其他六家為 consolidated：

| 公司 | report_basis | rows | EPS（TWD/share） |
| --- | --- | ---: | ---: |
| 3224 | consolidated | 138 | -0.11 |
| 3226 | individual | 135 | -0.38 |
| 3227 | consolidated | 142 | 3.46 |
| 3228 | individual | 112 | -0.45 |
| 3230 | consolidated | 129 | -0.58 |
| 3232 | consolidated | 135 | 0.19 |
| 3234 | consolidated | 130 | -0.16 |
| 3236 | consolidated | 126 | 0.11 |

共 1,047 rows；三種 period semantics 均保留為 balance sheet=`period_end_snapshot`、income statement=`quarter_single`、cash flow=`year_to_date`，官方 row code source 為 `mops.t164sb01.xbrl.row_code`。所有 numeric candidate 的 capture completion 以本次 replay／parse 完成時間保存，保守 date-only `available_date=2026-09-09`；沒有把 EZSearch CDATE 回填成 numeric availability，也沒有宣稱歷史首次公告 PIT。

八個 candidate 送入隔離 consumer `quarterly/consumer-r42-next8-ezsearch-r1.db`；DB SHA-256=`5fcbf91976d312ef4e04f3db9e8d073c2a5018762669da19d47dacceb91839b4`，research-only marker SHA-256=`a7da3790331876258ffa38ec9adfda637760405709784225f1cee95364ae5c87`，`PRAGMA quick_check=ok`，主表／sidecar 各 1,047。首次 evidence SHA-256=`d5daa4363f9a15ddd990a3f506f062b727ef27cc6749d5cbff1ca3d48df78d5e` 為 1,047 inserted／0 existing；重跑 evidence SHA-256=`c9f3538880a7965c126773d31836662d53ad30cccfbeb633ae590fd10708947a` 為 0 inserted／1,047 existing。provider 2026-09-07 與 2026-09-08 讀回 0，2026-09-09 讀回 1,047；EPS 由既有 consumer 以 `TWD_per_share` 與 scale 100 讀回，個別／合併沒有混淆。

r42 機器摘要 `quarterly/r42-next8-consumer-summary-r1.json` SHA-256=`bb6430402d8fede7e28aff211396bcbc19e4919b550e6ba2a5ff0f68fc9269e4` 綁定三份 r42 batch manifest、八個成功 child、candidate／run manifest hash、EZSearch capture、隔離 DB、首次／重跑 receipt、cutoff 與 universe plan。`quarterly/r42-quarterly-recovery-handoff-r1.json` SHA-256=`39a60bb1f47b78ba6520db8c1ad161a0164cee96468731a0d6f0a364b13a99eb`；handoff 內 42 個 path/hash reference 已由本地 recursive check 核對一致。摘要仍保留初始 3226／3228 failure attempts，並在 repair contract 綁定後續 immutable child；失敗歷史沒有被刪掉或誤算成新的公司。

最新 continuation plan `quarterly/mops-statement-universe-2026q2-continuation-r42-final-after-r41-next8.json` SHA-256=`b85d5aa6fc98ed610268118094cee265f2a3b6da6458de386b602bc34326b0d0` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`127`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,847`、remaining selectable=`1,846`，下一批為 `3252、3259、3260、3264、3265、3268、3272、3276`。另有一份較早產生但未包含 r42 child 的 `r42-after-r41-next8.json`（verified=`119`）保留為非交付中間產物；後續只使用上述 final plan，避免把中間 checkpoint 當成最新狀態。

本片相關編碼／candidate／batch／adapter／summary／plan 測試為 `59 passed`；r42 完整 bounded 輸出均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`。D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀；1780 仍在完整未完成分母，下一批沿 EZSearch bounded capture、來源 circuit、成功 raw reuse、immutable child 與首次／重跑 receipt 繼續。

### r43：六家公司成功入庫隔離、3252 官方科目對照修復與失敗保全

r43 依 r42 final plan 有界處理 3252、3259、3260、3264、3265、3268、3272、3276 八家。3252 的普通 Python transport 首次留下三項 `WinError 10013`；依既有 approval 路徑只重跑一次後，八家 EZSearch capture 均保留獨立 `capture-manifest.json` 與 evidence。3252、3259、3260、3265、3268、3272、3276 各有 F26／F27／F28 唯一公司／市場／2026-Q2 匹配；3264 三項均為 `no_matching_company_period_row`，沒有把無匹配解釋為公司不存在。EZSearch 僅供公告 availability lane，未被拿來回填 numeric PIT 日期。

r43 initial batch `quarterly/v4-quarterly-batch-2026q2-r43-ezsearch-next8-manifest.json` SHA-256=`f0f61202f356e1c7f0b7ddb661f26f5416ebebffe9f747376d20f167334d83ef`，8 requests 中 5 家成功、3252 的 XBRL row-code 對照、3259 的 statement title、3264 的 EZSearch evidence 分別形成明確 failure receipt。3252 的成功 replay batch `quarterly/v4-quarterly-batch-2026q2-r43-3252-rowcode-r2-manifest.json` SHA-256=`2d7fedfaf268403b9dec27ce8165120c84b660e85ded42837a6c7abf2fa6f8af`，使用原始 partial raw，建立新的 immutable child；先前 failure child 沒有覆寫。

3252 原始 XBRL `mops_t164sb01_xbrl_3252_115Q2.html` 為 489,323 bytes、SHA-256=`740a87e0e0ca413ce758e975ca9e9e29c949a5bc8457236f28a23ad9bf3026cd`。同一期 UTF-8 t164 顯示頁與 Big5/HKSCS XBRL row 逐筆核對後，新增的明示對照只有：`餐旅服務收入淨額`→`餐旅服務收入` code `4410`（102,346、縮排 2）、`旅遊服務收入`→`旅遊服務收入合計` code `4400`（102,346）、`旅遊服務成本`→`旅遊服務成本(觀光飯店業適用)合計` code `5400`（63,368）；值、income statement 類型與期別均由 resolver 再核對。只提供 4400 給 4410 對照或使用錯期回報值均拒絕。新增 `tests/test_mops_statement_3064_alias.py` 後，該測試與 `tests/test_build_mops_statement_pit_candidate.py` 合計 `60 passed`；沒有加入通用「合計」推算或放寬 row-code 防護。

六個成功 immutable child 均為 consolidated，candidate 合計 858 rows：

| 公司 | rows | EPS（TWD/share） | report_basis |
| --- | ---: | ---: | --- |
| 3252 | 126 | -0.23 | consolidated |
| 3260 | 200 | 32.39／31.75 | consolidated |
| 3265 | 141 | 2.09／2.09 | consolidated |
| 3268 | 121 | -0.03 | consolidated |
| 3272 | 152 | -1.25／-1.25 | consolidated |
| 3276 | 118 | 0.06 | consolidated |

三種 period semantics 維持 balance sheet=`period_end_snapshot`、income statement=`quarter_single`、cash flow=`year_to_date`，item code 來源均為 `mops.t164sb01.xbrl.row_code`。所有 numeric candidate 以實際 replay／parse 完成 timestamp 建立 `numeric_available_at`，date-only `available_date=2026-09-09`；沒有使用公告 CDATE 冒充數值可得日，也沒有宣稱歷史首次公告 PIT。

六個 candidate 送入新的隔離 consumer `quarterly/consumer-r43-next8-ezsearch-r2.db`。DB SHA-256=`761410aada943fd039b12f74c3d7a6f0d11d88f1d49d330e7abccdb89bfce4be`，research-only marker SHA-256=`b917b9f82f23fdf6c5edb49066505c8a361ce936e08661e8ba7d989e794b640b`，`PRAGMA quick_check=ok`，主表／sidecar 各 858。首次 evidence `consumer-r43-next8-ezsearch-r2-first.json` SHA-256=`37674d8a366bd81725c9495c35b66bcfe5d4b16693f9265ec9f2471658bd415d` 為 858 inserted／0 existing；重跑 evidence `consumer-r43-next8-ezsearch-r2-retry.json` SHA-256=`2b64ba17e652c5ccd355919ecac35fbdef25eb58af82e946285426ac288a4c6a` 為 0 inserted／858 existing。provider cutoff 2026-09-07 與 2026-09-08 讀回 0，2026-09-09 讀回 858；EPS 以 `TWD_per_share`、scale 100 與 sidecar period metadata 讀回。

r43 機器摘要 `quarterly/r43-next8-consumer-summary-r1.json` SHA-256=`f702f51c7e0c2731be69cf5d29f1e27c4cdb5fcde313147aafcc7e768cd0d24e` 綁定兩份 r43 batch manifest、6 個成功 child、3 個 unresolved attempt、candidate／run manifest hash、八家 EZSearch evidence、隔離 DB、首次／重跑 receipt、cutoff 與 universe plan。交接封裝使用合法 JSON `quarterly/r43-quarterly-recovery-handoff-r3.json`，SHA-256=`53fe4faf07a228b4c8c6a48af7c985d217aed3381319ff72008aaf84d8fda082`；本地遞迴檢查 22 個 path/hash reference 全部存在且 SHA 相符。先前 `r43` handoff r1 保留作為中間版本，r2 曾因 literal `\\n` 造成 JSON Extra data，交付只使用 r3，不讓 reader 忽略錯誤。

最新 continuation plan `quarterly/mops-statement-universe-2026q2-continuation-r43-after-r42-next8.json` SHA-256=`bac2366ad7d6c02db251788a699c3815fdb20c0c1fab55a4e0074ec7210a3e39` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`133`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,841`、remaining selectable=`1,840`，下一批為 `3259、3264、3284、3285、3287、3288、3289、3290`。3259 的 statement title mismatch、3264 的公告 no-match 與初始 3252 row-code failure 均保留在 r43 summary／handoff，沒有算成完成或從未完成分母刪除。

r43 所有輸出仍為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。後續沿 plan 每批最多 8 家，成功 raw 重用、來源 circuit 與一次性 retry budget 持續，3259／3264 只有在有明示 individual/title 或新的官方期別證據時才建立新 immutable child。

### r45：3294、3297、3303、3310、3313 五家公司隔離恢復與失敗保全

r45 沿 r44 continuation plan 建立新的 bounded batch，處理 `3259、3264、3306、3294、3297、3303、3310、3313` 八家，每家公司最多 1 次，來源 transport failure 上限 1。3259／3264 的既有 EZSearch evidence 維持重用；3259 的 numeric response 仍因官方資產負債表標題不符而 fail-closed，3264 的 EZSearch evidence 仍為 `no_matching_company_period_row`。3306 也收到相同的 consolidated title mismatch，且 partial staging 沒有可重播 raw；三家均保留 failed child 與具體 failure receipt，沒有把 HTTP 200 或空 partial 當成功。3294、3297、3303、3310、3313 的 publication／numeric lane 均通過公司、2026-Q2、官方 row-code、單位與報表型態驗證，五個 child 均為 `consolidated`。

r45 batch manifest `quarterly/v4-quarterly-batch-2026q2-r45-next8-manifest.json` SHA-256=`ac965010e902452eed28a66d646dd2187b6a6291633a42d31592465aede5a216`，8 requests 中 5 家成功、3 家 failed、無 pending。五家 candidate row count 與 candidate SHA-256 如下：

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3294 | consolidated | 129 | `dd951bcaa50dda16fb04fa5dbe0644dd995258d5291fb47d5b1054e3f9c69f9c` | -0.09 |
| 3297 | consolidated | 125 | `3c3f8299960b7fc88115b01e874380f34a4f177ab0c5713657763feafa4b8c68` | 0.74 |
| 3303 | consolidated | 140 | `5761a53a7f5241afc0349c7b2d7b9c18984a99f05fd5547025249ee9c5d8c211` | 1.48 |
| 3310 | consolidated | 131 | `ebd99dd4cd4bd7ad8c525e4cffd136fbef19f702b04246fb9e70de3d239e6a01` | 1.25 |
| 3313 | consolidated | 120 | `292aa1935db9fe175e8feaf10a62b438c252319b5a1154d742256e9d8540db3a` | -0.11 |

五個 child 合計 645 rows；balance sheet、income statement、cash flow 的 period basis 分別保留 `period_end_snapshot`、`quarter_single`、`year_to_date`，item-code lineage 為 `mops.t164sb01.xbrl.row_code`。EPS 由既有 consumer 讀回且保留 `TWD_per_share`、scale 100；沒有把 cents/share 當成元／股，也沒有混合 individual／consolidated。五家 r45 EZSearch capture 的 F26／F27／F28 均為唯一 2026-Q2 公司／市場／期別匹配，3259／3264 則沿用 r43 的 matched／no-match evidence。公告日期只作 publication lane，numeric candidate 仍以完整 capture completion 的保守 date-only policy 計 `available_date=2026-09-09`，沒有回填公告日或宣稱歷史 PIT。

五個 candidate 送入隔離 consumer `quarterly/consumer-r45-next8-ezsearch-r1.db`。DB SHA-256=`389eb8bff29dc0d63fc589c67afd7971112d552d7939eac10cf3fec4d5f7aa1d`，research-only marker SHA-256=`e538c5567c38401ee1ecb389ec3191bb1a26d0c0b09d0a673c3df197ad4711ea`，`PRAGMA quick_check=ok`，主表／sidecar 各 645。首次 receipt `quarterly/r45-next8-materialization-first.json` SHA-256=`526ae1a9eb07cd4e959162a9e5eb32700011ec58fe27b7c39cf20a6d6afd2653` 為 645 inserted／0 existing；重跑 receipt `quarterly/r45-next8-materialization-retry.json` SHA-256=`eb0e3f1cac10b064be890abbd6c6d82a917f7caefc8f1afa4b096194dff992ff` 為 0 inserted／645 existing。provider 在 2026-09-07 與 2026-09-08 均讀回 0，2026-09-09 讀回 645；五家公司各自 row count 為 129／125／140／131／120，沒有把 hidden cutoff 前資料誤提供給 consumer。

機器摘要 `quarterly/r45-next8-consumer-summary-r1.json` SHA-256=`41455530fe979b67d10eeaa4951f3686eda24a2d41d61a6ddd9d065013becf58` 綁定 r45 batch manifest、8 家 EZSearch evidence、5 個成功 child、candidate／run manifest／raw hash、隔離 DB、首次／重跑 receipt 與 cutoff；交接封裝 `quarterly/r45-quarterly-recovery-handoff-r1.json` SHA-256=`af097b5ac588664d831d5779df53a3aafa1f37bb724fe13b084a6cf3048f978e` 為合法 JSON，內含 60 個直接 artifact path/hash reference，遞迴讀取 child／capture manifest 後全部存在且 SHA 相符。handoff 明確保留 3259、3264、3306 的失敗原因與 partial failure hash，沒有將失敗 child 計入完成。

r45 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r45-after-r44-next8.json` SHA-256=`ddb34312fd03108cfba3326c50b7574142694e78ca3f5d3d2b348c79bc671867` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`144`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,830`、remaining selectable=`1,829`，下一批自動 queue 為 `3259、3264、3306、3317、3322、3323、3324、3325`。3259／3264／3306 仍是未完成且可重跑鍵，1780 仍保留完整分母；本片只完成五家公司，沒有宣稱全市場恢復。

r45 的 batch／materialization／summary 均實際執行成功；`tests/test_build_mops_statement_batch.py`、`tests/test_mops_statement_candidate_adapter.py`、`tests/test_summarize_mops_statement_consumer_batch.py`、`tests/test_plan_mops_statement_universe.py` 共 `40 passed、1 skipped`，skip 為既有平台 alias 限制，沒有當作成功。r45 handoff JSON 由實際換行寫出並可直接 `json.loads`；所有 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`，D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。後續沿 r45 plan 每批最多 8 家、成功 raw reuse、來源 circuit、immutable child 與首次／重跑 receipt 繼續。

### r46：3317、3322、3323、3324、3325 五家公司隔離恢復與續跑 checkpoint

r46 沿 r45 continuation plan 建立新的 bounded batch，處理 `3259、3264、3306、3317、3322、3323、3324、3325` 八家，每家公司最多 1 次，來源 transport failure 上限 1。3259／3264／3306 的既有 publication evidence 重用後，分別因 consolidated 資產負債表標題不符、EZSearch 無唯一公司／期別匹配、consolidated 資產負債表標題不符而 fail-closed；三家均保留 failed child 與具體 failure receipt，沒有以 HTTP 200 或空 partial 當成功。3317、3322、3323、3324、3325 的 publication／numeric lane 均通過公司、2026-Q2、官方 row-code、單位與報表型態驗證，五個 child 均為 `consolidated`。

r46 batch manifest `quarterly/v4-quarterly-batch-2026q2-r46-next8-manifest.json` SHA-256=`550f28c4a3138b28729f29b2dc3b17032ee048c614a2ca7d2e544fef39bc8ec8`，8 requests 中 5 家成功、3 家 failed、無 pending。五家 candidate row count 與 candidate SHA-256 如下：

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3317 | consolidated | 121 | `6cbfba4a3dc8dd238f61e50436db73d3616ced99059d063bd3746ac3f290305a` | 0.72 |
| 3322 | consolidated | 127 | `07b3d74d18b6970644d0ec25f49afbeccc0c04bf030282496d365c8d92578a78` | -0.50 |
| 3323 | consolidated | 128 | `fe6cc44f8c385f2876245d3f2a9b236b62eff2fb2d1982893723a211c7dc2489` | -0.42 |
| 3324 | consolidated | 151 | `f74e72b76a0b3f082909a04879b481cca99729cbcc7e4c48782f37f4b97b2de4` | 10.41 / 9.98 |
| 3325 | consolidated | 138 | `43741719e2d45668e7a3287b766dec4002cb44a0be505ed2ec1c60338d9e439c` | -0.75 |

五個 child 合計 665 rows；balance sheet、income statement、cash flow 的 period basis 分別保留 `period_end_snapshot`、`quarter_single`、`year_to_date`，item-code lineage 為 `mops.t164sb01.xbrl.row_code`。EPS 由既有 consumer 讀回且保留 `TWD_per_share`、scale 100；沒有把 cents/share 當成元／股，也沒有混合 individual／consolidated。五家 r46 EZSearch capture 的 F26／F27／F28 均為唯一 2026-Q2 公司／市場／期別匹配，3259／3264／3306 則沿用先前各自 matched／no-match evidence。公告日期只作 publication lane，numeric candidate 仍以完整 capture completion 的保守 date-only policy 計 `available_date=2026-09-09`，沒有回填公告日或宣稱歷史 PIT。

五個 candidate 送入隔離 consumer `quarterly/consumer-r46-next8-ezsearch-r1.db`。DB SHA-256=`e4012ee1f9e3dbd7e99e86c5e26a1dd79a309f9664d74a6cdbe6c7c5ff8d3535`，research-only marker SHA-256=`e679c1159242721edae9e2d2bc433276e04dd140e3d64ac843810c5e32a1b4f4`，`PRAGMA quick_check=ok`，主表／sidecar 各 665。首次 receipt `quarterly/r46-next8-materialization-first.json` SHA-256=`2116dc9be4657ec79ddbe3d3858bbb595b67c98b3deb426a5855c23df2eb50c8` 為 665 inserted／0 existing；重跑 receipt `quarterly/r46-next8-materialization-retry.json` SHA-256=`45d64cb32f9c8bfc78eb44d98cf38eb474bff4b87dc12545f3fa58e1003e57cd` 為 0 inserted／665 existing。provider 在 2026-09-07 與 2026-09-08 均讀回 0，2026-09-09 讀回 665；五家公司各自 row count 為 121／127／128／151／138，沒有把 hidden cutoff 前資料誤提供給 consumer。

機器摘要 `quarterly/r46-next8-consumer-summary-r1.json` SHA-256=`3bdf36e2ee3fb8c5a0b639cc452d924c7984205b018614d78df2fe1bed939657` 綁定 r46 batch manifest、8 家 EZSearch evidence、5 個成功 child、candidate／run manifest／raw hash、隔離 DB、首次／重跑 receipt 與 cutoff；交接封裝 `quarterly/r46-quarterly-recovery-handoff-r1.json` SHA-256=`7e697753581abd429cbf93baef91662abd255231bae5b6054187bdf0e6065e3d` 為合法 JSON，內含 60 個直接 artifact path/hash reference，遞迴讀取 child／capture manifest 後全部存在且 SHA 相符。handoff 明確保留 3259、3264、3306 的失敗原因與 partial failure hash，沒有將失敗 child 計入完成。

r46 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r46-after-r45-next8.json` SHA-256=`4624f9e3bc09cf59b73f582eaccbe039d927cf2eaaae06f572fe5d052c64ddca` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`149`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,825`、remaining selectable=`1,824`，下一批自動 queue 為 `3259、3264、3306、3332、3339、3349、3354、3357`。3259／3264／3306 仍是未完成且可重跑鍵，1780 仍保留完整分母；本片只完成五家公司，沒有宣稱全市場恢復。

r46 的 batch／materialization／summary 均實際執行成功；`tests/test_build_mops_statement_batch.py`、`tests/test_mops_statement_candidate_adapter.py`、`tests/test_summarize_mops_statement_consumer_batch.py`、`tests/test_plan_mops_statement_universe.py` 共 `40 passed、1 skipped`，skip 為既有平台 alias 限制，沒有當作成功。r46 handoff JSON 由實際換行寫出並可直接 `json.loads`；所有 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`，D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。後續沿 r46 plan 每批最多 8 家、成功 raw reuse、來源 circuit、immutable child 與首次／重跑 receipt 繼續。

### r44：3284、3285、3287、3288、3289、3290 六家公司隔離恢復與可續跑 checkpoint

r44 沿 r43 continuation plan 建立新的 bounded batch，處理 `3259、3264、3284、3285、3287、3288、3289、3290` 八家，每家公司最多 1 次，來源 transport failure 上限 1。3259 的既有 EZSearch 公告證據重用後，numeric lane 仍因官方資產負債表標題不符而 fail-closed；3264 的既有 EZSearch evidence 三項均為 `no_matching_company_period_row`，兩者都保留 failed child／evidence，沒有把 HTTP 200 或無匹配當成完成。3284、3285、3287、3288、3289、3290 均以既有 MOPS EZSearch publication response 及本輪 t164/XBRL HTTP raw 完成公司、2026-Q2、官方 row-code、單位與報表型態驗證，六個 child 均為 `consolidated`。

r44 batch manifest `quarterly/v4-quarterly-batch-2026q2-r44-next8-manifest.json` SHA-256=`60eb3db2de8b60e9acca6ce003e98412d13e51163600e2d7d196806a362d7a3f`，8 requests 中 6 家成功、2 家 failed、無 pending。六家 candidate row count 與 candidate SHA-256 如下：

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3284 | consolidated | 152 | `67aa876184740ad55a0002ac7949187b7b48176a3b2602f1de6ba85d4e643c5d` | 0.22 |
| 3285 | consolidated | 133 | `4d4d8bd311a53a96587e9e2ab1f6461b3d5d50288b30ba9e5b431137bbd97cdc` | 0.66 / 0.65 |
| 3287 | consolidated | 118 | `bc57c00f90cccee318cb682353d40aacce9e1df00c6f53e92853e4a980ea8af7` | 4.87 |
| 3288 | consolidated | 106 | `93a4c8dd8f1a9b485378792f68c02697ff167177b409affe20dc59cd8d45fa09` | 0.03 |
| 3289 | consolidated | 149 | `0b391d1cdbe0cd5bf8a84751af97cf095b36d77b8a9bc80dddb0cd0132077df8` | 1.03 |
| 3290 | consolidated | 136 | `e34af0d84290377043fdb0052aa61d768901c757f0acd9cc367e9ce6c9b1b682` | 0.08 |

六個 child 合計 794 rows；balance sheet、income statement、cash flow 的 period basis 分別保留 `period_end_snapshot`、`quarter_single`、`year_to_date`，item-code lineage 為 `mops.t164sb01.xbrl.row_code`。EPS 由既有 consumer 讀回且保留 `TWD_per_share`、scale 100；沒有把 cents/share 當成元／股，也沒有混合 individual／consolidated。官方 availability capture 的 F26／F27／F28 各為唯一 3284、3285、3287、3288、3289、3290 的 2026-Q2 公告匹配；3259／3264 仍分別保留 matched 與 no-match evidence。公告日期只用於 publication lane，numeric candidate 仍以完整 capture completion 的保守 date-only policy 計 `available_date=2026-09-09`，沒有回填公告日或宣稱歷史 PIT。

六個 candidate 送入隔離 consumer `quarterly/consumer-r44-next8-ezsearch-r1.db`。DB SHA-256=`74cb48e7894a764ec4fb59349d73ac75790f1bd5daf56c2d6ef82a3903d30f2f`，research-only marker SHA-256=`2a500edf1cac55e46de508ec42072484035290339871e24b13a5c5efe7e1cc4e`，`PRAGMA quick_check=ok`，主表／sidecar 各 794。首次 receipt `quarterly/r44-next8-materialization-first.json` SHA-256=`5e96a14259d75980ad4bc01e37d5d950269accccfccea59d97212b6e4e3058e4` 為 794 inserted／0 existing；重跑 receipt `quarterly/r44-next8-materialization-retry.json` SHA-256=`33361f9ca9a336160e94697bd5c912a5ba7b414aac349902d9ed618cd41d9c40` 為 0 inserted／794 existing。provider 在 2026-09-07 與 2026-09-08 均讀回 0，2026-09-09 讀回 794；六家公司各自 row count 為 152／133／118／106／149／136，沒有把 hidden cutoff 前資料誤提供給 consumer。

機器摘要 `quarterly/r44-next8-consumer-summary-r1.json` SHA-256=`b0ba115fc05ab86fd5113f5893336f77986f53bd8b83f943d4a4647b925059e0` 綁定 r44 batch manifest、八家 EZSearch evidence、6 個成功 child、candidate／run manifest／raw hash、隔離 DB、首次／重跑 receipt 與 cutoff；交接封裝 `quarterly/r44-quarterly-recovery-handoff-r1.json` SHA-256=`a6479835bf9ab9547ac526ccc6091e929bf8a4e8ccce4f4a097b446157266400` 為合法 JSON，內含 59 個 artifact path/hash reference，本地逐檔回讀全部存在且 SHA 相符。handoff 明確保留 3259 的 `MOPS statement response does not contain the expected official title; statement_type=balance_sheet` 與 3264 的 `EZSearch availability evidence has no unique company/period row; item=F26; status=no_matching_company_period_row`，沒有將失敗 child 計入完成。

r44 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r44-after-r43-next8.json` SHA-256=`a3071a0d0f24150f67790716d73fb9686996344a3f78e104b060b63696537caa` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`139`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,835`、remaining selectable=`1,834`，下一批自動 queue 為 `3259、3264、3294、3297、3303、3306、3310、3313`。3259／3264 仍是未完成且可重跑鍵，1780 仍保留完整分母；本片只完成六家公司，沒有宣稱全市場恢復。

本片機器執行與回歸驗證：r44 batch／materialization／summary 均成功；`tests/test_build_mops_statement_batch.py`、`tests/test_mops_statement_candidate_adapter.py`、`tests/test_summarize_mops_statement_consumer_batch.py`、`tests/test_plan_mops_statement_universe.py` 共 `40 passed、1 skipped`，skip 為既有平台 alias 限制，沒有當作成功。r44 handoff JSON 由實際換行寫出並可直接 `json.loads`；所有 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`，D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。後續沿 r44 plan 每批最多 8 家、成功 raw reuse、來源 circuit、immutable child 與首次／重跑 receipt 繼續。

### r47：六家公司（含兩家 individual repair）隔離恢復、失敗分類與全市場續跑 checkpoint

r47 主批次沿 r46 continuation plan 有界處理 `3259、3264、3306、3332、3339、3349、3354、3357` 八家，每家公司最多 1 次，來源 transport failure 上限 1；先前成功的 EZSearch raw／publication evidence 重用，不重抓已成功來源。主 batch manifest `quarterly/v4-quarterly-batch-2026q2-r47-next8-manifest.json` SHA-256=`8abf3572f4cad7e369c1d3ed5315d21b8f538a1784af6d221e93e1a68f2f523e`，8 requests 中 4 家成功、4 家 fail、無 pending。`3259`、`3306` 的 consolidated 路由均因官方資產負債表 title mismatch fail-closed；`3264`、`3354` 的 EZSearch F26/F27/F28 均沒有唯一公司／期別 row。這四次不是以 HTTP 200 當內容成功；raw、evidence 與 partial failure（有產生者）均保留。r47 主批沒有 transport failure，失敗屬內容身分驗證問題。

以已保留官方 raw 建立的新 immutable individual repair batch `quarterly/v4-quarterly-batch-2026q2-r47-individual-3259-3306-manifest.json` SHA-256=`d1edfe8cbaaab5e7aea80d6bb8eff3f5c016fb9874832dd153b971d988a0fba3`，明示 `report_basis=individual` 後兩家公司均通過公司／期別／row code／單位驗證；沒有覆寫主批失敗 child。六個成功 candidate 的 rows、EPS 與報表 basis 如下：

individual repair 的官方依據可由各 child `statement-sources.json` 逐項回讀：兩家公司均以 `https://mopsov.twse.com.tw/mops/web/ajax_t164sb03`、`ajax_t164sb04`、`ajax_t164sb05`，request `TYPEK=otc`、指定 `co_id`、`year=115`、`season=2` 取得 2026-Q2 個別資產負債表、損益表與 1/1–6/30 現金流量表；報表標頭分別為 `115年06月30日`、`115年第2季`、`115年01月01日至115年06月30日`。3259 三表接受數值列為 `34+19+42=95`，原始 response SHA-256 分別為 `94e00b9b2d8e8670a64100148a1789729eaeee8d63ba7f4d84acc47ebe7660b2`、`3b20deac3470513ef58b22e51bee1a9ddcc16d73b0d9c35852906f9c370d7bb2`、`a715277a61a9735e36116e26874feedc473b84749732d49e1b19c5ff2cd97d07`；3306 接受數值列為 `42+29+40=111`，原始 response SHA-256 分別為 `3cf84ec377e7d2579519c9f7573c8d00c0188caebf8883cf2e76f43985ea1e18`、`9c6618f87547a5cf5da67c83a438bf100012a127a19ae39bc07cb52f528868d2`、`2e269e3f8cf6c02caaaebd2229c006cd7df5fcc630832aaeb758a2bd37071da1`。兩者 item-code lineage 都由官方 `https://mopsov.twse.com.tw/server-java/t164sb01` XBRL response 提供，3259 raw SHA-256=`42a1637a9409d950c070d859d10c3a191255093e0862991ded3ff6f363484733`（373,657 bytes）、3306 raw SHA-256=`bd81c5fc00ef9f5442c0eb32db83a3367b70b791fd1b80a0f4cc6c153cddbf0b`（409,717 bytes）；不是依名稱猜碼或以 consolidated response 冒充個別報表。

本批 3264、3354 的共同缺口也有獨立證據：其 `ezsearch-r47-next8-r1/<stock>-approved/ezsearch-evidence-<stock>.json` 對 F26、F27、F28 都記錄 HTTP 200 原始回應，但三項均為 `no_matching_company_period_row`，所以 availability gate 沒有唯一公司／市場／2026-Q2 row，numeric lane 沒有被誤放行。兩者的 F26/F27/F28 raw bytes 使用同一組實際 SHA-256（分別 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、`a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、`3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`），不是 transport failure；兩鍵仍在 selectable 分母，下一輪只應查明官方 listing／公司狀態或新的唯一公告證據，不能 caller exclusion 當完成。

| 公司 | report_basis | rows | EPS（TWD/share） |
| --- | --- | ---: | ---: |
| 3259 | individual | 95 | -0.57 |
| 3306 | individual | 111 | 0.09 |
| 3332 | consolidated | 130 | 1.15 |
| 3339 | consolidated | 125 | -1.83 |
| 3349 | consolidated | 122 | -0.30 |
| 3357 | consolidated | 162 | 3.81 |

六個 candidate 合計 745 rows；balance sheet、income statement、cash flow 的 period basis 仍分別保存 `period_end_snapshot`、`quarter_single`、`year_to_date`，item code lineage 為 `mops.t164sb01.xbrl.row_code`。candidate SHA-256 為：3259=`fbb2f4d2640267dbde48f374a4348d61d6b648826ea47a23c70d3193a430cc74`、3306=`1c88d1283e6f8b5817fc78d8e9d6846d7273ae94423c075ea442d201493463cc`、3332=`afc709d4a542ac57781e06477a154cbae86f07ae92180fa91c72ae42d2c8d4d1`、3339=`69c5d3fde3243ce96479c3d185b30a52c5f71232d4cc3e4f27492b73ac8eb60b`、3349=`9a6f88796a238147caf0e244d630c95526e18c8c222cfc2443efd0ee1dfe4581`、3357=`21a10186860cdef6d94eb73d490090dcef34f1594310c00374748ba105c2e317`。數值 candidate 以實際 capture completion 建立 numeric availability，保守 date-only 為 `2026-09-09`；公告 CDATE 沒有被冒充成歷史 numeric PIT。

六個 candidate 送入隔離 consumer `quarterly/consumer-r47-next8-ezsearch-r1.db`。首次 receipt `quarterly/r47-next8-materialization-first.json` SHA-256=`e28da934b727d8717b1ea0733db69a788ebe35819ad1bf499dffdd4078235782` 為 745 inserted／0 existing；重跑 receipt `quarterly/r47-next8-materialization-retry.json` SHA-256=`00cff63f8ca78ab1ed4d0ec450d81c5037ff56659f88b8bdf94ff71d0aeda142` 為 0 inserted／745 existing。DB SHA-256=`d6b75fb66f2eca897bea003838e21c2d3ab03d2fa5fd2a12efae70292364c2e2`，research-only marker SHA-256=`531c376bd10cd241366abc70a624a9cd714acde1328e5427fcfeecebae1918d8`，`PRAGMA quick_check=ok`，主表／sidecar 各 745。provider 2026-09-07 讀回 0、2026-09-08 讀回 0、2026-09-09 讀回 745；沒有讓 cutoff 前資料進入 consumer。

最新機器摘要 `quarterly/r47-next8-consumer-summary-r1.json` SHA-256=`fd6694c3aca44930c575165ea1ddf841932ff34ad88f2c3dd9fe03437f42f1d7` 綁定主批與 individual repair batch、六個成功 child、所有 candidate／manifest hash、8 份 EZSearch capture、隔離 DB、首次／重跑 receipt 與 cutoff。handoff `quarterly/r47-quarterly-recovery-handoff-r2.json` SHA-256=`752e334e044048f689e3f5a9e488851ccd4aa7d7f42ba47e12db3e16e3dfdb06` 為合法 JSON，`artifact_references` 64 份加上 supersedes r1 的 path/hash 1 份，共 65 份 direct path/hash references 已逐檔回讀且 SHA 相符；較早 r1 handoff 保留但由 r2 標為 superseded（修正 scope.requests 的結構化 identity），沒有覆寫任何 raw 或 candidate。

r47 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r47-after-r46-next8.json` SHA-256=`d07ef1f9e6bb1c517217b18a6de46acfe6e37923645bb71947b28c7d1575ec9b` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`155`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,819`、remaining selectable=`1,818`，下一批自動 queue 為 `3264、3354、3360、3362、3363、3372、3373、3374`。本片兩筆 EZSearch unresolved 仍在 selectable 分母，沒有被 caller exclusion 當成不存在；3259／3306 已透過 individual immutable repair 計入 verified。

本片固定失敗分類為：主批 title mismatch 2 筆（3259、3306，已由 individual 修復）、EZSearch 無唯一公司／期別 2 筆（3264、3354，仍 unresolved），transport failure 0。handoff 另保存 1780 deferred、主批 failed attempts、partial failure hash、repair lineage 與來源 circuit policy，讓下一次只重試 unresolved／新選取鍵。所有輸出仍為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。

r47 batch／adapter／summary／universe 定向測試為 `40 passed、1 skipped`（1 個 skip 是既有平台 alias 限制，未計成功）；handoff、summary、plan 與 materialization receipt 均可由 `json.loads` 直接讀取。後續沿 r47 plan 每批最多 8 家，成功 raw reuse、來源級 circuit breaker、immutable resume 與首次／重跑 receipt 繼續恢復，不把本片 6 家或 verified=155 宣稱為全市場完成。

### r48：五家公司（含一家公司 individual repair）隔離恢復、EZSearch transport 診斷與續跑 checkpoint

r48 依 r47 continuation plan 執行一個最多八家的 bounded batch，request 為 `3264、3354、3360、3362、3363、3372、3373、3374`（均為 `otc:2026-Q2`），每家公司最多 1 次，官方來源 transport failure 上限為 1。3264、3354 沿用既有已核對的 EZSearch no-match evidence，沒有重抓；3360、3362、3363、3373、3374 使用本輪同一個官方 EZSearch response。主 batch manifest `quarterly/v4-quarterly-batch-2026q2-r48-next8-manifest.json` SHA-256=`0c9200995c8f8dea15618458d0b2dff7fdcc4b33f05d867c8d3db0c989e49a4d`，8 requests 中 4 家成功、4 家 failed、無 pending。

本輪先以普通 `requests.Session` 對官方 `https://mopsov.twse.com.tw/mops/web/ezsearch_query` 做一次有界 6 公司 capture；`quarterly/ezsearch-r48-next8-r1/capture-manifest.json` SHA-256=`bfbda2af2d0d2f3f51dac2596224537b99c2f35d992f1eff4dcdfbdd2eeef5cd`，三個 item 均為 `ConnectionError`／WinError 10013，沒有 raw，狀態只作本機 transport 診斷，沒有被當成官方 response。依正常 approval 路徑重新執行同一個 bounded window 後，`quarterly/ezsearch-r48-next8-r2/capture-manifest.json` SHA-256=`ae1b0695bcb5077ff822e3e0bd88dc52d918d92e4b41daa69b510b16a09a1a6e`，F26／F27／F28 raw SHA-256 分別為 `9d3c71bb91d4a00999b8592e2a01a91fb8b29d4c787a4aed6492113913f663df`、`a533d8a15ebd808dab64a000ab1c29a2ce28d9b6283be8767db7cf3f503bceeb`、`3ac99937f76d339e83ee22cb1c1ed6631672172b75c590051f35af475a0e0002`。3360、3362、3363、3373、3374 各三項均有唯一公司／上櫃市場／2026-Q2 公告列；3372 三項均仍為 `no_matching_company_period_row`。因此 3372、以及使用先前相同官方 raw 的 3264、3354，均未進入數值 lane；no-match 不代表公司不存在，三鍵維持 selectable。

3374 的 consolidated t164 response 因官方資產負債表 title mismatch fail-closed；沒有把錯誤 response 貼上 caller 的期別，也沒有覆蓋失敗 partial。另建立 `report_basis=individual` 的 immutable repair batch `quarterly/v4-quarterly-batch-2026q2-r48-individual-3374-manifest.json`，SHA-256=`b30c761331a907c59d63fc4645feea08c559e376e071b9dced87c8339bc858ac`，成功 child candidate 104 rows、candidate SHA-256=`509cd358b64989c54805727032f9ee564c4ede4216c0244dccba75156654d232`，run manifest SHA-256=`1f76dd54c6dec7f6c190de3ed4ecf18e3cc2f3d2e00ae296149fd3cb3bc6d770`。3374 child `statement-sources.json` 逐項保留官方 MOPSov t164 endpoint、request `TYPEK=otc`／`co_id=3374`／`year=115`／`season=2`，報表標頭依序為 `115年06月30日`、`115年第2季`、`115年01月01日至115年06月30日`；接受列數為 balance `38`、income `21`、cash flow `45`，合計 `104`。三張 t164 raw SHA-256 分別為 `823ca94607c4e91307220ab88d4a3839974b7abeeb2373e969af3de9fe9fd347`、`25efdf91949826836ce2f169cded7142c1db2a5705c75bf61f916fefe072f30c`、`bebfa4dc974aaa3c8203d008e8c1700f941689c42d191055f8b7dcc98012f886`；官方 row-code XBRL raw SHA-256=`5511ae740ef5daac0a6357417d98986b7fb96a5fa3db19099f2c5cfa1e75abc1`，不是依名稱猜碼或以 consolidated response 冒充個別報表。

四個 consolidated child 的 candidate rows／SHA-256／EPS 如下；所有 item code lineage 均為 `mops.t164sb01.xbrl.row_code`。

| 公司 | report_basis | rows | candidate SHA-256 | EPS（TWD/share） |
| --- | --- | ---: | --- | ---: |
| 3360 | consolidated | 127 | `c3c59bfe34814800144899d2d79938bddeda56eb367cff7f1d468bf1fde8c4dc` | 0.02 |
| 3362 | consolidated | 151 | `836498ace0e7bf4dba29345c0fb246897b3bbdec192b5fd31908ffc2bc77c2b1` | -1.38 |
| 3363 | consolidated | 143 | `b150b5402ccf87a781e0670bb1b06103310cc9c0b0e95e4bbef34d81ab1c5246` | -0.22 |
| 3373 | consolidated | 103 | `eeded23ba1e88f0581849ac696ca1356699d32261f769dc2527cfcf5de3b3e1a` | -0.09 |
| 3374 | individual | 104 | `509cd358b64989c54805727032f9ee564c4ede4216c0244dccba75156654d232` | 1.46 |

五個 candidate 合計 `628` rows。balance sheet、income statement、cash flow 的 period basis 仍分別保存 `period_end_snapshot`、`quarter_single`、`year_to_date`；EPS consumer 讀回使用 `TWD_per_share` 與 scale `100`，沒有把 cents/share 當成元／股，也沒有跨 `individual`／`consolidated` 靜默混合。所有數值 capture completion 的保守 date-only availability 為 `2026-09-09`，未用 EZSearch CDATE 回填歷史 numeric PIT。

五個 candidate 送入全新隔離 consumer `quarterly/consumer-r48-next8-http-r1.db`。首次 receipt `quarterly/r48-next8-materialization-first.json` SHA-256=`49cfe85974805e0cbbe4fc68a487ec7b113824ea657eac0cf01296c0ae0633b5` 為 `628 inserted／0 existing`；重跑 receipt `quarterly/r48-next8-materialization-retry.json` SHA-256=`3c10e7c140b7ecdf154495f8cfe55073e66ed549d40b45a097a802916c014db8` 為 `0 inserted／628 existing`。DB SHA-256=`b5a6287e9f173cccc5f0e62dc154b9a156ccc8ba02a7877a9b8a1c6a879399f7`，research-only marker SHA-256=`c62bd951ad6e07a5bc4c6311f33523570043453dfdbfdd75eff9b22cf6188904`，`PRAGMA quick_check=ok`，主表／sidecar 各 `628`；provider 2026-09-07、2026-09-08 皆讀回 `0`，2026-09-09 讀回 `628`。本輪機器摘要 `quarterly/r48-next8-consumer-summary-r1.json` SHA-256=`34f2b87780bf9eab87da53c801a352b6e334223511979af9ef58719e85078898`。

交接封裝 `quarterly/r48-quarterly-recovery-handoff-r1.json` SHA-256=`fb46f5f92548512d3871b320fee3c483b29029079ec36040584301c7a23e9558`，JSON 可直接 `json.loads`；102 個 direct path/hash reference 均重算一致，並包含 r48 主批／3374 repair、r48 普通 transport 診斷與升權後 EZSearch capture、重用的 3264／3354 evidence、五個 child 的 candidate／run manifest／raw、隔離 DB、首次／重跑 receipt、摘要及 previous r47 handoff。handoff 的失敗分類為主批 title mismatch `1`（3374，已 individual repair）、EZSearch no-match `3`（3264、3354、3372，仍 unresolved）、transport failure `0`（普通 capture 的 WinError 10013 另列為診斷，沒有混入 batch source failure）；沒有把 HTTP 200 或無匹配列計為完成。

r48 continuation plan `quarterly/mops-statement-universe-2026q2-continuation-r48-after-r47-next8.json` SHA-256=`b23bffbc049678d35c9298e3896ffb4b4fbad26bef3c5a485d4f700e90fcd5ba`，plan id=`mops-statement-universe-2026q2-d27ca425820502d9`，綁定同一份官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`160`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,814`、remaining selectable=`1,813`。下一自動 queue 為 `3264、3354、3372、3379、3388、3390、3402、3430`；三個 no-match 鍵仍在 selectable，1780 仍在完整未完成分母，沒有用 caller exclusion 使欠帳消失。

本片使用既有 `build_mops_statement_batch.py`、`materialize_mops_statement_candidates.py`、`summarize_mops_statement_consumer_batch.py` 與 `plan_mops_statement_universe.py`；定向回歸為 `40 passed、1 skipped`，skip 為既有平台 alias 限制，沒有計入成功。所有 r48 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。後續沿 r48 plan 每批最多 8 家，以來源級 circuit、成功 raw reuse、immutable child／resume、完整失敗分類與隔離 consumer readback 持續恢復，不把本片 5 家或 verified=160 宣稱為全市場完成。

### r49：3379／3402 窄 alias 修復、五家公司隔離恢復與續跑 checkpoint

r49 沿 r48 continuation plan 有界處理 `3264、3354、3372、3379、3388、3390、3402、3430` 八家（均為 `otc:2026-Q2`），每家公司最多一次，來源 transport failure 上限 1。3264、3354、3372 沿用已保存的 EZSearch 無唯一公司／期別 evidence，沒有重複抓取；3388、3390、3430 主批成功，3379、3402 主批在 XBRL row-code 對照失敗後保留 partial raw。主批 manifest `quarterly/v4-quarterly-batch-2026q2-r49-next8-manifest.json` SHA-256=`3dddf3c1628fe7bb75ff35e97ccc5b56e4fd5d52c3ee06921a4708ac5ab7ba4c`，8 requests 中 3 家成功、5 家 failed、無 pending。

3379／3402 的保存 XBRL raw 均以 strict Big5/HKSCS 解碼，未套用編碼修復；兩份原文同時列出 `工程收入` row `4520`、`營建工程收入合計` row `4500` 與 `營建工程成本合計` row `5500`。t164 顯示頁的 `工程收入淨額`、`營建工程收入`、`營建工程成本` 分別以相同報表類型、縮排與回報值核對後，才加入三個窄範圍 explicit alias；沒有使用通用「合計」改名，也沒有放寬未知 row code。新增 alias 回歸為 `9 passed`；值錯誤及同名多官方列均 fail-closed。r49 r1／r2 repair 的失敗 child 與 partial evidence 保留，沒有覆寫主批 immutable output。

以同一批保存 raw 建立的 immutable repair `quarterly/v4-quarterly-batch-2026q2-r49-repair-3379-3402-r3-manifest.json` SHA-256=`f6b3bdf49cd6314d52c2ae3606cacb17e2654e0d988681b0243513ebe3ca39ce`，兩家均成功，3379 candidate 142 rows（SHA-256=`0e1aa3fc68e2bef3672496713ebebd8c4ab998ff1e002a2d737f4854e2248411`）、3402 candidate 124 rows（SHA-256=`9c6ba8b4cffe3fcbfa286f96d4d2220b220956a76b80412198a16c0866abfa7d`）。三個主批成功 candidate 為 3388=`125` rows／`bba628edbb0b569a1c0e2a5b5c5ce9f929a2c8e8734fec9ec3b4fc33ddc73db3`、3390=`127` rows／`9b6a0d5910f362062c204ba40093674aa279afbe23e579c62dce65de3d5ddcf0`、3430=`126` rows／`1e4bb539e4b57388428f93df102d006e59b59fe4b161385ee4ce32667d95e988`。五家合計 `644` rows，報表 basis 全為 `consolidated`；balance／income／cash flow 的 period basis 仍分別保存 `period_end_snapshot`、`quarter_single`、`year_to_date`，item-code lineage 為 `mops.t164sb01.xbrl.row_code`。EPS 讀回為 3379=`-0.54`、3388=`2.21`、3390=`-0.31`、3402=`2.08`、3430=`1.23`（`TWD_per_share`，scale 100），沒有把官方 cents/share 誤當元／股。

五個 candidate 送入全新隔離 consumer `quarterly/consumer-r49-next8-http-r1.db`；DB SHA-256=`c55ff68594670a1bce5585f9a41bfa6665d24953d4de4909089d58b986596fff`，research-only marker SHA-256=`09f71ded474d01118c76b4cd67c7025791a55d9242e4e097a26c0b170f6fcf59`，`PRAGMA quick_check=ok`，主表／sidecar 各 644。首次 receipt `quarterly/r49-next8-materialization-first.json` SHA-256=`af72d073679d32cb339480cff4f2e4f1327e137752684ed6ca0409aec73a3e3e` 為 `644 inserted／0 existing`；重跑 receipt `quarterly/r49-next8-materialization-retry.json` SHA-256=`1fc64062676cc34662455c323ba06bf041d2063e8ae146532bc9ca58d96ddcd8` 為 `0 inserted／644 existing`。provider 在 2026-09-07、2026-09-08 均讀回 `0`，2026-09-09 讀回 `644`；五家公司分別為 142／125／127／124／126，沒有讓 cutoff 前資料進入 consumer。

r49 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r49-after-r48-next8.json` SHA-256=`a1e75bc64f781e01eb755ccb78d1ae5d833bca166dc38ee069b49c8759ce6881` 綁定官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`165`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,809`、remaining selectable=`1,808`，下一批自動 queue 為 `3264、3354、3372、3434、3438、3465、3466、3467`。3264／3354／3372 仍是 selectable 且未完成；1780 仍保留完整 deferred 分母，沒有以 caller exclusion 或 no-match evidence 使欠帳消失。

機器摘要 `quarterly/r49-next8-consumer-summary-r1.json` SHA-256=`04bfe61f5b210da654a78fe37297b9019bfe4554a3e17361c877c420e881ccbe` 綁定主批、r3 repair child、五個 candidate、隔離 DB、首次／重跑 receipt 與 cutoff。交接封裝 `quarterly/r49-quarterly-recovery-handoff-r1.json` SHA-256=`a94d75b24961f29e605761c328240cec01b3d411af39cd3bf4544a6e34220f98` 為合法 JSON，89 個直接 path/hash references 全部重算一致；failure classification 保留主批三個 EZSearch no-match、兩個已由窄 alias immutable repair 解決的 XBRL 對照失敗、capture transport 診斷與完整 universe 分母。所有 r49 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`，D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。

### r50：3438 個別報表修復、四家合併報表與續跑 checkpoint

r50 依 r49 continuation plan 執行 `3264、3354、3372、3434、3438、3441、3444、3455` 八家。普通 EZSearch capture `quarterly/ezsearch-r50-next8-r1/capture-manifest.json` 記錄 WinError 10013 且沒有 raw，僅作本機 transport 診斷；依正常 approval 路徑執行一次 bounded 官方讀取後，`quarterly/ezsearch-r50-next8-r2/capture-manifest.json` SHA-256=`4f796a1696c16a70f35c141cf31f8a50b00eb7e27931e37077935a02444c97b7`，五家新公司 F26／F27／F28 均取得 HTTP 200、唯一公司／市場／2026-Q2 公告列。3264、3354、3372 沿用既有 no-match evidence，沒有重複抓取。主批 manifest `quarterly/v4-quarterly-batch-2026q2-r50-next8-manifest.json` SHA-256=`41b8b2a2d813414457ecfc997f4d26db8b8b6b2022aa836fa20c8245ae189da3`，8 requests 中 4 家成功、4 家 failed、無 pending；3438 的 consolidated title mismatch 保留 failed child，沒有把 HTTP 200 當作數值成功。

3438 之後以同一公告 evidence 執行 immutable `report_basis=individual` repair，manifest `quarterly/v4-quarterly-batch-2026q2-r50-individual-3438-manifest.json` SHA-256=`bd4f9b9dc22cd95d1a4878917ac24ec24cdb0265c8d729870652320278a82252`，child candidate 120 rows／SHA-256=`72188d7f4a833d624c4ab703365d925f407825a24ba3f048476941d446f3c59e`、run manifest SHA-256=`7948d89c51b5af013d2fc6393dc32ff9ea220dedf9a13124cb0afc30c675e694`。四家 consolidated candidate 為 3434=`127` rows／`d67dfd8812101d11bde7565d62b74b5daee0efd9558776e8ba443d131131658b`、3441=`122` rows／`c8777831a6c60872089f093c47ed00070cdfcf30d49312987d5f2b07dacc1276`、3444=`130` rows／`eb4f0cd9663df12fd1ee8154b59da015cde824680a0277f17fbfd66acd815111`、3455=`135` rows／`32260370f75f6e60c8f45a9855f75e5d64c7d09e786c8243b58f3fcb2752e271`。五家合計 `634` rows；3438 individual 與其餘四家 consolidated 的 report basis 分開保存，period basis 與 item-code lineage 仍依各 child 原始契約保存。EPS 讀回為 3434=`0.10`、3438=`0.39`（individual）、3441=`0.69`、3444=`0.64`、3455=`0.38`，單位 `TWD_per_share`、scale 100。

五個 candidate 送入全新隔離 consumer `quarterly/consumer-r50-next8-http-r1.db`；DB SHA-256=`eee58f91360825be05a572ffbf4dc4e5ed869047d1f203dd61253e5bc4b65c87`，research-only marker SHA-256=`3abc8f8db6f17471f5a86dea59e0e1b72b1b00c4e1238db306ad6452b41d2208`，`PRAGMA quick_check=ok`，主表／sidecar 各 634。首次 receipt `quarterly/r50-next8-materialization-first.json` SHA-256=`e27f9bcbdf751e2d7aa39488e0d85fb4764ae5c1c209b78d1269f53ed7f9793b` 為 `634 inserted／0 existing`；重跑 receipt `quarterly/r50-next8-materialization-retry.json` SHA-256=`0163c2b419f6502b1d50c66477b4f8a72fadf6387d64959f8d7563033e2ad4a1` 為 `0 inserted／634 existing`。provider 在 2026-09-07、2026-09-08 均讀回 `0`，2026-09-09 讀回 `634`；沒有讓 cutoff 前資料進入 consumer。

r50 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r50-after-r49-next8.json` SHA-256=`de57c08c021f644db3248676701535298159836df85aae4273b73e4dc8091954` 綁定同一份官方 companies.csv；eligible=`1,974`、verified completed=`170`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,804`、remaining selectable=`1,803`，下一批自動 queue 為 `3264、3354、3372、3465、3466、3467、3479、3483`。3264／3354／3372 仍保留 no-match 失敗證據與 selectable 分母，沒有被誤計為不存在。

機器摘要 `quarterly/r50-next8-consumer-summary-r1.json` SHA-256=`2af4eb7f4fcb392161b1f81ad39f6d1381032e41ce1ece3c7a7fd28fbe19d213` 綁定主批、3438 individual child、五個 candidate、隔離 DB、首次／重跑 receipt 與 cutoff；交接封裝 `quarterly/r50-quarterly-recovery-handoff-r1.json` SHA-256=`b944758d7d9098e553ea18218333cfb766ff9b5a4b1be6f47129ef9afecca249` 為合法 JSON，37 個直接 path/hash references 全部重算一致。所有 r50 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`；後續沿 r50 plan 每批最多 8 家、成功 raw reuse、來源 circuit breaker、immutable repair／resume 與隔離 consumer readback 繼續，不能把 verified=170 或本片五家視為全市場完成。

### r51：3264／3354／3372 EZSearch 窄窗根因修復與個別報表隔離恢復

r51 針對 `3264、3354、3372:otc:2026-Q2` 追查反覆 `no_matching_company_period_row`。先前三份官方 EZSearch HTTP 200 evidence 的查詢區間都是 `2026-08-01` 至 `2026-09-07`，每份回應各 `863` rows，F26／F27／F28 均無目標公司／期別匹配；這是查詢起日排除了七月公告列，不是公司不存在，也不是 transport 成功後的空資料。既有官方寬窗 `2026-07-01` 至 `2026-09-07` raw 未重新下載，F26／F27／F28 各 `901` rows，三家公司均各有唯一公司代號、上櫃市場與 `2026-Q2` 列：3264 公告事件 `115/07/23 15:46:42`、3354 `115/07/31 10:15:52`、3372 `115/07/27 17:34:51`。寬窗 raw SHA-256 依序為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`；重用與逐公司匹配 evidence 保存在 `quarterly/ezsearch-r51-common-window-reuse-r1/`，其 capture manifest SHA-256=`578fdeb56da38888da2abaae5a471afef009250b2e25637627792f694d236622`，來源 capture manifest 為 `quarterly/ezsearch-r38-3088-broader-r1/capture-manifest.json`（SHA-256=`c4ae944aebdbb7ac8afee52b07d55453a1d82e3e36c95455597e8255ec5fbcbb`）。公告日期只作 availability lane，沒有給 numeric candidate 歷史 PIT credit。

普通 Python transport 只做一次 bounded diagnostic，第一個 t164 request（3264）留下 `WinError 10013`，source circuit 開啟後 3354／3372 pending；完整 manifest `quarterly/v4-quarterly-batch-2026q2-r51-common-gap-r1-manifest.json` SHA-256=`0ab3c5f5b4242db6617c576b4ad4ebbced10e5a66dbb38f0246b3c1a0b1ad5bf`，partial failure 與 pending 狀態保留。依正常升權 approval 路徑各一次 bounded official read 後，3264 manifest SHA-256=`3c265efa8aa92ca0850541680cd06d12be0c88f9fc01e3909ecac457f1bb494d`，candidate `138` rows／SHA-256=`871805725c7afcc1583906d8f42f9abf17677a0622eeeff063746898336d4d89`；3354 manifest SHA-256=`250f755e1acbeddb658d78c780e19e894fefe408189edc799148c767e837d22`，candidate `126` rows／SHA-256=`ee70c911f8d0a1ea12af6972826522d54bff620d90be5e5ad4f9c12eac154076`。兩家為 consolidated，source version 為 `mops-t164-consolidated-statements-with-mops-ezsearch-publication-xbrl-row-codes.v3`。

3372 的 consolidated 路由明確因官方回應標題為 individual 而 fail-closed，失敗 receipt 保留在 `r51-common-gap-approved-r2`，沒有把 individual response 貼成 consolidated。以明示 `report_basis=individual` 建立新的 immutable repair：manifest SHA-256=`1ab005f0cf9e540476bdb6c7833b485d36c85f20ca62ae888a207f61d72ecd08`，candidate `105` rows／SHA-256=`df2bd08a0cda716a704bbd9aaf232565a8b549214498b4fe3b940ef858ca7a92`，source version 為 `mops-t164-individual-statements-with-mops-ezsearch-publication-xbrl-row-codes.v3`。因此本片 3372 的可用資料是 individual，與 3264／3354 consolidated 分開保存；consolidated 失敗歷史沒有刪除或計入成功。

三個 candidate 合計 `369` rows，balance／income／cash flow 的 period basis 分別保留 `period_end_snapshot`、`quarter_single`、`year_to_date`，item-code lineage 為 `mops.t164sb01.xbrl.row_code`。隔離 consumer `quarterly/consumer-r51-common-gap-approved-r1.db` 的 SHA-256=`25e4f3a0024be393feb3d2a6fbd74007fd11efd77d635376b8593e77f6cda4c0`，research-only marker SHA-256=`71676e79d1bf7fa4e3b424cb04a5cd566b62fbdd652a872a6badf0020a1470c3`，`PRAGMA quick_check=ok`，主表／sidecar 各 `369`。首次 receipt `r51-common-gap-materialization-first.json` SHA-256=`228736847bc9121c7152529c340a8850554698a7a14fcf7de59ec174393eb394` 為 `369 inserted／0 existing`；重跑 receipt `r51-common-gap-materialization-retry.json` SHA-256=`891609afde38007f981509e7896be57a87c35b90dc56e8d4d1b19bee006673f3` 為 `0 inserted／369 existing`。provider 在 `2026-09-08` 讀回 `0`、`2026-09-09` 讀回 `369`；沒有讓 cutoff 前資料進入 consumer。EPS 由既有 consumer 讀回為 3264=`2.44／2.43`、3354=`-0.11／-0.11`、3372=`-0.07／-0.07`，單位均為 `TWD_per_share`、scale `100`，3372 sidecar 保留 individual basis。

r51 machine summary `quarterly/r51-common-gap-consumer-summary-r1.json` SHA-256=`7d9bc0eba5270a8631d58b8b8796550cbf0d0b630c93b8b523c978d84319c734` 綁定三份 approved batch、三個成功 child、3372 consolidated failure、candidate／run manifest／raw／availability hash、隔離 DB、首次／重跑 receipt 與 cutoff。交接 r1 後補入普通 transport 的 3264 具體 failure，建立合法 immutable `quarterly/r51-quarterly-recovery-handoff-r2.json`，SHA-256=`4892cae86c50207a787ea41601b922534ad57f4b597791f07ef331043b5379a1`，共 `67` 個 direct path/hash references，逐檔讀回並重算一致；r1 保留但由 r2 supersede。handoff 另綁定來源寬窗 raw／窄窗 no-match evidence，明確記錄「查詢窗遺漏」根因、WinError 10013 診斷與 report-basis 修復。

r51 continuation plan `quarterly/mops-statement-universe-2026q2-continuation-r51-common-gap.json` file SHA-256=`61fa7f26680b121c9193b908f899a475227b7b468a0edb2a32e69bb96d32fc2f`、content SHA-256=`7f3bde633e63401152e1f104fe366f38bd9d51c43a0ab8b91381393b3eeb49c0`，plan id=`mops-statement-universe-2026q2-7f3bde633e634011`；官方 companies.csv registry SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`。目前 eligible=`1,974`、verified completed=`173`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,801`、remaining selectable=`1,800`；下一自動 queue 為 `3465、3466、3467、3479、3483、3484、3485、3489`。本片三家公司已從未完成鍵轉為 verified，1780 仍保留完整 deferred／未完成母數，沒有把 caller exclusion 或窄窗 no-match 當成不存在。

本片定向 `capture_mops_ezsearch_statement_availability`、`build_mops_statement_batch`、candidate adapter、consumer summary、universe plan、candidate parser 與 3064 alias 回歸共 `109 passed、1 skipped`；skip 為既有平台 alias 限制，沒有計入成功。新增通用查詢窗規則：未明示 `--start-date` 時，依 request 的季度從財報期末翌日開始（2026-Q2 為 `2026-07-01`），不再固定從 `2026-08-01` 起查；顯式起日仍可用，公告事件與 numeric capture availability 仍分離。r51 所有 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`；D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。後續沿 plan 每批最多 8 家，成功 raw reuse、來源 circuit、immutable resume 與隔離 readback 繼續，不重抓本片已成功 raw，也不宣稱全市場已恢復。

### r52：八家 TPEx 季報官方取數、兩項 immutable 修復、隔離 consumer 與通用 EZSearch 查詢窗

r52 依 r51 continuation plan 有界選取 `3465、3466、3467、3479、3483、3484、3485、3489` 八家（均為 `otc:2026-Q2`），每家公司最多 1 次，來源 transport failure 上限為 1。先執行普通 Python transport diagnostic；`quarterly/v4-quarterly-batch-2026q2-r52-next8-manifest.json` 在第一個 t164 request（3465）遇 `WinError 10013`，開啟 `mopsov.twse.com.tw` source circuit，後七家公司保留 pending／deferred checkpoint，沒有把 sandbox 失敗誤寫成公司無資料。依正常 approval 路徑只執行一個 bounded window 後，`quarterly/ezsearch-r52-next8-r2/capture-manifest.json` SHA-256=`211aa7293b9cfa3bac15d06fdc53b6c00f2b894586b9fbc1e65cb01692ba2dc4`；官方 EZSearch F26／F27／F28 查詢窗為 `2026-07-01..2026-09-07`，每個 response 為 HTTP 200、901 rows，八家公司均有唯一公司代號、上櫃市場與 `2026-Q2` subject。capture 的 F26／F27／F28 raw SHA-256 分別為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`；各公司 evidence 與 matched row SHA 由 capture manifest 綁定。普通 capture `quarterly/ezsearch-r52-next8-r1/` 沒有 HTTP raw，只作 transport 診斷，沒有進入 availability acceptance。

本輪把 r51 已確認的固定起日缺陷接到通用入口：`capture_mops_ezsearch_statement_availability.py` 未指定 `--start-date` 時，以 request 的財報期末翌日作為起日；Q2 即 `2026-07-01`，顯式起日仍可覆蓋。保留公告 publication 與 numeric capture availability 的分離，沒有用公告日回填歷史 numeric PIT。capture parser 現在也保留 `transport_error`／HTTP error／invalid JSON／official no-data 的實際狀態，不再把 transport 失敗歸類為 `no_matching_company_period_row`。`tests/test_capture_mops_ezsearch_statement_availability.py` 對 Q1–Q4 預設窗、Q2 七月公告覆蓋及 transport 負例均通過。

標準官方 t164／XBRL batch `quarterly/v4-quarterly-batch-2026q2-r52-next8-approved-r1-manifest.json` SHA-256=`11480c579ac460ae9823ce43f1d6f36d7011de0b54794f150111c764bc2f072e`，八家中 6 家成功、2 家因內容語意防護失敗；失敗 raw／partial 保留。3467 的 consolidated balance title 與回應不符，先保留原始 failed child，再以明示 `report_basis=individual` 建立 immutable repair `quarterly/v4-quarterly-batch-2026q2-r52-repair-3467-individual-r1-manifest.json`，SHA-256=`8cc7842c7d6c6f3f4b3677a3266d942afd3ca622f3e7f79859d59913d984d973`，candidate `107` rows／SHA-256=`13e32143b43707e9c052bea49c60b8937e7ad5343fd008d7b0f66eb7ee322ce5`，run manifest SHA-256=`348299429275c10889d548995acd60d787d44c21fd9a462ff4d274fe11418210`。3479 的原始 XBRL 對顯示項目 `勞務收入` 找不到唯一 code，保留失敗 child 與 partial raw 後，依官方 XBRL 同期間／值核對得到總列 `勞務收入合計` code `4600`，以明確登錄 alias 建立 immutable repair `quarterly/v4-quarterly-batch-2026q2-r52-repair-3479-rowcode-r1-manifest.json`，SHA-256=`42937655ca0459bd80bfc2cb69fa156eb50883a033b99f7584d443aef0a75f07`，candidate `174` rows／SHA-256=`102f277333341ed35e1e8f8268b4ade85ae5f47757e450804b1b9d8b7d68f0d5`，run manifest SHA-256=`4796ee90bd77727c10de80564e235d5f2d6cb3632c1714e5cd9a9c04d49c5ab0`。此 alias 僅針對已核對的官方 4600 總列，沒有把任意同名列或未知科目自動加上／去掉「合計」。

| 公司 | report_basis | rows | EPS（TWD/share） | candidate SHA-256 |
| --- | --- | ---: | ---: | --- |
| 3465 | consolidated | 135 | 0.19 | `2901ad3a966b716979694c5c053d6a41f0831e0df6d4fefcdf26b90cf4833417` |
| 3466 | consolidated | 120 | -0.28 | `e20fa977c0e695a11c73944d5eba37e3e5a48025bda279c3a3815ffe361aa58a` |
| 3467 | individual | 107 | 0.50 | `13e32143b43707e9c052bea49c60b8937e7ad5343fd008d7b0f66eb7ee322ce5` |
| 3479 | consolidated | 174 | 1.72 / 1.63 | `102f277333341ed35e1e8f8268b4ade85ae5f47757e450804b1b9d8b7d68f0d5` |
| 3483 | consolidated | 137 | 0.52 | `109449a74b48a13e976ae9c41acd30114b3973581169093c473209ee6ed618bf` |
| 3484 | consolidated | 119 | 0.67 / 0.63 | `2b8e45e27ffba5b50978d21466f581c52976c309e28303280354e19291c26e3e` |
| 3485 | consolidated | 123 | 1.25 | `b375e1201beafdc42c064467a42faa7c83abda798186f4fc2f12573d96d99e44` |
| 3489 | consolidated | 112 | 0.05 | `5b0fd1ea57d5bbc95bbbf262f5cd4c944634d431922ff892f13178a3d8aea5b4` |

八家合計 `1,027` rows；balance／income／cash flow 的 period basis 與官方 `mops.t164sb01.xbrl.row_code` lineage 均保留。3467 的 107 rows 明確為 individual，另外七家為 consolidated，沒有混合 report basis；3479 的 4600 alias 值與期間均經 raw t164／XBRL 交叉核對。EPS 由既有 consumer 讀回，仍是 `TWD_per_share`、scale `100`，沒有把 cents/share 誤當元／股。

八個 candidate 送入全新隔離 consumer `quarterly/consumer-r52-next8-http-approved-r1.db`。DB SHA-256=`904d1174e4467ff0757aed5851d952e8bf2edba2465e72fdc05c966830cd6729`，research-only marker SHA-256=`75576f2f1042878f066fbf38c97c2063140131f7e70831cd6c50931a7f477ca3`，`PRAGMA quick_check=ok`，主表／sidecar 各 `1,027`；basis 分布為 consolidated `920`、individual `107`。首次 receipt `quarterly/r52-next8-materialization-first.json` SHA-256=`08f024d9261fc95c27c63588a3587879b9bc9cf9d561792a4807c304f411e35d` 為 `1,027 inserted／0 existing`；重跑 receipt `quarterly/r52-next8-materialization-retry.json` SHA-256=`2405707cf753803cc1ef0708a8c6f4e103cefe0d116db3778bf15e2cc73ff3a1` 為 `0 inserted／1,027 existing`。provider 在 `2026-09-08` 讀回 `0`、`2026-09-09` 讀回 `1,027`；numeric capture completion 的保守 date-only availability 為 `2026-09-09`，沒有讓 cutoff 前資料進入 consumer，也沒有用 publication CDATE 回填數值可得日。

r52 machine summary `quarterly/r52-next8-consumer-summary-r1.json` SHA-256=`00f7687b11718c4b5c0d213d5a4408eeb948762c6d706ca4c3f999a7ee72c8fb` 綁定三份成功／partial batch manifest、八個成功 child、兩個原始 parser failure、candidate／run manifest／raw／availability hash、隔離 DB、首次／重跑 receipt 與 cutoff。r52 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r52-next8.json` SHA-256=`88305b9426cb953b9fdb8d8ab5c560fc13565a2d43e642782b70fc8b71b81c5c`、content SHA-256=`d8896a69a0da50af7fcdf4807b5569e85d5de2766fc5ea0ebcbda25f2bb8d4c9`、plan id=`mops-statement-universe-2026q2-d8896a69a0da50af`，綁定官方 companies.csv registry SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`；eligible=`1,974`、verified completed=`181`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,793`、remaining selectable=`1,792`，下一自動 queue 為 `3490、3491、3492、3498、3499、3508、3511、3512`。本片八家公司已由 r51 的 selectable 鍵轉為 verified；1780 仍保留完整 deferred／未完成母數，沒有把任何 caller exclusion 或 transport／parser failure 從欠帳消失。

r52 交接封裝 `quarterly/r52-quarterly-recovery-handoff-r1.json` 為合法 JSON，實際保存 `215` 個 direct path/hash references，涵蓋兩次 EZSearch capture、普通 transport batch、approved batch、兩個 immutable repair batch、全部 child／partial raw、consumer DB／marker、首次／重跑 receipt、summary、plan 與 previous handoff；逐檔 hash checker 對所有 references 通過，沒有 self-reference 或 literal `\\n` 尾巴。handoff 明確記錄 ordinary `WinError 10013`、3467 title mismatch、3479 ambiguous row code 與各自修復沿革；所有 output 均為 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`，D 槽原始資料、正式 availability mapping 與正式 SQLite 維持只讀。handoff SHA-256=`1dfac0ef1ec20aa4581c255ad31c9db30e827d6ccbf556ccaebdd5a942c29b28`。

本片定向 `capture_mops_ezsearch_statement_availability`、3064 alias、batch、candidate adapter、consumer summary、universe plan 與 candidate parser 回歸為 `111 passed、1 skipped`；skip 為既有平台 alias 限制，沒有計入成功。四個變更腳本 `py_compile` 通過。r52 產物合計約 `25.0 MiB`，低於本片 1 GiB 產物上限；本片仍是隔離 research slice，不能把 verified=`181/1,974` 或 1,027 rows 宣稱為全市場恢復。後續沿 r52 plan 每批最多 8 家，成功 raw reuse、source circuit、immutable resume 與同樣的 publication／numeric availability 分離繼續。

## r53 bounded next8：3490、3491、3492、3498、3499、3508、3511、3512（2026-09-07）

本片先以普通 transport 做一次有界診斷，`r53-next8-http-r1` 在 `3490` 遇 `WinError 10013` 後開啟 `mopsov.twse.com.tw` source circuit，其餘七家公司保留 `source_transport_circuit_open` deferred receipt；此結果只證明執行環境 transport 限制，不把公司標成無公告，也沒有重複盲目請求。經正常 approved 唯讀路徑完成同一批官方數值擷取，`quarterly/v4-quarterly-batch-2026q2-r53-next8-approved-r1-manifest.json` SHA-256=`96d6b6e1f7270c1e48975de2e9125d11d05ddcd5bddf2e71ccde9258282d1b92`，7 家成功、1 家（3499）保留嚴格解碼 failure receipt；成功 row counts 為 `3490=133、3491=154、3492=155、3498=142、3508=133、3511=129、3512=107`，合計 953。

官方 EZSearch capture 保存在 `quarterly/ezsearch-r53-next8-r2/capture-manifest.json`，SHA-256=`211aa7293b9cfa3bac15d06fdc53b6c00f2b894586b9fbc1e65cb01692ba2dc4`。窗口為 `2026-07-01..2026-09-07`；F26/F27/F28 原始 response hash 分別為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`。8 筆 evidence 均核對 exact company id、TPEx market、2026-Q2 subject；公告日只作 availability lane，不回填 numeric PIT。

固定查詢窗缺陷已修正：`scripts/capture_mops_ezsearch_statement_availability.py` 的未指定 `--start-date` 現在依財報期末翌日產生候選起日，2026-Q2 為 `2026-07-01`，保留明確指定起日的 caller override。回歸涵蓋 Q1-Q4 default、Q2 小於舊 `2026-08-01` 窗口與 transport error status 保留，避免七月公告被漏查或把錯誤回應誤記成 no-match。

同一窗口的未指定 `--end-date` 現在在執行當下以 `ZoneInfo("Asia/Taipei")` 取得一次並凍結，明確指定的終日仍優先；因此不會因本機 Pacific timezone 少查一天，也不會在執行跨台北午夜時前後不一致。`2026-Q3` 在當日尚未到 `2026-10-01` 時會在建立 output 目錄或發送網路前 fail-closed。新增跨日凍結與未來季度 fail-before-network 回歸；本片修正後該測試模組為 `8 passed`（僅既存 pytest cache 權限 warning）。

3499 的失敗不是以放寬解碼吞掉：一次有界官方 `mopsov.twse.com.tw/server-java/t164sb01` 唯讀診斷保存於 `quarterly/r53-diagnose-3499-xbrl-r1/raw/mops_t164sb01_xbrl_3499_2026Q2.html`，536,270 bytes、raw SHA-256=`6e59cf3519d179137f6688210195b667f91597e2d1e73a9ce2f75a1b4e063a71`。明示 `big5` 下 strict Big5/HKSCS 僅在六個 offset `419490、419644、419706、420028、420707、420781` 遇 `0x84`；上下文均為 IFRS18／IAS7 敘述段落行首項目符號，非數值或識別欄位。只對該完整 raw SHA 與六個 offset 套用 `strip_declared_big5_c1_controls`，strict decode 後 metadata 仍為 `companyid=3499、year=2026、quarter=2、Consolidated report、Over-the-counter`。保留舊 failed partial raw，另以不可變 `r53-repair-3499-encoding-r1` replay 產生 170 rows（BS57／IS43／CF70，EPS=`-0.32`），candidate SHA-256=`0ae3a8cfc06196120e8b7fc598c88b9b843f856f029918df39ee9ac0f3ce2125`，child run manifest SHA-256=`21adb73fb292ed00c56b5a9be5fb1457d4880e73d660cb35c8f02599322eeb21`，repair batch manifest SHA-256=`14fa9c73b829c2af143dae409efe0709bbb3a69ab7e9796f43aa9d096c69cb9b`。此修復不推廣至未知來源或任意數值 byte。

8 家（含 3499 immutable repair）隔離 materialization 實際為 `1123` rows，沒有寫正式 DB 或 D 槽：

- 首次 receipt `quarterly/r53-next8-materialization-first.json` SHA-256=`90ce9aab9e3f5fdccc7b9a863462d72af47f49b4b48a4e80010cc88af155be3f`：`1123 inserted／0 existing`。
- 重跑 receipt `quarterly/r53-next8-materialization-retry.json` SHA-256=`8f1edd493224356e77d2ac39255f6c14d1669260a8fbaed53e83dc5c8b238788`：`0 inserted／1123 existing`。
- `consumer-r53-next8-http-approved-r1.db` SHA-256=`99ab31698b57975ba5f4a9d68e4e34c25c129ad16f24b01a9c2d4da9ad16655b`，marker SHA-256=`1cea23fbbcfa46db4bdc720d9061bbd02fe8b0c5171eab21f44846da94abab66`；SQLite `quick_check=ok`，main／sidecar 均 `1123`，全部 item code 來自 `mops.t164sb01.xbrl.row_code`。
- provider date-only readback：`2026-09-07=0、2026-09-08=0、2026-09-09=1123`；numeric capture completion 採保守 `next_taipei_calendar_day`，未以 EZSearch 公告日宣稱歷史 PIT。8 家 EPS、unit、period basis 經 sidecar 保留，3499 EPS `-0.32 TWD_per_share`、`quarter_single`。

機器 summary `quarterly/r53-next8-consumer-summary-r1.json` SHA-256=`aa038aa747fd8d7d4dfe6b195bb90e4eaa4aa244a7f1ec700fb2ccdc58a09f23` 綁定兩份 r53 batch manifest、8 個 completed child、3499 原始失敗歷史、candidate／run manifest／raw／EZSearch hash、隔離 DB、首次／重跑 receipt 與 cutoff。r53 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r53-next8.json` SHA-256=`d37a7b29b61a9c838db16ea7a6e07206f557b45b1bb91f034df0072572c5b764`、content SHA-256=`c19d9bcf9dae73ac64e9cbe0b50d7414c636eac11ce63595cc54f61031a57c0f`、plan id=`mops-statement-universe-2026q2-c19d9bcf9dae73ac`；eligible=`1,974`、verified completed=`189`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,785`、remaining selectable=`1,784`，下一自動 queue 為 `3516、3520、3521、3522、3523、3526、3527、3529`。完整 r53 handoff `quarterly/r53-quarterly-recovery-handoff-r1.json` 為合法 JSON，SHA-256=`8a2119d5851bd6f9a66dfa85e074b31601b4638981eb1a3cc230b7ddd2617f6d`，保存 `363` 個 direct path/hash references，包含前一 handoff、兩次 r53 EZSearch capture、普通／approved／repair batch、所有 r53 raw／partial／repair input、8 child、隔離 DB／marker、receipt、summary、plan；檔案逐一 hash 核對且無 literal `\\n` 尾巴或 handoff self-reference。

本片定向 capture、candidate parser、batch、adapter、consumer summary、universe plan 與既有 source contract 回歸為 `115 passed、1 skipped`；skip 為既有平台 alias 限制，沒有計入成功。六個變更／入口腳本 `py_compile` 通過；pytest 僅有既存 `.pytest_cache` 權限 warning。輸出維持 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`，正式 SQLite 與 D 槽原始資料不變。r53 artifact 仍是 bounded research slice，不能把 verified=`189/1,974` 或 1,123 rows 宣稱為全市場恢復；後續依 r53 checkpoint 每批最多 8 家，成功 raw reuse、source circuit、immutable resume 與 publication／numeric availability 分離繼續。

### r54 bounded next8：3516、3520、3521、3522、3523、3526、3527、3529（2026-09-07）

r54 沿 r53 continuation plan 有界處理 `3516、3520、3521、3522、3523、3526、3527、3529` 八家（均為 `otc:2026-Q2`），approved numeric batch 的每家公司最多一次，成功 raw 不重抓。官方 EZSearch capture `quarterly/ezsearch-r54-next8-r1/capture-manifest.json` SHA-256=`218b70a5048d5d3d488ef452752bb8bf1143e42a2f6385194b36e3c7c011298e`，窗口為 `2026-07-01..2026-09-07`；F26/F27/F28 raw SHA-256 依序為 `bff4154e4810efca0c4072412d198599c419f9ed492a55ef5cd4c56e14279083`、`edb5b38c41d1831b01065e1d77f9dd2edc4ca3e9ff7a1eb2ee2124000a27cea1`、`95f2d8fe06f56738da60bde7e263406ed6501c07bbb6c1562d28e004ea8e47fa`。八家 evidence 均保留 exact company、TPEx market 與 `2026-Q2` match；公告事件仍只屬 availability lane，沒有回填 numeric 歷史 PIT。

主批 `quarterly/v4-quarterly-batch-2026q2-r54-next8-approved-r1-manifest.json` SHA-256=`8a1f9e2fd7a3c3f9a338dbc7fe7828edba1813a9b041c979e7b770f3ce0585ab`，7 家成功、1 家失敗。成功候選 row counts 為 `3516=148、3520=116、3521=126、3522=144、3523=120、3527=116、3529=129`，合計 `899` rows；3526 在 XBRL strict Big5/HKSCS 解碼階段失敗，partial failure SHA-256=`48989e55dfcc944c173c74f2353b38b323dccf59b7f309ac30d45ac4bb3df175`，失敗 raw 與 evidence 均保留，沒有以 HTTP 200 當成數值成功。

3526 的一次有界官方 XBRL 診斷保存在 `quarterly/r54-diagnose-3526-xbrl-r1/raw/mops_t164sb01_xbrl_3526_2026Q2.html`，543,670 bytes、raw SHA-256=`4267346c8127510b1baf22a4bacfeac2488feaebd61034b93c1ec0e04e0366d1`。官方 metadata 核對為 `companyid=3526、year=2026、quarter=2、Consolidated report、Over-the-counter`；明示 `big5` 後只有五個 `0x84` 位於 offset `406096、406251、406312、406637、407323`，上下文均為 IFRS18／IAS7 敘述段落行首項目符號，不是數值儲存格或識別欄位。只對這一完整 raw SHA 與五個 offset 套用 `strip_declared_big5_c1_controls`，strict Big5/HKSCS 解碼成功；未增加一般性刪 byte 容錯。

以失敗 child 的三份已保存 statement raw、同一份 3526 XBRL raw 與既有 EZSearch evidence 做 immutable offline replay，建立 `quarterly/v4-quarterly-batch-2026q2-r54-repair-3526-encoding-r1-manifest.json`，SHA-256=`0077796aa9a095d594ee56802eff200baf05a3842a2d4c2564f9c30802d83824`。修復 child candidate 為 `146` rows、SHA-256=`1c2e345e2a8e7b3992689d396992fc0b54583f4038b062373f39a086779e14d2`；run manifest SHA-256=`c1625ea92d2d941ed6424860a6baf7945b11d438e5d224a309f0fab91792b7f3`。修復後八家均為 `consolidated`，每家 balance／income／cash flow 的 period basis 仍分別保留 `period_end_snapshot`、`quarter_single`、`year_to_date`，item-code lineage 為 `mops.t164sb01.xbrl.row_code`。

| 公司 | rows | balance / income / cash flow | EPS（TWD/share） |
| --- | ---: | ---: | ---: |
| 3516 | 148 | 60 / 31 / 57 | 0.36 |
| 3520 | 116 | 43 / 27 / 46 | -0.11 |
| 3521 | 126 | 45 / 29 / 52 | -0.02 |
| 3522 | 144 | 50 / 31 / 63 | -0.85 |
| 3523 | 120 | 44 / 28 / 48 | -0.44 |
| 3526 | 146 | 54 / 34 / 58 | 4.38 |
| 3527 | 116 | 40 / 31 / 45 | 0.14 |
| 3529 | 129 | 47 / 33 / 49 | 7.77 |

八家合計 `1,045` rows；EPS 由既有 consumer contract 以 `TWD_per_share`、scale `100` 讀回，沒有把 cents/share 當成元／股。

八個 candidate 送入全新隔離 consumer `quarterly/consumer-r54-next8-http-approved-r1.db`，沒有寫正式 DB 或 D 槽：

- 首次 receipt `quarterly/r54-next8-materialization-first.json` SHA-256=`119df0d084551e629d11c7416ff833984a7c44dd7c202f19c5fc0892a3f496ae`：`1,045 inserted／0 existing`。
- 重跑 receipt `quarterly/r54-next8-materialization-retry.json` SHA-256=`8a97dffa64a76e14f83d1b41a98a63816d5032ec196556ab86b04e171b8e2e6f`：`0 inserted／1,045 existing`；兩次 receipt 讀回同一 DB SHA-256=`78da3f39abd62c2f41353faebfc35c24392d47bc812063b35c3b458b20f754d0`。
- DB research-only marker SHA-256=`405a5e6ee71bd777b3fedc79a7b5d458b8ecf819b1d9bb6097e68cd07bc2d24f`；`PRAGMA quick_check=ok`，主表／sidecar 各 `1,045`，item-code source 全為 `mops.t164sb01.xbrl.row_code`。
- provider date-only readback 為 `2026-09-07=0、2026-09-08=0、2026-09-09=1,045`。candidate 內 numeric capture completion timestamp 與 date-only `2026-09-09` 分開保存，沒有以 EZSearch 公告日期宣稱歷史 PIT。

r54 machine summary `quarterly/r54-next8-consumer-summary-r1.json` SHA-256=`a200943faefdf945e6d043900df46ca224b743f8eb496ab5ff98dfc85c46e189` 綁定主批、3526 immutable repair、8 個 completed child、3526 初始 failure、candidate／run manifest／raw／availability hash、隔離 DB、首次／重跑 receipt 與 cutoff。r54 universe checkpoint `quarterly/mops-statement-universe-2026q2-continuation-r54-next8.json` SHA-256=`16f7c33c05c7e2279f2b287444dab3e24a8ce229fb6054acae0338b968fcfa8a`、content SHA-256=`17b06f7a4be07c04ae12bc78d183c6840a2967cebedabb9556dc4eb8e147dec5`、plan id=`mops-statement-universe-2026q2-17b06f7a4be07c04`；綁定同一份官方 companies.csv SHA-256=`a0d2e22ffab71b5c8ec9dbc2f783605557ef562e110ff43fca539a19c4006d41`。完整分母為 eligible=`1,974`、verified completed=`197`、deferred unresolved=`1`（`1780:tpex`）、total unfinished=`1,777`、remaining selectable=`1,776`；下一自動 queue 為 `3531、3537、3540、3541、3546、3548、3551、3552`。1780 仍在完整 deferred／未完成分母，沒有因 caller exclusion 從欠帳消失。

本片 handoff `quarterly/r54-quarterly-recovery-handoff-r1.json` 為合法 JSON，SHA-256=`93e2405b60bd1d6055237a4741c2249dfd92570e84244859ea41618de19d05d7`，含 `500` 個直接 path/hash references；重算結果為 `missing=0、mismatch=0、self_reference=false`，JSON 以真正 newline 結尾，沒有 literal `\\n` 額外資料。handoff 保存 r53 previous handoff、r54 capture、主批／repair manifest、3526 partial／診斷／repair input、全部八家 child、隔離 DB／marker、首次／重跑 receipt、summary 與 plan；r54 內容均 `research_only=true`、`formal_db_written=false`、`raw_data_modified=false`。

後續可用既有 CLI 以 batch manifest 自動展開成功 child candidate，不需手填公司路徑。以下命令在 repo 根目錄執行，`$Batches` 只引用本片兩個 immutable batch manifest，候選清單由 `child_runs.status=succeeded` 機器產生；需將 `$ReplayDb`／`$ReplayEvidence` 設為新的 research output 路徑以保留 create-only 證據：

```powershell
$Q = (Resolve-Path 'output/v4_data_recovery_2026-09-07/quarterly').Path
$Batches = @(
  (Join-Path $Q 'v4-quarterly-batch-2026q2-r54-next8-approved-r1-manifest.json'),
  (Join-Path $Q 'v4-quarterly-batch-2026q2-r54-repair-3526-encoding-r1-manifest.json')
)
$Candidates = @(
  foreach ($BatchPath in $Batches) {
    $Batch = Get-Content -Raw -LiteralPath $BatchPath | ConvertFrom-Json
    foreach ($Child in $Batch.child_runs) {
      if ($Child.status -eq 'succeeded') { [string]$Child.candidate }
    }
  }
)
$ReplayDb = Join-Path $Q 'consumer-r54-replay-example.db'
$ReplayEvidence = Join-Path $Q 'r54-replay-example.json'
$Args = @('scripts/materialize_mops_statement_candidates.py', '--db-path', $ReplayDb)
foreach ($Candidate in $Candidates) { $Args += @('--candidate', $Candidate) }
foreach ($DecisionDate in @('2026-09-07', '2026-09-08', '2026-09-09')) { $Args += @('--decision-date', $DecisionDate) }
$Args += @('--evidence-output', $ReplayEvidence)
& .\.venv\Scripts\python.exe @Args
```

定向回歸為 `107 passed、1 skipped`（2.90 秒）；skip 為既有平台 alias 限制，沒有計入成功，另有既存 `.pytest_cache` 權限 warning。r54 變更／入口腳本 `py_compile` 通過。以上只證明本片 8 家的官方 response、row code、period／unit、隔離入庫、冪等與 cutoff；不能把 verified=`197/1,974`、1,045 rows 或本片 handoff 宣稱為全市場恢復。後續沿 r54 plan 每批最多 8 家，成功 raw reuse、來源級 circuit、immutable resume 與 publication／numeric availability 分離繼續；1780 及其他 `1,776` selectable keys 仍待處理。

### r54 consumer 主路徑接線補充：batch manifest 自動收集、完整 scope receipt 與冪等 readback

已將既有 `scripts/materialize_mops_statement_candidates.py` 的 public 入口接到 v2 batch manifest：`--batch-manifest` 可重複指定，搭配 `--period` 後由程式逐一重驗 `succeeded` child 的 candidate、child run manifest、raw／candidate／manifest SHA-256、公司／市場／期別、`run_id` 與 `report_basis`，再交給既有隔離 materializer。`pending`、`running`、`failed`、`integrity_error` child 不進入 consumer；原批次 manifest 不被改寫，並在本次 receipt 留下完整未完成 scope。未知 `report_basis` 不再默認為 `consolidated`；只有候選 `source_version` 含單一可辨識 `consolidated`／`individual` token 時才允許 legacy 缺欄相容，否則在建立 DB 前拒絕。

從 repo 根目錄可用以下單一命令重跑 r54，不需代理逐家公司展開 candidate 路徑；兩份 manifest 的成功 child 會自動合併，3526 主批失敗 child 與其 immutable repair 會同時保留在 receipt 的成功／未完成 scope：

```powershell
.\.venv\Scripts\python.exe scripts/materialize_mops_statement_candidates.py `
  --batch-manifest output/v4_data_recovery_2026-09-07/quarterly/v4-quarterly-batch-2026q2-r54-next8-approved-r1-manifest.json `
  --batch-manifest output/v4_data_recovery_2026-09-07/quarterly/v4-quarterly-batch-2026q2-r54-repair-3526-encoding-r1-manifest.json `
  --period 2026-Q2 `
  --db-path output/v4_data_recovery_2026-09-07/quarterly/consumer-r54-batch-cli-r2.db `
  --decision-date 2026-09-07 `
  --decision-date 2026-09-08 `
  --decision-date 2026-09-09 `
  --evidence-output output/v4_data_recovery_2026-09-07/quarterly/r54-batch-cli-materialization-r2.json
```

本次實際首次執行 evidence `quarterly/r54-batch-cli-materialization-r2.json` SHA-256=`878a8aa23a14c1994be23ba7d9c152cfa6eb32171fa2b86d4eb4c560c31a027c`，自動收集 `8` 個 succeeded child（7 個主批成功加 3526 repair），並保存主批 `1` 個 failed child（3526 strict Big5/HKSCS failure）。兩份來源 batch manifest SHA-256 分別為主批 `8a1f9e2fd7a3c3f9a338dbc7fe7828edba1813a9b041c979e7b770f3ce0585ab`、repair `0077796aa9a095d594ee56802eff200baf05a3842a2d4c2564f9c30802d83824`；receipt 的 `input／unique／materialized／sidecar` 均為 `1,045`，`inserted=1,045`、`idempotent_existing=0`，批次 scope 為 `succeeded=8`、`incomplete=1`。provider date-only readback 為 `2026-09-07=0、2026-09-08=0、2026-09-09=1,045`。

同一命令以新的 create-only evidence `quarterly/r54-batch-cli-materialization-r2-retry.json` 重跑，receipt SHA-256=`e3e986e81edd81f91f7362947346839ce0e72b05d075886d708eca4fb173a5b0`，結果為 `inserted=0`、`idempotent_existing=1,045`、materialized／sidecar 仍各 `1,045`，cutoff readback 不變。隔離 DB `quarterly/consumer-r54-batch-cli-r2.db` SHA-256=`b4a8b5e3071316030ca8258d23f426cfead933b02699b6a21908759926994e9f`，marker SHA-256=`303f2da6dd5663493db51d0c0ba94ee14026b6bcf86393c2e4cdc888fb07a1d8`；以明確關閉的 SQLite connection 執行 `PRAGMA quick_check=ok`，主表／sidecar 各 `1,045`。本次 receipt 與 DB 均為 research-only，`formal_db_written=false`、`raw_data_modified=false`，沒有寫入 D 槽、正式 SQLite 或既有 raw。

新增接線、報表範圍與 batch lineage 負例後，相關回歸為 `111 passed、1 skipped`；skip 是既有平台 alias 限制，沒有計入成功，另有既存 `.pytest_cache` 權限 warning。`py_compile` 與 `mypy`（materializer、candidate adapter）均通過。已接受的 r54 immutable handoff 未覆寫；本補充只新增兩份隔離 consumer receipt、隔離 DB／marker 與 QA 內容，r54 的 `1,974` eligible 分母及未完成 child 分母維持原值。

### r51–r54 單一 research consumer 整合：27 家／3,564 rows

本片重用已驗收的 r51、r52、r53、r54 immutable batch manifest，透過同一個 `--batch-manifest` 可重複入口自動展開 `status=succeeded` child；沒有重新抓官方來源，也沒有改寫 candidate、raw、既有 handoff 或 D 槽。整合輸入為下列 10 份 batch manifest（r51：3 份、r52：3 份、r53：2 份、r54：2 份）：

- `quarterly/v4-quarterly-batch-2026q2-r51-common-gap-approved-3264-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r51-common-gap-approved-3354-3372-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r51-common-gap-approved-3372-individual-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r52-next8-approved-r1-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r52-repair-3467-individual-r1-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r52-repair-3479-rowcode-r1-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r53-next8-approved-r1-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r53-repair-3499-encoding-r1-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r54-next8-approved-r1-manifest.json`
- `quarterly/v4-quarterly-batch-2026q2-r54-repair-3526-encoding-r1-manifest.json`

可在 repo 根目錄以單一 Python invocation 重跑；每次請指定新的 research-only DB／evidence 路徑，讓 receipt 維持 create-only：

```powershell
$Q = 'output/v4_data_recovery_2026-09-07/quarterly'
$BatchManifests = @(
  "$Q/v4-quarterly-batch-2026q2-r51-common-gap-approved-3264-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r51-common-gap-approved-3354-3372-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r51-common-gap-approved-3372-individual-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r52-next8-approved-r1-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r52-repair-3467-individual-r1-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r52-repair-3479-rowcode-r1-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r53-next8-approved-r1-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r53-repair-3499-encoding-r1-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r54-next8-approved-r1-manifest.json",
  "$Q/v4-quarterly-batch-2026q2-r54-repair-3526-encoding-r1-manifest.json"
)
$Args = @('scripts/materialize_mops_statement_candidates.py', '--period', '2026-Q2', '--db-path', "$Q/consumer-r51-r54-integrated-example.db")
foreach ($BatchManifest in $BatchManifests) { $Args += @('--batch-manifest', $BatchManifest) }
foreach ($DecisionDate in @('2026-09-07', '2026-09-08', '2026-09-09')) { $Args += @('--decision-date', $DecisionDate) }
$Args += @('--evidence-output', "$Q/r51-r54-integrated-example.json")
& .\.venv\Scripts\python.exe @Args
```

本次實際首次／重跑產物如下：

- `quarterly/r51-r54-integrated-consumer-summary-r1.json` 為既有 summary CLI 產物，SHA-256=`58dd5867f3fddc01c5999c8345e3a12793125e6d9ba05ced0c433b90c9490f55`；schema=`v4-quarterly-mops-consumer-batch-summary.v1`、`research_only=true`、`formal_db_written=false`、`raw_data_modified=false`，綁定 10 份 batch manifest、27 個成功 child、5 個未完成 child 與兩次 materialization receipt。
- 首次 receipt `quarterly/r51-r54-integrated-materialization-first.json`：SHA-256=`da74e5a3431c49708a8e438842a1c8f289a0ba7e099894036fd3449baba57b9e`，`input=3,564、unique=3,564、duplicate=0、inserted=3,564、existing=0`。
- 重跑 receipt `quarterly/r51-r54-integrated-materialization-retry.json`：SHA-256=`619af3f2734bdf4a80d4c90f02201ef13d77c792e12d0ecdda388b0f4850974e`，`input=3,564、unique=3,564、duplicate=0、inserted=0、existing=3,564`；重跑沒有增加資料或覆寫既有 revision。
- 隔離 DB `quarterly/consumer-r51-r54-integrated-r1.db` SHA-256=`e0cf02894344e69aefe1d4298a31ce0983fd05c0f23dcf98953bcdeb176064fa`，research-only marker SHA-256=`ebe3bb30c959e849210c9831aa87883e42a112012c2f86049b4e162b4e9210b3`；`PRAGMA quick_check=ok`，主表／sidecar 各 `3,564`。
- provider date-only readback 為 `2026-09-08=0、2026-09-09=3,564`，遵循 `next_taipei_calendar_day` policy；公告／numeric capture 時間仍分開保存，沒有把整合日回填成歷史首次公告可用日。

整個 `output/v4_data_recovery_2026-09-07/quarterly` 目錄在本次驗證時為 `640,495,987` bytes（`610.82 MiB`），低於本片 `1 GiB` research output 上限；沒有接觸 D 槽的 `200 GiB` 保留空間設定。

實際成功 scope 為 `27` 家（r51 `369`、r52 `1,027`、r53 `1,123`、r54 `1,045` rows），report basis 由 sidecar／provider 讀回為 `consolidated=3,352`、`individual=212`。period basis 也逐列保留：`consolidated` 下 `period_end_snapshot=1,216、quarter_single=795、year_to_date=1,341`；`individual` 下分別為 `83、45、84`。EPS consumer 仍以 `TWD_per_share`、scale `100` 讀取，未把 cents/share 當作元／股。

跨批次檢查以完整 source identity 驗證，`(stock_code, statement_type, period, item_code, materialized_source_version)` 沒有重複鍵；`3479 / income_statement / 2026-Q2 / item_code=4600` 的兩個內容 hash（`b61548e…` 與 `ed2ce79…`）均保留，數值相同但 row label／content lineage 不同，沒有由 hash 排序或重跑順序任選覆蓋。此類同 code 多 revision／語意差異仍須下游依既有 ambiguity policy 處理，不能直接宣稱可合併。

未完成 scope 共 5 家，仍在 receipt／summary 中，沒有從全局欠帳刪除：`3372`、`3467` 為 balance sheet official title 不符；`3479` 舊 child 為 income row code 不唯一，但 row-code repair 已以新 immutable child 成功納入；`3499`、`3526` 舊 child 為 strict Big5/HKSCS 解碼失敗，兩者各以 immutable encoding repair child 納入。這些歷史 failure scope 供後續 audit／supersedes 追蹤，成功 repair 不會抹除原始失敗證據。

本片交付後定向回歸為 `113 passed、1 skipped`（3.06 秒）；skip 是平台 alias 限制，未計為通過，另有既存 `.pytest_cache` 權限 warning。`py_compile` 與 `mypy`（batch materializer、candidate adapter）均成功。本片只完成 27 家 bounded research consumer 整合，不代表全市場或正式 D 資料庫已恢復；其餘 universe 分母與 unresolved scope 沿既有 plan 保留。

### r55：197 家 Q2 research consumer 接線與 FundamentalFactorService readback（2026-09-07）

本節驗證既有 `consumer-universe-197-r1.db` 是否能由公開的 `FundamentalFactorService.build_snapshot()` 讀取並產生季度 statement factors；scope 固定為 preflight 的 `197` 家已完成公司，不向剩餘 `1,777` 家擴張，也沒有把 research DB 指到正式資料設定。service 以顯式 `db_file` 注入隔離 DB，`TWStockConfig`／`DATA_ROOT` 與 D 槽正式 DB 均未修改。

研究輸入與保全狀態：

- DB：`quarterly/consumer-universe-197-r1.db`，`PRAGMA quick_check=ok`；`fundamental_statement_items=26,139`、sidecar `mops_statement_consumer_metadata=26,139`、`197` distinct stocks，全部為 `2026-Q2`。
- marker：`research_only=true`、`formal_oos_allowed=false`；preflight：`formal_db_written=false`、`raw_data_modified=false`、`network_requested=false`。
- preflight 分母：eligible `1,974`、verified completed `197`、unfinished `1,777`、remaining selectable `1,776`；本次 `candidate_count=197`。
- DB SHA-256：`84890acb65d7bde8e6114805bc1299d449751444defdf5d65ac0e9e7f947c1fe`。
- preflight SHA-256：`7060f77bd8b0ee1ccc72c40efc33e494c131243614d49fed03ba96fbc9959b82`。
- first materialization receipt SHA-256：`4128a5bab1918e8593965b0cc06843d425eddd1398dad47c67ce7abbcf9c93dc`；retry receipt 為 `input=26,139、unique=26,139、duplicate=0、inserted=0、existing=26,139`。

服務層以兩個 decision date 逐一讀取 197 家，覆蓋率以 `floor(n / 197 * 10,000)` 表示 basis points：

| service factor／觀測 | 2026-09-08 | 2026-09-09 | 缺漏或判定 |
| --- | ---: | ---: | --- |
| statement rows 可見公司 | 35/197（1,776 bp） | 197/197（10,000 bp） | 其餘資料的 `available_date` 為 2026-09-09，較早 decision date 不可見 |
| `fundamental.statement.eps` | 34/197（1,725 bp） | 196/197（9,949 bp） | 2881 沒有核准的標準 EPS row-code contract |
| `fundamental.statement.gross_margin` | 34/197（1,725 bp） | 196/197（9,949 bp） | 2881 沒有可安全對應的 `Revenue`／`GrossProfit` |
| `fundamental.statement.operating_margin` | 34/197（1,725 bp） | 196/197（9,949 bp） | 2881 沒有可安全對應的 `Revenue`／`OperatingIncome` |
| `fundamental.statement.roe` | 34/197（1,725 bp） | 196/197（9,949 bp） | 2881 缺少本 factor 所需的標準 `NetIncome`／`Equity` 組合 |
| `fundamental.statement.non_operating_income_ratio` | 34/197（1,725 bp） | 196/197（9,949 bp） | 2881 缺少標準 `IncomeBeforeIncomeTax`、`OperatingIncome`、`Revenue` 組合 |
| `fundamental.statement.revenue_yoy` | 0/197（0 bp） | 0/197（0 bp） | research DB 只有 2026-Q2，沒有同 basis 的 2025-Q2；不以未來或缺失期間補算 |
| `fundamental.revenue_yoy`／其他月營收 factors | 0/197（0 bp） | 0/197（0 bp） | 隔離 DB 的 `fundamental_monthly_revenues` 為 0，service 明確回報 monthly revenue missing |
| valuation factors | 0/197（0 bp） | 0/197（0 bp） | 隔離 DB 的 `fundamental_valuation_metrics` 為 0；沒有虛構 percentile 或估值觀測 |

對應的 service diagnostics 為：2026-09-08 有 `fundamental_sqlite.statement_items_missing=162`（尚未到 available window）與 `fundamental_statement.required_item_missing=40`（35 家缺 Q2 prior-period YoY、2881 缺 5 個 base factors）；2026-09-09 前者降為 0，後者為 `202`（197 家缺 Q2 prior-period YoY、2881 缺 5 個 base factors）。兩個日期均有 `fundamental_sqlite.monthly_revenue_missing=197`。2026-09-09 另有 1 筆 `fundamental_statement.revision_ambiguous`，定位為 `3479 / income_statement / 2026-Q2 / item_code=4600` 的同 code 不同 content lineage；required 五個 factors 仍各自有可用 record，該 revision 沒有被 hash 或插入順序任選合併。

語意映射與 lineage readback：

- sidecar report basis 為 `consolidated=24,251`、`individual=1,888`；下游只接受這兩個明確 basis，未見 `report_basis_invalid` 或 `report_basis_mixed`。
- official row code 只在 exact source contract、official title、XBRL concept、statement type 與 report basis 同時吻合時映射：`9750 → EPS`、`4000 → Revenue`、`5950 → GrossProfit`、`6900 → OperatingIncome`、`7900 → IncomeBeforeIncomeTax`、`8200 → NetIncome`、`3XXX → Equity`。原始 code、source version、candidate version、lineage hash、period basis、unit、scale、公告／可用日期均隨 factor metadata 保留。
- 197 家的 26,139 rows 沒有產生 semantic mapping ambiguous／unproven、unit 或 period diagnostic；這不代表可以用名稱相似度把其他產業 row code 併入既有 contract。

代表性交叉檢查：3516 在 `decision_date=2026-09-07` 與 `2026-09-08` 均為 `records=0`，到 `2026-09-09` 才有 5 筆 statement factors，符合 `available_date=2026-09-09` 的保守 `next_taipei_calendar_day` policy。service output（均為 research degraded quality）為 EPS `0.36`、gross margin `0.2683716097751033572155241455`、operating margin `0.09112751358254507673326262473`、ROE `0.01714333795823933476670114752`、non-operating income ratio `0.03366955994718500400441567999`。以同一筆 consolidated Q2 input 重算：

```text
gross margin       = 74,391,000 / 277,194,000
operating margin   = 25,260,000 / 277,194,000
ROE                = 29,135,000 / 1,699,494,000
non-operating      = (34,593,000 - 25,260,000) / 277,194,000
```

3516 的 `9750/4000/5950/6900/7900/8200/3XXX` 分別保留官方 item title／XBRL concept；EPS unit 為 `TWD_per_share`、scale `100`，金額 unit 為 `TWD`、scale `1000`，沒有把 cents/share 或千元資料誤當成元。

2881 的 189 rows 是銀行型 layout，使用例如 `39999`（Equity）、`61000`（ProfitLossBeforeTax）、`69000`（ProfitLoss）等官方 code，但沒有本 factor contract 所需的 `9750/4000/5950/6900/7900/8200/3XXX` 完整集合；目前不能只靠相似名稱或 row code 猜測把利息收入／銀行專用科目當成一般產業的 Revenue、GrossProfit 或 OperatingIncome。因此 2881 的 5 個 factors 保持不可計算並明確回報 missing，待另立、另驗證的產業專用 semantic contract，不回填或混用不同經濟意義。

本次接線後定向回歸：`25 passed`（`tests/test_statement_semantic_mapping.py`、`tests/test_fundamental_factor_service.py`、`tests/test_fundamental_sqlite_provider.py`、`tests/test_statement_factor_pack.py`）；另完成變更 Python 檔 `py_compile` 與相關模組 `mypy`。本節只證明 197 家 research consumer 可由 public service 受 PIT／report-basis／semantic-lineage 控制地讀取，不代表正式 D 資料庫已回填，也不解除剩餘 1,777 家的 bounded recovery gate。
