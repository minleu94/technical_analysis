# Research Lab 工作台 V1 設計規格

## 背景

第一階段 Research Lab 工作流重整已完成語意與來源追溯基礎：

- Backtest / Research Lab 已有模式 taxonomy。
- Recommendation / Backtest 記錄到 Portfolio 時會保留來源 metadata。
- Watchlist 在研究流程中已重新定位為候選池。
- Recommendation 下一步行動已改成「加入候選池 / 送 Research Lab 批次回測 / 送 Research Lab 推薦回放 / 記錄到持倉管理」。

下一個痛點是 BacktestView 本身仍是「功能都在，但看起來像堆疊在一起」：策略預設、回測配置、資金成本、停損停利、部位 sizing、部位管理、市場限制、策略配置、最佳化、Walk-forward、推薦回放、執行、結果、歷史比較都在同一頁面內展開。使用者需要自己判斷這些控制和「本次實驗」的關係。

本規格定義 Research Lab 工作台 V1：採用「操作台式」布局，先做資訊架構與 UI 分組，不大改邏輯。

## 目標

1. 把 BacktestView 重新整理成「左側實驗設定台 + 右側實驗結果台」的 Research Lab 操作台。
2. 讓使用者先理解本次實驗的模式、輸入、策略與風控，再執行回測。
3. 保留既有單股回測、批次回測、推薦回放、Grid Search、Walk-forward、Promote、歷史比較與圖表功能。
4. 降低 UI 混亂度，但不重寫回測引擎、不改核心計算、不改 service contract。
5. 為後續「模式驅動 UI」與 Strategy Center 銜接留下清楚邊界。

## 非目標

1. V1 不新增新的回測引擎、策略引擎或推薦 replay service。
2. V1 不做完整 Strategy Center。
3. V1 不把固定組合回測做成全新儲存模型；固定組合第一版仍沿用既有選股清單 / 推薦組合回測相關能力。
4. V1 不依模式大量隱藏既有控制；只做分組、標題、提示與入口順序整理。
5. V1 不修改核心金融計算，因此不新增裸 `float` 計算，也不觸碰策略、績效或風控演算法。
6. V1 不刪除既有功能或改變已通過的 Backtest / Portfolio / Recommendation handoff 行為。

## 使用者流程

Research Lab 工作台 V1 的主要流程：

```text
選實驗模式
→ 選輸入來源
→ 設定策略與風控
→ 執行實驗
→ 查看摘要 / 交易 / 圖表 / 歷史
→ 下一步：保存 run、Promote、記錄到 Portfolio
```

V1 不要求每一步做成 wizard。它仍是單頁操作台，但用分組和標題讓流程自然成立。

## UI 架構

### 左側：實驗設定台

左側 ScrollArea 保留，但區塊重新整理為四大段。

#### 1. 實驗模式

目的：回答「這次實驗要解決什麼問題」。

內容：

- Research Lab 模式下拉選單。
- 模式說明文字。
- 主要輸入提示，例如「股票代號」、「候選池 / 選股清單」、「推薦 Profile / Config」。

V1 要把提示從單純描述升級為：

```text
{description}｜主要輸入：{primary_input}
```

#### 2. 輸入來源

目的：回答「我要測哪一批 / 哪一檔 / 哪個推薦設定」。

內容沿用既有控制：

- 股票選擇模式：單一股票 / 選股清單。
- 股票代號輸入。
- 候選池 / 選股清單下拉與管理入口。
- 日期區間。
- 推薦回放設定區的 Profile/Config 載入狀態與 Top N / holding days / rebalance 等控制。

V1 不移動資料流，只把相關控制放在同一語意區塊中。

#### 3. 策略與風控

目的：回答「用什麼策略、什麼成本、什麼風險設定來測」。

內容沿用既有控制：

- 策略預設。
- 策略配置與參數。
- 初始資金。
- 手續費、滑價、執行價格。
- 停損停利。
- 部位 sizing。
- 部位管理。
- 市場限制。
- Grid Search / 參數最佳化。
- Walk-forward 驗證。

V1 可以把 Grid Search 與 Walk-forward 保持在「進階驗證」區塊，但不改其行為。

#### 4. 執行與下一步

目的：回答「我現在要跑，跑完能做什麼」。

內容：

- 主要按鈕改成「執行 Research Lab 實驗」或「執行實驗」。
- 進度條與狀態文字保留。
- 保存 run / Promote / 記錄到 Portfolio 的入口仍在現有位置，但文案要和 Research Lab 語意一致。

### 右側：實驗結果台

右側結果分頁保留既有資料與表格，但整理 tab 名稱與順序。

建議順序：

1. **實驗摘要**：原績效摘要。
2. **交易明細**：原交易明細；右鍵可記錄到 Portfolio 並保留來源。
3. **圖表**：權益曲線、回撤、報酬分佈、持有天數。
4. **批次結果**：批次 leaderboard 與統計。
5. **推薦回放**：推薦組合回測結果。
6. **歷史與比較**：回測歷史、比較、載入。
7. **最佳化 / 驗證**：若現有 UI 已有獨立分頁，V1 只改標題，不重排資料模型。

V1 不要求完整搬動所有 tabs；若現有 tab 結構難以一次重排，第一版可先改 visible label 與 section title，保留原 widget 架構。

## 實作邊界

### 可修改

- `ui_qt/views/backtest_view.py`
  - groupbox 標題
  - 控制區塊順序
  - hint label 文字
  - button text
  - result tab labels
  - 小型 helper function / constants

- 測試檔
  - 新增 Research Lab workbench copy / taxonomy tests。
  - 必要時新增針對 `RESEARCH_LAB_MODES` 或可見文字的輕量測試。

- 文檔
  - 更新 UI docs / Snapshot / Roadmap / Documentation Index 只限描述 V1 落地。

### 不可修改

- `backtest_module/*` 核心計算。
- `app_module/backtest_service.py` 核心執行流程。
- `app_module/recommendation_portfolio_backtest_service.py` replay 計算。
- Portfolio domain 的 append-only trade 重建邏輯。
- 任何正式資料檔或資料根目錄內容。

## 測試策略

V1 測試重點是「UI 語意與既有行為不被破壞」。

最低驗證：

1. 新增 copy test，確認 `BacktestView` 包含：
   - `Research Lab 模式`
   - `實驗模式`
   - `輸入來源`
   - `策略與風控`
   - `執行實驗`
   - `實驗摘要`
   - `歷史與比較`
2. 保留並執行既有 Research Lab taxonomy test。
3. `py_compile ui_qt/views/backtest_view.py`。
4. UI 修改後依 repo 規範執行：
   - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
   - `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
   - `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`

若 mypy 仍出現既有型別債，需記錄完整錯誤摘要，並確認本次改動沒有新增型別錯誤。

## Look-ahead Bias 自查

V1 不修改任何策略、訊號、特徵、篩選、停損停利、benchmark 或績效計算。所有變更停留在 UI 分組與文案層，因此不新增未來函數風險。

若後續 implementation plan 發現需要改 service 或資料選取邏輯，必須另行重新做 look-ahead 自查並更新 spec / plan。

## 風險與緩解

### 風險 1：BacktestView 已很大，重排容易碰壞既有 signal wiring

緩解：

- V1 只改分組與標題，不拆 service。
- 優先保留原 widget 變數名稱與 signal connection。
- 每次移動 widget 後跑 py_compile 與 focused UI tests。

### 風險 2：使用者期望模式切換後自動隱藏不相關控制

緩解：

- V1 明確不做模式驅動隱藏。
- 模式 hint 說清楚主要輸入與用途。
- 第二階段再做「模式驅動 UI」。

### 風險 3：固定組合回測尚未有完整獨立模型

緩解：

- V1 在 UI 中將固定組合列為實驗模式，但不宣稱已提供全新固定組合引擎。
- 若使用者選此模式，第一版仍指向候選池 / 選股清單與既有推薦組合能力。

### 風險 4：文案重整後與既有 docs 不一致

緩解：

- 實作後同步更新 `docs/02_features/UI_FEATURES_DOCUMENTATION.md`。
- 若 Living Section 狀態有變，更新 Snapshot / Roadmap / Index。

## 驗收標準

1. Backtest 左側設定區可被理解為 Research Lab 實驗設定台。
2. 使用者能在第一屏附近看到實驗模式、輸入來源、策略與風控、執行實驗這四個概念。
3. 右側結果區的主要 tabs 以實驗摘要、交易明細、圖表、批次結果、推薦回放、歷史與比較等語意呈現。
4. 既有單股回測、批次回測與推薦回放的 wiring 不被改壞。
5. 無核心金融計算變更。
6. 對應測試與文件更新完成。

## 後續階段

第二階段可以在 V1 穩定後做：

- 模式驅動 UI：依單股 / 批次 / 推薦回放顯示相關設定。
- Candidate Pool → Research Lab 真正一鍵批次 handoff。
- Strategy Center MVP：策略模板、策略版本、回測 run 歷史與升級紀錄。
- 固定組合回測獨立模型與資料 contract。
