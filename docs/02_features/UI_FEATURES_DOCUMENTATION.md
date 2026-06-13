# UI 功能文件（Qt）

> **最後整理**：2026-06-13
> **適用範圍**：`ui_qt/` 目前主要使用者介面。
> **狀態判讀**：目前狀態以 `docs/00_core/PROJECT_SNAPSHOT.md` 為準；未來 6 個月工程方向以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準；本文件只描述 UI 功能與操作入口。
> **完整操作**：安裝、逐步操作、參數、結果判讀與排錯見 [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md)。

---

## 一、UI 定位

Qt UI 不是單純顯示股票名單，而是把「資料更新、候選觀察、策略研究、推薦、持倉檢查、Agent runtime 觀測」串成可回溯的投資決策工作台。

目前入口為：

- `ui_qt/main.py`
- `ui_qt/views/`
- `ui_qt/widgets/`

主要設計原則：

- UI 只負責呈現、輸入、互動與事件轉接。
- 核心計算、資料讀寫與策略邏輯必須在 service / domain 層。
- Recommendation、Backtest、Portfolio 之間的交接必須保留來源 metadata。
- 策略、回測、績效、持倉與金融金額計算不得在 UI 內新增裸 `float` 核心計算。
- 涉及回測或推薦訊號時，必須維持 Look-ahead bias 防線。

---

## 二、頂層 Tab

### 1. 數據更新

主要 view：

- `ui_qt/views/update_view.py`
- `ui_qt/widgets/sqlite_inspector_widget.py`

主要能力：

- 每日股價、大盤、產業、券商分點與技術指標更新。
- 快速更新（僅 SQLite）與安全更新（CSV + SQLite）分流。
- SQLite 狀態檢查、資料表檢視與唯讀 SQL preview。
- 券商分點資料更新、合併、長碼解密與品質狀態呈現。

文件同步重點：

- 更新流程改動需同步 `docs/03_data/` 相關指南。
- SQLite / CSV 雙軌行為改動需同步 `docs/01_architecture/system_architecture.md` 與 `docs/03_data/SQLITE_STORAGE_GUIDE.md`。

### 2. 市場觀察

主要 views：

- `ui_qt/views/market_regime_view.py`
- `ui_qt/views/strong_stocks_view.py`
- `ui_qt/views/weak_stocks_view.py`
- `ui_qt/views/strong_industries_view.py`
- `ui_qt/views/weak_industries_view.py`
- `ui_qt/views/smart_money/smart_money_flow_view.py`

子 Tab：

- 大盤指數
- 強勢個股
- 弱勢個股
- 強勢產業
- 弱勢產業
- 主力流向

主要能力：

- 市場 regime 判斷。
- 強弱勢股票與產業篩選。
- Smart Money Terminal：個股資金流向、分點進出追蹤、張數 / 金額品質標示。
- 可把觀察標的送入候選池 / Watchlist。

文件同步重點：

- 籌碼、分點、資料品質語意改動需同步 `docs/04_broker_branch/`。
- Regime 或 scoring 輸出語意改動需同步 `docs/02_features/SCORE_EXPLANATION.md`。

### 3. 策略回測

主要 views：

- `ui_qt/views/backtest_view.py`
- `ui_qt/views/backtest/config_panel.py`
- `ui_qt/views/backtest/result_panel.py`
- `ui_qt/widgets/fast_chart_widget.py`

主要能力：

- 單股回測、候選池批次回測、推薦組合回放。
- Strategy registry / preset / promotion 整合。
- Walk-forward、baseline comparison、overfitting risk、validation status。
- Fixed / quantile threshold mode UI 控制與無交易診斷。
- 結果保存、歷史比較、Promote 為策略版本。
- Fast chart renderer：權益曲線、回撤曲線、報酬分佈、持有天數。

回測防線：

- 回測訊號只能使用決策當下可取得的資料。
- `next_open` / `close` 撮合假設必須透過 metadata 或 warning 呈現。
- Quantile 模式的門檻需由策略執行器輸出，不應在 UI 或 service 端用完整期間重算。

文件同步重點：

- 回測邏輯變更需同步 `docs/02_features/BACKTEST_LAB_FEATURES.md`。
- 策略參數與門檻語意變更需同步 `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`。

### 4. 推薦分析

主要 view：

- `ui_qt/views/recommendation_view.py`

主要能力：

- Profile / mode / strategy config 推薦。
- Why / WhyNot / Explain panel。
- Regime snapshot 與推薦 metadata 保存。
- 推薦結果保存與 round-trip 載入。
- 一鍵送策略回測。
- 送 Research Lab 批次回測。
- 建立候選池 / Watchlist。
- Fixed / quantile 門檻模式與 eligible universe 橫斷面百分位排名。

推薦防線：

- Quantile / percentile 推薦必須先固定當日 eligible universe。
- 母體不足時應拒絕降級並顯示可理解錯誤。
- 排序需穩定化，避免相同分數因輸入順序造成結果不可重現。

文件同步重點：

- 推薦分數與百分位語意需同步 `docs/02_features/SCORE_EXPLANATION.md`。
- 推薦策略 contract 需同步 `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`。

### 5. 觀察清單

主要 view：

- `ui_qt/views/watchlist_view.py`

主要能力：

- 候選池 / watchlist 管理。
- 從 Market Watch、Recommendation、Backtest 取得候選標的。
- 支援後續送入 Backtest / Research workflow。

文件同步重點：

- Watchlist 語意若改為正式投組、研究候選池或交易候選池，需同步 Snapshot、User Guide 與 architecture。

### 6. 持倉管理

主要 view：

- `ui_qt/views/portfolio_view.py`

右側子 Tab：

- 交易歷史
- 覆盤日誌
- 策略與價格監控
- 籌碼監控

主要能力：

- 手動記錄交易並投影目前持倉。
- 保存 Recommendation / Backtest / Strategy Version 來源 metadata。
- 顯示目前價格、未實現損益、停損 / 停利與條件監控。
- 顯示策略版本或推薦來源追蹤。
- 籌碼監控：主力淨買賣、集中度、連續流向天數與風險級別。
- 從 Portfolio 下鑽至 Market Watch 的主力流向並定位個股。

持倉防線：

- 金額、成本、股數、PnL 必須使用 domain/service 層的 Decimal / 整數單位。
- UI 不應自行重算金融核心數值。
- 來源追溯不能被 UI 手動覆蓋成不可追蹤狀態。

文件同步重點：

- Portfolio 來源模型、條件監控或籌碼監控改動需同步 `docs/05_phases/PHASE4_PORTFOLIO_DESIGN.md`、Snapshot 與 architecture。

### 7. Runtime Observatory

主要 view：

- `ui_qt/views/runtime_view.py`
- `ui_qt/bridges/runtime_event_bridge.py`

主要能力：

- 顯示 AI Runtime Subsystem 狀態。
- 觀測 FSM 狀態、health snapshot 與 event stream。
- 透過 Qt bridge 接收 runtime event bus。

文件同步重點：

- Runtime 狀態、事件或治理規則改動需同步 `docs/01_architecture/runtime_observatory_rules.md`。

---

## 三、跨 Tab 工作流

### 市場觀察到候選池

1. 使用 Market Watch 找出強勢 / 弱勢 / 籌碼異常標的。
2. 加入 Watchlist / Candidate Pool。
3. 候選池可送 Backtest 或作為 Recommendation / Research workflow 的輸入。

### 推薦到回測

1. Recommendation 依 Profile、Regime、strategy config 產生推薦。
2. 使用一鍵送回測或送 Research Lab 批次回測。
3. Backtest 保存 run metadata，必要時 Promote 為策略版本。

### 回測到持倉

1. Backtest run 若符合條件，可建立或輔助建立持倉。
2. Portfolio 保存 `source_type`、`source_id`、strategy / recommendation metadata。
3. 持倉後續用價格、regime、score、籌碼監控做假設檢查。

### 持倉回到研究

1. Portfolio 顯示假設失效、停損 / 停利、籌碼惡化或來源策略資訊。
2. 使用下鑽回 Market Watch / Smart Money 查原因。
3. 回到 Backtest / Recommendation 調整研究假設。

---

## 四、UI Contract

### UI 可做

- 顯示資料、表格、圖表與警示。
- 收集使用者輸入並轉成 service config。
- 轉接跨 Tab 事件。
- 顯示 service/domain 回傳的 metadata、diagnostics 與 validation status。

### UI 不應做

- 不在 UI 內新增策略核心計算。
- 不在 UI 內重算金融金額、PnL、持倉 average cost。
- 不在 UI 內用完整期間資料重算回測門檻或推薦百分位。
- 不直接寫正式資料根目錄，必須透過既有 service / repository。

---

## 五、目前缺口與 6M Roadmap 對齊

近期 UI 相關缺口：

- Phase 5 大表格分頁仍待完成。
- Excel / PDF 研究報告輸出仍待完成。
- Research Run Registry 與跨 run 比較需要 UI 入口與結果視圖。
- Factor Layer、營收估值、三大法人資料加入後，需要新增可檢查資料品質與 available date 的呈現方式。

對應文件：

- [PROJECT_SNAPSHOT.md](../00_core/PROJECT_SNAPSHOT.md)
- [ROADMAP_6M_ENGINEERING.md](../00_core/ROADMAP_6M_ENGINEERING.md)
- [DEVELOPMENT_ROADMAP.md](../00_core/DEVELOPMENT_ROADMAP.md)
- [system_architecture.md](../01_architecture/system_architecture.md)
- [BACKTEST_LAB_FEATURES.md](BACKTEST_LAB_FEATURES.md)
- [USER_GUIDE.md](USER_GUIDE.md)
- [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md)
