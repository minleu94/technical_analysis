# UI_QT Development Roadmap 對照審核報表

**審核日期**：2026-05-19  
**審核範圍**：`docs/00_core/DEVELOPMENT_ROADMAP.md`、`ui_qt/`、相關 `app_module/` service、QA/測試文件  
**真相來源**：以 `docs/00_core/DEVELOPMENT_ROADMAP.md` 為主，並參照 Living Section、`docs/02_features/UI_FEATURES_DOCUMENTATION.md`、Phase 4 設計文件。

---

## 一、總結

目前 `ui_qt` **大致符合 Phase 1 ~ Phase 3.3b 的功能進度**，也已納入 Living Section 提到的 **Runtime Observatory MVP** 與 **Smart Money Terminal MVP**。

但有三個明顯落差：

1. **UI 頂層 Tab 架構與 roadmap 原始 IA 不一致**
   - Roadmap 規定 Phase 1 ~ 3 固定 4 個頂層 Tab：Update / Market Watch / Recommendation / Backtest。
   - 目前 `ui_qt/main.py` 實際頂層包含：數據更新、市場觀察、策略回測、推薦分析、觀察清單、Runtime Observatory。
   - `Watchlist` 被做成獨立頂層 Tab，與 roadmap「非獨立頂層 Tab」不一致。
   - `Runtime Observatory` 也是新增頂層 Tab，Living Section 有記錄完成，但 roadmap 的 IA 區塊尚未同步。

2. **Phase 4 尚未在 `ui_qt` 完成**
   - 已有 Phase 4.1 的 domain/service/test 骨架：`portfolio_module/`、`app_module/portfolio_service.py`、`app_module/journal_service.py`、`tests/test_portfolio_mvp.py`。
   - 但 `ui_qt` 沒有 `PortfolioView`，`main.py` 也沒有新增「持倉 / Portfolio」Tab。
   - Recommendation / Backtest 也尚未看到「建立持倉」的 UI 整合。

3. **文件狀態互相打架**
   - `DEVELOPMENT_ROADMAP.md` 和 `UI_FEATURES_DOCUMENTATION.md` 已到 Phase 3.3b 完成。
   - `ui_qt/README.md` 的「未來計劃」仍寫 Phase 3.2 / 3.3 待開始，已過期。
   - Roadmap Phase 2.5 仍提到 Walk-forward 暖機期未完成，但 Phase 3.3b 與 UI 文件已標示 warmup_days 完成。

---

## 二、Roadmap 逐項對照

### UI / Tab 架構

| 項目 | Roadmap 要求 | 目前狀態 | 判定 | 證據 |
|---|---|---:|---|---|
| Phase 1~3 固定 4 個頂層 Tab | Update / Market Watch / Recommendation / Backtest | 現有 6 個頂層 Tab，且順序為 Update / Market / Backtest / Recommendation / Watchlist / Runtime | 部分符合 | `ui_qt/main.py` 新增 tabs：數據更新、市場觀察、策略回測、推薦分析、觀察清單、Runtime Observatory |
| Phase 1~3 不新增頂層 Tab | 功能擴張應用 sub-tab / 區塊 / side panel | Smart Money 放在市場觀察 sub-tab，符合；Watchlist、Runtime 是頂層，需決策是否修正 IA | 部分符合 | `market_tabs.addTab(..., "主力流向")`；`tabs.addTab(watchlist, "觀察清單")`；`tabs.addTab(self.runtime_view, "Runtime Observatory")` |
| Phase 4 起新增 Portfolio Tab | 新增「持倉 / Portfolio」 | 尚未在 `ui_qt` 實作 | 未完成 | 未找到 `ui_qt/views/portfolio_view.py` 或 `tabs.addTab(... Portfolio ...)` |

### 跨 Tab 共用核心模組

| 項目 | Roadmap 要求 | 目前狀態 | 判定 | 證據 |
|---|---|---:|---|---|
| Watchlist | 跨 Market / Recommendation / Backtest 共用 | 已串接 Market 強弱股、Recommendation、Backtest；但 UI 是獨立頂層 Tab | 功能完成，IA 待調整 | `WatchlistService`、`WatchlistView`、`RecommendationView`、`BacktestView.load_from_recommendation` |
| StrategyRegistry | 策略定義與 meta | 已存在 `strategy_registry.py` 與策略 executor | 完成 | `app_module/strategy_registry.py`、`app_module/strategies/` |
| PresetService | 策略版本、參數預設、Profiles | 已存在，且 Promote 使用 | 完成 | `app_module/preset_service.py`、`app_module/promotion_service.py` |
| BacktestResultStore | SQLite + Parquet/CSV | 已有 `BacktestRunRepository` | 完成 | `app_module/backtest_repository.py` |
| DTO 規範 | Recommendation / Backtest 統一輸出 | 已有 DTO 與 repository | 完成 | `app_module/dtos/`、`recommendation_repository.py` |

---

## 三、Phase 狀態

### Phase 1：市場觀察儀

| 功能 | 狀態 | 說明 |
|---|---|---|
| 數據更新流程 | 完成 | `UpdateView` 已整合每日股票、大盤、產業、券商分點與技術指標計算入口。 |
| 強勢股 / 強勢產業 | 完成 | `StrongStocksView`、`StrongIndustriesView` 已存在。 |
| 市場 Regime 判斷 | 完成 | `MarketRegimeView` 呼叫 `RegimeService.detect_regime()`。 |
| 推薦理由生成 | 完成 | `RecommendationView` 顯示推薦理由與詳情。 |

**結論**：Phase 1 功能符合。

### Phase 2：策略資料庫

| 功能 | 狀態 | 說明 |
|---|---|---|
| Phase2-A Watchlist | 功能完成，IA 不完全符合 | Watchlist 功能完成，但 roadmap 要求「非獨立頂層 Tab」，目前是頂層 Tab。 |
| Phase2-B 弱勢分析 | 完成 | `WeakStocksView`、`WeakIndustriesView` 已存在並串接 Market sub-tab。 |
| Phase2-C Recommendation DTO 統一 | 完成 | 推薦結果可保存到 `RecommendationRepository`。 |
| Phase2-D Backtest 體驗補強 | 完成 | Grid Search 進度回調與結果套用已存在。 |
| Phase2-E 預設策略庫 | 完成 | 策略 registry / executor / docs 已存在。 |

**結論**：Phase 2 功能符合，只有 Watchlist 頂層位置與 roadmap 原則不一致。

### Phase 2.5：參數設計優化

| 功能 | 狀態 | 說明 |
|---|---|---|
| 強弱勢分數標準化 | 完成 | Service 層已有標準化邏輯，QA 文件也記錄通過。 |
| Pattern ATR-based | 完成 | `pattern_analyzer.py` 支援 ATR 相關參數。 |
| Scoring contract 0~100 | 完成 | 推薦與 UI 文件均記錄完成。 |
| execution_price | 完成 | `BacktestView` 與 `BacktestService` 已支援。 |
| ATR 停損停利 | 完成 | `BacktestView` 具備 ATR 輸入。 |
| max_positions / position_sizing | 完成 | 回測服務和 UI 參數已支援。 |
| 指標參數整體改進 | 未完成 / 待優化 | Roadmap 仍列為中期未完成。 |
| buy_score/sell_score 分位數 | 未完成 / 待優化 | Roadmap 仍列為未完成。 |
| 推薦系統參數改進 | 未完成 / 待優化 | Roadmap 仍列為未完成。 |

**結論**：Phase 2.5 核心完成，但中長期優化項仍未完成。另：Roadmap 早段說 warmup 未完成，但 Phase 3.3b 已完成，建議修正文檔。

### Phase 3.1：推薦可用化

| 功能 | 狀態 | 說明 |
|---|---|---|
| 推薦 Tab 可理解性優化 | 完成 | UI 有集中配置、tooltip、策略傾向、結果反推線索。 |
| 新手 / 進階模式 | 完成 | `RecommendationView` 已有 Profile 與 mode 切換。 |
| Why Not v1 | 完成 | `_generate_why_not()` 已實作。 |
| 推薦結果可保存 | 完成 | `_save_recommendation_result()` 使用 `RecommendationRepository.save_result()`。 |

**結論**：Phase 3.1 符合。

### Phase 3.2：Profiles 正式化

| 功能 | 狀態 | 說明 |
|---|---|---|
| Profiles v1 | 完成 | Recommendation UI 有 Profiles。 |
| Regime → Profile 建議 | 完成 | `RecommendationView` 會偵測 Regime 並顯示建議 Profile。 |
| Profile meta 可追溯 | 完成 | 一鍵送回測與保存結果會帶 profile / regime snapshot。 |

**結論**：Phase 3.2 符合；但 `ui_qt/README.md` 仍寫待開始，需更新。

### Phase 3.3a：研究閉環核心功能

| 功能 | 狀態 | 說明 |
|---|---|---|
| Explain 面板 v1 | 完成 | `_generate_explain_panel()` 顯示分數拆解與風險點。 |
| 一鍵送回測 | 完成 | `RecommendationView.sendToBacktestRequested` 連到 `BacktestView.load_from_recommendation()`。 |

**結論**：Phase 3.3a 符合。

### Phase 3.3b：研究閉環完整化

| Epic | 狀態 | 說明 |
|---|---|---|
| Epic 1 Promote 機制 | 完成 | `PromotionService`、`StrategyVersionService`、`BacktestView` Promote 按鈕與處理流程已存在。 |
| Epic 2 回測穩健性驗證 | 完成 | Baseline comparison、overfitting risk、warmup_days 相關支援已存在。 |
| Epic 3 K 線視覺驗證 | 完成 | Chart widget / Backtest UI 已有 K 線與交易標記相關功能。 |
| 完整驗證 | 文件顯示完成 | QA 報告存在，但本次未完整重跑所有歷史驗證腳本。 |

**結論**：Phase 3.3b 功能符合。

### Living Section：AI Runtime MVP

| 功能 | 狀態 | 說明 |
|---|---|---|
| RuntimeView UI | 完成 | `RuntimeView` 已存在並在 `main.py` 加為頂層 Tab。 |
| QtRuntimeBridge | 完成 | `QtRuntimeBridge` 將 event bus 轉成 Qt signal。 |
| QTimer 輪詢 | 完成 | `main.py` 每秒 poll updates。 |

**結論**：功能符合 Living Section，但需要補進 roadmap 的 UI / Tab IA，否則與「Phase 1~3 固定 4 Tab」規則衝突。

### Living Section：Smart Money Terminal MVP / Phase 4.2 前置能力

| 功能 | 狀態 | 說明 |
|---|---|---|
| Broker branch update | 完成 | `UpdateView` 有券商分點資料更新、合併、狀態區塊。 |
| Smart Money Terminal | 完成 | `SmartMoneyFlowView`、delegate、table model 已存在。 |
| 放置位置 | 可接受 | 實作在 Market Watch sub-tab「主力流向」，沒有新增頂層 Tab。 |

**結論**：Smart Money MVP 已完成；是否算 Phase 4.2 完成需要 roadmap 更新，因為 Phase 4.2 checklist 仍是未勾選。

### Phase 4：持倉管理與交易日誌

| 功能 | 狀態 | 說明 |
|---|---|---|
| 新增 Portfolio Tab | 未完成 | `ui_qt` 沒有 PortfolioView，`main.py` 沒有 Portfolio Tab。 |
| 交易紀錄 | 部分完成 | `PortfolioService.record_trade()`、append-only `PortfolioJsonlStore`、`tests/test_portfolio_mvp.py` 已存在；但 UI 未整合。 |
| 條件監控 | 部分完成 / 分歧 | 舊版 `PositionService` 有 `condition_status`；新版 `PortfolioService` 主要是 trades → positions projection，尚未整合 current regime / score monitor UI。 |
| 非強制提示 | 未完成 | 未看到 Portfolio UI 警示/提醒呈現。 |
| Journal | 部分完成 | `JournalService` 與測試已存在；UI 未整合。 |

**結論**：Phase 4.1 已開始做 service/domain 骨架，但 `ui_qt` 進度仍是未完成。以使用者可見功能來看，尚不能說已進入 Phase 4 完成狀態。

### Phase 5：效能與研究輸出

| 功能 | 狀態 | 說明 |
|---|---|---|
| 大表格分頁 | 未完成 | `PandasTableModel` 有排序，但未見 pagination。 |
| 圖表渲染優化 PyQtGraph | 未完成 | 目前仍主要使用 matplotlib/mplfinance 架構。 |
| 批次回測並行化 | 部分完成 | Optimizer 有多線程優化；Phase 5 更廣義的大規模 batch/table/chart 仍未完成。 |
| 匯出研究報告 Excel / PDF | 未完成 | 未見 UI 匯出研究報告功能。 |

**結論**：Phase 5 尚未開始或僅有局部性能優化。

---

## 四、目前已完成的功能清單

- Phase 1 市場觀察儀核心功能。
- Phase 2 策略資料庫核心功能。
- Phase 2.5 核心參數設計優化。
- Phase 3.1 推薦可用化。
- Phase 3.2 Profiles 正式化。
- Phase 3.3a 推薦 → 回測閉環。
- Phase 3.3b Promote / Walk-forward / Baseline / 過擬合風險 / K 線視覺驗證。
- Broker branch data update。
- Smart Money Terminal MVP。
- Runtime Observatory MVP。
- Phase 4.1 的部分 service/domain/test 骨架。

---

## 五、尚未完成或待優化

### 必須補齊

1. **Phase 4 Portfolio UI**
   - 新增 `ui_qt/views/portfolio_view.py`
   - 在 `main.py` 加入「持倉 / Portfolio」Tab
   - 串接 `PortfolioService`、`JournalService`
   - 顯示持倉列表、交易紀錄、Journal、來源追溯、條件狀態

2. **Phase 4 條件監控**
   - 將 entry snapshot、current regime、current score、current price 對照落地。
   - 目前有兩套方向：舊 `position_service.py` 的 condition model、新 `portfolio_service.py` 的 append-only trades projection，需要整併。

3. **Phase 3 → Phase 4 整合**
   - Recommendation 結果建立持倉。
   - Backtest / promoted strategy 建立持倉。
   - 持倉可回溯 source_type / source_id / snapshot。

### 需要優化

1. **UI IA 文件與實作同步**
   - 決定 Watchlist 是否保留頂層 Tab，或移回 Market / Backtest side panel。
   - 決定 Runtime Observatory 是否屬於開發者工具頂層 Tab，並寫入 roadmap。
   - 更新 `ui_qt/README.md`，它目前明顯落後。

2. **Phase 2.5 中長期項目**
   - 指標參數改進。
   - buy_score / sell_score 分位數化。
   - 推薦系統參數改進。

3. **Phase 5 性能與輸出**
   - 大表格分頁。
   - 圖表渲染改成 PyQtGraph 或等效方案。
   - 研究報告 Excel / PDF 匯出。

---

## 六、建議下一步

1. **先決定 IA 是否要修正**
   - 若嚴格遵守 roadmap：Watchlist 應從頂層 Tab 移回功能區或 side panel，Runtime 需另定為 dev/observability tab。
   - 若接受現在的實作：應更新 roadmap 的 UI / Tab 架構，承認目前已超過 4 個頂層 Tab。

2. **把 Phase 4.1 當成下一個主要開發目標**
   - 優先做 PortfolioView MVP。
   - 不新增策略、不做自動決策，只呈現持倉、交易紀錄、來源追溯、條件變化。

3. **清理文件落差**
   - 更新 `ui_qt/README.md` 的 Phase 3.2 / 3.3 狀態。
   - 修正 Phase 2.5 warmup 的舊描述。
   - 將 Smart Money / Runtime 的 IA 位置寫進 roadmap。

---

## 七、審核結論

`ui_qt` 目前**已符合 Phase 3.3b 完成後的主要產品能力**，而且比原始 Phase 1~3 roadmap 多了 Runtime Observatory 與 Smart Money Terminal。

真正尚未完成的是 **Phase 4 的使用者可見 UI 與 Phase 3 → Portfolio 的閉環整合**。目前 Phase 4 只有服務層、domain 與測試骨架，還不能算 `ui_qt` 層完成。

