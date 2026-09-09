# V4 Direct → OOC → Release 資料鏈交接

> 文件狀態：Direct capacity-gate handoff 快照（2026-09-08，America/Los_Angeles）
>
> 本文件只涵蓋 Direct／OOC／release 的資料工程與驗收邊界。模型訓練、投資成效與正式交易不是同一個完成狀態。

## 1. 目前結論

| 層級 | 狀態 | 可追溯證據／限制 |
|---|---|---|
| 資料建置（Direct） | capacity gate 暫停 | 新 namespace 已封存並驗證 2014–2020；2021 assembly 兩次在 required free 以下，已清理未封存 workspace；2021–2026 尚待處理。 |
| 模型訓練（OOC） | 尚未開始 | 本任務明確不跑新 fit、不暴露 fold-006+、不做 promotion。 |
| 投資成效／正式 release | 尚未成立 | 尚無合格 teacher；formal OOS、alpha、券商交易仍關閉。 |
| 專案範圍 | 已隔離 | 未新增 branch/worktree；未修改 Exit、Health、更新器、UI、raw 或舊 numeric root；未啟動 OOC／fit。 |

這不是重抓 2014 行情。Direct 讀取既有年度 PIT raw shards，逐年產出可分批讀取的數值特徵、標籤、索引、replay source、carry state 與 checkpoint；2014 是歷史建置順序，不代表行情或資料只到 2014。

## 2. Source、版本與 namespace

本輪使用的 Direct root 是：

`D:/Min/Python/Project/FA_Data/output/release_v4/portfolio_ml_direct_numeric_production_v4_v2-source-rebuild-79dccf8b7f0b`

舊 root `D:/Min/Python/Project/FA_Data/output/release_v4/portfolio_ml_direct_numeric_production_v4_v2` 與 `ml_pit_year_shards` 均保留，沒有用舊 numeric outputs、舊 labels 或舊 carry state 混接。

| 項目 | 值 |
|---|---|
| raw manifest | `D:/Min/Python/Project/FA_Data/output/release_v4/ml_pit_year_shards/runs/pit-6874d65ee70d4f84cf41f5d1/all_field_enriched/manifest.json` |
| raw canonical content hash | `sha256:d55879c6d4bfae7c8fbb095330b0732eb1c5c80ecd2e0a0b5b79ee617b2eddc9` |
| raw manifest file SHA-256 | `sha256:6ecc7b26040e00b5c9f70f77b22a7bc9dd976a38453a88c1d1d9865a1eb4e5bc`（與 canonical content hash 刻意分開） |
| dependency freeze | `sha256:79dccf8b7f0b30a19334c10563fc1766e9e1c15dad59c7bd22fb448dc5e60da3` |
| discovery cache | `sha256:45e30d6b6b51680541a7b2d43cf1b6f7132ea745d17758d74e7031cdd4146d00`；source content hash `sha256:57f4ae6aacfeb0c57fd0617ab19b1c3f250b14e4327a4a2783a22d828d6fc7d0`；62 features、13 個年度 shard、3,073 個 eligible dates、41 個既定 fold windows |
| training as-of | `2026-09-07T08:30:00+08:00` |
| benchmark | `TAIEX` |
| Direct scope | 2014–2026，共 13 個 raw shards；raw manifest 宣告 16,039,958 rows |
| split parameters | minimum train 252、test 63、purge 60 trading days、embargo 5 trading days |

15 項 dependency freeze 以 `output/v4_next_ml/direct_dependency_freeze_qa_20260908.json` 為準，精確檔案清單為：`data_module/portfolio_ml_direct_numeric_store.py`、`data_module/portfolio_ml_dataset_assembler.py`、`data_module/portfolio_ml_out_of_core_store.py`、`data_module/ml_storage_capacity.py`、`data_module/ml_pit_shared_block_resolver.py`、`data_module/ml_direct_shared_block_resolver.py`、`data_module/formal_portfolio_ledger.py`、`data_module/rule_champion_snapshot_service.py`、`data_module/teacher_input_source_producer.py`、`ml_module/allocation_training_service.py`、`ml_module/allocation_contracts.py`、`ml_module/allocation_teacher.py`、`ml_module/immutable_ml_block_store.py`、`ml_module/purged_walk_forward.py`、`data_module/ml_price_availability_contract.py`。其中 14 項 loaded code 與 source match，teacher input source producer 的 loaded fingerprint 為 null；launch 時使用 fresh process 驗證，未切換 branch。

### 啟動 custody

實際重新查詢到的程序不是依賴舊 status：

| PID | 建立時間（UTC） | executable | parent | 狀態 |
|---:|---|---|---:|---|
| 2220 | `2026-09-08T19:42:58.5245868Z` | `.venv\\Scripts\\python.exe` | 54028 | 原 launcher／builder command holder，已終止 |
| 23028 | `2026-09-08T19:42:58.5598952Z` | `C:\\Program Files\\Python311\\python.exe` | 2220 | 原實際 builder，因 capacity hold 已終止 |
| 39200 | `2026-09-09T00:36:55.1708533Z` | `.venv\\Scripts\\python.exe` | — | 同版本 resume launcher，已終止 |
| 44064 | `2026-09-09T00:36:55.2101724Z` | `C:\\Program Files\\Python311\\python.exe` | 39200 | 同版本 resume 實際 builder，因 capacity hold 已終止 |

launch receipt 的 `argument_vector` 已重新讀取，31 個參數與計畫完全一致；同一向量也用於 39200→44064 的 resume。`Get-Process` 已重新核實上述 PID 的 executable path／建立時間；本機 `Win32_Process.CommandLine` 查詢在目前 Windows 權限下沒有返回資料，因此不把不可讀的 WMI 欄位冒稱成 live command line，命令 custody 以 receipt／plan 的 exact vector 與實際 process path 為準：

`build_portfolio_ml_direct_numeric_store.py --raw-manifest <上述 raw manifest> --output-dir <上述新 root> --training-as-of 2026-09-07T08:30:00+08:00 --benchmark-entity TAIEX --minimum-train-dates 252 --test-date-count 63 --purge-trading-days 60 --embargo-trading-days 5 --batch-size 8192 --workers 2 --memory-budget-mb 4096 --corporate-action-manifest D:/Min/Python/Project/FA_Data/output/release_v4/official_market_events/runs/official-market-events-189a6e1401c0396ff8cd353a/manifest.json --temporary-storage-budget-bytes 42949672960 --persistent-storage-budget-bytes 37580963840 --safety-reserve-bytes 214748364800`

heartbeat path 為 `D:/Min/Python/Project/FA_Data/output/release_v4/portfolio_ml_direct_numeric_production_v4_v2-source-rebuild-79dccf8b7f0b/runs/direct-ooc-3cec102bc9f96e2219319560/heartbeat.json`；checkpoint path 為同一 run directory 下的 `checkpoint.json`。停止前最後 heartbeat（`2026-09-09T01:08:08.736426+00:00`）仍是 stale `status=running`、PID 44064、`completed_years=[2014,2015,2016,2017,2018,2019,2020]`、`current_year=2021`、stage `assembly_decision_2021-07-29_rows_180224_processed`；這不是程序仍活著的證據。最後有效 checkpoint 仍為 `year_2020_checkpoint`、`complete=false`、`peak_temporary_bytes=23,169,343,755`，capacity flags 全為 true。

Canonical OS heavy lock 仍由本次 builder 持有；owner sidecar 的 `owner_pid=23028`、`owner_released=false`，沒有擅自刪除舊 gate sidecar。launch receipt 指向 `output/v4_next_ml/direct_rebuild_launch_stdout_20260908.log` 與 `output/v4_next_ml/direct_rebuild_launch_stderr_20260908.log`，已檢查時兩者皆為 0 bytes；沒有把 timeout 或空輸出誤判成失敗。Windows event query 亦未發現本程序錯誤事件。

## 3. 容量與保留策略

| 項目 | 已宣告／觀測值 |
|---|---:|
| temporary budget | 42,949,672,960 bytes（40 GiB） |
| new persistent budget | 37,580,963,840 bytes（35 GiB） |
| safety reserve | 214,748,364,800 bytes（200 GiB） |
| Direct run root 最新可見大小 | 2,525,374,802 bytes，66 files；2014–2020 已封存，未留 2021 partial workspace |
| D: 最新 free | 318,606,434,304 bytes |
| D: required free | 295,279,001,600 bytes |
| D: margin | 23,327,432,704 bytes |
| C: 最新 free | 176,627,355,648 bytes |
| system TEMP | `C:\\Users\\archi\\AppData\\Local\\Temp`，掃描約 7,644,006,898 bytes；近啟動修改檔主要是其他 pytest 路徑，沒有證據歸因給 Direct |

Plan 的 estimated persistent upper bound 約 15,333,023,892 bytes、temporary peak 約 15,953,216,418 bytes；實際容量仍以每次觀測為準。若 D: free 低於 required free，或 lock／capacity guard 失敗，必須在可恢復 checkpoint 邊界停止；不得降低 reserve，也不得刪舊 raw／舊 root 湊空間。

### Capacity hold／resume evidence

- 原 builder PID 23028 在 `assembly_decision_2021-08-16_rows_193600_processed` 時觀測 D: free `295,229,341,696` bytes，較 required free 少 `49,659,904` bytes；已受控停止，並清理同一 run 內未 finalized 的 `.work-year-2021`（23,093,440,512 bytes）與 staging（279,970,252 bytes）。
- capacity 恢復後以同一 receipt argument vector resume；PID 39200／44064 重新通過 2014–2020 checkpoint reuse，但 PID 44064 在 `assembly_decision_2021-07-29_rows_180224_processed` 時 D: free `295,258,087,424` bytes，較 required free 少 `20,914,176` bytes；再次受控停止，並清理未 finalized 的 `.work-year-2021`（23,093,440,512 bytes）與 staging（254,891,640 bytes）。這兩次是容量安全停止，不是 builder exception；舊 launch log 與 resume stdout/stderr 均為 0 bytes，不能把空 log 當成功或失敗訊號。
- 清理後再次實測 D: free `318,606,434,304` bytes、margin `23,327,432,704` bytes，partial 目錄為 0；2014–2020 及 raw 均保留。兩次 hold 的短缺分別為 `49,659,904` 與 `20,914,176` bytes，因此最大觀測短缺是 `49,659,904` bytes（約 `47.359 MiB`），不是後一次較小值。越過上次 hold 點的最低歷史 headroom 只能以此最大短缺作下限；實務上建議至少 1 GiB 是操作緩衝，不是已證明可完成後續年度的容量保證。每個 capacity checkpoint 仍須維持 D: free `>=295,279,001,600`；不得降低 200 GiB reserve 或刪 raw／舊 root。canonical lock file 保留，owner sidecar 目前只記錄已死亡 PID 44064 的 stale owner，未手動刪除。

#### Capacity 算式與全 run headroom 下限

current guard 的固定門檻為 `40 GiB temporary + 35 GiB new persistent + 200 GiB reserve = 275 GiB`，即 required free `295,279,001,600` bytes。清理後的 D: free `318,606,434,304` bytes（`296.725364685 GiB`）因此有 `23,327,432,704` bytes（`21.725364685 GiB`）可在不低於 required free 的前提下消耗。2021 hold 期間保存的 temporary peak 為 `23,169,343,755` bytes（`21.578132878 GiB`）；當時 free 已低於 required free，兩次觀測短缺如上，故不能把一次 1 GiB 補量解讀為 2021 剩餘或 2022–2026 的完成證據。

目前 Direct root 已有 `2,525,374,802` bytes，plan persistent upper bound 為 `15,333,023,892` bytes，按已存在量估算剩餘新 persistent 為 `12,807,649,090` bytes（`11.928052725 GiB`）。若暫以已保存的 2021 temporary peak 代表後續單年 peak，並額外保留最大歷史短缺作 guard jitter 下限，從目前 margin 推得的全 run continuation lower bound 為：

```text
max(0,
  23,169,343,755 temporary_peak
  + 12,807,649,090 remaining_persistent
  + 49,659,904 max_observed_shortfall
  - 23,327,432,704 current_margin
)
= 12,699,220,045 bytes = 11.827070308 GiB additional headroom
```

若只計算 temporary peak 加剩餘 persistent，未加歷史短缺緩衝則為 `12,649,560,141` bytes（`11.780820918 GiB`）。這兩個數字都是依現有觀測與 plan 的保守下限，不是後續年度的實測峰值；2021 尚未完成，2022–2026 尚無年度 workspace／manifest 讀回，實際 resume 前仍須在同一 D root 重新做 capacity preflight、逐 checkpoint 量測 temporary／persistent bytes 與 lock。故本輪只保全並等待 root 明確核准，不盲目 resume；沒有證據顯示 Direct 使用系統 C: TEMP，不能以未證實的第三方 TEMP 使用量另造硬門檻。

## 4. 年度矩陣與 checkpoint

| 年度 | Direct 狀態 | 已知證據 |
|---:|---|---|
| 2014 | 已完成、已驗證 | `complete=true`；manifest canonical hash `sha256:01d38481cddfdb6c8020ca853001cff1173ba5e08a7130cf093098cd0d7bd938`；manifest file SHA `sha256:97a445dcdf395ba47ff84cca5f4c237d8aa212f6215b653c4e5ceb9ef95a9041`；carry hash `sha256:77fbbd905f84831b1a4908f84f7d0e6feddcfa556d5d2ac132a48ec13ca5e05e`。 |
| 2015 | 已完成、已驗證 | `complete=true`；manifest canonical hash `sha256:c0acfd410311e3f679036149d2c5a507d7d0f4d7a358e322ed4f37cfd2e4d656`；manifest file SHA `sha256:d4afc4bf4429bc1ee699242d1f629693d0e788074f7dfa22a0969e7fb1c9c731`；carry hash `sha256:42bbedf20851386dec11f5b2e9d3e8f5137ebc27df827ff0568f767483e005d9`。 |
| 2016 | 已完成、已驗證 | `complete=true`；manifest canonical hash `sha256:4be2054564c92b833c63f7a9ae7229535f712995214d1d3728a42c36beebf7a1`；manifest file SHA `sha256:ab7276df6a3ea59d4bd97271081e4ae9e63ec52b7e41ee207ee87f938635e525`；carry hash `sha256:784aeed23cf5e8fb60e8096d2c8962796601f8f895bd86b499fa15c316da7f43`。 |
| 2017 | 已完成、已驗證 | `complete=true`；manifest canonical hash `sha256:f440fd85080cb846ef14be5db6a11a8c0aa2e45070dc9f252d57343feb90a266`；manifest file SHA `sha256:84d7dea94ec1e19bd97451c07416f68974ef8efccd2d0986a51dc307002fd929`；carry hash `sha256:d5722d98be2e3c8be8fbbc2e9c6260261927f1a88d95ee2308954a5d88a31408`。 |
| 2018 | 已完成、已驗證 | `complete=true`；manifest canonical hash `sha256:4ff55e299077fcb52dc0535c32af651e6a5720e1cdc499ec05d51427066862b5`；manifest file SHA `sha256:f3a4758f31a798e5a7b874f5e07a429d268939c3dac2a826dcb1c581cbf2866f`；carry hash `sha256:49991e792436aa6a7eb476a854d05f9e8815050f7f73c5e35ebc7d61862fcf7d`。 |
| 2019 | 已完成、已驗證 | `complete=true`；manifest canonical hash `sha256:7bee2603865fb8c83be86f6dd7472d94839f3eafd7030c12dc0c318d7c4271e4`；manifest file SHA `sha256:eb028b6694feebb333a75f845d862f90eb37225ff14685a952c5160b39fe1323`；carry hash `sha256:576ba516268bb84ca21653efda30e2e6d49170d27071cf6f169ab3149671f3dd`。 |
| 2020 | 已完成、已驗證 | `complete=true`；manifest canonical hash `sha256:02840ceda1a67ee0539f3b15df7830c5731bb7554d4da42d5db10a50dd363ada`；manifest file SHA `sha256:3cd33b4c6b81cc2fec23ba5432fe1e4f338531c747f07641b2e80623edbe8e82`；carry hash `sha256:775dbfa83ab0ab6340039fa3ebd56f539bc939826c2f50ef98862b0eec2623dd`。 |
| 2021 | capacity gate 暫停 | 兩次 assembly 均在 required free 以下受控停止；無 finalized manifest，已清理 partial workspace。 |
| 2022–2026 | pending | 不把尚未產出的年度預先視為成功。 |

2014 manifest 的 row count 為 219,103、feature count 為 62。年度 artifact 已逐檔以 resolver 驗證 local bytes 與 SHA-256，包含：

- `features.values.i64`：shape `[219103, 62]`、bytes 108,675,088
- `features.masks.u8`：shape `[219103, 62]`、bytes 13,584,386
- `targets.i32`：shape `[219103, 6]`、bytes 5,258,472
- `labels.i32`：shape `[219103, 36]`、bytes 31,550,832
- `labels.masks.u8`：shape `[219103, 36]`、bytes 7,887,708
- `rows.sqlite`：bytes 76,980,224；`replay_source.sqlite`：bytes 65,515,520
- `carry.state.gz`：bytes 3,547,274

checkpoint 為 schema `portfolio-ml-direct-checkpoint.v2`，以 manifest canonical hash、manifest file hash、carry hash、raw/dependency identity 與 capacity snapshot 綁定。2014 checkpoint 當時的 capacity flags 全為 true，observed temporary 約 20,573,152,922 bytes、existing persistent 約 313,190,321 bytes。

## 5. 2014–2016 實體 consumer readback 驗收

本節是已完成年度的 evidence，不代表全年度 Direct 或 release 完成。

### Schema、型別與 mask

- `resolve_direct_year_artifact_paths` 通過 8 個 artifact 的存在、宣告 bytes、實體 bytes 與 file SHA 驗證。
- values／targets／labels 使用整數 binary：`int64`、`int32`；mask 使用 `uint8`。沒有把浮點計算引入策略／資金／風控核心。
- feature mask 語義為 `0=observed, 1=missing`；62 個 feature observed counts 與 manifest 一致。missing 總數 1,982,286，invalid mask 為 0，missing mask 下沒有非零 value。
- label mask 語義為 `0=valid, 1=missing`。benchmark downside／MAE／MFE／volatility／max drawdown／tail loss／fill feasible 的 5／10／20／60 horizon 在 2014 均為 219,103 valid；sector excess 因全數缺 sector 而保持 missing，不偽造有效 label。
- feature registry 沒有 label／target 欄位重疊；`target_available_at > decision_at` 是結果的 provenance，不是把未來結果寫進 decision feature。

### 索引、PIT 與 replay source

- `rows.sqlite` 的 `local_row_index` 為 0..219,102 且 distinct 219,103；decision timestamp 全為 `T08:30:00+08:00`，日期為 2014-01-03 至 2014-12-31；同一 decision_date/symbol 無重複。
- 每列 `target_available_at` 均在 decision 後；以實際欄位 `max_label_available_at <= decision_at` 檢查為 0、horizon end before decision=0、label availability cutoff violation=0。
- `replay_source.sqlite` row count／index 與 rows identity join 完全一致；保留 T-1 price availability、PIT sector id、official trade restriction timeline 與 source values hash。price availability after decision=0；T-1 的 `price_event_at` 可以早於 decision，這是預期歷史事件，不以 event timestamp 取代 availability cutoff；unknown restriction=0、negative volume=0。
- volume carry policy 為 `direct-replay-volume20-cross-year-carry.v1`；future／duplicate／invalid volume counters 全為 0。
- 2014 manifest 的 `corporate_action_excluded_label_count=65,692` 已由年度產物記錄；因最終年度 event closure 尚未完成，這裡只報告 artifact evidence，不把它擴大宣稱為全歷史公司行動隔離已完成。

### 現階段 teacher gate

2014 teacher diagnostics 顯示 187 個 decision dates 均 cash-only，eligible/search/sector-observed candidates 為 0、non-cash target decisions 為 0、unknown-sector candidates 為 219,103、target nonzero symbols 為 0、teacher incomplete 為 0。這是資料與 teacher input 的診斷，不是合格 teacher；OOC 即使日後建立，也只能依既有 gate 判為 research-only，不能製造正式投資結果。

### 2015 實體 consumer readback

2015 年度 artifact 在 2016 raw spool 開始後已封存，並以同一 resolver／readback 規則驗證：`complete=true`、8/8 artifact bytes 與 file SHA 全部符合 manifest；manifest canonical hash `sha256:c0acfd410311e3f679036149d2c5a507d7d0f4d7a358e322ed4f37cfd2e4d656`、manifest file SHA `sha256:d4afc4bf4429bc1ee699242d1f629693d0e788074f7dfa22a0969e7fb1c9c731`、carry hash `sha256:42bbedf20851386dec11f5b2e9d3e8f5137ebc27df827ff0568f767483e005d9`。

- row count 251,231、feature count 62；values/masks/labels dtype 分別為 `int64`／`uint8`／`uint8`。feature observed counts 與 manifest 相符，missing feature cells 2,224,833，missing mask 下非零 value 為 0；label masks 僅有 0/1。
- 5／10／20／60 horizon 的 label slot 均有 251,231 valid benchmark／risk／fill 類欄位，sector excess slot 為 0 valid 並保持 missing；不把未知 sector 當有效 label。
- rows 與 replay source 的 local index、decision timestamp/date、symbol key join mismatch=0；兩邊的 `sample_hash`／`source_values_hash` 均非空且不作跨語義相等要求。rows index 為 0..251,230、distinct 251,231、date 為 2015-01-05 至 2015-12-31、duplicate date/symbol=0。
- `target_available_at <= decision_at`=0、`max_label_available_at <= decision_at`=0、horizon end before decision=0、`price_available_at > decision_at`=0。price availability null 為 42 rows，且這些 rows 的 13 個 `daily_prices.*` feature masks 全為 missing、沒有 observed price payload；`price_event_at < decision_at` 為 251,189 rows，符合 T-1 event／availability 分離，不是 PIT violation；unknown restriction=0、negative volume=0。
- teacher diagnostics 為 244 個 decision dates 全 cash-only，eligible/search/sector-observed candidates=0、non-cash target decisions=0、unknown-sector rows=251,231、target nonzero symbols=0、teacher incomplete=0；因此 2015 也不能解除 teacher gate 或 formal gate。`corporate_action_excluded_label_count=69,288` 只作年度 artifact evidence，跨年度 event closure 仍待 Direct terminal 後補驗。

### 2016 實體 consumer readback

2016 年度 artifact 已封存，並以同一 resolver／readback 規則驗證：`complete=true`、8/8 artifact bytes 與 file SHA 全部符合 manifest；manifest canonical hash `sha256:4be2054564c92b833c63f7a9ae7229535f712995214d1d3728a42c36beebf7a1`、manifest file SHA `sha256:ab7276df6a3ea59d4bd97271081e4ae9e63ec52b7e41ee207ee87f938635e525`、carry hash `sha256:784aeed23cf5e8fb60e8096d2c8962796601f8f895bd86b499fa15c316da7f43`。

- row count 216,849、feature count 62；values／masks／targets／labels dtype 為 `int64`／`uint8`／`int32`／`int32`，feature observed counts 與 manifest 相符，missing feature cells 1,863,775，missing mask 下非零 value 為 0。
- label masks 僅有 0/1；5／10／20／60 horizon 的 benchmark／risk／fill 類欄位各有 216,849 valid，sector excess slot 為 0 valid 並保持 missing。
- rows 與 replay source 的 local index、decision timestamp/date、symbol key join mismatch=0；sample/source hash 均非空。rows index 為 0..216,848、distinct 216,849、date 為 2016-01-04 至 2016-12-30、182 個 decision dates、duplicate date/symbol=0。
- `target_available_at <= decision_at`=0、`max_label_available_at <= decision_at`=0、horizon end before decision=0、`price_available_at > decision_at`=0。price availability null 為 38 rows，且 13 個 `daily_prices.*` feature masks 全為 missing、沒有 observed price payload；`price_event_at < decision_at` 為 216,811 rows，符合 T-1 event／availability 分離；unknown restriction=0、negative volume=0。
- teacher diagnostics 為 182 個 decision dates 全 cash-only，eligible/search/sector-observed candidates=0、non-cash target decisions=0、unknown-sector rows=216,849、target nonzero symbols=0、teacher incomplete=0；`corporate_action_excluded_label_count=67,421` 先保留為年度 artifact evidence，跨年度 event closure 仍待 Direct terminal 後補驗。

### 2017 實體 consumer readback

2017 年度已在 builder 封存後，以 frozen `resolve_direct_year_artifact_paths`、唯讀 memmap 與 SQLite replay consumer 完成一次性 readback，結論為 `status=pass`。manifest canonical hash 為 `sha256:f440fd85080cb846ef14be5db6a11a8c0aa2e45070dc9f252d57343feb90a266`，manifest file SHA 為 `sha256:84d7dea94ec1e19bd97451c07416f68974ef8efccd2d0986a51dc307002fd929`；row count 232,654、feature count 62、feature registry hash `sha256:8b0f831a94ecd503591a146d36412b2385397928b98fbd607a33fa6073630f27`。

- 8/8 artifact 的宣告 bytes 與實體 bytes、file SHA 全部一致。`features.values.i64` 為 115,396,384 bytes、`features.masks.u8` 為 14,424,548 bytes、`targets.i32` 為 5,583,696 bytes、`labels.i32` 為 33,502,176 bytes、`labels.masks.u8` 為 8,375,544 bytes、`rows.sqlite` 為 81,747,968 bytes、`replay_source.sqlite` 為 69,558,272 bytes、`carry.state.gz` 為 3,922,902 bytes；carry file SHA 為 `sha256:d5722d98be2e3c8be8fbbc2e9c6260261927f1a88d95ee2308954a5d88a31408`。
- arrays shape/dtype 為 values `[232654,62]` `int64`、feature masks `[232654,62]` `uint8`、targets `[232654,6]` `int32`、labels `[232654,36]` `int32`、label masks `[232654,36]` `uint8`；feature registry 重算一致，feature 與 target／label 欄位無重疊。feature masks 僅 0/1、invalid=0、manifest observed counts 與實體計數一致，missing feature cells 為 1,979,578。
- label masks 僅 0/1；5／10／20／60 horizon 的 benchmark、downside、MAE、MFE、realized volatility、max drawdown、tail loss、fill feasibility 均各有 232,654 valid，sector excess 欄位各為 0 valid 並保留 missing；binary label slots 僅含 0/1。
- rows index 為 0..232,653、distinct 232,654、row_id distinct 232,654；decision date 為 2017-01-03 至 2017-12-29，共 243 個 decision dates；duplicate date/symbol、decision timestamp 格式／年度錯誤、sample/state hash 缺失均為 0。`target_available_at` 與 `max_label_available_at` 均沒有早於 decision，且沒有晚於 training as-of；horizon end 沒有早於 decision。未來 label 時間是結果 provenance，不進入 feature。
- replay row count/index 與 rows identity join 完全一致（key mismatch、雙向缺列均為 0）；`source_values_hash` 非空。price availability null 為 26 rows，這 26 rows 的 13 個 `daily_prices.*` feature masks 全 missing、observed price payload=0；`price_available_at > decision_at`=0，`price_event_at > decision_at`=0，T-1 `price_event_at < decision_at`=232,628；unknown trade restriction=0、negative volume=0。
- cross-year source metadata 與 frozen discovery cache 一致，2017／2018 shard 實體 bytes 分別為 760,292,359／783,885,281；2017 carry header schema 為 `portfolio-ml-direct-carry.v2`，carry records 104,864（feature 71,153、replay-volume 33,711），schema／record validation 通過。`corporate_action_excluded_label_count=72,214` 且 official CA sidecar hash 已綁定 source manifest；年度產物保留 exclusion/mask 語義，跨年度 event closure 仍待 Direct terminal 後補驗。
- teacher gate 以實際 targets 與年度 diagnostics 執行，結果為 `allocation-teacher-eligibility-gate.v1 / blocked_missing_teacher_provenance`，reason=`teacher_input_provenance_missing`；diagnostics 為 243 dates 全 cash-only、eligible candidates=0、unknown-sector candidates=232,654、non-cash target decisions=0、target nonzero symbols=0、teacher incomplete=0。這是 teacher 未具備 formal source provenance 的明確 blocker；可標 research-only，不能宣稱模型或投資成效完成。

### 2018 實體 consumer readback

2018 年度已在 builder 封存後，以 frozen `resolve_direct_year_artifact_paths`、唯讀 memmap 與 SQLite replay consumer 完成一次性 readback，結論為 `status=pass`。manifest canonical hash 為 `sha256:4ff55e299077fcb52dc0535c32af651e6a5720e1cdc499ec05d51427066862b5`，manifest file SHA 為 `sha256:f3a4758f31a798e5a7b874f5e07a429d268939c3dac2a826dcb1c581cbf2866f`；row count 260,476、feature count 62、feature registry hash `sha256:8b0f831a94ecd503591a146d36412b2385397928b98fbd607a33fa6073630f27`。

- 8/8 artifact 的宣告 bytes 與實體 bytes、file SHA 全部一致：`features.values.i64` 129,196,096 bytes、`features.masks.u8` 16,149,512 bytes、`targets.i32` 6,251,424 bytes、`labels.i32` 37,508,544 bytes、`labels.masks.u8` 9,377,136 bytes、`rows.sqlite` 91,537,408 bytes、`replay_source.sqlite` 77,869,056 bytes、`carry.state.gz` 4,057,414 bytes；carry file SHA 為 `sha256:49991e792436aa6a7eb476a854d05f9e8815050f7f73c5e35ebc7d61862fcf7d`。
- arrays shape/dtype 為 values `[260476,62]` `int64`、feature masks `[260476,62]` `uint8`、targets `[260476,6]` `int32`、labels `[260476,36]` `int32`、label masks `[260476,36]` `uint8`；feature registry 重算一致，feature 與 target／label 欄位無重疊。feature masks 僅 0/1、invalid=0、masked values 均為 0、manifest observed counts 與實體計數一致，missing feature cells 為 2,292,201。
- label masks 僅 0/1；5／10／20／60 horizon 的 benchmark、downside、MAE、MFE、realized volatility、max drawdown、tail loss、fill feasibility 均各有 260,476 valid，sector excess 欄位各為 0 valid 並保留 missing；binary label slots 僅含 0/1。
- rows index 為 0..260,475、distinct 260,476、row_id distinct 260,476；decision date 為 2018-01-02 至 2018-12-28，共 245 個 decision dates；duplicate date/symbol、decision timestamp 格式／年度錯誤、sample/state hash 缺失均為 0。`target_available_at` 與 `max_label_available_at` 均沒有早於 decision，且沒有晚於 training as-of；horizon end 沒有早於 decision。
- replay row count/index 與 rows identity join 完全一致（key mismatch、雙向缺列均為 0）；`source_values_hash` 非空。price availability null 為 48 rows，這些 rows 的 13 個 `daily_prices.*` feature masks 全 missing、observed price payload=0；`price_available_at > decision_at`=0，`price_event_at > decision_at`=0，T-1 `price_event_at < decision_at`=260,428；unknown trade restriction=0、negative volume=0。
- cross-year source metadata 與 frozen discovery cache 一致，2018／2019 shard 實體 bytes 分別為 783,885,281／782,422,960；2018 carry header schema 為 `portfolio-ml-direct-carry.v2`，carry records 108,886（feature 73,755、replay-volume 35,131），schema／record validation 通過。`corporate_action_excluded_label_count=74,756` 且 official CA sidecar hash 已綁定 source manifest；跨年度 event closure 仍待 Direct terminal 後補驗。
- teacher gate 以實際 targets 與年度 diagnostics 執行，結果為 `allocation-teacher-eligibility-gate.v1 / blocked_missing_teacher_provenance`，reason=`teacher_input_provenance_missing`；diagnostics 為 245 dates 全 cash-only、eligible candidates=0、unknown-sector candidates=260,476、non-cash target decisions=0、target nonzero symbols=0、teacher incomplete=0。資料可供 research-only 診斷，但不能宣稱模型訓練或投資成效完成。

### 2019 實體 consumer readback

2019 年度已在 builder 封存後，以 frozen `resolve_direct_year_artifact_paths`、唯讀 memmap 與 SQLite replay consumer 完成一次性 readback，結論為 `status=pass`。manifest canonical hash 為 `sha256:7bee2603865fb8c83be86f6dd7472d94839f3eafd7030c12dc0c318d7c4271e4`，manifest file SHA 為 `sha256:eb028b6694feebb333a75f845d862f90eb37225ff14685a952c5160b39fe1323`；row count 308,500、feature count 62、feature registry hash 維持 `sha256:8b0f831a94ecd503591a146d36412b2385397928b98fbd607a33fa6073630f27`。

- 8/8 artifact 的宣告 bytes 與實體 bytes、file SHA 全部一致：`features.values.i64` 153,016,000 bytes、`features.masks.u8` 19,127,000 bytes、`targets.i32` 7,404,000 bytes、`labels.i32` 44,424,000 bytes、`labels.masks.u8` 11,106,000 bytes、`rows.sqlite` 108,433,408 bytes、`replay_source.sqlite` 92,262,400 bytes、`carry.state.gz` 4,149,712 bytes；carry file SHA 為 `sha256:576ba516268bb84ca21653efda30e2e6d49170d27071cf6f169ab3149671f3dd`。
- arrays shape/dtype 為 values `[308500,62]` `int64`、feature masks `[308500,62]` `uint8`、targets `[308500,6]` `int32`、labels `[308500,36]` `int32`、label masks `[308500,36]` `uint8`；feature registry／order 重算一致，feature 與 target／label 欄位無重疊。feature masks 僅 0/1、invalid=0、masked values 均為 0、manifest observed counts 與實體計數一致，missing feature cells 為 2,854,827。
- label masks 僅 0/1；5／10／20／60 horizon 的 benchmark、downside、MAE、MFE、realized volatility、max drawdown、tail loss、fill feasibility 均各有 308,500 valid，sector excess 欄位各為 0 valid 並保留 missing；binary label slots 僅含 0/1。
- rows index 為 0..308,499、distinct 308,500、row_id distinct 308,500；decision date 為 2019-01-02 至 2019-12-31，共 241 個 decision dates；duplicate date/symbol、decision timestamp 格式／年度錯誤、sample hash 缺失均為 0。`target_available_at` 與 `max_label_available_at` 均沒有早於 decision，且沒有晚於 training as-of；horizon end 沒有早於 decision。
- replay row count/index 與 rows identity join 完全一致（key mismatch、雙向缺列均為 0）；`source_values_hash` 非空。price availability null 為 38 rows，這些 rows 的 13 個 `daily_prices.*` feature masks 全 missing、observed price payload=0；`price_available_at > decision_at`=0，`price_event_at > decision_at`=0，T-1 `price_event_at < decision_at`=308,462；unknown trade restriction=0、negative volume=0。
- cross-year source metadata 與 frozen discovery cache 一致，2019／2020 shard 實體 bytes 分別為 782,422,960／829,308,679；2019 carry header schema 為 `portfolio-ml-direct-carry.v2`，carry records 111,427（feature 75,310、replay-volume 36,117），schema／record validation 通過。`corporate_action_excluded_label_count=77,893` 且 official CA sidecar hash 已綁定 source manifest；跨年度 event closure 仍待 Direct terminal 後補驗。
- teacher gate 以實際 targets 與年度 diagnostics 執行，結果為 `allocation-teacher-eligibility-gate.v1 / blocked_missing_teacher_provenance`，reason=`teacher_input_provenance_missing`；diagnostics 為 241 dates 全 cash-only、eligible candidates=0、unknown-sector candidates=308,500、non-cash target decisions=0、target nonzero symbols=0、teacher incomplete=0。資料可供 research-only 診斷，但不能宣稱模型訓練或投資成效完成。

### 2020 實體 consumer readback

2020 年度已在 builder 封存後，以 frozen `resolve_direct_year_artifact_paths`、唯讀 memmap 與 SQLite replay consumer 完成一次性 readback，結論為 `status=pass`。manifest canonical hash 為 `sha256:02840ceda1a67ee0539f3b15df7830c5731bb7554d4da42d5db10a50dd363ada`，manifest file SHA 為 `sha256:3cd33b4c6b81cc2fec23ba5432fe1e4f338531c747f07641b2e80623edbe8e82`；row count 279,562、feature count 62、feature registry hash 維持 `sha256:8b0f831a94ecd503591a146d36412b2385397928b98fbd607a33fa6073630f27`。

- 8/8 artifact 的宣告 bytes 與實體 bytes、file SHA 全部一致：`features.values.i64` 138,662,752 bytes、`features.masks.u8` 17,332,844 bytes、`targets.i32` 6,709,488 bytes、`labels.i32` 40,256,928 bytes、`labels.masks.u8` 10,064,232 bytes、`rows.sqlite` 98,250,752 bytes、`replay_source.sqlite` 83,574,784 bytes、`carry.state.gz` 4,268,791 bytes；carry file SHA 為 `sha256:775dbfa83ab0ab6340039fa3ebd56f539bc939826c2f50ef98862b0eec2623dd`。
- arrays shape/dtype 為 values `[279562,62]` `int64`、feature masks `[279562,62]` `uint8`、targets `[279562,6]` `int32`、labels `[279562,4,9]` `int32`、label masks `[279562,4,9]` `uint8`；feature registry／order 重算一致，feature 與 target／label 欄位無重疊。feature masks 僅 0/1、invalid=0、masked values 均為 0、manifest observed counts 與實體計數一致，missing feature cells 為 2,391,993。
- label masks 僅 0/1；5／10／20／60 horizon 的 benchmark、downside、MAE、MFE、realized volatility、max drawdown、tail loss、fill feasibility 均各有 279,562 valid，sector excess 欄位各為 0 valid 並保留 missing；binary label slots 僅含 0/1。
- rows index 為 0..279,561、distinct 279,562、row_id distinct 279,562；decision date 為 2020-01-02 至 2020-12-31，共 245 個 decision dates；duplicate date/symbol、decision timestamp 格式／年度錯誤、sample hash 缺失均為 0。`target_available_at` 與 `max_label_available_at` 均沒有早於 decision，且沒有晚於 training as-of；horizon end 沒有早於 decision。
- replay row count/index 與 rows identity join 完全一致（key mismatch、雙向缺列均為 0）；`source_values_hash` 非空。price availability null 為 28 rows，這些 rows 的 13 個 `daily_prices.*` feature masks 全 missing、observed price payload=0；`price_available_at > decision_at`=0，`price_event_at > decision_at`=0，T-1 `price_event_at < decision_at`=279,534；unknown trade restriction=0、negative volume=0。
- cross-year source metadata 與 frozen discovery cache 一致，2020／2021 shard 實體 bytes 分別為 829,308,679／848,497,707，且 compressed SHA 與 raw manifest 一致；2020 carry header schema 為 `portfolio-ml-direct-carry.v2`，carry records 113,464（stock 76,346、industry 231、market 8、replay-volume 36,879），schema／record validation 通過，2020 的 volume seed 與 2019 final event count 一致。`corporate_action_excluded_label_count=78,425` 且 official CA sidecar hash 已綁定 source manifest；跨年度 event closure 仍待 Direct terminal 後補驗。
- teacher gate 以實際 targets 與年度 diagnostics 執行，結果為 `allocation-teacher-eligibility-gate.v1 / blocked_missing_teacher_provenance`，reason=`teacher_input_provenance_missing`；diagnostics 為 245 dates 全 cash-only、eligible candidates=0、unknown-sector candidates=279,562、non-cash target decisions=0、target nonzero symbols=0、teacher incomplete=0。資料可供 research-only 診斷，但不能宣稱模型訓練或投資成效完成。

## 6. 全年度完成時必須通過的資料驗收

每一年度都要重複下列驗收，且要在 root manifest／checkpoint 中留下 hash、row count、schema、bytes、source identity 與 capacity evidence：

1. 年度 manifest canonical hash 與 manifest file SHA 分開驗證；各 binary／SQLite／carry artifact 的實體 hash、bytes、shape、dtype 與 row identity 一致。
2. feature registry、feature order、mask semantics、label horizon／validity、PIT cutoff、decision-time availability 一致；missing value 不得帶有有效非零 payload。
3. rows 與 replay source 以 index、decision date／timestamp、symbol 做一對一 join；`sample_hash` 與 `source_values_hash` 各自非空且維持各自語義，不要求彼此相等；價格缺失、交易限制、公司行動要隔離而不是以零值偽裝。
4. 跨年度 window 與 volume carry 只能讀取決策當下已可取得的歷史；label 可以使用未來結果，但不進入 feature／scaler／split decision。
5. fold discovery 使用既定 purge=60／embargo=5；完成度只由既有產物證明，不在本任務新跑 fold-006+。任何標準化若由日後 OOC 執行，必須在每個 training fold 內 fit、再套用到 validation／test，不可使用全歷史統計量。
6. Direct root 只有在 13 年均 complete、root manifest／latest pointer 原子寫入且 independent readback 通過後，才可進 OOC preflight。寫出檔案本身不算全鏈完成。

## 7. Failure、resume 與版本隔離

目前程序已因兩次 capacity hold 終止，沒有第三次 restart。已保存並核對 process exit／命令 custody／建立時間、最後 heartbeat、checkpoint、stderr/stdout、lock owner、root artifact 與容量；這不是等待 timeout。最後有效年度是 2020，最後有效 manifest／carry hash 已列入年度矩陣；2021 partial 已清理，等待 root 提供額外容量後才可再 resume。

只有在 raw canonical hash、dependency freeze、builder code／loaded source snapshot、schema、label／carry policy 與 output namespace 全部相同時，才可使用本 run 的 checkpoint resume。若版本不相容，交 root 以新隔離 namespace 重新建置；不把舊 `portfolio_ml_direct_numeric_production_v4_v2` 的數值、label、carry 或部分年度混入新 root，也不直接覆寫任何既有 root。

## 8. OOC／release preflight（Direct terminal 後、root gate 前）

本輪尚未執行 downstream CLI。`continue_ml_direct_ooc_after_store.py --resume-after-direct-store` 會在 custody 後進入 OOC training service，屬於新 fit；依使用者限制不得擅自啟動。Direct terminal 後，先由 root 審核下列精確 preflight：

| Gate | 必須確認 |
|---|---|
| source | root manifest 指向本新 Direct namespace；raw canonical hash、dependency hash、corporate-action manifest hash、feature registry／dataset identity、PIT cutoff 可追溯 |
| version | 13 年完整年度矩陣、每年 manifest／file／artifact hashes、schema／row counts、cross-year carry 與 checkpoint closure 全部一致 |
| capacity／lock | D: free ≥ temporary + persistent + 200 GiB reserve 的 declared required free；canonical heavy lock 可取得且無第二 builder；實際 TEMP／output bytes 已重新讀取 |
| OOC output | 新 output namespace、batch／worker／memory budget、teacher input source、purge／embargo 與 no-lookahead policy 明確；不接舊 OOC／舊 labels |
| release | OOC artifact、shared-block registry、calibration／lineage／parity／policy hashes 與 release root contract 明確；沒有合格 teacher 時標 research-only，formal gate 保持關閉 |
| consumer | 用既有 resolver／shared-block readback 驗證 bytes／hash／feature order／mask／label／row parity；失敗則停止，不靠 pointer 或檔案存在判定成功。2014–2020 已完成年度 resolver／memmap／SQLite readback；root `_NumericStore`／全 root consumer readback 尚待 13 年 root manifest。 |

可執行方案是：Direct root terminal → immutable root readback → preflight report → root 明確核准後才可沿既有受控 OOC/release 流程；本文件交付的是 gate 條件，不把核准視為已取得。不得跑新 fit、fold-006+、promotion 或券商交易。

目前 preflight 結果為 `blocked_pre_direct_terminal`：run 尚無 root `manifest.json`／`latest_manifest.json`、fold index、完整年度矩陣或可供 `_NumericStore` 跨年度開啟的 root contract，因此沒有偽造 root manifest，也沒有把舊 root／舊 OOC／舊 shared registry 接入。Direct 未 terminal 前，不執行 `continue_ml_direct_ooc_after_store.py`；沒有 qualified teacher 時，即使日後 Direct 完成，也只能標為 research-only。

## 9. 已執行測試與待辦

已讀取並採用的 freeze QA 證據包括：Direct guard／interrupted-builder 9 passed、capacity 2 passed、cross-forward import 25 passed、root-independent shared/OOC 9 passed、同 interruption builder resume 1 passed、Direct mypy success、changed Python files `py_compile` exit 0，以及 typed canonical JSON canonicalization QA。這些是工程／資料鏈 guard，不是 model quality 或投資成效。

已使用 graphify 對 Direct numeric store、shared-block resolver、OOC training、release builder、purged walk-forward 與 teacher boundary 做 codebase chain query；未重建 graph，亦未以 graph output 取代實體 artifact readback。2014–2020 已以 production frozen resolver、唯讀 memmap、SQLite rows/replay 與 carry reader 完成年度 readback；2020 的實際結果為 `status=pass`，不是只檢查檔案存在。

既有 downstream CLI 的唯讀 `--help` 已讀取：`continue_ml_direct_ooc_after_store.py` 明確包含 `--resume-after-direct-store` 並會進入 OOC training service；`continue_ml_release_after_ooc.py` 只在 OOC helper 後協調既有 fail-closed release checks；`qa_ml_direct_ooc_shared_reuse.py` 以 `PYTHONIOENCODING=utf-8` 讀取成功，但未執行其 QA；其 source／計畫已讀，production shared registry 仍不存在，故不把 shared reuse 宣稱為通過。

接續只在 root 提供額外容量並明確要求 resume，或 heartbeat／checkpoint 有新年度、程序終止、capacity margin 接近 gate、或 Direct root terminal 時觸發。下一個必須補齊的交付是 2021–2026 的同等年度矩陣、root manifest／pointer closure、跨年度公司行動與 PIT window evidence，以及不啟動 fit 的 OOC／release preflight。若 teacher gate 仍不合格，最終狀態須明確寫成「資料建置可驗證、模型訓練未啟動／research-only、投資成效未成立」。

## 10. Root 整合複核（2026-09-08）

本輪獨立 readback 與測試確認：15 個 Direct computation dependency 檔案的實體 bytes／SHA-256 全部與 freeze 清冊一致；raw manifest 的 canonical content hash `sha256:d55879c6d4bfae7c8fbb095330b0732eb1c5c80ecd2e0a0b5b79ee617b2eddc9` 與實體 manifest file SHA `sha256:6ecc7b26040e00b5c9f70f77b22a7bc9dd976a38453a88c1d1d9865a1eb4e5bc` 分開保留。Direct 實際 checkpoint 正確封存 2014–2020 七個年度；2021 仍是 capacity hold，2022–2026 沒有 finalized manifest。當前 live builder／maintainer PID 已不存在，heartbeat 停在 `running`，因此不能宣稱 run 已完成；stale lock／status 仍保留供 root 判讀，沒有重啟或刪除。

本輪獨立 Data／update 定向驗證為 freshness／calendar／scheduled suite `115 passed`、bounded update suite `100 passed`、Direct／scheduler／capacity suite `50 passed, 1 skipped`，10 個變更 source 的 mypy 成功，變更 Python `py_compile` 成功。Direct 目標測試在移除 guard 污染後 `1 passed`；assembler progress 隔離測試 `2 passed`，完整 `tests/test_portfolio_ml_dataset_assembler.py` 為 `38 passed`。Root 另獨立重驗 Paper isolated scheduler 全檔 `9 passed` 與 Direct build／resume `1 passed`；這些結果是工程與資料 custody 證據，不等同 OOC fit、promotion 或投資成效。

容量判定沿用 current guard 固定 `40 GiB temporary + 35 GiB new persistent + 200 GiB reserve = 275 GiB`（`295,279,001,600` bytes）。清理後初始 D: free 為 `318,606,434,304` bytes（`296.725364685 GiB`），相對 required free 的 margin 為 `23,327,432,704` bytes（`21.725364685 GiB`）。已保存的 2021 temporary peak 是 `23,169,343,755` bytes（`21.578132878 GiB`），兩次 hold 的最大短缺是 `49,659,904` bytes（`47.359 MiB`）；後一次 `20,914,176` bytes 不能取代前一次較大值。若只要求越過歷史 hold，`49,659,904` bytes 是最低觀測下限，1 GiB 只是操作緩衝。若以現有 Direct root `2,525,374,802` bytes、plan 上限 `15,333,023,892` bytes 推得剩餘 persistent `12,807,649,090` bytes（`11.928052725 GiB`），並假設後續單年 temporary 不超過已觀測 2021 peak，連同最大歷史短缺由目前 margin 推得的全 run continuation lower bound 為 `12,699,220,045` bytes（`11.827070308 GiB`）；這仍未量測 2021 剩餘及 2022–2026 峰值，不能當成完成保證，也不改 required／reserve。

本節前兩段的 readback／測試摘要由本輪 Data／ML owner 執行，Direct 七年 checkpoint、live PID／heartbeat、capacity hold 與獨立重驗結果由 root 整合複核。可提交範圍是本文件與本輪測試修補；自然等待項仍為 Direct 2021–2026 生產、root manifest／pointer closure、正式基本面 apply、calendar／scheduler host 即時 inspector，以及 teacher／OOC／release 後續 gate。未完成項維持 pending／blocked，不以測試 fixture 或單次 capacity margin 產生自然信用。
