# V4 Next Formal／Paper Hand-off（2026-09-08）

本文件是 `v4_formal_paper` owner 的可重播 hand-off。它記錄本次實際讀回、工程修補、受控設定更新的先決條件與回滾方式。QA output 只保存證據，不能把 repository candidate 直接寫入 D 的正式路徑。

## Ownership

本 owner 負責 `app_module` 的 Formal／Paper service、`data_module` 的 causal ledger／Rule／PIT consumer、`portfolio_module/data` 的專屬 consumer 與 tests，以及 Paper 的股數、現金、費用、稅、跨日承接、hash 綁定、冪等、crash retry 和 readback；也負責非 scheduler script 的 PIT capture／publication、`formal_daily_input_producer`、三來源 identity 與受控設定 handoff 的實作及執行計畫。`v4_schedule_ops` 負責 scheduler 檔案與 Task Scheduler 接線及 quick updater；ML／teacher 由另一 owner 負責。官方價格更新排程由 ops 協調，本 owner 不改 scheduler 檔、不改寫 D 原始資料、不下單、不補造 fills。

## 實際觀測

本次不沿用舊的 `0/3` 敘述；以下均是當次 readback 或本次 QA 產物。

| 項目 | 當次證據 | 結果 |
| --- | --- | --- |
| Formal readiness | `output/v4_next_root/formal_readiness_baseline.json`，`training_as_of=2026-09-08T09:29:59.1264249+00:00` | 3 個 explicit path 都仍是 `D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260819\...\manifest.json`，檔案不存在，`formal_ready=0/3`。 |
| Runtime custody | `output/v4_next_formal/formal_controlled_environment_attestation_20260908.json`；file SHA-256=`sha256:122eb934e04b2c9de2b60b42e4bab943cce123b3036f17d64355c7f73283f153` | 三個 Formal path 的 effective source 均為 `process_environment`，process path 與 effective path 相符，Windows user/system registry 沒有同名值；controlled store 與 HMAC store 均已設定，未輸出 secret。 |
| Handoff plan | `output/v4_next_formal/formal_controlled_handoff_plan_20260908.json`；plan hash=`sha256:fb150caabade643d429e30b269fd1345b40d0e94a2998b2bcc5eef3cb01cafb2`；file SHA-256=`sha256:bbf59ecea6b9285b2bf23eee78365f3e7a712be797f3073f5b7c8cd5f8daf6b7` | `status=blocked`，原因是尚未由 owner 明確提供三個 proposed path、同一 clock manifest 與共同 identity manifest；沒有自動猜選。current 舊路徑只作診斷與 rollback target。 |
| Paper queue | `output/v4_next_root/paper_queue_actual_now_review.json` | 實際 resolver 選到 `scheduled_rec_20260907_051003.json`，`reason=pending_execution_retry`；19 份 receipt 中 9 份合法 pending，2 份 calendar-failure 因 `execution_date_missing` 被拒絕，calendar issues 不阻擋合法 pending。 |
| Paper cross-day | 同一 Paper queue QA | 新自然日 source 不會悄悄切走舊 pending；跨日回傳 `pending_execution_session_missed:2026-09-08`，`late_replay_policy=no_historical_backfill_pending_session_missed`，保留實際 `recorded_at`，不給 elapsed credit。 |
| Paper terminal source | `output/v4_next_root/operational_baseline.json` | EOD source／Paper fill source 仍缺，沒有 terminal receipt、fill 或 ledger；不得以 candidate 或 snapshot 補成成交。 |
| 其他 Formal blockers | `output/v4_next_root/operational_baseline.json` | causal ledger source／Paper fill source 缺件；PIT history coverage start 缺失且同日 multiple distinct captures；這些由 source／ops handoff 補件後再由同一 consumer 重驗。 |

Runtime attestation 證明的是本程序目前採用的來源：在本次程序中三個 path 由 inherited process environment 提供，並非 registry adoption。這不是新 clock，也不是正式 3/3；受控設定仍保持不變。

## 已完成的工程修補

### Paper queue 的內容綁定與 retry

`data_module/paper_daily_execution_producer.py` 現在以 `(portfolio_id, execution_date)` 保存 pending pin，讀回 `waiting`／`failed` legacy receipt 時先完整驗證 receipt、candidate、source file hash、source content hash、result ID、decision／execution date、recorded-at timezone 和 blocker 語意；只接受純 source 缺件或合法 waiting blocker。混合 `missing source + future/clock/identity/timing/session-missed` 的 receipt 會拒絕 adoption，不能被一個缺源字串掩蓋。

同一日已有合法 pending 時，resolver 固定使用其 exact source；較新的 05:10 recommendation 不覆蓋舊 pending，也不先寫 superseded。缺源在合法日內到達時可 retry，retry 不重算 decision、不補 elapsed credit；跨日則以明確 `pending_execution_session_missed:<date>` 結束該 pending session，保留 `recorded_at` 與 no-historical-backfill policy。calendar failure receipt 只留在 issues，不會攔截已驗證的 pending。

### Paper ledger 的 atomic append 與 identity scope

`app_module/paper_trade_ledger.py` 的 `append_many()` 先在 batch 內驗證 `fill_id` 與 `(portfolio_id, source_event_id)`，再以明確 `sqlite3.connect`、`BEGIN IMMEDIATE`、commit／rollback／`finally close` 寫入；existing row conflict 會精確拒絕，連線必定關閉。`source_event_id` 契約是 `portfolio_id:source_event_id` composite scope：來源系統事件 ID 在不同 portfolio 可合法重用，同一 portfolio 仍冪等拒絕；`fill_id` 仍為 ledger-wide primary key。Formal 的單一 portfolio readback 另行驗證其來源內事件唯一。

Ledger readback 保留 Decimal gross／fee／tax／net 與股數，測試涵蓋兩 writer 競爭時一筆 commit、一筆精確 duplicate rejection，以及費用後現金守恆。沒有把失敗 receipt 變成 fill，也沒有寫 broker。

### Formal controlled environment handoff

新增 `data_module/formal_controlled_handoff.py` 與 `scripts/qa_formal_controlled_handoff_plan.py`。它們只讀現行 effective environment 與三個 exact consumer，並 create-only 寫 QA plan。提案必須逐項傳入：

1. `BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH`；
2. `BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH`；
3. `BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH`；
4. 經 `load_clock_manifest_for_capture()` 驗證的 proposed clock manifest；
5. producer 共同產出的 identity manifest，逐項綁定 path hash、file hash、`clock_id` 與 `clock_manifest_hash`。

任何一項缺失、部分提供、路徑不存在、consumer readback 非 `formal_ready=true`／`formal_consumer_compatible=true`、或三路 clock identity 不一致，都保持 `blocked`。current 舊設定的失敗只保留在 `current_controlled_configuration.consumer_blockers`，不會阻擋一組完整的新 proposed bundle 進入 root review。

## 真實 source→fill→ledger→Formal 執行順序

這是可執行的更新順序；每一階段都必須留下 immutable receipt，任何失敗都停在該階段。

1. **Ops 取得官方當日價格來源。** ops 以既有資料更新排程／DB 接線取得 2026-09-08 EOD 所需 rows，保留 D DB 的 before／after hash 與 source-date evidence；只可做核准的 non-destructive derived DB 增量，不回寫或刪除 D 原始來源。缺源的 00:05 Pacific run 可在 06:00 Pacific 以同一資料日／版本 guard 合法 retry，不能把晚到資料冒充早已取得。
2. **Paper recommendation pin。** producer 讀 durable recommendation 與相同 `decision_date`／`execution_date`／version；若已有 pending，先驗 hash/content/source/date，固定原 decision。新 recommendation 只能排隊，待舊 pending terminal 後才可依規則 supersede；跨日 missed 只輸出 explicit late replay/no-credit。
3. **Paper source→fill。** EOD consumer 只在實際 source rows 到達、自然時序與 PIT／session gate 通過後建立精確股數 fill；不以 snapshot、backtest、candidate、cash-only row 或 estimated price 補 fill。receipt 需綁 source file hash、source content hash、decision／execution date、recorded-at、版本與 recommendation identity。
4. **Fill→Paper ledger。** 以 `PaperTradeLedgerRepository.append_many()` atomic append；同批與既有資料驗證 `fill_id`、composite source identity、Decimal gross／fee／tax／net、quantity／status、turnover、execution gap。commit 後重新 query-only readback，核對 receipt→fill identity、股數和現金／費稅守恆；crash retry 只能重播同一 hash-bound fill。
5. **Paper source custody→causal ledger。** producer 將真實 Paper snapshot／fill source、portfolio transition、cash／fee／tax 與 non-cash state 組成 append-only causal ledger candidate，寫入隔離 publication root；在 immutable manifest、source hash、clock identity 和 transition chain 完整前保持 candidate-only。
6. **PIT path。** Formal／Paper owner 以官方 08:30 前 capture、單一同日 capture、獨立 denominator、history coverage start 和 license/source registry 建立 sidecar；`v4_schedule_ops` 只負責 wrapper／Task Scheduler。post-cutoff 由 `portfolio_ml_dataset_assembler._spool_sector_memberships` 重驗，multiple distinct captures 或 coverage 缺件都 blocked。
7. **Rule path。** Formal／Paper owner 在自然合法 session 產生同一 proposed clock 的 Rule history，保留 owner policy、universe、snapshot content 和 producer receipt；現有 repository Rule candidate 不可直接填 D 受控 path。
8. **三路 consumer readback。** 以 `data_module.formal_daily_input_producer._readback_explicit_formal_sources()` 逐路重驗 ledger、Rule history、PIT sidecar；三路均 ready 且 receipt 的 `clock_id`／`clock_manifest_hash` 一致後，才形成 identity manifest。此步不使用「目錄看起來像最新」作 identity。
9. **Root review 與整批設定更新。** 將 identity manifest、三路 readback、proposed path/file hash、controlled-store identity、runtime attestation 和 rollback snapshot 放入 `formal_controlled_handoff_plan`，由 root 審核這個具體 plan。核准後由 owner／ops 在一次受控操作中更新三個 explicit path 值；不變更 HMAC／store ID，不做部分更新，不自動發現檔案。
10. **更新後驗證。** 立即重新執行 environment preflight、三路 exact consumer、Formal readiness 和 Paper operational readback；只有 3/3、Paper terminal receipt、source→fill→ledger readback 與 PIT coverage 都成立時才進入相應 Formal credit。任何 mismatch 都依 rollback plan 恢復三個舊值並保持 `formal_oos_allowed=false`。

## 2026-09-08 新 clock／calendar custody 與 Rule-only 邊界

以下取代本文件較早的 TEMP candidate／placeholder command 描述，均已用明確路徑
實際讀回；沒有重抓、覆寫或更新 D 受控設定。

| 產物 | 精確路徑與 hash | 當次結果 |
| --- | --- | --- |
| Official calendar durable bundle | `output/formal_daily_publications/calendar_candidate_archive/2026-09-09/1b6227dd0464eded-aff4c96e1edab151/v4_calendar_20260909_20260908_104849140.json`；bundle hash=`sha256:1b6227dd0464edede4d3d0a3a50679f3a241e3c82eb8f61448cdb7a82c2eb062`；file SHA=`sha256:8d3a55304982cba8976f6a31596df00b875f09368f54aa980adf1e2d8e1bca23` | raw/metadata 2 entries 與 inline base64 逐一相等；9/9 TWSE、TPEx 均 open；`candidate_only=true`、`formal_clock_created=false`。 |
| Calendar raw manifest | 上述 bundle 相鄰 `v4_calendar_20260909_20260908_104849140_raw/manifest.json`；manifest hash=`sha256:aff4c96e1edab151d1e2a6dfe30319c41ecdf9306b0dec03386d735ad6ffd9e9`；file SHA=`sha256:2c870ffbbe2886c269b89d6461190b08cc39a9788f855762535b1792d721a8a9` | durable source bytes 可在 TEMP 不可用時獨立重建整個 22 日 bundle。 |
| Clock planning report | `C:\Users\archi\AppData\Local\Temp\v4_formal_clock_20260909_candidate_v4\planning_report.json`；plan hash=`sha256:263d31852b64b95bc45a703489315b72f8d0f66f91ecc20a420828015f0fd274` | `schema=prospective-formal-clock-planning.v1`、`status=candidate_ready`、lookahead 31 僅為選取上界；此 report 不當作 clock。 |
| Immutable clock durable archive | `output/formal_daily_publications/clock_candidate_archive/2026-09-09/d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1/clock/manifest.json`；manifest hash=`sha256:d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1`；file SHA=`sha256:a4d5eb8f771bc5f24651eaa8cc6492d939d72766e42f2e6609aec78dd0d53eb2` | `load_clock_manifest(now=2026-09-08T11:19:38.145559+00:00)` 通過；`activation_trading_day=2026-09-09`、`status=planned`，仍 simulation-only。archive hash=`sha256:d3404b55de95ddb7b3a9d63cc4d0b1120f2655e052e6f12697d325e301281709`。 |
| Identity source mapping | `output/v4_next_formal/formal_clock_identity_source_mapping_20260908_v2.json`；file SHA=`sha256:3246198e9c83eae486b56928ca2ad2082cc701e0391bb255b301fbe5c8d2f068` | 八個 source reference 均通過獨立 hash readback；D 原始 owner acceptance 的 file SHA 為 `sha256:aed56ef...`，與 machine-revalidated repo acceptance 的 `sha256:d3aec53...` 分開保存。 |
| Preparation plan | `output/v4_next_formal/formal_next_clock_preparation_plan_20260908_v6.json`；plan hash=`sha256:e1e341876bbd401788664af4d8ca4f8822bd2ccedae6cdb9b1fb0ed01628ff6f`；file SHA=`sha256:ff486388970eb42752afb715cdeb0a061e90b22f39b5a6405537c98365c2e6d8` | `status=ready_for_root_review`、`blockers=[]`；calendar／planner／clock／D-1 PIT 已完成；activation-day PIT、Rule 9/9 publication、Paper fill、causal ledger、common identity 仍依自然時窗及真實來源。 |

clock 的 `candidate_model_hash=e0b9256...` 與 `candidate_feature_manifest_hash=92140d5...`
可回溯到 D `clock-20260828/metadata/candidate_model.json` 與
`candidate_feature_manifest.json`，但兩檔均 `status=disabled`、`training_performed=false`、
`features=[]`。policy／evaluation／calibration hash 也只沿用明確 Rule source metadata；
active universe `5bc52f...` 來自 2026-09-07 machine-revalidated Rule source，舊 owner
acceptance 的 `4e4d9b...` universe 不被回認為新 universe。因此本 clock 的
`identity_scope=rule_only_simulation`、`ml_identity_verified=false`、
`promotion_allowed=false`；它可供 Rule/PIT/ledger 準備，不能證明 ML 訓練或接入 Formal
promotion。ML owner 之後須提供 frozen model bytes、feature manifest、training cutoff
與 receipt 的實際路徑／SHA，再以新 immutable clock 重跑三路 consumer。

實際可重播命令順序已由 v6 plan 固定：讀回 durable calendar raw custody、讀回 planner
report、以實際 observed timestamp `load_clock_manifest`、在 9/9 台北 08:30 前消費
2026-09-08 的 D-1 PIT candidate，之後才由 scheduler 執行 PIT sidecar、Rule publication、
Paper EOD 與 causal producer。D-1 candidate 的 `effective_from` 保留 2026-09-08，
`available_at=2026-09-08T10:28:09.898861+00:00`，不把它改寫成 9/9 capture 或歷史信用。
Paper wrapper 時刻只採用 ops 傳入的 `root-v4-schedule-review-20260908` 證據：06:00
America/Los_Angeles（台北 21:00 PDT／22:00 PST）；本模組不另造時區 SSOT。

### 9/9 可部署候選 runtime 設定

已用目前程式重新讀取 durable source，產生 [formal_9_9_candidate_runtime_config_20260908_114000.json](../../output/v4_next_formal/formal_9_9_candidate_runtime_config_20260908_114000.json)。檔案 hash=`sha256:43c8d52a62a61fe962d8ef5788f0126d745838b68aa92c13c999f1576edf9557`，內容 hash=`sha256:8871988672f4aa3fcbf2b58296a5f3b589b7269397be75037c23f1891f8c8350`，`status=candidate_ready_for_root_review`。產生器為 `scripts/build_formal_9_9_candidate_runtime_config.py`；它對 durable calendar／clock、D `clock-20260828` parent、1984-row D-1 PIT archive 與兩個 wrapper path 做 readback，輸出採 create-only。相同輸出路徑再次執行會以 exit `2` 拒絕覆寫。

目前給 Ops 的 exact task／wrapper 契約如下；scheduler 檔與 Task Scheduler 設定仍由 `v4_schedule_ops` 維護，本 owner 沒有改寫：

| Task／自然時窗 | Exact action | 輸出與 gate |
| --- | --- | --- |
| `baldr-pit-sector-membership-preopen-capture-daily`；Pacific 16:00，台北 07:00 PDT／08:00 PST | `cmd.exe /d /c "C:\Projects\PythonProjects\technical_analysis\scripts\scheduled\run_pit_sector_membership_preopen_capture.cmd"` | 先呼叫 Rule preopen，再建立唯一 `pit_candidate_archive/2026-09-09/<capture_hash>-<receipt_hash>`；`captured_at`、`archived_at` 必須早於台北 08:30。 |
| `baldr-formal-pit-sidecar-postcutoff-daily`；Pacific 18:00，台北 09:00 PDT／10:00 PST | `cmd.exe /d /c "C:\Projects\PythonProjects\technical_analysis\scripts\scheduled\run_formal_pit_sidecar_postcutoff.cmd"` | 只讀 preopen archive；在獨立 denominator、coverage、license、單一 natural-day content 與 assembler readback 通過後才產生 `pit_sector_membership_formal/2026-09-09/sidecar.json`／`receipt.json`。 |
| `baldr-formal-input-producer-daily`；Pacific 21:25，台北 12:25 PDT／13:25 PST | `cmd.exe /d /c "C:\Projects\PythonProjects\technical_analysis\scripts\scheduled\run_formal_input_producer_daily.cmd"` | `FORMAL_DAILY_RULE_SOURCE_ROOT` 啟用完整 hash resolver；candidate／blocked 以 exit `2` 結束，不能當成 3/3。Paper snapshot 使用 repository isolated SQLite；causal ledger 仍等真實 fill。 |
| `baldr-paper-execution-eod-replay-daily`；Pacific 06:00，台北 21:00 PDT／22:00 PST | `cmd.exe /d /c "C:\Projects\PythonProjects\technical_analysis\scripts\scheduled\run_paper_execution_daily_isolated.cmd"` | 來源自然時窗為台北 15:00 後；沿用 frozen pending 的 date/version/source guard，同日 retry 可重播同一決策，沒有真實 fill receipt 就不建立 ledger row。 |

Rule wrapper 的環境值固定記在 candidate config：`DATA_ROOT=D:\Min\Python\Project\FA_Data`、`FORMAL_DAILY_MARKET_DB=D:\Min\Python\Project\FA_Data\sqlite\twstock.db`、`FORMAL_DAILY_RULE_BASELINE_ROOT=D:\Min\Python\Project\FA_Data\output\formal_prospective`、calendar cache 為 `output\paper_execution_eod_replay\calendar_cache`、Rule output 為 `output\formal_daily_publications\rule_source`。它不接受 date／now override 或 fixture；9/9 實際輸出 pattern 是 `clock-20260909-machine-v2-<source_window_hash_12>-85d50c270d9a`，其中 `85d50c270d9a` 是只讀 D `clock-20260828/clock/manifest.json` bytes hash 的前 12 碼。這個 producer 會在自然 Rule session 重新計算 source window 與 universe；目前 durable `planned-v1` clock 是準備證據，沒有偷偷注入 D controlled path。

Formal input wrapper 不設定 `FORMAL_DAILY_CLOCK_MANIFEST`、`FORMAL_DAILY_UNIVERSE_SYMBOLS`、`FORMAL_DAILY_OWNER_ACCEPTANCE` 或 legacy `BALDR_ML_*` path；它只從 `FORMAL_DAILY_RULE_SOURCE_ROOT` 做完整 clock／owner／universe／market revalidation 後取得 exact bundle，並把解析結果寫入 status。這避免舊 `clock-20260819` 路徑在新 source 到達時遮蔽新 bundle。`FORMAL_DAILY_PAPER_SNAPSHOT_DB` 與 `FORMAL_DAILY_PAPER_TRADE_LEDGER_DB` 分別固定在 repository isolated Paper snapshot／ledger path，D market 只以 `sqlite_mode_ro_query_only` 讀取。

D-1 PIT archive 的消費邊界已明確分開。`output/formal_daily_publications/pit_candidate_archive/2026-09-08/85f71a355f707404-284d54b9ccedbfea/archive_manifest.json` file SHA=`sha256:c2b838d9d79b794bc13b934c83f5f36f18c1b5828dead20ded9112de6745178f`，`effective_from=2026-09-08`、`available_at=2026-09-08T10:28:09.898861Z`、`archived_at=2026-09-08T10:34:49.359908Z`、1984 rows，raw custody／rows readback 通過。它可以在 9/9 decision 前以 caller 指定的 exact manifest 供 `ml_module.pit_archive_consumer` 做 candidate shadow；仍是 `candidate_only=true`，不授 forward credit 或 promotion。它不能直接當 Formal sidecar：`formal_consumer_compatible=false`，必須另經獨立 denominator／license／coverage、同一 natural day 不得有多個 distinct publication、正式 sidecar publisher 與 assembler readback；目前 9/8 archive root 的多個 distinct captures 仍應 fail closed。D-1 archive 的晚於 9/8 08:30 capture 不可追認為 9/8 formal coverage，但若未來 handoff 的 target cutoff、coverage 與 identity 全部滿足，才可作為後續日期的 lineage candidate。

這份 config 的 `controlled_activation_gate` 仍是 `three_exact_consumer_readbacks_required=true`、`common_identity_required=true`、`old_controlled_paths_unchanged_until_atomic_update=true`；D `clock-20260909` 目標只作 root review target，`controlled_update_applied=false`。因此 Rule／PIT 的自然 producer 可獨立累積，Paper fill 只阻最後 causal ledger／Formal release，不阻擋前述日曆、Rule 與 PIT 準備。

## Late replay 與跨日政策

合法同日 source retry 使用原始 frozen decision 與原始 source identity，`recorded_at` 記錄實際 retry 時刻，這不會把 retry 當成偽造歷史，也不補 elapsed credit。若 pending 執行日已經過去仍未有可驗證 source，resolver 回傳 `pending_execution_session_missed:<date>`，保留 receipt 與診斷；不切換到隔日 recommendation，不建立歷史日 fill。隔日的新 recommendation 只能在舊 pending 已 terminal 或明確 missed record 後進入新 execution date。

## 回滾清單

### 變更檔案清單

| 檔案路徑 | 變更類型 | 變更摘要 | 回滾方式 | 回滾風險 |
| --- | --- | --- | --- | --- |
| `data_module/paper_daily_execution_producer.py` | 修改 | legacy receipt adoption、strict blocker、same-day pin、cross-day no-credit | 只回退本 owner 的 diff；先確認 shared checkout 其他 agent 變更，再以人工 patch 還原 | 可能重新允許新 recommendation 覆蓋 pending |
| `app_module/paper_trade_ledger.py` | 修改 | composite identity、atomic transaction、explicit close | 只回退本 owner 的 diff；保留已產生的 ledger／receipt | 可能重新引入跨 portfolio 誤拒或 Windows lock |
| `data_module/formal_controlled_handoff.py` | 新增 | runtime attestation 與 proposed plan builder | 確認無相依後刪除該新增檔案 | 會失去受控設定的可重播 plan，不會刪 D 資料 |
| `scripts/qa_formal_controlled_handoff_plan.py` | 新增 | create-only handoff QA 入口 | 確認無相依後刪除該新增檔案 | 只影響 QA 入口 |
| `tests/test_formal_controlled_handoff.py` | 新增 | 舊 0/3、無自動猜路徑與 proposed 3/3 replacement regression | 確認無相依後刪除該新增檔案 | 失去 regression coverage |
| `tests/test_paper_daily_execution_producer.py` | 修改 | same-day retry、legacy、mixed blocker、cross-day guard tests | 只回退本 owner 新增測試 diff | 失去 queue safety coverage |
| `tests/test_paper_trade_ledger.py` | 修改 | identity scope、concurrent writer、cash conservation tests | 只回退本 owner 新增測試 diff | 失去 ledger concurrency coverage |
| `docs/01_architecture/system_architecture.md` | 修改 | source identity composite scope 架構契約 | 只回退本 owner 新增段落 | 架構文件會落後實作 |
| `docs/06_qa/V4_NEXT_FORMAL_HANDOFF_2026_09_08.md` | 新增 | 本次 live evidence、plan、順序與 rollback | 確認無相依後刪除該新增文件 | handoff history 不可見 |
| `data_module/official_calendar_bundle.py` | 修改 | 保存 exact HTTP raw bytes／metadata，拒絕 payload reserialization | 只回退本 owner 的 custody diff；既有 candidate bytes 保留 | calendar receipt 失去可重建性 |
| `scripts/capture_official_calendar_bundle.py` | 修改 | bounded capture 綁定 raw sidecar manifest | 只回退本 owner 的 capture diff；不刪既有 bundle | 新 capture 可能只剩 URL/hash |
| `scripts/persist_official_calendar_bundle.py` | 新增 | calendar raw／metadata create-only durable archive | 停止使用入口；保留已存 candidate archive | durable calendar custody 需人工核對 |
| `data_module/formal_next_clock_preparation.py` | 修改 | raw custody、exact clock/planner readback、無 placeholder 的 v6 command | 只回退本 owner 的 preparation diff；保留 QA evidence | plan 可能退回無法獨立驗證 |
| `scripts/qa_formal_next_clock_preparation_plan.py` | 修改 | 接收明確 planner report path | 只回退 CLI 參數 diff | report／clock 可能再混淆 |
| `scripts/persist_prospective_formal_clock.py` | 新增 | immutable clock 原 bytes create-only durable archive | 停止使用入口；保留 candidate archive，controlled path 不變 | 需重新建立 durable candidate |
| `scripts/build_formal_9_9_candidate_runtime_config.py` | 新增 | 9/9 Rule／PIT／Formal／Paper wrapper 的 exact env、task、source hash 與 D-1 consumer boundary | 停止使用入口；保留既有 candidate config，controlled path 不變 | Ops 需回到各 wrapper 既有 defaults，不能把 candidate 當受控輸入 |
| `output/v4_next_formal/formal_9_9_candidate_runtime_config_20260908_114000.json` | 新增 | create-only、hash-bound runtime candidate；不寫 scheduler／D／SQLite | QA evidence 只讀保留；如需重跑用新 filename | 只影響 root review 參考，不影響實際 Formal readiness |
| `tests/test_formal_next_clock_preparation.py` | 新增 | raw／metadata 篡改、path escape、future owner timestamp 負例 | 確認相依後刪除該新增測試 | 失去 custody／時序 regression coverage |
| `output/v4_next_formal/formal_clock_identity_source_mapping_20260908_v2.json` | 新增 | 八個 identity source path/hash 與 Rule-only 邊界 | QA evidence 只讀保留，不作程式 source | review 對照不完整 |

QA output `output/v4_next_formal/*` 與 `output/v4_next_root/*` 不得當成程式 source；若需重跑，使用新的 create-only filename。所有變更仍在 shared checkout，沒有建立 branch/worktree/checkout，也沒有 commit/push。

## 驗證

本 owner 已通過：

- `tests/test_paper_daily_execution_producer.py` + `tests/test_paper_trade_ledger.py`：`34 passed`；
- `tests/test_formal_controlled_handoff.py`：`3 passed`；涵蓋 current 0/3 不阻擋完整 proposed bundle、proposed path 未提供時保持 blocked，以及 proposed consumer 失敗仍 blocked；
- `tests/test_formal_next_clock_preparation.py` + `tests/test_official_calendar_bundle.py`：與上述 handoff tests 合計 `16 passed`；涵蓋 raw／metadata 篡改、manifest path escape、future owner timestamp，以及 exact raw sidecar／inline hash custody；
- `mypy --explicit-package-bases data_module/formal_controlled_handoff.py scripts/qa_formal_controlled_handoff_plan.py app_module/paper_trade_ledger.py data_module/paper_daily_execution_producer.py`：`Success: no issues found in 4 source files`；
- 新增 `scripts/persist_prospective_formal_clock.py`、calendar custody／preparation CLI 與變更模組均通過 `py_compile`／`mypy`；clock candidate 持久化後以 durable path 重新 `load_clock_manifest` 通過，source/durable bytes 相等；
- `scripts/build_formal_9_9_candidate_runtime_config.py` 以目前 process clock 完成 durable source readback，`py_compile`／`mypy` 通過；candidate config body hash 與 file hash 讀回通過，重跑同一 output path 以 exit `2` 拒絕覆寫；
- 變更 Python 檔案 `py_compile` 通過；
- 實際 Paper resolver／legacy readback：`pending_execution_retry` 選定 `scheduled_rec_20260907_051003`，跨日明確回傳 `pending_execution_session_missed`，source receipts 未被改寫；
- 實際受控 environment readback：三個 path source 為 process environment，path match；HMAC 僅輸出 configured boolean。

上述證據仍維持 Formal credit、production blend、promotion 與 broker order 關閉。9/9 durable clock 目前只允許 Rule-only simulation；直到真實 Paper fill、PIT／Rule／causal 三路 consumer 完整 readback，ML disabled metadata 被實際 frozen release 取代（如需 ML lane），並由 root 審核後執行受控設定更新，才可進入相應 Formal credit。

## 2026-09-08 rolling runtime producer 與五角色接線

本輪新增 `data_module/formal_runtime_roll_forward.py` 與
`scripts/scheduled/run_formal_runtime_roll_forward.py`。producer 只以目前 process
UTC clock 執行，從明確 pin 的 durable official calendar bundle 讀取嚴格晚於目前台北
自然日的第一個 TWSE／TPEx 同時開市日；它不以 weekday 推定日期、不掃描 latest、不接收
`--date`／`--now`／來源覆寫，也不更新 scheduler、D 槽或 market SQLite。只有明確的
`official_calendar_bundle_*_activation_day_not_open` 休市 blocker 可以跳過；raw custody、
hash、schema、缺列等未知或損壞 blocker 會立即拒絕，避免跳到較晚日期掩蓋證據缺口。

已由目前 code 以明確來源完成一份可供 root 讀回的候選：

| 項目 | 精確路徑／hash | 結果 |
| --- | --- | --- |
| Calendar source | `output/formal_daily_publications/calendar_candidate_archive/2026-09-09/1b6227dd0464eded-aff4c96e1edab151/v4_calendar_20260909_20260908_104849140.json`；bundle=`sha256:1b6227dd0464edede4d3d0a3a50679f3a241e3c82eb8f61448cdb7a82c2eb062`；file=`sha256:8d3a55304982cba8976f6a31596df00b875f09368f54aa980adf1e2d8e1bca23` | raw／metadata custody verified；9/9 TWSE、TPEx 均 open。 |
| Fixed cumulative portfolio clock | `output/formal_daily_publications/clock_candidate_archive/2026-09-09/d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1/clock/manifest.json`；manifest=`sha256:d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1`；file=`sha256:a4d5eb8f771bc5f24651eaa8cc6492d939d72766e42f2e6609aec78dd0d53eb2` | `clock:prospective:20260909:planned-v1`；`reset_on_each_natural_day=false`；Rule daily clock 與它分開。 |
| Rolling candidate runtime | `output/v4_next_formal/formal_daily_runtime_config_v3/2026-09-09.json`；file=`sha256:21f7f09008fae60def2430b725123048b44cf76df4444f61edb7e85984366df0`；config=`sha256:54fe2034f5605e4f2ac921bd500f32d2dbf896149a35e168b69356eb8c976365` | `candidate_ready_for_root_review`；五個 role loader 均在 2026-09-08 回傳 `waiting_for_activation`。 |
| Producer status | `output/v4_next_formal/runtime_roll_forward_status/latest.json` | `runtime_config_created`、`activation_trading_day=2026-09-09`、exit `0`；status 內保存 exact calendar／clock／config path、file hash 與 trigger metadata。 |

可重播的 source-bound command 為：

```powershell
$env:FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE = 'C:\Projects\PythonProjects\technical_analysis\output\formal_daily_publications\calendar_candidate_archive\2026-09-09\1b6227dd0464eded-aff4c96e1edab151\v4_calendar_20260909_20260908_104849140.json'
$env:FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST = 'C:\Projects\PythonProjects\technical_analysis\output\formal_daily_publications\clock_candidate_archive\2026-09-09\d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1\clock\manifest.json'
$env:FORMAL_DAILY_RUNTIME_ROLL_FORWARD_ROOT = 'C:\Projects\PythonProjects\technical_analysis\output\v4_next_formal\formal_daily_runtime_config_v3'
.\.venv\Scripts\python.exe scripts\scheduled\run_formal_runtime_roll_forward.py
```

roll-forward 的 Ops trigger 已寫入候選 `runtime_trigger`：
`baldr-formal-runtime-roll-forward-daily`、Pacific 06:15（台北 21:15 PDT／22:15 PST），
action 為上述 Python entrypoint。它在 Paper EOD 06:00 task 後建立下一個 date-scoped
candidate，但不等待 fill、也不自動套用；`v4_schedule_ops` 仍須以其 scheduler 權限建立
每日 task，root review 後才把當日 exact file 綁到
`FORMAL_DAILY_RUNTIME_CONFIG`。本 owner 沒有修改任何 `.cmd`、Task Scheduler 或
controlled environment。

五個 wrapper 都以同一 `FORMAL_DAILY_RUNTIME_CONFIG` candidate 做 process-boundary
驗證：`rule_source_wrapper` 由 `data_module.formal_rule_source_producer`、
`pit_preopen_wrapper` 由 `run_pit_sector_membership_preopen_capture.py`、
`pit_sidecar_wrapper` 由 `run_formal_pit_sidecar_postcutoff.py`、
`formal_input_wrapper` 由 `run_formal_input_producer_daily.py`、
`paper_eod_wrapper` 由 `run_paper_execution_daily_isolated.py` 消費。前兩個 PIT
wrapper 已補上同樣的 schema／bytes／environment／activation gate；候選未啟用時只寫
`waiting_for_runtime_config`，不先抓 source 或發布 sidecar。Formal input 的
`FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST` 是同一份固定累積 clock；daily Rule source
bundle 的 `clock/manifest.json` 維持獨立且由 exact predecessor status 綁定，不能用每日
Rule clock 重置 portfolio 起點。

同日補跑不會因 roll-forward selector 的嚴格 `>` 而跳到隔日：selector 只供前一自然日
建立下一份 candidate；9/9 盤前 recovery 直接以 Ops 已綁定的
`formal_daily_runtime_config_v3/2026-09-09.json` 讀取，loader 在 2026-09-09
00:00 UTC（台北 08:00）回傳 `active`。因此 retry 消費既有日期設定，不能再呼叫
roll-forward 取代當日設定。

### 本輪接線驗證

- `tests/test_formal_runtime_roll_forward.py`：`8 passed`；涵蓋 strict next-day 選取、明確休市跳過、最早日 raw evidence 損壞立即拒絕、固定 clock 不重置、五 role loader、同日 recovery、缺 pin 與 create-only byte-idempotency。
- `tests/test_formal_runtime_config.py`、`tests/test_formal_runtime_wiring.py`、上述 rolling suite：`17 passed`。
- `tests/test_formal_rule_source_producer.py`：`19 passed`；包含真 SQLite T-1 captured-window mutation 後 actual decision 仍使用 captured ranking。v2 負例仍是 loader substitution 的 hash negative，未宣稱真 DB E2E；v2 仍要求 live T-1 revalidation，v3 才能以 persisted rows replay。
- `tests/test_pit_preopen_schedule.py`、`tests/test_formal_pit_sector_publisher_cli.py`、`tests/test_scheduled_paper_execution_wrapper.py`：`17 passed`。
- 變更檔案 py_compile 與 mypy（rolling producer／caller、Rule producer、PIT capture／sidecar）：均通過。

第一份 `output/v4_next_formal/formal_daily_runtime_config/2026-09-09.json` 曾是同一路徑
的 loader probe，因缺少既有 schema 要求的 `safety` object 而未被使用；它保留作不可用
immutable 證據，沒有覆寫。修正版另以 `formal_daily_runtime_config_v2` 建立，最終以
`formal_daily_runtime_config_v3`（含 scheduler trigger metadata）建立並完成五 role
readback。任何 Ops／root consumer 都不得綁定第一份 probe。

Paper fill、causal ledger closed interval、PIT／Rule／Formal 三方 common identity 與
controlled handoff 仍是最終發布 gate；本 rolling candidate 不增加 Formal credit、不
宣稱 ML frozen lineage、不產生 fill，也不把缺來源轉成成功。回滾時保留所有候選與 QA，將
`FORMAL_DAILY_RUNTIME_CONFIG` 恢復到前一份 root 已審核的 exact path；producer 本身沒有
切換行為，因此不存在回滾時刪除 D 資料或還原 scheduler 的動作。

## v6 rolling runtime correction（2026-09-08）

前述 v3、v4、v5 runtime candidate 均保留為不可覆寫的歷史 QA；root 不應把它們綁到
當日 wrapper。v6 是加入真實 Rule dependency preflight、Paper retry caller、一次性
date-scoped runtime root binding 與 degraded exit semantics 後的最新候選：

| 項目 | 精確路徑／hash | 當次結果 |
| --- | --- | --- |
| v6 runtime config | `output/v4_next_formal/formal_daily_runtime_config_v6/2026-09-09.json`；file SHA=`sha256:08f3d342b37ce6d69dc06cad16680f756fe1beb296ad64a76e19a9d1e15810b4`；`config_hash=sha256:55a352bcd92231dbe625014180ce2c796cd0716da4fbf2f9ac453bff7561854d` | `runtime_config_created`、`activation_trading_day=2026-09-09`、producer exit `0`；`candidate_only=true`、`formal_oos_allowed=false`。 |
| Rule parent preflight | D `D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260828\clock\manifest.json`；clock id=`clock:prospective:20260828:v1`；file SHA=`sha256:85d50c270d9a10098e4e99d4531b0b3ce96eb096797977ab64349bc164c90161`；manifest hash=`sha256:dfcd95b89f02cf1e68de945525694d0d912fd37b138e17c04b5506c7e2655f6d` | 與正式 Rule producer 相同的 `_find_baseline_bundle` 與 `_official_calendar_evidence` 實際 resolver；owner acceptance 與 1932 symbols 皆存在且有 file hash，calendar source hash=`sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`。 |
| v6 readback QA | `output/v4_next_formal/formal_runtime_roll_forward_readback_v6_20260908.json`；file SHA=`sha256:77d026c33cae5093357d99a3bc2f7da1a2ab23b47ff665c34785b40f32b448a1` | v6 source／role／caller／auto-binding readback；root 可用 v6 config file hash 與 QA file hash 獨立重算。 |

v6 `source_evidence.rule_dependency_preflight.status=verified`，不再使用舊的
`rule_parent_policy.exists=false` 診斷欄位。它保存 D market read-only file hash、固定
portfolio clock、官方 calendar bundle、parent owner acceptance、parent universe
symbols 與 calendar evidence 的精確來源；D SQLite 只以 bounded streaming hash／query
讀取，沒有寫入。

Paper 的實際 caller 是既有 `baldr-paper-execution-eod-replay-daily`：其
`run_paper_execution_daily_isolated.cmd` 呼叫 `paper_execution_retry_runner.py`，在
同一自然日 bounded retry 結束後呼叫
`run_formal_runtime_roll_forward.py`。這個 hook 只產生下一個 date-scoped candidate，
不套用 controlled path、不產生 fill。v6 `runtime_trigger` 的 task、action、時間與
`trigger_mode=existing_paper_execution_retry_runner_after_retry_boundary` 均以此實際
caller 為準；不需要另造一個未接線的 proposed scheduler task。

第一次 root／Ops preflight 後，只需一次性綁定 v6 `wrapper_contract` 中的 exact
environment，包括 `FORMAL_DAILY_RUNTIME_CONFIG_ROOT`、
`FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE`、`FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST`、
`FORMAL_DAILY_RUNTIME_ROLL_FORWARD_ROOT` 與各 role 的既有 source/output pins。之後
`load_optional_formal_runtime_config()` 依 `Asia/Taipei` 當日精確讀取
`<root>\\YYYY-MM-DD.json`，在 process 內更新 `FORMAL_DAILY_RUNTIME_CONFIG`，其他
環境值保持 exact；它不掃描 latest，也不要求 root 每日手動改 JSON pointer。若當日檔案
不存在，只有仍未到 activation 日的 explicit config 可回傳 waiting；已過期或缺少
必要檔案會 fail closed。

若 Paper adapter 自身成功但 rolling producer 失敗或缺少已配置的 source pin，retry
runner 會保留 `paper_execution_status`，將整體 status 設為
`degraded_runtime_roll_forward` 並回傳 exit `2`；因此明天缺 config 不會被 Paper
成功狀態掩蓋。成功建立或重用 candidate 時才保留 Paper 的 terminal status 與 exit `0`。

本輪測試包含：rolling/config/wiring/retry 與連續 2026-09-09→2026-09-10 五角色
auto-binding 共 `26 passed`；Rule producer `19 passed`（真 SQLite captured T-1
mutation 後 decision 仍使用 captured rows）；相關變更檔案 mypy／py_compile 均通過。
連續日測試只在 9/9 config 設定一次環境，9/10 由同一 root 精確選檔，沒有重新設定
config10 或其他 source/output path。v6 仍受 Paper 真 fill、causal ledger closed
interval、PIT／Rule／Formal common identity 與 root controlled handoff gate 約束。

## 一次性 runtime environment binding（2026-09-08）

較早段落中曾列出的 `baldr-formal-runtime-roll-forward-daily` 是歷史性未接線
candidate 描述，不是目前可執行入口。v6 的實際觸發仍是既有
`baldr-paper-execution-eod-replay-daily` → `run_paper_execution_daily_isolated.cmd`
→ `paper_execution_retry_runner.py`，在 bounded Paper retry 邊界後呼叫
`run_formal_runtime_roll_forward.py`。本節是目前部署與回滾的唯一權威方案。

### 具體來源與部署邊界

| 項目 | 精確值 |
| --- | --- |
| v6 candidate config | `output/v4_next_formal/formal_daily_runtime_config_v6/2026-09-09.json`；file SHA=`sha256:08f3d342b37ce6d69dc06cad16680f756fe1beb296ad64a76e19a9d1e15810b4`；config hash=`sha256:55a352bcd92231dbe625014180ce2c796cd0716da4fbf2f9ac453bff7561854d` |
| durable calendar pin | `output/formal_daily_publications/calendar_candidate_archive/2026-09-09/1b6227dd0464eded-aff4c96e1edab151/v4_calendar_20260909_20260908_104849140.json`；bundle=`sha256:1b6227dd0464edede4d3d0a3a50679f3a241e3c82eb8f61448cdb7a82c2eb062` |
| durable cumulative clock pin | `output/formal_daily_publications/clock_candidate_archive/2026-09-09/d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1/clock/manifest.json`；manifest=`sha256:d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1`；file=`sha256:a4d5eb8f771bc5f24651eaa8cc6492d939d72766e42f2e6609aec78dd0d53eb2` |
| binding target | `output/v4_next_formal/formal_runtime_environment_binding.json` |
| deployment entrypoint | `scripts/write_formal_runtime_environment_binding.py` |
| pre-apply QA | `output/v4_next_formal/formal_runtime_environment_deployment_readback_20260908.json`；dry-run file SHA=`sha256:f4d350586a8672623253ed1cd2c279bc5822d5e6e9eca19dace398c56fbedc08` |

`write_formal_runtime_environment_binding.py` 先以 v6 wrapper contract 衍生
allowlist，再在同一個 process 內設定暫時環境並執行五角色 readback。它驗證 v6
bytes/config hash、所有 required keys、exact source/output/clock paths 與
candidate safety；任何驗證失敗都不寫 binding。`--apply` 通過後才以 fsync + atomic
replace 建立 active binding，並先保存 exact prior bytes 的 hash-bound backup。它不寫
User/System environment、不依賴 Windows environment inheritance、不改 Task Scheduler
registration，也不碰 D 或任何來源／成交資料庫。舊的 `deploy_formal_runtime_environment.ps1`
入口已移除，避免留下會修改 User environment 的第二套部署方式。

### root 可審核命令

以下命令都從 repository root 執行。第一條是已實際執行的 process-only dry-run；它
回讀五個 role 的 `waiting_for_activation`、同一 v6 file SHA、兩個 source pins，且
`persistent_environment_written=false`、`scheduler_written=false`。這個 readback 不
代表受控 Formal promotion。

```powershell
.\.venv\Scripts\python.exe scripts\write_formal_runtime_environment_binding.py
```

root 完成 candidate-only machine review 後，使用已核准的 preparation decision
（`root-v4-preparation-20260908T103457Z`、`2026-09-08T10:34:57+00:00`）執行一次：

```powershell
.\.venv\Scripts\python.exe scripts\write_formal_runtime_environment_binding.py `
  --config-path "C:\Projects\PythonProjects\technical_analysis\output\v4_next_formal\formal_daily_runtime_config_v6\2026-09-09.json" `
  --output-path "C:\Projects\PythonProjects\technical_analysis\output\v4_next_formal\formal_runtime_environment_binding.json" `
  --owner-decision-id "root-v4-preparation-20260908T103457Z" `
  --approved-at "2026-09-08T10:34:57+00:00" `
  --apply
```

apply 的 JSON readback 會給出精確 `backup_path` 與 `backup_file_sha256`。若需回退，
把該 readback 的實際 backup path 原樣傳入：

```powershell
.\.venv\Scripts\python.exe scripts\write_formal_runtime_environment_binding.py `
  --output-path "C:\Projects\PythonProjects\technical_analysis\output\v4_next_formal\formal_runtime_environment_binding.json" `
  --rollback-from "C:\Projects\PythonProjects\technical_analysis\output\v4_next_formal\formal_runtime_environment_backup_<apply-utc-stamp>.json"
```

rollback 先驗 backup schema、content hash、target path 與 prior file hash；有 prior
binding 時原子恢復其 exact bytes，第一次 apply 前沒有 prior binding 時則寫入
`status=inactive` 的 fail-closed marker。兩種情況都維持
`persistent_environment_written=false` 與 `scheduler_written=false`，不會靜默回到
未知舊 clock。若要再次啟用，必須由相同入口對已審核的新 candidate 重新建置 active
binding。

### Task Scheduler process inheritance 契約

既有 `run_paper_execution_daily_isolated.cmd` 與其他已註冊 action 不需修改，也不靠
目前 PowerShell、User registry 或長駐 process 的舊 environment。每次 Task Scheduler
啟動新的 Python wrapper 時，`load_optional_formal_runtime_config()` 在 process
boundary 讀取固定的 `formal_runtime_environment_binding.json`，驗證 exact source
config bytes、binding content hash、allowlist 與 safety，再把 map 載入該 process；之後
以 `FORMAL_DAILY_RUNTIME_CONFIG_ROOT` 精確選取當日台北日期的 `YYYY-MM-DD.json`。因此
9/9→9/10 由同一個 root 自然滾動，不需每天修改 User env 或手動替換 JSON pointer。
已有中的 process 不會被檔案熱改；下一次正常 Task Scheduler invocation 才讀取新
binding，這是可重現的 fresh-process 邊界。binding 缺失、篡改、source map 與 v6
contract 不一致時，wrapper fail closed；Paper 成功而 roll-forward 失敗仍由 retry
runner 回傳 `degraded_runtime_roll_forward` / exit `2`，不會被 task success 掩蓋。

本節的實際 dry-run 證據顯示五個 role 在目前 2026-09-08 均為
`waiting_for_activation`，v6 config file SHA 一致，Rule dependency／calendar／fixed
clock pins 均存在；後續 root 已依下方一次性命令完成 active binding apply 與 fresh
process readback。binding 只是 candidate runtime wiring，不改變三 consumer、真 fill、
closed causal ledger、common identity 或 controlled handoff gate。

### Binding 測試

- `tests/test_formal_runtime_config.py`：`10 passed`；新增 active binding exact map
  readback、allowlist tamper、重新 hash 後 source clock map mismatch、future machine
  decision time 四項邊界；測試使用 temp output 並未寫入正式 v6 binding。
- `tests/test_formal_runtime_roll_forward.py`、`tests/test_formal_runtime_wiring.py`、
  `tests/test_paper_execution_retry_runner.py`：保留五角色連續自然日選檔、same-day
  recovery、Paper 成功／roll failure degraded semantics。
- `data_module/formal_runtime_config.py`、`scripts/qa_formal_runtime_environment_preflight.py`、
  `scripts/write_formal_runtime_environment_binding.py` 與 rolling producer／caller
  均通過 `py_compile` 與 mypy；binding deployment readback 的五 role preflight 為
  `all_five_roles_verified=true`。

### root apply 與 fresh Task action readback

root 已依上述 candidate-only review 執行一次 active binding apply：

| 項目 | 精確證據 |
| --- | --- |
| active binding | `output/v4_next_formal/formal_runtime_environment_binding.json`；file SHA=`sha256:205c60fa256200edf13765ad109ed0601ee6a4ecc5f8fbbf6fd6f81e32db085d`；source v6 file SHA=`sha256:08f3d342b37ce6d69dc06cad16680f756fe1beb296ad64a76e19a9d1e15810b4`；owner decision=`root-v4-runtime-reviewed-20260908` |
| apply receipt | `output/v4_next_root/runtime_binding_apply_20260908.json`；binding `created`，post-apply five-role preflight 全部 verified |
| exact rollback backup | `output/v4_next_formal/formal_runtime_environment_backup_20260908T152436730619Z.json`；由 apply receipt 提供 backup hash，未修改 User/System environment |
| fresh-process readback | `output/v4_next_root/runtime_binding_fresh_process_20260908.json`；清除 inherited pins 後仍由 default binding 載入，五 role 均 `waiting_for_activation` |
| Task-shaped read-only readback | `output/v4_next_formal/formal_runtime_environment_task_action_readback_20260908.json`；file SHA=`sha256:095aa2755fddac4f03a3a6cb8cd3711897c35fd30eb16155b4a955d96f099a5`；fresh `cmd.exe` process 清空四個 runtime/source pin 後執行 QA，`all_five_roles_verified=true`、`source_pins_present=true` |

這次 task-shaped probe 只執行 `scripts/qa_formal_runtime_environment_preflight.py`，沒有
呼叫 Paper execution、沒有建立 fill、沒有執行 Rule producer、沒有寫 market database、
沒有授予自然日或 Formal credit。既有 Task Scheduler action 保持原樣；下一次新的
Python process 會在 wrapper 啟動邊界讀取 active default binding。`tests/conftest.py`
提供明確的 `isolated_formal_runtime_subprocess_env` fixture；實際使用它的
`test_fresh_subprocess_uses_explicit_isolated_binding_path` 會以 fresh Python process
執行 `scripts/qa_formal_runtime_environment_preflight.py`，並傳入 repository output
下不存在的 binding path，因此不會讀取已部署的 default binding。其餘需要驗 binding
的測試各自明確指定 temp binding path；沒有使用此 fixture 的其他 subprocess test 不
宣稱自動隔離。因此 root apply 後，以下兩個測試順序都已通過 `36 passed`
（`-p no:cacheprovider`）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_formal_runtime_config.py tests\test_formal_runtime_roll_forward.py tests\test_formal_runtime_wiring.py tests\test_paper_execution_retry_runner.py -q -o addopts= -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_paper_execution_retry_runner.py tests\test_formal_runtime_config.py tests\test_formal_runtime_roll_forward.py tests\test_formal_runtime_wiring.py -q -o addopts= -p no:cacheprovider
```

### Natural shadow maturity/pruning read-only common exit

`scripts/natural_shadow_pruning_evidence_runner.py` 是本片唯一的排程後置
projector。它不建立第二個 sidecar、不執行 pruning、promotion 或正式信用；輸入
固定為既有 orchestration run root 下的
`shadow_evidence_collector/shadow_evidence.sqlite`，不掃描 latest 檔案。接線點是
`scripts/run_daily_ml_allocation_orchestration.py` 的 `_write_status` common exit，
因此交易日、非交易日及各 stage 的 fail-closed status 都會讀取既有 collector
revision；不掛在 forward child 的成功尾端，也不新增 Task Scheduler task 或修改
既有 `.cmd` action。現有 `baldr-ml-allocation-copilot-daily` action 仍經
`run_ml_allocation_copilot.cmd` 呼叫同一個 orchestration。

每次 status boundary 以 `as_of_date=decision_at` 的 Taipei 自然日執行一次
projector。成功讀取 sidecar 後，原 evidence body 同時以 create-only 方式保存到：

```text
<run_root>/natural_shadow_pruning_evidence/daily/YYYY-MM-DD/evidence_<hash-prefix16>.json
<run_root>/natural_shadow_pruning_evidence/weekly/YYYY-Www/asof_YYYY-MM-DD_evidence_<hash-prefix16>.json
```

同一 body 也各自寫入 daily/weekly 的 `status_<hash-prefix16>.json`。檔名只取
16 碼是為了 Windows 路徑上限；完整 `evidence_hash`、`status_hash` 與 source
file hash 都保留在 JSON，若 prefix 碰撞則完整 bytes 比對後拒絕，不會覆寫。weekly
檔案是該 ISO 週的自然日 as-of checkpoint，並不宣稱整週已成熟。sidecar 缺失時
status=`pending`、`integrity_state=awaiting_source`、exit=0，表示 collector 尚未
供應來源；sidecar JSON/schema/hash/讀取期間變動或 immutable output conflict 時
status=`blocked_integrity`、exit=2。orchestration 保留原本的 Rule-only `status`，
另以 `natural_shadow_pruning_evidence_exit_code=2` 與
`failed_reasons` marker 傳遞完整性失敗；CLI main 及 derived wrapper 都會保留非零
exit，不把它誤報為成功 candidate。

所有 immutable status/evidence 發布都先用短名 temporary file 寫滿、flush、fsync，
再以同目錄 `os.link` 原子地建立目的檔；fsync/crash 測試確認目的檔不會留下半成品。
`ml_module/natural_shadow_pruning_evidence.write_natural_shadow_pruning_evidence`
也使用同一個邊界，並保留 exact replay idempotency 與不同 bytes conflict。

### 真 D sidecar isolated readback

本輪以真實 D sidecar 做一次獨立唯讀 probe，輸出只放 repository QA，不把 probe
路徑當正式來源：

| 項目 | 精確值 |
| --- | --- |
| sidecar | `D:\Min\Python\Project\FA_Data\output\scheduled\ml_allocation_copilot\shadow_evidence_collector\shadow_evidence.sqlite` |
| sidecar bytes/hash before/after | `22,515,712` bytes；before=`sha256:b86c91afad16b5d0a07a1382fbb42d9075cd037dea962ca5bc6e38815470a9e8`；after 相同 |
| as-of result | `observation_count=26`、`pending_observation_count=26`、`matured_observation_count=0`、evidence status=`pending_maturity` |
| evidence hash | `sha256:8b0745be457e71c83149e442f08750cc741f78b93add481380e673d62fc90e9f` |
| daily/weekly evidence file hash | `sha256:81aedee8aa54fcdcc12c4017933bc9e057fac712d5baf03d4e5e2a33939368f9`（兩份 bytes 相同） |
| probe QA | `output/v4_next_formal/natural_shadow_pruning_runner_readback_20260908.json` |

probe result 的 `pending_is_normal_wait=true`、`exit_code=0`、
`read_only=true/query_only=true`，且 `pruning_action_performed=false`、
`promotion_action_performed=false`、`formal_oos_allowed=false`、
`production_action_allowed=false`、`writes_source_database=false`。這 26 筆仍是
自然成熟度待累積資料，沒有授予正式 Formal/Paper credit。

### Natural shadow runner 測試

`tests/test_natural_shadow_pruning_evidence_runner.py` 新增 6 個有意義案例：
缺 sidecar 的正常 pending、真 SQLite sidecar 的 daily/weekly hash-bound output、
無效 sidecar 的 exit=2、orchestration common exit 綁定、status atomic publish
中斷不留半檔，以及 evidence writer 中斷不留半檔且 exact replay/conflict 保護。
runner、orchestration、derived wrapper、natural evidence 合併重跑為 `47 passed`；
四個 changed source 的 `py_compile` 與 mypy 亦通過。

root 另以真 D sidecar 重跑 scheduled common-exit readback，證據為
`output/v4_next_root/pruning_scheduled_actual_readback.json`；本輪新增的
`test_fresh_subprocess_uses_explicit_isolated_binding_path` 以真正 fresh Python
subprocess 傳入 repo output 下不存在的 binding path，確認測試不會讀取 active default
binding（單項通過）。

### D copilot Paper 與 repo Formal/Paper 唯讀 identity/schema/lineage audit

本輪沒有把 D copilot 狀態複製或合併到 repository Paper 狀態。所有 SQLite 都用
`file:<absolute-path>?mode=ro` 開啟並在連線內設 `PRAGMA query_only=ON`，查詢完成後明確
關閉連線；完整 table SQL、columns、row counts、bytes/hash 與選取列摘要保存於
`output/v4_next_formal/paper_source_lineage_gap_audit_20260908.json`，該 QA 檔案 SHA=`sha256:17d3825b90be95cef7d711ba1532de3a39e57af10c4fab46b64d842b53931ec9`。

| source lane | exact path | observed identity |
| --- | --- | --- |
| D copilot legacy Paper state | `D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_portfolio.sqlite` | 28,672 bytes；SHA=`sha256:a5ba36e358d2634084a271719acc042a4b0d9e8efe0ea52617086ce4aebf6afb`；`paper_portfolio_snapshots` 27 rows／latest `2026-09-07`；`paper_portfolio_positions` 81 rows |
| repository Formal/Paper snapshot | `C:\Projects\PythonProjects\technical_analysis\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite` | 28,672 bytes；SHA=`sha256:f093e79ce11daa43d2721726eb16f06c55d0ed0ed9cec43f93b7f00210f6a3d4`；snapshots 28 rows／latest `2026-09-08`；positions 84 rows |
| repository Formal/Paper fill ledger | `C:\Projects\PythonProjects\technical_analysis\output\paper_execution_eod_replay\paper_trade_ledger.sqlite` | 20,480 bytes；SHA=`sha256:441dd437981bb82a787f5069fef5e7e878b316ef506fbc0dd78ca8dc6627af58`；8 rows，event date `2026-09-08`，statuses `filled/partially_filled/rejected`，`research_only=1`，broker/auto-rebalance flags all 0 |

兩個 state DB 的 table/schema 形狀相同，但 bytes、row count 與最新日期不同；因此
`schema_match=true`、`state_file_hash_match=false`，且 repo 只多出 `2026-09-08`。兩者
均為 `portfolio_id=paper-main`，但這不構成可合併身份。D `paper_portfolio_daily` status
仍指向上述 D state、日期 `2026-09-07`、source result
`scheduled_rec_20260712_051002`；D copilot 最新 orchestration 已是
`decision_at=2026-09-09T08:30:00+08:00`，故 D Paper state 落後當前 copilot
decision，不能直接供 9/9 Formal 消費。

repository 9/8 delayed-EOD receipt 的 exact path 是
`output/paper_execution_eod_replay/receipts/paper_execution_2026-09-08_9330c91d89344056_20260908T130006868388Z.json`，檔案 SHA=`sha256:3db985e85b4ce42c9dd1b795d839f1eaf01ca6b061ad3ddc98d8f7fb90be51eb`。其 recommendation path/hash 精確綁定 D 的 9/7
`scheduled_rec_20260907_051003.json`（file SHA=`sha256:9330c91d8934405629d9f4f48d2c1a239741f1d886a71bfc75d4086fa33df165`），state snapshot
path/hash 精確綁定 repository 9/7 snapshot，ledger path 精確綁定上述 8-row repo fill
DB，`fill_count=8` 與 ledger row count 相等。這條 execution lineage 可讀回，但 receipt
明確是 `execution_replay_mode=delayed_eod_replay`、`execution_event_time_proven=false`、
`formal_consumer_compatible=false`、`formal_ready=false`、`formal_credit=false`，仍是
research-only 的最終 Formal gate，不能以 D 9/8 或 9/9 新 recommendation 取代。

active 9/9 runtime binding/config 目前精確指向 repository snapshot 與 fill ledger；
`formal_identity_20260909.json` 尚不存在，Formal scheduler status 仍為
`candidate_only`。因此本輪決定 `safe_to_merge=false`，保留兩條 source lane。root
審核後的最小接線順序是：

1. 固定使用 repository snapshot + fill ledger 的 exact path/bytes hash；D copilot
   state 只作 read-only diagnostic，禁止 seed/copy/merge。
2. 只使用上述已被 9/8 receipt 綁定的 D 9/7 frozen recommendation，驗 data date、
   portfolio identity、recommendation file/content hash；拒絕 D 9/8/9/9 current
   candidate 覆蓋已進入 execution 的 decision。
3. 先驗 receipt→snapshot/fill path+hash、實際 fill count、event/execution date、
   rejected/partial settlement 與 research-only boundary，再送 Formal consumer。
4. 將同一 fixed portfolio clock、Rule/PIT receipt、Paper snapshot receipt、Paper
   fill receipt 組成 common identity；daily Rule source 以獨立 version lineage 綁定
   共同 policy/universe/clock。缺任一 exact receipt 或 receipt 的
   `formal_consumer_compatible` 仍為 false 時維持 candidate/blocked。
5. 只有 root 審核完整三來源 identity 與新的 terminal Paper receipt 後，才接既有
   Formal consumer；本輪不切換 runtime path、不授 Formal credit、不觸碰 D 資料。

### 每日 copilot 的 canonical repository Paper caller 契約

上述 audit 已解除「把 D 舊狀態當成 repository Formal/Paper 輸入」的歧義，但 audit
本身不是每日 caller。下一個自然日的 copilot 必須由受控 date-scoped config 明確
綁定 repository Paper state 與 receipt lineage，並將 D lane 留作唯讀歷史診斷：

| caller input | canonical repository contract | fail-closed 條件 |
| --- | --- | --- |
| Paper state snapshot | `output/paper_execution_eod_replay/paper_portfolio/paper_portfolio.sqlite`；以 SQLite `mode=ro`／`PRAGMA query_only=ON` 讀取 | 不接受 `D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_portfolio.sqlite` 作為 9/9 以後的 state；path、portfolio、snapshot date 或 clock 不符即 blocked |
| Paper fill ledger | `output/paper_execution_eod_replay/paper_trade_ledger.sqlite`；只讀已 commit rows | 缺 ledger、`fill_id`／`(portfolio_id, source_event_id)` 重複、Decimal gross／fee／tax／net 不守恆或 receipt hash 不符即 blocked |
| Recommendation | 每個 Taipei 自然日，在 decision cutoff 前由同一 canonical portfolio／fixed clock 產生一份 immutable recommendation，保存 source path、content/file hash、decision／execution date 與 version | 不掃描 latest；已進入 pending 的 decision 由 `(portfolio_id, execution_date, source_hash)` pin；新 recommendation 只能排隊，不能覆寫；D 9/7 recommendation 僅可讀回既有 9/8 delayed-EOD 歷史 receipt |
| Receipt | `output/paper_execution_eod_replay/receipts/<execution-date>/` 下的 terminal operational receipt，綁 recommendation、snapshot、fill ledger 的 exact path/hash 與實際 `recorded_at` | `execution_event_time_proven=false`、`research_only`／`formal_credit` 邊界不符、缺 fill 或跨日 missed session 時維持 pending／no-credit，不升 Formal |

最小接線順序是：fresh copilot process 先讀 active date-scoped runtime binding，解析
上述 canonical paths；接著以 decision 前 snapshot 建立 recommendation，Paper queue
固定同日 identity，EOD 僅消費真實 source rows 並寫 terminal receipt，最後由 Formal
consumer 以 receipt exact paths/hash 重驗。任何 legacy D path 只可進入明確的
`historical_diagnostic_readonly` 分支，不能流入 recommendation、Paper state、fill
或 common identity。`decision_at` 必須早於 execution window，跨日 replay 保留真實
`recorded_at` 並標記 `historical_credit=false`；沒有把 delayed EOD 提升成盤中事件。

本段的實作分工是：Formal owner 維護 runtime source contract、receipt／identity
consumer 與 readback；Paper wrapper owner 維護 repository isolated state／fill 的
exact producer；ML owner 將 copilot caller 的 `paper_state_db` 與 recommendation
root 讀自同一份受控 config；`v4_schedule_ops` 只把同一 fresh-process binding 傳給
既有 Task action。切換前 root 必須看到 9/9 與下一自然日各一份 config 的 config hash、
五角色 fresh-process readback、canonical source path/hash 及 rollback backup。若任何
一項不符，保留目前 active binding 與 D／repository 分離，將新 candidate 留在
`candidate_only`，以已保存的 exact backup 原子回退；不改 D 原始資料，也不把此 plan
當作已完成 3/3。

### Paper receipt custody 與 Formal eligibility 分流（本輪新增）

本輪把「已由 Paper writer 提交且可逐欄重讀」與「可以進入 Formal」分成兩個明確狀態，
避免 9/8 真實 delayed-EOD receipt 因 fill IDs 齊全而取得 Formal count。具體 readback
保存在 `output/v4_next_formal/paper_receipt_formal_eligibility_readback_20260908.json`。

`data_module/formal_daily_input_producer.py::_paper_execution_receipt_projection()` 現在
先要求單一 processed receipt 完整列出本輪 candidate 的 fill-ID 集合，再以 receipt 的
`candidate_path`／`result.fills` 與 `result.ledger` 對照 SQLite `paper_trade_ledger` 的
每個持久欄位：identity、日期、side、股數、reference／fill price、commission、tax、
slippage、turnover、execution gap、status、source event 與三個 safety flags。它使用
query-only 連線並在 `finally` 關閉，財務欄位以 `Decimal` 比對；因此相同 IDs 但欄位
漂移也會被拒絕。

只有 `custody_verified=true` 才表示 receipt 對應完整的 immutable fill rows；另須同時
滿足 `formal_eligible=true` 才會把 `verified`／`formal_ready` 設為 true。後者要求：
`execution_event_time_proven` 與 `formal_consumer_compatible` 均為 true、同 session
的 event-time replay、官方 timestamped intraday/session-open source、source bytes
的 exact file hash 與正 row count，以及 `event_at <= capture_at <= recorded_at <= observed`
和 execution date 對應。現在 9/8 的真實 EOD receipt 會得到
`custody_verified=true`、`formal_eligible=false`、`formal_ready_input_count=0`，保留
實際 `recorded_at` 與 research-only/no-credit 語意。

durable causal-ledger retry 也有向後相容的 fail-closed guard：舊 publication context
若只有 fill-ID 推導的 `paper_execution_receipt_verified=true`，或缺少
`formal_eligibility_schema_version=paper-receipt-formal-eligibility.v2` 的完整
eligibility projection，重試時會降為 false；它可以恢復 custody receipt，不能追認
delayed EOD 為 Formal。兩份以上完整 receipt 對應同一 candidate 時也視為 ambiguous，
不以 union 或較新的 receipt 掩蓋衝突。新增的 real producer negative、durable receipt
recovery、row-level commission drift negative 與 timestamped source positive 測試已
通過 42 項 Formal/Paper suite；`mypy` 與 `py_compile` 亦通過。這些測試只在隔離 temp
fixture 寫入或篡改測試 SQLite，不改 D／active binding／正式來源。

目前既有 Paper producer 的官方 `daily_prices` 只提供盤後 replay 的開盤欄位，沒有
可證明的盤中 capture timestamp；因此它可以產生真實 research-only fill 與 custody，
不能取得 Formal event-time eligibility。要解除這個最後 gate，Paper source wrapper
需在真實台北 session open 取得經核准的官方 intraday/session-open bytes，保存
`execution_source_capture_path`、file hash、row count、`execution_event_at` 與
`execution_source_capture_at`，再由既有 queue／Formal consumer 以同一 receipt 重驗。
Fubon research adapter、盤後 daily row、事後重標時間、fixture 或估算價格都不符合
這個來源契約；在新來源完成前維持 custody-only/no-credit，不能回填 9/8。

### MIS raw capture 契約補正（2026-09-08）

`data_module/paper_event_source_capture.py::capture_twse_session_open_prices` 已提供
真正的 bounded 官方來源 producer；`scripts/capture_paper_event_source.py` 是其明確
唯讀 CLI。它只支援固定 endpoint
`https://mis.twse.com.tw/stock/api/getStockInfo.jsp` 的 `tse_####.tw` channel，
只在台北當日 `09:00 <= now < 13:30` 執行，每個 response 以 `4 MiB + 1` 讀取界線、
HTTP status、final URL、content encoding 與 parser 驗證，將原始 `raw_response.bin`、
v2 envelope 及 hash 保存到全新 TEMP 目錄。它不產生 fill、不寫 D／Paper ledger，
正式執行必須使用真實自然時間，不以 `--now` 或歷史補抓取代 session。

v2 envelope 的 `execution_event_at` 是受控 Paper 模擬的 session-open 事件；MIS 的
`tlong`／`t` 是每檔 quote observation time，`o` 是 capture 當下回應的當日 open quote。
parser 以 raw response 的 `msgArray` 重建每列股票、日期、觀測時間與 Decimal price，
每列時間可以不同，但必須落在 envelope 的共同 `capture_window`；沒有自填的
`raw_rows` 欄位可供驗證。Formal receipt 另以實際 fill 的 stock、event date、reference
price、數量與同一 raw bytes 綁定，不能把 quote observation 或 `o` 直接改名成成交時間。

若 Paper receipt 已達 `formal_eligible=true`，causal publication 會把 capture envelope、
raw response 與 custody metadata 以 `fsync` 後 create-only hard-link 保存；retry 會重新
讀這些 bytes、檢查完整 hash/path、parser、source metadata 與 durable fill custody，再
呼叫同一 Formal validator。舊 v1 projection 或缺少／篡改 v2 custody 一律降為
Formal-ineligible。既有 `daily_prices` 盤後 replay 仍是 custody-only/research-only，
不可回填 9/8 或假造盤中事件。

## 自然 session caller 與 isolated Paper→Formal E2E（本輪收尾）

本輪完成的 ownership 是 Paper writer/caller、session-open capture、isolated EOD
接線及其 CMD／registration plan；root 只負責既有 Windows Task 的 live registration
readback。recommendation producer 仍由 Ops 維護並繼續寫入 D，沒有搬移或合併歷史
推薦。Paper canonical state／ledger 仍是 repository isolated output。

| 邊界 | 實際接線 |
| --- | --- |
| session source | `scripts/scheduled/run_paper_event_source_capture_daily.py`；預設讀 `D:\Min\Python\Project\FA_Data\output\recommendation\runs` 與 `D:\Min\Python\Project\FA_Data\sqlite\twstock.db`，寫 `output/paper_execution_eod_replay/event_captures`、同一 operation root 的 `scheduled/paper_event_source_capture/latest_status.json`。 |
| Task action | 已存在的 `baldr-formal-pit-sidecar-postcutoff-daily` 由 `scripts/scheduled/run_formal_pit_sidecar_postcutoff.cmd` 先跑 PIT sidecar，再串接上述 capture runner；不新增平行 Task。wrapper 路徑已以 CRLF 與 script existence tests 驗證。 |
| EOD writer | `scripts/scheduled/run_paper_execution_daily_isolated.py::run_isolated` 以 execution date + recommendation file/content hash exact resolve durable manifest，寫 `paper_execution_candidate_bound.json`，再由 repository Paper ledger／receipt producer append research-only rows。 |
| Formal consumer | `data_module/formal_daily_input_producer.py` 以 processed receipt exact path/hash 重讀 candidate、ledger rows、capture envelope 與 bounded TWSE MIS raw bytes；完整 custody 與 event-time eligibility 才能取得個別 Paper formal eligibility，三來源 common identity 仍是整體 Formal gate。 |

捕捉的 durable bucket 形狀為：

```text
output/paper_execution_eod_replay/event_captures/<execution-date>/<recommendation-file-hash[7:23]>/
  capture.json
  raw_response.bin
  manifest.json
```

bucket 仍保存完整 recommendation file/content hash、source endpoint、raw／capture／
manifest hashes、row count、execution event／capture clocks 與 parser identity。正式
capture 只接受台北 `09:00 <= captured_at < 13:30`，production caller 傳 `now=None`，
因此 completion clock 取 bounded HTTP read 完成後的 UTC 時間；測試注入 clock 只用於
隔離 deterministic QA。重試上限為 3 次，僅官方 GET／空 response 等 transient failure
可 retry；每次 retry 都重驗原始 recommendation bytes hash，任何 identity、hash、path、
schema、session 或既有 durable custody 衝突直接 fail closed。完整 capture 重跑不再
GET，所有失敗 attempts 留在 status。

`run_paper_execution_daily_isolated.py` 的 EOD writer 依同一 execution date 與 frozen
recommendation identity exact resolve durable capture，將候選與 capture manifest 綁成
`paper_execution_candidate_bound.json`，再產生 repository research-only processed
receipt。Formal consumer 重新讀 receipt、candidate、ledger SQLite、capture envelope
與官方 raw response，逐列比對 stock、reference price、fill／費稅／股數、event/capture
時間與 hash；只有 custody 與 event-time eligibility 都成立才可進 Formal，今日 delayed
EOD 或缺三來源仍維持 candidate/no-credit。

本輪新增的端到端測試為
`tests/test_paper_formal_daily_source_chain.py::test_isolated_eod_writer_binds_durable_capture_then_formal_reads_receipt`。
它以真實 Paper preopen／isolated EOD writer、真實 durable capture producer、processed
receipt 與 Formal readback 連成同一條鏈；官方 MIS HTTP 僅在測試中以 bounded response
stub 提供固定 raw bytes，沒有對 D 發 request 或寫入，亦沒有製造歷史 fill。結果為：
`status=machine_verified_candidate`、capture／candidate binding readback true、
receipt `queue_state=processed`、Formal `consumer_verified=true`、Paper custody 與
event-time eligibility true；整體 `formal_ready_input_count` 仍不是 3，因 Rule／PIT／
common identity gate 沒有被測試越權放行。

定向回歸結果：

```text
tests/test_paper_formal_daily_source_chain.py
tests/test_paper_execution_isolated_scope.py
tests/test_scheduled_cmd_scripts_exist.py
tests/test_scheduled_cmd_scripts_task_names.py
tests/test_pit_preopen_schedule.py
47 passed, 1 skipped
```

`1 skipped` 是 Windows reparse/junction 能力依環境不可用的負例，不是 production
成功宣告。五個 changed Python source 以同一命令通過 mypy
`--explicit-package-bases --follow-imports=silent`，並通過 `py_compile`。本次修正也讓
Formal capture Decimal validator 接受 read-only Paper ledger 的 validated `Decimal`
物件與 canonical wire string，明確拒絕 float；因此實際 writer 的 fill／reference
price 可逐列重驗，沒有靠字串或任意 self-authored hash 放行。完整 QA JSON 為
`output/v4_next_formal/paper_isolated_e2e_readback_20260908.json`，file SHA-256=
`sha256:fa717c02f20382aad09ae3d1029d62e8fd4e8bbe7479118f4faa8d309e29f5b8`。

root 已核可並實際套用 active runtime binding；本輪不重複 apply、不覆寫 binding/config。
既有 18:00 Task action 會直接讀目前工作樹的 wrapper。下列是由 root 依自然 session／
EOD 時窗執行的受控命令；它們會依契約抓取或寫入 durable capture、Paper ledger／receipt，
不是唯讀 probe：

```powershell
& .\.venv\Scripts\python.exe scripts\scheduled\run_paper_event_source_capture_daily.py
& .\.venv\Scripts\python.exe scripts\scheduled\run_paper_execution_daily_isolated.py
```

上列命令只適合在對應自然 session／EOD 時窗由 root 依 Task action 受控執行，再以
下列路徑做 readback；不應以人工 `--now` 冒充 live capture。任何缺 recommendation、缺 official session source、
receipt／ledger 不一致或 common identity 不完整都應保持 blocked/candidate-only，並把
實際 `recorded_at` 留在 receipt，不能回填 9/8 或把 delayed EOD 當盤中 Formal source。

真正的唯讀 readback 路徑是：

```text
output/paper_execution_eod_replay/scheduled/paper_event_source_capture/latest_status.json
output/paper_execution_eod_replay/scheduled/paper_execution/latest_status.json
output/paper_execution_eod_replay/event_captures/<execution-date>/<hash-prefix16>/manifest.json
output/paper_execution_eod_replay/receipts/<processed-receipt>.json
output/paper_execution_eod_replay/paper_trade_ledger.sqlite (SQLite mode=ro, PRAGMA query_only=ON)
```

readback 應重驗 status／manifest／receipt 的 file hash、recommendation identity、日期、
source custody 與 ledger rows；不要用 readback 命令代替受控 producer，也不要將 status
檔案的 `formal_credit=false` 改寫成成功。

## Calendar rolling：跨日、跨週末與跨月 successor（2026-09-08）

### Ownership 與實際入口

本片由 Formal/Paper owner 維護 `data_module/formal_runtime_roll_forward.py` 及其
定向測試；既有 `scripts/scheduled/run_paper_execution_daily_isolated.cmd` →
`paper_execution_retry_runner.run_scheduled` → `run_from_environment` 是自然 caller。
capture 與 persistence 重用既有 `scripts/capture_official_calendar_bundle.py` 及
`scripts/persist_official_calendar_bundle.py`，沒有新增 Task，也沒有改 scheduler
檔案或 active binding。固定 portfolio clock 維持 9/9 cumulative 起點；calendar
anchor 只作一次性環境 pin，selected successor 另記在 rolling source evidence。

### 已完成的 bounded rolling 行為

`FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE` 指向 active v6 的 immutable 9/9–9/30 bundle。
resolver 先從這個 exact path 選嚴格晚於 Taipei today 的第一個 TWSE／TPEx 同時開市日，
因此 9/10 與週末後的下一開市日可由同一份 config 自動讀回，不必人工改環境。日期列只
能跳過明示的兩市場休市 blocker；未知、損壞、future 或 raw custody 不足會拒絕。

bundle 用盡時，resolver 只讀
`output/formal_daily_publications/calendar_candidate_archive/rotations/<source-bundle-sha256>.json`。
link 以完整 source bundle hash 命名，並驗 source／successor path、file hash、bundle
hash、連續 range、link hash、安全欄位與 successor raw custody；不掃描 latest。沒有
link 時，才以 31 個曆日建立下一段 bounded official TWSE annual + TPEx monthly
candidate，透過既有 persist CLI 複製 exact bundle/raw bytes 至 candidate archive，再以
create-only fsync／hard-link 發布 successor link。舊 bundle、clock、環境、D 原始資料及
controlled path 均不覆寫；candidate 仍不等於 Formal credit。

### 可重驗證據與測試

隔離的實際雙來源鏈測試為
`tests/test_formal_runtime_roll_forward.py::test_calendar_successor_real_capture_persist_validator_survives_temp_cleanup`。
測試只在 HTTP 邊界提供已保存、official-shaped 的 TWSE 2026 年度與 TPEx 2026-10
raw fixtures；capture main 真實解析、建立 source response/raw metadata，persist
script 以真 subprocess 執行，production `_inspect_calendar_bundle` 真實驗證 bundle
hash、兩份 inline raw response、sidecar manifest、file hash 與日期。persist 後刪除
TEMP candidate/raw，resolver 仍從 durable archive 讀回 successor；第二次 replay 不
再呼叫 capture 或 persist。最後另將 durable bundle 改寫為不同內容而不重算 hash，確認
resolver 以 `official_calendar_bundle_hash_invalid` fail closed。這是 fixture-boundary
工程證據，不宣稱 10/1 已有自然 HTTP 或自然 Paper credit。

定向結果：

```text
tests/test_formal_runtime_roll_forward.py
tests/test_paper_execution_retry_runner.py
25 passed
```

型態檢查：

```text
\.venv\Scripts\python.exe -m mypy data_module\formal_runtime_roll_forward.py --explicit-package-bases --follow-imports=silent
Success: no issues found in 1 source file
```

`output/v4_next_formal/runtime_cross_day_roll_forward_readback_20260908.json` 保存本片
測試命令、固定 clock invariants、anchor／successor contract、TEMP cleanup 與安全邊界；
其 SHA-256 為 `sha256:31704a09210a0544343f7f8ddd3c3392ba2e0fe7c494cce298d0f8df71dfc1fc`。
root 已獨立重跑 25 passed（含真 capture→persist→validator→durable replay）；尚未發生
新版 live 自然跨月 renewal，故 handoff 不把本片隔離 fixture 當成自然實績。

### 失敗／回退語意

capture timeout、官方來源不足、persist 失敗、archive 不完整、raw／bundle／link hash
不符或 successor range 不連續都會停止 renewal；目前 active anchor 保留，caller status
必須呈現 roll-forward degraded／非零 exit。完整相同 bytes 可 idempotent replay，內容
改變或半成品不會覆寫既有 immutable 檔。下一個自然重試仍從同一個 anchor 或已存在的
完整 hash-keyed link 開始，固定 portfolio clock 不重置。

## Formal inspector 與自然 0/3→3/3 驗收界線（2026-09-09）

### 目前實際 caller 盤點

本輪沿 active v6 binding 逐段讀取既有入口，沒有再發現缺少的 production caller：

| 順序 | 既有入口 | 寫入／消費 | 自然日條件 |
| --- | --- | --- | --- |
| 1 | `scripts/scheduled/run_pit_sector_membership_preopen_capture.cmd` → `run_pit_sector_membership_preopen_capture.py` | 官方 TWSE／TPEx PIT raw、machine receipt、durable archive | 台北 07:00–08:30；過 cutoff 只可重用完整 archive |
| 2 | `scripts/scheduled/run_formal_rule_source_preopen.cmd` → `data_module.formal_rule_source_producer` | exact machine Rule source-window bundle；09:00 後由 daily consumer 重用 | 首次 machine bundle 必須在 08:30 前；daily Rule 只消費相同 bundle |
| 3 | `scripts/scheduled/run_formal_pit_sidecar_postcutoff.cmd` | 讀同日 PIT archive，並串接 `run_paper_event_source_capture_daily.py` | 台北 09:00 後；不重新抓同日 PIT |
| 4 | `scripts/scheduled/run_formal_input_producer_daily.cmd` → `run_formal_input_producer_daily.py` | 讀 exact Rule/PIT/Paper paths，產生三來源 receipt、common identity 與 Formal status | Rule 09:00–13:30；缺任一來源以非零／candidate-only 結束 |
| 5 | `scripts/scheduled/run_paper_execution_daily_isolated.cmd` → `paper_execution_retry_runner.run_scheduled` | 凍結 recommendation 的 Paper queue、實際 fill、ledger／receipt；retry 後呼叫既有 runtime roll-forward | EOD 受控時窗；跨台北自然日不重用 pending，roll failure 使 overall status degraded |

active binding 的 date-scoped root 由 `FORMAL_DAILY_RUNTIME_CONFIG_ROOT` 讀取當日 `Asia/Taipei/YYYY-MM-DD.json`；固定 cumulative portfolio clock 由 `FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST` 綁定，daily Rule clock 只以 lineage 版本化。roll-forward 由既有 Paper retry runner 在同一 process boundary 後置觸發，建立下一自然開市日 candidate config；不改 binding、不改 scheduler、不將 candidate 自動升格。日曆耗盡時只沿完整 source-bundle hash successor link 續接，沒有 successor 或來源驗證失敗則保留舊 anchor 並回報 degraded。

週末 dependency gate 的明確 `not_trading_day` 狀態現在在 retry runner 入口直接作
`skipped_non_trading_day` no-op，不呼叫 Paper adapter、不建立 fill；迴圈結束仍執行既有
bounded roll-forward，所以週末不會被舊 explicit runtime path 卡住，也不會把週末誤當成交易日。

### 真 producer→common identity→Formal inspector 證據

新增測試將原先舊的自填 daily lineage 改為實際建立 machine Rule source bundle，再以同一固定 clock 產生 causal ledger、Rule history 與 PIT sidecar。它寫入並重讀 common identity，接著把三份 exact producer paths 交給 `scripts.inspect_ml_formal_input_readiness.build_readiness_report`；正式 inspector 逐一重載三個 consumer，得到 `ready_input_ratio=3/3`。同一測試將 ledger path 改成不存在的檔案後再次執行 inspector，結果低於 3/3 且 ledger state 為 `missing`，證明 common identity 不能掩蓋缺來源。

```text
tests/test_formal_common_identity.py::test_real_three_source_identity_replays_through_exact_consumers
1 passed
```

這是 isolated temporary fixture；三來源皆是同一測試 process 建立的 candidate，`formal_oos_allowed=false`、`promotion_eligible=false`，不能視為自然日期 credit。既有 9/8 delayed EOD receipt 同樣保留 custody／research-only 語意。

### 2026-09-09 當下只讀 readiness

使用 active binding 執行：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_formal_operational_readiness.py --publication-root output\formal_daily_publications --readiness-path output\v4_next_root\formal_readiness_baseline.json --paper-receipt-root output\paper_execution_eod_replay\receipts --output output\v4_next_formal\formal_operational_readiness_actual_20260909.json
```

讀回 `output/v4_next_formal/formal_operational_readiness_actual_20260909.json`，file SHA-256 為 `sha256:4203587cc50735627e02a852c3890158669cc4c979e665442bf74893080de8f0`；觀測時間為 `2026-09-08T20:46:01.109562+00:00`（台北 `2026-09-09T04:46:01.109562+08:00`），phase=`before_pit_cutoff`、target=`2026-09-09`、status=`blocked_no_formal_credit`、credit=`no_credit`、formal count=`0/3`。此結果符合自然時間：PIT、Rule、Paper 窗口尚未到；同時 readiness baseline 仍是 9/8 舊日，故報告列 stale baseline。Inspector 現已依實際 host 06:00 Pacific 動態映射 Paper EOD（本日台北 21:00；冬令台北 22:00），不再使用過時的 15:05。命令沒有提供 scheduler registration query；這是觀測輸入缺少，不是 Task 缺失證據。此 readback 不寫 D、沒有下單、沒有手動補自然信用。

### 驗證數字校正與自然驗收清單

先前所稱 `67 passed` 有可重跑的完整命令，並非 25-test calendar 子集的數字；本片又補上
週末 `not_trading_day` gate no-op 回歸，因此目前同一完整集合為 `68 passed`：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_formal_runtime_roll_forward.py tests\test_paper_execution_retry_runner.py tests\test_formal_runtime_config.py tests\test_formal_runtime_wiring.py tests\test_scheduled_cmd_scripts_exist.py tests\test_scheduled_cmd_scripts_task_names.py tests\test_pit_preopen_schedule.py -q -o addopts= -p no:cacheprovider --tb=short
68 passed in 4.43s
```

同一份 QA JSON `output/v4_next_formal/runtime_cross_day_roll_forward_readback_20260908.json` 已補上
修補前 67 項的精確命令／結果、目前 68 項完整命令、真 inspector E2E、缺來源負例、定向
測試、mypy 與 py_compile；更新後 file SHA-256 為 `sha256:68ca2c5c0354b7ad5f933b5835c60b934c3e5fe5b1dc4363a622a32ded136642`。
其中原有 calendar 子集仍是 `25 passed`，與修補前 67 及目前 68 是不同測試集合。

下一次自然驗收只使用當下 process clock，不使用 `--date`／`--now` 寫正式輸出：

1. 台北 07:00–08:30 讀 active date-scoped config，執行 PIT preopen wrapper，確認同日 archive、raw／metadata／receipt hash 與 machine consumer readback。
2. 台北 09:00 後執行 sidecar wrapper，確認只重用同一 PIT archive，並讀回 Paper event capture 的 exact recommendation file/content hash。
3. 台北 09:00–13:30 執行 Formal input wrapper，確認 Rule source predecessor path、source-window hash、固定 portfolio clock 及三份 receipt 的 exact match；接著讀 common identity manifest 與 Formal inspector。
4. Paper EOD 受控 task 完成後，重新讀 Paper candidate、實際 fill、費稅、cash／position ledger 與 receipt；只有 event-time、source custody、日期窗與 common identity 全部成立，才可由 root 評估自然 3/3。任何 delayed EOD、缺 fill、缺 PIT／Rule 或 identity mismatch 都維持 candidate／blocked，保留 `recorded_at`，不補歷史信用。
5. 下一開市日、週末後及跨月由同一 runtime config root 自動選 exact calendar day；確認 config path、固定 clock id／manifest hash、daily Rule lineage 與 Paper／PIT source date 共同前進，且沒有人工改 env。跨月 renewal 需重新取得官方雙來源 raw custody 並透過 successor hash 驗證，不能把本輪 fixture chain 當 live 10/1 實績。
