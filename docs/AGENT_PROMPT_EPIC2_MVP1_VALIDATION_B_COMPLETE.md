# Agent Prompt: Epic 2 MVP-1 驗證（完整驗證版）

**預估時間**：4-6 小時  
**目標**：完整驗證所有功能，包含邊界條件、錯誤處理、性能測試，並建立完整的驗證腳本與文檔

---

## 1) 任務目標

完整驗證 Epic 2 MVP-1 的所有功能：Walk-Forward 暖機期（warmup_days）與 Baseline 對比（Buy & Hold），確保功能正確性、向後兼容性、錯誤處理完整性，並建立完整的驗證腳本、測試案例與驗證報告供後續維護使用。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

---

## 2) 要驗證的功能清單

### 2.1 Warmup Days 功能（完整驗證）
- [ ] `WalkForwardService.walk_forward()` 方法包含 `warmup_days` 參數（預設 0）
- [ ] `WalkForwardService.train_test_split()` 方法包含 `warmup_days` 參數（預設 0）
- [ ] 訓練期計算從「開始日期 + warmup_days」開始
- [ ] `warmup_days=0` 時行為與修改前完全一致（向後兼容）
- [ ] `warmup_days` 參數正確傳遞到 `WalkForwardResult`
- [ ] `progress_callback` 日期顯示使用實際訓練期開始日期
- [ ] 邊界條件處理（warmup_days 過大、負數等）

### 2.2 Baseline 對比功能（完整驗證）
- [ ] `PerformanceMetrics.calculate_buy_hold_return()` 方法存在且可正常調用
- [ ] `PerformanceMetrics.calculate_baseline_comparison()` 方法存在且可正常調用
- [ ] `BacktestService` 在生成報告時計算 Baseline 對比
- [ ] `BacktestReportDTO.baseline_comparison` 欄位存在且格式正確
- [ ] Baseline 計算支援多種欄位名稱（'收盤價'、'Close'）
- [ ] Baseline 計算正確處理日期索引和日期欄位
- [ ] Baseline 計算正確處理缺值情況

### 2.3 DTO 與報告格式（完整驗證）
- [ ] `BacktestReportDTO` 包含 `baseline_comparison: Optional[Dict[str, Any]] = None`
- [ ] 回測報告的 `to_dict()` 方法包含 Baseline 對比結果（如果存在）
- [ ] `WalkForwardResult` 包含 `warmup_days: int = 0` 欄位
- [ ] 所有新增欄位都有適當的類型提示和文檔

### 2.4 錯誤處理與邊界條件
- [ ] 處理開始日期不存在的情況
- [ ] 處理結束日期不存在的情況
- [ ] 處理期間內缺值的情況
- [ ] 處理 warmup_days 過大的情況
- [ ] 處理負數 warmup_days 的情況
- [ ] 處理空數據的情況

---

## 3) 測試案例設計（完整驗證版 - 20+ 個案例）

### 3.1 Warmup Days 功能測試（8 個案例）

#### 測試案例 1：warmup_days 預設值驗證
**目標**：確認 `warmup_days` 參數預設值為 0，不傳入參數時行為不變

**測試步驟**：
1. 調用 `walk_forward()` 不傳入 `warmup_days` 參數
2. 調用 `train_test_split()` 不傳入 `warmup_days` 參數
3. 驗證結果與傳入 `warmup_days=0` 時一致
4. 驗證 `WalkForwardResult.warmup_days` 為 0

**預期結果**：
- 方法可正常執行，無錯誤
- 訓練期開始日期與修改前一致
- `warmup_days` 欄位值為 0

#### 測試案例 2：warmup_days 功能驗證（正常值）
**目標**：確認 `warmup_days` 參數正確影響訓練期計算

**測試步驟**：
1. 設定 `warmup_days=20`
2. 執行 `walk_forward()` 或 `train_test_split()`
3. 驗證訓練期開始日期 = 原始開始日期 + 20 天
4. 驗證 `WalkForwardResult.warmup_days` 為 20

**預期結果**：
- 訓練期開始日期正確延後 20 天
- `warmup_days` 欄位值為 20

#### 測試案例 3：warmup_days 邊界條件（過大值）
**目標**：確認處理 warmup_days 過大的情況

**測試步驟**：
1. 設定 `warmup_days` 為一個非常大的值（如 1000 天）
2. 執行 `walk_forward()` 或 `train_test_split()`
3. 驗證系統行為（應有適當的錯誤處理或警告）

**預期結果**：
- 系統應檢測到可用數據不足
- 應拋出適當的異常或返回錯誤訊息
- 不應導致系統崩潰

#### 測試案例 4：warmup_days 邊界條件（負數）
**目標**：確認處理負數 warmup_days 的情況

**測試步驟**：
1. 設定 `warmup_days=-10`
2. 執行 `walk_forward()` 或 `train_test_split()`
3. 驗證系統行為

**預期結果**：
- 系統應檢測到負數值
- 應拋出 `ValueError` 或使用絕對值
- 不應導致系統崩潰

#### 測試案例 5：warmup_days 與 Walk-Forward 多個 Fold
**目標**：確認在多個 Fold 的情況下 warmup_days 正確應用

**測試步驟**：
1. 設定 `warmup_days=20`，執行 `walk_forward()` 多個 Fold
2. 驗證每個 Fold 的訓練期都從「開始日期 + warmup_days」開始
3. 驗證所有 `WalkForwardResult` 的 `warmup_days` 都為 20

**預期結果**：
- 每個 Fold 的訓練期都正確應用 warmup_days
- 所有結果的 `warmup_days` 欄位一致

#### 測試案例 6：warmup_days 與 progress_callback
**目標**：確認 progress_callback 顯示的日期使用實際訓練期開始日期

**測試步驟**：
1. 設定 `warmup_days=20`
2. 執行 `walk_forward()` 並提供 progress_callback
3. 驗證 callback 接收到的日期資訊

**預期結果**：
- callback 顯示的日期應為實際訓練期開始日期（原始開始日期 + 20 天）

#### 測試案例 7：warmup_days 與 Train-Test Split
**目標**：確認 train_test_split 正確應用 warmup_days

**測試步驟**：
1. 設定 `warmup_days=20`，執行 `train_test_split()`
2. 驗證訓練期開始日期 = 原始開始日期 + 20 天
3. 驗證測試期不受影響

**預期結果**：
- 訓練期正確應用 warmup_days
- 測試期不受 warmup_days 影響

#### 測試案例 8：warmup_days 向後兼容性（完整驗證）
**目標**：完整驗證現有程式碼行為不變

**測試步驟**：
1. 執行多個現有的 Walk-Forward 測試案例（不傳入 warmup_days）
2. 驗證所有結果與修改前完全一致
3. 驗證性能不受影響

**預期結果**：
- 所有現有測試通過
- 結果與修改前完全一致
- 性能無明顯下降

### 3.2 Baseline 對比功能測試（8 個案例）

#### 測試案例 9：calculate_buy_hold_return 基本功能
**目標**：確認 Buy & Hold 計算方法基本功能正常

**測試步驟**：
1. 準備測試數據（包含 '收盤價' 欄位，日期索引）
2. 調用 `calculate_buy_hold_return(df, '2024-01-01', '2024-12-31')`
3. 驗證返回字典包含必要欄位
4. 驗證數值合理性

**預期結果**：
- 返回字典包含：`total_return`, `annualized_return`, `max_drawdown`, `sharpe_ratio`
- 數值合理（總報酬率在 -1 到 10 之間）

#### 測試案例 10：calculate_buy_hold_return 欄位名稱兼容（'收盤價'）
**目標**：確認方法支援 '收盤價' 欄位名稱

**測試步驟**：
1. 使用 '收盤價' 欄位名稱測試
2. 驗證計算結果正確

**預期結果**：
- 能正確識別 '收盤價' 欄位
- 計算結果正確

#### 測試案例 11：calculate_buy_hold_return 欄位名稱兼容（'Close'）
**目標**：確認方法支援 'Close' 欄位名稱

**測試步驟**：
1. 使用 'Close' 欄位名稱測試
2. 驗證計算結果正確
3. 與 '收盤價' 測試結果對比（如果數據相同）

**預期結果**：
- 能正確識別 'Close' 欄位
- 計算結果正確
- 與 '收盤價' 結果一致（如果數據相同）

#### 測試案例 12：calculate_buy_hold_return 日期索引處理
**目標**：確認方法正確處理日期索引

**測試步驟**：
1. 使用日期索引（`pd.DatetimeIndex`）的 DataFrame 測試
2. 驗證日期查找正確

**預期結果**：
- 能正確處理日期索引
- 日期查找準確

#### 測試案例 13：calculate_buy_hold_return 日期欄位處理
**目標**：確認方法正確處理日期欄位

**測試步驟**：
1. 使用日期欄位（'日期' 或 'Date'）的 DataFrame 測試
2. 驗證日期轉換和查找正確

**預期結果**：
- 能正確處理日期欄位
- 日期轉換和查找準確

#### 測試案例 14：calculate_buy_hold_return 缺值處理（開始日期不存在）
**目標**：確認處理開始日期不存在的情況

**測試步驟**：
1. 準備數據，開始日期不存在（如 '2024-01-01' 不在索引中）
2. 調用 `calculate_buy_hold_return()`，使用不存在的開始日期
3. 驗證系統行為（應使用最接近的日期或拋出異常）

**預期結果**：
- 系統應使用最接近的日期或拋出明確的異常
- 不應導致系統崩潰

#### 測試案例 15：calculate_buy_hold_return 缺值處理（期間內缺值）
**目標**：確認處理期間內缺值的情況

**測試步驟**：
1. 準備數據，期間內有缺值（NaN）
2. 調用 `calculate_buy_hold_return()`
3. 驗證系統行為（應使用前向填充或跳過）

**預期結果**：
- 系統應正確處理缺值（前向填充或跳過）
- 計算結果合理

#### 測試案例 16：calculate_baseline_comparison 基本功能
**目標**：確認 Baseline 對比計算方法基本功能正常

**測試步驟**：
1. 調用 `calculate_baseline_comparison()` 傳入策略和 Baseline 的績效指標
2. 驗證返回字典包含對比結果
3. 驗證計算邏輯正確

**預期結果**：
- 返回字典包含：`excess_returns`, `relative_sharpe`, `relative_max_drawdown`, `outperforms`
- `outperforms` 為布林值，正確反映策略是否優於 Baseline
- 計算邏輯正確（excess_returns = strategy_returns - baseline_returns）

### 3.3 BacktestService 整合測試（4 個案例）

#### 測試案例 17：BacktestService Baseline 整合（基本）
**目標**：確認 BacktestService 正確計算並加入 Baseline 對比

**測試步驟**：
1. 執行一次回測（使用 `BacktestService.run_backtest()`）
2. 檢查返回的 `BacktestReportDTO.baseline_comparison` 欄位
3. 驗證欄位不為 None 且包含必要資訊
4. 驗證格式正確

**預期結果**：
- `baseline_comparison` 不為 None
- 包含 `baseline_type: "buy_hold"` 和所有對比指標
- 格式符合規範

#### 測試案例 18：BacktestService Baseline 整合（空數據）
**目標**：確認處理空數據的情況

**測試步驟**：
1. 執行回測，但數據不足（如只有 1 天數據）
2. 驗證系統行為

**預期結果**：
- 系統應有適當的錯誤處理
- 不應導致系統崩潰

#### 測試案例 19：BacktestService Baseline 整合（多股票）
**目標**：確認在多股票回測時 Baseline 計算正確

**測試步驟**：
1. 執行多股票回測
2. 驗證每個股票的 Baseline 對比都正確計算

**預期結果**：
- 每個股票都有獨立的 Baseline 對比結果
- 計算結果正確

#### 測試案例 20：BacktestService Baseline 整合（性能測試）
**目標**：確認 Baseline 計算不影響回測性能

**測試步驟**：
1. 執行回測並記錄時間
2. 與修改前的回測時間對比
3. 驗證性能無明顯下降

**預期結果**：
- Baseline 計算時間合理（< 100ms）
- 整體回測時間無明顯增加（< 5%）

### 3.4 DTO 與格式測試（4 個案例）

#### 測試案例 21：DTO 欄位存在性驗證
**目標**：確認 DTO 定義正確

**測試步驟**：
1. 檢查 `BacktestReportDTO` 的欄位定義
2. 驗證 `baseline_comparison` 欄位存在且類型為 `Optional[Dict[str, Any]]`
3. 驗證 `WalkForwardResult` 包含 `warmup_days` 欄位
4. 驗證所有新增欄位都有適當的類型提示

**預期結果**：
- 欄位定義正確
- 類型提示完整

#### 測試案例 22：to_dict() 方法驗證
**目標**：確認 `to_dict()` 方法包含新增欄位

**測試步驟**：
1. 創建 `BacktestReportDTO` 實例，包含 `baseline_comparison`
2. 調用 `to_dict()` 方法
3. 驗證輸出包含 `baseline_comparison` 欄位

**預期結果**：
- `to_dict()` 輸出包含 `baseline_comparison`（如果存在）
- 格式正確（字典格式）

#### 測試案例 23：DTO 序列化驗證
**目標**：確認 DTO 可以正確序列化（JSON）

**測試步驟**：
1. 創建 `BacktestReportDTO` 實例
2. 嘗試序列化為 JSON
3. 驗證序列化成功

**預期結果**：
- 可以正確序列化為 JSON
- 無序列化錯誤

#### 測試案例 24：向後兼容性驗證（完整）
**目標**：完整驗證現有程式碼行為不變

**測試步驟**：
1. 執行所有現有的回測測試案例
2. 驗證回測報告格式與修改前一致（除了新增欄位）
3. 驗證不傳入 `warmup_days` 時 Walk-Forward 行為不變
4. 驗證現有 UI 功能正常

**預期結果**：
- 所有現有測試通過
- 回測報告格式不變（除了新增 `baseline_comparison` 欄位）
- 現有功能完全正常運作

---

## 4) 驗收標準

### 4.1 輸出格式驗證（詳細）

**BacktestReportDTO.baseline_comparison 格式**：
```python
{
    'baseline_type': 'buy_hold',        # 必須為字串 'buy_hold'
    'baseline_returns': float,          # 必須為浮點數，範圍 -1.0 到 10.0
    'baseline_sharpe': float,           # 必須為浮點數，範圍 -5.0 到 5.0
    'baseline_max_drawdown': float,     # 必須為浮點數（負數），範圍 -1.0 到 0.0
    'baseline_annualized_return': float, # 必須為浮點數（可選，但建議包含）
    'excess_returns': float,            # 必須為浮點數，策略報酬率 - Baseline 報酬率
    'relative_sharpe': float,          # 必須為浮點數，策略 Sharpe - Baseline Sharpe
    'relative_max_drawdown': float,    # 必須為浮點數，策略回撤 - Baseline 回撤
    'outperforms': bool                 # 必須為布林值，True 表示策略優於 Baseline
}
```

**WalkForwardResult.warmup_days 格式**：
```python
warmup_days: int = 0  # 必須為整數，預設值為 0
```

### 4.2 數值合理性檢查（詳細）

- **總報酬率**：
  - 範圍：-1.0 到 10.0（視市場情況而定）
  - 檢查：不應為 NaN 或 Infinity
- **年化報酬率**：
  - 範圍：-1.0 到 2.0（視期間長度而定）
  - 檢查：不應為 NaN 或 Infinity
- **Sharpe Ratio**：
  - 範圍：-5.0 到 5.0
  - 檢查：不應為 NaN 或 Infinity
- **最大回撤**：
  - 範圍：-1.0 到 0.0（必須為負數或零）
  - 檢查：不應為正數
- **超額報酬率**：
  - 計算：`excess_returns = strategy_returns - baseline_returns`
  - 檢查：計算邏輯正確

### 4.3 欄位存在性檢查（完整）

- [ ] `BacktestReportDTO` 包含 `baseline_comparison: Optional[Dict[str, Any]] = None`
- [ ] `WalkForwardResult` 包含 `warmup_days: int = 0`
- [ ] `PerformanceMetrics` 包含 `calculate_buy_hold_return()` 方法
- [ ] `PerformanceMetrics` 包含 `calculate_baseline_comparison()` 方法
- [ ] 所有新增方法都有完整的 docstring（繁體中文）
- [ ] 所有新增參數都有類型提示

### 4.4 錯誤處理檢查

- [ ] 處理開始日期不存在的情況（使用最接近的日期或拋出異常）
- [ ] 處理結束日期不存在的情況（使用最接近的日期或拋出異常）
- [ ] 處理期間內缺值的情況（前向填充或跳過）
- [ ] 處理 warmup_days 過大的情況（拋出異常或警告）
- [ ] 處理負數 warmup_days 的情況（拋出 ValueError）
- [ ] 處理空數據的情況（拋出適當的異常）

---

## 5) 回滾策略

### 5.1 快速關閉功能（Feature Flag）

如果驗證失敗，可以透過以下方式快速關閉：

**方案 A：環境變數控制**
```python
# 在 app_module/config.py 或環境變數中
ENABLE_BASELINE_COMPARISON = False  # 關閉 Baseline 對比
ENABLE_WARMUP_DAYS = False  # 關閉暖機期功能
```

**方案 B：條件判斷（推薦）**
在 `BacktestService` 中加入條件判斷：
```python
# 在生成回測報告時
if ENABLE_BASELINE_COMPARISON:
    try:
        baseline_comparison = self._calculate_baseline_comparison(...)
    except Exception as e:
        logger.warning(f"Baseline 計算失敗: {e}")
        baseline_comparison = None
else:
    baseline_comparison = None
```

**方案 C：方法級別控制**
在 `WalkForwardService` 中：
```python
def walk_forward(
    self,
    ...,
    warmup_days: int = 0,
    enable_warmup: bool = True  # 新增開關
):
    if not enable_warmup:
        warmup_days = 0
    # ... 後續邏輯
```

### 5.2 Git 回滾

```bash
# 如果所有改動都在單一 commit
git log --oneline -1  # 查看最新 commit hash
git revert <commit_hash>

# 或直接重置
git reset --hard HEAD~1

# 驗證回滾
python -m pytest tests/ -v
```

### 5.3 手動回滾檢查清單

- [ ] 移除 `WalkForwardService` 中的 `warmup_days` 參數
- [ ] 恢復訓練期計算邏輯為原始版本
- [ ] 移除 `PerformanceMetrics` 中的 Baseline 相關方法
- [ ] 移除 `BacktestReportDTO` 中的 `baseline_comparison` 欄位
- [ ] 移除 `BacktestService` 中的 Baseline 計算邏輯
- [ ] 移除 `WalkForwardResult` 中的 `warmup_days` 欄位
- [ ] 驗證所有現有測試通過

---

## 6) 不允許改動的範圍

1. **禁止修改既有 API 行為**：
   - 不得修改 `BacktestService.run_backtest()` 的返回格式（除了新增欄位）
   - 不得修改 `WalkForwardService` 的現有方法簽名（除了新增可選參數）
   - 不得修改 `PerformanceMetrics` 的現有方法

2. **禁止破壞向後兼容**：
   - 所有新增參數必須有預設值
   - 所有新增欄位必須為 `Optional` 或 `None` 預設值
   - 現有程式碼不傳入新參數時行為必須不變
   - 現有測試必須全部通過

3. **禁止引入新模組**：
   - 不得新增業務邏輯模組（`app_module/`, `backtest_module/` 等）
   - 可以新增測試腳本（`scripts/qa_validate_*.py`）
   - 可以新增測試檔案（`tests/test_*.py`）

4. **禁止修改既有回測邏輯**：
   - 不得修改策略執行邏輯
   - 不得修改績效計算邏輯（除了新增 Baseline 計算）
   - 不得修改回測引擎核心邏輯

5. **禁止修改 UI 層核心邏輯**：
   - UI 層僅做顯示擴充，不修改核心業務邏輯
   - 不得修改現有 UI 組件的核心功能

---

## 7) 需要新增的測試腳本

### 7.1 驗證腳本：`scripts/qa_validate_epic2_mvp1.py`

**功能**：執行所有驗證測試案例，生成詳細驗證報告

**必須包含**：
- 所有 24 個測試案例的實作
- 驗證結果輸出（通過/失敗/警告）
- 詳細的驗證報告生成（包含測試結果、數值檢查、錯誤處理等）
- 報告輸出到 `output/qa/epic2_mvp1_validation/`

**範例結構**：
```python
"""
Epic 2 MVP-1 驗證腳本
執行所有驗證測試案例並生成報告
"""

import sys
from pathlib import Path
# ... 其他 import

class Epic2MVP1Validator:
    """Epic 2 MVP-1 驗證器"""
    
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0
    
    def test_warmup_days_default(self):
        """測試案例 1：warmup_days 預設值驗證"""
        # 實作測試邏輯
        pass
    
    # ... 其他測試方法
    
    def run_all_tests(self):
        """執行所有測試"""
        # 執行所有測試案例
        pass
    
    def generate_report(self):
        """生成驗證報告"""
        # 生成 Markdown 報告
        pass

if __name__ == '__main__':
    validator = Epic2MVP1Validator()
    validator.run_all_tests()
    validator.generate_report()
```

### 7.2 單元測試：`tests/test_walkforward_warmup.py`

**功能**：Walk-Forward 暖機期功能的單元測試

**必須包含**：
- warmup_days 參數測試
- 訓練期計算測試
- 邊界條件測試
- 向後兼容性測試

### 7.3 單元測試：`tests/test_baseline_comparison.py`

**功能**：Baseline 對比功能的單元測試

**必須包含**：
- Buy & Hold 計算測試
- Baseline 對比計算測試
- 欄位名稱兼容測試
- 缺值處理測試

---

## 8) 欄位名稱對齊要求（詳細）

### 8.1 Baseline 計算欄位名稱

**必須支援的欄位名稱**：
- `'收盤價'`（繁體中文，現有系統使用）
- `'Close'`（英文，標準格式）

**處理方式**（必須實作）：
```python
def _get_price_column(df: pd.DataFrame) -> str:
    """
    取得價格欄位名稱
    
    Args:
        df: 股票價格數據
    
    Returns:
        價格欄位名稱
    
    Raises:
        ValueError: 如果找不到價格欄位
    """
    if '收盤價' in df.columns:
        return '收盤價'
    elif 'Close' in df.columns:
        return 'Close'
    else:
        raise ValueError(
            "找不到價格欄位。"
            "請確認 DataFrame 包含 '收盤價' 或 'Close' 欄位。"
        )
```

**測試要求**：
- 必須測試兩種欄位名稱
- 必須測試欄位不存在的情況（應拋出 ValueError）

### 8.2 日期索引處理（詳細）

**要求**：
- 支援日期索引（`pd.DatetimeIndex`）
- 支援日期欄位（`'日期'` 或 `'Date'`）
- 如果使用日期欄位，必須能正確轉換為索引
- 日期格式支援：`'YYYY-MM-DD'`, `'YYYY/MM/DD'`, `datetime` 對象

**處理方式**（必須實作）：
```python
def _ensure_date_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    確保 DataFrame 有日期索引
    
    Args:
        df: 股票價格數據
    
    Returns:
        具有日期索引的 DataFrame
    """
    # 如果已有日期索引，直接返回
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    
    # 如果有日期欄位，轉換為索引
    if '日期' in df.columns:
        df = df.set_index('日期')
    elif 'Date' in df.columns:
        df = df.set_index('Date')
    
    # 確保索引為 DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    
    return df
```

**測試要求**：
- 必須測試日期索引的情況
- 必須測試日期欄位的情況
- 必須測試日期格式轉換

---

## 9) 缺值處理要求（詳細）

### 9.1 數據缺值處理

**要求**：
- 如果開始日期不存在，應使用最接近的日期（向後查找）
- 如果結束日期不存在，應使用最接近的日期（向前查找）
- 如果期間內有缺值，應使用前向填充（forward fill）
- 必須處理邊界情況（如開始日期晚於結束日期）

**處理方式**（必須實作）：
```python
def _get_nearest_date(df: pd.DataFrame, target_date: str, direction: str = 'backward') -> str:
    """
    取得最接近的日期
    
    Args:
        df: 股票價格數據（必須有日期索引）
        target_date: 目標日期
        direction: 查找方向（'backward' 或 'forward'）
    
    Returns:
        最接近的日期（字串格式）
    
    Raises:
        ValueError: 如果找不到日期
    """
    target_dt = pd.to_datetime(target_date)
    
    if direction == 'backward':
        # 向後查找（使用 <= target_date 的最大日期）
        available_dates = df.index[df.index <= target_dt]
    else:
        # 向前查找（使用 >= target_date 的最小日期）
        available_dates = df.index[df.index >= target_dt]
    
    if len(available_dates) == 0:
        raise ValueError(f"找不到 {direction} 方向的日期: {target_date}")
    
    nearest_date = available_dates.max() if direction == 'backward' else available_dates.min()
    return nearest_date.strftime('%Y-%m-%d')
```

**測試要求**：
- 必須測試開始日期不存在的情況
- 必須測試結束日期不存在的情況
- 必須測試期間內有缺值的情況
- 必須測試邊界情況（開始日期 = 結束日期、開始日期 > 結束日期）

### 9.2 缺值填充策略

**要求**：
- 使用前向填充（forward fill）處理期間內的缺值
- 如果缺值過多（> 50%），應發出警告或拋出異常
- 必須記錄缺值處理的資訊（可選，但建議）

**處理方式**：
```python
def _handle_missing_values(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """
    處理期間內的缺值
    
    Args:
        df: 股票價格數據
        start_date: 開始日期
        end_date: 結束日期
    
    Returns:
        處理後的 DataFrame
    """
    # 選取期間
    period_df = df.loc[start_date:end_date]
    
    # 檢查缺值比例
    missing_ratio = period_df['收盤價'].isna().sum() / len(period_df)
    if missing_ratio > 0.5:
        logger.warning(f"缺值比例過高: {missing_ratio:.2%}")
    
    # 前向填充
    period_df = period_df.fillna(method='ffill')
    
    # 如果仍有缺值（開頭缺值），使用後向填充
    period_df = period_df.fillna(method='bfill')
    
    return period_df
```

---

## 10) 驗證報告格式要求

### 10.1 報告結構

驗證報告應包含以下章節：

1. **執行摘要**：總體通過率、失敗案例數、警告數
2. **測試結果詳情**：每個測試案例的結果
3. **數值合理性檢查**：所有數值的範圍檢查結果
4. **錯誤處理檢查**：邊界條件和錯誤處理的測試結果
5. **向後兼容性檢查**：現有功能是否正常
6. **建議與後續行動**：發現的問題和改進建議

### 10.2 報告輸出位置

- **報告檔案**：`output/qa/epic2_mvp1_validation/VALIDATION_REPORT.md`
- **詳細日誌**：`output/qa/epic2_mvp1_validation/validation.log`
- **測試數據**：`output/qa/epic2_mvp1_validation/test_data/`（可選）

---

## 11) 檢查清單

### 驗證前檢查
- [ ] 已閱讀相關文檔（`docs/PHASE_3_3B_IMPLEMENTATION_PLAN.md`）
- [ ] 已閱讀研究設計文檔（`docs/PHASE_3_3B_RESEARCH_DESIGN.md`）
- [ ] 已確認實作完成（所有功能已實作）
- [ ] 已準備測試數據（包含各種情況的測試數據）
- [ ] 已準備驗證環境

### 驗證執行
- [ ] 執行所有 24 個測試案例
- [ ] 驗證輸出格式符合要求
- [ ] 驗證數值合理性
- [ ] 驗證向後兼容性
- [ ] 驗證錯誤處理
- [ ] 驗證性能（無明顯下降）

### 驗證後
- [ ] 生成完整驗證報告
- [ ] 記錄所有發現的問題
- [ ] 確認回滾策略已準備
- [ ] 更新相關文檔（如果需要）

---

**版本**：v1.0（完整驗證版）  
**預估時間**：4-6 小時  
**最後更新**：2025-01-XX

