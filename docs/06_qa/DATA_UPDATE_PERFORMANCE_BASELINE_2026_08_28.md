# Data Update 效能基線與平行化邊界 — 2026-08-28

## 目的

這份基線先回答「慢在哪裡、哪些可以平行、哪些不能平行」，不把尚未量測的
thread 數或 worker 數直接寫進 production。除另行標示的 isolated staging write
probe 外，其餘結果都是唯讀觀測；不能因為
dashboard warm query 很快，就推論資料抓取、CSV 寫入或 SQLite sync 已經可無限制
加速。
staging probe 也不會把任何 writer 結果寫回 production。

## 目前實測

在目前正式資料庫（`D:\Min\Python\Project\FA_Data\sqlite\twstock.db`）以
`scripts\qa_broker_flow_dashboard_latency.py --period week --runs 3` 量測：

| Stage | cold | warm p95 | 結果 |
|---|---:|---:|---|
| Broker dashboard（含 semantics） | 2452.209 ms | 0.153 ms | pass；冷啟主要是首次 SQLite／semantic setup，不是可直接平行化證據 |
| Broker dashboard（source-only diagnostic） | 438.582 ms | 0.193 ms | diagnostic-only |
| 單股 branch detail | 20.613 ms | 19.387 ms | pass |
| branch tracker | 17.950 ms | 16.582 ms | pass |

SQLite shape probe（2026-08-28 06:38 UTC host rerun）觀察到 `broker_flows` 約 966,616 rows、212 個交易日、51 個
分點、2,189 個標的；probe 前後 DB SHA-256 相同，未寫入資料庫。

技術指標 probe 的重現方式（只讀指定單股 CSV，不呼叫 writer）：

```powershell
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_latency.py `
  --technical-dir D:\Min\Python\Project\FA_Data\technical_analysis `
  --stocks 0050 2330 3008 --rows 500 --runs 3
```

以現有檔案尾端最多 500 rows、每檔 3 runs 觀察到 `calculate_all_indicators`
的 cold 約 3.36–5.06 ms、warm p95 約 3.08–3.42 ms，CSV read 約 4.85–8.99 ms。
這不是全市場更新承諾：完整批次還包含
CSV 讀取、每股 merge／寫入、全市場 concat、backup 與可選 SQLite rebuild。

### 2026-08-28 08:33 UTC host rerun（本輪觀測）

本輪以 4 檔明確指定 CSV（`2330`、`2317`、`2454`、`0050`）、尾端 120 rows、2 runs
重跑技術指標唯讀 probe：CSV read=`3.12–22.08 ms`、計算 cold=`2.98–4.82 ms`、
warm p95=`2.76–3.07 ms`；每檔輸入／輸出均為 120 rows，`write_attempted=false`、
`parallelism_enabled=false`、`observed_worker_count=1`。

同時以 `qa_broker_flow_dashboard_latency.py --period week --runs 2` 重跑正式 SQLite
唯讀 dashboard：含 semantics cold=`2176.638 ms`、warm p95=`0.207 ms`，source-only
diagnostic cold=`429.314 ms`、warm p95=`0.167 ms`；單股 branch detail warm p95=`13.825 ms`、
branch tracker warm p95=`11.284 ms`，各自 gate=`pass`。Probe 前後資料庫 SHA-256 均為
`3a5e791dd8f5e0b4cab338abff65d34d442d2ce5b1ceade2385e25b347cd1f61`，確認未寫入正式 DB。
原始 JSON 證據留在 OS TEMP：`technical_latency_20260828.json`（SHA-256=`188D47C63D8EF16C4B14BC51B4D9198E25C8B15EC90DE38F55E8650C2B46A0B5`）與
`broker_flow_latency_20260828.json`（SHA-256=`1EB08E31B5321B3AA5F60F5595ADF1CE56D9F3EDEACE21B0B1E2D315EE2E2807`）。

### 2026-08-28 09:08 UTC full-batch read-only probe（本輪新增）

新增 `scripts\qa_technical_indicator_full_batch.py`，以明確指定的 raw stock CSV
執行記憶體內 `read → normalize/group → calculate → aggregate`；它保留 `0050` 等
前導零代號，不呼叫單股 writer，不建立 backup、不寫 CSV／SQLite，且固定
`parallelism_enabled=false`、`observed_worker_count=1`、`single_writer_required=true`。
重現命令：

```powershell
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_full_batch.py `
  --stock-data-file D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv `
  --stocks 0050 2317 2330 2454 `
  --min-rows 30 --max-rows-per-stock 120 --runs 1 `
  --output-json <TEMP_OUTPUT>
```

本次只選 4 檔做受控計算，但完整掃過 raw CSV 的 `5,226,219` rows，量測結果為：

| Stage | ms | rows／結果 |
|---|---:|---|
| CSV read | `8,301.849` | raw file `486,228,553` bytes |
| normalize | `2,237.654` | normalized `5,226,219` rows |
| group | `1,383.154` | `2,198` groups，選取 `4` |
| calculate | `27.001` | `4/4` stocks、`480` rows |
| aggregate | `0.372` | `480` rows、35 columns |
| total | `11,950.456` | `write_attempted=false`、`sqlite_write_attempted=false` |

artifact 暫存於 `C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_full_batch_20260828.json`，SHA-256=`5A95D9C97C92BBA22CFD9F7D7EC2510D55A15357BAD42AF719007E849469A76F`。這組結果證明全批次的主要成本目前在 raw CSV read／normalize／group，而不是 4 檔計算本身；它不是全市場計算承諾，也不涵蓋後續 CSV serialization、backup 或 SQLite contention 的 writer 證據。

這組數字只支持「目前 query／單股計算的 warm path 很快、冷啟有固定成本」；後續
isolated staging 已補上 CSV／SQLite writer 與 lock retry 觀測，但仍不足以批准全市場
worker 數或 broker 併發。下一步是把 backup、取消／retry／crash recovery 與 bounded
worker acceptance 補成可重現的完整測試。

### 2026-08-28 09:19 UTC isolated staging write probe（本輪新增）

新增 `scripts\qa_technical_indicator_write_probe.py`。它要求明確的既有
`--staging-root`、至少一個 `--protected-root` 與
`--confirm-write-probe`；未確認時不建立檔案，staging root 若位於 protected
root 內則直接拒絕。確認後只在 ephemeral staging 子目錄寫入逐股 CSV、合併 CSV
與 SQLite，離開 probe 即清除；正式 raw CSV 只讀取並以前後 SHA-256 驗證未變更。
SQLite writer 使用既有 `DBManager` schema／write path，另以兩個 staging
connection 實測 `BEGIN IMMEDIATE` contention，holder 釋放後再驗證 serialized
retry。重現命令：

```powershell
New-Item -ItemType Directory -Path C:\Users\archi\AppData\Local\Temp\technical_analysis_write_probe_stage -Force
.\.venv\Scripts\python.exe scripts\qa_technical_indicator_write_probe.py `
  --stock-data-file D:\Min\Python\Project\FA_Data\meta_data\stock_data_whole.csv `
  --staging-root C:\Users\archi\AppData\Local\Temp\technical_analysis_write_probe_stage `
  --protected-root D:\Min\Python\Project\FA_Data `
  --protected-root D:\Min\Python\Project\FA_Data\output `
  --confirm-write-probe --stocks 0050 2330 --min-rows 30 --max-rows-per-stock 120 `
  --output-json C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_write_20260828.json
```

本次 2 檔、每檔 120 rows 的受控結果為：

| Stage | ms | rows／結果 |
|---|---:|---|
| CSV read | `8,165.166` | raw `5,226,219` rows、`486,228,553` bytes |
| calculate | `12.002` | `2/2` stocks、`240` rows |
| per-stock CSV serialization | `20.934` | 2 files、共 `99,297` bytes |
| aggregate CSV write | `3.817` | `240` rows、35 columns |
| SQLite schema | `5.570` | staging `technical_indicators` schema |
| SQLite write／commit | `11.735` | `240` rows，`write_ok=true` |
| single-writer contention | `5.151` | `database is locked`，contention observed |
| serialized retry | `0.347` | retry succeeded，probe rows=`2` |
| total | `11,963.428` | cleanup succeeded、input hash unchanged |

artifact 暫存於 `C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_write_20260828.json`，SHA-256=`90EA5379C8D59E248B05C0F80C34CCD9617F04636D368ECAC392E6840005B1EF`。這證明 CSV／SQLite 寫入可以在隔離環境由單一 writer 完成，且 SQLite 在第二個 writer 進入時確實會以 lock 拒絕；它不代表 production writer 已改造，也不授權提高 worker 數。ephemeral CSV／SQLite 在 probe 結束後已清除，artifact 內的 staging 檔案路徑僅供當次追溯。

### 2026-08-28 09:42 UTC real indicator process-pool staging probe（本輪新增）

新增 `scripts\qa_technical_indicator_process_pool.py`，在明確確認與 protected-root
護欄下，從同一份 raw CSV 選取 `0050`／`2330` 各最多 120 rows，使用真正的
`TechnicalIndicatorCalculator` 交給 bounded `ProcessPoolExecutor(max_workers=2,
max_in_flight=4)`；worker 只回傳 DataFrame，逐股與 aggregate CSV 由父程序寫入
ephemeral staging。`0050` 注入一次 transient failure，驗證有限 retry；沒有 SQLite
connection、正式 CSV 或正式 worker 被傳入子程序。

實測結果：raw `5,226,219` rows／`486,228,553` bytes，兩個 worker PID 均被觀察到，
`max_observed_in_flight=2`、retry=`1`、dispatch=`1,423.558 ms`、父程序逐股 CSV
serialization=`22.495 ms`、aggregate CSV=`3.366 ms`、total=`13,233.054 ms`；
2/2 stocks、240 calculated rows、5/5 checks 通過，staging cleanup 與 input hash
均通過。artifact 暫存於
`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_process_pool_20260828.json`，
SHA-256=`C662A26E0937363547022FEB30ADAFD0185875AFBBDD7A3FD08AEF9323765FFF`。

這是「真實 calculator＋bounded process pool＋parent single writer」的 staging 證據，
不是 production 啟用證明；`production_worker_enabled=false`、`production_write_attempted=false`、
`production_sqlite_write_attempted=false`。本節本身不涵蓋 worker crash recovery、長時間取消
與正式 single-writer integration，也不能替代 broker HTTP rate-limit／retry acceptance。

### 2026-08-28 10:15 UTC real worker recovery／cancellation acceptance（本輪新增）

新增 `scripts\qa_technical_indicator_worker_recovery.py`。它先以同一份受控 raw
CSV 跑 real `TechnicalIndicatorCalculator` bounded process pool，再在隔離 staging
故意讓一個 worker process 結束，確認 `BrokenProcessPool` 後重建 executor 能完成
下一個 120-row 計算；另以單 worker、8 個延遲 task 驗證取消時至少 6 個 queued task
被取消，2 個已開始但取消後完成的結果被丟棄。worker 沒有 writer／SQLite handle；
parent writer integration 只寫入 ephemeral
staging，不把 production worker 開啟。

實測使用 `all_stocks_data_top10.csv` 的 `2330`／`2308` 兩組、
`max_workers=2`、`max_in_flight=2`、`max_retries=1`；real calculator 2/2 groups、
crash recovery=`measured`（`BrokenProcessPool` → recovery `120` rows）、cancellation
=`measured`（6 cancelled／2 discarded），所有 combined checks 通過。artifact 暫存於
`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_worker_recovery_20260828.json`，
SHA-256=`983FDEB4C1829137857F49513463BA48579910BF5A3882B73260F096F0454A8D`。

這只補足 staging 的 recovery／取消前置條件；本輪再把同一批 real calculator
結果接到既有 parent CSV／`DBManager.write_dataframe`，並在 ephemeral SQLite
實測 lock／retry。`production_single_writer_integration` 現為
`staging_measured`（scope=`isolated_staging`），不是 production 啟用證明；因此
readiness 仍保留 production single-writer blocker，technical worker 仍維持關閉。

### 2026-08-28 10:28 UTC parent single-writer integration staging（本輪新增）

同一個 `qa_technical_indicator_worker_recovery.py` 現在會在 recovery／cancellation
通過後，使用 2 個 real calculator worker、`max_in_flight=2`，由父程序依序寫入
2 份逐股 CSV、1 份 aggregate CSV，再透過正式 `DBManager.write_dataframe`
寫入 ephemeral `technical_indicators.sqlite`。240 rows 寫入成功，SQLite
`database is locked` contention 被觀察到，holder 釋放後 retry 成功；worker
write attempts=`0`、production CSV／SQLite write=`false`、staging cleanup 與
raw input hash 均通過。

artifact 暫存於
`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_worker_recovery_20260828.json`，
SHA-256=`983FDEB4C1829137857F49513463BA48579910BF5A3882B73260F096F0454A8D`。
這讓 production integration 的剩餘工作縮小為：在正式環境由 owner 核准 rollback、
backup 與小範圍 canary；程式端的 technical batch feature flag／scheduler lifecycle
已接上，但預設仍為關閉，`staging_measured` 不會自動升格成 production。

### 2026-08-28 11:00 UTC production batch feature-flag wiring（本輪新增）

`UpdateService.calculate_technical_indicators` 現在可由明確的
`technical_process_pool_enabled`／`--enable-technical-process-pool` opt-in。父程序先
完成股票分組、日期與 incremental warm-up 判斷，再把準備好的 frame 送入 bounded
`ProcessPoolExecutor`；worker 只回傳 DataFrame，逐股 CSV、aggregate CSV 與 SQLite
仍由父程序既有 writer 完成。worker exception、pool restart、有限 retry、取消與父程序
寫入數會保存於 step result；不會自動 fallback 到第二套計算或把 partial 結果標為完整。

`TWStockConfig` 的預設為 `enabled=false`、`workers=2`、`max_in_flight=4`、
`max_retries=1`。排程 wrapper 預設不傳 enable 旗標；只有受控 canary 才能在單次
run 明確傳入，running／terminal status 會同時記錄參數。這一批只證明程式邊界已接上，
不代表正式 host ACL、backup／rollback 或來源端效能 canary 已完成。

### 2026-08-28 09:50 UTC broker bounded fetch acceptance probe（本輪新增）

新增 `scripts\qa_broker_bounded_fetch_acceptance.py`。它以完全離線的 deterministic
transport 呼叫既有 `BrokerBranchUpdateService._fetch_metric_records_http` 與 MoneyDJ
HTML parser，再由 bounded `ThreadPoolExecutor(max_workers=2,max_in_flight=4)` 模擬
HTTP I/O；父程序才寫入 ephemeral staging CSV。9 個 task submission（含 1 個 duplicate）、
1 個 transient failure、1 個預期 permanent failure，另以 global rate limiter 控制每次
transport call 間隔；Selenium fallback 不啟動且保持 serialized policy。

實測結果：`max_observed_in_flight=4`、2 個 worker thread、10 次 transport call、
最小開始間隔=`5.114 ms`（要求 5 ms）、retry=`1`、duplicate suppression=`1`、
預期 permanent failure 未寫入，7 筆 record 由父程序寫 staging CSV；10/10 checks
通過，fetch dispatch=`111.723 ms`、parent CSV=`4.337 ms`、total=`117.348 ms`。
artifact 暫存於
`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\broker_bounded_fetch_20260828.json`，
SHA-256=`A3B203805559AF5B136441EBB6D31290F9ACACFA32E0533B7C91C29CE5AAE4B7`。

這是「現有 parser／fetch method＋離線 bounded transport」的工程契約證據，不是
MoneyDJ 真實連線品質或授權證明；`network_enabled=false`、`production_fetch_pool_enabled=false`、
`production_write_attempted=false`。正式 HTTP canary、真實 rate-limit、Selenium driver
重建／fallback QA 與 production writer integration 仍需另外取得 owner／環境允許後驗收。

### 2026-08-28 09:30 UTC bounded worker contract probe（本輪新增）

新增 `scripts\qa_bounded_worker_acceptance.py`，以 deterministic synthetic tasks 驗證
technical compute-only worker 應遵守的 bounded orchestration：`max_workers=2`、
`max_in_flight=4`、transient failure 最多 1 次 retry、permanent failure 不寫入、
重複 task 只提交一次 commit、取消後 pending work 會被取消，且 worker 不直接擁有
writer。這是設計契約驗收，不是 production process pool，也不讀／寫正式資料。

```powershell
.\.venv\Scripts\python.exe scripts\qa_bounded_worker_acceptance.py `
  --workers 2 --max-in-flight 4 --max-retries 1 --cancel-after 3 `
  --output-json C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\bounded_worker_acceptance_20260828.json
```

結果為 `status=measured`，8/8 checks 通過：full completion 的 retry=`1`、
permanent failure 未寫入、duplicate input `task-normal-3` 僅保留 1 次 commit；
cooperative cancellation 在 committed 3 筆後停止新提交，取消 3 個 pending task、
丟棄 2 個取消後才完成的結果；兩組的 `max_observed_in_flight=4`、
`worker_write_attempts=0`，writer owner 都是主執行緒。artifact 暫存於
`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\bounded_worker_acceptance_20260828.json`，
SHA-256=`107DC6DD7391A2AF20D070BC7CCC040BB00041499A1B77319AC788BCC0BCF9DC`。
它只證明 technical worker 的 queue／cancel／retry／single-writer 介面可驗收；真實
indicator process-pool throughput 已由上一節補上，crash recovery 或 broker HTTP
rate-limit 仍未完成，因此 production worker 仍維持關閉。

## 現行寫入與平行化事實

- Broker production ingestion 目前仍依 branch/date 順序抓取；lots 與 amount 依序請求。
  HTTP 失敗才進 Selenium fallback，而 fallback 使用共用 driver，不能把同一 driver
  放進多執行緒。上一節的離線 acceptance 已先證明現有 HTTP parser 可放入 bounded
  fetch orchestration，但沒有把 production 網路／driver 打開。
- Broker CSV mutation 現在由 `BrokerBranchWriteCoordinator` 統一包住，並以
  process-local single-writer lock 序列化 daily／merged CSV 寫入與 backup；這只
  建立安全邊界，沒有偷偷開啟 fetch concurrency。
- Technical indicator production batch 預設仍逐股計算、逐股保存，最後再整合 CSV；
  `technical_process_pool_enabled=false` 時維持這條既有路徑。明確 opt-in 後才使用
  bounded compute-only workers，`parallelism_enabled`／worker PID／retry／cancel 與
  parent single-writer summary 會寫入該次 step result；尚未完成 canary 前排程不傳旗標。
- SQLite 仍遵循 single-writer；若未來要把計算放進 process pool，worker 只能回傳
  immutable result，SQLite／整合 CSV 必須由一個受控 writer commit，且要保留取消、
  backup、hash、duplicate 與 fail-closed 邊界。

## 下一個可實作切點（尚未啟用）

1. production batch 的 feature flag／scheduler lifecycle 已接上；下一步由 owner 在
   正式環境核准 backup／rollback 並做小範圍 canary，保留每段 row count、error、cancel、
   file hash 與 rollback，完成前不把排程預設改為 enabled。
2. Broker 只在 owner／環境允許的真實 canary 中考慮 bounded HTTP fetch pool；每個 task
   必須含 global rate-limit、retry budget、source/date identity，Selenium fallback 維持
   serialized，結果交給上述 single writer。離線 parser／queue acceptance 已完成，
   不得把它當成真實來源成功。
3. Technical indicators 維持 worker 只回傳 immutable result、CSV／SQLite 由單一
   writer commit；禁止把 SQLite connection 共享到 writer 以外的 process。
4. 以 synthetic staging／isolated output 做 throughput、取消、重試、重複與 crash
   recovery QA；未通過前不改 production worker 數，不碰正式 `DATA_ROOT`。

## 結論

效能不是目前 P0／Paper／Formal gate 的資料缺口，但它確實需要工程化。現在已先
把可觀測基線與 single-writer 安全護欄補上；「平行」仍是後續在量測證明後才可
opt-in 的行為，不會因半成品觀感而用高 thread 數掩蓋 rate-limit 或寫入一致性問題。
