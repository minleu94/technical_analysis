# PROJECT_SNAPSHOT（必讀｜每次開新對話先看）

> **開場 30 秒內讀完** - 只放今天的狀態，不放歷史細節

## 系統定位（一句話）

這不是每天吐股票的工具，而是一個可驗證、可回溯、可演化的投資決策系統。

## 當前狀態（以 DEVELOPMENT_ROADMAP.md 的 Living Section 為準）

> **注意**：Living Section 定義見 `DEVELOPMENT_ROADMAP.md` 的「📍 Living Section 定義」段落。

- Phase 1 ✅ / Phase 2 ✅ / Phase 2.5 ✅ / Phase 3 ✅（核心研究閉環與 CSV 手動匯出已完成）
- Phase 2A, 2B & 2C SQLite DB-first 讀取改造與視覺化 Table 檢視 ✅（盤點主讀 CSV 處改為 SQLite 優先，並提供防禦性 SELECT 唯讀 SQL 視覺化檢視面板）
- Phase 3.1 ✅ / Phase 3.2 ✅ / Phase 3.3b ✅（研究閉環已完成，含 Promote / Walk-forward / Baseline / Overfitting risk / 視覺驗證）
- AI Runtime Subsystem MVP ✅（Governance-aware 狀態機監控站已完成）
- Smart Money Terminal MVP ✅（高密度、低延遲的專業級籌碼分析終端已完成）
- UI Qt Backtest chart renderer ✅（QtWebEngine + HTML5 Canvas fast renderer 已完成，Matplotlib fallback 保留）
- Recommendation Portfolio Backtest MVP ✅（推薦 Profile/Config 可在歷史日期重播，回測整組推薦組合績效與個股貢獻）
- 數據更新工作台 ✅（`UpdateView` 已整理為左側導覽維運工作台，新增「安全更新所有數據」日常維護入口）
- Codex / Antigravity / Agent 指引 ✅（repo 根目錄 `AGENTS.md` 與 `GEMINI.md` 已建立，`docs/agents/` 與 `.agent/rules/` 已對齊目前 `ui_qt`、資料根目錄與文檔路徑）
- Phase 4.1 Portfolio MVP 🚧（service/domain/test 骨架已開始；`ui_qt` Portfolio Tab 與 Phase 3 → Portfolio 整合尚未完成）

## 現在的工作模式（你每天要用的流程）

1. Update 使用「安全更新所有數據」或左側資料來源頁更新資料
2. Market Watch 看 Regime + 強弱
3. Recommendation 用 Profile 出名單 + 看 Why/WhyNot → 丟 Watchlist，或送「推薦組合回測」
4. Backtest 可跑 Watchlist/現有名單批次回測，也可用歷史重播推薦邏輯評估整組推薦組合

## Tech Lead 的預設任務（開場要先做什麼）

- 給出「下一步最合理的工程行動」與原因（不寫 code）
- 如需看程式碼：先提出要 review 的檔案清單與目的，等我授權 scope

## 本週優先事項（只列 3 個）

1. 補強推薦組合回測的穩健分析指標（Sortino、Sharpe、Monte Carlo）與結果可讀性
2. 評估將回測最佳 Profile/Config 回灌推薦頁，形成可優化的推薦系統
3. 保持 Roadmap / Snapshot / Documentation Index / UI docs / Agent docs 一致

## 高風險區（改動需謹慎）

- `app_module/backtest_service.py` / `backtest_module/*`
- `app_module/recommendation_service.py`
- `app_module/recommendation_replay_service.py` / `app_module/recommendation_portfolio_backtest_service.py`
- Strategy registry / preset / promotion 相關服務
- UI ↔ service contract（DTO）
- `runtime/` 核心子系統與 FSM 狀態機
- `ui_qt/widgets/fast_chart_widget.py` / `ui_qt/widgets/chart_payloads.py`（回測圖表 renderer 與資料 payload contract）
- `ui_qt/views/update_view.py` / `app_module/update_service.py`（數據更新工作台與安全更新流程）

## 指定權威文件（需要細節再看）

- `DEVELOPMENT_ROADMAP.md` - 完整開發路線圖（Single Source of Truth）
- `DOCUMENTATION_INDEX.md` - 文檔索引
- `DOCUMENTATION_STRUCTURE.md` - docs 資料夾歸屬、生命週期、刪除/歸檔規則
- `DOC_COVERAGE_MAP.md` - 文檔覆蓋矩陣（Documentation Agent 判斷 coverage 的規則）
- `PROJECT_NAVIGATION.md` / `PROJECT_INVENTORY.md` - 專案導航與盤點

---

**注意**：此 Snapshot 內容從 `DEVELOPMENT_ROADMAP.md` 的「Living Section」（定義見該文件的「📍 Living Section 定義」段落）與 `DOCUMENTATION_INDEX.md` 抽出的短版入口。詳細資訊請參考權威文件。

 
## 2026-05-27 補充狀態

- Recommendation Portfolio Backtest 已開始補強穩健性分析：目前已加入 Sharpe Ratio、Sortino Ratio 與 Monte Carlo P05/P50/P95 模擬報酬，並顯示在 Backtest 的「推薦組合」總覽。後續若要再深化，下一步是做 rolling Sharpe/Sortino、VaR/CVaR 或更完整的 metric/factor layer。
- Recommendation Portfolio Backtest 的 portfolio value 已改為每日 mark-to-market，Backtest「推薦組合」結果頁新增 Portfolio Value / Drawdown 圖表，並會嘗試載入大盤基準線做比較；目前停損/停利與策略學習閉環尚未納入推薦組合路徑。
- Recommendation Portfolio Backtest 已接入停損 (%) / 停利 (%) 提前出場，並在結果總覽顯示出場原因統計、虧損交易占比與最拖累股票；策略版本儲存與自動學習閉環仍待下一步。
- Recommendation Portfolio Backtest 已新增獨立 research run 保存庫，可保存/載入/刪除推薦組合回測結果，產生 rule-based 改善建議，並可將通過最低條件的推薦組合 run 升級為策略版本；此保存模型與一般單股 BacktestRunRepository 分離。

## 2026-05-30 SQLite 儲存、Bug 修復與全量技術指標重算升級成果

- **SQLite 資料庫儲存升級與全量遷移 (research/sqlite-storage) 圓滿完成**：已成功在分支上完成 CSV 到 SQLite 升級與無縫向後相容層重構。
- **大盤指數與日期標準化 Bug 完美修復**：修復了西元年無補零被民國年錯誤加 1911 的解析大 Bug（產業指數結束日期完美修正為 `2026-05-29`，無任何髒數據）；修復了大盤指數 KeyError Bug，成功導入 **3,008 筆** 歷史加權指數記錄（覆蓋 `2014-01-02` 至 `2026-05-29`）。
- **技術指標全量重新計算並高速寫入 SQLite**：重構了指標計算腳本與 UI 服務層，成功執行一鍵全量指標重新計算（1,157 檔個股，僅耗時 1 分 51 秒），成功將 **2,802,159 筆新重算的技術指標資料** 同步批次寫入 SQLite 資料庫的 `technical_indicators` 表，數據對比 100% 精準吻合。
- **322 倍回測資料載入加速**：回測載入單股價格歷史時間由大 CSV 的 **8.37 秒** 直降至 SQLite 複合索引查詢的 **0.025 秒 (25 毫秒)**，效能飆升 **322.9 倍**！
- **UI 狀態加載毫秒級「秒開」優化**：重構 `check_data_status` 等數據狀態統計方法，當 SQLite 啟用時 100% 改由 SQL 極速聚合統計，徹底避開幾百 MB 的 CSV 硬碟掃描，數據更新 Tab 瞬間秒開。
- **UI ↔ Service 合規性 100% 通過**：通過 `test_ui_qt_update_view_workbench.py` (7/7 passed) 與 `qa_validate_update_tab.py` (21 passed, 0 failed)，系統完好無損，穩定性極佳。

## 2026-06-02 安全更新 Phase 1 DB 同步補強

- **安全更新補上 CSV → SQLite 同步鏈**：日常「安全更新所有數據」仍保留既有 CSV 下載、合併與人工檢查習慣，但會在每日股價、大盤、產業、合併每日資料與合併券商分點成功後，同步寫入 `daily_prices`、`market_indices`、`industry_indices` 與 `broker_flows`，降低 UI 狀態 DB-first 與更新流程 CSV-first 之間的分岔風險。

## 2026-06-03 SQLite DB-first 讀取改造與視覺化 Table 檢視 (Phase 2A, 2B & 2C) 成果

- **SQLite 視覺查詢資料表 (Phase 2C) 實作完成**：實作了 `SqliteInspectorService` 與 `SqliteInspectorWidget` 並將其整合至數據更新工作台中。支援資料表 Preview、欄位定義 (Schema) 檢視、自訂唯讀 SQL 執行展示、錯誤輸出、以及非同步載入防止 UI 假死，並配備嚴格的安全防禦機制（僅允許唯讀的 SELECT 查詢且強制進行 Limit 限制，防範 SQL Injection 與大數據崩潰）。
- **數據讀取 SQLite 優先 (DB-first) 圓滿完成**：重構了強勢股篩選 (StockScreener)、市場狀態偵測 (MarketRegimeDetector)、產業映射器 (IndustryMapper) 及推薦服務 (RecommendationService)，數據載入 100% 實現 SQLite 優先與 CSV 備用降級，徹底消除遍歷讀取磁碟小 CSV 的 I/O 毒瘤。
- **一鍵安全更新效能 Hotfix 完美修復**：優化了 `_date_key` 日期格式解析函數，避免在百萬行資料中因逐行呼叫 `pd.to_datetime` 造成的嚴重的 CPU 與 I/O 開銷。產業指數日期轉換由 13.19 秒縮短至 **0.136 秒** (提速 100 倍)，286 萬筆每日股價同步寫入 SQLite 僅需 **59.35 秒**。所有單元測試與 QA 驗證全部通過。

## 2026-06-03 CSV 手動匯出與更新流程優化 (Phase 3) 成果

- **停止日常更新大型 CSV 重寫**：當啟用 SQLite 時，日常安全更新直接將新下載的單日 CSV 同步寫入 SQLite 庫（包含個股價格與主力分點），跳過重寫 `stock_data_whole.csv` 與主力分點大合併 CSV 等大型檔案，避免磁碟 I/O 重擔。
- **技術指標增量同步優化**：增量計算技術指標時，略過保存 `all_stocks_data.csv`，並在同步 SQLite `technical_indicators` 表時，改為只針對有更新的 `(證券代號, 日期)` 組合進行舊記錄刪除後追加寫入，不執行全表 `DELETE`。
- **各 subtab 加入「匯出 CSV」**：在數據更新工作台的五大數據 subtab 中新增「匯出 CSV」按鈕，支援非同步匯出指定範圍或全量 SQLite 記錄至 CSV 備案，檔名與日期格式（`YYYY-MM-DD`）符合人工檢查需求，且使用 UTF-8 with BOM 避免 Excel 亂碼。
- **測試與驗證 100% 綠燈**：Pytest 與 QA 驗證全部安全通過，mypy 零新增錯誤。
