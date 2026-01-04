# Agent Prompt: Epic 2 MVP-1 驗證（最小驗證版）

**預估時間**：1-2 小時  
**目標**：快速驗證核心功能是否正常運作，確保無破壞性變更

---

## 1) 任務目標

驗證 Epic 2 MVP-1 的核心功能：Walk-Forward 暖機期（warmup_days）與 Baseline 對比（Buy & Hold）是否正確實作，確保向後兼容性，並建立基本的驗證腳本供後續使用。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

---

## 2) 要驗證的功能清單

### 2.1 Warmup Days 功能
- [ ] `WalkForwardService.walk_forward()` 方法包含 `warmup_days` 參數（預設 0）
- [ ] `WalkForwardService.train_test_split()` 方法包含 `warmup_days` 參數（預設 0）
- [ ] 訓練期計算從「開始日期 + warmup_days」開始
- [ ] `warmup_days=0` 時行為與修改前完全一致（向後兼容）

### 2.2 Baseline 對比功能
- [ ] `PerformanceMetrics.calculate_buy_hold_return()` 方法存在且可正常調用
- [ ] `PerformanceMetrics.calculate_baseline_comparison()` 方法存在且可正常調用
- [ ] `BacktestService` 在生成報告時計算 Baseline 對比
- [ ] `BacktestReportDTO.baseline_comparison` 欄位存在且格式正確

### 2.3 DTO 與報告格式
- [ ] `BacktestReportDTO` 包含 `baseline_comparison: Optional[Dict[str, Any]] = None`
- [ ] 回測報告的 `to_dict()` 方法包含 Baseline 對比結果（如果存在）

---

## 3) 測試案例設計（最小驗證版 - 8 個核心案例）

### 測試案例 1：warmup_days 預設值驗證
**目標**：確認 `warmup_days` 參數預設值為 0，不傳入參數時行為不變

**測試步驟**：
1. 調用 `walk_forward()` 不傳入 `warmup_days` 參數
2. 調用 `train_test_split()` 不傳入 `warmup_days` 參數
3. 驗證結果與傳入 `warmup_days=0` 時一致

**預期結果**：
- 方法可正常執行，無錯誤
- 訓練期開始日期與修改前一致

### 測試案例 2：warmup_days 功能驗證
**目標**：確認 `warmup_days` 參數正確影響訓練期計算

**測試步驟**：
1. 設定 `warmup_days=20`
2. 執行 `walk_forward()` 或 `train_test_split()`
3. 驗證訓練期開始日期 = 原始開始日期 + 20 天

**預期結果**：
- 訓練期開始日期正確延後 20 天
- `WalkForwardResult.warmup_days` 欄位值為 20

### 測試案例 3：calculate_buy_hold_return 基本功能
**目標**：確認 Buy & Hold 計算方法基本功能正常

**測試步驟**：
1. 準備測試數據（包含 '收盤價' 或 'Close' 欄位）
2. 調用 `calculate_buy_hold_return(df, '2024-01-01', '2024-12-31')`
3. 驗證返回字典包含必要欄位

**預期結果**：
- 返回字典包含：`total_return`, `annualized_return`, `max_drawdown`, `sharpe_ratio`
- 數值合理（總報酬率在 -1 到 10 之間，年化報酬率合理）

### 測試案例 4：calculate_buy_hold_return 欄位名稱兼容
**目標**：確認方法支援 '收盤價' 和 'Close' 兩種欄位名稱

**測試步驟**：
1. 使用 '收盤價' 欄位名稱測試
2. 使用 'Close' 欄位名稱測試
3. 驗證兩種情況都能正常計算

**預期結果**：
- 兩種欄位名稱都能正確識別
- 計算結果一致（如果數據相同）

### 測試案例 5：calculate_baseline_comparison 基本功能
**目標**：確認 Baseline 對比計算方法基本功能正常

**測試步驟**：
1. 調用 `calculate_baseline_comparison()` 傳入策略和 Baseline 的績效指標
2. 驗證返回字典包含對比結果

**預期結果**：
- 返回字典包含：`excess_returns`, `relative_sharpe`, `relative_max_drawdown`, `outperforms`
- `outperforms` 為布林值，正確反映策略是否優於 Baseline

### 測試案例 6：BacktestService Baseline 整合
**目標**：確認 BacktestService 正確計算並加入 Baseline 對比

**測試步驟**：
1. 執行一次回測（使用 `BacktestService.run_backtest()`）
2. 檢查返回的 `BacktestReportDTO.baseline_comparison` 欄位
3. 驗證欄位不為 None 且包含必要資訊

**預期結果**：
- `baseline_comparison` 不為 None
- 包含 `baseline_type: "buy_hold"` 和對比指標

### 測試案例 7：DTO 欄位存在性驗證
**目標**：確認 DTO 定義正確

**測試步驟**：
1. 檢查 `BacktestReportDTO` 的欄位定義
2. 驗證 `baseline_comparison` 欄位存在且類型為 `Optional[Dict[str, Any]]`
3. 驗證 `to_dict()` 方法包含該欄位

**預期結果**：
- 欄位定義正確
- `to_dict()` 輸出包含 `baseline_comparison`（如果存在）

### 測試案例 8：向後兼容性驗證
**目標**：確認現有程式碼行為不變

**測試步驟**：
1. 執行一個簡單的回測（不涉及 Walk-Forward）
2. 驗證回測報告格式與修改前一致
3. 驗證不傳入 `warmup_days` 時 Walk-Forward 行為不變

**預期結果**：
- 回測報告格式不變（除了新增 `baseline_comparison` 欄位）
- 現有功能完全正常運作

---

## 4) 驗收標準

### 4.1 輸出格式驗證

**BacktestReportDTO.baseline_comparison 格式**：
```python
{
    'baseline_type': 'buy_hold',  # 必須為字串
    'baseline_returns': float,     # 必須為浮點數
    'baseline_sharpe': float,      # 必須為浮點數
    'baseline_max_drawdown': float, # 必須為浮點數（負數）
    'excess_returns': float,       # 必須為浮點數
    'relative_sharpe': float,      # 必須為浮點數
    'relative_max_drawdown': float, # 必須為浮點數
    'outperforms': bool            # 必須為布林值
}
```

### 4.2 數值合理性檢查

- **總報酬率**：應在合理範圍內（-1.0 到 10.0，視市場情況而定）
- **年化報酬率**：應在合理範圍內（-1.0 到 2.0，視期間長度而定）
- **Sharpe Ratio**：應在合理範圍內（-5.0 到 5.0）
- **最大回撤**：應為負數或零（-1.0 到 0.0）
- **超額報酬率**：應為策略報酬率減去 Baseline 報酬率

### 4.3 欄位存在性檢查

- [ ] `BacktestReportDTO` 包含 `baseline_comparison` 欄位
- [ ] `WalkForwardResult` 包含 `warmup_days` 欄位
- [ ] `PerformanceMetrics` 包含 `calculate_buy_hold_return()` 方法
- [ ] `PerformanceMetrics` 包含 `calculate_baseline_comparison()` 方法

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

**方案 B：條件判斷**
在 `BacktestService` 中加入條件判斷：
```python
if ENABLE_BASELINE_COMPARISON:
    baseline_comparison = self._calculate_baseline_comparison(...)
else:
    baseline_comparison = None
```

### 5.2 Git 回滾

```bash
# 如果所有改動都在單一 commit
git log --oneline -1  # 查看最新 commit hash
git revert <commit_hash>

# 或直接重置
git reset --hard HEAD~1
```

### 5.3 手動回滾檢查清單

- [ ] 移除 `WalkForwardService` 中的 `warmup_days` 參數
- [ ] 移除 `PerformanceMetrics` 中的 Baseline 相關方法
- [ ] 移除 `BacktestReportDTO` 中的 `baseline_comparison` 欄位
- [ ] 移除 `BacktestService` 中的 Baseline 計算邏輯

---

## 6) 不允許改動的範圍

1. **禁止修改既有 API 行為**：
   - 不得修改 `BacktestService.run_backtest()` 的返回格式（除了新增欄位）
   - 不得修改 `WalkForwardService` 的現有方法簽名（除了新增可選參數）

2. **禁止破壞向後兼容**：
   - 所有新增參數必須有預設值
   - 所有新增欄位必須為 `Optional` 或 `None` 預設值
   - 現有程式碼不傳入新參數時行為必須不變

3. **禁止引入新模組**：
   - 不得新增業務邏輯模組（`app_module/`, `backtest_module/` 等）
   - 可以新增測試腳本（`scripts/qa_validate_*.py`）

4. **禁止修改既有回測邏輯**：
   - 不得修改策略執行邏輯
   - 不得修改績效計算邏輯（除了新增 Baseline 計算）

---

## 7) 需要新增的測試腳本

### 7.1 驗證腳本：`scripts/qa_validate_epic2_mvp1.py`

**功能**：執行所有驗證測試案例，生成驗證報告

**必須包含**：
- 所有 8 個測試案例的實作
- 驗證結果輸出（通過/失敗）
- 簡單的驗證報告生成（可選）

**範例結構**：
```python
def test_warmup_days_default():
    """測試案例 1：warmup_days 預設值驗證"""
    # 實作測試邏輯
    pass

def test_warmup_days_functionality():
    """測試案例 2：warmup_days 功能驗證"""
    # 實作測試邏輯
    pass

# ... 其他測試案例

if __name__ == '__main__':
    # 執行所有測試並生成報告
    pass
```

---

## 8) 欄位名稱對齊要求

### 8.1 Baseline 計算欄位名稱

**必須支援的欄位名稱**：
- `'收盤價'`（繁體中文，現有系統使用）
- `'Close'`（英文，標準格式）

**處理方式**：
```python
# 在 calculate_buy_hold_return() 中
if '收盤價' in df.columns:
    price_col = '收盤價'
elif 'Close' in df.columns:
    price_col = 'Close'
else:
    raise ValueError("找不到價格欄位（'收盤價' 或 'Close'）")
```

### 8.2 日期索引處理

**要求**：
- 支援日期索引（`pd.DatetimeIndex`）
- 支援日期欄位（`'日期'` 或 `'Date'`）
- 如果使用日期欄位，必須能正確轉換為索引

**測試方式**：
- 使用日期索引的 DataFrame 測試
- 使用日期欄位的 DataFrame 測試
- 驗證兩種情況都能正確計算

---

## 9) 缺值處理要求

### 9.1 數據缺值處理

**要求**：
- 如果開始日期或結束日期不存在，應使用最接近的日期
- 如果期間內有缺值，應使用前向填充（forward fill）或跳過
- 必須處理邊界情況（如開始日期晚於結束日期）

**測試方式**：
- 測試開始日期不存在的情況
- 測試結束日期不存在的情況
- 測試期間內有缺值的情況
- 測試邊界情況（開始日期 = 結束日期）

---

## 10) 檢查清單

### 驗證前檢查
- [ ] 已閱讀相關文檔（`docs/PHASE_3_3B_IMPLEMENTATION_PLAN.md`）
- [ ] 已確認實作完成（所有功能已實作）
- [ ] 已準備測試數據

### 驗證執行
- [ ] 執行所有 8 個測試案例
- [ ] 驗證輸出格式符合要求
- [ ] 驗證數值合理性
- [ ] 驗證向後兼容性

### 驗證後
- [ ] 生成驗證報告
- [ ] 記錄發現的問題（如果有）
- [ ] 確認回滾策略已準備

---

**版本**：v1.0（最小驗證版）  
**預估時間**：1-2 小時  
**最後更新**：2025-01-XX

