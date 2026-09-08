# V4 ML Storage Guard QA（2026-09-07）

## 本輪範圍

本輪把所有會建立或發布 ML 長鏈產物的入口收斂到同一套唯讀容量政策與
reservation。修改 owner 包含 `data_module/ml_storage_capacity.py`、PIT／Direct／
raw-to-OOC builder、OOC training CLI、兩個 scheduled caller、maintainer 及其
受控 CLI；沒有啟動交易、沒有寫入正式 SQLite 或 D 槽正式資料、沒有執行全鏈
訓練，也沒有改動既有 immutable run。研究比較與已發布 release 的讀取仍沿用
各自較小的輸出預算，但安全保留與共用 lock 不能繞過中央政策。

## 可驗證契約

- 所有 heavy chain caller 的安全保留至少為 200 GiB。scheduled raw／Direct
  的單次上限仍為持久新增 35 GiB、暫存峰值 40 GiB，因此 required free
  headroom 為 275 GiB；PIT／Direct／raw-to-OOC／OOC 的 standalone 預設為
  持久新增 1 GiB、暫存峰值 1 GiB。純容量算式的舊
  `MLStorageCapacityBudget` 仍可接受小型 fake 值，但 production caller
  必須經 `heavy_chain_capacity_budget()`，低於 200 GiB 的 CLI 值會 fail closed。
- scheduled bootstrap 在輸出量尚未知時，以兩項已設定上限作最壞情況估算。
  明確傳入 `None` 的估算會留下
  `persistent_new_bytes_estimate_unknown` 或
  `temporary_peak_bytes_estimate_unknown` blocker，不會被折成零而放行。
- `directory_size_bytes` 使用明確的 `lstat`／`scandir`。不存在路徑仍是
  0 bytes；symlink 與 Windows junction／reparse point 不跟隨；列舉或
  metadata 權限錯誤會轉成 `StorageCapacityPreflightError`，不再靜默成
  0 bytes。Windows junction 測試只在 pytest 暫存目錄建立 junction。
- raw 與 Direct/OOC 透過同一個
  `release_v4/.ml_heavy_chain.lock` reservation 互斥。Windows 使用
  `msvcrt.locking`，POSIX 使用 `fcntl.flock`；lock 檔固定保留，不做 PID
  存活探測、stale rename 或 unlink reclaim，程序結束由 OS 釋放持有的檔案鎖。
- reservation handoff 不再接受舊的
  `BALDR_ML_HEAVY_CHAIN_RESERVATION_HELD=1` marker。真正 owner 取得 OS lock
  後以隨機 nonce、canonical lock path、owner PID 與 atomic owner sidecar
  建立 lease；每次 `Popen` 回傳後，parent 必須把 child PID 及 parent PID
  寫入 sidecar，child 才能進入 builder。child 會重新核對 sidecar、nonce、
  owner／parent liveness 與 parent→child mapping，並在開始 writer 前取得
  canonical lock 旁的獨立 OS handoff gate；Windows Python launcher 的中介
  PID 也必須是同一 mapping 的立即 bridge。競爭者即使在 owner OS lock 已
  釋放後取得 canonical lock，仍會檢查 live child custody 並 probe 同目錄
  的實際 gate；child 持 gate 時拒絕新 chain，因此不只依賴可遺失的 sidecar。
  每層 forwarding 使用新的 gate path，避免巢狀 continuation 互相搶同一把
  gate。watchdog 觀察 owner、parent、sidecar custody 消失時，以 return code
  `75` 結束 child；偽造 marker、未登記 child、錯誤 lock path／nonce 與
  owner 結束後的續寫均 fail closed。
- scheduled caller 先做唯讀容量 preflight。raw 在自己的 execution
  reservation 取得後立即重讀 filesystem usage 與輸出目錄大小；Direct
  wrapper 將 reservation ownership 交給真正的
  `maintain_ml_direct_v3_refresh_chain.py`，由 child 原子競爭同一路徑並在
  child 整個 watcher／continuation lifetime 內持有，再做 locked recheck。
  第二次不足會 fail closed 並釋放 reservation。Direct 的
  `--preflight-only` 在取得 reservation 前結束。既有 Direct instance
  custody 若可驗證仍活躍，wrapper 不啟動第二個 child；raw 也會依同一
  custody 判定拒絕並在 stale owner 後恢復。若 maintainer 異常退出而既有
  continuation command 仍活躍，raw 另外使用既有 output-bound target
  custody 暫停重疊啟動，待 target 消失後恢復。

- caller 矩陣如下：

  | 入口 | 預算解析／寫入邊界 | reservation 行為 |
  | --- | --- | --- |
  | `build_ml_pit_year_shards.py`／`PITYearShardExporter` | standalone 1/1 GiB、reserve ≥200 GiB；年度 checkpoint 重新量測 | 正式 `release_v4/.ml_heavy_chain.lock` |
  | `build_portfolio_ml_direct_numeric_store.py`／Direct builder | standalone 1/1 GiB、reserve ≥200 GiB；checkpoint 與 incomplete checkpoint 保留 | CLI 或 scheduled maintainer 持有同一 canonical lock |
  | `build_portfolio_ml_ooc_from_raw.py`／raw-to-OOC | standalone 1/1 GiB、reserve ≥200 GiB；spool 建立前 preflight | canonical lock；由上層 supervisor 傳遞可驗證 handoff |
  | `train_ml_allocation_out_of_core.py`／OOC service | standalone 1/1 GiB、reserve ≥200 GiB；fit/meta checkpoint 量測 | canonical lock；低預算在 source read／fit 前拒絕 |
  | `run_ml_raw_pit_refresh.py`、`run_ml_direct_chain_maintenance.py` | scheduled 35/40 GiB、reserve ≥200 GiB，required 275 GiB | 先 preflight、取鎖後再查一次；child 不另開第二把鎖 |
  | derived／v3 linear／daily shadow／confirmatory read-only CLI | 各自固定 200 GiB reserve，輸出上限另由 request 綁定 | release_v4 canonical lock；只讀 source，不授予 promotion |

  每個 group 以 nearest existing ancestor 判定檔案系統；probe、persistent 與
  temporary 可在不同磁碟，但全 chain 的 persistent／temporary aggregate quota
  仍各自計算，並且每個實際 destination 都要保留 safety/headroom。caller
  指定的 lock 若不等於由 parent／`release_v4` 推導的 canonical path 會被拒絕。

## 定向驗證

以下中央容量檢查在本機 Windows Python 3.11.9 完成；原先 67 passed 的 scheduled
基線屬政策變更前歷史讀數，不覆蓋本次新增的低 reserve／跨磁碟判斷：

```text
python -m pytest tests/test_ml_storage_capacity.py -q -o addopts= -p no:cacheprovider
25 passed, 1 skipped

python -m pytest tests/test_ml_direct_numeric_shared_reuse.py `
  -k direct_year_path_receives_resolved_capacity_budget -q `
  -o addopts= -p no:cacheprovider
1 passed

python -m mypy --explicit-package-bases \
  data_module/ml_storage_capacity.py \
  data_module/ml_pit_year_shard_exporter.py \
  data_module/portfolio_ml_direct_numeric_store.py \
  data_module/portfolio_ml_raw_to_ooc_pipeline.py \
  ml_module/allocation_out_of_core_training_service.py \
  scripts/build_ml_pit_year_shards.py \
  scripts/build_portfolio_ml_direct_numeric_store.py \
  scripts/build_portfolio_ml_ooc_from_raw.py \
  scripts/train_ml_allocation_out_of_core.py \
  scripts/scheduled/run_ml_raw_pit_refresh.py \
  scripts/scheduled/run_ml_direct_chain_maintenance.py \
  scripts/maintain_ml_direct_v3_refresh_chain.py

Success: no issues found in 12 source files

python -m py_compile \
  data_module/ml_storage_capacity.py \
  scripts/scheduled/run_ml_raw_pit_refresh.py \
  scripts/scheduled/run_ml_direct_chain_maintenance.py \
  scripts/maintain_ml_direct_v3_refresh_chain.py \
  ml_module/allocation_out_of_core_training_service.py \
  data_module/portfolio_ml_direct_numeric_store.py \
  data_module/ml_pit_year_shard_exporter.py \
  data_module/portfolio_ml_raw_to_ooc_pipeline.py \
  scripts/build_ml_pit_year_shards.py \
  scripts/build_portfolio_ml_direct_numeric_store.py \
  scripts/build_portfolio_ml_ooc_from_raw.py \
  scripts/train_ml_allocation_out_of_core.py
```

本次 handoff 與 scheduled fixture 回歸使用相同 repo worktree，未啟動 D 槽
來源／live fit：

```text
python -m pytest tests/test_ml_storage_capacity.py `
  tests/test_ml_direct_chain_maintenance.py `
  tests/test_scheduled_ml_direct_chain_maintenance.py `
  tests/test_scheduled_ml_raw_pit_refresh.py -q -o addopts= --disable-warnings
78 passed, 1 skipped

python -m pytest tests/test_continue_ml_direct_v3_refresh_chain.py `
  tests/test_continue_ml_direct_ooc_after_store.py -q -o addopts= --disable-warnings
23 passed

python -m py_compile \
  data_module/ml_storage_capacity.py \
  scripts/maintain_ml_direct_v3_refresh_chain.py \
  scripts/continue_ml_direct_v3_refresh_chain.py \
  scripts/continue_ml_direct_ooc_after_store.py \
  scripts/scheduled/run_ml_raw_pit_refresh.py \
  scripts/build_ml_pit_year_shards.py \
  scripts/build_portfolio_ml_direct_numeric_store.py \
  scripts/build_portfolio_ml_ooc_from_raw.py \
  scripts/train_ml_allocation_out_of_core.py

python -m mypy --explicit-package-bases \
  data_module/ml_storage_capacity.py \
  scripts/maintain_ml_direct_v3_refresh_chain.py \
  scripts/continue_ml_direct_v3_refresh_chain.py \
  scripts/continue_ml_direct_ooc_after_store.py \
  scripts/scheduled/run_ml_raw_pit_refresh.py \
  scripts/build_ml_pit_year_shards.py \
  scripts/build_portfolio_ml_direct_numeric_store.py \
  scripts/build_portfolio_ml_ooc_from_raw.py \
  scripts/train_ml_allocation_out_of_core.py
Success: no issues found in 9 source files
```

`test_reservation_handoff_accepts_real_parent_and_forwards_to_child` 驗證
parent→child→grandchild 的分層 gate 與 sidecar 登記；
`test_reservation_handoff_child_stops_after_owner_exit` 驗證 owner 結束後
watchdog 不允許 child 繼續；`test_owner_exit_keeps_child_gate_against_immediate_competitor`
則讓 child 持續寫入、先讓 owner 突然結束；競爭 process 會先確認 owner PID
已終止，再以底層 canonical OS lock probe 證明 owner lock 已可取得，最後
經 public acquire 驗證仍被 child 實際 handoff gate 阻擋。蓄意移除 sidecar
後仍維持相同結果，直到 child 終止。scheduled
fixtures 明確使用 35 GiB persistent、40 GiB temporary、200 GiB safety
reserve；低 headroom、低 CLI reserve 及 old marker 仍是拒絕案例。測試中的
capacity fake 只供純算式或 custody 隔離，不代表正式檔案系統容量。

測試涵蓋低空間與超額 checkpoint、未知估算、permission-denied fail-closed、
不存在路徑、真 Windows junction、兩程序競爭、例外釋放／恢復、程序直接結束
後由 OS 釋放 reservation、鎖定後外部容量變化、canonical lock mismatch，以及
probe／persistent／temporary 位於三個 filesystem 時的 aggregate quota；另以真實
三年度 Direct fixture 驗證年度 helper 收到已解析 budget。唯一 skipped case 是
該環境無法建立 symlink 的既有 symlink fixture；Windows junction case 已成功通過。

### bounded union late-write hardening（2026-09-07）

獨立檢視舊 over-capacity 失敗後，補上兩個不改變既有 artifact identity 的邊界：

- `data_module/portfolio_ml_dataset_assembler.py` 在 raw observation／price 及 label／
  exclusion batch callback 前先 commit SQLite，避免 callback 只看到 connection cache
  而低估實際 spool bytes；label batch 也會各自發布 persisted batch event。
- `data_module/ml_research_shadow_union_bounded.py` 在最後 summary atomic write 前以
  canonical JSON（SHA-256 placeholder 保持等長）估算精確 projection，通過 capacity
  checkpoint 後才寫入，寫後再量測一次。summary payload 會保存此 guard 的 stage／
  projected bytes；若寫前或寫後超額，流程 fail closed，不回收或覆寫既有 immutable run。

這是 future bounded execution 的 protection tightening；本輪沒有用新 guard 重跑
v2 bounded union。相應 regression 已通過：bounded／assembler／storage 合計
`63 passed, 1 skipped`，overlay／release／frozen inference integration 合計
`50 passed, 1 skipped`；mypy 3 個 owner source 與 py_compile 皆成功。

## 邊界與後續

本輪驗證的是 heavy caller 的容量與互斥工程接線，不代表 Formal OOS、promotion、
投資有效性或真實 fill 已完成。執行中 RSS 仍是 sampled checkpoint evidence，
不是 OS-level 4 GiB hard limit；temporary evidence 也只涵蓋 producer 明確導向的
workspace。容量通過只表示可以安全啟動或續跑，不能解除 alpha=0、broker disabled
或正式輸入 gate。跨 run immutable block reuse 另有獨立 hash／失效鍵契約。
