# Month 3 Recommendation Factor Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓推薦組合回放的 recommendations 轉成 Factor Layer v1 metadata，並在保存到 Research Run Registry 時帶入 `factor_snapshot` / `factor_contributions`。

**Architecture:** `RecommendationPortfolioBacktestService` 從每期 `RecommendationSnapshotDTO.recommendations` 讀取既有 `total_score` 與 `factor_scores.volume`，轉為 v1 `FactorRecord`，經 `FactorService` 建立 snapshot 與 contribution summary，再放入 result `details.data_manifest`。BacktestView 既有 Research Run 保存流程會讀取 `details.data_manifest`，因此不需要新增 UI 按鈕或 SQLite schema。

**Tech Stack:** Python dataclasses、Decimal、pandas、pytest、既有 `FactorService`、既有 Research Run Registry。

---

## File Structure

**Modify**

- `app_module/recommendation_portfolio_dtos.py`：在 `RecommendationPortfolioBacktestResultDTO` 新增 `details`，讓服務層可帶保存 metadata。
- `app_module/recommendation_portfolio_backtest_service.py`：新增 snapshot -> factor records -> manifest 的轉換 helper。
- `tests/test_recommendation_portfolio_backtest.py`：驗證推薦組合回放結果產生 factor manifest。
- `tests/test_ui_qt_research_run_save.py`：驗證 UI 保存路徑不會遺失 `details.data_manifest.factor_*`。
- `docs/00_core/*` 與 `docs/01_architecture/system_architecture.md`：同步 Month 3 狀態。

---

## Task 1: Recommendation Portfolio Result Carries Details

- [x] **Step 1: Write failing test**

在 `tests/test_recommendation_portfolio_backtest.py` 新增：

```python
def test_portfolio_backtest_result_includes_factor_manifest_from_replay_snapshots():
    ...
    manifest = result.details["data_manifest"]
    assert manifest["factor_snapshot"]["records"][0]["factor_name"] == "technical.total_score"
```

- [x] **Step 2: Verify red**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_result_includes_factor_manifest_from_replay_snapshots -q -o addopts=
```

Expected: `AttributeError: 'RecommendationPortfolioBacktestResultDTO' object has no attribute 'details'`.

- [x] **Step 3: Implement DTO details**

在 `RecommendationPortfolioBacktestResultDTO` 新增 `details: Dict[str, Any] = field(default_factory=dict)`，並納入 `to_dict()` / `from_dict()`。

- [x] **Step 4: Implement factor manifest builder**

在 `RecommendationPortfolioBacktestService` 新增 `_build_factor_manifest()` 與 `_factor_records_from_snapshot()`：

- `technical.total_score` 來自 recommendation `total_score`。
- `volume.volume_ratio` v1 先由 `factor_scores.volume` 轉成可追溯 metadata，保留 `metadata.source_field = factor_scores.volume`。
- 每筆 factor 的 `as_of_date` / `available_date` 使用 snapshot `as_of_date`，避免使用未來資料。

---

## Task 2: Research Run Save Path Preserves Factor Manifest

- [x] **Step 1: Extend UI save test**

在 `tests/test_ui_qt_research_run_save.py` 的 fake recommendation portfolio result 加入 `details.data_manifest.factor_snapshot` / `factor_contributions`。

- [x] **Step 2: Verify save metadata**

確認 `_save_recommendation_portfolio_to_research_registry()` 建立的 metadata 可讀回：

```python
assert metadata.factor_snapshot["records"][0]["factor_name"] == "technical.total_score"
assert metadata.factor_contributions["by_stock"]["2330"][0]["factor_name"] == "technical.total_score"
```

---

## Task 3: Verification

- [x] Focused regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_ui_qt_research_run_save.py tests\test_factor_service_research_run.py tests\test_research_run_service.py -q -o addopts=
```

Result: `36 passed, 8 warnings`。Warnings 為推薦組合回測既有同日收盤成交假設。

- [x] Syntax check:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_dtos.py app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py tests\test_ui_qt_research_run_save.py
```

Result: passed。
