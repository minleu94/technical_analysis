# baldr Scheduled Operational Wrappers

These wrappers are intentionally conservative. They use CMD files and Windows built-in `schtasks.exe` because the previous PowerShell `.ps1` registration path was blocked by local execution policy. Do not use `Set-ExecutionPolicy` or bypass local policy. Only the dedicated Decision/Evidence capture task enters confirmed append-only formal evidence capture；EOD Paper execution may append the separate research-only Paper ledger under its own bounded contract. 所有 Gate 都由機器重驗，不建立等待人工批准的排程 task。

Aggregate `register`／`register-all` 只允許在 Windows `Pacific Standard Time`
主機建立這些以 Pacific local time 表示的 task；`dryrun` 仍可在其他時區唯讀檢查。
Paper Portfolio 的 trigger 固定為 Pacific 16:15：PDT 時是台北次日 07:15、PST
時是 08:15。adapter 以真實 Asia/Taipei 08:30 cutoff guard；兩種 offset 都會等待
cutoff，不能把台北 09:30 開盤後時間稱為盤前。
完整 Windows 清冊目前是 17 個每日 task 加 1 個 weekly task，共 18 個。
`baldr-ml-allocation-forward-daily` 使用 pinned UTF-16 XML 與獨立 preflight，
aggregate `register`／`register-all` 不會建立或覆蓋它；aggregate `unregister`
也只會查詢並保留它，回復必須依 registration plan 的專用 delete 命令進行。

## Tasks

| Task | State | Trigger | Behavior |
|---|---:|---|---|
| `baldr-data-update-quick-daily` | enabled after register | daily local time 04:20 | Runs the non-UI quick data update path for the recent weekday window. Writes market data CSV / SQLite updates plus status and logs under `OUTPUT_ROOT/scheduled/data_update_quick/`. If TPEX has failed dates, the task continues later steps and writes `passed_with_warnings`. |
| `baldr-official-market-events-daily` | enabled after register | daily local time 04:50 | 以官方來源建立 append-only market-event vintages；無公告／生效／修訂時間的事件 fail closed，不反推歷史可得時間。若 verified latest publication 的歷史起點被縮窄，task 會自動切換到 2014–當年度做 recovery；coverage 完整後才恢復兩年增量，避免 pointer 長期遺失歷史。 |
| `baldr-data-freshness-check-daily` | enabled after register | daily local time 05:00 | Read-only SQLite / `DATA_ROOT` freshness check. Also verifies raw TWSE / TPEX daily price files for the latest SQLite daily date. Writes only status and logs under `OUTPUT_ROOT/scheduled/data_freshness/`. |
| `baldr-ml-raw-pit-refresh-daily` | enabled after register | daily local time 05:05 | 先讀取 data-update quick 的 terminal freshness proof；daily／technical core date 就緒且輸出磁碟通過唯讀容量 preflight 時，以 SQLite `mode=ro/query_only` 建立全市場 immutable raw PIT publication。正式 safety reserve 固定至少 200 GiB；低於此值的 CLI 參數 fail closed。scheduled raw 的 35 GiB persistent 與 40 GiB temporary 上限另計，required headroom 至少 275 GiB。空間不足只寫 `blocked_insufficient_storage`，不啟動 builder；既有同 cutoff 且較新的 publication 會跳過，不寫回來源 SQLite、不改變 formal gate；完成後由 Direct/OOC maintenance watcher 依 pointer/hash 自動接續。 |
| `baldr-recommendation-snapshot-daily` | enabled after register | daily local time 05:10 | Runs the research-only recommendation snapshot path after freshness. Saves one recommendation result under `OUTPUT_ROOT/recommendation/runs/` and writes status/logs under `OUTPUT_ROOT/scheduled/recommendation_snapshot/`. The scheduled caller also emits immutable candidate-only packets under the repository `output/forward_position_thesis/YYYY-MM-DD/`; recommendation reasons and Decimal-text scores are preserved, while missing explicit invalidation／horizon policy remains `awaiting_explicit_policy`. It does not write the production evidence DB, does not confirm evidence, does not change portfolio state, and does not automate trading. |
| `baldr-evidence-pipeline-dry-run-daily` | enabled after register | daily local time 05:15 | Runs `scripts/run_evidence_pipeline.py` with `--dry-run` and forwards the resolved `DATA_ROOT` / `OUTPUT_ROOT` explicitly. Before the child, it refreshes the derived Paper health baseline from the repository snapshot using the preopen status receipt and the append-only Paper trade ledger; the scheduled path also enables `PaperPositionIdentityProvider`, which derives a stable ID only from a verified bounded flat-to-positive Paper fill. Same-snapshot or receipt-backed no-event continuity may preserve human fields, while missing coverage or entry evidence keeps the current row `WATCH`/unknown and preserves prior fields in history. Because the v1 ledger has no same-day sequence/time, multiple material fills for one stock on one date are blocked instead of ordered by `fill_id`. It then runs `--produce-position-health-sources`: quick/freshness receipts are checked first, and a read-only SQLite capture of selected `technical_indicators`/`daily_prices` rows is bound to real capture start/completion timestamps. The condition and Decimal metrics artifacts are create-only immutable; missing identity never falls back to stock code, and condition remains observation-only until a governed thesis/current condition exists. The CMD caller also consumes every immutable receipt under `output/forward_position_thesis/bindings/` through `--paper-health-forward-binding`; the consumer rechecks candidate/recommendation file and content hashes, Paper source event/order/fill, ledger row and evidence hash, then adds lineage provenance only. Missing or awaiting binding stays degraded and never supplies a human thesis. The CMD caller also runs `--evaluate-position-health-transition`, passing the source capture completion to the evaluator so an earlier quick receipt cannot backfill a later database read. The evaluator writes only the isolated `OUTPUT_ROOT/position_health_transition/` proposal receipt and append-only proposal repository. The same 05:15 CMD action passes `--run-exit-effectiveness`, which invokes `scripts/run_exit_effectiveness_daily.py` as a bounded 120-second child with the transition SQLite, repository Paper ledger, market SQLite, and verified calendar cache. Its create-only research artifact is written under `OUTPUT_ROOT/exit_effectiveness/YYYYMMDD.json`; timeout, malformed output, blocked source, or non-zero child status is surfaced in `latest_status.json` and returns non-zero. The child has no historical as-of switch, never applies a transition, never places an order, and never treats a stale prior artifact as a successful run. Missing thesis/condition/metrics remains `degraded`; only a proposal is written, never a human approval or execution action. Writes report, status, and logs under `OUTPUT_ROOT/scheduled/evidence_pipeline_dry_run/`; health source artifacts are under `OUTPUT_ROOT/position_health_sources/`. Scheduled status inherits freshness and pipeline overall status: missing / stale / blocking data is `degraded`, while complete observed-or-estimated MoneyDJ provenance is `ready_with_advisories`. |
| `baldr-ml-promotion-evidence-daily` | enabled after register | daily local time 05:17 | 固定 discovery 並重驗 formal OOC v5、雙 replay、Shadow outcome、逐 horizon calibration／drift 與 hash custody。證據不完整時只寫 blocked status，不更新 compatible pointer；若 OOC readiness 不足，blocker 會附上 `formal_ooc_dataset_full_market_not_ready:<readiness_check,...>` 的具體檢查名；若 direct store 落後最新 verified official market-event publication，會輸出 `formal_ooc_corporate_action_custody_stale:<field,...>`；完整時也只發布 unsigned evidence。 |
| `baldr-ml-promotion-authority-daily` | enabled after register | daily local time 05:18 | 由獨立 DPAPI user-scope authority 重驗 compatible evidence、Gate registry 與決策有效窗。只有所有機器門檻通過才簽章；否則成功 fail closed，維持 alpha 0。 |
| `baldr-ml-allocation-copilot-daily` | enabled after register | daily local time 05:20 | 執行配置型 ML promotion 評估並寫入 append-only sidecar、promotion artifact 與 `latest_status.json`。缺少、無效或未授權證據時仍成功完成每日流程，但固定輸出 `formal_oos_allowed=false`、`selected_alpha_bp=0` 與四條未通過 lane；不改寫來源資料庫或投組狀態。 |
| `baldr-decision-evidence-capture-daily` | enabled after register | daily local time 05:25 | 依台北時間選擇最近一個**已到達**的 08:30 日曆決策日，依序確認保存 durable Decision Desk snapshot 與 Evidence Event；不再把隔日 cutoff 當成已發生資料。既有 hash／unique key 使重跑轉為 duplicate；任一步失敗即回傳失敗並保留下一次重跑能力。它不推定交易日／成熟日、不改 Rule／Advice／Portfolio 狀態，也不連接券商執行。 |
| `baldr-paper-portfolio-daily` | enabled after register | daily local time 16:15 Pacific（PDT 台北次日 07:15；PST 台北次日 08:15，adapter guard 至 08:30） | 由 `run_paper_portfolio_daily_isolated.py` 先以 D 槽 snapshot 的 SQLite read-only consistent backup 建立 repository state；兩種 offset 都等待真實台北 08:30，再 append preopen/T-1 估值 snapshot。之後 D snapshot 永遠只讀，EOD 與 Formal 共用 repository state。盤前只以 `mode=ro/query_only` 讀市場 SQLite 與 EOD ledger；不覆寫既有 snapshot、不把 snapshot 當成交、不自動調倉、不修改 Advice，也不具券商執行能力。 |
| `baldr-ml-allocation-forward-daily` | registered by dedicated XML | daily local time 16:15 Pacific（PDT 台北次日 07:15；PST 台北次日 08:15，等待 Asia/Taipei 08:30，08:35 後 fail closed） | 只執行 repository-isolated、candidate-only ML forward shadow。每日 config producer 依 offline official calendar、單一交易日 freshness、archive custody 與固定 V2 release manifest hash 建立 create-only config；child 必須保留完整 outer payload，`forward_credit_granted=false`。不寫市場 SQLite、不下單、不改正式 Paper／Formal 狀態；註冊前先執行 `run_ml_allocation_forward_daily.py --preflight`，aggregate registration 不會替換其設定。 |
| `baldr-pit-sector-membership-preopen-capture-daily` | enabled after dedicated register | daily local time 16:00（PDT 台北 07:00；PST 台北 08:00） | 在台北 08:30 前以官方 TWSE／TPEx response completion timestamp 建立 current-day PIT machine candidate，保存 raw custody、machine consumer readback 與 durable archive；同一 task 會先重驗當日獨立 denominator，缺少時自動以 data.gov dataset/resource、官方 Swagger 與授權文件建立 bounded create-only refresh；來源失敗會保留具體 status 並讓 sidecar 下輪重試。若 clock 或 response 越過 cutoff，fail closed，不建立可被當日 handoff 消費的 archive。 |
| `baldr-formal-pit-sidecar-postcutoff-daily` | enabled after dedicated register | daily local time 18:00（PDT 台北 09:00；PST 台北 10:00） | 先只讀盤前已完成的 PIT archive，以當下 Taipei decision clock 重建 handoff；sidecar 階段通過獨立 denominator、coverage、license scope 與 assembler readback 才 create-only 發布 sidecar，隨後同一 action 呼叫 `run_paper_event_source_capture_daily.py`，在台北 09:00..13:30 以固定 TWSE MIS endpoint 保存 Paper session-open raw bytes。沒有完整證據寫 blocked receipt，不重新抓取同一自然日 PIT HTTP source；Paper capture 缺來源時只保留 bounded retry 診斷，不建立 fill。 |
| `baldr-formal-input-producer-daily` | enabled after register | daily local time 21:25（PDT 台北 12:25；PST 台北 13:25） | 使用當下自然時間執行 Rule／causal Paper ledger／current PIT 的 bounded machine handoff。Rule 與 ledger 的 immutable manifest、source custody、publication context 與 receipt 寫入 repository output durable root；candidate 與 development 工作區每輪使用新的 TEMP 子目錄。缺 Rule source 不會阻止 PIT capture；缺任一 input 會保存具體 blocker，candidate-only 或 blocked 回傳非零狀態，不計入 Formal 3/3。 |
| `baldr-paper-execution-eod-replay-daily` | enabled after register | daily local time 06:00（PDT／PST 分別對應台北 21:00／22:00） | 先以固定 D 槽唯讀 dependency gate 驗證同一台北自然日的 quick update、freshness、daily_prices open rows 與 TWSE／TPEX source hash，再從持久 recommendation queue 選取下一官方 session 已到期的 frozen input。Paper writer 以 execution date 與完整 recommendation file/content hash 讀取同一份 repository `event_captures` durable manifest；缺失、hash／日期／source custody 不符時 fail closed。只有 durable capture、candidate、processed receipt 與 query-only ledger readback 全部綁定才保存 research-only fill；Formal consumer 仍另驗 event-time 與三來源 common identity。上游暫時來源最多重試 3 次並保留每次診斷，terminal blocker 立即停止；不跑 snapshot valuation，也不接受 D／環境變數 writer path 覆寫。 |
| `baldr-ml-direct-chain-maintainer` | enabled after register | daily local time 05:30 | 自動解析並重驗最新全市場 immutable raw PIT pointer、official market-event custody 與目前 Direct identity，然後啟動／維持 `maintain_ml_direct_v3_refresh_chain.py --watch-formal-inputs`。使用既有 instance lock 防止重複訓練；無效輸入只寫 `blocked_invalid_bootstrap_input`，不寫來源 SQLite、不建立未受控 sidecar、不放寬 formal／alpha／broker gate。 |
| `baldr-v2-2-weekly-collection` | `weekly-register` 後啟用 | 每週日 18:00 | 執行 `run_v2_2_weekly_collection.cmd`，以 SQLite read-only 讀取來源並將 evidence append 至 sidecar。對外狀態為 `pending_human_review`；需要人工判讀，但不代表 Gate 通過、不寫 weekly history，且 `write_intent=false`。 |

`run_paper_portfolio_daily.cmd` 先呼叫 `run_paper_portfolio_daily_isolated.py`。首次
執行只將 `DATA_ROOT\output\paper_portfolio\paper_portfolio.sqlite` 以 SQLite
`mode=ro/query_only` 一致 backup seed 到
`<repo>\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite`，
並以 immutable `state_seed_manifest.json` 綁定來源 main/WAL/SHM hash；repository
state 後續由公開 `scripts/run_paper_portfolio_daily.py` append，D snapshot 不再是
writer target。若呼叫端設定 `PAPER_EXECUTION_RECOMMENDATION_JSON`，cmd 只會以同一
repository state 建立 T+1 next-session-open、bounded、research-only candidate；
不接受環境變數將 state／ledger 導回 D。16:15 Pacific 的 Paper Portfolio
hook 仍不追加 ledger；adapter 會在 PDT 早於台北 08:30 時等待真實 cutoff，
PST 則於 08:30 執行；目前 Pacific 06:00（PDT／PST 對應台北 21:00／22:00）的 EOD replay task
透過 `run_paper_execution_daily_isolated.cmd`／`run_paper_execution_daily_isolated.py` 固定使用
固定的 `D:\Min\Python\Project\FA_Data\output\recommendation\runs` 自動選取下一
official session 到期的 frozen recommendation，並以 repository operation root 的
`receipts` 保存每次 processed／
superseded／waiting／failed／skipped receipt。Queue 的唯一鍵是
`portfolio_id + next_official_execution_date`；同一鍵只採用最新的 frozen
recommendation，其餘候選會留下 `queue_state=superseded`，因此 processed hash 被排除後
不會在下一次重跑切換到較舊目標。它預設傳入明確的 append flag，將 research-only fill 寫入
repository 隔離的 `PAPER_EXECUTION_LEDGER_DB`；設定 `PAPER_EXECUTION_APPEND=0` 才保留 candidate-only
預覽。processed receipt 只有在 schema、receipt content hash、來源 recommendation
檔案 hash、candidate result 與 append/readback ledger 均可重驗時才會阻止同一 source
重跑；損壞或不完整 receipt 會被忽略並留下具體 diagnostic。candidate 會驗證 recommendation 的自然日、下一個官方 session、開盤價／
reference session 收盤成交量、Decimal 成本與自然日界線。preopen snapshot 已存在時，
它被視為 execution 的 T-1 起始狀態；EOD writer 只追加獨立 postfill transition，
不覆寫 snapshot。下一個 preopen runner 以唯讀 ledger 投影該 transition 至新 snapshot，
並以現金／股數守恆驗證。現有 `daily_prices` 是沒有逐列 capture timestamp
的 EOD 來源，runner 以台北交易日 15:00 的保守延遲重播門檻消費；15:00 前只回傳
`waiting_for_execution_source`，不把全天成交量拿來決定開盤 cap，也不宣稱即時成交。
Queue root 不存在、沒有待執行 source 或 source JSON 無法解析時，會輸出
`skipped_no_pending_recommendation` 及原始 blocker；不會靜默以 exit 0 偽裝成已處理。

若唯讀 scheduler query 顯示 `baldr-paper-portfolio-daily` 尚未採用最新時序，使用專用的
`scripts\scheduled\register_paper_portfolio_task.cmd dryrun` 核對後，再以同一腳本的
`register` 模式只更新這一個 task。既有 task 使用 `schtasks /Change` 只改 16:15
trigger 與 action，保留原有 principal、登入、電池與其他 settings；只有查不到 task
時才以 `/Create` 建立。16:15 Pacific 對應 PDT 台北 07:15、PST 台北 08:15，adapter
在兩種 offset 都等待真實台北 08:30；不能把 09:30 視為盤前。這個腳本不會呼叫 aggregate
registration，也不會修改其他 task。

Paper EOD task 若在唯讀 scheduler query 中缺失，使用專用的
`scripts\scheduled\register_paper_execution_task.cmd dryrun` 檢查後，再以同一腳本的
`register` 模式只建立 `baldr-paper-execution-eod-replay-daily`；它不會呼叫 aggregate
registration，也不會修改其他 task。06:00 Pacific 在 PDT／PST 分別對應台北 21:00／22:00，
所以不會在延遲 EOD source cutoff 前讀取開盤資料。Query 仍須實際讀回
`Task To Run`、`Last Result`、登入模式與電池條件；初次建立 task 的
`Last Run Time=1999/11/30` 或非零結果只是未成功執行／來源未就緒證據，不能當成 Paper
fill 已完成。scheduled Paper wrapper 只可使用研究用隔離 ledger；broker、正式行情與
Formal controlled path 永遠維持 false。

官方下一 session 判定優先讀取
`<repo>\output\paper_execution_eod_replay\calendar_cache\` 中由
`official-trading-calendar-cache.v1` 保存的 TWSE annual `holidaySchedule`。隔離
adapter 每輪先重驗同年度 cache；有效 cache 不發 request，缺失／過期／竄改／錯年份時才
對官方 endpoint 做最多兩次 bounded request，成功後以實際 response completion 建立新的
create-only 檔案，舊檔永不覆寫或刪除。每次結果另保存於 `receipts\calendar_refresh_*.json`，
因此失敗、保留舊檔與下一次重試都有可讀回狀態；refresh 只允許 operation root 內的 repo
output，不能使用 D 或既有正式 ledger。

每個 cache 保存原始 response bytes、HTTP status／headers、request／response URL、response
SHA-256、實際 `captured_at_utc`、七日 freshness window 及完整年度正規化 projection；consumer
會重新驗 raw hash、年份、完整 coverage、timestamp chain 與 expiry。年度表的 `weekday
absence is planned open` 只代表年度排定狀態，不涵蓋 capture 後公布的颱風或其他臨時全面休市；
cache 明確綁定 TWSE 天然災害處理規則頁
`https://www.twse.com.tw/zh/clearing/suspended.html`，臨時事件必須另有官方事件公告
證據，不能從 365 日 projection 推導。若 refresh 仍不可得，Paper 保持
`official_calendar_not_proven:*`，不以 weekdays、行情列或空結果代替。cache 是 read-only
operational source observation，不建立 Formal clock、PIT 歷史信用或 broker 權限。

若 TWSE 發布臨時全面休市公告，可用
`scripts\capture_twse_temporary_closure_cache.py --closure-date YYYY-MM-DD
--source-url <TWSE公告URL> --output <repo output> --confirm-network` 建立
`official-twse-temporary-closure-cache.v1`。capture 會要求官方 HTTPS 公告 response
同時包含指定日期及明確休市文字，並重驗 response／outer hash、URL、status 與 capture
時間；天然災害規則頁本身沒有事件日期，不能直接通過。isolated resolver 只接受驗證過的
`twse_temporary_closure_*.json`，事件可覆蓋同日 annual plan；缺少或失效事件證據不會被
自動補成休市，也不會由 weekday 或行情列推導。

isolated Paper adapter 每輪也會自動呼叫 TWSE 官方
`https://www.twse.com.tw/rwd/zh/news/newsList?tag=%E4%BC%91%E5%B8%82&response=json`
清單，再對最多 8 筆標題明示「單日全面休市」的公告呼叫
`/rwd/zh/news/newsDetail?id=<zhId>`。清單與明細都必須是 HTTP 200、final URL
仍在指定 TWSE endpoint、response bytes／公告 ID／日期／時間可重驗；只有通過
驗證才 create-only 寫入 `calendar_cache/twse_temporary_closure_*.json`。清單
不可得、欄位改變、公告不是單日全面休市或明細驗證失敗時，receipt 會保留
`temporary_closure_discovery_blocked`／`temporary_closure_events_partial` 與具體
原因，下一輪自動重試；不會要求每日人工執行 CLI，也不會用年度表、weekday 或
行情有無推導臨時休市。sidecar 的 discovery raw list、detail raw bytes、source
hash 與實際 response completion time 會由 `OfficialTradingCalendar` consumer
再次 readback，仍只影響研究用日曆判定，不建立 Formal credit 或 broker 權限。

Paper EOD scheduled task 不使用通用 wrapper 的可覆寫環境變數。隔離 adapter 固定
既有 `D:\Min\Python\Project\FA_Data` 下的 recommendation queue 與
`sqlite\twstock.db` 為 SQLite `mode=ro/query_only` 來源；repository
`output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite` 是盤前
adapter 建立、EOD 唯讀消費的唯一 Paper state。每輪 candidate 寫入
`<repo>\output\paper_execution_eod_replay\candidates\run_<uuid>`，receipt 寫入
同一 operation root 的 `receipts`，append-only research Paper ledger 固定為
`<repo>\output\paper_execution_eod_replay\paper_trade_ledger.sqlite`。啟動時會建立／
驗證 `scope_manifest_v2.json`，若來源、target 或 manifest 不符合 scope，會保存 blocked
candidate／receipt 並回傳非零；缺少 ledger 不會被當成 Formal 或已完成 evidence，只有
具體 machine-verified Paper fill 才會建立 append transition。

PIT 的日常來源分成兩個排程：`run_pit_sector_membership_preopen_capture.cmd`
固定在 Pacific 16:00 執行，PDT/PST 分別對應台北 07:00/08:00，並在每個官方
response completion timestamp 越過台北 08:30 時停止。盤前 task retry 會先重驗同一
台北自然日既有的 archive；只有當日完全沒有 archive 才進入一次 live capture，存在
但竄改或不完整則 fail closed，避免重試製造多個不同 capture timestamp；
`run_formal_pit_sidecar_postcutoff.cmd`
固定在 Pacific 18:00 執行，PDT/PST 分別對應台北 09:00/10:00，只讀前一 task
已保存的 archive。aggregate register 會呼叫這兩個 task 的專用註冊流程；也可用
`register_pit_sector_handoff_tasks.cmd dryrun` 檢查後再以 `register` 單獨建立，
不會改動其他 task。`run_formal_input_producer_daily.cmd` 若設定
`FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT`（wrapper 預設為 publication root 下的
`pit_candidate_archive`），盤後也只重驗該 archive，不會重新抓取同一自然日的 PIT
HTTP source；缺 archive 會保存具體 blocker。

## Formal input producer durable handoff

`baldr-formal-input-producer-daily` 的入口是
`scripts/scheduled/run_formal_input_producer_daily.cmd`。只針對這一項 task 的註冊計畫由
`scripts/scheduled/register_formal_input_producer_task.cmd` 提供；它要求 Windows
timezone ID 為 `Pacific Standard Time`，並使用本機 21:25。這個時刻在 Pacific
Daylight Time 對應台北 12:25，在 Pacific Standard Time 對應台北 13:25，全年都
落在 Rule 09:00–13:30 capture window。若主機不是 Pacific Standard Time，註冊腳本
fail closed，不把固定 local time 冒充台北時區排程。入口不接受 `--now` 或人工確認；每輪以實際 clock 建立新的 TEMP
candidate／Rule development 子目錄，再把 Rule history 與 causal Paper ledger 的
immutable manifest、source custody、publication context、receipt 寫入
`<repo>\output\formal_daily_publications`。設定
`FORMAL_DAILY_PUBLICATION_ROOT` 可指定另一個合法 repo `output` 或隔離 TEMP root；
該值是持久 parent，每輪會自動建立唯一空 run，不能直接當成固定 candidate 目錄。

使用者環境只需設定一次 Rule 來源：
`FORMAL_DAILY_CLOCK_MANIFEST`、`FORMAL_DAILY_UNIVERSE_SYMBOLS`、
`FORMAL_DAILY_OWNER_ACCEPTANCE`。market DB 預設為
`DATA_ROOT\sqlite\twstock.db`；Paper snapshot／fill 預設讀取
`<repo>\output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite`
（盤前 runner append、Formal 唯讀）與
`<repo>\output\paper_execution_eod_replay\paper_trade_ledger.sqlite`（由 isolated
Paper EOD task append、Formal 唯讀）；production cmd 固定傳遞這兩個 repository path，
不把 Formal reader 指回 D。正式
controlled path 若已存在，可用 `FORMAL_DAILY_FORMAL_LEDGER_PATH`、
`FORMAL_DAILY_FORMAL_RULE_HISTORY_PATH`、`FORMAL_DAILY_FORMAL_SECTOR_PATH` 指定，
否則沿用既有 `BALDR_ML_FORMAL_*` 環境設定；所有 path 都由 consumer 唯讀重驗。

Rule clock／universe／owner 缺件只會使 Rule lane 產生具體 blocker，不會封鎖 PIT
現況 capture；PIT 仍由官方 response completion time gate。缺 Paper fill、官方日曆、
HMAC 或 consumer custody 時，狀態會保存相應 blocker。wrapper 的
`latest_status.json` 位於 publication root 的 `scheduler` 子目錄，會以原子替換
更新；其中 `status=candidate_only` 或 `blocked` 都以 exit code 2 回報，只有三個
明確 formal paths 皆由正式 consumer readback 才回傳 0。這不會把等待中的輸入、歷史
時間或 TEMP candidate 轉成 Formal credit。

每次 scheduled wrapper 也會在同一個 durable scheduler root 追加
`attempts.jsonl`。每筆記錄保存實際 `python_executable`、entrypoint、wrapper command、
working directory、arguments、producer status、blockers 與 exit code；不保存完整環境或
secret。`latest_status.json` 同步保存 `exit_code` 與 `attempt_log_path`。因此
`Last Result=2` 可由 status／attempt log 直接追到「candidate-only／blocked 的具體來源」；
不能把它改成零來掩蓋缺少 Rule、causal ledger、PIT formal sidecar 或自然時間窗口。

PIT capture 在同一輪 machine consumer readback 通過後，會把 publication、receipt、
operational envelope 及兩份官方 raw bytes 以 create-only 方式保存到
`<publication_root>\pit_candidate_archive\<Taipei capture date>\<short key>\`。
`archive_manifest.json` 保存完整 source／archive file hashes、capture time、producer
code hash 與 candidate-only 邊界；readback 直接以 archive 內的 raw bytes 重驗 rows，
不依賴已結束的 TEMP 目錄。這是持久的 machine candidate custody，不是 Formal sector
source，也不會把 `formal_consumer_compatible`、promotion 或 broker 權限改為 true。

盤前 capture task 會在相同 publication root 下查找當日
`pit_denominator\<Taipei capture date>-run-*\denominator.json`。找到仍可由完整
child bytes 重驗的封套時只讀重用；找不到時，才自動抓取兩市場 OpenAPI、兩份 data.gov
CSV／metadata、兩份官方 Swagger 與 data.gov 授權文件，並將回應完成時間、final URL、
HTTP status、內容 hash、coverage start 與 machine license scope 寫入新的 immutable
run。這個 resolver 僅接受 coverage start 等於當日台北自然日的封套；過期、竄改、錯年或
來源不可得都會留下 `missing_verified_current_denominator` 或
`pit_denominator_refresh_failed:*`，不以舊日清冊補當日，也不要求人工每日設定 path。

若要讓同一輪另外建立 PIT history handoff，設定可選的
`FORMAL_DAILY_PIT_EXPECTED_UNIVERSE`（或
`BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH`）指向 archive 以外、由獨立來源驗證的
排序唯一 symbol JSON；`FORMAL_DAILY_PIT_HISTORY_COVERAGE_START` 指定明確的
`YYYY-MM-DD` coverage 起點。兩者任一缺少時仍可保存 current archive，但 handoff
會保留 `pit_formal_independent_expected_universe_missing` 或
`pit_formal_history_coverage_start_missing` blocker。handoff 以台北每日 08:30
cutoff 逐日檢查 capture／archive availability、官方日曆與 source/license lineage，
並以 create-only bytes 保存到
`<publication_root>\pit_history_candidate\<Taipei decision date>\handoff-<hash>.json`。
它固定 `candidate_only=true`、`formal_ready=false`、
`formal_consumer_compatible=false`；current source union、任何 owner 名稱或
外層重簽 hash 都不能取代獨立 denominator、正式 sidecar publication 與 license
scope evidence。

要安裝這一項 task，先以
`scripts\scheduled\register_formal_input_producer_task.cmd dryrun` 驗證 timezone、
21:25 trigger 與 wrapper path，再以同一腳本的 `register` 模式建立或更新
`baldr-formal-input-producer-daily`；該腳本只呼叫這一項 task 的 `schtasks.exe /Create`，
並套用最長 1 小時與重複 instance=`IgnoreNew`，不會順手重註冊其他 task。Query 顯示目前
環境為 `Interactive only`、電池供電不啟動／切換電池會停止；這不是無人值守服務，必須由
已登入的 Windows 使用者承接首次執行與 terminal status。若來源尚未就緒，task 仍會留下
機器可讀 blocker 並等待下一輪，不會寫入來源資料庫或啟動交易／訓練。整體 task 清單的 aggregate register 仍可供既有維運使用，
但不屬於本項單獨安裝計畫。

`baldr-data-update-quick-daily` 預設以 serial technical-indicator path 執行。
只有在受控 canary 的 task environment 明確設定
`BALDR_ENABLE_TECHNICAL_PROCESS_POOL=1` 時，CMD wrapper 才會傳入
`--enable-technical-process-pool`；worker 上限、in-flight 與 retry 預設仍為
`2 / 4 / 1`，每次 running／terminal status 會留存實際旗標。未設定時不會啟動
technical process pool，也不會因 staging acceptance 自動改變排程行為。

## Direct chain automatic bootstrap

`baldr-ml-direct-chain-maintainer` 的入口是
`scripts/scheduled/run_ml_direct_chain_maintenance.cmd`。wrapper 會從
`OUTPUT_ROOT/release_v4/ml_pit_year_shards/latest_manifest.json` 解析最新
pointer，重驗 publication／dataset canonical hash、`all_universe=true`、raw
dataset safety、`decision_at` 與 official market-event custody，再把已驗證的
immutable manifest 傳給既有 Direct → OOC maintainer。它不建立 raw data、不改寫
來源 SQLite、不建立歷史 sector membership，也不把 `companies.csv` 當成 PIT sidecar。

wrapper 在取得 immutable input 後、啟動 maintainer 前會做唯讀三段 filesystem
capacity preflight。Direct chain scheduled 預設檢查 35 GiB 持久新增、40 GiB 暫存峰值與
200 GiB 安全保留；raw PIT wrapper 也至少保留 200 GiB。任一項不足時只寫
`status=blocked_insufficient_storage` 與 `storage_preflight.capacity_budget`（含
total／used／free bytes 與 blockers），不建立 Direct/OOC worker、不進入 retry loop，也不
刪除既有 run。可用 `--persistent-storage-budget-bytes`、`--temporary-storage-budget-bytes`
與 `--safety-reserve-bytes` 在受控環境調整；舊的 `--minimum-free-space-bytes` 仍作相容安全
保留門檻，但低於 200 GiB 的值會 fail closed。全鏈啟動前可搭配
35 GiB 持久新增與 40 GiB 暫存峰值；required headroom 因此至少為 275 GiB。先用
`--preflight-only` 驗證，再由 owner 依 raw shard 估算與 rollback 空間確認容量。這個容量政策
不是 Formal／promotion gate。

狀態寫入：

```text
<OUTPUT_ROOT>/scheduled/ml_direct_chain_maintenance/latest_status.json
```

wrapper 在長時間監督期間會定期重驗 training output instance lock，並更新
`heartbeat_at`、`maintenance_lock_state` 與 `maintenance_owner_process_id`；因此
`running` 狀態中的 owner 是 child maintainer 取得 lock 後的實際命令列 custody，
不是只在 bootstrap 時讀到的暫時值。wrapper 結束後也會重新讀取一次 lock 狀態。

`status=running` 代表已通過 bootstrap 並正在監督既有 chain；`completed` 代表
wrapper 子程序正常返回（包括 instance lock 已由現有 owner 持有的安全重複觸發）。
若是後者，status 會明列 `execution_disposition=existing_owner_lock`、
`maintenance_lock_state=verified` 與經命令列驗證的 `maintenance_owner_process_id`；命令列
還必須與同一個 `training_output_dir` 完整相符，避免把其他 lineage 的 maintainer 誤認為現有
owner，或把安全跳過誤讀成 Direct/OOC 已完成。若 live owner 命令列暫時無法讀取，wrapper
會改列 `execution_disposition=owner_lock_unverifiable` 與
`maintenance_lock_state=owner_lock_unverifiable`，保留 lock 並等待下次驗證；
`blocked_invalid_bootstrap_input` 代表輸入驗證失敗，舊 publication／run 會保留，
不會用猜測資料啟動訓練。status 永遠明列 `database_mode=ro`、`query_only=true`、
`writes_source_database=false`、`formal_oos_allowed=false`、`production_alpha_bp=0`
與 `broker_order_allowed=false`。完成排程註冊後不需要人工重新執行 Direct、OOC 或
promotion；每日觸發會自動重試，既有 lock 與 hash-bound checkpoint 負責冪等續接。

## OOC refresh continuation

Direct v4 完成後，若新的 PIT sector sidecar 被放入 direct output lineage，
`continue_ml_direct_ooc_after_store.py` 會先以正式 assembler 驗證 canonical manifest、
accepted/license/source hash、可得時間與 training cutoff；全部通過才建立新的 immutable
Direct run，否則沿用現有 publication 並維持 formal gate 關閉。可用
`BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 指向受控來源；未設定時只掃描明確的
`pit_sector_membership`／`sector_membership`／`sidecars` 目錄與固定檔名，不會把
`companies.csv` 或研究輸出當成 PIT 歷史資料。若要讓這個等待跨越 worker／supervisor
中斷，維護程序可加 `--watch-formal-inputs`；它只在偵測到一個合規且唯一的 sidecar
時自動續跑，沒有來源時不會重複訓練。

維護器的 `--watch-formal-inputs` 不只等待 sector sidecar：它會以 pointer、canonical hash、
raw dataset safety、dataset decision_at 與現行 Direct identity 驗證新版或同一 cutoff 的新版
all-field raw PIT publication；也會驗證最新 official market-event publication。合格輸入會在同一
次 immutable Direct → OOC chain 綁定，並保留既有已驗證的 sector sidecar；只重發 wrapper、但
canonical events hash 未變時不會觸發不必要的重訓。這些探測不會自動建立或採用未受控的 causal
non-cash ledger／Rule Champion artifact，formal gate、alpha=0、broker disabled 仍維持。

正式 ledger／Rule Champion 可由受控 Windows 使用者環境變數
`BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH`／`BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH`
交給同一 watcher。維護器先執行唯讀 ledger chain、cutoff 與 Rule history HMAC 驗證；只有
sector、ledger、history 三項都可合法 hash-bind 時，formal-only refresh 才會啟動。分批出現
或驗證失敗的來源只會等待，不會觸發部分重訓、改寫舊 run 或提升 alpha。

長駐 watcher 每輪也會重新讀取 Windows 使用者／系統環境登錄值，讓 watcher 啟動後才完成的 owner deposit 能交接到同一個 process；只會將受控
path、HMAC key 與 store id 放入目前 process memory，絕不寫入檔案、命令列、status 或 log。若 watcher 自己採用的登錄值被移除，會清掉
該 process 內的值並回到 fail-closed 驗證；log 最多記錄被刷新的是變數名稱，不記錄任何 value。這不會繞過 ledger chain、Rule HMAC、PIT
sector 或 formal promotion gate。

獨立執行 `scripts/inspect_ml_formal_input_readiness.py` 時也會使用同一套 controlled Windows registry handoff：它只把 owner deposit 接到當前 read-only process memory，不寫回 registry、artifact 或 source DB。

Direct numeric store runs also publish `runs/<run_id>/heartbeat.json` with the
current stage, PID, completed years, and UTC `updated_at`.  While the OOC
continuation helper is waiting, it mirrors the latest valid heartbeat into
`continuation_status.json` when available and when its PID matches the
direct process being supervised.  This is progress observability only;
`checkpoint.json`, the finalized year manifests, and the hash-bound
`latest_manifest.json` remain the completion authority.  A stale or missing
heartbeat must never be interpreted as a completed store.

New direct builds also publish real annual boundaries: each source shard first
reports `raw_spool_source_shard_<year>_rows_<n>_processed` while validating (at
least every 100,000 rows or after 30 seconds without a progress event) and
then `raw_spool_source_shard_<year>_complete`, followed by
`year_raw_spool_complete` and `year_labels_complete`. During the potentially
long annual assembly, the builder reports
`assembly_decision_<date>_rows_<n>_processed` from the sample-row loop at the
same bounded row/time cadence, so a single large decision date cannot silence
the heartbeat. The label-spool stage also reports
`label_spool_starting_<symbols>_symbols_<dates>_dates`, bounded
`label_spool_symbol_<n>_of_<total>_decision_<n>_of_<total>_processed` events
while a single symbol is expensive, and `label_spool_symbols_<n>_of_<total>_processed`
at symbol boundaries, followed by `label_spool_complete`. The annual stages then
continue with `year_assembly_complete`, `year_artifacts_complete`, and
`year_directory_finalized`. These are
observability stages only; continuation still requires the checkpoint,
finalized year manifest, and hash-bound latest pointer before it can start OOC
training.

The initial raw discovery pass uses the same bounded heartbeat contract. It
reports `discovery_source_shard_<year>_rows_<n>_processed` and
`discovery_source_shard_<year>_complete` while verifying compressed hashes,
row hashes, feature definitions, and source content custody, so a long resume
scan remains observable without treating progress as completion.

After a successful discovery, the direct run stores a hash-bound
`discovery_cache.json`. A later checkpoint resume rechecks the raw manifest
identity and every compressed shard hash before reusing the cached feature
registry, calendar, folds, and source digest; any mismatch falls back to the
full fail-closed discovery scan.

Promotion evidence custody compares the official market-event canonical file
hash to the direct store. A republished wrapper with the same
`canonical_events_hash` is accepted as a no-op publication change, so an
unchanged immutable direct store is not rebuilt solely for corrected duplicate
metadata. Any canonical timeline hash change still produces
`formal_ooc_corporate_action_custody_stale` and remains fail-closed.

On Windows a venv launcher may have a separate Python worker PID.  The OOC
continuation accepts a direct heartbeat only when its PID is the supervised
launcher or a live descendant of that launcher; an unrelated or stale PID is
ignored.  This preserves process custody while still exposing the real annual
stage.

The annual raw spool now commits at each source-shard boundary to keep the
ephemeral SQLite transaction bounded; no annual artifact is published until
the complete work directory, hashes, and checkpoint pass validation.

The OOC trainer also keeps final-meta training bounded: it streams matured OOF
rows fold-by-fold and batch-by-batch, uses only a deterministic bounded sample
for medians, and makes separate bounded passes for normalization, Gram fitting,
and logistic IRLS. It does not materialize one full-width `train.meta.f32`, so
the 4GB memory guard remains meaningful on Windows.

OOC classifier calibration now has an expanding outer-fold cross-fitted
diagnostic: each target fold uses only earlier OOF blocks whose labels are
mature before the next fold starts. The report is integer-bp and explicitly
`oof_diagnostic_only=true` / `production_eligible=false`; it does not rewrite
the raw base vector consumed by the meta allocator. A later training manifest
may therefore replace `classifier_calibration_not_cross_fitted` with
`classifier_calibration_not_attached_to_ooc_model`; that remains a fail-closed
shadow boundary until a calibration artifact is attached to OOC inference.

若要先做成本後增益的低複雜度 shadow，可直接執行
`scripts\train_ml_allocation_out_of_core.py --profile minimal_linear_shadow --algorithm ridge_logistic --horizon <H>`；
這個 profile 強制單一 Ridge／Logistic 與單一明確 horizon，缺少恰好一個 horizon 或指定
HGB 會停止。`full_shadow` 才是既有多 horizon／Ridge+HGB 研究流程；兩者均不授予
Formal OOS、非零 alpha 或 broker 權限。

`scripts\continue_ml_direct_ooc_after_store.py` 啟動時會先將 `continuation_status.json` 寫成 `waiting_for_direct_store`，避免沿用上一輪的 terminal `blocked` 診斷；direct store 完成後才會驗證 custody 並啟動 OOC。所有新版 waiting、custody、training heartbeat、complete 與 blocked status 都明列 `formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。若舊版 helper 完成時缺少這三個欄位，已結束 OOC helper 的 release coordinator 會自動補寫 fail-closed 欄位；明確的 true／非零值則直接阻擋，不以缺欄位或不安全值放行。Direct numeric v4 會把官方 halt/resume timeline 以 decision-time `effective_at`／`available_at` 寫入 replay source；舊 direct run 不會被原地改寫，續接流程會以新的 immutable custody 重新發布。接著 `scripts\continue_ml_release_after_ooc.py` 必須先觀察到 PID 與命令列均相符的 OOC helper，再等待其結束；之後才確認 training `latest_manifest.json`、continuation status 與兩者 manifest hash 完整一致，並依序執行 promotion evidence、promotion authority 與 daily ML copilot。任何缺件、hash 不一致或非零 exit code 都只寫 `blocked`，它不取代 Windows Task Scheduler，也不修改正式 market SQLite。

若 direct process 已正常完成但 supervisor 因 Windows custody／launcher race 中斷，可使用 `--resume-after-direct-store` 重新驗證 immutable direct manifest 後續接 OOC；此模式不宣稱 direct PID 仍存活，且同樣要求完整 checkpoint、年度 manifest、fold index 與 hash custody。

release follow-up 的三個命令現在以受監督子程序執行；每個命令會在 `post_ooc_followup_status.json` 發布 `followup_command_running`／`followup_command_complete`、子程序 PID、命令序號、開始時間與 return code。這只增加長命令的可觀測性，不改變 fail-closed promotion gate 或任何正式資料寫入邊界。

ML promotion evidence 與 promotion authority 的 status／pointer atomic publication 也使用 120 次、每次 0.5 秒的 Windows transient-lock bounded retry；重試耗盡仍會 fail-closed，不會以半成品覆寫既有狀態。

OOC handoff 在啟動訓練前會先發布 `store_custody_validation_starting`，再重新計算 direct top-level manifest canonical hash，並驗證 complete checkpoint、每個年度的 8 個 artifact hash／byte custody，以及所有 fold index artifact；任一年度、fold 或 checkpoint 不一致即停止在 `blocked`，不會開始訓練。

若現行 legacy direct run 已經在執行，`scripts\continue_ml_direct_v3_refresh_chain.py` 可由受控背景程序接手：它先以 PID／完整命令列等待既有 direct、OOC、release 三層全部結束，再啟動新的 immutable v4 direct build，並在 direct process 尚未退出前綁定新的 OOC helper 與 release helper，避免 process-custody race。狀態保存於 `v3_refresh_chain_status.json`，建置與下游輸出保存於 direct/training `logs\*v3_refresh.log`；任何失敗仍 fail-closed，不會刪除舊 run、改寫正式 SQLite 或開啟 alpha。

若 supervisor 本身在 legacy chain 停止後被中斷，重啟時使用 `--resume-after-legacy-chain`；此模式會先掃描完整命令列，若仍有任何相符的 direct／OOC／release process 就拒絕啟動，確認無 active target 後才從既有 checkpoint 接續。正常模式會在等待前一次性驗證三個 legacy PID，避免後續 helper 已先退出而造成錯誤的 custody failure。

若需要讓這條長時間 refresh chain 在 worker 或 supervisor 因 Windows sleep／process
中斷後自行恢復，可由受控背景程序執行
`scripts\maintain_ml_direct_v3_refresh_chain.py`。它會先以完整命令列掃描
Direct／OOC／release target；只要任一 target 存活就只等待，不會平行啟動。全部
target 停止且 primary status 尚未 `complete` 時，才會呼叫既有
`--resume-after-legacy-chain`，由相同 run identity 的 checkpoint、年度 manifest
與 raw hash 決定可否續跑。它另以 training output 目錄的 instance lock 防止兩個
維護器競爭；任何 retry 都維持 `formal_oos_allowed=false`、alpha 0、broker false，
不刪除舊 run、不改寫正式 SQLite 或手動發布 pointer。

補充：`continue_ml_direct_v3_refresh_chain.py` 若以自訂 `--status-path` 啟動，會自動把 direct／OOC／release 的 operational log 寫到 heartbeat 同層的 `logs` 目錄；因此即使正式資料目錄的 log 權限受限，也能繼續執行而不改寫正式資料。未指定自訂 status path 時仍使用既有 direct/training `logs` 位置。

## Register

Preview:

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun
```

Create or replace the daily tasks:

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd register
```

Create or replace all 16 daily tasks and the weekly collection task in one explicit operation:

    scripts\scheduled\register_baldr_scheduled_tasks.cmd register-all

Both registration modes run a wrapper-file preflight first. If a selected wrapper
is missing, the command exits before calling schtasks and leaves existing tasks
untouched. Use dryrun to inspect all 17 actions without registration.

The register script creates:

```text
baldr-data-update-quick-daily
  DAILY 04:20
  cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_update_quick.cmd"

baldr-official-market-events-daily
  DAILY 04:50
  cmd.exe /c "<repo>\scripts\scheduled\run_official_market_event_backfill.cmd"

baldr-data-freshness-check-daily
  DAILY 05:00
  cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_freshness_check.cmd"

baldr-ml-raw-pit-refresh-daily
  DAILY 05:05
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_raw_pit_refresh.cmd"

baldr-recommendation-snapshot-daily
  DAILY 05:10
  cmd.exe /c "<repo>\scripts\scheduled\run_recommendation_snapshot.cmd"

baldr-evidence-pipeline-dry-run-daily
  DAILY 05:15
  cmd.exe /c "<repo>\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"

baldr-ml-promotion-evidence-daily
  DAILY 05:17
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_promotion_evidence.cmd"

baldr-ml-promotion-authority-daily
  DAILY 05:18
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_promotion_authority.cmd"

baldr-ml-allocation-copilot-daily
  DAILY 05:20
  cmd.exe /c "<repo>\scripts\scheduled\run_ml_allocation_copilot.cmd"

baldr-decision-evidence-capture-daily
  DAILY 05:25
  cmd.exe /c "<repo>\scripts\scheduled\run_decision_evidence_capture.cmd"

baldr-paper-portfolio-daily
  DAILY 16:15 Pacific (07:15 PDT / 08:15 PST Taipei; adapter guard)
  cmd.exe /c "<repo>\scripts\scheduled\run_paper_portfolio_daily.cmd"
```

舊 `baldr-evidence-working-copy-smoke-manual` 不再屬於排程清單；獨立 smoke script 只保留作工程診斷。unregister wrapper 仍會清除可能殘留的舊 task。

只建立或取代週日 sidecar collection task：

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd weekly-register
```

`weekly-register` 只建立 `baldr-v2-2-weekly-collection`，其排程為 `WEEKLY SUN 18:00` 並執行 `run_v2_2_weekly_collection.cmd`。它不建立、取代、啟用或以其他方式變更任何每日 task。

The weekly-register mode still only changes the weekly collection task. The
register-all mode performs the daily and weekly registrations together, but
both modes require the selected wrapper files to pass preflight first.

## Query

```cmd
scripts\scheduled\query_baldr_scheduled_tasks.cmd
schtasks /Query /TN baldr-official-market-events-daily /V /FO LIST
schtasks /Query /TN baldr-data-freshness-check-daily /V /FO LIST
schtasks /Query /TN baldr-ml-raw-pit-refresh-daily /V /FO LIST
schtasks /Query /TN baldr-recommendation-snapshot-daily /V /FO LIST
schtasks /Query /TN baldr-evidence-pipeline-dry-run-daily /V /FO LIST
schtasks /Query /TN baldr-ml-promotion-evidence-daily /V /FO LIST
schtasks /Query /TN baldr-ml-promotion-authority-daily /V /FO LIST
schtasks /Query /TN baldr-ml-allocation-copilot-daily /V /FO LIST
schtasks /Query /TN baldr-decision-evidence-capture-daily /V /FO LIST
schtasks /Query /TN baldr-paper-portfolio-daily /V /FO LIST
schtasks /Query /TN baldr-v2-2-weekly-collection /V /FO LIST
```

Missing tasks are reported as friendly `Task not found` messages by the query wrapper.

For a machine-readable, side-effect-free check, run
`scripts\inspect_scheduled_task_registration.py`. In addition to querying each
expected task, it verifies that all 15 repository wrapper files exist and, when
`schtasks /Query` exposes `Task To Run`, that the registered action contains the
expected wrapper path. The report keeps these checks separate from
`all_available`; an available task without a visible action is marked
`action_unobserved`, and `configuration_ready` is true only when task
availability, local wrappers, observed actions, and action matching all pass.
No task is created or changed.

## Unregister

Preview:

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd dryrun
```

Remove the scheduled tasks:

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd unregister
```

也可以在 Windows Task Scheduler 手動停用或刪除每日 task。若只要停止週日 sidecar collection，請在其中停用 `baldr-v2-2-weekly-collection`，或執行：

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd weekly-unregister
```

Rollback 時禁止自動 drop sidecar SQLite table；保留 `pending_human_review` 與 `collection_failed` record 供稽核與人工處理。

## Logs And Reports

官方市場事件：

```text
<OUTPUT_ROOT>/scheduled/official_market_events/latest_status.json
<OUTPUT_ROOT>/release_v4/official_market_events/latest_manifest.json
<OUTPUT_ROOT>/release_v4/official_market_events/runs/<publication_id>/
<OUTPUT_ROOT>/release_v4/official_market_events/quarantine/<failure_id>/
```

TPEx 官方端點暫時不可用時，wrapper 會保留最後一個完整 formal publication，將本次失敗的 raw custody 移入 quarantine，並在 `latest_status.json` 記錄 `failure_class`、`formal_publication_preserved` 與可重試狀態；不會寫入 active SQLite，也不需要人工確認。若 latest pointer 仍可驗證但只涵蓋近兩年，下一次成功執行會自動 recovery 到 2014 起點；只有通過完整年度覆蓋與 hash 驗證的 publication 才能繼續供 PIT／ML evidence 使用。

Data freshness:

The quick update publishes `status=running` with a run/process identity before its long-running steps begin, then records `started_at` and `completed_at` on the terminal status. Downstream freshness and ML evidence checks treat a running or stale update as not-ready, so a partially completed update cannot be consumed.

若正式 `OUTPUT_ROOT` 的 ACL 只允許讀取，`run_daily_data_freshness_check.cmd` 可由 owner
明確設定 `BALDR_FRESHNESS_STATUS_PATH`；若未另外設定
`BALDR_FRESHNESS_LOG_PATH`，wrapper 會把 log 放在 status path 同一位置（加上 `.log`）。
兩個變數都未設定時維持既有 `<OUTPUT_ROOT>/scheduled/data_freshness/` 出口。這只改變
read-only status／log 的寫入位置，不會繞過正式 DB、scheduler、Evidence 或 Formal gate；
UI 若要讀取外部 status，另需設定 `DATA_FRESHNESS_STATUS_ARTIFACT` 指向同一個明確檔案。
若 status／log 路徑仍因 ACL 或其他 `OSError` 無法寫入，canonical
`data_freshness_probe.py` 不再留下未處理 traceback；它會在 stdout 輸出
`status=failed` 與 `status_artifact_write_failed:<ErrorType>`／
`log_artifact_write_failed:<ErrorType>`，並以 exit code `1` 結束。如此 scheduler／wrapper
可以把「資料檢查失敗」與「結果檔無法發布」分開診斷；能寫入的 artifact 也會被重寫成同一份
結構化錯誤，不會沿用舊的 `passed` 假狀態。
`run_daily_data_freshness_check.ps1` 也只委派這個 canonical probe，並接受相同的
`BALDR_FRESHNESS_STATUS_PATH`／`BALDR_FRESHNESS_LOG_PATH` 或參數覆寫，避免維運入口維護第二套
日期／freshness 判定。

The same runner appends bounded `data-update-status-history.v1` records to `history.jsonl` (or the explicit `--history-path`) for the running and terminal attempts. The history is append-only and idempotent by record hash; it does not backfill an existing `latest_status.json` and does not change any downstream readiness or write permission.

```text
<OUTPUT_ROOT>/scheduled/data_update_quick/latest_status.json
<OUTPUT_ROOT>/scheduled/data_update_quick/history.jsonl
<OUTPUT_ROOT>/scheduled/data_update_quick/YYYYMMDD_data_update_quick.log
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log
```

Automatic raw PIT refresh:

```text
<OUTPUT_ROOT>/scheduled/ml_raw_pit_refresh/latest_status.json
<OUTPUT_ROOT>/scheduled/ml_raw_pit_refresh/refresh.log
<OUTPUT_ROOT>/release_v4/ml_pit_year_shards/latest_manifest.json
<OUTPUT_ROOT>/release_v4/ml_pit_year_shards/runs/<publication_id>/
```

`latest_status.json` records the upstream data-update status, core dates, decision cutoff,
source database read-only contract, builder return code, and published manifest hashes.
若 builder 因 daily-price source quality guard 退出，terminal receipt 另保存 bounded
`source_quality_summary`：candidate／classification 計數、受影響日期 top list、最多 12
筆樣本與完整 report hash；不保存數百萬筆 candidate payload，也不以摘要放寬
quarantine。這讓 ML/data-quality owner 可先依日期／市場 probe 定位缺檔或數值映射
問題，修復與重跑仍須另行審核。
`blocked_upstream_not_ready` means the runner waits for a later data-update proof;
`skipped_current` means the current pointer already covers the cutoff; `completed` means
the immutable raw publication passed pointer, canonical hash, all-universe scope, dataset
safety, and decision-time validation. `blocked_insufficient_storage` means the runner
observed less than the configured free-space threshold before launching the builder; the
status includes `storage_preflight` and the runner never creates a partial publication.
The runner never deletes an earlier publication.

`data_update_quick/latest_status.json` uses `passed_with_warnings` when TPEX failed dates remain, for example `TPEX 每日股價缺少日期：20260706`. `data_freshness/latest_status.json` uses `degraded` when SQLite is current but either `daily_price/YYYYMMDD.csv` or `daily_price_tpex/YYYYMMDD.csv` is missing for that latest daily date.

Recommendation snapshot:

```text
<OUTPUT_ROOT>/scheduled/recommendation_snapshot/latest_status.json
<OUTPUT_ROOT>/scheduled/recommendation_snapshot/YYYYMMDD_recommendation_snapshot.log
<OUTPUT_ROOT>/recommendation/runs/scheduled_rec_YYYYMMDD_HHMMSS.json
<OUTPUT_ROOT>/recommendation/runs/recommendation_runs.db
```

The recommendation snapshot status includes `result_id`, `recommendations_count`, `screening_matrix_rows`, `why_not_payload_rows`, `liquidity_gate_payload_rows`, `writes_recommendation_result`, `writes_evidence_db`, `auto_trading`, and `lifecycle_action`.

Evidence dry-run:

```text
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/latest_status.json
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/YYYYMMDD_evidence_pipeline_dry_run.log
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/reports/YYYYMMDD_evidence_pipeline_dry_run.md
```

ML allocation Production Co-pilot：

```text
<OUTPUT_ROOT>/scheduled/ml_promotion_evidence/latest_status.json
<OUTPUT_ROOT>/release_v4/ml_allocation_promotion_evidence/latest_pointer.json
<OUTPUT_ROOT>/release_v4/ml_promotion_authority/latest_status.json
<OUTPUT_ROOT>/release_v4/ml_promotion_authority/latest_authorization_pointer.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/latest_status.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/raw_pit_publications/runs/<publication_id>/
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/orchestration/YYYYMMDD/<run_hash>/*_post_freeze_shadow_input.json.gz
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/orchestration/YYYYMMDD/<run_hash>/*_allocation_proposal.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/artifacts/YYYYMMDD_<hash>_promotion.json
<OUTPUT_ROOT>/scheduled/ml_allocation_copilot/sidecar/YYYYMMDD_<hash>_shadow.json
```

排程入口是 `scripts/run_daily_ml_allocation_orchestration.py`。它先用官方交易日曆求 strict T-1，再從正式 SQLite 以 `mode=ro/query_only` 發布固定 11 檔、730 日 causal lookback 的 immutable `all_field_enriched` raw snapshot；只在 post-freeze input 與 ML allocation inference 都成功後才呼叫 promotion evaluator。`<run_hash>` 綁定決策時間、raw publication、凍結 training manifest、模型 artifact 與 policy；相同輸入冪等重跑，不同 custody 版本不覆蓋舊輸出。凍結 release 預設為 `DATA_ROOT/output/release_v4/ml_allocation_bounded_v4_operational`，可用 `BALDR_ML_RELEASE_ROOT` 覆寫。新增的 `AllocationReleaseAdapter` 會在 daily consumer 載入前重驗 release manifest、artifact／preprocessor／calibrator hash、feature order、missing policy 與 dataset lineage；同一批 frozen rows 可執行 OOC→release parity，任何 mismatch 直接停止 ML path。校準 mapping 僅接受跨 fold 的單調整數 bp artifact，未附正式校準器時仍回退既有未校準輸出並保留 Rule-only 邊界。

任何 release、官方日曆、strict T-1、raw publication、post-freeze input 或 inference 缺件都會留下 `passed_rule_only`、`alpha=0`、`formal_oos_allowed=false`、`broker_order_allowed=false`，且不呼叫 promotion evaluator，因此不會新增假的 shadow sidecar。`latest_status.json` 明列 `post_freeze_input_status`、`inference_status`、`promotion_status`，以及 raw manifest、input、兩份 audit、proposal、replay 與 promotion 的 domain/file hashes。完成 inference 後產生的 sidecar 只代表一筆 observation；每日編排器固定輸出 `shadow_day_credit_allowed=false`，是否能列入 20 個真實交易日由後續 evidence collector 依完整性另行判定，不在此處自行加總。

Promotion evidence 與 authorization 不接受人工作業環境變數注入。05:17 builder 只能從固定、hash-bound custody pointer 發布 unsigned evidence；05:18 Authority 只能以 DPAPI 保護的本機 user-scope key 簽署同一決策窗；05:20 Co-pilot 只讀固定 `latest_authorization_pointer.json`，且再次要求授權的 model／dataset 與實際 inference release 完全相同。任何錯配都回退 Rule-only。

四條 alpha lane 固定為 `0 / 2000 / 3500 / 5000 bp`。Evidence 不存在、格式無效、門檻未通過或 authorization hash 不相符時，runner 一律 fail closed 為 `alpha=0`。同一決策日與同一輸入會得到相同 hash 與相同檔名；若同日證據版本不同，舊 sidecar 與 artifact 仍會保留。

Decision Desk / Evidence confirmed capture：

```text
<OUTPUT_ROOT>/scheduled/decision_evidence_capture/latest_status.json
```

`latest_status.json` 記錄台北 `decision_at`、`snapshot.saved`／`snapshot.duplicate`、`evidence.events_inserted`／`evidence.duplicates`／`evidence.failures`，以及整體 `passed`／`failed`。排程預設選擇最近一個已到達的台北 08:30 cutoff；明確指定未到達的日期則由 capture CLI 以 `decision_date cannot be future-dated` fail closed。它明確輸出 `trading_calendar_validated=false`、`maturity_date_inferred=false`，不把週末、休市或未成熟資料偽裝成正式交易日證據。snapshot 成功、event capture 失敗時，下次執行會重用 snapshot hash 並再次嘗試 event unique-key capture。

Paper Portfolio 每日估值（repository isolated）：

```text
<repo>/output/paper_execution_eod_replay/paper_portfolio/paper_portfolio.sqlite
<repo>/output/paper_execution_eod_replay/scheduled/paper_portfolio_daily/latest_status.json
```

runner 先以 D 槽 baseline／snapshot 的唯讀來源建立 repository state seed，並在
`state_seed_manifest.json` 綁定來源與初始 target hash；每次 repository append 後以
`state_head_manifest.json` 綁定最新 state hash。排程預設選擇最近一個已到達的台北
08:30 cutoff；明確指定仍未到達的 `--decision-at` 會寫入 `skipped_future_decision`，
且不開啟 state／market DB。市場 DB 永遠唯讀，SQL 與 domain runner 都拒絕
`price_date >= decision_date` 或 `available_date >= decision_date`；同一決策日重跑只
回報 duplicate。來源缺件、seed/head hash 不一致或來源在 backup 期間變動時會 blocked，
不建立無 provenance state。此排程不把 current weight 猜成 0、不產生交易、不套用配置提案。

Working-copy smoke diagnostic script（不構成人工 Gate，也不註冊為 task）：

```cmd
scripts\scheduled\run_evidence_working_copy_smoke.cmd <source-db-path> <working-copy-db-path> [YYYY-MM-DD] [repeat]
```

If the DB paths are missing, the wrapper prints usage and exits. Repeat defaults to 2.

每週 sidecar collection：

```text
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/evidence_scheduler.db
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/logs/v2_2_weekly_collection_YYYYMMDD_HHMMSS.log
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/v2_2_weekly_collection_YYYYMMDD.json
<OUTPUT_ROOT>/scheduled/v2_2_weekly_collection/v2_2_weekly_collection_YYYYMMDD.md
```

sidecar record 刻意與 source DB 分離。Schema v3 只允許 `pending_human_review` 與 `collection_failed`；首次開啟舊 sidecar 時，repository 會在單一 SQLite transaction 內保留所有 `collection_id`、payload、hash、error 與建立時間，並把舊版 `observed_automatic`（尚未取得人工核准）原子映射回 `pending_human_review`。Migration 可重跑且不開啟或修改 source DB。收集成功只代表待人工審核，收集失敗則保存 `collection_failed` 與 diagnostics。

## Evidence Boundary

The daily automation runs only:

- non-UI quick market data updates for the recent weekday window;
- read-only data freshness checks;
- research-only recommendation snapshot generation and recommendation result save;
- evidence pipeline dry-run reports.
- unsigned, fail-closed ML promotion evidence construction.
- independent DPAPI-protected machine authorization.
- fail-closed ML allocation promotion evaluation and append-only sidecar records.
- dedicated confirmed Decision Desk snapshot and Evidence Event append-only capture.
- strict T-1 append-only Paper Portfolio valuation.

### ML allocation automatic catch-up

run_ml_allocation_copilot.cmd 會固定傳入 --auto-catch-up。只有在沒有
明確指定 ML_ALLOCATION_DECISION_AT、排程選到下一個台北曆日，且完整
orchestration 實際證明該候選日的 strict T-1 尚未就緒時，runner 才會
向後重試最多 31 個曆日，選擇最近的已過交易日。判定依據是既有
hash-bound raw publication 與 post-freeze T-1 proof，不新增另一套資料
解讀，也不寫入來源 SQLite、不使用未來資料；資料庫或官方日曆狀態未知時，
不猜測，保留 fail-closed。明確指定日期時不會自動改日期。

latest_status.json 會保存 decision_selection_mode、
requested_decision_at、decision_selection_reason 與每個候選的
decision_selection_attempts，因此自動補跑不需要人工猜測，也不會把
回溯日期偽裝成原本的決策日。

### ML forward 自然日設定產出（已註冊、尚待自然執行）

`run_ml_allocation_forward_daily.cmd` 是第 17 個 daily task 的前瞻 shadow 入口，
目前已由 pinned UTF-16 XML 獨立註冊；它不由 aggregate registration 建立或覆寫。
省略
`ML_FORWARD_CONFIG_PATH` 時，Python wrapper 在真實 Asia/Taipei 08:30
到達後呼叫 `prepare_ml_allocation_forward_config.py`，將當日設定以
`<ML_FORWARD_CONFIG_ROOT>\configs\YYYY-MM-DD.json` create-only 建立，並把
候選選擇收據寫到 `selection_receipts/`、以 atomic pointer 更新
`latest_selection.json`。既有日期設定若 bytes 不同會 fail closed，不能以
較新的候選取代已凍結來源；wrapper 也只讀該日期檔案，不掃描 latest 檔案。

自然執行前可執行 `run_ml_allocation_forward_daily.cmd preflight`；這個模式唯讀
檢查 wrapper、V2 release manifest hash、repo shadow／Paper 路徑、D market DB、
calendar refresh caller 與 offline calendar cache，不等待台北時間、不發網路、不
呼叫 producer、不啟動 child，也不建立 Windows task。直接省略 `preflight` 才會
進入自然日流程；
目前 task 雖已註冊，尚未授權手動啟動或宣稱已有自然日 shadow 累積結果。

設定產出只接受既有 ML PIT archive consumer 完整重驗過的單一 archive。產出器
先保存 manifest bytes hash，再由 consumer 做 source custody、current code、
raw rebuild、available／archived time 與 manifest readback；consumer 最終回傳的
manifest file hash 必須與前讀 hash 完全一致，任何替換都拒絕。freshness window
只允許決策日當日 08:30 前已完成的 archive 或上一個由官方日曆判定的交易日；
週末／休市日寫 `skipped_non_trading_day` 且不建立 config，官方日曆 unknown、
過舊 archive、source hash mismatch 都是 blocked。正式 runtime 預設唯讀使用
`output\paper_execution_eod_replay\calendar_cache\` 的已驗證 TWSE annual
cache 與 temporary-closure cache，`allow_online_probe=false`；缺少、過期或
竄改 cache 時不以 weekday 或行情列猜測交易日。

forward `.cmd` 在等待台北 08:30 前先呼叫
`run_official_calendar_cache_refresh_daily.py`。它以實際 Asia/Taipei 時鐘計算下一個
08:30 cutoff；只有現有 annual cache 的 `expires_at_utc` 不涵蓋該 cutoff 時，才透過
既有 `capture_official_trading_calendar_cache.py --confirm-network` 發出最多一次
bounded capture。capture 的 `captured_at_utc`、`expires_at_utc`、原始 response hash
與新檔 hash 會寫入
`output\v4_ml_forward_scheduler\calendar_cache_refresh\`；檔名使用實際執行時間與
唯一尾碼，舊 cache 永不覆寫或刪除。cache 仍過期、response 不完整、hash／時間驗證
失敗時 wrapper 直接退出，producer 與 child 不會啟動。這個前置步驟不寫 market DB、
Paper ledger 或 formal clock，也不給予 forward credit。

前瞻設定的預設路徑刻意固定在 repository isolated output：market SQLite 仍是
`DATA_ROOT\sqlite\twstock.db`，shadow output 是
`output\v4_ml_daily_derived_shadow_real_v2`，Paper state 是
`output\paper_execution_eod_replay\paper_portfolio\paper_portfolio.sqlite`，
frozen release 是
`output\v4_ml_derived_h5_20260907_real_v2`，其
`release_manifest.json` 必須符合固定 hash
`sha256:c306c1ea53ccef112204a8412a605b575e4d107b4503b2b5be5d6d5ee50910ea`。
每日 config 會保存該 hash，wrapper 在啟動 child 前重新讀回比對；路徑或
manifest bytes 被替換時 fail closed。如需變更，使用
`ML_FORWARD_DATABASE`、`ML_FORWARD_OUTPUT_ROOT`、`ML_FORWARD_PAPER_STATE_DB`、
`BALDR_ML_RELEASE_ROOT`、`BALDR_ML_RELEASE_MANIFEST_FILE_HASH` 與
`ML_FORWARD_ARCHIVE_ROOT` 明確指定，不能以一般
`OUTPUT_ROOT` 的 D 槽 fallback 取代上述 custody。

wrapper 從 Pacific 16:15 喚醒後只等待真實台北 08:30；子程序超過台北
08:35、外層 capacity／read-only status 失敗、或
`daily_orchestration.natural_forward_completion_clock` 沒有在期限內完成，
都保留完整 outer blocked payload，不給 forward credit。archive 與 operational
publication 是互斥來源；既有 05:20 `--auto-catch-up` task 維持盤後補跑，
不會因這個入口而改成 08:30 前瞻 consumer。完整 ML child／frozen release
契約雖已完成首日接線與註冊驗收，task 尚未有自然執行 receipt；在自然日
shadow、maturity、promotion 與 broker gate 全部完成前，仍不得授權
production alpha／broker。

預備中的 forward child 使用
`run_daily_ml_allocation_derived_shadow.py`。由 scheduled caller 傳入的
archive branch 只包含 `--pit-machine-archive-root`、exact
`--pit-machine-archive-manifest` 與其 frozen file hash；child 在 forward mode
依 `decision_at + 5 分鐘` 固定 08:35 deadline，並把完整 daily orchestration
payload 保留在 outer stdout。若未來採用 operational branch，ML owner 必須另行
接通 publication bytes hash 的 child 驗證，不能由 scheduler 僅靠 path 名稱放行。
完整 payload 的 `status`、capacity／read-only 結果優先；完成時間位於
`daily_orchestration.natural_forward_completion_clock`，至少包含
`post_inference_completed_at`、`observation_emitted_at` 與 `within_*` gate
欄位。既有 05:20 `--auto-catch-up` task 不傳上述 forward 參數，仍維持
盤後 catch-up 語意。

週日 sidecar task 只執行 collection CLI；不呼叫 `--save-history` 或 `--confirm-action-items`，也不寫 source DB。成功週期由 Pre-V2/V4 readiness 自動計數與重驗；不足證據只限制 formal evidence credit，不阻擋 Rule／Advice／Paper operational production。

### ML promotion evidence automatic catch-up

05:17 `run_ml_promotion_evidence.cmd` 會以唯讀方式解讀
`scheduled/data_update_quick/latest_status.json` 的 `check_overview_after`，只接受
`daily_data` 與 `technical_indicators` 都已到達的最晚日期。若原始下一個官方決策日的
strict T-1 超過該日期，就依官方日曆向後掃描最多 31 個曆日，改選最近一個已具備
T-1 證據的決策日；若 strict T-1 已完整，則維持預備的下一個決策日。此選擇不使用
未來資料、不寫正式 SQLite，也不更新 compatible pointer。

Evidence runner 在選日前先驗證 upstream `data_update_quick` status 為 `passed` / `passed_with_warnings`，且 `daily_data` / `technical_indicators` latest date 不得超過當前台北日。status 遺失、failed、格式破損或未來日期時，直接寫 blocked，不猜測未來決策日。

Evidence status schema v3 會保存 `requested_decision_at`、`decision_selection_mode`、
`decision_selection_reason`、`decision_selection_attempts` 與
`latest_core_feature_date`、`upstream_data_update_proof_state` 與
`upstream_data_update_proof_reason`。選日調整不是 Gate 通過；formal OOC、PIT、replay、shadow
或 authority 任一缺件仍會回傳 blocked、alpha 0。

Only the dedicated Decision/Evidence capture task writes the durable snapshot and production evidence event tables through the existing idempotent repositories. The Paper Portfolio task writes only its isolated append-only paper ledger. The data freshness, recommendation, evidence dry-run, ML co-pilot and weekly collection tasks do not write the production evidence DB. No scheduled task runs the UI, reads UI state, changes the live portfolio, changes `ScoringEngine`, changes recommendation weights, promotes / demotes / retires strategies, connects to a broker, or automates trading.

ML allocation co-pilot task 只消費前兩個獨立 task 產生、且與本次 inference release 相同的 evidence／authorization custody。Evidence builder 不簽章，Authority 不訓練模型，Co-pilot 不自行製造 OOS、PIT、calibration、drift 或 shadow days 證據；非零 alpha 必須通過三層重驗。

The recommendation snapshot is intentionally saved before the evidence dry-run so the dry-run can observe the latest recommendation payloads, including screening matrix / why-not / liquidity gate payloads when available.

Generated evidence reports 是機器 Gate 的可稽核輸入；它們本身不證明 alpha，也不得直接轉成交易指令。

During dry-run, the runner may build a transient Daily Decision Desk snapshot for the same run. Reports mark this as `source_coverage_basis=dry_run_transient_decision_desk_snapshot`; this reconciles diagnostics only and does not persist the snapshot.

The evidence dry-run `latest_status.json` also includes selected pipeline summary fields from the same run, including `pipeline_overall_status`, warning counts, advisory counts, source-quality coverage rows, diagnostics, and source-coverage readiness. `pipeline_warnings_count` is only actual warning occurrences. `pipeline_natural_maturity_warning_counts` separates `insufficient_future_data` from `pipeline_actionable_warning_counts`; `natural_maturity_only=true` means the remaining degradation is expected to resolve only as forward observations mature and is not a manual repair blocker. `manual_action_required=true` is reserved for a failed or stale freshness input, missing pipeline summary, pipeline error / blocking gap, or non-natural warning. The wrapper always records `dry_run=true`, `confirm=false`, `writes_evidence_db=false`, and `production_scheduler_allowed=false`. `pipeline_advisories_count` separately records complete but estimated MoneyDJ provenance; it does not mean source data is missing. Fixed-threshold recommendation snapshots may leave `score_percentile_bp` empty because no comparable ranked universe is persisted; that is not a warning. These fields are copied from the dry-run stdout only; the wrapper does not rerun the pipeline. Decision Desk SQLite section providers use `mode=ro` / `query_only` for scheduled reads.

產業指數更新的完整性比較以請求日前最近一個有效交易日的指數集合為基準；歷史上已停用或改名的指數不應造成每日 false-positive warning。若目前有效集合仍缺少指數，仍須保留 warning，因為服務會保留既有當日資料但不會假造來源數值。Portfolio alert 的 `portfolio_alerts_chip_data_missing:<stock_code>` 代表持倉代號在目前籌碼來源不可用，必須先核對持倉來源與公司主檔，不得由 scheduled wrapper、dry-run 或 Codex automation 自動改碼。

### Paper session-open capture 與 Formal 綁定

`baldr-formal-pit-sidecar-postcutoff-daily` 的既有 18:00 Pacific action 會先執行
`run_formal_pit_sidecar_postcutoff.py`，再執行
`run_paper_event_source_capture_daily.py`；沒有另建平行 Task。capture caller 只讀
固定的 D recommendation root
`D:\Min\Python\Project\FA_Data\output\recommendation\runs` 與 D market SQLite
`D:\Min\Python\Project\FA_Data\sqlite\twstock.db`，並把官方 TWSE MIS response
的 bounded raw bytes 寫到 repository 的
`output\paper_execution_eod_replay\event_captures\`。每個 execution date 與
recommendation 完整 file/content hash 各自形成 immutable bucket，保存 envelope、
`raw_response.bin`、capture metadata 與 manifest；不覆寫已存在 bytes，也不寫 D。

capture 僅接受台北 `09:00 <= captured_at < 13:30`、官方固定 endpoint、同一 frozen
recommendation、同日 execution date 與 parser/row/hash readback。production path 以
`now=None` 讓 producer 在 bounded HTTP read 完成後取 `captured_at`；逾 session、
identity/hash/path/schema/custody 錯誤直接 fail closed。GET／空 response 等 transient
錯誤最多重試 3 次，每次都重驗最初 recommendation file/content hash；完整 durable
capture 重跑不再 GET，失敗 attempts 會留在 status receipt。

`run_paper_execution_daily_isolated.py` 的 EOD writer 依同一 execution date 與 frozen
recommendation identity exact resolve durable capture，將候選與 capture manifest 綁成
`paper_execution_candidate_bound.json`，再產生 repository research-only processed
receipt。Formal consumer 重新讀 receipt、candidate、ledger SQLite、capture envelope
與官方 raw response，逐列比對 stock、reference price、fill／費稅／股數、event/capture
時間與 hash；只有 custody 與 event-time eligibility 都成立才可進 Formal，今日 delayed
EOD 或缺三來源仍維持 candidate/no-credit。

## Codex Morning Summary

The Codex app automation `baldr scheduled evidence morning report` runs separately at about local time 05:30. It only reads Windows Task Scheduler status, `latest_status.json`, the latest data update status, the latest recommendation snapshot status, the latest evidence dry-run report, and relevant log warning / error sections, then writes a Traditional Chinese summary to the user.

It must not rerun data update, rerun data freshness, rerun the evidence pipeline, enter confirm write mode, create or modify Windows Task Scheduler tasks, write the production evidence DB, change portfolio / scoring / recommendation weights, apply lifecycle actions, push, or produce trading advice.
