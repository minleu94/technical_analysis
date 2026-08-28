# Program Readiness Audit — 2026-08-28

## 結論

程式可以持續推進，而且多個原先看起來像「功能沒做」的項目已被補成可觀測、可驗證的工程路徑：P0 已取得 `13/13` 候選來源矩陣與 27 條 acquisition route、Evidence projection 已能顯示 `3/3` 但仍待正式 credit、Paper Equal Weight benchmark 已建立、technical process-pool／recovery／single-writer staging 與 scheduler wiring 已完成、Data Update 也能顯示 fallback 與排程註冊狀態。

這仍不是完整產品 closeout。真正尚未具備的不是同一種「補資料」問題，而是不同性質的外部 gate：P0 的具名 owner／license／PIT decision、Evidence 的真實週期與 review credit、Paper 的真實 fills／成本／execution gap、Formal/ML 的 3 個 owner-controlled inputs、正式 Runtime ACL、technical production backup／rollback＋canary，以及正式 scheduler registration／history。Broker 現在已完成一次受控真實 HTTP canary，但長期 rate-limit／Selenium fallback／production writer 仍未驗收。程式不能替這些事實自行推導或用 replay 填入。正確做法是繼續完成可工程化部分，同時把外部輸入與時間證據獨立追蹤，不再把兩者統稱為「功能沒做完」。

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
  --freshness-status-path <FRESHNESS_STATUS_JSON> `
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

`training_as_of` 若只給日期或格式無效，`formal_ml` lane 會直接回報
`training_as_of_timezone_required`／`training_as_of_invalid`，不再把時區輸入錯誤包裝成
泛化的 `formal_ml_readiness_inspection_failed`。

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
| Evidence Gate | weekly `0/3` | owner-approved weekly projection=`3/3`；multi-day dry-run=`3/3`；Pre-V2=`ready`；另以正式 SQLite 唯讀連線收集 `2026-08-24..2026-08-28` 一筆 `pending_human_review` sidecar；readiness 與 Workbench 都明確輸出 `formal_credit_authorized=false`，並揭露 pending 期段 | 另有 8 個 pending-human-review sidecar 期間；此 projection／sidecar 都不授予 Formal credit 或 production scheduler | 可以；Gate 顯示已修正，後續只累積真實週期與審核 |
| Paper Portfolio | 只有 snapshot、週報不可算 | 21 筆 Paper snapshot；最近週期唯讀觀察到 5 筆 snapshot／5 筆 Equal Weight benchmark；正式 Paper output Equal Weight ledger 21 筆，benchmark reader=`ready`；UI／CLI 已有受控 preview→confirm 建置流程；fills template 已可輸出 | 真實 fill／partial-fill／reject／override、Decimal 成本、turnover、execution gap；Paper Trade Ledger 目前不存在（最近週報 `cost_record_count=0`、`weekly_report_status=not_computable`） | 可以；benchmark 已建立，先由 Paper execution producer／人工提供真實 fills，再以 preview→confirm 建立 ledger；不可從 snapshot 或 virtual trace 推造 |
| Formal／ML | formal input `0/3` | 仍是 `0/3`；隔離 dry-run 已驗證三個 prospective producer 可產出，但受控環境目前把三個 path 指向缺失且早於 `training_as_of=2026-08-28` 的 `clock-20260819`；readiness 已明示 stale-clock hint，並列出同 output root 下 6 個 `diagnostic_only` prospective clock/staging marker | causal portfolio ledger、rule champion history、可供該 validator 使用的歷史 PIT sector membership；prospective wrapper 不可直接消費；owner 必須發布當前 clock 並更新明確 path | 可以工程化累積；不得自動改接 `clock-20260828`、也不得拿 prospective sector coverage 回填歷史 |
| Runtime | 只有 `os.access` 提示 | `scripts/inspect_runtime_environment_readiness.py --confirm-write-probe` 已能在明確 TEMP staging 以正式 Registry schema 完成 insert／讀回／rollback／清除；統一 inspector 可用 `--runtime-write-probe` 載入這份 artifact。此 host 對正式 `config.log`／Research Registry 的 write-handle 仍可能回 PermissionError，會標成 production ACL 未驗證而不再混同 staging 能力 | 正式 Registry 本身仍未做實寫；production ACL／鎖定仍需 owner 在正式環境確認 | 可以；schema transaction 已在非正式 staging 驗證，正式路徑只差環境權限證據 |
| 效能工程 | technical full-batch、isolated CSV／SQLite writer、real indicator process-pool staging、broker bounded fetch 離線 acceptance 與 synthetic contract 已量測 | full-batch read／calculate／aggregate、CSV serialization、SQLite lock/retry、real calculator process pool（bounded in-flight／retry／parent single writer）、worker process crash recovery／queued cancellation、broker parser／rate-limit／retry／duplicate／failure contract、synthetic queue／cancel checks 與單次 MoneyDJ real HTTP canary 均有 artifact；technical batch 的 production feature flag／scheduler wiring 已接上但預設關閉，broker pool 仍關閉 | 真實來源長期 rate-limit、Selenium driver 重建、technical production backup／rollback 與 owner-approved canary；staging recovery／單次 HTTP 不等同 production proof | 可以；先由 owner 核准 technical backup／rollback 後做單次 canary，再評估 broker bounded pool，不能直接拉高 thread 數 |
| Data Update 顯示 | 卡片／頁面狀態容易互相矛盾 | fail-closed 顯示、台灣市場日期、候選分頁、inline summary、P0 13 列唯讀 projection 與 Research Console 共用欄位已接上；`data-update-timeline.v1` 明確顯示排程 run、最後成功完成時間、12 個步驟結果與 freshness；runner／UI 已接 `data-update-status-history.v1` append-only 歷史；P0 fallback attempted／date mismatch／network error 已保留並以不同文字呈現；待更新卡片會顯示新鮮度基準日／資料最新日；2026-08-28 quick run=`20260828-29472` terminal=`passed`、12/12，Data Update QA=`23 passed / 0 failed / 4 skipped`；unified readiness 新增明確 `--freshness-status-path`，可分開投影 freshness 的 status／checked_at／warnings／errors | 核心 SQLite 已追上 `2026-08-28`，隔離 TEMP freshness probe 已觀察 `passed`，但正式 `data_freshness/latest_status.json` 仍是 `2026-08-27`；本機 probe 對正式 output 寫入被 `PermissionError` 拒絕；`query_baldr_scheduled_tasks.cmd`／registration inspector 仍是 13/13 不可用，因此下一輪 freshness／evidence history 不能靠自然 scheduler 產生；仍需 owner 修正正式 output ACL、重新註冊 task，再做完整 live UI QA | 可以；資料更新本身已恢復，先由 owner 修正 output ACL 並重新註冊／確認 `baldr-data-update-quick-daily`（以及依序的 freshness／evidence tasks），再觀察 terminal history、freshness 與 downstream live refresh；不回放補歷史或繞過 candidate-only 邊界 |

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

本機以 `cmd /c scripts\\scheduled\\query_baldr_scheduled_tasks.cmd` 做唯讀查詢，結果仍為 `13 of 13 task(s) missing or unavailable`；沒有刪除或修改任何 task。另一方面，2026-08-28 quick runner 已由既有程序完成真實 `running`／terminal history（run=`20260828-29472`），所以目前缺的是正式 scheduler registration 與 freshness output ACL，不是可以複製的歷史檔。重新註冊屬於 host 狀態變更，需由 owner 在正確 Windows 帳號與路徑下執行 `scripts\\scheduled\\register_baldr_scheduled_tasks.cmd` 的受控流程，然後再以 query 與實際 terminal status 驗證。

本輪新增 `scripts\\inspect_scheduled_task_registration.py`，以同樣的 `schtasks /Query` 產生
可供 unified readiness 讀取的 `scheduled-task-registration.v1` 摘要；它不保存完整 LIST、
不寫 task，也不會把缺 task 自動註冊。2026-08-28 實測 artifact 為
`C:\\Users\\archi\\AppData\\Local\\Temp\\technical_analysis_program_readiness\\scheduled_task_status_20260828.json`，
`available=0/13`、`all_available=false`，SHA-256=`880FB764D8B44D9F37F99D22147B2A37692D62A0F097B6C02D2F577318B5B13C`。
將它以 `--scheduled-task-status` 傳給 `inspect_program_readiness.py` 後，Update History lane
會明確保留 `scheduled_tasks_missing_or_unavailable:0/13`，即使已有手動／受控 quick run history，仍會要求 owner 先完成 task registration。

本次 quick runner terminal artifact 位於
`D:\\Min\\Python\\Project\\FA_Data\\output\\scheduled\\data_update_quick\\latest_status.json`，
`status=passed`、`run_id=20260828-29472`、`step_count=12`；同一目錄的
`history.jsonl` 已有 `running` 與 `passed` 兩筆 record。重新執行唯讀
`scripts\\qa_validate_update_tab.py` 得到 `23 passed / 0 failed / 4 skipped`。
嘗試手動執行 `data_freshness_probe.py` 時，對正式
`output\\scheduled\\data_freshness\\latest_status.json` 的寫入被
`PermissionError` 拒絕；現在 probe 會以結構化 `status=failed`、
`status_artifact_write_failed:PermissionError` 回報，不再留下未處理 traceback；正式 freshness
檔仍停在 `2026-08-27`，這是正式 output ACL 問題，不是把核心 SQLite 判定成落後。另以明確 TEMP status／log path 完成一次
read-only probe，結果為 `status=passed`、daily／technical latest=`2026-08-28`，
status artifact SHA-256=`3A077E2D2775F02E4BE6A4016EA5DEB6A8B7B1B5E784303699CE64760BF6D66C`；
它只證明資料與 probe 路徑可運作，不會替正式 freshness 檔或排程 history。程式端已補上
`BALDR_FRESHNESS_STATUS_PATH`／`BALDR_FRESHNESS_LOG_PATH` 的受控覆寫；owner 可在
修正 ACL 前先把 read-only 產物導到已核准可寫路徑，並在 UI 設定
`DATA_FRESHNESS_STATUS_ARTIFACT` 讀取同一份明確檔案。這仍需要 owner 更新 Task
Scheduler 執行環境，不能由 readiness inspector 自動套用。

### 2026-08-28 月營收更新缺口與候選補齊

SQLite 月營收目前仍停在 `2026-06`（246,331 rows、最新完整可用日
`2026-07-15`），但這不代表官方來源沒有新資料。以 MOPS static snapshot
取得 `2026-07` 數值後，再分別查詢 TWSE `t187ap05_L` 與 TPEx
`mopsfin_t187ap05_O` 的官方 `出表日期`，兩條鏈交集為 `1,851` rows：TWSE
991、TPEx 860，公告日皆為 `2026-08-17`、保守 `available_date=2026-08-18`。
另有 2 筆 snapshot（2850、2883）沒有官方公告映射，保留為缺口，沒有用猜測日期補值。

候選 CSV 已通過 validator（accepted=1,851、diagnostics=0），並以正式 DB
執行唯讀 backfill dry-run（raw=1,851、normalized=1,851、diagnostics=0）；
候選與 raw／DB 仍在 TEMP，沒有寫入正式 availability mapping 或 SQLite。這也暴露
原本更新頁的顯示問題：只有 SQLite 狀態時會顯示 `status=ok`，看不出較新的數值
候選尚未套用。更新服務現在依 snapshot 期別選檔並揭露
`candidate_latest_period`；若候選較新，UI 顯示「候選可用／候選待套用期別」，不再
把抓取完成誤顯示成正式完成。availability builder 也共用同一套期別／抓取日選檔規則，
不會讓歷史大檔因 mtime／檔案大小遮蔽新月份。正式 apply 仍需 owner 確認。

本輪 snapshot SHA-256=`D055DF5F6193961198655C5B46F5D6111D808430CBEFDC4DDB27F521EBABAD65`；
availability candidate SHA-256=`9CAE017074FE08B5EE14761FDAB8458D738AFD63AF0ED73F4E5A72E8BF34D016`。

## 為什麼有些東西不能直接補滿

1. **Owner／license decision 是權限事實，不是資料欄位。** 程式可以蒐集官方 endpoint、條款 URL、hash、coverage 與 PIT 證據，但不能冒用具名 reviewer 作出 `accepted`／`limited` 決議。
2. **Paper fills 是執行事實。** 現有 `trades.jsonl`、virtual order trace 或每日 NAV 不能反推出真實 partial fill、reject、滑價、手續費與 override；硬轉換會製造不存在的績效證據。
3. **Formal clock 是時間事實。** 2026-08-25 的 prospective sector membership 有 1,932 列，但只證明該日起的前景 coverage；把它套回更早日期會造成 look-ahead。現有 historical ML validator 拒絕該 prospective schema 是正確的 fail-closed。
4. **Runtime staging transaction 不是正式 Registry 實寫。** Probe 現在會在非正式暫存 DB 使用正式 Registry schema，驗證 insert／讀回／rollback／清除；這排除了「程式完全沒有 transaction 路徑」的疑問，但仍不能宣稱正式 Registry 的 ACL／鎖定／production 實寫已成功。
5. **Formal path 的 missing 可能是 stale owner handoff。** 本次 readiness 實測三個受控 path 都落在缺失的 `clock-20260819`，且該 clock 日期早於 `training_as_of`；這是 path／publication 尚未完成，不代表可以把同根下另一個 clock 自動冒充正式 input。

6. **候選根目錄確實有檔案，但沒有可直接消費的 Formal input。** 新增的 `inspect_formal_input_candidates.py` 在正式 output 做 bounded 掃描：511 份 manifest 可解析、1 份無法解析、到達 512 上限；31 份 research-only、7 份 prospective-only，三個可辨識 causal ledger 都明確標成 `research-causal-baseline-ledger.v1`／`formal_consumer_compatible=false`，PIT sidecar 則屬 prospective clock。這證明目前缺的是 owner-controlled publication／custody，不是單純漏掃資料夾。

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
- P0 owner packet（由最新 fresh capture 唯讀重排，含 actual／candidate route、fallback、PIT／timestamp 與 license URL 線索）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_owner_decision_packet_20260828_live_tpex_fallback_current.md`（SHA-256=`6A4CA81DD2E4C6B69784FCC06316399B878AEC727D4E131865A47778A12FDD41`）
- cross-date owner packet：`C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_owner_decision_packet_20260827_live.md`（SHA-256=`30101531579324020A899CDECE3AD1EBE04812ABA78632050F4DB7F522DD65E7`）
- Control Center：`C:\Users\archi\AppData\Local\Temp\p0-source-control-center-20260827.json`
- Evidence readiness（既有 projection readout）：`C:\Users\archi\AppData\Local\Temp\pre-v2-readiness-20260828.json`
- V2.2 current weekly collection（正式 SQLite `mode=ro`、`2026-08-24..2026-08-28`、`pending_human_review`，不計 Gate credit）：sidecar `C:\Users\archi\AppData\Local\Temp\technical_analysis_evidence_20260828\scheduled\v2_2_weekly_collection\evidence_scheduler.db`（SHA-256=`B5331161E4E96C6FC4AED055B3B4BEC6F566E8699C2C96CF6C2A15254AA3F666`）；report `C:\Users\archi\AppData\Local\Temp\technical_analysis_evidence_20260828\scheduled\v2_2_weekly_collection\v2_2_weekly_collection_20260828.json`（SHA-256=`86DAE1280B09B26435A0BE745C7362A16BE41045C27DB4A21D119AB2E2D56A88`）
- 2026-08-28 最終 unified readiness（載入 live P0、approved projection、pending sidecar、Paper／Formal／Runtime／performance artifacts）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_20260828_final.json`（status=`action_required`；SHA-256=`BFCF66C300EABA7A5FF4384BE3C5BF0104BCDC861CBD8FCD693C45604F7038E3`）
- quick runner 完成後重新產生的 unified readiness（run=`20260828-29472`、已載入 scheduler registration artifact）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_20260828_post_patch.json`（status=`action_required`；SHA-256=`210FF09EB321BC4DFAA6C12FACC29CC3E8D15D4A962CC08B8EE399C73AE63931`）；Update History blocker 已精確投影為 `scheduled_tasks_missing_or_unavailable:0/13`，下一步是 owner 重新註冊 task，不是回填 history。
- 最新 unified readiness（同一組輸入另載入明確 TEMP freshness status）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_20260828_final_with_freshness_projection.json`（status=`action_required`；SHA-256=`80AF60C103E12948E935791E16009622F5898566AD7F067092C8A10B874727E9`）；freshness projection=`passed`、daily／technical latest=`2026-08-28`，Update History 剩餘 blocker 僅 `scheduled_tasks_missing_or_unavailable:0/13`，不再把 freshness 觀測與 scheduler registration 混在一起。
- post-QA unified readiness（完成 `3664 passed / 1 skipped` 全回歸、Data Update QA 與 targeted mypy／py_compile 後重算）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_20260828_final_postqa.json`（status=`action_required`；SHA-256=`750CEEC7DD65ADE1A826B8A1427DA08332BFF4C65F4A07C38A47F1446C7C92A0`）；七個 lane 的 blocker 與前一份一致，freshness 仍為 `passed`，沒有把測試通過誤宣稱為 production gate 通過。
- 最新全量回歸（兩批月營收候選／snapshot 選檔修正後）：`3674 passed / 1 skipped / 66 warnings`（`537.05s`；未指定 JUnit 輸出）；這只更新工程回歸證據，不會把 production scheduler、正式 ACL、owner decision 或資料 gate 誤標成 ready。
- 新增 availability candidate merge workflow 後的月營收候選唯讀預演：既有 mapping=`1,832`、candidate=`1,851`、added=`1,851`、conflict=`0`、merged=`3,683`；正式 target／SQLite 均未寫入。新增真實 broker HTTP canary 後重算 unified readiness：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_after_broker_canary_20260828.json`（status=`action_required`；SHA-256=`F7B644EC597629E61D17431EF497C2E251F165DF4827DB1E5B0CF8178350FABB`），performance blocker 僅剩 `technical_production_single_writer_canary_not_completed`。
- freshness probe／CMD／PowerShell wrapper post-change regression：`3665 passed / 1 skipped`；`run_daily_data_freshness_check.ps1` 與正式 Task Scheduler 使用的 `.cmd` 都已以正式資料唯讀＋TEMP status/log 實際執行 `status=passed`、daily／technical latest=`20260828`，並共用同一個 canonical probe。
- HEAD final unified readiness（canonical freshness wrapper 修正後重新盤點）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\program_readiness_20260828_head_final.json`（status=`action_required`；SHA-256=`AEA56956A13AE25B271CFE56D59905180C3412743EA063FAC324A763C5A29039`）；七個 lane 的 blocker 維持原樣，表示 wrapper 修正只改善錯誤可觀測性，沒有越過任何治理／正式環境 gate。
- freshness probe ACL fail-soft regression：明確模擬 status／log `PermissionError` 時，probe 輸出結構化 `status=failed`、兩個 artifact write diagnostics 並回傳 exit code `1`；不再讓 scheduler 只看到未處理 traceback。
- post-QA MainWindow UI smoke：`output\qa\full_app_healthcheck_20260828_final_postqa\20260828_062145\result.json`（status=`passed`；SHA-256=`CE1DCCF942F3A1FADC02F910FFBE7A8ABF00369679206CE834DD441E9AF0CC41`）；8 個 workspace 全部切換成功，`1366x768`／`390x844` 均 matched，cancel-only probe 未觸發 destructive action；UpdateView suite=`67 passed`、Data Update QA=`23 passed / 0 failed / 4 skipped`。
- 既有 live P0 audit 已另以 `scripts\build_p0_intake_from_audit.py` 轉成 13 列 candidate intake；輸出 `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_candidate_intake_from_audit_20260828.json`，重建後 SHA-256=`35682FF727887B1F4521755D548CD88CDF8080174828D64B0ECF012CFD9DC81D`。唯讀 validator 結果為 `deferred`、`valid=13`、`owner_review_ready=0`；轉接器在 dossier 外另保留 allowlist 內的 machine route／fallback／probe／timestamp evidence，但沒有填入或推導 owner／license／publication／PIT 決議，`downstream_eligibility` 仍為 `none`。validator report SHA-256=`E1ECE0A7615DAA867ABB099BECAF4F2EB4DADB995007C775FBA1E0A70B5FDE43`。
- 2026-08-28 Formal input readiness：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\ml_formal_input_readiness_20260828.json`（`0/3`、`formal_oos_allowed=false`；SHA-256=`F9C896F2D2196F0BFAB18E9C9A06B2CE08618C5F83BC6E5EFCD4B8AA0F7AF960`）
- Formal candidate inventory（明確指定正式 output、只讀 bounded manifest，無升格）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_formal_candidate_inventory_20260828\inventory.json`（511 parsed／1 invalid／truncated at 512；31 research-only、7 prospective-only、0 formal schema candidate；SHA-256=`700B5E61A1C537E23166E51A0C6F98F493F6D44B7145DC524C800267CD3BC7D8`）
- ML Formal readiness（既有 baseline readout）：`C:\Users\archi\AppData\Local\Temp\ml-formal-input-readiness-20260828.json`
- Runtime readiness：2026-08-28T06:32:33Z 以 `scripts/inspect_runtime_environment_readiness.py --format json` 在一般 host context 重跑；overall=`ready`、`write_probe=os.access_plus_existing_handle`、diagnostics=`[]`。同日 06:58:30Z 另在 OS TEMP 的明確 staging 目錄執行 `--confirm-write-probe`：`file_write_succeeded=true`、`sqlite_write_succeeded=true`、`registry_transaction_succeeded=true`、`cleanup_succeeded=true`；正式 Registry 仍未被寫入。
- QA Equal Weight preview：`D:\Min\Python\Project\FA_Data\output\qa\readiness_refresh_20260828\paper_equal_weight_preview.sqlite`
- Paper Equal Weight output：`D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_equal_weight_benchmark.sqlite`（21 筆；research-only benchmark，不是成交帳）
- Equal Weight workflow service：`app_module/paper_equal_weight_benchmark_builder.py`；Portfolio UI 入口為持倉管理 > Paper Portfolio >「預覽／建立 Equal Weight」
- Paper weekly evidence（2026-08-24..2026-08-28，唯讀正式 SQLite）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_weekly_20260828.json`（status=`not_configured`、snapshot／benchmark=`5/5`、cost records=`0`、weekly=`not_computable`、SHA-256=`488F86D7B274EF832559DD0D2EFA49ED997560798069C61383AFA1E0FB86BA6`）
- Paper fills template（只產生欄位，不建立 ledger）：`C:\Users\archi\AppData\Local\Temp\technical_analysis_paper_weekly_20260828\paper_trade_fills_template.csv`（row count=`0`、SHA-256=`0B6284E2869DA7958B4C4C0A28EBD083665F1998726DBCA257FE819068F70D96`）；下一步需填入真實受控 execution event，再走 CSV preview／hash revalidation／confirm append。
- Technical worker recovery／取消與 parent single-writer integration staging：`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\technical_worker_recovery_20260828.json`（SHA-256=`983FDEB4C1829137857F49513463BA48579910BF5A3882B73260F096F0454A8D`）；real calculator 2/2 stock groups、crash=`BrokenProcessPool` 後 recovery 120 rows、queued cancellation 6 筆、parent 依序寫 240 rows CSV／SQLite、SQLite lock/retry 通過、all checks 通過；`production_single_writer_integration.status=staging_measured`、scope=`isolated_staging`，production worker 仍關閉
- Broker real HTTP canary：`C:\Users\archi\AppData\Local\Temp\technical_analysis_performance\broker_real_http_canary_20260828.json`（SHA-256=`5532F53BDE0C86B4A8983B766DA46AF45D5DF53D893EAEE0F70797F22A48E83C`）；`1030_1030`／`2026-08-28`／`lots` 單一 GET 解析 100 rows，Selenium 未啟動，正式 writer／SQLite 均未寫入。這只證明當次來源可讀與 parser 可用，不代表長期 rate-limit、授權、Selenium fallback 或 production pool。

## 安全邊界

本次沒有把任何 candidate source 升格為 accepted／limited，沒有把 QA benchmark 當正式績效，沒有從既有 snapshot 補造 Paper fills，沒有回填 prospective Formal evidence，也沒有開啟 ML training、promotion、production scheduler 或 broker。正式 source、Paper execution 與 Formal clock 仍各走自己的 append-only／PIT 契約。
