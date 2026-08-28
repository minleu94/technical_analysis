# Program Readiness Audit — 2026-08-28

## 結論

程式可以持續推進，而且原先六項 blocker 中有三項是舊投影或不完整診斷，不是資料真的不存在：P0 已取得 `13/13` 來源候選證據、Evidence Gate 已是 `3/3`、正式路徑的既有檔案 write-handle probe 在一般 host context 已通過。現在真正不能由程式自動補造的，只剩具名來源接受決議、真實 Paper execution evidence，以及必須隨 prospective clock 累積的 Formal inputs。

這仍不是完整產品 closeout。Data Update 的第一個 read-model slice 已把明確指定的 live audit route／fallback／publication-PIT／治理狀態投影到同一個唯讀畫面；Paper benchmark 建置入口已完成，但成本後週報與 ML Formal lane 仍尚未可計算。正確做法是繼續完成可工程化部分，同時把外部輸入與時間證據獨立追蹤，不再把兩者統稱為「功能沒做完」。

本輪已用 `clock:prospective:20260828:v1` 的實際官方 staging 在隔離 TEMP output
完成一次 activation dry-run：PIT、Rule、simulated Portfolio 三個 producer 均能各自產出
prospective manifest，strict readiness 也能產出；所有產物仍保留
`prospective_formal_simulation`／`prospective_only` lane，沒有寫入正式 `BALDR_ML_FORMAL_*`
path，也沒有取得 Formal `3/3` credit。這證明目前的資料與 producer 路徑可運作；剩餘缺口是
下一個有效 clock 的自然累積與 owner-controlled formal publication，不是把兩套 schema 直接改名。

## 目前真實狀態

| 區域 | 先前觀感 | 2026-08-28 實測 | 真正剩餘缺口 | 可否繼續推進 |
|---|---|---|---|---|
| P0 來源 | `13 contract_only`、像是全部沒資料 | live audit=`1 verified / 12 degraded / 0 missing`；Control Center=`0 contract_only`；13 個來源共 27 條候選 route，全部都有至少 2 條 route | 12 項 publication／decision-time provenance、13 項具名 owner/reviewer decision 與 license/use-case 證據；`accepted=0`、`limited=0` | 可以；資料取得與 governance 分流推進 |
| Evidence Gate | weekly `0/3` | owner-approved weekly projection=`3/3`；multi-day dry-run=`3/3`；Pre-V2=`ready` | 另有 8 個 pending-human-review sidecar 期間；此 projection 不授予 Formal credit 或 production scheduler | 可以；Gate 顯示已修正，後續只累積真實週期與審核 |
| Paper Portfolio | 只有 snapshot、週報不可算 | 21 筆 Paper snapshot；正式 Paper output Equal Weight ledger 21 筆，benchmark reader=`ready`；UI／CLI 已有受控 preview→confirm 建置流程 | 真實 fill／partial-fill／reject／override、Decimal 成本、turnover、execution gap；Paper Trade Ledger 缺失 | 可以；benchmark 已建立，execution evidence 不可推造 |
| Formal／ML | formal input `0/3` | 仍是 `0/3`；隔離 dry-run 已驗證三個 prospective producer 可產出，但正式受控 manifest path 仍不存在 | causal portfolio ledger、rule champion history、可供該 validator 使用的歷史 PIT sector membership；prospective wrapper 不可直接消費 | 可以工程化累積；不得拿 2026-08-25 之後的 prospective sector coverage 回填歷史 |
| Runtime | 只有 `os.access` 提示 | 一般 host context 對既有 `config.log`／Research Registry 的零位元 write-handle probe 通過，overall=`ready`；隔離 staging probe 已能以正式 Registry schema 完成 insert／讀回／rollback／清除 | 正式 Registry 本身仍未做實寫；production ACL／鎖定仍需 owner 在正式環境確認 | 可以；路徑 ACL 不是目前 blocker，schema transaction 能力已可在非正式 staging 驗證 |
| 效能工程 | 尚未設計 | 既有 batch backtest、optimizer 與部分 TPEX refresh 已有受控平行化 | 券商來源 rate limit／retry／Selenium 邊界；技術指標 process pool＋SQLite/CSV single writer 設計 | 可以；先量測、再做 bounded worker 與 single-writer，不直接拉高 thread 數 |
| Data Update 顯示 | 卡片／頁面狀態容易互相矛盾 | fail-closed 顯示、台灣市場日期、候選分頁、inline summary、P0 13 列唯讀 projection 與 Research Console 共用欄位已接上；另新增 `data-update-timeline.v1`，明確顯示排程 run、最後成功完成時間、12 個步驟結果與 freshness 狀態 | 目前只投影固定的 `latest_status` 出口，尚未建立 append-only capture history；缺失、格式錯誤、失敗、執行中與過期已分開顯示，不會以 DB mtime 或舊卡片冒充成功 | 可以；下一步可在受治理 artifact 到位後接續 live refresh／capture history，不應掃描目錄或繞過 candidate-only 邊界 |

## P0 多路徑取得結果

新增 `p0-source-acquisition-routes.v1`，固定 13 個來源分母與 27 條受治理候選 route；每個來源至少兩條 route。已直接接上三條 live fallback：

- TDCC legacy CSV 失敗時改走 `https://openapi.tdcc.com.tw/v1/opendata/1-5`。
- TWSE 月營收 OpenAPI 失敗時改走 MOPS `t187ap05_L.csv`。
- TPEx 月營收 OpenAPI 失敗時改走 MOPS `t187ap05_O.csv`。

漲跌停鎖死來源已由不相符的 `MI_INDEX` 改為官方 `TWT84U`。本次 `TWT84U` 原始 1,377 列、鎖死事件 0 列；這表示該交易日沒有符合條件的事件，不是 schema 或 endpoint 失敗。

本次 live audit 的主要 row count 為：除權息 271、減資／分割 2、停復牌 1、處置 4、分盤 4、全額交割 10、三大法人 18,307、信用交易 1,295、TDCC 68,578、TWSE 月營收 1,085、TPEx 月營收 890；MOPS 季報 availability artifact 通過驗證。所有 route 仍固定 `candidate_evidence_only=true`、`formal_eligible=false`、scheduler／production ingestion 關閉。

所以 `contract_only` 的正確解讀是「Control Center 沒有載入 audit」，不能再解讀為「沒有資料」。載入本次 audit 後，真實治理狀態為 `12 blocked_provenance + 1 research_shadow`，人工 decision 為 `13 not_supplied`。

## 為什麼有些東西不能直接補滿

1. **Owner／license decision 是權限事實，不是資料欄位。** 程式可以蒐集官方 endpoint、條款 URL、hash、coverage 與 PIT 證據，但不能冒用具名 reviewer 作出 `accepted`／`limited` 決議。
2. **Paper fills 是執行事實。** 現有 `trades.jsonl`、virtual order trace 或每日 NAV 不能反推出真實 partial fill、reject、滑價、手續費與 override；硬轉換會製造不存在的績效證據。
3. **Formal clock 是時間事實。** 2026-08-25 的 prospective sector membership 有 1,932 列，但只證明該日起的前景 coverage；把它套回更早日期會造成 look-ahead。現有 historical ML validator 拒絕該 prospective schema 是正確的 fail-closed。
4. **Runtime staging transaction 不是正式 Registry 實寫。** Probe 現在會在非正式暫存 DB 使用正式 Registry schema，驗證 insert／讀回／rollback／清除；這排除了「程式完全沒有 transaction 路徑」的疑問，但仍不能宣稱正式 Registry 的 ACL／鎖定／production 實寫已成功。

## 持續推進順序

1. 將 live P0 audit、actual route、fallback reason、publication/PIT class 與 owner decision 投影接進 Data Update／Research Console，同時保留 candidate-only 安全邊界。（Data Update 的唯讀 projection 已完成；後續補 artifact refresh／capture history。）
2. 以 5 組 owner packet 完成 13 項 source 的 license/use-case/reviewer 決議；可先 `limited`，不必等待全部來源一次 accepted。
3. 將 QA Equal Weight builder 納入明確受控的 Paper benchmark 建置流程（已完成 CLI／UI 共用 preview→confirm 與不可覆寫 ledger）；由真實 paper execution producer 或使用者提供完整 fills CSV，建立 Paper Trade Ledger 後才計算成本後週報。
4. 保持 prospective publisher 與歷史 ML validator 的 schema 分離；讓 portfolio ledger、rule history、PIT sector 三個 manifest 自下一個有效 clock 起自然累積，並用 readiness inspector 的 lane／schema 診斷避免把 shadow bytes 誤接到正式 consumer。
5. 先量測 broker／technical indicator 各階段耗時、限流與 write contention，再實作 bounded worker＋single-writer queue。
6. 完成整個 Update 使用流程的 live UI QA：成功、官方無資料、fallback、schema mismatch、network failure、資料落後與 governance blocked 都要有不同且一致的顯示。

## 本次程式與證據

- 多路徑 registry：`data_module/p0_source_acquisition_routes.py`
- 官方 parser：`data_module/p0_official_source_parsers.py`
- live probe／fallback：`scripts/update_phase3c_candidates.py`
- P0 evidence audit：`scripts/run_p0_source_evidence_audit.py`
- candidate audit：`scripts/run_p0_candidate_audit.py`
- live audit：`C:\Users\archi\AppData\Local\Temp\p0-source-evidence-audit-20260827-multiroute.json`
- Control Center：`C:\Users\archi\AppData\Local\Temp\p0-source-control-center-20260827.json`
- Evidence readiness：`C:\Users\archi\AppData\Local\Temp\pre-v2-readiness-20260828.json`
- ML Formal readiness：`C:\Users\archi\AppData\Local\Temp\ml-formal-input-readiness-20260828.json`
- Runtime readiness：2026-08-28T04:12:24Z 以 `scripts/inspect_runtime_environment_readiness.py --format json` 在一般 host context 重跑；overall=`ready`、`write_probe=os.access_plus_existing_handle`、diagnostics=`[]`（CLI 唯讀輸出，未建立 probe artifact）。另以 isolated staging test 驗證正式 Research Run Registry schema 的 insert／rollback probe；正式 Registry 仍未被寫入。
- QA Equal Weight preview：`D:\Min\Python\Project\FA_Data\output\qa\readiness_refresh_20260828\paper_equal_weight_preview.sqlite`
- Paper Equal Weight output：`D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_equal_weight_benchmark.sqlite`（21 筆；research-only benchmark，不是成交帳）
- Equal Weight workflow service：`app_module/paper_equal_weight_benchmark_builder.py`；Portfolio UI 入口為持倉管理 > Paper Portfolio >「預覽／建立 Equal Weight」

## 安全邊界

本次沒有把任何 candidate source 升格為 accepted／limited，沒有把 QA benchmark 當正式績效，沒有從既有 snapshot 補造 Paper fills，沒有回填 prospective Formal evidence，也沒有開啟 ML training、promotion、production scheduler 或 broker。正式 source、Paper execution 與 Formal clock 仍各走自己的 append-only／PIT 契約。
