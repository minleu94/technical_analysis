# Owner Production Readiness — 2026-08-06

## 結論

目前可供 Owner 日常使用的正式範圍是：**Rule 驅動 Decision／Advice、推薦、日常資料更新、Paper Portfolio、證據保存與只讀 Runtime 監控**。這不是券商交易系統，也不代表投資績效或 ML 已正式 promotion。

本文件只記錄 2026-08-06 的實測狀態；長期產品方向仍以 `docs/00_core/PRODUCT_ROADMAP_POST_REFACTOR.md` 與 Gate registry 為準。

## Owner 功能狀態

| 功能 | Owner 狀態 | 已驗證的事實 | 不可過度解讀的邊界 |
|---|---|---|---|
| 正式市場 DB | 可日常使用 | `PRAGMA quick_check=ok`；`daily_prices=5,252,628`、`technical_indicators=5,196,894`、`market_indices=3,055`、`industry_indices=209,575`、`broker_flows=862,859`。 | 資料可讀與完整性正常，不等於每個歷史來源都已有 PIT／授權證明。 |
| 日常資料更新 | 可日常使用 | `data_update_quick` 與 `data_freshness` artifact 為 `passed`；日價與技術資料當日 age=0。 | Scheduler artifact 不等於 Windows task 已註冊／執行／`Last Result=0`；需用 `scripts\scheduled\query_baldr_scheduled_tasks.cmd` 判定。 |
| Daily Decision／Advice | 可日常使用 | Rule lane、Decision Evidence 及 Recommendation snapshot 都有成功 artifact；推薦快照保存 7 個候選、200 列 screening matrix、193 列 Why Not／排除資訊。 | Action 是 Owner 判讀用建議，不是券商委託或績效承諾。 |
| Paper Portfolio | 可日常使用 | 最新 daily artifact 為 `passed`；3 檔持倉、現金 `341000.00`、總值 `488700.00`，市場 DB 固定 `ro/query_only`。 | 不送單、不自動再平衡、不代表真實成交或實盤績效。 |
| Backtest／Research Lab | 可研究使用 | Registry、回測、walk-forward 與報告保存流程仍可用，並受 T-1、Decimal／bp 與 look-ahead 防線保護。 | 研究結果不等於產品／策略有效性；需要樣本、獨立驗證與時間成熟。 |
| Portfolio／Position Health／Exit | 受保護可用 | deterministic policy、追溯、風險與監控可供 Owner 覆盤。 | 尚缺成熟 forward／Exit outcome 證據，不得宣稱 effectiveness 已驗證。 |
| Runtime Owner 監控 | 可日常使用 | 兩平面 UI：scheduled artifact 與 governance Runtime 分開呈現；實測核心 artifact `6/6` 正常、9 列狀態可呈現。 | 它不啟動／設定 task、不寫 DB、不重訓、不變更 alpha，也不取代 Scheduler 真實查詢。 |
| UI 背景工作關閉 | 受保護可用 | 主視窗與各 view 對受管 worker 只送非阻塞合作式取消；仍在執行的工作或 TPEX 子程序會暫停關閉，不再以 `QThread.terminate()` 中斷 SQLite／檔案操作。 | 不支援 cancellation token 的長工作須自然結束；Owner 需等待狀態結束後再次關閉，不能把等待誤判為更新完成。 |
| ML Co-pilot | 受保護 Rule-only | 最新狀態為 `passed_rule_only`，`production_blend_alpha_bp=0`、`formal_oos_allowed=false`、`broker_order_allowed=false`。 | `alpha=0` 是正確安全 fallback；不得人工改為非零或宣稱已 promotion。 |
| ML Promotion／OOC retrain | 訓練 custody 已完成；Promotion 受保護 blocked | 2026-08-07 OOC v5 已原子發布 `latest_manifest.json`：120 base、24 final-base、4 meta、1 final-meta artifact 均可驗證；最新 evidence pipeline 已重新產生。 | `formal_ooc_dataset_full_market_not_ready` 仍阻擋 formal replay；`production_blend_alpha_bp=0`、`formal_oos_allowed=false`、broker order disabled 不變。 |
| P0／fundamental 擴充資料 | 受控 formal／其餘 research-shadow | 2026-06 月營收 1,832 筆已通過受限 legacy 官方 mapping；新月營收／季報必須走 `formal-availability.v2`，讀取端會再核對 mapping 與 SQLite row 的五個時間／identity 欄位。 | 2026-05 first-seen 月營收 1,848 筆保留但被正式讀取 gate 隔離；缺 publication time、revision lineage、coverage、license／provenance 或 PIT 佐證者，不得導入正式 Decision／Portfolio。 |
| 券商下單／自動交易 | 不在範圍 | 全部 daily artifacts 保持 broker execution／order disabled。 | 不可由本系統自動下單、調倉或平倉。 |

## 本輪正式資料盤點

已完成 raw／SQLite／PIT／來源驗收的唯讀對帳。可無歧義安全寫入正式 DB 的剩餘 records 為 **0**；現有可接受 source data 已與正式 DB 對齊。

- 日價、技術、market index、industry index 與可接受估值資料已對齊。
- broker 原始／DB 差異含顯示名稱與 leading-zero identity 等語意差異；現有 replace-by-date sync 可能刪除 DB-only rows，因此未執行。
- 月營收、財報、三大法人、信用與 TDCC 的缺口主要是 `available_date`／來源 acceptance，而不是單純尚未匯入的檔案。
- weekend raw、malformed test CSV、release／ML output、mirror、backup 與 derived artifact 都維持隔離，未誤導入正式 DB。

下一個正式資料工作不是 bulk import，而是逐來源補齊 PIT mapping、provenance、revision lineage 與受控 only-upsert 邊界。

## Runtime Owner 監控的實作邊界

本輪 Runtime UI 將下列資料面分離：

```text
runtime/ state + append-only governance events
  -> RuntimeSnapshot / Health / EventStream services

OUTPUT_ROOT/scheduled/*/latest_status.json
  -> ScheduledOperationsStatusService
```

- core artifact 缺失、損壞或超過 36 小時時 fail-closed 為「需要注意」。
- evidence `degraded` 只有在完整 natural-maturity 證據、無 actionable／blocking gap、freshness passed 時才是「安全邊界中」。
- ML `blocked`／`passed_rule_only` 顯示為 guarded，不轉譯成 promotion。
- 歷史、未來、無法解析時間與 event log 不可讀，都不能假冒為當前 `HALTED` 或健康。
- UI 只保留本 session 後最近 500 筆事件；底層 JSONL 不會因 UI 裁切而被改寫。

使用說明與架構規則已同步於：

- `docs/07_guides/APPLICATION_MANUAL.md` 第 11 節。
- `docs/01_architecture/system_architecture.md` 第 10 節。
- `docs/01_architecture/runtime_observatory_rules.md`。

## 驗證證據

| Gate | 結果 |
|---|---|
| Runtime core focused suite | `26 passed` |
| Full App Healthcheck（full） | 11 個 bridge suites／`120 passed` |
| UpdateView required suite | `38 passed` |
| Update Tab QA | `23 passed / 0 failed / 4 skipped` |
| MyPy | `478 source files / 0 issues` |
| Test Inventory audit | 582 filesystem files／582 entries／3,051 collected tests／0 machine blockers |
| MainWindow offscreen smoke | 8 個 workspace 都存在並成功切換；navigation mode=`left_workspace_navigation` |
| Full App Healthcheck + MainWindow UI smoke | `passed`；8 個 workspace 都存在並成功切換；未呼叫禁止動作 |
| Runtime Qt end-to-end | 核心 `6/6`、9 個 scheduled status rows；治理歷史事件正確不冒充當前事故 |
| OOC v5 custody resume | 已發布 `latest_manifest.json`；149/149 artifact 雜湊可驗證；training manifest=`sha256:312df8744b81e8cadb3bc8c06b57dc416fd055ee5de9a081faf00e94ae1f3d0b` |
| 最新 ML promotion evidence | `blocked`（`formal_ooc_dataset_full_market_not_ready`）；alpha 仍為 `0` |
| 月營收／季報 provenance | availability／builder／backfill／statement focused suite `122 passed, 1 skipped`；正式 mapping 唯讀驗證 `1,832 accepted / 0 diagnostics` |
| 月營收 live read gate | provider／Recommendation YoY／Factor／governance／CLI focused suite `29 passed`；正式 DB：2026-05 `1,848 blocked`、2026-06 `1,832 admitted` |
| UI 合作式關閉 | TaskWorker／shutdown coordinator `13 passed`；Decision Desk／匯出／主力流向／回測相鄰 UI `30 passed` |
| 正式 DB | `quick_check=ok` |
| Windows Scheduler query | 11/11 task 為 Enabled／Ready，最新 `Last Result=0`；皆為 `Interactive only`、電池時不啟動／會停止 |

完整 `pytest -q -o addopts=` 曾開始執行，但 process 使本機 commit 使用量逼近 `63.8 / 65.2 GiB`，為保護正式環境而主動停止。這不是 test failure；完整 suite 仍是需在資源充足環境補跑的 release evidence。

## 尚需 Owner 或外部條件的項目

1. **ML formal promotion**：OOC v5 training custody 已完整，但 direct store 仍標示 full-market not ready；需要 PIT sector membership、可因果學習的非現金 portfolio ledger、formal replay／semantic verifier，以及自然累積的 20 個 shadow days。完成訓練不得改變 alpha。
2. **真實盤中 Formal capture**：需 Owner 在台北市場實際交易時段執行受控 Rule-only foreground producer；scheduler replay／事後資料不能取代 observed day。
3. **無人值守排程**：目前 Windows tasks 是 local interactive workflow。若要無人登入仍可靠執行，需 Owner 明確授權變更帳號、憑證、電源與 missed-run recovery 政策。
4. **資料源正式升級**：每一來源要先有可驗證 license／provenance、publication timestamp、revision lineage 與 coverage，再考慮 formal acceptance。

## 日常 Owner 操作順序

1. 使用排程 query 指令確認 Windows task 真實狀態。
2. 在資料更新與 Runtime 頁確認 freshness／artifact；遇 `attention` 先讀 diagnostic，而非直接重跑。
3. 在 Decision Desk 檢視 Rule/Advice、Why／Why Not、風險與資料品質。
4. Paper Portfolio 僅作 paper tracking；不要將其視為已送出的交易。
5. ML 保持 `alpha=0`，直到所有 promotion gate 自動產生可驗證 evidence。
