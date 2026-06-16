# Month 5 Revenue Factor Pack v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Revenue YoY, Revenue MoM, three-month trend, and revenue new high factor adapters.

**Architecture:** Extend `decision_module/factors/fundamental_adapters.py` without connecting to `ScoringEngine`. Inputs must already be normalized records with explicit `available_date`; all emitted records use `MissingPolicy.SKIP` and pass through `FactorGate` before Research Run storage or diagnostics.

**Tech Stack:** Python, pytest, `Decimal`, existing `MonthlyRevenueRecord`, `FactorRecord`, `FactorGate`.

---

## Entry Conditions

- Complete the availability entrypoint plan.
- Complete or explicitly defer formal SQLite migration; tests may use in-memory normalized records and must not require formal DB writes.
- Confirm no raw CSV row without `available_date` can produce a factor.

## Task 1: Revenue Factor Input Model

**Files:**
- Modify: `decision_module/factors/fundamental_adapters.py`
- Test: `tests/test_revenue_factor_pack.py`

- [ ] **Step 1: Write failing tests for pack construction**

Create `tests/test_revenue_factor_pack.py`:

```python
from datetime import date
from decimal import Decimal

from data_module.fundamental_data import MonthlyRevenueRecord
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy
from decision_module.factors.fundamental_adapters import build_revenue_factor_pack


def _record(period: str, revenue: str, available_date: date) -> MonthlyRevenueRecord:
    year, month = [int(part) for part in period.split("-")]
    return MonthlyRevenueRecord(
        stock_code="2330",
        period=period,
        as_of_date=date(year, month, 28),
        raw_date=available_date,
        announced_date=available_date,
        available_date=available_date,
        revenue=Decimal(revenue),
        source="financial_data.monthly_revenue_csv",
        source_version="financial-data-csv-v1",
        quality=FactorQuality.OBSERVED,
    )


def test_build_revenue_factor_pack_emits_yoy_mom_trend_and_new_high():
    records = (
        _record("2025-04", "90", date(2025, 5, 10)),
        _record("2025-05", "100", date(2025, 6, 10)),
        _record("2026-03", "110", date(2026, 4, 10)),
        _record("2026-04", "120", date(2026, 5, 10)),
        _record("2026-05", "150", date(2026, 6, 10)),
    )

    result = build_revenue_factor_pack(records, stock_code="2330", decision_period="2026-05")

    by_name = {record.factor_name: record for record in result.records}
    assert by_name["fundamental.revenue_yoy"].value == Decimal("0.5")
    assert by_name["fundamental.revenue_mom"].value == Decimal("0.25")
    assert by_name["fundamental.revenue_3m_trend"].value == "up"
    assert by_name["fundamental.revenue_new_high"].value == 1
    for record in result.records:
        assert record.available_date == date(2026, 6, 10)
        assert record.missing_policy == MissingPolicy.SKIP
        assert record.score_bp is None
        assert record.source_version == "financial-data-csv-v1"
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_revenue_factor_pack.py -q -o addopts=
```

Expected: import fails because `build_revenue_factor_pack` does not exist.

- [ ] **Step 3: Implement factor pack model**

Modify `decision_module/factors/fundamental_adapters.py`:

```python
from data_module.fundamental_data import MonthlyRevenueRecord


def build_revenue_factor_pack(
    records: tuple[MonthlyRevenueRecord, ...],
    *,
    stock_code: str,
    decision_period: str,
) -> FundamentalFactorBuildResult:
    ordered = tuple(sorted((record for record in records if record.stock_code == stock_code), key=lambda item: item.period))
    current = next((record for record in ordered if record.period == decision_period), None)
    if current is None:
        return FundamentalFactorBuildResult(
            diagnostics=(
                FactorDiagnostic(
                    code="fundamental_revenue.current_period_missing",
                    factor_name="fundamental.revenue",
                    stock_code=stock_code,
                    message=f"current revenue period missing; period={decision_period}",
                ),
            )
        )

    records_out: list[FactorRecord] = []
    diagnostics: list[FactorDiagnostic] = []
    _append_ratio_factor(records_out, diagnostics, current, _same_month_previous_year(ordered, current), "fundamental.revenue_yoy")
    _append_ratio_factor(records_out, diagnostics, current, _previous_month(ordered, current), "fundamental.revenue_mom")
    records_out.append(_string_factor(current, "fundamental.revenue_3m_trend", _three_month_trend(ordered, current)))
    records_out.append(_integer_factor(current, "fundamental.revenue_new_high", _new_high_flag(ordered, current)))
    return FundamentalFactorBuildResult(records=tuple(records_out), diagnostics=tuple(diagnostics))
```

Add helper functions in the same file:

```python
def _factor_metadata(record: MonthlyRevenueRecord) -> dict[str, object]:
    return {
        "period": record.period,
        "announced_date": record.announced_date,
        "source": record.source,
    }


def _base_record(record: MonthlyRevenueRecord, factor_name: str, value: Decimal | int | str) -> FactorRecord:
    return FactorRecord(
        factor_name=factor_name,
        stock_code=record.stock_code,
        as_of_date=record.as_of_date,
        available_date=record.available_date,
        value=value,
        score_bp=None,
        quality=record.quality,
        missing_policy=MissingPolicy.SKIP,
        source_version=record.source_version,
        metadata=_factor_metadata(record),
    )
```

Implement `_append_ratio_factor`, `_same_month_previous_year`, `_previous_month`, `_three_month_trend`, `_new_high_flag`, `_string_factor`, and `_integer_factor` in the same file. Ratio formula is `(current.revenue - baseline.revenue) / baseline.revenue` using `Decimal`; if baseline missing or zero, emit diagnostic and no record for that ratio factor.

- [ ] **Step 4: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_revenue_factor_pack.py tests\test_fundamental_factor_adapters.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add decision_module/factors/fundamental_adapters.py tests/test_revenue_factor_pack.py
git commit -m "month5: add revenue factor pack adapters"
```

## Task 2: Missing Baseline Diagnostics and Gate Behavior

**Files:**
- Modify: `tests/test_revenue_factor_pack.py`

- [ ] **Step 1: Add focused regression tests**

Append to `tests/test_revenue_factor_pack.py`:

```python
from decision_module.factors.factor_gate import FactorGate


def test_revenue_factor_pack_reports_missing_yoy_baseline_without_neutral_record():
    records = (
        _record("2026-04", "120", date(2026, 5, 10)),
        _record("2026-05", "150", date(2026, 6, 10)),
    )

    result = build_revenue_factor_pack(records, stock_code="2330", decision_period="2026-05")

    assert "fundamental.revenue_yoy" not in {record.factor_name for record in result.records}
    assert any(item.code == "fundamental_revenue.baseline_missing" for item in result.diagnostics)


def test_revenue_factor_gate_skips_future_available_date():
    records = (
        _record("2025-05", "100", date(2025, 6, 10)),
        _record("2026-04", "120", date(2026, 5, 10)),
        _record("2026-05", "150", date(2026, 6, 20)),
    )

    result = build_revenue_factor_pack(records, stock_code="2330", decision_period="2026-05")
    gate_result = FactorGate().validate_for_decision(
        result.records,
        decision_date=date(2026, 6, 16),
    )

    assert gate_result.accepted == ()
    assert len(gate_result.skipped) == len(result.records)
    assert gate_result.diagnostics[0].code == "factor.skipped_lookahead"
```

- [ ] **Step 2: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_revenue_factor_pack.py tests\test_factor_gate.py tests\test_factor_contract.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_revenue_factor_pack.py
git commit -m "test: cover revenue factor missing baselines and lookahead gate"
```

## Task 3: Documentation Sync

**Files:**
- Modify: `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`

- [ ] **Step 1: Update docs**

Document Revenue YoY / MoM / 3M trend / new high factor adapters as factor-layer only, diagnostic-aware, and not connected to `ScoringEngine`.

- [ ] **Step 2: Review diff**

```powershell
git diff -- docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md
```

Expected: docs do not claim strategy scoring changed.

- [ ] **Step 3: Commit**

```powershell
git add docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md
git commit -m "docs: document revenue factor pack"
```

## Final Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_revenue_factor_pack.py tests\test_fundamental_factor_adapters.py tests\test_factor_gate.py tests\test_factor_contract.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile decision_module\factors\fundamental_adapters.py
git status --short --branch
```
