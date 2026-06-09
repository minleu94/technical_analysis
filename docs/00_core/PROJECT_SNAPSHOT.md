# PROJECT_SNAPSHOT（必讀｜每次開新對話先看）

> **開場 30 秒內讀完** - 只放今天的狀態，不放歷史細節

## 系統定位（一句話）

這不是每天吐股票的工具，而是一個可驗證、可回溯、可演化的投資決策系統。

## 當前狀態（以 DEVELOPMENT_ROADMAP.md 的 Living Section 為準）

> **注意**：Living Section 定義見 `DEVELOPMENT_ROADMAP.md` 的「📍 Living Section 定義」段落。

專案已超出早期線性 Phase 規劃，實際產品主線已形成三個閉環：

- **閉環 1：資料與市場狀態閉環** ✅ 基礎已建立
  - Update → SQLite 狀態 → Market Watch / Smart Money（市場觀察子 Tab）→ 候選池
  - Phase 1 ✅ / Phase 2 ✅ / Phase 2.5 核心 ✅ / Phase 2A/2B/2C SQLite DB-first ✅ / Phase 3 CSV 手動匯出 ✅
  - 數據更新工作台 ✅ / SQLite 儲存升級 ✅ / Smart Money Terminal MVP ✅

- **閉環 2：研究驗證閉環** ✅ 基礎已建立
  - Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Promote
  - Phase 3.1 ✅ / Phase 3.2 ✅ / Phase 3.3a ✅ / Phase 3.3b ✅
  - Research Lab 多模式實驗室 ✅ / Recommendation Portfolio Backtest MVP ✅ / Backtest chart fast renderer ✅
  - AI Runtime Subsystem MVP ✅ / Codex / Antigravity Agent 指引 ✅

- **閉環 3：持倉檢查閉環** 🚧 MVP 已建立，深化進行中
  - Recommendation / Backtest → Portfolio → Condition Monitor → Journal → 回到研究
  - Phase 4.1 Portfolio MVP 🚧：domain/service/test、Portfolio Tab、來源追溯 metadata、ConditionMonitor MVP ✅
  - 策略版本追蹤視圖、Price 對照、持倉層風險提示仍待深化

- **效能與研究輸出（Phase 5）** 🚧 部分已完成
  - 圖表渲染優化 ✅ / 大表格分頁、批次回測並行化、報告輸出仍在後續

## 現在的工作模式（你每天要用的流程）

1. Update 使用「安全更新所有數據」或左側資料來源頁更新資料
2. Market Watch 看 Regime + 強弱
3. Recommendation 用 Profile 出名單 + 看 Why/WhyNot → 加入候選池，或送 Research Lab 批次回測 / 推薦回放
4. Research Lab / Backtest 可跑單股、候選池批次、固定組合或推薦回放；必要時把明確交易記錄到 Portfolio 並保留來源追溯

## Tech Lead 的預設任務（開場要先做什麼）

- 給出「下一步最合理的工程行動」與原因（不寫 code）
- 如需看程式碼：先提出要 review 的檔案清單與目的，等我授權 scope

## 本週優先事項（只列 3 個）

1. Roadmap Rebaseline 與文件重整（對齊三個產品閉環敘事）
2. 回測時間軸契約與 no-look-ahead 測試定義
3. 金融核心數值治理啟動

## 高風險區（改動需謹慎）

- `app_module/backtest_service.py` / `backtest_module/*`
- `app_module/recommendation_service.py`
- `app_module/recommendation_replay_service.py` / `app_module/recommendation_portfolio_backtest_service.py`
- Strategy registry / preset / promotion 相關服務
- UI ↔ service contract（DTO）
- `runtime/` 核心子系統與 FSM 狀態機
- `ui_qt/widgets/fast_chart_widget.py` / `ui_qt/widgets/chart_payloads.py`（回測圖表 renderer 與資料 payload contract）
- `ui_qt/views/update_view.py` / `app_module/update_service.py`（數據更新工作台與安全更新流程）
- `portfolio_module/core.py` / `app_module/portfolio_condition_monitor.py`（Portfolio domain 與條件監控）

## 指定權威文件（需要細節再看）

- `DEVELOPMENT_ROADMAP.md` - 完整開發路線圖（Single Source of Truth）
- `NEXT_ACTION_PLAN.md` - 下一輪 Rebaseline、技術治理與 Agent 交接行動計畫
- `DOCUMENTATION_INDEX.md` - 文檔索引
- `DOCUMENTATION_STRUCTURE.md` - docs 資料夾歸屬、生命週期、刪除/歸檔規則
- `DOC_COVERAGE_MAP.md` - 文檔覆蓋矩陣（Documentation Agent 判斷 coverage 的規則）
- `PROJECT_NAVIGATION.md` / `PROJECT_INVENTORY.md` - 專案導航與盤點

---

**注意**：此 Snapshot 內容從 `DEVELOPMENT_ROADMAP.md` 的「Living Section」（定義見該文件的「📍 Living Section 定義」段落）與 `DOCUMENTATION_INDEX.md` 抽出的短版入口。詳細資訊請參考權威文件。

 
## 2026-06-09 Roadmap Rebaseline

- Roadmap Living Section 從舊線性 Phase 敘事重寫為三個產品閉環（資料與市場狀態、研究驗證、持倉檢查）+ Backlog + 技術治理 Next。
- Phase 4.1 已標記為「Portfolio MVP 已建立，深化仍在進行」；Phase 5 圖表渲染已標記完成，其餘項保留。
- 本週優先事項改為 Rebaseline → 回測時間軸契約 → 金融核心數值治理。
- Blockers / Risks 新增回測時間軸未定義、金融核心裸 float、文檔不一致三項。
- 高風險區新增 `portfolio_module/core.py` 與 `app_module/portfolio_condition_monitor.py`。
- 指定權威文件新增 `NEXT_ACTION_PLAN.md`。

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
- **UI 狀態加載毫秒級「秒開」優化**：重構 `check_data_status` 等數據狀態統計方法，當 SQLite 啟用時 100% 改由 SQL 極速聚合統計，徹底避開幾百 MB 的 CSV 硬碟掃描。
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

## 2026-06-03 主力流向 (Smart Money Flow) 視覺重構與排版優化成果

- **UI 左右分欄與架構重構**：將主力流向 Tab 重構為左右分欄布局（左側主表佔 65%，右側詳情面板佔 35%）。右側面板新增「選中股雷達摘要卡片」與「訊號原因解析」，改善籌碼流向的可讀性與解釋性。
- **中文化玻璃擬態卡片**：將頂部四張小卡片（市場趨勢、熱度、多空個股數、異常警示）完全繁體中文化，並放大標題（11px）與數值（15/16px）字型，提升視覺質感與操作清晰度。
- **Sparklines 漸層與 ToolTip 懸浮提示**：為 Sparkline 微型圖表實作漸層面積填色（`QLinearGradient`），並收緊為顯示「最近 5 筆交易明細」，解決不同週期切換導致空白或不規律的問題。實作全列 `Qt.ToolTipRole` 強制觸發，使滑鼠懸停於表格任何單元格時皆能顯示詳細的最近交易明細。
- **排序功能與 Bug 修復**：
  - 修復點擊表格標頭無法排序的問題（在 `TerminalTableModel` 與 `BranchTrackerTableModel` 中實作 `sort()` 方法）。
  - 修復多空個股數中「偏空個股數恆定為 0」與「市場熱度恆定為 100%」的 Bug（改由 unfiltered 數據重新統計多空家數，並收緊偏多異常判定至 `score >= 80` 且 `net_qty >= 500`）。
  - 完整重構說明對話框（InfoButton），提供功能說明的繁體中文對齊。

## 2026-06-03 數據更新工作台 (UpdateView) 視覺重構與架構優化成果

- **主看板升級與狀態卡片 (`StatusCard`)**：將「全部資料」頁面重構為極簡數據看板，移除了所有手動配置與雜亂按鈕。設計了 StatusCard 元件（圓角、Hover 漸變與陰影效果），整合四色狀態指示燈（🟢/🟡/🔴/⚪）顯示最新日期與筆數，與原 `QTextEdit` 介面相容度 100%。
- **進階與手動操作配置歸位**：解耦原有界面，將下載日期範圍、手動下載與合併按鈕搬移至個別專屬分頁（每日股價、大盤、產業、券商分點、技術指標）。每日股價分頁中，以紅色警示邊框封裝了 **Danger Zone (高風險區)** 存放強制重新合併按鈕。
- **全域底部日誌 Console 與進度條共享**：將 QProgressBar、進度 Label 以及 Terminal 日誌輸出框移至最外層佈局的最下方，實作分頁切換時日誌與進度的全域共享。Console 採用深色背景、Consolas 等寬 11px 字型與微型清除按鈕。
- **日期聯動同步與委派更新**：在 `UpdateView` 中實作了日期聯動邏輯，任何分頁修改日期皆會透過 blockSignals 同步更新其他分頁元件。手動更新按鈕透過 `_dispatch_update()` 自適應設定隱藏的對應 RadioButton 狀態，實現 UI 與原 Service 業務代碼的無縫相容。
- **自動與 QA 測試 100% 綠燈**：通過 mypy 無新增錯誤，`tests/test_ui_qt_update_view_workbench.py` (9 passed) 與 `scripts/qa_validate_update_tab.py` (21 passed, 0 failed) 順利通過。

## 2026-06-04 Research Lab 工作流重整

- Research Lab 第一階段開始將回測頁定位為多模式研究實驗室，區分單股回測、批次股票回測、固定組合回測、推薦系統回放與策略研究。
- 觀察清單在研究流程中重新定位為候選池 / 實驗 Universe，用於回答「我要測哪一批」。
- Recommendation / Backtest 記錄到 Portfolio 時將保留來源 metadata，讓交易紀錄可追溯到推薦結果或回測 run。


