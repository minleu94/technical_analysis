# Month 3 Factor Replay Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 補齊固定組合 Research Lab 路徑的 factor metadata 保存覆蓋，讓固定組合回測的每檔結果能進入 Research Run Registry 並保存 `factor_snapshot` / `factor_contributions`。

**Architecture:** 固定組合目前共用批次回測服務；本計劃不建立新的組合績效引擎，也不在 UI 重算 factor。新增 `research_mode` 由 UI 傳入 `BatchBacktestService`，保存時將固定組合標記為 `fixed_basket_stock`，並沿用既有 `BacktestReportDTO.details["factor_records"]` 與 `factor_decision_date` 交給 `ResearchRunService.save_run()`。

**Tech Stack:** Python、PySide6、pytest、Research Run Registry、Factor Layer v1。

---

## Files

- Modify: `app_module/batch_backtest_service.py`
  - 新增 `research_mode` 參數。
  - 在 Research Run metadata 中標記 `run_type` 與 `original_input["research_mode"]`。
  - 保持既有批次預設行為為 `batch_backtest_stock`。
- Modify: `ui_qt/views/backtest_view.py`
  - 在 `_execute_batch_backtest()` 接收並轉傳 Research Lab mode。
  - 在 `_execute_backtest()` 依目前 `research_lab_mode_combo.currentData()` 傳入 `batch_stock` 或 `fixed_basket`。
- Modify: `tests/test_batch_backtest_research_run_save.py`
  - 新增固定組合路徑測試，先驗證失敗，再實作。
- Modify: `tests/test_ui_qt_research_run_save.py`
  - 新增 UI 呼叫轉傳 `research_mode="fixed_basket"` 的測試。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - 更新本週優先事項狀態，標示固定組合 factor records 覆蓋已補強。
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - 更新 Month 3 狀態，反映固定組合路徑已正式標記與保存 factor metadata。
- Modify: `docs/01_architecture/system_architecture.md`
  - 補充 Research Run 保存路徑中固定組合使用 `fixed_basket_stock` metadata，不重算 UI 分數。
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - 補充固定組合回測保存至 Registry 時會保留 factor metadata，但仍不等同完整可成交組合績效。

---

### Task 1: RED - 固定組合 Research Run metadata 必須保存 mode 與 factor records

**Files:**
- Modify: `tests/test_batch_backtest_research_run_save.py`

- [x] **Step 1: Add failing test**

Add this test after `test_batch_save_forwards_factor_records_to_research_run_service()`:

```python
def test_fixed_basket_save_marks_run_type_and_forwards_factor_records():
    factor_record = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 1, 7),
        available_date=date(2026, 1, 7),
        total_score=Decimal("82.35"),
    )
    report = _report_with_factor_records(factor_record)
    research_run_service = MagicMock()
    batch_service = BatchBacktestService(
        _FakeBacktestService(report),
        _FakeRunRepository(),
        research_run_service=research_run_service,
    )

    batch_service.run_batch_backtest(
        stock_codes=["2330"],
        start_date="2026-01-05",
        end_date="2026-01-07",
        strategy_spec=_strategy_spec(),
        save_runs=True,
        parallel_threshold=5,
        batch_name="Fixed Basket Factor Test",
        research_mode="fixed_basket",
    )

    metadata, equity, trades = research_run_service.save_run.call_args.args
    kwargs = research_run_service.save_run.call_args.kwargs
    assert metadata.run_type == "fixed_basket_stock"
    assert metadata.original_input["research_mode"] == "fixed_basket"
    assert metadata.original_input["batch_name"] == "Fixed Basket Factor Test"
    assert metadata.universe == ["2330"]
    assert list(equity["portfolio_value"]) == [1000, 1120]
    assert list(trades["stock_code"]) == ["2330"]
    assert kwargs["factor_records"] == [factor_record]
    assert kwargs["factor_decision_date"] == date(2026, 1, 7)
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_batch_backtest_research_run_save.py::test_fixed_basket_save_marks_run_type_and_forwards_factor_records -q -o addopts=
```

Expected: FAIL with `TypeError: ... unexpected keyword argument 'research_mode'`.

---

### Task 2: GREEN - BatchBacktestService 支援 research_mode

**Files:**
- Modify: `app_module/batch_backtest_service.py`

- [x] **Step 1: Implement minimal code**

Change `run_batch_backtest()` signature:

```python
        max_workers: Optional[int] = None,
        research_mode: str = "batch_stock",
```

When calling `_save_batch_research_run(...)` in both sequential and parallel paths, pass:

```python
                            research_mode=research_mode,
```

and:

```python
                                        research_mode=research_mode,
```

Change `_save_batch_research_run()` signature:

```python
        notes: str,
        research_mode: str = "batch_stock",
```

Before constructing `ResearchRunMetadataDTO`, add:

```python
        run_type = "fixed_basket_stock" if research_mode == "fixed_basket" else "batch_backtest_stock"
```

Then change metadata:

```python
            run_type=run_type,
```

and `original_input`:

```python
                "research_mode": research_mode,
```

Keep `run_id=f"batch-backtest:{legacy_run_id}"` unchanged for backward compatibility.

- [x] **Step 2: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_batch_backtest_research_run_save.py::test_fixed_basket_save_marks_run_type_and_forwards_factor_records -q -o addopts=
```

Expected: PASS.

- [x] **Step 3: Verify existing batch behavior**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_batch_backtest_research_run_save.py -q -o addopts=
```

Expected: all tests PASS.

---

### Task 3: RED - UI 固定組合模式必須轉傳 research_mode

**Files:**
- Modify: `tests/test_ui_qt_research_run_save.py`

- [x] **Step 1: Add failing test**

Add imports:

```python
from app_module.strategy_spec import StrategySpec
from unittest.mock import patch
```

Add this test near the other `BacktestView` save/dispatch tests:

```python
def test_fixed_basket_execution_forwards_research_mode_to_batch_service(backtest_view):
    backtest_view.batch_backtest_service = MagicMock()
    backtest_view.research_lab_mode_combo.setCurrentIndex(
        backtest_view.research_lab_mode_combo.findData("fixed_basket")
    )
    strategy_spec = StrategySpec(
        strategy_id="baseline_score",
        strategy_version="1.0",
        default_params={"buy_score": 60, "sell_score": 40},
        config={"params": {"threshold_mode": "fixed", "buy_score": 60, "sell_score": 40}},
    )

    with patch("ui_qt.views.backtest_view.TaskWorker") as task_worker_cls:
        worker = MagicMock()
        task_worker_cls.return_value = worker

        backtest_view._execute_batch_backtest(
            stock_codes=["2330", "2317"],
            start_date="2026-01-05",
            end_date="2026-01-07",
            strategy_spec=strategy_spec,
            capital=1000000,
            fee_bps=14.25,
            slippage_bps=5,
            execution_price="next_open",
            stop_loss_pct=None,
            take_profit_pct=None,
            stop_loss_atr_mult=None,
            take_profit_atr_mult=None,
            sizing_mode="all_in",
            fixed_amount=None,
            risk_pct=None,
            max_positions=None,
            position_sizing="equal_weight",
            allow_pyramid=False,
            allow_reentry=True,
            reentry_cooldown_days=0,
            enable_limit=True,
            enable_volume=True,
            max_participation=0.05,
        )

    task = task_worker_cls.call_args.args[0]
    task()
    kwargs = backtest_view.batch_backtest_service.run_batch_backtest.call_args.kwargs
    assert kwargs["research_mode"] == "fixed_basket"
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_run_save.py::test_fixed_basket_execution_forwards_research_mode_to_batch_service -q -o addopts=
```

Expected: FAIL because `_execute_batch_backtest()` does not pass `research_mode`.

---

### Task 4: GREEN - UI 傳入目前 Research Lab mode

**Files:**
- Modify: `ui_qt/views/backtest_view.py`

- [x] **Step 1: Implement minimal code**

Before calling `_execute_batch_backtest(...)` from `_execute_backtest()`, add:

```python
            research_mode = str(self.research_lab_mode_combo.currentData() or "batch_stock")
```

Then pass:

```python
                research_mode=research_mode,
```

Change `_execute_batch_backtest()` signature:

```python
        max_participation: float,
        research_mode: str = "batch_stock",
    ):
```

Inside `batch_backtest_task()`, pass:

```python
                research_mode=research_mode,
```

- [x] **Step 2: Verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_run_save.py::test_fixed_basket_execution_forwards_research_mode_to_batch_service -q -o addopts=
```

Expected: PASS.

- [x] **Step 3: Verify UI research save tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_run_save.py -q -o addopts=
```

Expected: all tests PASS.

---

### Task 5: Documentation sync

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] **Step 1: Update Snapshot**

In `PROJECT_SNAPSHOT.md` 本週優先事項第 1 點， change wording to state that fixed basket Research Lab path now preserves factor metadata per stock in Registry, while Month 3 still needs Portfolio Replay credibility work.

- [x] **Step 2: Update 6M Roadmap**

In Month 3 status, add a sentence:

```markdown
固定組合回測共用批次回測執行路徑，但 Research Run Registry 會以 `fixed_basket_stock` 標記每檔保存結果，並沿用回測產生的 factor records 生成 `factor_snapshot` / `factor_contributions`。
```

- [x] **Step 3: Update Architecture**

In Factor Layer v1 / Research governance section, add that fixed basket saves are metadata-distinguished and do not recompute UI scores.

- [x] **Step 4: Update Manual**

In Research Lab fixed basket or save section, add that fixed basket saves per-stock Registry runs with factor metadata; also warn that complete portfolio-level cash/rebalance/liquidity credibility remains Month 3 follow-up.

---

### Task 6: Final verification

**Files:**
- Verify changed files only plus project gates relevant to this change.

- [x] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_batch_backtest_research_run_save.py tests\test_ui_qt_research_run_save.py tests\test_backtest_factor_metadata.py tests\test_research_run_service.py -q -o addopts=
```

- [x] **Step 2: Run py_compile on changed Python files**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\batch_backtest_service.py ui_qt\views\backtest_view.py
```

- [x] **Step 3: Run financial float boundary check**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

- [x] **Step 4: Inspect git diff**

```powershell
git diff -- app_module\batch_backtest_service.py ui_qt\views\backtest_view.py tests\test_batch_backtest_research_run_save.py tests\test_ui_qt_research_run_save.py docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\01_architecture\system_architecture.md docs\07_guides\APPLICATION_MANUAL.md
```

Expected: only planned files changed; no generated QA outputs staged or modified by this work.

---

## Self-Review

- Spec coverage: Covers Month 3 fixed basket factor metadata coverage, preserves no-look-ahead by reusing existing `FactorRecord.available_date` gate in `ResearchRunService`, and documents remaining Portfolio Replay credibility work.
- Placeholder scan: No `TBD`, `TODO`, or undefined future task remains.
- Type consistency: `research_mode` is a string defaulting to `"batch_stock"`; fixed basket maps to metadata `run_type="fixed_basket_stock"`; existing default remains `batch_backtest_stock`.
