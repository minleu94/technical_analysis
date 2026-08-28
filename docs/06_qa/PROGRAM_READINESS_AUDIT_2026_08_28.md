# Program Readiness Audit — 2026-08-28

## 結論

程式可以持續推進，而且多個原先看起來像「功能沒做」的項目已被補成可觀測、可驗證的工程路徑：P0 已取得 `13/13` 候選來源矩陣與 27 條 acquisition route、Evidence projection 已能顯示 `3/3` 但仍待正式 credit、Paper Equal Weight benchmark 已建立、technical process-pool／recovery／single-writer staging 與 scheduler wiring 已完成、Data Update 也能顯示 fallback 與排程註冊狀態。

這仍不是完整產品 closeout。真正尚未具備的不是同一種「補資料」問題，而是不同性質的外部 gate：P0 的具名 owner／license／PIT decision、Evidence 的真實週期與 review credit、Paper 的真實 fills／成本／execution gap、Formal/ML 的 3 個 owner-controlled inputs、正式 Runtime ACL、technical production backup／rollback＋canary、broker 真實 HTTP canary，以及正式 scheduler registration／history。程式不能替這些事實自行推導或用 replay 填入。正確做法是繼續完成可工程化部分，同時把外部輸入與時間證據獨立追蹤，不再把兩者統稱為「功能沒做完」。

## 可重複的整體盤點入口

新增 `scripts/inspect_program_readiness.py` 作為單一唯讀盤點入口。它會重用既有的
P0 Source Control Center、Pre-V2、Paper Portfolio、Formal ML 與 Runtime read model，
另檢查 `data-update-status-history.v1` 的 JSONL schema、run identity、terminal record
與 8 MiB bounded retention，並可載入 technical／broker latency baseline。它不會呼叫
網路、不掃描替代路徑、不建立 `TWStockConfig`（避免建立目錄／log 的副作用）、不寫
正式 SQLite，也不把 `partial`／`action_required` 轉成任何 scheduler、Formal 或 broker
授權。

目前這份 audit 可用下列方式重算（所有外部 artifact 都必須是明確指定的檔案）：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_program_readiness.py `
  --data-root <DATA_ROOT> `
  --output-root <OUTPUT_ROOT> `
  --p0-audit-json <P0_AUDIT_JSON> `
  --approved-weekly-history-projection <APPROVED_WEEKLY_HISTORY_JSON> `
  --weekly-collection-sidecar <WEEKLY_COLLECTION_SIDECAR_DB> `
  --training-as-of <TRAINING_AS_OF> `
  --technical-performance-baseline <TECHNICAL_BASELINE_JSON> `
  --technical-batch-performance-baseline <TECHNICAL_BATCH_BASELINE_JSON> `
  --technical-write-performance-baseline <TECHNICAL_WRITE_BASELINE_JSON> `
  --technical-worker-acceptance-baseline <TECHNICAL_WORKER_ACCEPTANCE_JSON> `
  --broker-performance-baseline <BROKER_BASELINE_JSON> `
  --runtime-write-probe <RUNTIME_WRITE_PROBE_JSON> `
  --format markdown
```

輸出固定分成 `p0`、`evidence`、`paper`、`formal_ml`、`runtime`、`performance` 與
`update_history` 七個 lane，並以 `execution_order` 列出目前順序（與上述推進順序一致）。
`--weekly-collection-sidecar` 可把隔離 TEMP 的 `pending_human_review` collection 接入
Evidence read model；它只會顯示待審核週期，不會把 pending 轉成 Gate credit。`ready` 只代表該 lane
的既有輸入通過；`partial` 代表仍有安全邊界或後續工程；`waiting_for_external_input`
代表要等真實週期／owner artifact；`action_required` 代表需要先修正資料或治理決策。
缺少路徑時會明示「未觀察」，不會以同根目錄的 prospective、replay、snapshot 或舊
latest status 冒充正式輸入。

本輪已用 `clock:prospective:20260828:v1` 的實際官方 staging 在隔離 TEMP output
完成一次 activation dry-run：PIT、Rule、simulated Portfolio 三個 producer 均能各自產出
prospective manifest，strict readiness 也能產出；所有產物仍保留
`prospective_formal_simulation`／`prospective_only` lane，沒有寫入正式 `BALDR_ML_FORMAL_*`
path，也沒有取得 Formal `3/3` credit。這證明目前的資料與 producer 路徑可運作；剩餘缺口是
下一個有效 clock 的自然累積與 owner-controlled formal publication，不是把兩套 schema 直接改名。

## 目前真實狀態

| 區域 | 先前觀感 | 2026-08-28 實測 | 真正剩餘缺口 | 可否繼續推進 |
|---|---|---|---|---|
| P0 來源 | `13 contract_only`、像是全部沒資料 | live audit=`1 verified / 10 degraded / 2 official_no_data`；Control Center=`0 contract_only`；13 個來源共 27 條候選 route，全部都有至少 2 條 route；TWSE T86／MI_MARGN 無資料時已會再 probe TPEx OpenAPI | 12 項 publication／decision-time provenance、13 項具名 owner/reviewer decision 與 license/use-case 證據；`accepted=0`、`limited=0`；fallback 仍須證明要求日期，不能用最新快照冒充 | 可以；資料取得與 governance 分流推進 |
| Evidence Gate | weekly `0/3` | owner-approved weekly projection=`3/3`；multi-day dry-run=`3/3`；Pre-V2=`ready`；另以正式 SQLite 唯讀連線收集 `2026-08-24..2026-08-28` 一筆 `pending_human_review` sidecar；readiness 明確輸出 `formal_credit_authorized=false` | 另有 8 個 pending-human-review sidecar 期間；此 projection／sidecar 都不授予 Formal credit 或 production scheduler | 可以；Gate 顯示已修正，後續只累積真實週期與審核 |
| Paper Portfolio | 只有 snapshot、週報不可算 | 21 筆 Paper snapshot；正式 Paper output Equal Weight ledger 21 筆，benchmark reader=`ready`；UI／CLI 已有受控 preview→confirm 建置流程 | 真實 fill／partial-fill／reject／override、Decimal 成本、turnover、execution gap；Paper Trade Ledger 缺失 | 可以；benchmark 已建立，execution evidence 不可推造 |
| Formal／ML | formal input `0/3` | 仍是 `0/3`；隔離 dry-run 已驗證三個 prospective producer 可產出，但受控環境目前把三個 path 指向缺失且早於 `training_as_of=2026-08-28` 的 `clock-20260819`；readiness 已明示 stale-clock hint，並列出同 output root 下 6 個 `diagnostic_only` prospective clock/staging marker | causal portfolio ledger、rule champion history、可供該 validator 使用的歷史 PIT sector membership；prospective wrapper 不可直接消費；owner 必須發布當前 clock 並更新明確 path | 可以工程化累積；不得自動改接 `clock-20260828`、也不得拿 prospective sector coverage 回填歷史 |
| Runtime | 只有 `os.access` 提示 | `scripts/inspect_runtime_environment_readiness.py --confirm-write-probe` 已能在明確 TEMP staging 以正式 Registry schema 完成 insert／讀回／rollback／清除；統一 inspector 可用 `--runtime-write-probe` 載入這份 artifact。此 host 對正式 `config.log`／Research Registry 的 write-handle 仍可能回 PermissionError，會標成 production ACL 未驗證而不再混同 staging 能力 | 正式 Registry 本身仍未做實寫；production ACL／鎖定仍需 owner 在正式環境確認 | 可以；schema transaction 已在非正式 staging 驗證，正式路徑只差環境權限證據 |
| 效能工程 | technical full-batch、isolated CSV／SQLite writer、real indicator process-pool staging、broker bounded fetch 離線 acceptance 與 synthetic contract 已量測 | full-batch read／calculate／aggregate、CSV serialization、SQLite lock/retry、real calculator process pool（bounded in-flight／retry／parent single writer）、worker process crash recovery／queued cancellation、broker parser／rate-limit／retry／duplicate／failure contract 與 synthetic queue／cancel checks 均有 artifact；technical batch 的 production feature flag／scheduler wiring 已接上但預設關閉，broker pool 仍關閉 | 真實 broker HTTP canary／來源 rate limit、Selenium driver 重建、technical production backup／rollback 與 owner-approved canary；staging recovery 不等同 production proof | 可以；先由 owner 核准 technical backup／rollback 後做單次 canary，再允許真實 broker canary，不能直接拉高 thread 數 |
| Data Update 顯示 | 卡片／頁面狀態容易互相矛盾 | fail-closed 顯示、台灣市場日期、候選分頁、inline summary、P0 13 列唯讀 projection 與 Research Console 共用欄位已接上；`data-update-timeline.v1` 明確顯示排程 run、最後成功完成時間、12 個步驟結果與 freshness；runner／UI 已接 `data-update-status-history.v1` append-only 歷史；P0 fallback attempted／date mismatch／network error 已保留並以不同文字呈現；UI 會把 history 缺漏明示為「新版 runner 尚未產生；不回填舊 latest」 | 現有正式 latest status 最後一次為 `2026-08-27T04:32:14-07:00`，history 仍缺漏；本機 `query_baldr_scheduled_tasks.cmd` 實測 13/13 個預期 task 均不存在／不可用，因此不能期待自然 history 在未重新註冊 task 前出現；live refresh／歷史 retention 尚未完成；仍需在正式環境走完全流程 live UI QA | 可以；先由 owner 重新註冊並確認 `baldr-data-update-quick-daily`（以及依序的 freshness／evidence tasks），再觀察真實 history；依成功、官方無資料、fallback、schema mismatch、network failure、資料落後與 governance blocked 做 live QA，不掃描目錄、不回放補歷史或繞過 candidate-only 邊界 |

## P0 多路徑取得結果

新增 `p0-source-acquisition-routes.v1`，固定 13 個來源分母與 27 條受治理候選 route；每個來源至少兩條 route。已直接接上五條 live fallback：

- TDCC legacy CSV 失敗時改走 `https://openapi.tdcc.com.tw/v1/opendata/1-5`。
- TWSE 月營收 OpenAPI 失敗時改走 MOPS `t187ap05_L.csv`。
- TPEx 月營收 OpenAPI 失敗時改走 MOPS `t187ap05_O.csv`。
- TWSE T86 回覆官方無資料或 primary transport 失敗時，改 probe `https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading`；只接受與要求日期完全相同的列。
- TWSE MI_MARGN 回覆官方無資料或 primary transport 失敗時，改 probe `https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance`；只接受與要求日期完全相同的列。

兩條 TPEx fallback 已有 source-specific parser、ROC compact date 正規化、row conservation 與日期 fail-closed 測試。這是「能取得另一條官方路徑」的工程完成，不是 source acceptance；TPEx OpenAPI 目前是 latest snapshot，不會被自動回填到較早或未證明的交易日。

漲跌停鎖死來源已由不相符的 `MI_INDEX` 改為官方 `TWT84U`。本次 `TWT84U` 原始 1,377 列、鎖死事件 0 列；這表示該交易日沒有符合條件的事件，不是 schema 或 endpoint 失敗。

2026-08-28 重新以受控外部網路完成 bounded live audit：13/13 來源均有 machine row，`1 verified / 10 degraded / 2 official_no_data`；raw rows=`72,202`、accepted rows=`70,825`。主要 row count 為：除權息 251、減資／分割 2、停復牌 1、處置 4、分盤 4、全額交割 10、漲跌停行情 1,377（鎖死事件 0）、三大法人 0、信用交易 0、TDCC 68,578、TWSE 月營收 1,085、TPEx 月營收 890；三大法人與信用交易的 primary 0 列是官方當日無資料回覆，不是 network failure。新增的 fallback evidence 顯示：信用交易 TPEx OpenAPI 確實回 `2026-08-27`、但要求日為 `2026-08-28`，所以明確標成 `date_mismatch` 並拒絕；三大法人本次 fallback 遇到 response prematurely，明確標成 `network_error`，沒有把它誤算成資料。MOPS 季報 availability artifact 通過驗證。所有 route 仍固定 `candidate_evidence_only=true`、`formal_eligible=false`、scheduler／production ingestion 關閉。

為釐清「官方當日無資料」是否只是日期語意，另於本輪以 `decision_date=2026-08-27` 完成第二次 bounded live cross-date capture：13/13 均有 machine row，raw=`91,824`、accepted=`90,447`；TWSE T86 實得 `18,307` 列、MI_MARGN 實得 `1,295` 列，表示兩個同語意官方主路徑在 8/27 有可取得資料。這份 capture 只作日期對照，不會回填 8/28、改寫正式資料或解除 PIT／license／owner blocker。artifact=`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_evidence_20260828_live_tpex_20260827.json`（SHA-256=`ABF95D392FFC05EA81BB03EB68D8ACBFFE50C9FEDBEEE09EA7641A5B94FEE57A`）；owner packet=`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_owner_decision_packet_20260827_live.md`（SHA-256=`30101531579324020A899CDECE3AD1EBE04812ABA78632050F4DB7F522DD65E7`）。

所以 `contract_only` 的正確解讀是「Control Center 沒有載入 audit」，不能再解讀為「沒有資料」。載入本次 audit 後，真實治理狀態為 `12 blocked_provenance + 1 research_shadow`，人工 decision 為 `13 not_supplied`。

2026-08-27 另以官方 MOPS EZSearch 抓取 2026-08-20～2026-08-27 的 availability-only artifact，得到 426 個 events／426 個 projections。sii、otc 的 8 個 query 有正常回應；rotc、pub 的 8 個 query 是官方 `status=fail` 零列回覆，現在已與真正的 timeout／網路／解析錯誤分開計數。此 artifact 仍只在 TEMP development root，沒有寫入正式 availability mapping、SQLite 或 Formal input；P0 的季度來源仍須 owner／reviewer 的 license、coverage 與使用範圍決議。

### Data Update 排程註冊觀察

本機以 `cmd /c scripts\\scheduled\\query_baldr_scheduled_tasks.cmd` 做唯讀查詢，結果為 `13 of 13 task(s) missing or unavailable`；沒有刪除或修改任何 task。這解釋了為什麼正式 output 仍只有舊的 `latest_status.json` 而沒有新版 runner 產生的 `history.jsonl`：目前缺的是排程註冊／真實執行證據，不是可以安全複製的歷史檔。重新註冊屬於 host 狀態變更，需由 owner 在正確 Windows 帳號與路徑下執行 `scripts\\scheduled\\register_baldr_scheduled_tasks.cmd` 的受控流程，然後再以 query 與實際 terminal status 驗證。

本輪新增 `scripts\\inspect_scheduled_task_registration.py`，以同樣的 `schtasks /Query` 產生
可供 unified readiness 讀取的 `scheduled-task-registration.v1` 摘要；它不保存完整 LIST、
不寫 task，也不會把缺 task 自動註冊。2026-08-28 實測 artifact 為
`C:\\Users\\archi\\AppData\\Local\\Temp\\technical_analysis_program_readiness\\scheduled_task_status_20260828.json`，
`available=0/13`、`all_available=false`，SHA-256=`880FB764D8B44D9F37F99D22147B2A37692D62A0F097B6C02D2F577318B5B13C`。
將它以 `--scheduled-task-status` 傳給 `inspect_program_readiness.py` 後，Update History lane
會明確保留 `scheduled_tasks_missing_or_unavailable:0/13`，並維持等待真實 history 的狀態。

## 為什麼有些東西不能直接補滿

1. **Owner／license decision 是權限事實，不是資料欄位。** 程式可以蒐集官方 endpoint、條款 URL、hash、coverage 與 PIT 證據，但不能冒用具名 reviewer 作出 `accepted`／`limited` 決議。
2. **Paper fills 是執行事實。** 現有 `trades.jsonl`、virtual order trace 或每日 NAV 不能反推出真實 partial fill、reject、滑價、手續費與 override；硬轉換會製造不存在的績效證據。
3. **Formal clock 是時間事實。** 2026-08-25 的 prospective sector membership 有 1,932 列，但只證明該日起的前景 coverage；把它套回更早日期會造成 look-ahead。現有 historical ML validator 拒絕該 prospective schema 是正確的 fail-closed。
4. **Runtime staging transaction 不是正式 Registry 實寫。** Probe 現在會在非正式暫存 DB 使用正式 Registry schema，驗證 insert／讀回／rollback／清除；這排除了「程式完全沒有 transaction 路徑」的疑問，但仍不能宣稱正式 Registry 的 ACL／鎖定／production 實寫已成功。
5. **Formal path 的 missing 可能是 stale owner handoff。** 本次 readiness 實測三個受控 path 都落在缺失的 `clock-20260819`，且該 clock 日期早於 `training_as_of`；這是 path／publication 尚未完成，不代表可以把同根下另一個 clock 自動冒充正式 input。

## 持續推進順序

1. 將 live P0 audit、actual route、fallback reason、publication/PIT class 與 owner decision 投影接進 Data Update／Research Console，同時保留 candidate-only 安全邊界。（Data Update 的唯讀 projection、fallback 拒絕診斷與 append-only history producer 已完成；後續觀察真實排程並補 live refresh／retention。）
2. 以 5 組 owner packet 完成 13 項 source 的 license/use-case/reviewer 決議；可先 `limited`，不必等待全部來源一次 accepted。
3. 持續收集真實 weekly sidecar 並完成 owner review；目前已接入明確 sidecar 參數，不能用 pending 或 projection 直接取得 Formal credit。
4. 將 QA Equal Weight builder 納入明確受控的 Paper benchmark 建置流程（已完成 CLI／UI 共用 preview→confirm 與不可覆寫 ledger）；由真實 paper execution producer 或使用者提供完整 fills CSV，建立 Paper Trade Ledger 後才計算成本後週報。
5. 保持 prospective publisher 與歷史 ML validator 的 schema 分離；讓 portfolio ledger、rule history、PIT sector 三個 manifest 自下一個有效 clock 起自然累積，並用 readiness inspector 的 lane／schema 診斷避免把 shadow bytes 誤接到正式 consumer。
6. 已完成 technical indicator 各階段耗時、writer contention、real staging bounded process-pool、worker recovery／取消 acceptance、parent single-writer integration staging，以及 production batch feature flag／scheduler wiring；下一步是由 owner 核准 backup／rollback 後做單次 technical canary，再允許真實 broker canary。
7. 完成整個 Update 使用流程的 live UI QA：程式端已先以 fixture 覆蓋成功、官方無資料、fallback、schema mismatch、network failure、資料落後與 governance blocked 的狀態投影；剩餘是正式環境真實排程／權限／歷史 retention 的觀察與截圖證據。

## 本次程式與證據

- 多路徑 registry：`data_module/p0_source_acquisition_routes.py`
- 官方 parser：`data_module/p0_official_source_parsers.py`
- live probe／fallback：`scripts/update_phase3c_candidates.py`
- P0 evidence audit：`scripts/run_p0_source_evidence_audit.py`
- candidate audit：`scripts/run_p0_candidate_audit.py`
- live audit（2026-08-28 fresh capture，含 TPEx fallback lineage）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_evidence_20260828_live_tpex_fallback_v2.json`（SHA-256=`94186ed0565f544a296427b423b01167e78ef15d2871e1c757bb8de9efe83d82`）
- cross-date live audit（`decision_date=2026-08-27`，驗證 T86／MI_MARGN 有真實官方日資料）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_evidence_20260828_live_tpex_20260827.json`（SHA-256=`ABF95D392FFC05EA81BB03EB68D8ACBFFE50C9FEDBEEE09EA7641A5B94FEE57A`）
- P0 owner packet（由最新 fresh capture 唯讀重排）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_owner_decision_packet_20260828_live_tpex_fallback.md`（SHA-256=`be6e164ead39fb2894e5a6f028ca275dcafa1f0f4926888fe2efb299c5ad7314`）
- cross-date owner packet：`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_owner_decision_packet_20260827_live.md`（SHA-256=`30101531579324020A899CDECE3AD1EBE04812ABA78632050F4DB7F522DD65E7`）
- Control Center：`C:\Users\archi\AppData\Local\Temp\p0-source-control-center-20260827.json`
- Evidence readiness（既有 projection readout）：`C:\Users\archi\AppData\Local\Temp\pre-v2-readiness-20260828.json`
- V2.2 current weekly collection（正式 SQLite `mode=ro`、`2026-08-24..2026-08-28`、`pending_human_review`，不計 Gate credit）：sidecar `C:\Users\archi\AppData\Local\Temp\technical_analysis_evidence_20260828\scheduled\v2_2_weekly_collection\evidence_scheduler.db`（SHA-256=`B5331161E4E96C6FC4AED055B3B4BEC6F566E8699C2C96CF6C2A15254AA3F666`）；report `C:\Users\archi\AppData\Local\Temp\technical_analysis_evidence_20260828\scheduled\v2_2_weekly_collection\v2_2_weekly_collection_20260828.json`（SHA-256=`86DAE1280B09B26435A0BE745C7362A16BE41045C27DB4A21D119AB2E2D56A88`）
- 2026-08-28 最終 unified readiness（載入 live P0、approved projection、pending sidecar、Paper／Formal／Runtime／performance artifacts）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_20260828_final.json`（status=`action_required`；SHA-256=`BFCF66C300EABA7A5FF4384BE3C5BF0104BCDC861CBD8FCD693C45604F7038E3`）
- 2026-08-28 Formal input readiness：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\ml_formal_input_readiness_20260828.json`（`0/3`、`formal_oos_allowed=false`；SHA-256=`F9C896F2D2196F0BFAB18E9C9A06B2CE08618C5F83BC6E5EFCD4B8AA0F7AF960`）
- ML Formal readiness（既有 baseline readout）：`C:\Users\archi\AppData\Local\Temp\ml-formal-input-readiness-20260828.json`
- Runtime readiness：2026-08-28T06:32:33Z 以 `scripts/inspect_runtime_environment_readiness.py --format json` 在一般 host context 重跑；overall=`ready`、`write_probe=os.access_plus_existing_handle`、diagnostics=`[]`。同日 06:58:30Z 另在 OS TEMP 的明確 staging 目錄執行 `--confirm-write-probe`：`file_write_succeeded=true`、`sqlite_write_succeeded=true`、`registry_transaction_succeeded=true`、`cleanup_succeeded=true`；正式 Registry 仍未被寫入。
- QA Equal Weight preview：`D:\Min\Python\Project\FA_Data\output\qa\readiness_refresh_20260828\paper_equal_weight_preview.sqlite`
- Paper Equal Weight output：`D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_equal_weight_benchmark.sqlite`（21 筆；research-only benchmark，不是成交帳）
- Equal Weight workflow service：`app_module/paper_equal_weight_benchmark_builder.py`；Portfolio UI 入口為持倉管理 > Paper Portfolio >「預覽／建立 Equal Weight」
- Technical worker recovery／取消與 parent single-writer integration staging：`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_worker_recovery_20260828.json`（SHA-256=`983FDEB4C1829137857F49513463BA48579910BF5A3882B73260F096F0454A8D`）；real calculator 2/2 stock groups、crash=`BrokenProcessPool` 後 recovery 120 rows、queued cancellation 6 筆、parent 依序寫 240 rows CSV／SQLite、SQLite lock/retry 通過、all checks 通過；`production_single_writer_integration.status=staging_measured`、scope=`isolated_staging`，production worker 仍關閉

## 安全邊界

本次沒有把任何 candidate source 升格為 accepted／limited，沒有把 QA benchmark 當正式績效，沒有從既有 snapshot 補造 Paper fills，沒有回填 prospective Formal evidence，也沒有開啟 ML training、promotion、production scheduler 或 broker。正式 source、Paper execution 與 Formal clock 仍各走自己的 append-only／PIT 契約。
