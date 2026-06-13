# Strategy & Scoring Governance A: Backtest Thresholds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為 Baseline、Momentum Aggressive、Stable Conservative 加入 fixed / expanding quantile 雙模式門檻，並保持 fixed 結果完全相容。

**Architecture:** 在 `decision_module/score_threshold_policy.py` 建立純決策元件。quantile 路徑先用 `Decimal` 量化分數，再以排序歷史樣本計算 T-1 nearest-rank；fixed 路徑保留既有 pandas 比較語義。executor 只消費候選布林序列，確認天數與 cooldown 邏輯不改。

**Tech Stack:** Python、Decimal、bisect、pandas、PySide6、pytest、mypy。

---

## Task 1：建立門檻元件契約

**Files:**
- Create: `tests/test_score_threshold_policy.py`

- [ ] **Step 1: 寫量化與參數驗證失敗測試**

```python
def test_quantize_score_uses_decimal_half_up():
    assert quantize_score_to_basis_points("60.005") == 6001
    assert quantize_score_to_basis_points(0) == 0
    assert quantize_score_to_basis_points(100) == 10000


@pytest.mark.parametrize("params", [
    {"threshold_mode": "bad"},
    {"threshold_mode": "quantile", "buy_quantile_bp": 4000,
     "sell_quantile_bp": 4000, "quantile_warmup_observations": 60,
     "quantile_method": "nearest_rank"},
])
def test_invalid_threshold_params_are_rejected(params):
    with pytest.raises(ValueError):
        ScoreThresholdPolicy(params)
```

- [ ] **Step 2: 寫 T-1、暖機、NaN 與未來資料不變性測試**

```python
def test_quantile_threshold_uses_only_prior_valid_observations():
    scores = pd.Series([10] * 59 + [90, 95], index=pd.date_range("2026-01-01", periods=61))
    result = ScoreThresholdPolicy(quantile_params()).evaluate(scores)
    assert not result.warmup_ready.iloc[:60].any()
    assert result.warmup_ready.iloc[60]
    assert result.buy_threshold_score_bp.iloc[60] == 1000


def test_appending_future_scores_does_not_change_existing_thresholds():
    original = pd.Series(range(61), index=pd.date_range("2026-01-01", periods=61))
    extended = pd.concat([original, pd.Series([100, 0], index=pd.date_range("2026-03-03", periods=2))])
    policy = ScoreThresholdPolicy(quantile_params())
    pd.testing.assert_frame_equal(
        policy.evaluate(original).to_frame(),
        policy.evaluate(extended).to_frame().iloc[:len(original)],
    )
```

- [ ] **Step 3: 執行並確認模組不存在**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_score_threshold_policy.py -q -o addopts=
```

- [ ] **Step 4: 提交失敗測試**

```powershell
git add tests/test_score_threshold_policy.py
git commit -m "test(scoring): define score threshold policy contract"
```

## Task 2：實作純門檻元件

**Files:**
- Create: `decision_module/score_threshold_policy.py`
- Modify: `tests/test_score_threshold_policy.py`

- [ ] **Step 1: 建立固定 API**

```python
@dataclass(frozen=True)
class ScoreThresholdResult:
    score_bp: pd.Series
    buy_threshold_score_bp: pd.Series
    sell_threshold_score_bp: pd.Series
    warmup_ready: pd.Series
    buy_candidate: pd.Series
    sell_candidate: pd.Series

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({
            "score_bp": self.score_bp,
            "buy_threshold_score_bp": self.buy_threshold_score_bp,
            "sell_threshold_score_bp": self.sell_threshold_score_bp,
            "threshold_warmup_ready": self.warmup_ready,
            "buy_threshold_hit": self.buy_candidate,
            "sell_threshold_hit": self.sell_candidate,
        })
```

- [ ] **Step 2: 用 Decimal 實作量化**

```python
def quantize_score_to_basis_points(value: object) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    score = Decimal(str(value))
    if score < Decimal("0") or score > Decimal("100"):
        raise ValueError("score must be between 0 and 100")
    return int((score * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

- [ ] **Step 3: fixed 分支保留舊比較**

```python
buy_candidate = scores >= self.buy_score
sell_candidate = scores <= self.sell_score
```

不得先量化再比較，否則會改變既有小數邊界訊號。量化欄位只供診斷使用。

- [ ] **Step 4: quantile 分支先計算、後插入今日值**

```python
history: list[int] = []
for position, raw_score in enumerate(scores):
    current_bp = quantize_score_to_basis_points(raw_score)
    if len(history) >= self.warmup_observations and current_bp is not None:
        buy_threshold = nearest_rank(history, self.buy_quantile_bp)
        sell_threshold = nearest_rank(history, self.sell_quantile_bp)
        buy_candidate.iloc[position] = current_bp >= buy_threshold
        sell_candidate.iloc[position] = current_bp <= sell_threshold
        warmup_ready.iloc[position] = True
    if current_bp is not None:
        insort(history, current_bp)
```

```python
def nearest_rank(sorted_values: Sequence[int], quantile_bp: int) -> int:
    rank = max(1, (len(sorted_values) * quantile_bp + 9999) // 10000)
    return sorted_values[rank - 1]
```

- [ ] **Step 5: 驗證 0/10000、全同分、非法 method、暖機值非 60**
- [ ] **Step 6: 執行測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_score_threshold_policy.py -q -o addopts=
```

- [ ] **Step 7: 提交**

```powershell
git add decision_module/score_threshold_policy.py tests/test_score_threshold_policy.py
git commit -m "feat(scoring): add historical score threshold policy"
```

## Task 3：鎖定三個 executor 的相容性

**Files:**
- Create: `tests/test_strategy_threshold_modes.py`

- [ ] **Step 1: 參數化測試缺少 mode 與明確 fixed 的 signal 完全相同**
- [ ] **Step 2: 保存變更前已知 signal 序列，避免兩個新分支一起錯**
- [ ] **Step 3: 測試 quantile 第 61 個有效觀測才可能產生候選條件**
- [ ] **Step 4: 測試附加未來資料不改變既有 signal**
- [ ] **Step 5: 執行並確認 executor 尚未輸出門檻欄位**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_strategy_threshold_modes.py -q -o addopts=
```

- [ ] **Step 6: 提交測試**

```powershell
git add tests/test_strategy_threshold_modes.py
git commit -m "test(strategies): lock fixed and quantile threshold behavior"
```

## Task 4：接入 Baseline executor

**Files:**
- Modify: `app_module/strategies/baseline_score_executor.py`

- [ ] **Step 1: 從 `spec.config["params"]` 初始化 policy**
- [ ] **Step 2: 在分數計算後取得 thresholds**

```python
thresholds = self.threshold_policy.evaluate(df["TotalScore"])
signals = self._generate_signals_with_cooldown(
    df=df,
    buy_candidate=thresholds.buy_candidate,
    sell_candidate=thresholds.sell_candidate,
)
```

- [ ] **Step 3: `_generate_signals_with_cooldown` 移除固定比較，但不動確認與 cooldown**
- [ ] **Step 4: 將 `thresholds.to_frame()` 六欄加入 DailySignalFrame**
- [ ] **Step 5: 執行 Baseline 測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_strategy_threshold_modes.py -q -o addopts= -k baseline
```

- [ ] **Step 6: 提交**

```powershell
git add app_module/strategies/baseline_score_executor.py
git commit -m "feat(strategy): add dual thresholds to baseline executor"
```

## Task 5：接入 Momentum 與 Stable executor

**Files:**
- Modify: `app_module/strategies/momentum_aggressive_executor.py`
- Modify: `app_module/strategies/stable_conservative_executor.py`

- [ ] **Step 1: 套用與 Baseline 相同 policy 契約**
- [ ] **Step 2: 保留各策略自己的 fixed 預設、確認天數與 cooldown**
- [ ] **Step 3: 執行三策略回歸**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_strategy_threshold_modes.py tests\test_backtest_diagnostics_and_date_adjustment.py -q -o addopts=
```

- [ ] **Step 4: 提交**

```powershell
git add app_module/strategies/momentum_aggressive_executor.py app_module/strategies/stable_conservative_executor.py
git commit -m "feat(strategy): add dual thresholds to production executors"
```

## Task 6：改造回測診斷

**Files:**
- Modify: `app_module/backtest_service.py`
- Modify: `tests/test_backtest_diagnostics_and_date_adjustment.py`

- [ ] **Step 1: 寫 quantile 診斷失敗測試**

期望至少包含：

```python
{
    "threshold_mode": "quantile",
    "buy_quantile_bp": 8000,
    "sell_quantile_bp": 4000,
    "quantile_warmup_observations": 60,
    "quantile_method": "nearest_rank",
    "warmup_ready_days": 1,
    "buy_hit_days": 1,
    "sell_hit_days": 0,
}
```

- [ ] **Step 2: quantile 只讀 signal frame 診斷欄位，不在 service 重算分位數**
- [ ] **Step 3: fixed 繼續輸出既有 `buy_score` / `sell_score`**
- [ ] **Step 4: 執行測試並提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_backtest_diagnostics_and_date_adjustment.py -q -o addopts=
git add app_module/backtest_service.py tests/test_backtest_diagnostics_and_date_adjustment.py
git commit -m "feat(backtest): report threshold mode diagnostics"
```

## Task 7：策略 metadata 與回測 UI

**Files:**
- Modify: `app_module/strategies/baseline_score_executor.py`
- Modify: `app_module/strategies/momentum_aggressive_executor.py`
- Modify: `app_module/strategies/stable_conservative_executor.py`
- Modify: `ui_qt/views/backtest_view.py`
- Modify: `tests/test_ui_qt_research_workflow.py`

- [ ] **Step 1: 三策略加入預設參數**

```python
"threshold_mode": "fixed",
"buy_quantile_bp": 8000,
"sell_quantile_bp": 4000,
"quantile_warmup_observations": 60,
"quantile_method": "nearest_rank",
```

- [ ] **Step 2: 寫 QComboBox 參數讀取失敗測試**
- [ ] **Step 3: `_update_params_form()` 支援 `type="choice"` 與 choices**
- [ ] **Step 4: `_get_strategy_params()` 讀取 QComboBox data/text**
- [ ] **Step 5: fixed 只顯示分數門檻；quantile 只顯示分位參數**
- [ ] **Step 6: 最佳化表單的 choice 只能固定選擇，不建立數值 range**
- [ ] **Step 7: 執行 UI 測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_workflow.py -q -o addopts=
```

- [ ] **Step 8: 提交**

```powershell
git add app_module/strategies ui_qt/views/backtest_view.py tests/test_ui_qt_research_workflow.py
git commit -m "feat(ui): configure fixed and quantile strategy thresholds"
```

## Task 8：更新無交易說明

**Files:**
- Modify: `ui_qt/views/backtest_view.py`
- Modify: `tests/test_ui_qt_research_workflow.py`

- [ ] **Step 1: quantile 無交易訊息不得建議降低 `buy_score`**
- [ ] **Step 2: 顯示暖機需求、可判斷日數、分位與命中日數**
- [ ] **Step 3: fixed 文案保持不變**
- [ ] **Step 4: 執行測試並提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_workflow.py -q -o addopts=
git add ui_qt/views/backtest_view.py tests/test_ui_qt_research_workflow.py
git commit -m "feat(ui): explain quantile backtest diagnostics"
```

## Task 9：Preset / StrategyVersion 重播

**Files:**
- Modify: `tests/test_portfolio_deepening.py`
- Modify: `tests/test_recommendation_portfolio_promotion_service.py`
- Modify only if required: `app_module/preset_service.py`
- Modify only if required: `app_module/strategy_version_service.py`

- [ ] **Step 1: 寫五個新參數的 round-trip 測試**
- [ ] **Step 2: 先驗證現有 dict persistence；通過時不修改 service**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_portfolio_deepening.py tests\test_recommendation_portfolio_promotion_service.py -q -o addopts=
```

- [ ] **Step 3: 只修實際相容缺口並提交**

```powershell
git add tests/test_portfolio_deepening.py tests/test_recommendation_portfolio_promotion_service.py app_module/preset_service.py app_module/strategy_version_service.py
git commit -m "test(strategy): preserve threshold metadata on replay"
```

## Task 10：文件同步

**Files:**
- Modify: `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`
- Modify: `docs/02_features/SCORE_EXPLANATION.md`
- Modify: `docs/02_features/BACKTEST_LAB_FEATURES.md`
- Modify: `docs/02_features/USER_GUIDE.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `PROJECT_NAVIGATION.md`

- [ ] **Step 1: 記錄 fixed / quantile、T-1、暖機與 UI 操作**
- [ ] **Step 2: 標記 quantile 是 opt-in**
- [ ] **Step 3: Snapshot / Roadmap 將 A 標為完成，B 保持待辦**
- [ ] **Step 4: 提交**

```powershell
git add docs PROJECT_NAVIGATION.md
git commit -m "docs: document backtest threshold modes"
```

## Task 11：Gate A 驗證

- [ ] **Step 1: 目標測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_score_threshold_policy.py tests\test_strategy_threshold_modes.py tests\test_backtest_diagnostics_and_date_adjustment.py tests\test_ui_qt_research_workflow.py tests\test_portfolio_deepening.py tests\test_recommendation_portfolio_promotion_service.py -q -o addopts=
```

- [ ] **Step 2: UI 強制 QA**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

- [ ] **Step 3: 型態、語法與 float boundary**

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile decision_module\score_threshold_policy.py app_module\strategies\baseline_score_executor.py app_module\strategies\momentum_aggressive_executor.py app_module\strategies\stable_conservative_executor.py app_module\backtest_service.py ui_qt\views\backtest_view.py
```

- [ ] **Step 4: 檢查 diff**

```powershell
git status --short
git diff --check
git diff --stat
```
