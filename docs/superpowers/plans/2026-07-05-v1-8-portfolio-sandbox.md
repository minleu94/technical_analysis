# V1.8 Portfolio Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 research-only portfolio construction sandbox 與 virtual execution trace inspection。

**Architecture:** 新增 app-layer DTO / service，不改既有 portfolio domain、推薦分數、回放 PnL 或 scheduler。配置服務用 `Decimal` 與整數基點產生研究配置結果；execution trace 服務把配置結果轉成虛擬事件生命週期。

**Tech Stack:** Python dataclasses、Decimal、pytest、現有 `financial_module.units`。

---

## File Structure

- Create: `app_module/portfolio_construction_dtos.py`，定義候選、request、allocation row、result DTO。
- Create: `app_module/portfolio_construction_service.py`，實作 equal / score / inverse volatility allocation、cap、lot sizing 與 diagnostics。
- Create: `app_module/portfolio_execution_trace_service.py`，實作 virtual order lifecycle event builder。
- Create: `scripts/inspect_portfolio_sandbox.py`，輸出 sample JSON / Markdown inspection。
- Create: `tests/test_portfolio_construction_sandbox.py`，TDD 覆蓋配置服務與 trace service。
- Create: `tests/test_portfolio_sandbox_inspection_cli.py`，TDD 覆蓋 CLI sample output。
- Modify docs after implementation: Snapshot、Roadmap Hub、6M Roadmap、Version Roadmap、Architecture、Manual、Documentation Index、Project Navigation。
- Add QA closeout: `docs/06_qa/V1_8_PORTFOLIO_SANDBOX_CLOSEOUT_2026_07_05.md`。

## Task 1: Design Commit

- [x] Write design doc at `docs/superpowers/specs/2026-07-05-v1-8-portfolio-sandbox-design.md`.
- [x] Write implementation plan at `docs/superpowers/plans/2026-07-05-v1-8-portfolio-sandbox.md`.
- [ ] Commit design and plan.

## Task 2: Portfolio Construction Sandbox

- [ ] Write failing tests in `tests/test_portfolio_construction_sandbox.py`:

```python
def test_equal_weight_allocation_respects_max_weight_and_lot_sizing():
    candidates = [
        PortfolioConstructionCandidate("2330", "台積電", score_bp=9000, reference_price=Decimal("333")),
        PortfolioConstructionCandidate("2317", "鴻海", score_bp=7000, reference_price=Decimal("100")),
        PortfolioConstructionCandidate("2454", "聯發科", score_bp=6000, reference_price=Decimal("500")),
    ]
    request = PortfolioConstructionRequest(
        decision_date="2026-07-05",
        capital_amount=Decimal("1000000"),
        allocation_method="equal_weight",
        candidates=tuple(candidates),
        max_position_weight_bp=4000,
        lot_size=1000,
    )
    result = PortfolioConstructionService().construct(request)
    assert result.research_basis is True
    assert [row.stock_code for row in result.allocations] == ["2330", "2317", "2454"]
    assert all(row.constrained_weight_bp <= 4000 for row in result.allocations)
    assert result.allocations[0].executable_shares == 1000
    assert result.diagnostics
```

```python
def test_score_and_inverse_volatility_methods_are_deterministic():
    candidates = (
        PortfolioConstructionCandidate("A", "A", score_bp=9000, reference_price=Decimal("100"), volatility_bp=3000),
        PortfolioConstructionCandidate("B", "B", score_bp=3000, reference_price=Decimal("100"), volatility_bp=1000),
    )
    score_result = PortfolioConstructionService().construct(
        PortfolioConstructionRequest(
            decision_date="2026-07-05",
            capital_amount=Decimal("120000"),
            allocation_method="score_weight",
            candidates=candidates,
        )
    )
    inverse_vol_result = PortfolioConstructionService().construct(
        PortfolioConstructionRequest(
            decision_date="2026-07-05",
            capital_amount=Decimal("120000"),
            allocation_method="inverse_volatility",
            candidates=candidates,
        )
    )
    assert [row.target_weight_bp for row in score_result.allocations] == [7500, 2500]
    assert [row.target_weight_bp for row in inverse_vol_result.allocations] == [2500, 7500]
```

- [ ] Run RED:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_construction_sandbox.py -q -o addopts=
```

Expected: fails with missing module/classes.

- [ ] Implement DTO and construction service with Decimal / integer bp only.
- [ ] Run GREEN focused pytest.
- [ ] Commit:

```powershell
git add app_module/portfolio_construction_dtos.py app_module/portfolio_construction_service.py tests/test_portfolio_construction_sandbox.py
git commit -m "feat: add v1.8 portfolio construction sandbox"
```

## Task 3: Virtual Execution Trace / Inspection

- [ ] Extend failing tests in `tests/test_portfolio_construction_sandbox.py`:

```python
def test_virtual_execution_trace_marks_research_only_lifecycle():
    result = PortfolioConstructionService().construct(...)
    events = PortfolioExecutionTraceService().build_trace(result)
    assert [event.event_type for event in events[:3]] == ["created", "submitted", "filled"]
    assert all(event.research_only for event in events)
    assert {event.source_type for event in events} == {"portfolio_sandbox"}
```

```python
def test_virtual_execution_trace_can_partial_fill_and_reject():
    result = PortfolioConstructionService().construct(...)
    events = PortfolioExecutionTraceService().build_trace(
        result,
        partial_fill_bp_by_symbol={"2330": 5000},
        rejected_symbols={"2317": "price_limit_lock"},
    )
    event_types = {(event.stock_code, event.event_type) for event in events}
    assert ("2330", "partially_filled") in event_types
    assert ("2317", "rejected") in event_types
```

- [ ] Write failing CLI test in `tests/test_portfolio_sandbox_inspection_cli.py`:

```python
def test_inspection_cli_outputs_sample_json():
    result = subprocess.run(
        [sys.executable, "scripts/inspect_portfolio_sandbox.py", "--sample", "--format", "json"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["research_basis"] is True
    assert payload["trace_events"]
```

- [ ] Run RED for the new tests.
- [ ] Implement trace service and inspection CLI.
- [ ] Run GREEN focused pytest.
- [ ] Commit:

```powershell
git add app_module/portfolio_execution_trace_service.py scripts/inspect_portfolio_sandbox.py tests/test_portfolio_construction_sandbox.py tests/test_portfolio_sandbox_inspection_cli.py
git commit -m "feat: add v1.8 virtual execution trace"
```

## Task 4: Documentation / QA Closeout

- [ ] Update active docs listed in File Structure.
- [ ] Add QA closeout with commands and results.
- [ ] Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_construction_sandbox.py tests/test_portfolio_sandbox_inspection_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module/portfolio_construction_dtos.py app_module/portfolio_construction_service.py app_module/portfolio_execution_trace_service.py scripts/inspect_portfolio_sandbox.py
.\.venv\Scripts\python.exe scripts/quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

- [ ] Commit docs:

```powershell
git add PROJECT_NAVIGATION.md docs/00_core docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md docs/06_qa/V1_8_PORTFOLIO_SANDBOX_CLOSEOUT_2026_07_05.md
git commit -m "docs: close out v1.8 portfolio sandbox"
```

