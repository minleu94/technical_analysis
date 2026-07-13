# Evidence and V3 Data Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 V3 報表只對適用事件要求 score，因果地解析 event price / maturity，並產生完整且 fail-closed 的 effectiveness / pruning package。

**Architecture:** 新增純 contract / resolver / read-model units，既有 evidence repositories 保持 append-only。V3 只消費標準化 evidence rows，不回填不適用資料，也不修改 score 或 lifecycle。

**Tech Stack:** Python dataclasses、SQLite read-only repositories、Decimal / integer bp、pytest。

## Global Constraints

- `score_not_applicable` 不得轉成 missing-score diagnostic。
- event price 只能來自 decision date 當下或之前的最近交易日。
- outcome maturity 以交易日序列計算，不用 calendar-day 猜測。
- 所有 pruning action 都是 proposal，`apply_action=false`。

---

### Task 1: Event Metric Applicability Contract

**Files:**
- Create: `app_module/evidence_metric_applicability.py`
- Modify: `app_module/score_effectiveness_read_model.py`
- Test: `tests/test_evidence_metric_applicability.py`
- Test: `tests/test_score_effectiveness_read_model.py`
- Docs: `docs/06_qa/V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md`

**Interfaces:**
- Produces: `EvidenceMetricApplicability.classify(event_family: str, event_type: str) -> MetricApplicability`
- `MetricApplicability.score_requirement` is one of `required | optional | not_applicable`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_risk_prompt_score_is_not_applicable():
    result = EvidenceMetricApplicability().classify("risk_prompt", "risk_prompt_data_quality")
    assert result.score_requirement == "not_applicable"

def test_recommendation_included_requires_score():
    result = EvidenceMetricApplicability().classify("recommendation", "recommendation_included")
    assert result.score_requirement == "required"
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_evidence_metric_applicability.py -q -o addopts=`
Expected: import failure because module is absent.

- [ ] **Step 3: Implement immutable mapping and filter diagnostics**

```python
@dataclass(frozen=True)
class MetricApplicability:
    score_requirement: str
    supported_metrics: tuple[str, ...]

class EvidenceMetricApplicability:
    def classify(self, event_family: str, event_type: str) -> MetricApplicability:
        if event_family == "recommendation":
            return MetricApplicability("required", ("score", "forward_return", "precision_at_k"))
        if event_family in {"risk_prompt", "decision_quality"}:
            return MetricApplicability("not_applicable", ("alert_quality",))
        return MetricApplicability("optional", ("forward_return",))
```

- [ ] **Step 4: Verify GREEN and regression**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_evidence_metric_applicability.py tests/test_score_effectiveness_read_model.py -q -o addopts=`
Expected: all pass; not-applicable events produce no missing-score diagnostic.

- [ ] **Step 5: Document and commit**

```powershell
git add app_module/evidence_metric_applicability.py app_module/score_effectiveness_read_model.py tests/test_evidence_metric_applicability.py tests/test_score_effectiveness_read_model.py docs/06_qa/V3_0_ENGINEERING_CANDIDATE_MANUAL_VALIDATION_REPORT_2026_07_08.md
git commit -m "feat(evidence): classify metric applicability by event family"
```

### Task 2: Causal Event Price Resolver

**Files:**
- Create: `app_module/event_price_resolver.py`
- Modify: `app_module/forward_performance_service.py`
- Test: `tests/test_event_price_resolver.py`
- Test: `tests/test_forward_performance_service.py`

**Interfaces:**
- Consumes: ordered `(trading_date, close)` observations visible at `data_as_of_date`.
- Produces: `EventPriceResolution(price_date, close, fallback_reason, quality)`.

- [ ] **Step 1: Write failing weekend and future-data tests**

```python
def test_weekend_uses_previous_visible_trading_day():
    result = resolver.resolve(decision_date="2026-07-12", data_as_of_date="2026-07-12", prices=prices)
    assert result.price_date == "2026-07-10"
    assert result.fallback_reason == "previous_trading_day"

def test_future_price_is_never_used():
    result = resolver.resolve(decision_date="2026-07-12", data_as_of_date="2026-07-10", prices=prices)
    assert result.price_date <= "2026-07-10"
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_event_price_resolver.py -q -o addopts=`
Expected: missing resolver.

- [ ] **Step 3: Implement resolver with Decimal close boundary**

```python
visible = [row for row in prices if row.trading_date <= min(decision_date, data_as_of_date)]
if not visible:
    return EventPriceResolution(None, None, "no_visible_price", "missing")
row = visible[-1]
reason = None if row.trading_date == decision_date else "previous_trading_day"
```

- [ ] **Step 4: Integrate and verify prefix invariance**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_event_price_resolver.py tests/test_forward_performance_service.py -q -o addopts=`
Expected: all pass; adding future rows does not change prior resolution.

- [ ] **Step 5: Commit**

```powershell
git add app_module/event_price_resolver.py app_module/forward_performance_service.py tests/test_event_price_resolver.py tests/test_forward_performance_service.py
git commit -m "fix(evidence): resolve causal event-price trading date"
```

### Task 3: Outcome Maturity Calendar

**Files:**
- Create: `app_module/outcome_maturity_service.py`
- Modify: `app_module/forward_performance_read_model.py`
- Test: `tests/test_outcome_maturity_service.py`

**Interfaces:**
- Produces: `OutcomeMaturity(expected_trading_date, status, remaining_trading_days)`.

- [ ] **Step 1: Write failing trading-day maturity tests**

```python
def test_five_day_maturity_uses_fifth_future_trading_day():
    result = service.evaluate(event_date="2026-07-06", window_days=5, trading_dates=dates, as_of="2026-07-10")
    assert result.expected_trading_date == "2026-07-13"
    assert result.status == "pending"
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_outcome_maturity_service.py -q -o addopts=`
Expected: missing service.

- [ ] **Step 3: Implement index-based trading-day calculation**

```python
future = [date for date in trading_dates if date > event_date]
expected = future[window_days - 1] if len(future) >= window_days else None
```

- [ ] **Step 4: Verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_outcome_maturity_service.py tests/test_forward_performance_read_model.py -q -o addopts=`
Expected: pass; read model exposes expected maturity date.

- [ ] **Step 5: Commit**

```powershell
git add app_module/outcome_maturity_service.py app_module/forward_performance_read_model.py tests/test_outcome_maturity_service.py
git commit -m "feat(evidence): expose expected outcome maturity dates"
```

### Task 4: Decision-ready Effectiveness Metrics

**Files:**
- Create: `app_module/v3_effectiveness_metrics.py`
- Modify: `app_module/v3_effectiveness_read_model.py`
- Test: `tests/test_v3_effectiveness_metrics.py`
- Test: `tests/test_v3_effectiveness_read_model.py`

**Interfaces:**
- Produces: integer-bp `EffectivenessMetrics` with monotonicity, precision-at-k, hit, payoff, MAE/MFE readiness.

- [ ] **Step 1: Write failing deterministic metric tests**

```python
def test_precision_at_k_uses_ready_rows_only():
    result = compute_precision_at_k(rows, k=2)
    assert result.ready_count == 2
    assert result.precision_bp == 5000
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_metrics.py -q -o addopts=`
Expected: missing module.

- [ ] **Step 3: Implement pure integer-bp metrics**

```python
precision_bp = positive_count * 10000 // ready_count
monotonic = all(left <= right for left, right in pairwise(bucket_returns))
```

- [ ] **Step 4: Verify GREEN and no-float guard**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_v3_effectiveness_metrics.py tests/test_v3_effectiveness_read_model.py -q -o addopts=`
Run: `.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add app_module/v3_effectiveness_metrics.py app_module/v3_effectiveness_read_model.py tests/test_v3_effectiveness_metrics.py tests/test_v3_effectiveness_read_model.py
git commit -m "feat(v3): add decision-ready effectiveness metrics"
```

### Task 5: Structured Pruning Decision Package

**Files:**
- Create: `app_module/v3_pruning_decision_service.py`
- Create: `scripts/build_v3_pruning_package.py`
- Test: `tests/test_v3_pruning_decision_service.py`
- Test: `tests/test_v3_pruning_package_cli.py`
- Docs: `docs/07_guides/APPLICATION_MANUAL.md`

**Interfaces:**
- Produces proposal actions `retain | restrict | downweight | retire | defer` with `apply_action=False`.

- [ ] **Step 1: Write failing insufficient-sample and stable-signal tests**

```python
def test_insufficient_sample_always_defers():
    item = service.propose(metrics=metrics(sample_count=12), minimum_sample=30)
    assert item.action == "defer"
    assert item.apply_action is False
```

- [ ] **Step 2: Verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_v3_pruning_decision_service.py -q -o addopts=`
Expected: missing service.

- [ ] **Step 3: Implement deterministic proposal rules and JSON CLI**

```python
if metrics.sample_count < minimum_sample:
    return PruningProposal("defer", ("insufficient_sample",), False)
```

- [ ] **Step 4: Verify CLI safety boundary**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_v3_pruning_decision_service.py tests/test_v3_pruning_package_cli.py -q -o addopts=`
Expected: output contains `apply_action=false`, `auto_trading=false`.

- [ ] **Step 5: Document and commit**

```powershell
git add app_module/v3_pruning_decision_service.py scripts/build_v3_pruning_package.py tests/test_v3_pruning_decision_service.py tests/test_v3_pruning_package_cli.py docs/07_guides/APPLICATION_MANUAL.md
git commit -m "feat(v3): build structured pruning decision package"
```

### Task 6: Plan Boundary Verification

- [ ] Run complete verification:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -o addopts=
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
git diff --check
```

Expected: zero failures / errors / violations.

