# Month 5 Valuation Presentation Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the conservative valuation presentation policy boundary for Month 5 Fundamental Layer without implying buy/sell actions or producing target prices.

**Architecture:** Valuation data must enter as governed observations with `available_date`, `quality`, `source_version`, and optional raw metric values. The first implementation only classifies relative valuation percentile bands and emits diagnostics / `FactorRecord` metadata; it must not connect to `ScoringEngine`, write formal SQLite, modify the UI main flow, or infer valuation from raw CSV.

**Tech Stack:** Python, pytest, existing `decision_module/factors/` contract, existing `FactorGate`, docs under `docs/`.

---

## Entry Conditions

Before implementation, confirm:

- Current branch is clean or only contains this task's intended changes.
- Month 5 preflight commits exist on `main`:
  - `month5: add fundamental preflight contracts`
  - `month5: add fundamental availability mapping contract`
  - `month5: add monthly revenue availability csv entrypoint`
- No formal SQLite migration is part of this task.
- No UI change is part of this task.
- No data-source fetcher is part of this task.

---

## Required Source Documents

Read these before writing code:

- `AGENTS.md`
- `docs/agents/README.md`
- `docs/agents/shared_context.md`
- `docs/agents/git_exclusions.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- `docs/01_architecture/system_architecture.md`
- `docs/agents/skills_registry.md`
- `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- `docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md`

---

## Non-Negotiable Policy Rules

- Internal `ValuationBand` names must not imply buy/sell advice:
  - `LOW_RELATIVE`
  - `MID_RELATIVE`
  - `HIGH_RELATIVE`
  - `UNAVAILABLE`
- UI wording, if ever needed later, must be mapped separately:
  - `LOW_RELATIVE` -> `相對低估值區`
  - `MID_RELATIVE` -> `中性估值區`
  - `HIGH_RELATIVE` -> `相對高估值區`
  - `UNAVAILABLE` -> `資料不足`
- Every valuation policy result must include `policy_version="valuation_presentation_policy_v1"`.
- `ValuationObservation` may preserve raw `metric_value`, but this phase must not derive:
  - `fair_value`
  - `target_price`
  - `upside_pct`
  - `buy_signal`
  - `sell_signal`
  - `recommendation`
- Missing `industry_percentile_bp` must produce `UNAVAILABLE` or diagnostic-only output. It must not fall back to `MID_RELATIVE`.
- Adapter output must preserve:
  - `available_date`
  - `quality`
  - `missing_policy`
  - `source_version`
  - diagnostics
- This task must not:
  - connect to `ScoringEngine`
  - write formal SQLite
  - change the UI main flow
  - infer valuation from raw CSV

---

## File Structure

### Create

- `decision_module/factors/valuation_policy.py`
  - Owns valuation DTOs, relative band classifier, UI-label mapping, and forbidden-output guard.
- `decision_module/factors/valuation_adapters.py`
  - Converts governed valuation observations into `FactorRecord` only when policy allows a usable relative band.
- `tests/test_valuation_policy.py`
  - Unit tests for policy classification, versioning, missing percentile behavior, labels, and forbidden outputs.
- `tests/test_valuation_factor_adapters.py`
  - Unit tests for adapter output, diagnostics, available-date preservation, and `FactorGate` no-look-ahead behavior.

### Modify

- `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
  - Document valuation policy as presentation-only and not a target-price engine.
- `docs/00_core/PROJECT_SNAPSHOT.md`
  - Update Month 5 preflight current state.
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - Update Month 5 valuation policy status.
- `docs/01_architecture/system_architecture.md`
  - Document valuation policy / adapter boundary and forbidden outputs.
- `docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md`
  - Add status note that valuation presentation policy exists.

### Do Not Modify

- `decision_module/scoring_engine.py`
- `app_module/recommendation_service.py`
- `app_module/backtest_service.py`
- `data_module/db_manager.py`
- `ui_qt/`
- Formal data under `D:/Min/Python/Project/FA_Data`

---

## Task 1: Valuation Policy DTOs and Band Classifier

**Files:**

- Create: `decision_module/factors/valuation_policy.py`
- Test: `tests/test_valuation_policy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_valuation_policy.py` with:

```python
from datetime import date
from decimal import Decimal

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality
from decision_module.factors.valuation_policy import (
    VALUATION_PRESENTATION_POLICY_VERSION,
    ValuationBand,
    ValuationObservation,
    classify_relative_valuation,
    valuation_band_ui_label,
)


def test_classify_relative_valuation_uses_non_trading_band_names():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)

    assert result.band == ValuationBand.LOW_RELATIVE
    assert result.policy_version == VALUATION_PRESENTATION_POLICY_VERSION
    assert result.metric_value == Decimal("18.5")
    assert result.diagnostics == ()


def test_classify_relative_valuation_mid_and_high_relative_bands():
    mid = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("22"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=5000,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )
    high = ValuationObservation(
        stock_code="2317",
        metric_name="pe",
        metric_value=Decimal("45"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=8500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    assert classify_relative_valuation(mid).band == ValuationBand.MID_RELATIVE
    assert classify_relative_valuation(high).band == ValuationBand.HIGH_RELATIVE


def test_missing_industry_percentile_is_unavailable_not_neutral():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=None,
        quality=FactorQuality.DEGRADED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)

    assert result.band == ValuationBand.UNAVAILABLE
    assert result.band != ValuationBand.MID_RELATIVE
    assert result.diagnostics[0].code == "valuation.missing_industry_percentile"


def test_invalid_percentile_is_unavailable():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=10001,
        quality=FactorQuality.DEGRADED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)

    assert result.band == ValuationBand.UNAVAILABLE
    assert result.diagnostics[0].code == "valuation.invalid_industry_percentile"


def test_valuation_band_ui_labels_are_descriptive_not_actionable():
    assert valuation_band_ui_label(ValuationBand.LOW_RELATIVE) == "相對低估值區"
    assert valuation_band_ui_label(ValuationBand.MID_RELATIVE) == "中性估值區"
    assert valuation_band_ui_label(ValuationBand.HIGH_RELATIVE) == "相對高估值區"
    assert valuation_band_ui_label(ValuationBand.UNAVAILABLE) == "資料不足"


def test_policy_output_forbids_target_price_and_recommendation_fields():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = classify_relative_valuation(observation)
    output = result.to_metadata()

    forbidden_fields = {
        "target_price",
        "fair_value",
        "upside_pct",
        "buy_signal",
        "sell_signal",
        "recommendation",
    }
    assert forbidden_fields.isdisjoint(output)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_policy.py -q -o addopts=
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'decision_module.factors.valuation_policy'`.

- [ ] **Step 3: Implement minimal policy module**

Create `decision_module/factors/valuation_policy.py`:

```python
"""估值呈現政策：只分類相對估值區間，不產生目標價或交易建議。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


VALUATION_PRESENTATION_POLICY_VERSION = "valuation_presentation_policy_v1"


class ValuationBand(str, Enum):
    LOW_RELATIVE = "low_relative"
    MID_RELATIVE = "mid_relative"
    HIGH_RELATIVE = "high_relative"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ValuationObservation:
    stock_code: str
    metric_name: str
    metric_value: Decimal | None
    as_of_date: date
    available_date: date
    industry_percentile_bp: int | None
    quality: FactorQuality
    source: str
    source_version: str


@dataclass(frozen=True)
class ValuationPolicyResult:
    stock_code: str
    metric_name: str
    metric_value: Decimal | None
    as_of_date: date
    available_date: date
    industry_percentile_bp: int | None
    band: ValuationBand
    quality: FactorQuality
    source: str
    source_version: str
    policy_version: str = VALUATION_PRESENTATION_POLICY_VERSION
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_metadata(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "metric_value": str(self.metric_value) if self.metric_value is not None else None,
            "industry_percentile_bp": self.industry_percentile_bp,
            "valuation_band": self.band.value,
            "valuation_band_label": valuation_band_ui_label(self.band),
            "policy_version": self.policy_version,
            "source": self.source,
        }


def classify_relative_valuation(
    observation: ValuationObservation,
) -> ValuationPolicyResult:
    diagnostics: list[FactorDiagnostic] = []
    percentile = observation.industry_percentile_bp

    if percentile is None:
        diagnostics.append(
            _diagnostic(
                observation,
                "valuation.missing_industry_percentile",
                "industry_percentile_bp missing; valuation band unavailable",
            )
        )
        band = ValuationBand.UNAVAILABLE
    elif percentile < 0 or percentile > 10000:
        diagnostics.append(
            _diagnostic(
                observation,
                "valuation.invalid_industry_percentile",
                "industry_percentile_bp outside 0..10000; valuation band unavailable",
            )
        )
        band = ValuationBand.UNAVAILABLE
    elif percentile <= 2000:
        band = ValuationBand.LOW_RELATIVE
    elif percentile <= 8000:
        band = ValuationBand.MID_RELATIVE
    else:
        band = ValuationBand.HIGH_RELATIVE

    return ValuationPolicyResult(
        stock_code=observation.stock_code,
        metric_name=observation.metric_name,
        metric_value=observation.metric_value,
        as_of_date=observation.as_of_date,
        available_date=observation.available_date,
        industry_percentile_bp=observation.industry_percentile_bp,
        band=band,
        quality=observation.quality,
        source=observation.source,
        source_version=observation.source_version,
        diagnostics=tuple(diagnostics),
    )


def valuation_band_ui_label(band: ValuationBand) -> str:
    return {
        ValuationBand.LOW_RELATIVE: "相對低估值區",
        ValuationBand.MID_RELATIVE: "中性估值區",
        ValuationBand.HIGH_RELATIVE: "相對高估值區",
        ValuationBand.UNAVAILABLE: "資料不足",
    }[band]


def _diagnostic(
    observation: ValuationObservation,
    code: str,
    message: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=code,
        factor_name=f"valuation.{observation.metric_name}",
        stock_code=observation.stock_code,
        message=message,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_policy.py -q -o addopts=
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

Run:

```powershell
git add decision_module/factors/valuation_policy.py tests/test_valuation_policy.py
git commit -m "month5: add valuation presentation policy"
```

---

## Task 2: Valuation Factor Adapter Boundary

**Files:**

- Create: `decision_module/factors/valuation_adapters.py`
- Test: `tests/test_valuation_factor_adapters.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_valuation_factor_adapters.py`:

```python
from datetime import date
from decimal import Decimal

from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy
from decision_module.factors.factor_gate import FactorGate
from decision_module.factors.valuation_adapters import build_relative_valuation_factor
from decision_module.factors.valuation_policy import ValuationBand, ValuationObservation


def test_valuation_adapter_preserves_factor_contract_and_policy_metadata():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = build_relative_valuation_factor(observation)

    assert result.diagnostics == ()
    assert len(result.records) == 1
    record = result.records[0]
    assert record.factor_name == "valuation.pe.relative_band"
    assert record.stock_code == "2330"
    assert record.as_of_date == date(2026, 6, 15)
    assert record.available_date == date(2026, 6, 16)
    assert record.quality == FactorQuality.OBSERVED
    assert record.missing_policy == MissingPolicy.SKIP
    assert record.source_version == "daily-price-pe-2026-06-16"
    assert record.score_bp is None
    assert record.value == ValuationBand.LOW_RELATIVE.value
    assert record.metadata["policy_version"] == "valuation_presentation_policy_v1"
    assert record.metadata["industry_percentile_bp"] == 1500
    assert record.metadata["metric_value"] == "18.5"


def test_valuation_adapter_diagnostic_only_when_percentile_missing():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=None,
        quality=FactorQuality.DEGRADED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = build_relative_valuation_factor(observation)

    assert result.records == ()
    assert result.diagnostics[0].code == "valuation.missing_industry_percentile"


def test_valuation_adapter_output_forbids_target_price_and_recommendations():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 16),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = build_relative_valuation_factor(observation)
    record = result.records[0]

    forbidden_fields = {
        "target_price",
        "fair_value",
        "upside_pct",
        "buy_signal",
        "sell_signal",
        "recommendation",
    }
    assert forbidden_fields.isdisjoint(record.metadata)


def test_valuation_factor_gate_skips_future_available_date():
    observation = ValuationObservation(
        stock_code="2330",
        metric_name="pe",
        metric_value=Decimal("18.5"),
        as_of_date=date(2026, 6, 15),
        available_date=date(2026, 6, 20),
        industry_percentile_bp=1500,
        quality=FactorQuality.OBSERVED,
        source="daily_prices.pe",
        source_version="daily-price-pe-2026-06-16",
    )

    result = build_relative_valuation_factor(observation)
    gate_result = FactorGate(decision_date=date(2026, 6, 16)).apply(result.records)

    assert gate_result.records == ()
    assert gate_result.diagnostics[0].code == "factor.future_available_date_skipped"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_factor_adapters.py -q -o addopts=
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'decision_module.factors.valuation_adapters'`.

- [ ] **Step 3: Implement minimal adapter**

Create `decision_module/factors/valuation_adapters.py`:

```python
"""估值 factor adapter：只輸出相對估值區間，不輸出交易建議。"""

from __future__ import annotations

from dataclasses import dataclass

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorRecord, MissingPolicy
from decision_module.factors.valuation_policy import (
    ValuationBand,
    ValuationObservation,
    classify_relative_valuation,
)


@dataclass(frozen=True)
class ValuationFactorBuildResult:
    records: tuple[FactorRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def build_relative_valuation_factor(
    observation: ValuationObservation,
) -> ValuationFactorBuildResult:
    policy_result = classify_relative_valuation(observation)
    diagnostics = tuple(policy_result.diagnostics)

    if policy_result.band == ValuationBand.UNAVAILABLE:
        return ValuationFactorBuildResult(records=(), diagnostics=diagnostics)

    record = FactorRecord(
        stock_code=policy_result.stock_code,
        factor_name=f"valuation.{policy_result.metric_name}.relative_band",
        as_of_date=policy_result.as_of_date,
        available_date=policy_result.available_date,
        value=policy_result.band.value,
        score_bp=None,
        quality=policy_result.quality,
        missing_policy=MissingPolicy.SKIP,
        source_version=policy_result.source_version,
        metadata=policy_result.to_metadata(),
    )
    return ValuationFactorBuildResult(records=(record,), diagnostics=diagnostics)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_factor_adapters.py -q -o addopts=
```

Expected: `4 passed`.

- [ ] **Step 5: Run focused factor regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_policy.py tests\test_valuation_factor_adapters.py tests\test_factor_gate.py tests\test_factor_contract.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add decision_module/factors/valuation_adapters.py tests/test_valuation_factor_adapters.py
git commit -m "month5: add valuation factor adapter boundary"
```

---

## Task 3: Documentation Sync

**Files:**

- Modify: `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md`

- [ ] **Step 1: Update source inventory valuation policy section**

In `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`, add a subsection under valuation-related notes:

```markdown
### 5.3 估值呈現政策 v1

`decision_module/factors/valuation_policy.py` 定義 `valuation_presentation_policy_v1`。本政策只允許把 P/E、P/B、P/S 或殖利率等估值 metric 呈現為相對估值區間：

- `LOW_RELATIVE`：相對低估值區
- `MID_RELATIVE`：中性估值區
- `HIGH_RELATIVE`：相對高估值區
- `UNAVAILABLE`：資料不足

本政策禁止產生 `fair_value`、`target_price`、`upside_pct`、`buy_signal`、`sell_signal` 或 `recommendation`。缺少 `industry_percentile_bp` 時只能回 `UNAVAILABLE` 或 diagnostics，不得假設為中性估值區。此政策目前不代表任何估值資料來源已正式可用，也不寫入正式 SQLite。
```

- [ ] **Step 2: Update Snapshot**

In `docs/00_core/PROJECT_SNAPSHOT.md`, update Month 5 current-state bullet to include:

```text
估值呈現政策 v1 已建立 presentation-only 邊界，僅輸出相對估值區間、policy_version、quality 與 diagnostics，不輸出目標價、合理價、上漲空間或交易建議。
```

- [ ] **Step 3: Update 6M Roadmap**

In `docs/00_core/ROADMAP_6M_ENGINEERING.md`, update the Month 5 immediate status and update log to mention:

```text
估值呈現政策 v1 已採相對分位區間與 forbidden-output regression，缺分位不回中性。
```

- [ ] **Step 4: Update architecture**

In `docs/01_architecture/system_architecture.md`, add a note near factor layer / fundamental preflight:

```text
`decision_module/factors/valuation_policy.py` 與 `valuation_adapters.py` 只建立估值 presentation boundary。它們不得 import 或呼叫 `ScoringEngine`，不得產生 target price / fair value / upside / buy-sell recommendation，且缺少 `industry_percentile_bp` 時不得輸出中性估值區。
```

- [ ] **Step 5: Update Month 5 preflight plan status**

In `docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md`, update WP-4 status:

```markdown
**Status update 2026-06-16:** Valuation presentation policy v1 exists as a presentation-only factor boundary. It preserves raw metric value, available_date, quality, missing policy, source version, diagnostics, and policy_version; it forbids target price, fair value, upside percent, buy/sell signals, and recommendations.
```

- [ ] **Step 6: Run doc diff review**

Run:

```powershell
git diff -- docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md
```

Expected: docs describe policy status without claiming valuation data is formally available.

- [ ] **Step 7: Commit**

Run:

```powershell
git add docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/01_architecture/system_architecture.md docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md
git commit -m "docs: document valuation presentation policy"
```

---

## Task 4: Final Verification

**Files:**

- Verify only; no edits expected.

- [ ] **Step 1: Run focused pytest**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_valuation_policy.py tests\test_valuation_factor_adapters.py tests\test_factor_gate.py tests\test_factor_contract.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 2: Run py_compile**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile decision_module\factors\valuation_policy.py decision_module\factors\valuation_adapters.py
```

Expected: exit code 0.

- [ ] **Step 3: Run financial float boundary guard**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: exit code 0.

- [ ] **Step 4: Run mypy**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy data_module decision_module
```

Expected: `Success: no issues found`.

- [ ] **Step 5: Confirm no forbidden integrations**

Run:

```powershell
rg "valuation_policy|valuation_adapters" decision_module app_module ui_qt data_module
```

Expected:

- Matches in `decision_module/factors/valuation_policy.py`
- Matches in `decision_module/factors/valuation_adapters.py`
- No import from `decision_module/scoring_engine.py`
- No UI import
- No DB manager import

- [ ] **Step 6: Confirm clean working tree**

Run:

```powershell
git status --short --branch
```

Expected: clean working tree after commits.

---

## Execution Notes for New Conversation

Paste this into the new conversation:

```text
請使用繁體中文。工作目錄：
C:\Projects\PythonProjects\technical_analysis

先閱讀並遵守：
1. AGENTS.md
2. docs/agents/README.md
3. docs/agents/shared_context.md
4. docs/agents/git_exclusions.md
5. docs/00_core/PROJECT_SNAPSHOT.md
6. docs/00_core/DEVELOPMENT_ROADMAP.md
7. docs/00_core/ROADMAP_6M_ENGINEERING.md
8. docs/00_core/LEGACY_ROADMAP_CARRYOVER.md
9. docs/01_architecture/system_architecture.md
10. docs/agents/skills_registry.md
11. docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md
12. docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md
13. docs/superpowers/plans/2026-06-16-month5-valuation-presentation-policy.md

任務：
依照 docs/superpowers/plans/2026-06-16-month5-valuation-presentation-policy.md 執行 Month 5「估值呈現政策」。

硬性限制：
- ValuationBand 內部 enum 只能使用 LOW_RELATIVE / MID_RELATIVE / HIGH_RELATIVE / UNAVAILABLE。
- policy_version 使用 valuation_presentation_policy_v1。
- 可保留 raw metric_value。
- 不得推導 fair_value、target_price、upside_pct。
- tests 必須包含 forbidden output regression，禁止 target_price / fair_value / upside_pct / buy_signal / sell_signal / recommendation。
- 缺 industry_percentile_bp 時必須 band=UNAVAILABLE 或 diagnostic_only，不得回傳 neutral。
- adapter 的 FactorRecord 必須保留 available_date、quality、missing_policy、source_version、diagnostics。
- 不接 ScoringEngine、不寫正式 SQLite、不改 UI 主流程、不從 raw CSV 推估估值。

完成後跑 plan 中的驗證，確認 working tree，分段 commit。
```

---

## Self-Review Checklist

- Spec coverage:
  - ValuationBand non-trading enum names covered in Task 1.
  - `policy_version` covered in Task 1 and Task 2.
  - Raw `metric_value` preserved and target/fair/upside forbidden covered in Task 1 and Task 2.
  - Forbidden output regression covered in both policy and adapter tests.
  - Missing percentile unavailable behavior covered in Task 1 and Task 2.
  - FactorRecord contract preservation covered in Task 2.
  - No ScoringEngine / SQLite / UI / raw CSV inference covered in non-goals and final verification.
- Placeholder scan:
  - No TBD / TODO / "fill in later" placeholders.
- Type consistency:
  - `ValuationObservation`, `ValuationPolicyResult`, `ValuationBand`, `build_relative_valuation_factor`, and `VALUATION_PRESENTATION_POLICY_VERSION` names are consistent across tasks.
