# Data Update 效能基線與平行化邊界 — 2026-08-28

## 目的

這份基線先回答「慢在哪裡、哪些可以平行、哪些不能平行」，不把尚未量測的
thread 數或 worker 數直接寫進 production。所有結果都是唯讀觀測；不能因為
dashboard warm query 很快，就推論資料抓取、CSV 寫入或 SQLite sync 已經可無限制
加速。

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

artifact 暫存於 `C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_full_batch_20260828.json`，SHA-256=`5A95D9C97C92BBA22CFD9F7D7EC2510D55A15357BAD42AF719007E849469A76F`。這組結果證明全批次的主要成本目前在 raw CSV read／normalize／group，而不是 4 檔計算本身；它不是全市場計算承諾，也尚未量測 CSV serialization、backup 或 SQLite contention。

這組數字只支持「目前 query／單股計算的 warm path 很快、冷啟有固定成本」；仍不足以
批准全市場 worker 數或 broker 併發。下一步仍必須量測完整 `read → calculate → write →
aggregate → SQLite commit` 五段與取消／retry／contention，再於 isolated staging 做 bounded
worker acceptance。

## 現行寫入與平行化事實

- Broker ingestion 目前依 branch/date 順序抓取；lots 與 amount 依序請求。HTTP
  失敗才進 Selenium fallback，而 fallback 使用共用 driver，不能把同一 driver
  放進多執行緒。
- Broker CSV mutation 現在由 `BrokerBranchWriteCoordinator` 統一包住，並以
  process-local single-writer lock 序列化 daily／merged CSV 寫入與 backup；這只
  建立安全邊界，沒有偷偷開啟 fetch concurrency。
- Technical indicator batch 目前逐股計算、逐股保存，最後再整合 CSV；新的
  `qa_technical_indicator_latency.py` 明確標示 `parallelism_enabled=false`、
  `observed_worker_count=1` 與 `single_writer_required=true`，不會誤宣稱已完成
  多核心版本。
- SQLite 仍遵循 single-writer；若未來要把計算放進 process pool，worker 只能回傳
  immutable result，SQLite／整合 CSV 必須由一個受控 writer commit，且要保留取消、
  backup、hash、duplicate 與 fail-closed 邊界。

## 下一個可實作切點（尚未啟用）

1. 先把完整批次拆成 `read → calculate → write → aggregate → SQLite commit` 五段
   timing，保留每段的 row count、error、cancel 與 file hash。
2. Broker 只考慮 bounded HTTP fetch pool；每個 task 必須含 global rate-limit、retry
   budget、source/date identity，Selenium fallback 維持 serialized，結果交給上述
   single writer。
3. Technical indicators 只在 CPU／memory 基線與 worker overhead 有證據時，才以
   bounded process pool 計算；禁止把 pandas DataFrame 或 SQLite connection 共享到
   writer 以外的 process。
4. 以 synthetic staging／isolated output 做 throughput、取消、重試、重複與 crash
   recovery QA；未通過前不改 production worker 數，不碰正式 `DATA_ROOT`。

## 結論

效能不是目前 P0／Paper／Formal gate 的資料缺口，但它確實需要工程化。現在已先
把可觀測基線與 single-writer 安全護欄補上；「平行」仍是後續在量測證明後才可
opt-in 的行為，不會因半成品觀感而用高 thread 數掩蓋 rate-limit 或寫入一致性問題。
