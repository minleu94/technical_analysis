# V4 Next Ops Handoff — 2026-09-08

本文件是 scheduler／operations owner 的交付，記錄 Windows Task Scheduler、Paper EOD 相依性、真實資料累積入口與可回溯證據。工作只在共用 `dev` checkout 進行，沒有建立 branch、worktree、commit 或 push。

## 目前 ownership 與邊界

- scheduler／operations：`scripts/scheduled/`、scheduler registration/query、Paper EOD scheduler gate/retry、自然日與 weekly evidence 的排程觀測。
- ML owner：`scripts/run_daily_ml_allocation_derived_shadow.py` 與 forward ML orchestration；ML owner 需要補上已驗證的 `pit_machine_operational_path`、path/hash custody、盤前 emission 與 maturity 接線。這份 handoff 沒有改 ML consumer。
- Paper／Formal owner：既有 Paper domain、Formal consumer、成交候選與正式 evidence gate。這份 handoff 沒有改 Paper domain 或 Formal consumer。
- D 槽原始行情檔與正式 SQLite：本次沒有寫入、覆蓋、刪除或回填。

## Scheduler 實際狀態

2026-09-08 10:44:24 UTC 的唯讀 registration inspection 是新增 forward task 前的歷史觀測：17 個 task（16 daily + 1 weekly），17 個 wrapper 都存在，`action_mismatch_count=0`、`schedule_mismatch_count=0`、`configuration_ready=true`。新增 task 後的最新唯讀清冊為 18 個 task（17 daily + 1 weekly），18 個 wrapper 都存在，`action_mismatch_count=0`、`schedule_mismatch_count=0`、`configuration_ready=true`；證據在 `output/v4_next_ops/task_registration_after_forward_20260908.json`。EOD、Portfolio 與 forward 的完整 live query 和 XML 均在 `output/v4_next_ops/`。

Paper EOD task 原本於 Pacific 00:05 執行，會早於 Pacific 04:20 quick data update，因此 2026-09-08 00:05 的 `Last Result=2` 只能解釋為變更前的缺源／阻塞歷史。已經在既有 task 上執行一次受控 mutation：`register_paper_execution_task.cmd register` 回傳 exit code 0，使用 `schtasks /Change` 只將 trigger 改為 Pacific 06:00，並保留既有 action 與安全設定。`output/v4_next_ops/paper_eod_register_result.txt` 保存命令和回讀結果。

After XML 的 Next Run 為 `2026/9/8 上午 06:00:00`、狀態 `Ready`／`Enabled`。XML diff 只有一條允許路徑：`Task/Triggers/CalendarTrigger/StartBoundary`，`00:05:00 → 06:00:00`；principal、`InteractiveToken`、user SID、action、battery policy、`PT1H` execution limit、`IgnoreNew` 都未變。證據為 `output/v4_next_ops/paper_eod_xml_diff.json`、`paper_eod_xml_diff.txt`、`paper_eod_settings_compare.json` 與 `scheduler_after/baldr-paper-execution-eod-replay-daily.xml`。

目前實際執行限制仍是 `Logon Mode=Interactive only`、停止於電池且電池上不啟動、`WakeToRun=false`。登出、休眠或電池狀態下不能保證自然 capture；本次沒有擅自改 principal、credential、wake 或電池設定。缺跑必須由每個窗口的 `Next Run`／`Last Result`、latest status 的 aware timestamp、Paper gate receipt freshness 共同揭露。

Paper Portfolio 也已在既有 task 上完成第二個受控 trigger mutation。`register_paper_portfolio_task.cmd register` 回傳 exit code 0，`schtasks /Change` 只將 Pacific local time 從 16:30 改為 16:15；action、`Run As User=archi`、`Interactive only`、電池政策、`IgnoreNew` 與 72 小時 execution limit 維持不變。after live query 的 Next Run 為 `2026/9/8 下午 04:15:00`，Last Run 仍是 9/7 16:30、Last Result=0，這是變更前一次執行的結果。`paper_portfolio_xml_diff_1615.json` 證明唯一 XML leaf 差異是 `CalendarTrigger/StartBoundary` 的 `16:30 → 16:15`；完整 before/after XML、live query、設定比較及註冊輸出均保存在 `output/v4_next_ops/`。

## 目前時序與時區

Task Scheduler 使用主機 `Pacific Standard Time` 的 local time；台北換算會隨 PDT/PST 改變。下面是目前實際註冊的窗口：

| Pacific local | Taipei PDT | Taipei PST | task |
|---|---:|---:|---|
| 04:20 daily | 19:20 | 20:20 | `baldr-data-update-quick-daily` |
| 04:50 daily | 19:50 | 20:50 | `baldr-official-market-events-daily` |
| 05:00 daily | 20:00 | 21:00 | `baldr-data-freshness-check-daily` |
| 05:05 daily | 20:05 | 21:05 | `baldr-ml-raw-pit-refresh-daily` |
| 05:10 daily | 20:10 | 21:10 | `baldr-recommendation-snapshot-daily` |
| 05:15 daily | 20:15 | 21:15 | `baldr-evidence-pipeline-dry-run-daily` |
| 05:17 daily | 20:17 | 21:17 | `baldr-ml-promotion-evidence-daily` |
| 05:18 daily | 20:18 | 21:18 | `baldr-ml-promotion-authority-daily` |
| 05:20 daily | 20:20 | 21:20 | `baldr-ml-allocation-copilot-daily` |
| 05:25 daily | 20:25 | 21:25 | `baldr-decision-evidence-capture-daily` |
| 05:30 daily | 20:30 | 21:30 | `baldr-ml-direct-chain-maintainer` |
| 06:00 daily | 21:00 | 22:00 | `baldr-paper-execution-eod-replay-daily` |
| 16:00 daily | 07:00 next day | 08:00 next day | `baldr-pit-sector-membership-preopen-capture-daily` |
| 16:15 daily | 07:15 next day | 08:15 next day | `baldr-paper-portfolio-daily` |
| 16:15 daily | 07:15 next day | 08:15 next day | `baldr-ml-allocation-forward-daily` |
| 18:00 daily | 09:00 next day | 10:00 next day | `baldr-formal-pit-sidecar-postcutoff-daily` |
| 21:25 daily | 12:25 next day | 13:25 next day | `baldr-formal-input-producer-daily` |
| Sunday 18:00 | Monday 09:00 | Monday 10:00 | `baldr-v2-2-weekly-collection` |

Paper Portfolio 與新增 forward task 都在 Pacific 16:15 喚醒；PDT 對應台北 07:15、PST 對應台北 08:15，兩個 wrapper 都要等待真實台北 08:30 cutoff。ML allocation 的既有 05:20 task 仍是盤後 catch-up；新增 task 只執行 candidate-only forward shadow，08:35 後 fail closed，不授予 forward credit。

### ML scheduled caller 邊界

目前 `baldr-ml-allocation-copilot-daily` 在 Pacific 05:20 喚醒（PDT 台北 20:20、PST 台北 21:20），`run_ml_allocation_copilot.cmd` 只呼叫 `scripts/run_daily_ml_allocation_orchestration.py --auto-catch-up`。這條路徑的輸出屬盤後 catch-up，不能授予台北 08:30 的前瞻 credit，也沒有接入 `run_daily_ml_allocation_derived_shadow.py` 的 forward 模式。

forward caller 已完成 preflight 並註冊為 `baldr-ml-allocation-forward-daily`：`run_ml_allocation_forward_daily.cmd` 只會喚醒 `run_ml_allocation_forward_daily.py`，不含 `schtasks`／aggregate registration；task 本身以 pinned XML 建立。wrapper 從 Pacific 16:15 喚醒後等待真實 Asia/Taipei 當日 `08:30`，省略固定設定時才呼叫每日 producer，並只讀 `configs/YYYY-MM-DD.json`；既有 `05:20 --auto-catch-up` task 不變。task registration 後尚未執行，不能把 `Last Result=267011` 解讀為成功。

每日 producer 使用已驗證的離線官方 calendar cache，`allow_online_probe=false`。實際 cache probe（`2026-09-09`、`09-08`、`09-07` open；`09-06`、`09-05` weekend closed）在 `output/v4_next_ops/forward_calendar_offline_probe_20260908.json`；因此週末／休市只寫 `skipped_non_trading_day`，calendar unknown fail closed。archive freshness 僅允許決策日當日或官方 calendar 判定的上一交易日，跨週末／假日找 predecessor，不以 weekday 推定。

設定產出只接受既有 ML PIT archive consumer 完整重驗過的單一 archive；archive 與 operational publication 互斥。producer 先讀 manifest bytes hash，再交 consumer 驗 source custody、`available_at`／`effective_from`、raw rebuild 與 HMAC receipt，最後回傳 hash 必須與前讀 bytes 相同；config 對每個自然日 create-only，選擇收據保留歷史檔。`release_root` 已固定為 repository 的 `output/v4_ml_derived_h5_20260907_real_v2`，`release_manifest_file_hash` 必須是 `sha256:c306c1ea53ccef112204a8412a605b575e4d107b4503b2b5be5d6d5ee50910ea`；wrapper 在 child 前重讀 `release_manifest.json`，path／bytes 改變即 blocked。Paper state 明確使用 repository `output/paper_execution_eod_replay/paper_portfolio/paper_portfolio.sqlite`，market SQLite 才使用 D 槽唯讀來源。

child command 只傳真正 derived parser 接受的 archive／operational 參數，forward deadline 由 child 以 `decision_at + 5 分鐘` 計算；wrapper 同值驗證至 `08:35`。child 必須保留完整 outer payload，並在 `daily_orchestration.natural_forward_completion_clock` 提供 emission／inference completion；outer `blocked_capacity`／`failed_read_only` 不能被 inner completed clock 覆蓋。成功也只落地 `completed_candidate_shadow`，`forward_credit_granted=false`；registration 已完成，但不代表 child 曾自然執行、ML custody／maturity 已完成或取得正式 credit。

Forward task 的 registration plan 與 XML template 已放在 `scripts/scheduled/ml_forward_task_registration_plan.json` 與 `scripts/scheduled/ml_forward_task_registration.xml`，狀態為 `registered_verified`。規格是 Pacific 16:15 daily、`InteractiveToken`／既有 `archi` SID、`IgnoreNew`、電池禁止、`StartWhenAvailable=false`、`WakeToRun=false` 與 `PT2H` execution limit（足以涵蓋最長 75 分鐘等待及 08:35 child deadline）。plan 內的 environment 明確指向 repo `real_v2` shadow／Paper state、D market source、V2 release manifest hash 與離線 calendar cache；Python preflight、UTF-16 XML import 失敗與修正後成功、after XML、NextRun 及設定回讀均保留在 `output/v4_next_ops/`。aggregate registration 不會覆蓋此 task；回復只能依 plan 的 task-name query 後專用 delete 命令執行。

### Formal／Paper／forward 排程依賴審核

新增 18-task 清冊與依賴圖保存在 `output/v4_next_ops/formal_paper_schedule_dependency_plan_20260908.json`。Formal 目前固定 Pacific 21:25（PDT 台北 12:25、PST 台北 13:25），仍落在 Rule 09:00–13:30 合法時窗；Formal consumer 使用 strictly prior-date Paper ledger transition，因此不需要把 EOD 或 Formal trigger 互相挪動。現階段保持 21:25，等待 Formal owner 將 actual Rule producer → consumer handoff 接線並以缺 bundle／stale bundle fail closed；不因舊的同日解讀新增 task。

Paper EOD 的 06:00 trigger 依賴 Pacific 04:20 quick 與 05:00 freshness，Paper Portfolio 與 forward 在 16:15 同時喚醒並各自等待台北 08:30。先觀察兩者對 repository Paper state 的實際鎖定／耗時；只有自然 receipts 證明有 contention，才另提出 stagger XML 差異。Interactive-only、電池限制、登出或休眠仍可能造成缺跑，必須以每個 task 的 `Next Run`／`Last Result` 和 status receipt 揭露。

## Paper EOD gate 與 retry

`run_paper_execution_daily_isolated.cmd` 現在只呼叫 `paper_execution_retry_runner.py`。每次嘗試：

1. 以 D 槽 SQLite `mode=ro`／`PRAGMA query_only=ON` 讀取 quick、freshness、`daily_prices` 與兩個 raw CSV；不寫 D 槽。
2. 要求 quick／freshness 的資料日等於當下台北自然日，並要求 receipt `checked_at` 有 timezone、台北日期正確、`checked_at <= observed_at`。future、naive、malformed timestamp 會 fail closed。
3. 以同一次 raw bytes 讀取計算 hash、解析所有可用 TWSE／TPEx code/open rows，再對同日 SQLite 每一列做 source→DB open readback。任何 missing、parse error 或 mismatch 都不能進 adapter。
4. 只有明確的缺源／上游 running 狀態，而且所有 blockers 都是已定義的 transient code，才會在同一台北自然日再等 15 分鐘。最多 3 次；跨自然日、identity、schema、future clock、malformed JSON、未知或混合 blocker 立即終止。
5. 每次 gate receipt 使用 UTC timestamp + attempt 唯一檔名，保留歷史檔；`latest.json` 以同目錄 atomic replace 更新。`official_no_data` 是明確 no-op，不呼叫成交 adapter。

測試已覆蓋 source CSV 替換、空檔、DB stale/open mismatch、future receipt、naive/malformed timestamp、混合 blocker、marker 被嵌在 identity 文字中，以及 non-interactive retry sleep。

## 已完成的歷史 readback

`output/v4_next_ops/source_db_readback_20260907.json` 是 2026-09-07 的歷史唯讀觀測，不是 2026-09-08 ready 證明：

- `daily_prices` target rows：1,970，open rows：1,970，SQLite read mode 為 `ro/query_only`。
- TWSE source：1,095/1,095 usable rows 與 SQLite open 完全相符。
- TPEx source：875/875 usable rows 與 SQLite open 完全相符。
- `blockers=[]`、`source_db_written=false`、`source_files_written=false`。

在 2026-09-08 早於今日 quick update 完成的觀測點，D `twstock.db` 最新仍為 2026-09-07，不能把上述歷史 receipt 當成今日 source。今日 06:00 trigger 目前只代表已註冊且等待自然執行；`LastResult=2` 是 00:05 的變更前結果，不能稱為 06:00 成功。

## 真實資料累積的 bounded plan

計畫證據在 `output/v4_next_ops/bounded_quick_update_plan_20260908.json`。D 槽現場觀測 free bytes 為 `333659111424`，高於既有 required headroom `295279001600`（200 GiB safety reserve + 35 GiB scheduled raw persistent + 40 GiB temporary）。這只是當下容量觀測；每次正式 capture 前仍須重新檢查。

正常自然流程使用既有 `scripts\\scheduled\\run_daily_data_update_quick.cmd`，Pacific 04:20 執行，依 `scheduled_now` 選擇最近工作日與預設十工作日 window。它對 TWSE 先做 missing-file scan，對已有 raw file skip；TPEx 使用 `force_refresh=false`，已有 target file skip；daily price SQLite 同步以日期範圍 upsert。

自然執行前的 2026-09-08 03:49:48 PDT live baseline 已保存於 `output/v4_next_ops/quick_update_live_query_before_20260908.txt`：Next Run=04:20、Ready／Enabled、前一日 LastResult=0；這份 query 沒有啟動或修改 task。

若 root 另行核准今日一日 recovery，精確入口命令已寫入 plan JSON：直接呼叫 `run_daily_data_update_quick.py --start-date 2026-09-08 --end-date 2026-09-08`，並指定 D data/output、status、history、log。這個 date range 會限制 TWSE／TPEx／daily price／broker 的日期選擇，但現有 quick CLI 還會執行 market／industry 更新與全表 SQLite synchronization；technical coverage 落後時會用既有 `incremental_lookback_days=120` 計算。因此它必須被記錄為既有 full quick chain，不能宣稱 prices-only，也不能在未核准前執行。

Root 尚未核准這個手動 full quick chain；目前不新增 prices-only 系統，也不重複啟動 04:20 task。2026-09-08 官方 availability 已先以唯讀方式探測：TWSE／TPEx 均 HTTP 200，response hash、payload size 與來源日期保存在 `output/v4_next_ops/official_availability_probe_20260908.json`，沒有寫入 D 槽或正式 SQLite。今日 04:20 natural run 的 running after query 與 process tree 保存在 `output/v4_next_ops/quick_update_live_query_after_20260908.txt`，terminal query 保存在 `output/v4_next_ops/quick_update_live_query_terminal_20260908.txt`：同一個 run `20260908-49768` 已回傳 `status=passed`、12/12 steps、errors/warnings 空、Task Scheduler `Ready`／`LastResult=0`。既有 05:00 task 於 `2026-09-08T12:00:01+00:00` 自然完成 freshness，status=`passed`、daily／technical=`2026-09-08`、errors/warnings 空；隨後唯讀 Paper gate 於 `2026-09-08T12:01:05+00:00` 回傳 `ready=true`、TWSE 1092/1092、TPEx 866/866 source→DB open readback、`source_db_written=false`、`source_files_written=false`，證據在 `output/v4_next_ops/paper_gate_after_freshness_20260908.json`。Paper EOD 06:00 仍只由自然 task 消費這個 gate，不手動觸發。

Known derived writes 是 D `daily_prices` date-scoped upsert、market／industry canonical CSV 與 full-table SQLite synchronization、broker-flow date replacement、必要時的 120-day technical-indicator derived update，以及 D output 下 quick status/history/log。任何 target raw file 已存在、讀取中變動、容量低於 headroom、官方資料未發布、updater step 失敗或 post-run source→DB readback 失敗，都要停止並讓 Paper gate 維持 blocked。

完成 quick update 後，使用 plan JSON 的 read-only gate command 產生 `paper_gate_after_quick_20260908.json`；只有 gate ready 才能讓 06:00 EOD runner 消費。不能用隔日新 recommendation 覆蓋當日未完成的 frozen execution。

## 後續需要跨 owner 處理的項目

- ML owner：完成並驗證 PIT operational path、source hash、sector mapping 的輸入契約；安排真實盤前 prediction emission、frozen release 與 outcome maturity，盤後 collector 不得自行取得前瞻 credit。
- Paper／Formal owner：以 gate 的 source→DB readback receipt 作為成交依賴；確認 pending symbols、交易日 calendar、正式 consumer 對 missing source 與 `official_no_data` 的處理，不以新日期資料覆蓋待成交決策。
- Scheduler operations：持續保存每個自然日的 task query、quick/freshness receipt、gate attempts、Paper result 與 weekly receipt；將 interactive-only／battery blocked 的缺跑明確呈現給監控。

## 驗證結果

- 排程／Portfolio DST／Paper gate／retry／health focused tests：45 passed（pytest cache 目錄權限 warning 不影響結果）。
- ML forward wrapper／daily producer／registration tests：21 passed；涵蓋真 derived parser、outer failure 優先、nested completion clock、兩個來源互斥、離線 calendar cache、跨週末 predecessor、one-session freshness、create-only config、manifest hash replacement、固定 V2 release pin 與 UTF-16 XML 語意解析。
- `mypy --explicit-package-bases`（Portfolio scheduler、registration、health CLI、gate、retry，cache `output/v4_next_ops/mypy_cache`）：Success, no issues found in 5 source files。
- forward producer／wrapper `mypy --explicit-package-bases`（cache `output/v4_next_ops/mypy_cache`）：Success, no issues found in 2 source files；兩檔 `py_compile` 通過。
- Registration inspection after兩個 trigger mutation與 forward task registration：18/18 available，action/schedule 全部 match，`configuration_ready=true`；forward task registration 後仍是 never-run (`Last Result=267011`)，不能視為自然 run 成功。

## 2026-09-08 raw PIT 自然執行終點

05:05 Pacific 的 `baldr-ml-raw-pit-refresh-daily` 已由同一自然 process chain 完成；
runner／builder PID 28664／55248 先後退出，heavy-chain lock 已釋放，未重啟。terminal
receipt `D:\Min\Python\Project\FA_Data\output\scheduled\ml_raw_pit_refresh\latest_status.json`
為 `status=failed`、`error=raw_pit_builder_failed:2`，builder 原因是
`DailyPriceSourceQualityError: daily price source quality quarantine required: 4476508 candidate rows`。
D 槽當時仍有約 310.74 GiB free，SQLite 是 `ro/query_only`、`writes_source_database=false`；
因此這次不是容量不足，也沒有寫入來源 DB。compact ops snapshot 在
`output/v4_next_ops/raw_pit_refresh_observation_20260908.json`。

這次 failure log 前段的舊成功 manifest 不屬於本次 run；本次 terminal 行只應讀最後的
quality guard error。root 的有界 route probe `output/v4_next_root/raw_quality_market_route_probe.json`
已分出兩類供 ML／資料品質 owner 處理：symbol `6488` 在 TWSE-only route 的 1 筆
source missing，以及 TPEx route 以 `990.0`／`990.00` 這類相同數值不同字串表示造成的
1 筆 OHLC mismatch。這些是 quarantine
根因線索，不是已批准的資料修復；不得刪除或覆寫既有 raw／SQLite。後續 raw runner 已補上
bounded `source_quality_summary`，future terminal receipt 會保留分類計數與少量樣本，不
再要求產生數百萬筆 JSON。

本輪可交付的穩定檔案為：`scripts/scheduled/prepare_ml_allocation_forward_config.py`、
`scripts/scheduled/run_ml_allocation_forward_daily.py`、
`scripts/scheduled/run_ml_allocation_forward_daily.cmd`、
`scripts/scheduled/ml_forward_scheduled_config.schema.json`、
`scripts/scheduled/ml_forward_task_registration_plan.json`、
`scripts/scheduled/ml_forward_task_registration.xml`、
`tests/test_ml_forward_scheduled_wrapper.py` 與
`tests/test_ml_forward_task_registration_plan.py`。即時資料與 calendar／gate／quick
readback 均只保存於 `output/v4_next_ops/`，不應與來源 D 槽資料混淆。

本 handoff 保留變更前 scheduler XML 於 `output/v4_next_ops/scheduler_backup_before/`；如需回復 Paper EOD 時間，只能由受控 Windows session 依該 backup 和 root 審核的 XML 差異執行，不能用 aggregate registration 覆蓋其他 task。

## 2026-09-08 forward calendar preemptive refresh

實際 caller 已核對為 `scripts/scheduled/run_paper_execution_daily_isolated.py:641`：
Paper EOD isolated scope preflight 通過後會呼叫 `refresh_twse_calendar_cache`，其
cache root 與 forward producer 相同，都是
`output/paper_execution_eod_replay/calendar_cache/`。它是 create-only、最多兩次
bounded GET；有效 cache 只讀回，過期才依 response completion time 建立新檔，失敗時保留
既有檔案。這條 caller 無法保證 Paper 06:00 仍早於稍後 forward cutoff 的 cache expiry，
因此不能單靠「當日 Paper 已 refresh」作為長期保證。

已新增 `scripts/scheduled/run_official_calendar_cache_refresh_daily.py`，並接到現有
`run_ml_allocation_forward_daily.cmd` 的正常流程前置步驟。它以實際 Asia/Taipei
時鐘計算下一個 08:30 cutoff；只有 annual cache 的 verified `expires_at_utc` 不涵蓋
該 cutoff 才呼叫既有 `scripts/capture_official_trading_calendar_cache.py`，輸出檔名
使用實際執行時間與唯一尾碼，舊 immutable capture 永不覆寫／刪除。capture 後會重新
讀取同一檔案、驗證 raw response hash、完整年度、captured／expires timestamp；任何
network、path、hash、future timestamp 或 expiry failure 都寫入
`output/v4_ml_forward_scheduler/calendar_cache_refresh/` 並使 forward producer／child
不啟動。`--preflight` 只驗路徑，不發網路、不寫 receipt。

當前 2026-09-07 capture 的實際 expiry 是 `2026-09-14T12:20:27-07:00`；這說明
2026-09-14 06:00 Paper 仍可能讀到 valid cache，但同日 16:15 forward 已不能使用它。
前置 wrapper 以 horizon 判斷並於需要時建立下一個 immutable capture，沒有固定 9/9
或未來日期注入；若 cutoff 落在 1 月，會同時驗證前一年與當年 annual cache，避免
跨年 predecessor 缺件。每次新 capture 的 verified `expires_at` 還必須嚴格晚於該
horizon，否則 fail closed。測試 `tests/test_scheduled_forward_calendar_refresh.py`
覆蓋 horizon 內有效 cache、即將過期的 preemptive refresh、過期且 network failure
fail closed、capture expiry 不足、preflight 無寫入、輸出 root escape、跨年 cache，
以及不同 Pacific DST 對應；目前 7 tests passed。真實 CMD preflight（證據
`output/v4_next_ops/forward_calendar_refresh_cmd_preflight_20260908.txt`）exit 0，
refresh 與既有 forward preflight 均為 ready，network attempts=0、child_started=false。

## 2026-09-08 natural chain closeout

本次自然鏈的 05:10 recommendation receipt 為 `status=passed`、`decision_date=2026-09-08`，
`result_id=scheduled_rec_20260908_051021`，產生 5 筆 recommendation、200 筆 screening、
195 筆 why-not 與 180 筆 liquidity payload。它仍是 research-only，
`writes_evidence_db=false`、`auto_trading=false`；exclusion quality 為 `degraded`，
並保留 `screening_matrix_persisted_v1`／`screening_contains_unknown_evidence` 兩項觀察。

05:15 evidence dry-run 自然 receipt 為 `status=degraded`、`exit_code=0`、
`pipeline_overall_status=degraded`。阻塞項是
`portfolio_alert_not_ready`／`risk_prompt_not_ready`，source coverage 亦明確列出
`portfolio_alert_snapshot_section_missing`／`risk_prompt_snapshot_section_missing`；
`manual_action_required=true`、`scheduler_readiness_after=not_ready`、
`production_scheduler_allowed=false`、`writes_evidence_db=false`。這是受控 fail-closed
結果，不能解讀為 evidence production ready。

05:30 `baldr-ml-direct-chain-maintainer` 在本次觀測（約 Pacific 06:05）仍為
`status=running`，heartbeat=`2026-09-08T13:05:04.540970+00:00`，
`execution_started=false`、`execution_disposition=new_owner_requested`。容量 preflight
仍在既有 headroom／persistent／temporary budget 內（free bytes=`333590917120`），
`query_only=true`、`writes_source_database=false`、`destructive_action_performed=false`；
因此只保留 running evidence，不能稱 Direct／OOC 已完成，也沒有停止或重啟自然程序。

06:00 Paper EOD 已由新 trigger 自然消費 ready gate。最新 operational receipt
`output/paper_execution_eod_replay/receipts/paper_execution_2026-09-08_9330c91d89344056_20260908T130006868388Z.json`
為 `status=machine_verified_candidate`，`decision_date=2026-09-07`、
`execution_date=2026-09-08`；這個 T-1 decision date 是 frozen execution contract，
不是缺少 9/8 recommendation。candidate-only／research-only、broker order 與正式 credit
均為 false。append-only ledger 已寫入 8 筆並以 read-only transaction 讀回驗證，狀態為
6 filled、1 partially_filled、1 rejected，cash projection 與獨立 Decimal readback 均為
`161526.11`；逐欄結果見 `output/v4_next_root/paper_natural_eod_20260908_readback.json`。
同次 gate receipt `dependency_gate_20260908T130002686981Z_attempt1.json` 為
`ready=true`、quick／freshness 同日通過、blockers 空、`source_db_written=false`、
`source_files_written=false`、`query_only=true`。

同次 Paper calendar refresh 的 annual cache 為 `cache_valid`、
`refresh_attempted=false`、annual `network_attempts=0`，目前 immutable capture 的
`expires_at=2026-09-14T19:20:27.355937+00:00`。因此 9/14 06:00 Paper 可能仍可讀取它，
但 16:15 Pacific forward cutoff 已在 expiry 後；已接入的 forward pre-step 會依實際下一個
Asia/Taipei 08:30 horizon 做 preemptive refresh，不能以本次 Paper 的 valid 結果取代該檢查。
本輪尚未執行 16:15 forward task，也沒有手動觸發 forward／Raw／Direct。

完整收斂摘要（包含兩個早晨 receipts、Paper／gate／calendar 與 Direct running 狀態）為
`output/v4_next_ops/paper_direct_natural_closeout_20260908.json`；舊 Pacific 00:05
receipt 仍只作變更前歷史，不與本次 06:00 結果混用。

## 2026-09-08 evidence Paper source 與 Direct projection 收尾

本片新增 `app_module/paper_decision_desk_evidence_source.py`，把 evidence 的
portfolio alert source 接到實際 repository Paper ledger、isolated Paper status 與
position-health baseline。它以單一 SQLite read transaction 讀取請求日前最近的
snapshot／positions，並保存 canonical row digest、SQLite `data_version`、status bytes
hash、health baseline hash、snapshot date／id 與 read-only／research-only boundary。
它不呼叫手動 `PortfolioService` JSONL，也不寫入 Paper、D 槽或 evidence DB。

`scripts/run_evidence_pipeline.py`、
`scripts/scheduled/run_scheduled_evidence_pipeline_dry_run.py`、同名 CMD／PowerShell
wrapper 已接上明確參數：`--paper-evidence-operation-root`、
`--paper-evidence-health-baseline`、`--paper-evidence-status-path`、
`--paper-evidence-health-status-path` 與 `--paper-evidence-ledger-db`。scheduled 預設使用
repository `output\paper_execution_eod_replay` 的 Paper state，health baseline 使用
當次 output root 下的 `position_health\latest.json`（由 05:15 daily refresh 產生），並以
`scheduled\paper_portfolio_isolated\latest_status.json` 作為 health coverage receipt；完整 provenance
放入 stored Decision Desk snapshot metadata。Paper alert 會再供既有 risk prompt service
推導，不會由 scheduler 合成 ready 證據。

實際隔離 probe 讀到 2026-09-08 Paper snapshot `paper-main-20260908` 及三筆 positions，
health baseline 為 2026-07-12、已超過 31 日上限；因此結果是 `degraded`，保留三筆
真實 `WATCH` attribution、stale warning 與完整 hash provenance，沒有 blocker 以外的
人工猜測，也沒有把 readiness 提升為 ready。缺檔、未來日期、coverage／schema／boundary
不符、來源 bytes 於讀取期間變更時，source 會回傳 `unknown`／`MISSING` 並不建立
attribution／prompt。這個 probe 是接線驗收，不是重跑 2026-09-08 05:15；當日原始
05:15 receipt 仍保留為變更前 `portfolio_alert_not_ready`／`risk_prompt_not_ready` 的
歷史 fail-closed 結果，後續自然日才消費新接線。

source coverage 現在分開記錄 `*_snapshot_available`、`*_capture_ready` 與
`*_snapshot_quality_not_ready`。有內容但 degraded 時不再錯誤標成
`*_snapshot_section_missing`，同時仍保留 `portfolio_alert_not_ready`／
`risk_prompt_not_ready`；因此 evidence 可追溯性增加，但 production／formal readiness
沒有被隱藏或放寬。Formal owner 可依此接線：先呼叫
`PaperDecisionDeskEvidenceSource.build(decision_date)`，只消費回傳的已驗證 summary／
metadata；缺來源或 unknown 要阻擋，不能填 0 或沿用隔日資料。

本片也把 `scripts/scheduled/run_ml_direct_chain_maintenance.py` 的外層狀態改為以已驗證
inner stage 與 child command line 投影。`execution_started` 不能由 launcher 存活單獨
推導；`fit_completion_verified` 必須同時有 inner stage、OOC 與 release 的 complete
證據。當前 live chain `direct-ooc-3cec102bc9f96e2219319560` 仍是
`complete=false`，已完成 years=`2014`，目前 stage 為
`assembly_decision_2015-01-16_rows_14421_processed`；保留現行 PID／checkpoint，沒有
停止或重啟，也沒有宣稱 fit／release 完成。現行已載入的 supervisor 不會因磁碟檔案
變更而 reload；新的投影要等下一次自然 process 啟動，或由獨立唯讀 inspector 讀取並顯示。
僅看到 launcher
running 仍不得授予完成語意。

本片檢查結果：Paper source 加既有 Direct 測試在隔離設定下 `19 passed`；Evidence
runner／CLI／scheduled wrapper 既有測試 `23 passed`；mypy（Paper source、runner、CLI、
scheduled wrapper、Direct maintenance）與 py_compile 均通過。先前另一 owner 的
`data_module/portfolio_ml_dataset_assembler.py` 暫時性語法狀態已由獨立 compile(read_bytes)
驗收解除；本 handoff 不再把它列為目前阻擋。穩定實作與測試檔案如下：

- `app_module/paper_decision_desk_evidence_source.py`
- `tests/test_paper_decision_desk_evidence_source.py`
- `app_module/position_health_baseline_service.py`
- `app_module/position_health_daily_refresh_service.py`
- `scripts/run_position_health_daily.py`
- `tests/test_position_health_daily_refresh_service.py`
- `app_module/evidence_pipeline_runner.py`
- `scripts/run_evidence_pipeline.py`
- `scripts/scheduled/run_scheduled_evidence_pipeline_dry_run.py`
- `scripts/scheduled/run_evidence_pipeline_dry_run.cmd`
- `scripts/scheduled/run_evidence_pipeline_dry_run.ps1`
- `scripts/scheduled/run_ml_direct_chain_maintenance.py`
- `tests/test_scheduled_ml_direct_chain_maintenance.py`

## 2026-09-08 daily position-health refresh

為避免 health baseline 永久停留在 2026-07-12，新增
`app_module/position_health_daily_refresh_service.py` 與
`scripts/run_position_health_daily.py`。producer 以 repository Paper SQLite 的同一個
read-only transaction 選取 `as_of_date` 前最近 snapshot，驗證同一個 Paper daily status
與 boundary，再由既有 `PositionHealthBaselineService` 建立相同的 health schema。它只
寫 derived health directory 的不可覆寫日期檔、atomic `latest.json` 與
`latest_status.json`；Paper SQLite、D 槽來源、Paper status 與 positions DB 都不會寫入。

05:15 scheduled wrapper 已加入 `--refresh-paper-health` 接線；CMD／PowerShell 排程入口
會在 evidence child 前執行這個 producer，並把 `latest.json` 傳給 evidence。producer
成功時日期檔以 Paper snapshot 日期命名，重跑相同 bytes 會 reuse；同日 bytes 改變則
建立 hash suffix 新檔並保留舊檔。producer blocked 時，wrapper 傳入不存在的 sentinel
path，使下游 source 明確回傳 unknown／MISSING，不會沿用 stale latest baseline。
此時即使 evidence child 偶然回傳 exit code 0，wrapper 仍會寫入 `status=failed`、
`exit_code=2`、`pipeline_exit_code=0` 並以非零退出，讓 Task Scheduler 明確揭露
health refresh 阻擋。

每日 refresh 只更新持倉觀測與來源 provenance；它不評估 thesis、invalidation 或當日
condition。缺少的人工作業欄位仍是 `None`、`required_human_fields` 與 WATCH／unknown，
不得把新 `observed_at` 解讀成 thesis 已更新。只有前一份 baseline 的
`source_snapshot_id` 與本次 snapshot 完全相同，或同一 Paper preopen status receipt
已把前後 snapshot identity 綁到同一份 ledger 且 transaction row digest 證明期間沒有
該代號事件時，才會保留連續持有的人工欄位。snapshot 變更、同代號重新進場、缺少
coverage receipt 或 ledger 讀回不完整時，舊 thesis／review／state 只作歷史來源，
當前列回到 WATCH／unknown，不會把 CLOSED 或 EXIT_CANDIDATE 投影到新持倉；歷史
人工欄位與舊 reasons 仍保留在 `historical_prior_health_fields` 等欄位。未知內容仍
fail closed。
因此 fresh source 的 health quality 仍可能因 thesis 未填而 degraded，這是可追溯的真實
缺口，不是用日期更新掩蓋 readiness。

實際隔離 readback `output/v4_next_ops/position_health_probe_20260908_v3/` 讀到
`paper-main-20260908`、3 positions、snapshot rows hash
`sha256:f25fe9254bcbf36a55d0c8670867494766281072f9a4bc29c64f71f8885f4bf9`，producer
receipt 為 `status=passed`、`writes_positions_db=false`、`writes_paper_state=false`；
baseline 三筆皆為 WATCH，entry thesis／invalidation／holding horizon／review date
仍缺失。這是實際 repository source 的接線證據，沒有寫回 D 原始資料。

daily producer 測試 `tests/test_position_health_daily_refresh_service.py` 覆蓋同一交易
snapshot、同 snapshot 保留既有 human fields、ledger coverage 下跨日期連續持有、
closed→reentry 不繼承、缺 coverage／status blocked、同日 immutable history；baseline
service／daily producer／scheduled wrapper 合計 `14 passed`（另有 pytest cache 權限
warning）。

本次跨日期 lineage 收緊後的實際 readback 位於
`output/v4_next_ops/position_health_probe_20260908_v4/`。它使用 repository
`paper_portfolio_isolated/latest_status.json` 作為 preopen coverage receipt、同一份
`paper_trade_ledger.sqlite`，並以 state DB 的前後 snapshot identity 與限定持倉代號的
transaction row digest 綁定來源；本次 snapshot 與前一份 baseline 同 ID，因此
`entry_lineage_verified=true`，沒有改寫 Paper state 或 D 槽。不同 snapshot 若缺少
coverage、ledger schema／hash／row readback 或發現期間有 buy／sell，則只保留
`historical_prior_health_fields`、`historical_prior_reasons`，當前列維持 WATCH／unknown。

Root 的 fresh-source consumer readback 位於
`output/v4_next_root/health_fresh_evidence_readback.json`：health age 已回到當日、3
個 position alerts 均有來源且整體仍為 `degraded`。這證明 Paper snapshot、coverage
與 evidence consumer 的接線；proposal-only `transition evaluator` 也已接入，但實際
thesis、invalidation、horizon、review date 仍可為 unknown，故不能把本次 daily refresh
宣稱為完整的 source-backed daily health evaluation，待後續 Formal／health integration
slice 接續。

本次 wiring 盤點與下一片的最小輸入／輸出／Gate 契約見
`docs/06_qa/V4_POSITION_HEALTH_TRANSITION_EVALUATOR_CONTRACT_2026_09_08.md`，機器可讀
清冊見 `output/v4_next_ops/position_health_transition_wiring_inventory_20260908.json`。
清冊確認 `PositionHealthService`、`PositionHealthStateMachine`、
`PositionThesisContract` 與 append-only transition repository 都可重用；本片已接上
正式 proposal-only daily evaluator caller。`PositionHealthDailyRefreshService` 仍只
負責 Paper baseline 與 lineage；本片新增
`app_module/position_health_source_providers.py` 作為唯一 source-to-caller 邊界，並將
已驗證的 official calendar cache 接入 evaluator。`PositionThesisRegistryProvider`、
`PITConditionSourceProvider` 與 `DecimalMetricSourceProvider` 只接受帶內容 hash、
available／as-of time 與 stable position／entry lineage 的 derived artifact；缺檔維持
degraded，future、竄改或 identity 不符則 blocked。不得把 legacy `PositionService`、
recommendation 文案或 UI cache 混入。

人工 thesis 的建立入口是 `scripts/record_position_thesis.py`。它要求 reviewer 明確
提供完整 `PositionThesisContract` 與 invalidation rules，透過
`PositionThesisRegistryWriter` 的跨程序 lock、atomic replace 與每筆 `record_sha256`
追加 registry；同時保存 writer 實際產生的 `recorded_at`。兩個 writer 不會互相覆蓋
歷史；同 version 的相同使用者語意重試即使 process clock 前進也會保留第一筆 hash／
`recorded_at` 並回報 `idempotent`，矛盾內容或同 effective date 的衝突會拒絕，中斷寫入
不會破壞既有 registry。provider 只在 `available_at` 與實際 `recorded_at` 都不晚於 evaluator 的 decision
cutoff 時給予 PIT credit，因此事後手填舊日期不能回填歷史 credit。沒有人工輸入時不
建立空白 thesis。

### Paper source-to-ID 接線與 9/8 readback（2026-09-08）

Paper snapshot 的正式 schema 只有 `snapshot_id`、decision date、`stock_code`、quantity
與估值欄位；Paper ledger 保存 `fill_id`／`source_event_id`／event date／side／filled
quantity，但沒有 stable `position_id` 或 entry lineage 欄。為避免把代號誤當持倉
identity，新增 `app_module/paper_position_identity_provider.py`，由 05:15 health
refresh 在同一 state DB、ledger 與 isolated Paper preopen status receipt 上做唯讀驗證。
它只掃描 bounded `[previous_snapshot_date, current_snapshot_date)`，排除 current
snapshot 當日盤後事件；只有 source type 合法且已驗證的 filled／partially-filled buy
將數量由 zero 轉為 positive 時，才以 canonical ledger row hash 產生
`paper:{portfolio}:{stock}:entry-{hash_prefix}`。已驗證的 active identity 且期間沒有
flat transition 才能 carry；closed→reentry 必須新 ID；無法證明的歷史維持
`position_id=null`／`unproven`，保留 prior fields 在 history。
v1 ledger 沒有同日 sequence／time，因此同一 stock 同日多筆 material fill 會以
`paper_position_identity_event_order_ambiguous` blocked，不用 `fill_id` 推測 buy／sell
順序；跨日 buy→flat→buy 則只採最後一次可證明的 entry。

與 ML／Paper producer 的接口是讀既有 output：producer 必須持續保存 preopen snapshot
coverage receipt、同一 ledger path、`fill_id`／`source_event_id`、event date、source
type、filled quantity 與 transaction rows hash。此片沒有修改
`data_module/paper_daily_execution_producer.py`，也沒有寫 D 槽、Paper state 或 Formal
ledger；下一個自然 preopen 若出現新的合法 flat→positive event，provider 才會產生新的
deterministic identity。

實際唯讀 readback 在 `output/v4_next_ops/position_health_identity_readback_20260908_v2/`，
摘要收據為 `readback_summary.json`：
baseline `sha256:d684dd2168d7ea60034ee3d07aefd1d38cbad6670b098d7c7232e389bbe10d16`、
snapshot `paper-main-20260908`、3 active rows，coverage receipt `status=ready`，ledger
window `[2026-09-07, 2026-09-08)` 的 row count 為 0。1418／1536／1615 全部維持
`position_id=null`／`entry_lineage_status=unproven`；隔離 evaluator
`transition/latest.json` 回傳 `status=degraded`、3 positions、0 proposals，calendar
verified，missing identity／thesis／PIT condition／Decimal metrics。這是目前來源能
證明的結果，沒有用 9/8 盤後 fill 倒填盤前 lineage。

05:15 wrapper 的 blocked-refresh 負例已由
`tests/test_scheduled_evidence_pipeline_dry_run_wrapper.py` 驗證：舊 latest 存在時仍
使用 missing sentinel、child 假成功不會掩蓋 health refresh failure，wrapper payload
為 `status=failed`、`exit_code=2` 並保留 `pipeline_exit_code=0`。

### Daily transition evaluator 接線（2026-09-08）

`app_module/position_health_transition_evaluator.py` 已建立單一薄 adapter，重用既有
`PositionHealthService`、`PositionHealthStateMachine`、`PositionThesisContract` 與
`PositionHealthTransitionRepository`。它只產生 proposal，event id 綁定 stable
`position_id`、decision date、policy hash 與每筆 position 的 input hash；同一 payload
重跑會回報 `idempotent`，同 position／decision date 出現不同 payload 會 blocked。狀態
合併固定採 `EXIT_CANDIDATE > REDUCE_CANDIDATE > WATCH > HEALTHY`，保留已知較嚴重
狀態與全部 reasons；缺 thesis／condition／metrics／calendar 只回 `degraded`／WATCH，
不生成投資理由、不自動核准。

`scripts/run_position_health_transition_daily.py` 提供獨立 CLI；05:15
`run_evidence_pipeline_dry_run.cmd` 已加入 `--evaluate-position-health-transition`，
scheduled Python wrapper 會把 refresh 後的 baseline 送入同一 evaluator，結果只寫
`<OUTPUT_ROOT>/position_health_transition/` 與其 proposal SQLite。現在 baseline 尚未
攜帶正式 thesis 與 PIT condition artifact，所以自然執行可安全產生 `degraded`；這是
接線成功的 machine receipt，不代表 V4 transition 或完整 health 已完成。官方 calendar
已透過 `OfficialCalendarSourceProvider` 唯讀重驗 cache，9/8 readback 綁定 cache／
response hash、available／expiry 與交易日範圍；thesis registry、PIT current condition
與 Decimal metric 的 caller 已具備；Paper identity provider 也已接上，但 9/8 bounded
window 沒有可證明三筆既有持倉的 entry event，且人工 thesis／condition／metric artifact
仍缺，故仍缺資料而非假裝通過。正式 reviewer approval workflow 仍待後續接線。

9/8 真實 baseline 的來源→隔離 evaluator readback 在
`output/v4_next_ops/position_health_identity_readback_20260908_v2/transition/latest.json`：
baseline hash `sha256:d684dd2168d7ea60034ee3d07aefd1d38cbad6670b098d7c7232e389bbe10d16`、3
個 position、calendar verified、status=`degraded`；三筆均保留 WATCH，缺
stable `position_id`／entry thesis／invalidation／holding horizon／review date、PIT
condition 與 Decimal metrics。readback 沒有 Paper／Formal／raw write。

本片 source providers／identity provider／daily health／evaluator／scheduled caller／
wrapper 的隔離正負矩陣共 `43 passed`（含跨日 re-entry 與同日無序 fill 負例）；另以 `mypy --explicit-package-bases` 檢查 9 個
source／caller 檔案，並完成 `py_compile`。目前仍需後續 owner 接上真正的 PIT condition、
Decimal metrics 與 reviewer thesis workflow，不能把這次 source-to-ID 或 degraded
proposal receipt 宣稱為完整 V4 health。

### Latest correction: market source capture and calendar renewal

官方 calendar 續期 caller 已確認為既有 forward pre-step：
`scripts/scheduled/run_official_calendar_cache_refresh_daily.py` 由
`scripts/scheduled/run_ml_allocation_forward_daily.cmd` 呼叫，依實際 Asia/Taipei
下一個 08:30 horizon 判斷。只有 verified annual cache 不涵蓋 horizon 才呼叫既有
capture CLI；新檔以實際 capture 時間與唯一名稱 create-only 保存，再驗 raw hash、
完整年度及 `expires_at > horizon`。Paper EOD 的既有 `refresh_twse_calendar_cache`
仍共用相同 cache root，但不取代 forward pre-step，也沒有新增另一個 calendar task。
目前 cache expiry 是 `2026-09-14T19:20:27Z`；9/14 06:00 Paper 的有效性不能替
16:15 forward 作保證，forward caller 必須在當次 horizon 再檢查。

每日 health source caller 現由
`app_module/position_health_market_source_producer.py` 產生 condition／Decimal
metrics，再由 `run_scheduled_evidence_pipeline_dry_run.py` 傳給 transition evaluator。
它先驗 quick／freshness receipt，之後才以 SQLite `mode=ro/query_only` capture 當日
selected rows；`condition_YYYYMMDD.json`、`metrics_YYYYMMDD.json`、source receipt
採 create-only immutable payload，同 bytes 重跑才 reuse，異動則保存 hash suffix，
`latest_status.json` 才使用 atomic replace。沒有 verified stable identity 時不掃描
大表，也不以 stock code 代替 position lineage。

本次移除 CLI／scheduled caller 對 `now_provider` 的固定時間注入。自然執行以真實
capture start／completion 記錄，沒有明確歷史 cutoff 時以 completion 作有效 source
decision clock；wrapper 將 source completion 傳給 evaluator。若呼叫端明確指定較早
`decision_at`／`observed_at`，實際 SQLite read 越過該時間會 fail closed。慢讀、
capture-after-cutoff 與來源 artifact 異動測試均已覆蓋，避免用早期 quick receipt 將
目前 DB rows 回填成歷史可得。

實際 9/8 CLI readback 位於
`output/v4_next_ops/position_health_market_source_readback_20260908/`。quick
`completed_at=2026-09-08T11:32:45Z`、freshness `checked_at=2026-09-08T12:00:01Z`，
本次 source capture 起訖為 `2026-09-08T16:57:50.762482Z`，source snapshot hash
`sha256:15ca90632c274d04912da3d9d5469a956179a8a8ce297a376df901bd063b69d4`。輸入
baseline 使用 identity readback v3，hash
`sha256:1e335f4681ddfcecbc33f3c096d778b8c67205f66dd19ff289ee026c2b79831b`；三筆
1418／1536／1615 都沒有可證明 entry event，故 source status=`degraded`、condition
與 metrics row 均為 0，沒有 D／Paper／Formal write。這是合法的缺 identity 結果，
不代表 V4 health 已完成。

本片最新 market source／wrapper 正負測試為 `14 passed`，producer、CLI、scheduled
wrapper 的 mypy 與 py_compile 均通過。待完成項仍是可證明的三筆 stable entry lineage、
reviewer 提供的 `PositionThesisContract`／invalidation，以及同一 lineage 的實際
PIT condition／metrics；在此之前 evaluator 維持 degraded、proposal-only、
`formal_credit=false`、`broker_execution=false`。

### Formal Rule machine policy bridge 與 policy identity 分離（2026-09-08）

本片新增的 `FrozenRulePolicySourceProvider` 只讀並重驗既有
`output/formal_daily_publications/rule_source/scheduler/rule_source_latest_status.json`。
它會重新讀取並 hash stable status、clock manifest、owner acceptance 與 machine
revalidation receipt，檢查 `candidate_only=true`、所有 formal／promotion／broker／
market write boundary 均為 false，以及各 artifact 的 PIT 時間、manifest hash、
source-window hash 與安全欄位。它只把已驗證的 Formal Rule machine metadata 放入
`provenance.policy`，不把 Rule ranking 的設定轉成持倉 thesis、invalidation rule、
holding horizon 或人工作業理由。

兩種 policy identity 必須維持獨立：`result.policy_hash` 與每筆 transition event 的
`policy_hash` 是 Health state machine 實際使用的 transition policy；
`provenance.policy.policy_hash` 是 Formal Rule ranking／source bundle 的來源 hash。
Rule hash 會透過完整 source provenance 進入 position `input_hash`，因此可追溯影響
輸入，但不會覆寫 Health policy identity。若未來要讓 Rule 直接提供持倉失效條件，
必須新增明確版本化的組合 policy（同時包含 Health transition rules 與 Rule source），
並由 owner 另行驗收，不能以欄位重命名或直接沿用目前 Rule hash 代替。

目前實際 Formal bundle 只有排名／安全／來源時鐘資訊，沒有每一持倉的
`entry_thesis`、結構化 invalidation rules、holding horizon 或 next review date；因此
provider 正確回傳 `position_thesis_policy_status=missing`、
`position_invalidation_rules_status=missing`、`holding_horizon_status=missing`，
evaluator 仍會保留 degraded／WATCH。這是資料契約尚未具備的真缺口，不以 machine
policy metadata 偽造健康結論。

本片新增 policy bridge 的 source-provider／evaluator 正負測試後，限定套件執行結果為
`37 passed`；`mypy --explicit-package-bases` 對 source／caller 檔案為零錯誤。正式
05:15 CMD 以 `PAPER_HEALTH_POLICY_SOURCE` 傳入同一 stable status 路徑；缺檔、未來
receipt、hash／schema／安全邊界錯誤會形成明確 blocker，並沿用既有 wrapper 的
fail-closed 行為。這不改 D 槽、Paper state、Formal producer 或 ML owner 檔案。

以目前 repository 的 9/8 baseline 做唯讀 CLI readback，結果保存在
`output/v4_next_ops/policy_bridge_real_readback_20260908/latest.json`：
Health `result.policy_hash` 為
`sha256:b6e849c7d2a8ee55688f8cd4481022f98e847ac6b3e56087344573e197371f16`，
而 `provenance.policy.policy_hash` 為
`sha256:26ac99c06b5afc60f575859730a2185fac83d7714c4369861f2b8a4fa6af4f1b`；兩者
均以實際檔案讀回取得，沒有覆寫。該次結果為 `status=degraded`、3 positions、0
proposals，calendar verified，三筆仍是 `position_id=null`／`unproven`，並保留
`position_thesis_policy_status=missing`、`position_invalidation_rules_status=missing`
與 `holding_horizon_status=missing`。這是 policy bridge 的真實閉環證據，也是目前
不能升級為完整 Health／Exit 的理由。

### 前瞻 Paper machine thesis policy candidate 與新持倉接線（2026-09-08）

候選參數與審核結果集中在
`docs/06_qa/V4_FORWARD_MACHINE_POLICY_CANDIDATE_2026_09_08.md`。root 已核准
research-only baseline：`macd_hist <= 0`、`rsi <= 30`、`adx < 15` 均只產生
`reduce` proposal；20 個交易日是獨立工程觀察窗，5 個交易日是自動 review evidence
cadence，兩者都不是歷史績效或 Rule minimum history 結論。`macd_hist <= 0` 是當日
level，不宣稱已證實負向 cross。policy bytes 在明確 supersede／retire 前保持 immutable；
calendar／source 失效會 fail closed，驗證過的 renewal 只更新觀測／snapshot evidence，
不切換同一組參數的 policy identity，也不要求每日人工續期。

policy producer 已用實際 clock 寫入 approved future-effective artifact：
`output/forward_position_thesis/policies/paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1.json`，
policy hash 為
`sha256:23c3d37f36630b9a9217f41e6d60c50b17ee1bea44b3843edef55c1d904512ee`，
effective date `2026-09-09`，首次 available／recorded `2026-09-08T20:14:46.522133+00:00`。
完整 bytes 的日曆 custody snapshot 是
`output/forward_position_thesis/calendar_snapshots/paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1_74790d36d0cd6639.json`。
首次 activation receipt 為
`.../policy_activation/activation_paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1_772f6656220d35f7.json`；
以遞增實際 clock 重跑後，第二份 observation receipt 回報 `status=idempotent`、
保留原 `available_at`／policy hash，並把現行 observation time 分開保存。最新
observation receipt 為
`output/forward_position_thesis/policy_activation/activation_paper-machine-thesis-benchmark-v1_2026-09-08-approved-v1_ad53dba6002098c1.json`，其 receipt hash 為
`sha256:ad53dba6002098c1b59c082ce5254583bb732b73fa881a9c05f383152a9c551e`。

已完成完整的 policy producer → candidate binder → Paper entry proof → 真實
`PositionHealthMarketSourceProducer`（含 `macd_hist`／`rsi`／`adx` Decimal rows）→
`DailyPositionHealthTransitionEvaluator` 隔離正例；規則觸發 `REDUCE_CANDIDATE`，
但 `apply_transition=false`／`human_approval_required=true`。測試也覆蓋 policy
發布後 calendar source renewal：consumer 仍使用舊 immutable snapshot 驗證同一 policy
identity，新 hash 僅落在 observation receipt。Human registry 與 machine contract
同時存在的正例已驗證 human contract 優先；不能把這項 precedence 解讀成自動核准。
對應端到端測試為
`test_approved_machine_policy_binds_real_decimal_market_source_into_health_evaluator`；
calendar renewal consumer 正例為
`test_calendar_renewal_preserves_policy_identity_and_records_new_observation`。

候選 producer 凍結 policy／recommendation file、content、config hash；binding receipt
保存 Paper entry availability、fill／source event／evidence proof。只對 policy 生效後
的新 `natural_entry_verified` entry 建立
`PositionThesisContract(source_type=machine_policy, source_actor=...)`；既有三筆舊持倉
不升格、不回填，不寫人工 registry、Paper、Formal 或 D 槽。05:15 caller 已接入
`--bind-forward-thesis` 並由 `run_recommendation_snapshot.cmd` 預設指向上述 approved
policy path；目前沒有新的自然 Paper entry，故 real 9/8 readback 仍不能宣稱完整
V4 Health／Exit 已完成。

本片 forward candidate／policy producer 測試為 `22 passed`，其中包含跨來源端到端正例、
calendar renewal consumer、遞增 clock idempotence 與 human precedence；同一輪限定的
source／evaluator／scheduled caller 回歸套件合計 `90 passed`。source／candidate／
evaluator／policy producer 目標檔案的 mypy 與 py_compile 均通過。

### 工作區清理與測試清冊收尾（2026-09-08）

本輪採兩批有限清理。第一批只處理受保護根目錄之外的 repo bytecode／pytest cache：
預定 2,396 筆、50,975,401 bytes，實際移除 2,324 筆、49,587,838 bytes；72 筆因
活動程序持有、存取限制或清理期間變更而保留，沒有強制刪除。第二批只清除過期
`output/qa/full_app_healthcheck_tmp/` QA 報告，145 筆、666,244 bytes、74 個空目錄
均已移除；刪除前逐檔 manifest、hash、大小、mtime 與 rollback plan 均保留。這些
歷史暫存可由既有 healthcheck 重新產生，但沒有 bytes backup，不能宣稱回復當時完全
相同內容。

`.git`、`.venv`、`D:` 原始資料、`output` 正式 evidence／SQLite／WAL／ledger／raw／
checkpoint、`graphify-out` 與活動程序均未刪除。`graphify-out` 當時仍有 5,434 筆
檔案及近期寫入；受保護 output 內的三個 reparse fixture 位於刪除範圍外，也全部
保留。完整清理收尾見 `docs/06_qa/V4_WORKSPACE_CLEANUP_CLOSEOUT.md`；逐檔證據見
`output/v4_next_ops/workspace_cleanup_20260908/`。

測試清冊以實際 `tests/` 目錄重驗為 777 筆，inventory 亦為 777；31 個新增 V4 測試
已依既有責任分類登錄，missing／stale／documentation count drift／markdown link
errors 皆為零。MCP project snapshot 測試改為讀取並比對權威
`docs/00_core/PROJECT_SNAPSHOT.md` 的 path、完整 bytes 與 line count，不再依賴易變
文案。清冊、MCP 與相關測試定向結果為 `14 passed`；Exit caller 與唯讀 AST guard
回歸合併後限定套件為 `31 passed`。

### Exit effectiveness 接入既有 05:15 Evidence caller

`scripts/scheduled/run_evidence_pipeline_dry_run.cmd` 現在在既有
`baldr-evidence-pipeline-dry-run-daily` action 中傳入 `--run-exit-effectiveness`，
沒有新增 Task。`run_scheduled_evidence_pipeline_dry_run.py` 在 position-health
transition proposal 之後以 bounded 120 秒 subprocess 呼叫
`scripts/run_exit_effectiveness_daily.py`，並明確傳入：

- `OUTPUT_ROOT/position_health_transition/position_health_transitions.sqlite`；
- repository Paper `paper_trade_ledger.sqlite`；
- `--db-path` 對應的 market SQLite；
- 已驗證的 Paper operation `calendar_cache`，以及呼叫端明確提供的 temporary
  closure cache；
- create-only `OUTPUT_ROOT/exit_effectiveness/YYYYMMDD.json`。

child CLI 沒有 historical as-of 參數，使用自己的實際 UTC clock，caller 不會將舊
receipt 回填成今日可得資料。timeout、OS error、非零 return、JSON 缺失與 child
blocked 都寫入 bounded log、`latest_status.json` 的 receipt／blocker，並讓 scheduled
wrapper 回傳非零；`degraded` 仍保留研究證據但會在狀態中顯示。producer 既有
`research_only=true`、`historical_backfill=false`、`auto_exit_allowed=false`、
`broker_order_allowed=false` 契約不變，未寫 transition、未下單。

Exit caller、producer、CMD、scheduled wrapper 與 read-only guard 定向驗證為
`31 passed`（pytest cache 因活動程序／權限限制的既有 warning 不影響結果）。尚待
下一個自然 05:15 run 以真實 source 產出第一份 child receipt；在自然 receipt 出現
前，不把 registration 或 mock subprocess 測試宣稱為 live Exit evidence。
