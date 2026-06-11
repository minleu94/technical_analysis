# 金融 Float 邊界治理設計規格

## 背景

金融核心數值治理已完成第一階段：

- `financial_module/units.py` 已提供 `Decimal`、金額量化、基點與整股 helper。
- `BrokerSimulator` 的交易成本、滑價、稅費與整股計算已移至金融數值邊界。
- Portfolio domain、交易損益統計與推薦組合 PnL 已使用 Decimal 邊界。
- DTO、repository、analytics 與 visualization 仍需要 `float` 以維持相容性或配合 pandas、numpy、Qt 與圖表套件。

目前的缺口是這些合法邊界只靠人工理解。後續修改可能在金融核心重新加入未隔離的 `float` 計算，而既有單元測試不一定能辨識這類架構回歸。

## 目標

1. 建立可由 pytest 執行的靜態治理檢查。
2. 在指定金融核心範圍內，阻擋未標記的 `float` 邊界。
3. 讓合法 DTO、analytics 與 visualization 轉換具有明確、可審查的理由。
4. 不改變現有金融計算結果、公開 DTO 或 UI contract。
5. 保留逐步擴大掃描範圍的能力，但第一版不掃描整個專案。

## 非目標

1. 不全面移除現存 `float`。
2. 不修改策略訊號、推薦排序、回測成交、停損停利或 benchmark 邏輯。
3. 不修改正式資料、SQLite schema 或 CSV fallback。
4. 不新增 Ruff、Flake8 或其他第三方 lint 依賴。
5. 不處理 UI、圖表與資料分析模組中不屬於第一版白名單的 `float`。
6. 不使用檔案級全面放行，避免合法邊界掩蓋新的核心計算。

## 第一版掃描範圍

掃描器只檢查以下金融核心白名單：

- `backtest_module/broker_simulator.py`
- `backtest_module/performance_metrics.py`
- `portfolio_module/core.py`
- `app_module/portfolio_service.py`
- `app_module/recommendation_portfolio_backtest_service.py`
- `app_module/recommendation_portfolio_dtos.py`

此清單集中保存在掃描器模組中，新增範圍必須經過程式碼審查，不從執行期設定或環境變數動態載入。

以下範圍第一版不納入：

- `ui_qt/`
- `app_module/chart_data_service.py`
- `app_module/recommendation_portfolio_metrics.py`
- repository JSON serialization
- 一般推薦分數、資料載入與非金融核心 DTO

這些位置可能合法使用 numpy/pandas float，後續應另行評估，不應讓第一版因大量既有案例失去可操作性。

## 治理標記

合法的轉換必須與對應語句位於同一實體行，並使用以下格式：

```python
value = float(amount)  # numeric-boundary: dto
ratio = float(series.mean())  # numeric-boundary: analytics
point = float(value)  # numeric-boundary: visualization
```

只接受三種分類：

- `dto`：公開 DTO、repository、序列化或既有 contract 的相容轉換。
- `analytics`：Sharpe、Sortino、報酬率、drawdown、統計量等明確分析邊界。
- `visualization`：圖表 payload、Qt widget 或純展示資料轉換。

下列標記無效：

```python
value = float(amount)  # numeric-boundary: allow
value = float(amount)  # numeric-boundary: temporary
```

標記只放行同一行被偵測到的語法，不放行整個函式或檔案。標記不代表該轉換永遠正確；reviewer 仍須確認分類與上下文相符。

## 掃描器設計

新增 `scripts/check_financial_float_boundaries.py`，使用 Python 標準庫 `ast` 與 `tokenize`，不新增外部依賴。

### AST 偵測規則

第一版偵測：

1. `float(...)`
2. `.astype(float)`
3. `.astype("float")`
4. 呼叫中的 `dtype=float`
5. 呼叫中的 `dtype="float"`

掃描器只解析 Python 語法節點，因此不會把註解、文件字串或一般文字中的 `float(` 當成違規。

### 註解解析

`tokenize` 用來建立「行號 → 註解」映射。每個違規 AST 節點以起始行號查找同一行註解；只有完整符合以下模式才放行：

```text
# numeric-boundary: dto
# numeric-boundary: analytics
# numeric-boundary: visualization
```

同一行若有多個受管制節點，一個有效標記可放行該行全部節點。第一版不支援跨行標記，避免標記歸屬不明。

### 結果模型

掃描器回傳結構化 violation，至少包含：

- repo-relative path
- 1-based line number
- column
- rule id
- source expression 類型
- 修正提示

Rule ID：

- `NFB001`：未標記的 `float(...)`
- `NFB002`：未標記的 `.astype(float)` 或 `.astype("float")`
- `NFB003`：未標記的 `dtype=float` 或 `dtype="float"`
- `NFB004`：存在 `numeric-boundary` 標記，但分類不合法

### 命令列介面

預設執行：

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

行為：

- 掃描固定白名單。
- 無 violation 時 exit code 為 `0`。
- 有 violation、語法錯誤或白名單檔案不存在時 exit code 為 `1`。
- 每筆 violation 使用 `path:line:column rule message` 格式輸出，方便 IDE 與 CI 閱讀。

掃描器另提供純函式 API，讓單元測試可對暫存 source 或指定路徑驗證，不依賴 subprocess。

## 測試策略

依 TDD 實作，先建立失敗測試，再寫掃描器。

### 掃描器單元測試

新增 `tests/test_financial_float_boundary_checker.py`，涵蓋：

1. 未標記 `float(...)` 產生 `NFB001`。
2. `dto`、`analytics`、`visualization` 標記可放行。
3. 非法分類產生 `NFB004`。
4. `.astype(float)` 與 `.astype("float")` 產生 `NFB002`。
5. `dtype=float` 與 `dtype="float"` 產生 `NFB003`。
6. 註解或字串中的 `float(` 不產生 violation。
7. 前一行標記不會放行下一行。
8. 語法錯誤以明確 violation 或檢查錯誤回報。

### Repository 治理測試

同一測試檔加入 repository-level 測試，呼叫固定白名單掃描並要求零 violation。這個測試是防止回歸的主要 gate。

### 既有程式標記

掃描器測試轉綠後，逐行檢視白名單中的現存 `float`：

- DTO／service 回傳相容邊界標記為 `dto`。
- 報酬率、Sharpe、drawdown 與 pandas/numpy 統計標記為 `analytics`。
- 第一版白名單原則上不應需要 `visualization`；若出現，必須確認該檔案確實在建立展示 payload。
- 若某處實際屬於核心金額、成本、股數或倉位計算，不得加標記規避，必須改用既有 Decimal helper。

## Look-ahead Bias 自查

本變更只讀取 Python source 並檢查語法，不執行策略、推薦或回測資料流。

- 不改訊號日期。
- 不改特徵窗口或標準化樣本。
- 不改 universe 排序或篩選。
- 不改成交日期、成交價格、停損停利或 equity curve。
- 不改 benchmark 對齊。

因此本設計不引入新的未來函數路徑。實作期間若發現需要修改上述行為，必須停止並另開設計與 Look-ahead 審查。

## 錯誤處理

- 白名單檔案不存在：視為治理設定失效，檢查失敗。
- Python source 無法解析：視為檢查失敗，不靜默略過。
- 無法讀取檔案：回報檔案與例外摘要，檢查失敗。
- 非法標記：回報 `NFB004`，不可視為未標記後自動猜測分類。

## 文件同步

實作完成時更新：

- `docs/00_core/DEVELOPMENT_ROADMAP.md`：將 analytics／visualization float 邊界制度化標記完成。
- `docs/00_core/PROJECT_SNAPSHOT.md`：同步本週優先事項與治理狀態。
- `docs/00_core/NEXT_ACTION_PLAN.md`：記錄 P0 金融核心數值治理收尾狀態。
- `docs/00_core/DOCUMENTATION_INDEX.md`：加入本規格與實作計畫入口。

因第一版不改使用者操作、UI 或金融計算結果，不需要更新 USER_GUIDE 或 UI 功能文件。

## 驗收標準

1. 掃描器單元測試全部通過。
2. Repository 治理測試對固定白名單回報零 violation。
3. 在白名單檔案新增未標記 `float(...)` 時，測試可穩定失敗。
4. 合法標記只接受 `dto`、`analytics`、`visualization`。
5. 不新增第三方依賴。
6. 現有金融數值治理測試全部通過。
7. 變更 Python 檔案通過 `py_compile`。
8. `mypy` 不新增錯誤。

## 回滾策略

此治理只新增靜態檢查、測試與註解。回滾時可：

1. 移除 repository-level 治理測試。
2. 移除掃描器。
3. 移除純治理標記註解。
4. 保留既有 Decimal 金融核心實作，不回退已完成的數值治理。

回滾不涉及正式資料或資料庫。
