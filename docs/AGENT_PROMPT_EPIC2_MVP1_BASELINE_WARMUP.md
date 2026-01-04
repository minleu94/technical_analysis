# Agent Prompt: Epic 2 MVP-1 - Walk-Forward 暖機期與 Baseline 對比

## 1) 任務目標

實作 Epic 2 的 MVP-1 版本：在 `WalkForwardService` 中加入 `warmup_days` 參數（預設 0，向後兼容），並在回測報告中加入 Baseline 對比功能（至少實作 Buy & Hold 基準策略），為後續 Promote 機制提供穩健性驗證基礎。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

## 2) 影響範圍

### 需要修改的檔案

1. **`app_module/walkforward_service.py`**（擴充）
   - 在 `walk_forward()` 方法中新增 `warmup_days` 參數（預設 0）
   - 修改訓練期計算邏輯：訓練期從「開始日期 + warmup_days」開始計算
   - 在 `WalkForwardResult` 中新增 `warmup_days` 欄位（可選）

2. **`backtest_module/performance_metrics.py`**（擴充）
   - 新增 `calculate_buy_hold_return()` 方法：計算 Buy & Hold 策略的報酬率
   - 新增 `calculate_baseline_comparison()` 方法：計算策略相對於 Baseline 的對比結果

3. **`app_module/backtest_service.py`**（擴充）
   - 在回測報告生成時計算 Baseline 對比
   - 在 `BacktestReportDTO` 中新增 `baseline_comparison` 欄位

4. **`app_module/dtos.py`**（擴充）
   - 在 `BacktestReportDTO` 中新增 `baseline_comparison: Optional[Dict[str, Any]]` 欄位

5. **`ui_qt/views/backtest_view.py`**（擴充，可選）
   - 在 Walk-forward 驗證 UI 中顯示 Baseline 對比結果（如果時間允許）

### 不需要修改的檔案

- ❌ 不修改 `app_module/preset_service.py`
- ❌ 不修改 `app_module/recommendation_service.py`
- ❌ 不實作過擬合風險提示
- ❌ 不實作多個 Baseline 策略（僅 Buy & Hold）
- ❌ 不實作可調整的 warmup 長度（固定使用參數值）

## 3) 明確禁止事項

1. **禁止修改業務邏輯**：不得修改現有的回測邏輯、策略執行邏輯、績效計算邏輯
2. **禁止破壞向後兼容**：`warmup_days` 必須有預設值 0，確保現有程式碼不傳入此參數時行為不變
3. **禁止修改測試檔案**：不得修改任何 `tests/` 目錄下的檔案（除非是新增測試）
4. **禁止使用簡體中文**：所有程式碼註解、文件字串（docstring）、變數名稱、註釋必須使用繁體中文，嚴禁使用簡體中文
5. **禁止實作過擬合風險提示**：本次任務不包含過擬合風險提示功能
6. **禁止實作多個 Baseline**：本次任務僅實作 Buy & Hold，不實作 Random Entry 或其他 Baseline
7. **禁止修改 UI 層核心邏輯**：UI 層僅做顯示擴充，不修改核心業務邏輯
8. **禁止跳過驗證步驟**：必須完整執行所有檢查與驗證步驟

## 4) 實作步驟

### Step 4.1: 擴充 WalkForwardService 加入 warmup_days 參數

**檔案：`app_module/walkforward_service.py`**

**操作**：
1. 在 `walk_forward()` 方法簽名中新增 `warmup_days: int = 0` 參數
2. 修改訓練期計算邏輯：
   ```python
   # 舊的邏輯（約第 151-153 行）
   # train_end = current_start + timedelta(days=train_months * 30)
   
   # 新的邏輯
   # 計算實際訓練期開始（從開始日期 + warmup_days 開始）
   actual_train_start = current_start + timedelta(days=warmup_days)
   train_end = actual_train_start + timedelta(days=train_months * 30)
   ```
3. 在執行訓練集回測時，使用 `actual_train_start` 作為開始日期
4. 在 `WalkForwardResult` 中新增 `warmup_days: int` 欄位（記錄使用的暖機期天數）
5. 在 `train_test_split()` 方法中也新增 `warmup_days: int = 0` 參數（保持一致性）

**注意事項**：
- `warmup_days` 預設值必須為 0，確保向後兼容
- 訓練期計算時需要確保 `actual_train_start` 不晚於 `end_date`
- 如果 `warmup_days` 過大導致可用數據不足，應在文檔中說明或加入警告

### Step 4.2: 實作 Baseline 對比功能

**檔案：`backtest_module/performance_metrics.py`**

**操作**：
1. 新增 `calculate_buy_hold_return()` 方法：
   ```python
   def calculate_buy_hold_return(
       self,
       df: pd.DataFrame,
       start_date: str,
       end_date: str
   ) -> Dict[str, float]:
       """
       計算 Buy & Hold 策略的報酬率
       
       Args:
           df: 股票價格數據（必須包含 '收盤價' 欄位）
           start_date: 開始日期（YYYY-MM-DD）
           end_date: 結束日期（YYYY-MM-DD）
       
       Returns:
           包含總報酬率、年化報酬率、最大回撤等指標的字典
       """
       # 實作邏輯：
       # 1. 取得開始日期和結束日期的收盤價
       # 2. 計算總報酬率 = (end_price - start_price) / start_price
       # 3. 計算年化報酬率（根據天數）
       # 4. 計算最大回撤（期間內最高點到最低點的跌幅）
       # 5. 返回字典
   ```

2. 新增 `calculate_baseline_comparison()` 方法：
   ```python
   def calculate_baseline_comparison(
       self,
       strategy_returns: float,
       strategy_sharpe: float,
       strategy_max_drawdown: float,
       baseline_returns: float,
       baseline_sharpe: float,
       baseline_max_drawdown: float
   ) -> Dict[str, Any]:
       """
       計算策略相對於 Baseline 的對比結果
       
       Args:
           strategy_returns: 策略總報酬率
           strategy_sharpe: 策略 Sharpe Ratio
           strategy_max_drawdown: 策略最大回撤
           baseline_returns: Baseline 總報酬率
           baseline_sharpe: Baseline Sharpe Ratio
           baseline_max_drawdown: Baseline 最大回撤
       
       Returns:
           包含對比結果的字典（超額報酬率、相對 Sharpe、相對回撤等）
       """
       # 實作邏輯：
       # 1. 計算超額報酬率 = strategy_returns - baseline_returns
       # 2. 計算相對 Sharpe = strategy_sharpe - baseline_sharpe
       # 3. 計算相對回撤 = strategy_max_drawdown - baseline_max_drawdown
       # 4. 判斷是否優於 Baseline（策略報酬率 > Baseline 報酬率）
       # 5. 返回字典
   ```

### Step 4.3: 在 BacktestService 中整合 Baseline 對比

**檔案：`app_module/backtest_service.py`**

**操作**：
1. 在生成回測報告時，計算 Buy & Hold Baseline：
   ```python
   # 在生成 BacktestReportDTO 的地方（約在 run_backtest() 方法中）
   # 1. 取得回測期間的股票價格數據
   # 2. 調用 performance_metrics.calculate_buy_hold_return()
   # 3. 調用 performance_metrics.calculate_baseline_comparison()
   # 4. 將結果加入 BacktestReportDTO.baseline_comparison
   ```

2. 確保 Baseline 對比結果包含：
   - `baseline_type: str`（如 "buy_hold"）
   - `baseline_returns: float`
   - `baseline_sharpe: float`
   - `baseline_max_drawdown: float`
   - `excess_returns: float`（策略相對於 Baseline 的超額報酬率）
   - `outperforms: bool`（策略是否優於 Baseline）

### Step 4.4: 更新 DTO 定義

**檔案：`app_module/dtos.py`**

**操作**：
1. 在 `BacktestReportDTO` 中新增欄位：
   ```python
   baseline_comparison: Optional[Dict[str, Any]] = None
   ```
2. 確保欄位有適當的類型提示和文檔說明

### Step 4.5: 更新 UI 顯示（可選，如果時間允許）

**檔案：`ui_qt/views/backtest_view.py`**

**操作**：
1. 在回測結果顯示區域加入 Baseline 對比資訊
2. 顯示超額報酬率、是否優於 Baseline 等關鍵指標
3. 如果時間不足，可以僅在後端實作，UI 顯示留待後續任務

## 5) 完成條件

### 5.1 靜態檢查
- [ ] `WalkForwardService.walk_forward()` 已新增 `warmup_days` 參數（預設 0）
- [ ] `WalkForwardService.train_test_split()` 已新增 `warmup_days` 參數（預設 0）
- [ ] 訓練期計算邏輯已更新為從「開始日期 + warmup_days」開始
- [ ] `PerformanceMetrics` 已新增 `calculate_buy_hold_return()` 方法
- [ ] `PerformanceMetrics` 已新增 `calculate_baseline_comparison()` 方法
- [ ] `BacktestReportDTO` 已新增 `baseline_comparison` 欄位
- [ ] `BacktestService` 已在回測報告生成時計算 Baseline 對比
- [ ] 所有程式碼註解、文件字串使用繁體中文，無簡體中文

### 5.2 功能驗證

**驗證 warmup_days 功能**：
```bash
# 1. 驗證預設值為 0（向後兼容）
python -c "
from app_module.walkforward_service import WalkForwardService
from app_module.backtest_service import BacktestService
from data_module.config import TWStockConfig

config = TWStockConfig()
backtest_service = BacktestService(config)
wf_service = WalkForwardService(backtest_service)

# 檢查方法簽名是否包含 warmup_days 參數
import inspect
sig = inspect.signature(wf_service.walk_forward)
assert 'warmup_days' in sig.parameters
assert sig.parameters['warmup_days'].default == 0
print('✓ warmup_days 參數已正確加入，預設值為 0')
"

# 2. 驗證 warmup_days 不影響現有行為（當 warmup_days=0 時）
# 執行一個簡單的 walk_forward 測試，確認結果與修改前一致
```

**驗證 Baseline 對比功能**：
```bash
# 1. 驗證 calculate_buy_hold_return 方法
python -c "
from backtest_module.performance_metrics import PerformanceMetrics
import pandas as pd
from datetime import datetime, timedelta

pm = PerformanceMetrics()

# 創建測試數據
dates = pd.date_range('2024-01-01', '2024-12-31', freq='D')
df = pd.DataFrame({
    '收盤價': [100 + i * 0.1 for i in range(len(dates))],
    '日期': dates
})
df.set_index('日期', inplace=True)

result = pm.calculate_buy_hold_return(df, '2024-01-01', '2024-12-31')
assert 'total_return' in result
assert 'annualized_return' in result
print('✓ calculate_buy_hold_return 方法正常運作')
"

# 2. 驗證 calculate_baseline_comparison 方法
python -c "
from backtest_module.performance_metrics import PerformanceMetrics

pm = PerformanceMetrics()
result = pm.calculate_baseline_comparison(
    strategy_returns=0.15,
    strategy_sharpe=1.2,
    strategy_max_drawdown=-0.1,
    baseline_returns=0.10,
    baseline_sharpe=0.8,
    baseline_max_drawdown=-0.15
)
assert 'excess_returns' in result
assert 'outperforms' in result
print('✓ calculate_baseline_comparison 方法正常運作')
"

# 3. 驗證 BacktestService 整合
python -c "
from app_module.backtest_service import BacktestService
from data_module.config import TWStockConfig

config = TWStockConfig()
service = BacktestService(config)

# 檢查 BacktestReportDTO 是否有 baseline_comparison 欄位
from app_module.dtos import BacktestReportDTO
import dataclasses

fields = [f.name for f in dataclasses.fields(BacktestReportDTO)]
assert 'baseline_comparison' in fields
print('✓ BacktestReportDTO 已包含 baseline_comparison 欄位')
"
```

### 5.3 向後兼容性驗證
- [ ] 現有程式碼不傳入 `warmup_days` 參數時，行為與修改前完全一致
- [ ] 現有測試通過（如果有的話）
- [ ] `warmup_days=0` 時，訓練期計算邏輯與修改前一致

### 5.4 完整性驗證
- [ ] 所有新增方法都有完整的 docstring（繁體中文）
- [ ] 所有新增參數都有類型提示
- [ ] 無語法錯誤
- [ ] 無未使用的 import

## 6) 回退方式

### 6.1 Git 回退（推薦）
```bash
# 如果所有改動都在單一 commit
git log --oneline -1  # 查看最新 commit hash
git revert <commit_hash>

# 或直接重置到改動前
git reset --hard HEAD~1  # 如果只有一個 commit
git reset --hard <previous_commit_hash>  # 如果有多個 commit
```

### 6.2 手動回退步驟

**Step 1: 恢復 WalkForwardService**
- 移除 `walk_forward()` 和 `train_test_split()` 方法中的 `warmup_days` 參數
- 恢復訓練期計算邏輯為原始版本

**Step 2: 恢復 PerformanceMetrics**
- 刪除 `calculate_buy_hold_return()` 方法
- 刪除 `calculate_baseline_comparison()` 方法

**Step 3: 恢復 BacktestService**
- 移除 Baseline 對比計算邏輯
- 恢復回測報告生成邏輯為原始版本

**Step 4: 恢復 DTO 定義**
- 從 `BacktestReportDTO` 中移除 `baseline_comparison` 欄位

### 6.3 回退驗證
```bash
# 確認所有修改已恢復
grep -r "warmup_days" app_module/walkforward_service.py
# 預期輸出：無結果

grep -r "baseline_comparison" app_module/
# 預期輸出：無結果（或只有註解中的舊引用）

# 執行測試確認功能恢復
python -m pytest tests/ -v
```

---

## 檢查清單

- [ ] **warmup_days 參數**：已加入 `walk_forward()` 和 `train_test_split()` 方法，預設值為 0
- [ ] **訓練期計算**：已更新為從「開始日期 + warmup_days」開始計算
- [ ] **Baseline 計算**：已實作 `calculate_buy_hold_return()` 方法
- [ ] **Baseline 對比**：已實作 `calculate_baseline_comparison()` 方法
- [ ] **DTO 更新**：`BacktestReportDTO` 已新增 `baseline_comparison` 欄位
- [ ] **服務整合**：`BacktestService` 已在回測報告生成時計算 Baseline 對比
- [ ] **繁體中文檢查**：所有程式碼註解、文件字串使用繁體中文，無簡體中文
- [ ] **向後兼容**：現有程式碼不傳入 `warmup_days` 時行為不變
- [ ] **功能測試**：所有新增功能通過驗證
- [ ] **回退準備**：所有改動已 commit，可隨時回退

---

## 版本/變更註記

### v1.0 (2025-01-XX)
- 初始版本：Epic 2 MVP-1 - Walk-Forward 暖機期與 Baseline 對比
- 完成 `warmup_days` 參數實作（預設 0，向後兼容）
- 完成 Buy & Hold Baseline 對比功能
- 保持 100% 向後兼容性

