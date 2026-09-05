# Program Status Rebaseline — 2026-08-29

## 結論先行

目前程式不是「核心都沒做」，而是**工程平台已相當完整，產品 Gate 尚未收口**。
主 UI、資料更新、研究、回測、Paper／Evidence／ML shadow 的受控入口與大量 fail-closed
檢查都已存在；本輪 HEAD 完整回歸為 `3,826 passed / 1 skipped / 26 warnings`
（共收集 `3,827` tests，耗時 552.80 秒）。
但真正能讓產品
從候選／影子／紙上狀態進入正式可用狀態的 owner 決策、真實 fills、正式輸入與 production
canary 尚未齊，因此整體正確狀態仍是 `action_required`，不能以畫面或測試數量宣稱完成。

2026-08-28 的 6.11 GiB 容量阻擋已由使用者授權的 retention cleanup 解除；8/30 fresh
唯讀 inventory 為 `headroom_ok`、D 槽可用約 `338.9 GiB`。這只移除 performance lane
的一個實體前置問題，不會替 P0、Evidence、Paper 或 Formal/ML 補出外部事實。

2026-08-30 P0 continuation 已完成一次 bounded 官方唯讀 retry；完整 artifact custody、
`official_no_data` 與 owner handoff 見 [P0 Evidence Refresh](P0_EVIDENCE_REFRESH_2026_08_30.md)。
本次不改寫 8/29 rebaseline 的其他 lane，也不把 request-date no-data 解讀成來源永久缺失。

同日 Evidence sidecar 也追加自然 collection，pending record 由 9 筆增為 10 筆；唯讀
approval input 與不授權邊界見 [Evidence Weekly Approval Refresh](EVIDENCE_WEEKLY_APPROVAL_REFRESH_2026_08_30.md)。

本輪 Runtime／Performance 也完成 fresh read-only recheck：TEMP 寫入 probe 通過、正式
Registry 與單股 technical canary 仍停在 `confirmation_required`；D 槽 headroom 已恢復，
Direct/OOC 只做 `preflight_only`，沒有啟動 chain。完整 artifact custody 見
[Runtime Performance Readiness Refresh](RUNTIME_PERFORMANCE_READINESS_REFRESH_2026_08_30.md)。

以本輪最新 artifacts 重建 unified readiness=`program_readiness_current_20260830.json`，
SHA-256=`5229F27373B0CF83E875E4B05D2867121D9E16D18813E91529C337F545720F6E`；overall=`action_required`，
Runtime／Update History=`ready`，Performance=`partial` 且只剩
`technical_production_single_writer_canary_not_completed`。報告因仍有真實 blockers 回傳 exit 2，
但 JSON 產出成功；不能把這個 exit code 誤讀成 collector／UI 失敗。

## 判讀基線

- Repository HEAD：`3c663ac7b5ecbfabcbe79ee1a2ac253d09b16e61`
- Git branch：`dev`
- 前一完整 pytest checkpoint：`3,820 passed / 1 skipped / 26 warnings`；發生在
  `e58a573` raw-PIT low-space guard 前，不冒充目前 HEAD 的完整結果
- 目前 HEAD collect-only：`3,827 collected`
- 目前 HEAD focused readiness／runtime／data／Paper／Formal／performance regression：全綠
- 目前 HEAD 完整 pytest：`3,826 passed / 1 skipped / 26 warnings in 552.80s`；無
  collection error／test failure。警告為 joblib physical-core fallback、既有推薦組合回測的
  理想化同日收盤成交假設，以及 sandbox 無法更新 `.pytest_cache`；後者不影響測試判讀
- 最近 unified readiness current artifact：
  `program_readiness_current_20260830.json`，
  SHA-256=`5229F27373B0CF83E875E4B05D2867121D9E16D18813E91529C337F545720F6E`，
  overall=`action_required`
- 8/30 fresh storage inventory：
  `ml_storage_retention_inventory_20260830.json`，
  SHA-256=`320026E804C2C5AF546AE31167848E5BD879AD03544E2C452EE0E708CC2B2CF5`，
  status=`headroom_ok`；D 槽可用約 `338.9 GiB`

早期 unified readiness 產生於 cleanup 前，故其中 `direct_chain_storage_preflight_blocked`
只代表歷史輸入；本輪以較新的 read-only inventory 與 `preflight_only` artifact 重新判讀
實體容量，不手改舊 artifact，也不把整個 performance lane 升格為 ready。

## Canonical lane 狀態

| Lane | 已有的工程／證據 | 目前正確狀態 | 真正缺口 | 可否持續推進 |
|---|---|---|---|---|
| P0 Data Sources | 13/13 machine rows；8/30 retry=`1 verified / 9 degraded / 3 official_no_data`；3/3 官方條款頁 candidate 已取得；多路徑 acquisition、row conservation、owner packet 與 UI projection 已建立 | `action_required`；accepted=`0`、limited=`0`、downstream eligibility=`none` | 逐來源 publication／coverage／missingness／license／PIT available-date 與具名 owner 決議；3 個 request-date no-data 待自然交易日重試 | 可以；先做 owner/legal/PIT acceptance，不必再把所有問題當成「沒有抓到資料」 |
| Evidence Gate | canonical formal DB 未取得正式 Gate credit；歷史 working-copy Week 1=`1/3`；owner-approved UI projection=`3/3`；正式 sidecar pending=`10`；multi-day dry-run=`3/3` | `partial`；`formal_credit_authorized=false`、production scheduler disabled | 具名 reviewer 逐期裁決、正式 credit／approval package、backup／rollback／recovery 與自然 scheduler history | 可以；review 與 approval 可持續，不能用 replay 或只改數字補 credit |
| Paper Portfolio | 21 snapshots、21 Equal Weight observations；8/30 latest daily status=`skipped_non_trading_day`（合法週末，latest snapshot=`2026-08-28`）；execution import／reconciliation contract 已建立 | `partial`；ledger missing、fills=`0`、cost records=`0`、weekly=`not_computable_cost_ledger_missing` | 真實 producer fills、partial-fill／override、Decimal commission／tax／slippage、turnover／execution gap | 可以；先提供真實成交來源，接著走 preview→hash recheck→explicit confirm，再跑成本後週報與 UI QA；空白範本與本次 reconciliation 修正見 [Paper Portfolio Readiness Refresh](PAPER_PORTFOLIO_READINESS_REFRESH_2026_08_30.md) |
| Formal / ML | PIT／Direct／OOC immutable chain、shadow stores、owner packet、strict validator 與 promotion safety 已建立；8/30 strict validator 重驗仍為 `0/3` | `action_required`；owner-controlled inputs=`0/3`、`clock-20260819` path 未發布且早於 cutoff、`formal_oos_allowed=false`、alpha=`0` | causal non-cash portfolio ledger、formal Rule Champion history、PIT sector membership 三份 owner-controlled manifest | 可以；先由 owner-controlled publisher 發布三份新 input，再以 strict validator、replay、calibration、drift 與 promotion evidence 逐層推進；本次原因與 hash 見 [Formal Input Readiness Refresh](FORMAL_INPUT_READINESS_REFRESH_2026_08_30.md) |
| Runtime | environment／existing-handle probe ready；TEMP actual ephemeral write／SQLite／Registry transaction=`passed`；正式 Registry read-only clone `quick_check=ok`、98 rows | `runtime_environment_ready`；正式 canary=`confirmation_required`，不是 production writer ready | 正式 Registry insert／read-back／rollback canary 仍未執行 | 可以；需 owner 確認無並行 writer 後做單次 guarded canary |
| Data Update / History | 8/30 quick run 12/12 passed；core freshness 至 2026-08-28；週末日期語意修正後 timeline=`current`；status history、timeline、手動 run 摘要與 fail-closed UI 已接線 | `ready`（最近 host observation） | TPEX path 未設定；readiness card 會對比明確 reference path 並標記較舊 artifact，仍不自動替換；後續只累積自然 history | 可以；優先刷新觀測與顯示一致性，不重播補歷史；修正詳見 [Data Update Display Refresh](DATA_UPDATE_DISPLAY_REFRESH_2026_08_30.md) |
| Performance / Concurrency | technical process-pool／recovery／parent single-writer staging 已量測；broker bounded real HTTP 已量測；PIT／Direct／OOC current runs=`8/9/9`；fresh inventory=`headroom_ok`；`preflight_only` 已驗證 | `partial`；容量不再阻擋，但 technical canary、broker pool 與 owner review 仍未完成 | technical production backup／rollback single-writer canary；broker long-term rate-limit／serialized fallback／production writer review；長 chain 需另行核准 | 可以；先審核 packet／canary guard，不能只把 thread 數拉高或因 headroom_ok 自動啟動 |

## 使用者可見工作區盤點

下表的「可用」是指入口與受控研究流程可操作，不等於對應產品 Gate 已 closeout。

| 工作區 | 工程可用性 | 目前仍像半成品的原因 |
|---|---|---|
| 決策工作台 | read-only dashboard、Action Items、Operating Loop 與跨頁 drill-down 已接線 | 多數動作是導覽／人工交接；Evidence／Paper／Formal 的外部 Gate 未完成時，畫面必須持續顯示 pending／degraded |
| 市場探索 | 市場總覽、產業／強弱／流動性／籌碼與每日決策唯一實例可用 | P0 source 雖 13/13 有 machine evidence，publication／PIT／license 尚未 accepted，部分資料只能降級判讀 |
| 推薦分析 | Gate 1 bounded Advice、Why／Why Not、Profile、候選保存與 Research handoff 可用 | 這是研究候選，不是投資有效性；不能因推薦結果存在就解除 Evidence、Paper 或 Formal Gate |
| 策略回測／Research Lab | 單股、批次、組合、walk-forward、Registry／比較與治理檢查可用 | 既有推薦組合回測仍有「同日收盤訊號同日收盤成交」理想化警告；Formal OOS 與成本後 Paper evidence 尚未成立 |
| 觀察清單 | 候選管理與跨頁 handoff 可用 | 只保存人工觀察池，不會自動成為持倉、訂單或策略 lifecycle 決議 |
| 持倉管理 | 手動交易／CSV preview-import、持倉投影、監控、壓力情境與研究快照可用 | Paper 只有 21/21 snapshot／benchmark；真實 fill producer、成本 ledger、partial-fill／override／execution gap 缺失 |
| 數據更新 | 8/30 quick run 12/12、freshness 至 2026-08-28；timeline 已修正週末檢查日誤判並顯示 `current`；進度、history、no-op 與 fail-closed card 已接線 | TPEX path 尚未設定；部分 readiness card 仍可能由 explicit path 載入 cleanup 前 artifact，需依 generated-at／source path 判讀 |
| Runtime | 治理事件、health、read-only environment／clone proof 可檢視 | 正式 Registry transaction／rollback canary 未執行；UI ready 不能解讀為 production writer ready |

因此目前最主要的問題不是「八個頁面都沒有做」，而是介面已把未完成 Gate 真實呈現出來，
同時缺少一個足夠清楚的 current-vs-historical 狀態層。這次文件 rebaseline 已先修正文義；
程式面的下一個顯示改善應是所有 readiness card 一律帶 `generated_at`、source path 與 superseded
提示，避免舊 artifact 看起來像即時狀態。

## 為什麼畫面仍像半成品

1. **UI 同時呈現產品能力與 Gate 診斷**。許多頁面已能打開、查詢或預覽，但輸出刻意標成
   candidate／shadow／paper／not-computable；這是防止缺資料時假裝完成，不是單純漏接按鈕。
2. **工程 readiness 與產品 closeout 長期混寫**。舊 Snapshot／Roadmap 依日期追加大量
   checkpoint，讀者容易把某次 `ready`、`0/3`、`1/3` 或容量狀態當成現在。
3. **外部事實不能由程式自行創造**。授權接受、PIT publication、人工 review、真實 fills、
   正式 owner-controlled manifest 與 production approval 都需要具名來源或真實事件。
4. **部分 current projection 仍指向舊 artifact**。尤其 cleanup 後，舊
   `ml-direct-chain-maintenance-status.v1` 仍忠實保存當時 `blocked_insufficient_storage`；
   若 UI 載入 cleanup 前的 `PROGRAM_READINESS_ARTIFACT`，仍會看到過期容量 blocker。
5. **產品缺口不是同一種補資料問題**。P0 是治理與來源接受；Evidence 是時間與 review；
   Paper 是 execution event；Formal 是受控發布；Runtime／Performance 是 production canary。

## 已完成與未完成的邊界

### 可以視為已完成的工程基礎

- Gate 0 Safe Refactor closeout 與 Gate 1 bounded Daily Usable Advice formal closeout。
- PySide6 主 UI、八個主要工作區、資料更新、推薦、回測、Portfolio、Research、Runtime
  的主要操作入口。
- SQLite-first／query-only read paths、Decimal／整數 bp 防線、look-ahead guards、
  append-only evidence／registry contracts、status history 與大量回歸測試。
- P0 candidate acquisition、Evidence／Paper／Formal owner handoff、ML shadow chain、
  technical staging concurrency 與 broker bounded fetch 的工程形狀。

### 不能視為完整產品 closeout

- Gate 2 Evidence 正式 credit 與 production scheduler approval。
- Gate 3 P0 逐來源 accepted／limited／rejected／deferred 決議。
- Gate 4 Paper 成本後 Portfolio／Equal Weight 比較與 execution realism。
- Formal OOS／ML promotion、非零 alpha、production ML adapter。
- production Registry／technical writer canary、broker production pool／orders。
- 長期 forward／paper／live evidence 所要求的投資有效性、pruning 與 V4.0 maturity。

## 推進順序

以下工作可並行，但 Gate 不應跳級：

1. **P0 governance**：用現有 13 列 owner packet 逐項補 publication／coverage／license／PIT
   證據，取得 accepted／limited／rejected／deferred 決議。
2. **Evidence review**：把 formal DB、歷史 working-copy、3/3 projection 與 10 筆 pending
   sidecar 分層呈現；由具名 reviewer 完成裁決後，再評估 formal credit 與 scheduler approval。
3. **Paper execution**：由 Paper producer／broker export 真實 fills，先 reconciliation，
   再走 preview → source hash recheck → explicit confirm append；建立成本後 weekly report。
4. **Formal publication**：發布 causal ledger、Rule history、PIT sector 三份 expected-schema
   manifests，重跑 strict readiness；通過前維持 shadow-only、alpha 0。
5. **Production canaries**：容量已足夠後，分別執行 Registry transaction／rollback 與單股
   technical backup／rollback canary；仍不等於啟用長期 writer。
6. **顯示一致性**：已用 `--preflight-only` 產生 fresh Direct/OOC capacity status；下一步重建
   unified readiness projection，並讓 UI 顯示 artifact generated-at／source path，避免新舊
   狀態混讀。

## 本輪文件整理決策

- `PROJECT_SNAPSHOT.md` 頂部新增單一 canonical lane table；舊逐日工程紀錄保留為歷史證據。
- `DEVELOPMENT_ROADMAP.md` 回復 Hub 職責，只在頂部提供 current Next，舊 activation
  checkpoint 明示為歷史。
- `ROADMAP_6M_ENGINEERING.md`、Version Roadmap 更新 Gate 現況，但不改 maturity 定義。
- Current Architecture 補上 immutable ML artifact retention／pointer／tombstone 邊界，
  並區分 runtime environment proof 與 production transaction proof。
- Application Manual 補上人工 cleanup SOP、current Evidence／Paper 判讀與 stale status 排錯。
- Documentation Index、Coverage Map 與既有 readiness audit 加入本 rebaseline／cleanup 入口。
- Product Roadmap、Target Architecture、Legacy Carryover 的方向與 scope 未因本次 cleanup 改變，
  不加入容量流水帳。

## 安全邊界

本次 rebaseline 沒有啟用 scheduler、broker、Formal OOS、非零 alpha 或 production writer；
沒有將 owner packet、projection、replay、Paper snapshot 或 retained ML run 升格成正式 Gate
credit。Storage cleanup 的完整範圍、保留鏈與不可逆性見
[ML Release v4 Storage Retention Cleanup](ML_RELEASE_V4_STORAGE_RETENTION_CLEANUP_2026_08_29.md)。
