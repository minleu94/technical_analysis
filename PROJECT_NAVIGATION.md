# 專案導航文件

**版本**：v1.0.0  
**最後更新**：2025-12-30  
**目標讀者**：專案開發者、新加入工程師

---

## 1️⃣ 專案一句話定位

**這是一個「可驗證、可回溯、可演化」的台股投資決策系統。**

系統提供完整的數據更新、市場觀察、股票推薦、策略回測功能，讓策略成為可被描述、被比較、被淘汰的研究對象。這不是單純的策略腳本，而是一個工具型系統。

---

## 2️⃣ 三層架構導航

### UI Layer（`ui_qt/`、`ui_app/`）

**主要入口**：`ui_qt/main.py`（PySide6 Qt UI，推薦使用）

**這一層不該做什麼**：
- 不包含業務邏輯
- 不直接操作數據
- 只負責：收參數、呼叫 Service、顯示 DTO

**Legacy UI**：`ui_app/main.py`（Tkinter UI，僅供參考）

---

### Application Service Layer（`app_module/`）

**這一層負責什麼**：
- Use case 編排（orchestration）
- UI 與 Domain 的解耦橋樑
- 數據轉換（DTO 處理）
- 服務組合（例如：回測服務組合策略執行器、績效分析器）

**與 Domain 的關係**：
- 依賴 `decision_module/`，不依賴 `ui_app/`
- 所有業務邏輯都透過 `decision_module/` 取得

---

### Domain Layer（`decision_module/`）

**這一層放什麼**：
- 策略配置器（StrategyConfigurator）
- 股票篩選器（StockScreener）
- 打分引擎（ScoringEngine）
- 推薦理由引擎（ReasonEngine）
- 市場狀態檢測（MarketRegimeDetector）
- 產業映射（IndustryMapper）

**為什麼它是核心**：
- 所有業務邏輯的實際實作都在這裡
- `app_module/` 服務層完全依賴它
- UI 層透過服務層間接使用它，或主程式直接初始化它

---

## 3️⃣ 專案主要入口

### ✅ 主要啟動方式（推薦）

```bash
python ui_qt/main.py
```

**這是什麼**：PySide6 Qt 圖形界面，包含所有功能 Tab（數據更新、市場觀察、推薦分析、策略回測、觀察清單）

---

### ⚠️ Legacy 啟動方式（僅供參考）

```bash
python ui_app/main.py
```

**這是什麼**：Tkinter UI（舊版），業務邏輯已遷移到 `decision_module/`，此 UI 僅保留 Tkinter 相關代碼

---

### ❌ 不建議使用的入口

- `examples/main_example.py`：已棄用的舊版主程式示例

---

## 4️⃣ 「我要做 X，要去哪裡看？」功能導航

### 📌 Data Update（數據更新）

**從哪個 UI 進**：`ui_qt/views/update_view.py`（數據更新 Tab）

**對應的 Service**：`app_module/update_service.py`
- 負責：數據狀態檢查、更新流程編排

**真正動邏輯的地方**：
- `scripts/batch_update_daily_data.py`：批量更新每日股票數據
- `scripts/merge_daily_data.py`：合併數據到 meta_data
- `scripts/batch_update_market_and_industry_index.py`：更新市場/產業指數

**如果我要改數據更新邏輯**：先看 `app_module/update_service.py`，再看對應的腳本檔案。

---

### 📌 Market Watch（市場觀察）

**從哪個 UI 進**：`ui_qt/views/` 目錄下的 5 個視圖
- `market_regime_view.py`：大盤指數
- `strong_stocks_view.py`：強勢個股
- `weak_stocks_view.py`：弱勢個股
- `strong_industries_view.py`：強勢產業
- `weak_industries_view.py`：弱勢產業

**對應的 Service**：
- `app_module/screening_service.py`：強勢/弱勢股篩選
- `app_module/regime_service.py`：市場狀態檢測

**真正動邏輯的地方**：
- `decision_module/stock_screener.py`：股票篩選邏輯（強勢/弱勢判斷）
- `decision_module/market_regime_detector.py`：市場狀態判斷（Trend/Reversion/Breakout）
- `decision_module/industry_mapper.py`：產業映射與產業指數處理

**如果我要改市場觀察邏輯**：先看 `app_module/screening_service.py` 或 `app_module/regime_service.py`，再看 `decision_module/` 對應的檔案。

---

### 📌 Recommendation（推薦分析）

**從哪個 UI 進**：`ui_qt/views/recommendation_view.py`（推薦分析 Tab）

**對應的 Service**：`app_module/recommendation_service.py`
- 負責：策略配置編排、推薦結果生成、結果保存

**真正動邏輯的地方**：
- `decision_module/strategy_configurator.py`：策略配置（技術指標、圖形模式設定）
- `decision_module/scoring_engine.py`：打分引擎（統一打分模型，0-100 分）
- `decision_module/reason_engine.py`：推薦理由生成（Why / Why Not）

**如果我要改推薦邏輯**：
- 改策略配置 → `decision_module/strategy_configurator.py`
- 改打分邏輯 → `decision_module/scoring_engine.py`
- 改推薦理由 → `decision_module/reason_engine.py`

---

### 📌 Backtest（策略回測）

**從哪個 UI 進**：`ui_qt/views/backtest_view.py`（策略回測 Tab）

**對應的 Service**：
- `app_module/backtest_service.py`：單次回測
- `app_module/batch_backtest_service.py`：批次回測
- `app_module/walkforward_service.py`：Walk-forward 驗證
- `app_module/optimizer_service.py`：參數最佳化

**真正動邏輯的地方**：
- `backtest_module/strategy_tester.py`：策略測試器（執行策略邏輯）
- `backtest_module/performance_analyzer.py`：績效分析器（計算績效指標）
- `backtest_module/performance_metrics.py`：績效指標計算（包含 Walk-Forward 退化、一致性、過擬合風險）
- `backtest_module/broker_simulator.py`：券商模擬器（模擬交易執行）
- `app_module/strategies/`：策略執行器（實際策略邏輯）

**如果我要改回測邏輯**：
- 改回測流程 → `app_module/backtest_service.py`
- 改績效計算 → `backtest_module/performance_metrics.py`
- 改策略執行 → `app_module/strategies/` 對應的執行器
- 改 Walk-Forward → `app_module/walkforward_service.py`

**特殊功能**：
- **Walk-Forward 暖機期**：`app_module/walkforward_service.py` 的 `warmup_days` 參數
- **Baseline 對比**：`backtest_module/performance_metrics.py` 的 `calculate_baseline_comparison()`
- **過擬合風險提示**：`backtest_module/performance_metrics.py` 的 `calculate_overfitting_risk()`

---

### 📌 Watchlist（觀察清單）

**從哪個 UI 進**：`ui_qt/views/watchlist_view.py`（觀察清單 Tab）

**對應的 Service**：`app_module/watchlist_service.py`
- 負責：跨 Tab 共用候選池管理、JSON 持久化

**真正動邏輯的地方**：
- `app_module/watchlist_service.py`：觀察清單的完整邏輯都在這裡（沒有 Domain 層依賴）

**如果我要改觀察清單邏輯**：直接看 `app_module/watchlist_service.py`。

---

## 5️⃣ ⚠️ 高風險核心檔案（Do Not Touch Blindly）

### `decision_module/scoring_engine.py`
**為什麼風險高**：統一打分模型的核心，所有推薦分數都從這裡計算，改動會影響所有策略。

### `decision_module/strategy_configurator.py`
**為什麼風險高**：策略配置的核心，定義所有技術指標和圖形模式的參數，改動會影響所有推薦結果。

### `backtest_module/performance_metrics.py`
**為什麼風險高**：所有回測績效指標的計算邏輯，包含 Walk-Forward 退化、一致性、過擬合風險等核心計算。

### `app_module/backtest_service.py`
**為什麼風險高**：回測流程的編排核心，整合策略執行器、績效分析器、券商模擬器，改動會影響所有回測結果。

### `app_module/walkforward_service.py`
**為什麼風險高**：Walk-Forward 驗證的核心邏輯，包含暖機期處理、訓練/測試期分割，改動會影響驗證結果。

### `backtest_module/broker_simulator.py`
**為什麼風險高**：模擬交易執行的核心，包含手續費、滑價、停損停利等邏輯，改動會影響所有回測的實際交易模擬。

### `decision_module/stock_screener.py`
**為什麼風險高**：強勢/弱勢股篩選的核心邏輯，改動會影響市場觀察的所有結果。

### `decision_module/market_regime_detector.py`
**為什麼風險高**：市場狀態判斷的核心，改動會影響所有依賴 Regime 的策略和推薦。

### `data_module/config.py`
**為什麼風險高**：所有數據路徑和配置的核心，改動會影響整個系統的數據存取。

### `app_module/recommendation_service.py`
**為什麼風險高**：推薦分析的編排核心，整合策略配置、打分、理由生成，改動會影響所有推薦結果。

---

## 6️⃣ Legacy / Historical 區塊

### `ui_app/` 目錄

**角色**：Legacy Tkinter UI

**狀態**：
- 業務邏輯已遷移到 `decision_module/`
- 僅保留 Tkinter UI 相關代碼
- `ui_app/main.py` 已更新為使用 `decision_module/`

**使用建議**：新功能不應再引用 `ui_app/` 中的業務邏輯檔案（如 `strategy_configurator.py`、`stock_screener.py` 等），這些檔案已不存在或已遷移。

---

### `recommendation_module_legacy/` 目錄

**角色**：舊版推薦引擎（已棄用）

**狀態**：
- 僅被 `tests/` 和 `examples/` 使用
- 不屬於核心架構
- 已添加棄用警告

**使用建議**：新功能應使用 `app_module/recommendation_service.py`，不應再引用 `recommendation_module_legacy/`。

---

### 不應再被新功能引用的模組

- `ui_app/` 中的業務邏輯檔案（已遷移到 `decision_module/`）
- `recommendation_module_legacy/`（應使用 `app_module/recommendation_service.py`）
- `examples/main_example.py`（已棄用）

---

## 📚 相關文檔

- **開發演進地圖**：`docs/DEVELOPMENT_ROADMAP.md`（了解系統演進計劃）
- **專案盤點報告**：`PROJECT_INVENTORY.md`（完整的專案結構盤點，與本文檔同層）
- **文檔索引**：`docs/DOCUMENTATION_INDEX.md`（所有文檔的索引）

---

**文件結束**

