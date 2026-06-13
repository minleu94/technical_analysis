# Strategy & Scoring Governance B: Recommendation Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 fixed 推薦維持舊排序的前提下，新增 eligible universe 橫斷面百分位排名、最小母體診斷與結果 metadata。

**Architecture:** `decision_module/recommendation_percentile_ranker.py` 接受股票代碼與已量化分數，不依賴 DTO。`RecommendationService` 完成逐股硬篩選與評分後才建立母體；`top_n` 永不參與百分位計算。DTO / Repository 負責追溯欄位與舊 JSON 相容。

**Tech Stack:** Python、Decimal、bisect、dataclasses、pytest、現有 RecommendationService / RecommendationRepository / RecommendationView。

**Prerequisite:** 增量 A Gate 全部通過，且 `quantize_score_to_basis_points()` 已存在。

---

## Task 1：建立橫斷面排名契約

**Files:**
- Create: `tests/test_recommendation_percentile_ranker.py`

- [ ] **Step 1: 寫 empirical CDF 與同分測試**

```python
def test_percentiles_use_empirical_cdf_and_keep_ties_equal():
    result = calculate_score_percentiles({
        "1101": 5000,
        "1102": 7000,
        "1103": 7000,
        "1104": 9000,
    })
    assert result["1101"] == 2500
    assert result["1102"] == 7500
    assert result["1103"] == 7500
    assert result["1104"] == 10000
```

- [ ] **Step 2: 驗證輸入順序不影響結果**
- [ ] **Step 3: 驗證空母體與越界 score_bp**
- [ ] **Step 4: 執行並確認模組不存在**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_percentile_ranker.py -q -o addopts=
```

- [ ] **Step 5: 提交測試**

```powershell
git add tests/test_recommendation_percentile_ranker.py
git commit -m "test(recommendation): define percentile ranking contract"
```

## Task 2：實作排名元件

**Files:**
- Create: `decision_module/recommendation_percentile_ranker.py`

- [ ] **Step 1: 實作純函式**

```python
def calculate_score_percentiles(scores_by_stock: Mapping[str, int]) -> dict[str, int]:
    if not scores_by_stock:
        return {}
    validate_score_range(scores_by_stock)
    sorted_scores = sorted(scores_by_stock.values())
    universe_size = len(sorted_scores)
    return {
        stock_code: (
            bisect_right(sorted_scores, score_bp) * 10000
            + universe_size - 1
        ) // universe_size
        for stock_code, score_bp in scores_by_stock.items()
    }
```

同分因 `bisect_right` 使用相同 `count(score <= current)`，必須得到同一 percentile。

- [ ] **Step 2: 執行測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_percentile_ranker.py -q -o addopts=
```

- [ ] **Step 3: 提交**

```powershell
git add decision_module/recommendation_percentile_ranker.py
git commit -m "feat(recommendation): add cross-sectional percentile ranker"
```

## Task 3：鎖定 RecommendationService 行為

**Files:**
- Create: `tests/test_recommendation_ranking_service.py`

- [ ] **Step 1: fixed 基線**

缺少 `recommendation_ranking` 與明確 fixed 都維持：

```python
sorted(all_recommendations, key=lambda item: item.total_score, reverse=True)[:top_n]
```

fixed 不新增 stock code tie-break，避免改變舊結果。

- [ ] **Step 2: quantile 順序測試**

驗證處理順序：

1. 個股硬篩選。
2. 完成全部 DTO。
3. 完整母體計算 percentile。
4. 套最低 percentile。
5. `total_score desc, stock_code asc`。
6. 最後套 `top_n`。

- [ ] **Step 3: 測試 19/20 母體邊界、產業篩選後重建母體**
- [ ] **Step 4: 測試 `top_n` 不改變百分位**
- [ ] **Step 5: 執行並確認失敗**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_ranking_service.py -q -o addopts=
```

- [ ] **Step 6: 提交測試**

```powershell
git add tests/test_recommendation_ranking_service.py
git commit -m "test(recommendation): lock eligible universe ranking behavior"
```

## Task 4：接入 RecommendationService

**Files:**
- Modify: `app_module/recommendation_service.py`
- Create: `app_module/recommendation_errors.py`

- [ ] **Step 1: 建立明確例外**

```python
class RecommendationUniverseTooSmallError(ValueError):
    def __init__(self, actual_size: int, minimum_size: int) -> None:
        self.actual_size = actual_size
        self.minimum_size = minimum_size
        super().__init__(
            f"eligible universe too small: actual={actual_size}, minimum={minimum_size}"
        )
```

- [ ] **Step 2: 解析固定 config 路徑**

```python
ranking_config = config.get("recommendation_ranking", {})
threshold_mode = ranking_config.get("threshold_mode", "fixed")
```

quantile 必須明確提供：

- `recommendation_min_percentile_bp`
- `recommendation_min_universe_size`
- `recommendation_ranking_method`

- [ ] **Step 3: fixed 分支保留既有 sort、slice 與 max_stocks 語義**
- [ ] **Step 4: quantile 在逐股迴圈後量化完整母體**

```python
scores_by_stock = {
    rec.stock_code: quantize_score_to_basis_points(rec.total_score)
    for rec in all_recommendations
}
percentiles = calculate_score_percentiles(scores_by_stock)
```

無法量化時指出股票代碼並拒絕，不可靜默移除。

- [ ] **Step 5: 寫入 metadata 後再 filter / stable sort / top_n**

欄位：

- `score_percentile_bp`
- `eligible_universe_size`
- `eligible_universe_date`
- `ranking_method`
- `threshold_mode`

`eligible_universe_date` 使用資料實際最新交易日，不使用系統日期。

- [ ] **Step 6: 執行服務測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_ranking_service.py tests\test_recommendation_percentile_ranker.py -q -o addopts=
```

- [ ] **Step 7: 提交**

```powershell
git add app_module/recommendation_service.py app_module/recommendation_errors.py tests/test_recommendation_ranking_service.py
git commit -m "feat(recommendation): rank eligible universe by percentile"
```

## Task 5：DTO 與 Repository round-trip

**Files:**
- Modify: `app_module/dtos/__init__.py`
- Modify: `app_module/recommendation_repository.py`
- Create: `tests/test_recommendation_dto_roundtrip.py`

- [ ] **Step 1: 先鎖定既有中文 key 無法載入的缺口**

測試 `RecommendationDTO.to_dict()` 產出可由 `RecommendationResultDTO.from_dict()` 還原。

- [ ] **Step 2: DTO 末端加入 optional metadata**

```python
score_percentile_bp: Optional[int] = None
eligible_universe_size: Optional[int] = None
eligible_universe_date: Optional[str] = None
ranking_method: Optional[str] = None
threshold_mode: str = "fixed"
```

- [ ] **Step 3: 新增 `RecommendationDTO.from_dict()`**

同時接受 dataclass 英文 key、既有中文顯示 key，以及缺少新 metadata 的歷史 JSON。`RecommendationResultDTO.from_dict()` 改呼叫此方法。

- [ ] **Step 4: `to_dict()` 增加追溯欄位；不改舊欄位名稱、不改 SQLite schema**
- [ ] **Step 5: 執行 round-trip 與 repository 測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_dto_roundtrip.py tests\test_recommendation_portfolio_run_repository.py -q -o addopts=
```

- [ ] **Step 6: 提交**

```powershell
git add app_module/dtos/__init__.py app_module/recommendation_repository.py tests/test_recommendation_dto_roundtrip.py
git commit -m "feat(recommendation): persist ranking provenance"
```

## Task 6：推薦 UI

**Files:**
- Modify: `ui_qt/views/recommendation_view.py`
- Modify: `tests/test_ui_qt_research_workflow.py`

- [ ] **Step 1: 測試 `_collect_config()` 預設輸出 fixed**

```python
"recommendation_ranking": {"threshold_mode": "fixed"}
```

- [ ] **Step 2: 新增 fixed / quantile、最低百分位、最小母體、方法 controls**
- [ ] **Step 3: UI 百分比轉 integer bp；service 邊界不傳 float percentile**
- [ ] **Step 4: quantile 才顯示百分位 controls**
- [ ] **Step 5: 母體不足錯誤顯示 actual/minimum，並說明未降級**
- [ ] **Step 6: quantile 結果表顯示百分位、母體數與排名日期**
- [ ] **Step 7: 執行 UI 測試並提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_workflow.py -q -o addopts=
git add ui_qt/views/recommendation_view.py tests/test_ui_qt_research_workflow.py
git commit -m "feat(ui): configure recommendation percentile ranking"
```

## Task 7：推薦回放與重現性

**Files:**
- Modify: `tests/test_recommendation_portfolio_backtest.py`
- Modify: `tests/test_recommendation_portfolio_run_repository.py`
- Modify only if required: `app_module/recommendation_portfolio_backtest_service.py`

- [ ] **Step 1: recommendation config 原樣進入回放**
- [ ] **Step 2: `top_n` 改變不改同一母體的 percentile metadata**
- [ ] **Step 3: 股票輸入順序改變時結果一致**
- [ ] **Step 4: 執行測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_run_repository.py -q -o addopts=
```

- [ ] **Step 5: 提交**

```powershell
git add tests/test_recommendation_portfolio_backtest.py tests/test_recommendation_portfolio_run_repository.py app_module/recommendation_portfolio_backtest_service.py
git commit -m "test(recommendation): verify percentile replay determinism"
```

## Task 8：文件同步

**Files:**
- Modify: `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`
- Modify: `docs/02_features/SCORE_EXPLANATION.md`
- Modify: `docs/02_features/USER_GUIDE.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `PROJECT_NAVIGATION.md`

- [ ] **Step 1: 記錄 eligible universe、empirical CDF、同分與最小母體**
- [ ] **Step 2: 記錄 fixed 相容性與 config 路徑**
- [ ] **Step 3: 更新 Snapshot / Roadmap**
- [ ] **Step 4: 提交**

```powershell
git add docs PROJECT_NAVIGATION.md
git commit -m "docs: document recommendation percentile governance"
```

## Task 9：Gate B 驗證

- [ ] **Step 1: 目標測試**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_percentile_ranker.py tests\test_recommendation_ranking_service.py tests\test_recommendation_dto_roundtrip.py tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_run_repository.py tests\test_ui_qt_research_workflow.py -q -o addopts=
```

- [ ] **Step 2: A + B 整合回歸**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_score_threshold_policy.py tests\test_strategy_threshold_modes.py tests\test_backtest_diagnostics_and_date_adjustment.py tests\test_recommendation_percentile_ranker.py tests\test_recommendation_ranking_service.py tests\test_recommendation_dto_roundtrip.py -q -o addopts=
```

- [ ] **Step 3: UI 強制 QA**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

- [ ] **Step 4: 型態、語法與 float boundary**

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile decision_module\recommendation_percentile_ranker.py app_module\recommendation_service.py app_module\recommendation_errors.py app_module\dtos\__init__.py ui_qt\views\recommendation_view.py
```

- [ ] **Step 5: Walk-forward 比較報告**

相同資料截止日、交易成本與策略版本下比較 fixed / quantile：

- 交易次數、暖機後有效天數。
- 報酬、最大回撤、Sharpe。
- regime 穩定性。
- 推薦母體數、門檻通過率與換手。

報告不自動變更預設模式。

- [ ] **Step 6: 最終 diff**

```powershell
git status --short
git diff --check
git diff --stat
```
