# Month 5 Valuation Data Layer v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a governed valuation metric data layer that supplies industry-relative percentiles to the existing valuation presentation policy.

**Architecture:** Valuation metric observations must preserve `available_date`, `quality`, `source_version`, raw metric value, and optional `industry_percentile_bp`. The layer must not produce target prices, fair values, upside percentages, or recommendations, and must not connect to `ScoringEngine`.

**Tech Stack:** Python, pytest, `Decimal`, SQLite rows or row-like mappings, existing `valuation_policy.py` and `valuation_adapters.py`.

---

## Entry Conditions

- Complete the valuation presentation policy plan already committed.
- Complete or explicitly defer formal SQLite migration for `fundamental_valuation_metrics`.
- Confirm no P/B, P/S, or yield source is fabricated; unavailable metrics produce diagnostics.

## Task 1: Valuation Metric Observation Builder

**Files:**
- Create: `data_module/valuation_data.py`
- Test: `tests/test_valuation_data.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_valuation_data.py`:

```python
from datetime import date
from decimal import Decimal

from data_module.valuation_data import (
    build_valuation_observations,
    calculate_industry_percentiles_bp,
)
from decision_module.factors.factor_dtos import FactorQuality


def test_calculate_industry_percentiles_bp_uses_same_industry_universe():
    rows = [
        {"stock_code": "2330", "industry": "半導體", "metric_value": Decimal("18")},
        {"stock_code": "2303", "industry": "半導體", "metric_value": Decimal("22")},
        {"stock_code": "2454", "industry": "半導體", "metric_value": Decimal("30")},
        {"stock_code": "2317", "industry": "電子零組件", "metric_value": Decimal("12")},
    ]

    result = calculate_industry_percentiles_bp(rows)

    assert result[("2330", "半導體")] == 3333
    assert result[("2303", "半導體")] == 6667
    assert result[("2454", "半導體")] == 10000
    assert result[("2317", "電子零組件")] is None


def test_build_valuation_observations_preserves_contract():
    observations = build_valuation_observations(
        [
            {
                "stock_code": "2330",
                "as_of_date": "2026-06-15",
                "available_date": "2026-06-16",
                "metric_name": "pe",
                "metric_value": "18.5",
                "industry": "半導體",
                "industry_percentile_bp": "3333",
                "source": "daily_prices.pe",
                "source_version": "daily-price-pe-2026-06-16",
                "quality": "observed",
            }
        ]
    )

    assert observations.diagnostics == ()
    observation = observations.records[0]
    assert observation.stock_code == "2330"
    assert observation.metric_name == "pe"
    assert observation.metric_value == Decimal("18.5")
    assert observation.available_date == date(2026, 6, 16)
    assert observation.industry_percentile_bp == 3333
    assert observation.quality == FactorQuality.OBSERVED
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_data.py -q -o addopts=
```

Expected: collection fails with `ModuleNotFoundError: No module named 'data_module.valuation_data'`.

- [ ] **Step 3: Implement valuation data module**

Create `data_module/valuation_data.py` with:

```python
"""估值資料層：產生治理後的 ValuationObservation，不推導目標價。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality
from decision_module.factors.valuation_policy import ValuationObservation


@dataclass(frozen=True)
class ValuationObservationBuildResult:
    records: tuple[ValuationObservation, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def calculate_industry_percentiles_bp(
    rows: list[Mapping[str, object]],
) -> dict[tuple[str, str], int | None]:
    by_industry: dict[str, list[tuple[str, Decimal]]] = {}
    for row in rows:
        stock_code = str(row["stock_code"])
        industry = str(row["industry"])
        value = row["metric_value"]
        metric_value = value if isinstance(value, Decimal) else Decimal(str(value))
        by_industry.setdefault(industry, []).append((stock_code, metric_value))

    result: dict[tuple[str, str], int | None] = {}
    for industry, items in by_industry.items():
        if len(items) < 2:
            for stock_code, _ in items:
                result[(stock_code, industry)] = None
            continue
        ranked = sorted(items, key=lambda item: (item[1], item[0]))
        denominator = len(ranked)
        for index, (stock_code, _) in enumerate(ranked, start=1):
            result[(stock_code, industry)] = int(round(index * 10000 / denominator))
    return result


def build_valuation_observations(
    rows: list[Mapping[str, str]],
) -> ValuationObservationBuildResult:
    records: list[ValuationObservation] = []
    diagnostics: list[FactorDiagnostic] = []
    for row in rows:
        stock_code = row.get("stock_code", "").strip()
        metric_name = row.get("metric_name", "").strip()
        try:
            metric_value = Decimal(row.get("metric_value", "").strip())
            as_of_date = _parse_date(row.get("as_of_date", ""))
            available_date = _parse_date(row.get("available_date", ""))
            percentile_raw = row.get("industry_percentile_bp", "").strip()
            percentile = int(percentile_raw) if percentile_raw else None
            quality = FactorQuality(row.get("quality", "").strip())
        except (InvalidOperation, ValueError):
            diagnostics.append(
                FactorDiagnostic(
                    code="valuation_data.invalid_row",
                    factor_name=f"valuation.{metric_name or 'unknown'}",
                    stock_code=stock_code,
                    message="valuation row has invalid metric, date, percentile, or quality",
                )
            )
            continue
        records.append(
            ValuationObservation(
                stock_code=stock_code,
                metric_name=metric_name,
                metric_value=metric_value,
                as_of_date=as_of_date,
                available_date=available_date,
                industry_percentile_bp=percentile,
                quality=quality,
                source=row.get("source", "").strip(),
                source_version=row.get("source_version", "").strip(),
            )
        )
    return ValuationObservationBuildResult(records=tuple(records), diagnostics=tuple(diagnostics))


def _parse_date(value: str):
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()
```

- [ ] **Step 4: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_data.py -q -o addopts=
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add data_module/valuation_data.py tests/test_valuation_data.py
git commit -m "month5: add valuation metric data layer"
```

## Task 2: Adapter Integration Regression

**Files:**
- Modify: `tests/test_valuation_data.py`

- [ ] **Step 1: Add tests connecting data layer to existing adapter**

Append:

```python
from decision_module.factors.valuation_adapters import build_relative_valuation_factor


def test_valuation_data_layer_feeds_existing_relative_band_adapter():
    observations = build_valuation_observations(
        [
            {
                "stock_code": "2330",
                "as_of_date": "2026-06-15",
                "available_date": "2026-06-16",
                "metric_name": "pe",
                "metric_value": "18.5",
                "industry": "半導體",
                "industry_percentile_bp": "1500",
                "source": "daily_prices.pe",
                "source_version": "daily-price-pe-2026-06-16",
                "quality": "observed",
            }
        ]
    )

    factor_result = build_relative_valuation_factor(observations.records[0])

    record = factor_result.records[0]
    assert record.factor_name == "valuation.pe.relative_band"
    assert record.metadata["policy_version"] == "valuation_presentation_policy_v1"
    assert record.metadata["metric_value"] == "18.5"


def test_valuation_data_layer_keeps_missing_percentile_diagnostic_only():
    observations = build_valuation_observations(
        [
            {
                "stock_code": "2330",
                "as_of_date": "2026-06-15",
                "available_date": "2026-06-16",
                "metric_name": "pe",
                "metric_value": "18.5",
                "industry": "半導體",
                "industry_percentile_bp": "",
                "source": "daily_prices.pe",
                "source_version": "daily-price-pe-2026-06-16",
                "quality": "degraded",
            }
        ]
    )

    factor_result = build_relative_valuation_factor(observations.records[0])

    assert factor_result.records == ()
    assert factor_result.diagnostics[0].code == "valuation.missing_industry_percentile"
```

- [ ] **Step 2: Run focused valuation tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_data.py tests\test_valuation_policy.py tests\test_valuation_factor_adapters.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_valuation_data.py
git commit -m "test: cover valuation data adapter bridge"
```

## Task 3: Documentation Sync

**Files:**
- Modify: `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`

- [ ] **Step 1: Update docs**

Document that the valuation data layer creates governed observations and industry percentiles, while the existing presentation policy remains the only valuation output boundary.

- [ ] **Step 2: Review diff**

```powershell
git diff -- docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md
```

Expected: docs still forbid target price, fair value, upside, and recommendation.

- [ ] **Step 3: Commit**

```powershell
git add docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md
git commit -m "docs: document valuation data layer"
```

## Final Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_data.py tests\test_valuation_policy.py tests\test_valuation_factor_adapters.py tests\test_factor_gate.py tests\test_factor_contract.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\valuation_data.py decision_module\factors\valuation_policy.py decision_module\factors\valuation_adapters.py
rg "valuation_policy|valuation_adapters|valuation_data" decision_module app_module ui_qt data_module
git status --short --branch
```

Expected `rg` matches only the new data layer and existing factor modules unless this plan explicitly documents another tested import.
