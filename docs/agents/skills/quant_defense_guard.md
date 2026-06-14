# Skill: Quant Defense Guard (量化防禦與未來函數審查)

> 適用於對策略、回測、推薦、績效、風控與資金等金融核心模組進行 Code Review 或程式碼變更前/後的合規性檢查。

---

## 1. 核心原則

為維護量化交易系統的數據真實性與精度，所有 AI Agent 必須遵守以下兩項量化防禦核心條款：

### 1.1 精度防禦（無裸 Float 條款）
*   **原則**：金融核心數值（PnL、均價、交易手續費、滑價）必須使用 `Decimal` 或整數單位（分、股、基點）。
*   **例外隔離**：如果第三方套件（如 talib, matplotlib）或繪圖需要 float，必須在資料分析/展示邊界進行隔離轉換，不能污染策略決策層。
*   **標記註解**：在允許使用 float 的邊界程式碼行尾，必須加上 `# numeric-boundary: <category>` 標記（如 `dto`, `analytics`, `visualization`）。

### 1.2 未來函數防禦（No Look-Ahead Leaks）
*   **原則**：歷史回測與推薦重播，在 $T$ 日生成信號或評分時，**僅能使用 $T-1$ 以前的資料**，嚴禁存取未來任何時點的價格或量能資料。
*   **例外隔離**：橫斷面排名計算，必須先固定當日 eligible universe，再對該日已實現分數進行排名，禁止跨日計算分位數。

---

## 2. 檢測工具與使用方式

本專案已建立專屬的一鍵式靜態 AST 量化合規檢測工具。

### 執行檢測命令
在修改任何代碼或進行 PR Review 前，必須在專案根目錄下執行：
```powershell
.\.venv\Scripts\python.exe scripts/quant_guard_linter.py
```

### 工具運作機制
1.  **`check_financial_float_boundaries.py`**：遍歷金融白名單檔案，偵測是否有未標記註解的 `float(...)`、`.astype(float)` 或 `dtype=float`。
2.  **`check_look_ahead_bias.py`**：檢測策略執行器中，在 iteration 迴圈內是否有對迴圈索引變數進行非法加法運算（如 `iloc[i + 1]` 或 `i + 2` 跨期存取），自動排除合理的 exclusive 切片上界 `i + 1`。

### 能力邊界

- 兩個檢查器都是白名單式靜態 Gate，不等同完整的策略正確性證明。
- Look-ahead AST 規則目前聚焦 `for` 迴圈索引向前存取；全期間標準化、錯誤資料可得日、跨函式資料洩漏與 benchmark 對齊仍須以單元測試和人工 review 驗證。
- 管理檔案缺失、無法讀取或 Python 語法無法解析時必須 fail-closed，回傳非零 exit code。
- 每次策略、回測、推薦或 factor 改動仍須新增符合實際資料流的 no-look-ahead 測試，不能只依賴 linter 綠燈。

---

## 3. 合規審查白名單

精度防禦主要針對以下金融核心白名單檔案進行強檢：
- `backtest_module/broker_simulator.py`
- `backtest_module/performance_metrics.py`
- `portfolio_module/core.py`
- `app_module/portfolio_service.py`
- `app_module/portfolio_condition_monitor.py`
- `app_module/recommendation_portfolio_backtest_service.py`
- `app_module/recommendation_portfolio_dtos.py`

未來函數審查主要針對以下策略檔案進行強檢：
- `app_module/strategies/baseline_score_executor.py`
- `app_module/strategies/momentum_aggressive_executor.py`
- `app_module/strategies/stable_conservative_executor.py`

---

## 4. 更新記錄

- 2026-06-14：建立 Quant Defense Guard 技能，發布一鍵式量化檢查工具 `quant_guard_linter.py`，並補上 fail-closed 與能力邊界。
