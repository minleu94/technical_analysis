# Month 5 Abnormal Fundamental Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conservative abnormal fundamental flags and surface them as diagnostics in research and Daily Decision Desk flows.

**Architecture:** Flags are warnings, not accounting rewrites and not automatic score penalties. They consume governed revenue / valuation / statement observations, produce `FactorDiagnostic`-compatible metadata, and integrate through application services without importing `ScoringEngine` or recalculating UI-layer decisions.

**Tech Stack:** Python, pytest, existing `FactorDiagnostic`, `FactorService`, `DecisionDeskRiskPromptService`, Research Run metadata contracts.

---

## Entry Conditions

- Complete revenue factor pack v1.
- Complete valuation data layer v1.
- Confirm Daily Decision Desk UI remains service-snapshot only; UI must not import factor calculation modules.

## Task 1: Abnormal Fundamental Flag Policy

**Files:**
- Create: `decision_module/factors/abnormal_fundamental_flags.py`
- Test: `tests/test_abnormal_fundamental_flags.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_abnormal_fundamental_flags.py`:

```python
from datetime import date
from decimal import Decimal

from decision_module.factors.abnormal_fundamental_flags import (
    AbnormalFundamentalFlag,
    build_abnormal_fundamental_diagnostics,
)


def test_abnormal_fundamental_flags_mark_revenue_and_profit_divergence():
    diagnostics = build_abnormal_fundamental_diagnostics(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=Decimal("0.25"),
        operating_profit_yoy=Decimal("-0.10"),
        one_off_gain_ratio=None,
        quality_warnings=(),
        source_version="fundamental-diagnostics-v1",
    )

    assert diagnostics[0].code == AbnormalFundamentalFlag.REVENUE_PROFIT_DIVERGENCE.value
    assert "revenue_yoy=0.25" in diagnostics[0].message
    assert "operating_profit_yoy=-0.10" in diagnostics[0].message


def test_abnormal_fundamental_flags_mark_one_off_gain():
    diagnostics = build_abnormal_fundamental_diagnostics(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=Decimal("0.05"),
        operating_profit_yoy=Decimal("0.04"),
        one_off_gain_ratio=Decimal("0.35"),
        quality_warnings=(),
        source_version="fundamental-diagnostics-v1",
    )

    assert diagnostics[0].code == AbnormalFundamentalFlag.ONE_OFF_GAIN_RISK.value


def test_abnormal_fundamental_flags_preserve_quality_warnings():
    diagnostics = build_abnormal_fundamental_diagnostics(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=None,
        operating_profit_yoy=None,
        one_off_gain_ratio=None,
        quality_warnings=("fundamental_availability.missing_announced_date",),
        source_version="fundamental-diagnostics-v1",
    )

    assert diagnostics[0].code == AbnormalFundamentalFlag.DATA_QUALITY_GAP.value
    assert "missing_announced_date" in diagnostics[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_abnormal_fundamental_flags.py -q -o addopts=
```

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement flag policy**

Create `decision_module/factors/abnormal_fundamental_flags.py`:

```python
"""保守基本面異常旗標：只產生 diagnostics，不改寫財報或分數。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from decision_module.factors.factor_dtos import FactorDiagnostic


class AbnormalFundamentalFlag(str, Enum):
    REVENUE_PROFIT_DIVERGENCE = "abnormal_fundamental.revenue_profit_divergence"
    ONE_OFF_GAIN_RISK = "abnormal_fundamental.one_off_gain_risk"
    DATA_QUALITY_GAP = "abnormal_fundamental.data_quality_gap"


def build_abnormal_fundamental_diagnostics(
    *,
    stock_code: str,
    as_of_date: date,
    revenue_yoy: Decimal | None,
    operating_profit_yoy: Decimal | None,
    one_off_gain_ratio: Decimal | None,
    quality_warnings: tuple[str, ...],
    source_version: str,
) -> tuple[FactorDiagnostic, ...]:
    diagnostics: list[FactorDiagnostic] = []
    factor_name = "fundamental.abnormal_flags"
    if (
        revenue_yoy is not None
        and operating_profit_yoy is not None
        and revenue_yoy > Decimal("0")
        and operating_profit_yoy < Decimal("0")
    ):
        diagnostics.append(
            FactorDiagnostic(
                code=AbnormalFundamentalFlag.REVENUE_PROFIT_DIVERGENCE.value,
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    f"revenue_yoy={revenue_yoy}; operating_profit_yoy={operating_profit_yoy}; "
                    f"as_of_date={as_of_date.isoformat()}; source_version={source_version}"
                ),
            )
        )
    if one_off_gain_ratio is not None and one_off_gain_ratio >= Decimal("0.30"):
        diagnostics.append(
            FactorDiagnostic(
                code=AbnormalFundamentalFlag.ONE_OFF_GAIN_RISK.value,
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    f"one_off_gain_ratio={one_off_gain_ratio}; "
                    f"as_of_date={as_of_date.isoformat()}; source_version={source_version}"
                ),
            )
        )
    for warning in quality_warnings:
        diagnostics.append(
            FactorDiagnostic(
                code=AbnormalFundamentalFlag.DATA_QUALITY_GAP.value,
                factor_name=factor_name,
                stock_code=stock_code,
                message=(
                    f"quality_warning={warning}; "
                    f"as_of_date={as_of_date.isoformat()}; source_version={source_version}"
                ),
            )
        )
    return tuple(diagnostics)
```

- [ ] **Step 4: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_abnormal_fundamental_flags.py -q -o addopts=
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add decision_module/factors/abnormal_fundamental_flags.py tests/test_abnormal_fundamental_flags.py
git commit -m "month5: add abnormal fundamental diagnostics policy"
```

## Task 2: Application Diagnostics Service

**Files:**
- Create: `app_module/fundamental_diagnostics_service.py`
- Test: `tests/test_fundamental_diagnostics_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_fundamental_diagnostics_service.py`:

```python
from datetime import date
from decimal import Decimal

from app_module.fundamental_diagnostics_service import FundamentalDiagnosticsService


def test_fundamental_diagnostics_service_serializes_diagnostics_for_research_metadata():
    service = FundamentalDiagnosticsService()

    result = service.build_metadata(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=Decimal("0.25"),
        operating_profit_yoy=Decimal("-0.10"),
        one_off_gain_ratio=None,
        quality_warnings=(),
        source_version="fundamental-diagnostics-v1",
    )

    assert result["schema_version"] == 1
    assert result["stock_code"] == "2330"
    assert result["diagnostics"][0]["code"] == "abnormal_fundamental.revenue_profit_divergence"
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_diagnostics_service.py -q -o addopts=
```

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement service**

Create `app_module/fundamental_diagnostics_service.py`:

```python
"""Application boundary for fundamental diagnostics metadata."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from decision_module.factors.abnormal_fundamental_flags import (
    build_abnormal_fundamental_diagnostics,
)


class FundamentalDiagnosticsService:
    def build_metadata(
        self,
        *,
        stock_code: str,
        as_of_date: date,
        revenue_yoy: Decimal | None,
        operating_profit_yoy: Decimal | None,
        one_off_gain_ratio: Decimal | None,
        quality_warnings: tuple[str, ...],
        source_version: str,
    ) -> dict[str, Any]:
        diagnostics = build_abnormal_fundamental_diagnostics(
            stock_code=stock_code,
            as_of_date=as_of_date,
            revenue_yoy=revenue_yoy,
            operating_profit_yoy=operating_profit_yoy,
            one_off_gain_ratio=one_off_gain_ratio,
            quality_warnings=quality_warnings,
            source_version=source_version,
        )
        return {
            "schema_version": 1,
            "stock_code": stock_code,
            "as_of_date": as_of_date.isoformat(),
            "source_version": source_version,
            "diagnostics": [item.to_dict() for item in diagnostics],
        }
```

- [ ] **Step 4: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_abnormal_fundamental_flags.py tests\test_fundamental_diagnostics_service.py -q -o addopts=
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app_module/fundamental_diagnostics_service.py tests/test_fundamental_diagnostics_service.py
git commit -m "month5: add fundamental diagnostics application service"
```

## Task 3: Daily Decision Desk Risk Prompt Bridge

**Files:**
- Modify: `app_module/decision_desk_dtos.py`
- Modify: `app_module/decision_desk_risk_prompt_service.py`
- Test: `tests/test_decision_desk_risk_prompt_service.py`
- Test: `tests/test_decision_desk_ui_contract.py`

- [ ] **Step 1: Add tests for fundamental diagnostic prompts**

Extend `tests/test_decision_desk_risk_prompt_service.py` with a case that passes a `fundamental_diagnostics` list into the risk prompt summary input and expects one prompt with source `fundamental`. The prompt text must not say buy, sell, target price, fair value, or recommendation.

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_risk_prompt_service.py::test_risk_prompt_includes_fundamental_diagnostics -q -o addopts=
```

Expected: failure because DTO / service does not expose fundamental diagnostics yet.

- [ ] **Step 3: Add DTO field and service mapping**

Add an optional tuple field named `fundamental_diagnostics` to the risk prompt input DTO currently used by `DecisionDeskRiskPromptService`. Map diagnostics into `DecisionDeskRiskPrompt` records with:

- `source="fundamental"`
- `severity="warning"`
- `reason_token` equal to the diagnostic code
- display message copied from diagnostic message after removing forbidden actionable wording if present

Do not import `decision_module.scoring_engine`, `decision_module.factors.abnormal_fundamental_flags`, or raw data modules in `ui_qt/views/decision_desk_view.py`.

- [ ] **Step 4: Run contract and prompt tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_decision_desk_risk_prompt_service.py tests\test_decision_desk_ui_contract.py -q -o addopts=
```

Expected: tests pass and UI contract remains clean.

- [ ] **Step 5: Commit**

```powershell
git add app_module/decision_desk_dtos.py app_module/decision_desk_risk_prompt_service.py tests/test_decision_desk_risk_prompt_service.py tests/test_decision_desk_ui_contract.py
git commit -m "month5: surface fundamental diagnostics in decision desk prompts"
```

## Task 4: Documentation Sync

**Files:**
- Modify: `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: Update docs**

Document that abnormal fundamental flags are diagnostics only, appear in Research Run metadata / Daily Decision Desk risk prompts, and do not rewrite financial statements or score stocks.

- [ ] **Step 2: Review diff**

```powershell
git diff -- docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md
```

Expected: docs include user-facing interpretation because Daily Decision Desk output changes.

- [ ] **Step 3: Commit**

```powershell
git add docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md
git commit -m "docs: document abnormal fundamental diagnostics"
```

## Final Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_abnormal_fundamental_flags.py tests\test_fundamental_diagnostics_service.py tests\test_decision_desk_risk_prompt_service.py tests\test_decision_desk_ui_contract.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile decision_module\factors\abnormal_fundamental_flags.py app_module\fundamental_diagnostics_service.py app_module\decision_desk_risk_prompt_service.py
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=
git status --short --branch
```
