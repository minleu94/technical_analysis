# Month 5 Availability Data Entrypoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the formal validation entrypoint for monthly revenue announcement / `available_date` mappings.

**Architecture:** Reuse `data_module/fundamental_availability.py`, `data_module/fundamental_availability_sources.py`, and `TWStockConfig.monthly_revenue_availability_file`. The entrypoint validates a governed CSV and emits diagnostics / reports; it does not create formal data, does not rewrite raw CSV, and does not guess availability from raw monthly revenue dates.

**Tech Stack:** Python, pytest, CSV, `pathlib.Path`, existing `FactorDiagnostic` DTOs, `TWStockConfig`.

---

## Entry Conditions

- Read `AGENTS.md`, `docs/agents/git_exclusions.md`, `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`, and `docs/superpowers/plans/2026-06-16-month5-fundamental-layer-preflight.md`.
- Confirm `data_module/fundamental_availability_sources.py` already exposes `load_monthly_revenue_availability_overrides_csv`.
- Confirm this task does not write `DATA_ROOT/meta_data/monthly_revenue_availability.csv`; it only validates a user-provided file.

## Task 1: Validation Service

**Files:**
- Create: `data_module/fundamental_availability_entrypoint.py`
- Test: `tests/test_fundamental_availability_entrypoint.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_fundamental_availability_entrypoint.py`:

```python
from data_module.fundamental_availability_entrypoint import (
    MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES,
    validate_monthly_revenue_availability_file,
)


def test_validate_monthly_revenue_availability_file_accepts_governed_source(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16\n",
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()
    assert result.source_versions == ("announcement-log-2026-06-16",)


def test_validate_monthly_revenue_availability_file_rejects_ungoverned_source(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "financial_data.monthly_revenue_csv,raw-v1\n",
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == "fundamental_availability.raw_csv_not_available_source"


def test_validate_monthly_revenue_availability_file_reports_missing_file(tmp_path):
    result = validate_monthly_revenue_availability_file(
        tmp_path / "monthly_revenue_availability.csv"
    )

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == "fundamental_availability.mapping_file_missing"


def test_allowed_sources_do_not_include_raw_csv_source():
    assert "financial_data.monthly_revenue_csv" not in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_availability_entrypoint.py -q -o addopts=
```

Expected: collection fails with `ModuleNotFoundError: No module named 'data_module.fundamental_availability_entrypoint'`.

- [ ] **Step 3: Implement validation service**

Create `data_module/fundamental_availability_entrypoint.py` with:

```python
"""月營收公告日 mapping 的正式驗證入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_module.fundamental_availability_sources import (
    FundamentalAvailabilityOverride,
    load_monthly_revenue_availability_overrides_csv,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES = frozenset(
    {
        "manual.twse_monthly_revenue_announcement_log",
        "manual.available_date_mapping",
        "twse.monthly_revenue_announcement",
        "mops.monthly_revenue_announcement",
    }
)


@dataclass(frozen=True)
class MonthlyRevenueAvailabilityValidationResult:
    valid: bool
    accepted_count: int
    source_versions: tuple[str, ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_versions", tuple(self.source_versions))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Monthly Revenue Availability Validation",
                "",
                f"- valid: {str(self.valid).lower()}",
                f"- accepted_count: {self.accepted_count}",
                f"- source_versions: {', '.join(self.source_versions) or 'none'}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


def validate_monthly_revenue_availability_file(
    path: Path,
) -> MonthlyRevenueAvailabilityValidationResult:
    load_result = load_monthly_revenue_availability_overrides_csv(Path(path))
    diagnostics = list(load_result.diagnostics)
    for override in load_result.overrides.values():
        if override.source not in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES:
            diagnostics.append(_unsupported_source_diagnostic(override))

    accepted = tuple(
        override
        for override in load_result.overrides.values()
        if override.source in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
    )
    return MonthlyRevenueAvailabilityValidationResult(
        valid=bool(accepted) and not diagnostics,
        accepted_count=len(accepted),
        source_versions=tuple(sorted({item.source_version for item in accepted})),
        diagnostics=tuple(diagnostics),
    )


def _unsupported_source_diagnostic(
    override: FundamentalAvailabilityOverride,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code="fundamental_availability.unsupported_available_date_source",
        factor_name="fundamental.availability",
        stock_code=override.stock_code,
        message=(
            "monthly revenue availability source is not in allowed source list; "
            f"period={override.period}; source={override.source}"
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_availability_entrypoint.py tests\test_fundamental_availability_sources.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add data_module/fundamental_availability_entrypoint.py tests/test_fundamental_availability_entrypoint.py
git commit -m "month5: add monthly revenue availability validation entrypoint"
```

## Task 2: CLI Dry-Run Validator

**Files:**
- Create: `scripts/validate_monthly_revenue_availability.py`
- Test: `tests/test_monthly_revenue_availability_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_monthly_revenue_availability_cli.py`:

```python
from scripts.validate_monthly_revenue_availability import main


def test_monthly_revenue_availability_cli_exits_zero_for_valid_mapping(tmp_path, capsys):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16\n",
        encoding="utf-8-sig",
    )

    assert main(["--path", str(mapping_file)]) == 0
    assert "valid: true" in capsys.readouterr().out


def test_monthly_revenue_availability_cli_exits_nonzero_for_invalid_mapping(tmp_path, capsys):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text("stock_code,period\n2330,2026-05\n", encoding="utf-8")

    assert main(["--path", str(mapping_file)]) == 1
    assert "valid: false" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_monthly_revenue_availability_cli.py -q -o addopts=
```

Expected: collection fails with `ModuleNotFoundError` or import error for the new script.

- [ ] **Step 3: Implement CLI**

Create `scripts/validate_monthly_revenue_availability.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from data_module.config import TWStockConfig
from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate governed monthly revenue availability mapping."
    )
    parser.add_argument("--path", type=Path, default=None)
    args = parser.parse_args(argv)

    path = args.path or TWStockConfig().monthly_revenue_availability_file
    result = validate_monthly_revenue_availability_file(path)
    print(result.to_markdown())
    for diagnostic in result.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.message}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests and py_compile**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_monthly_revenue_availability_cli.py tests\test_fundamental_availability_entrypoint.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\fundamental_availability_entrypoint.py scripts\validate_monthly_revenue_availability.py
```

Expected: tests pass and `py_compile` exits 0.

- [ ] **Step 5: Commit**

```powershell
git add scripts/validate_monthly_revenue_availability.py tests/test_monthly_revenue_availability_cli.py
git commit -m "month5: add monthly revenue availability validation cli"
```

## Task 3: Documentation Sync

**Files:**
- Modify: `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update docs**

Record that the availability entrypoint exists, validates governed sources, rejects raw CSV availability sources, and remains dry-run / diagnostic-only.

- [ ] **Step 2: Review diff**

```powershell
git diff -- docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/DOCUMENTATION_INDEX.md
```

Expected: docs describe validation capability without claiming formal announcement data has been filled.

- [ ] **Step 3: Commit**

```powershell
git add docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/DOCUMENTATION_INDEX.md
git commit -m "docs: document monthly revenue availability entrypoint"
```

## Final Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_availability.py tests\test_fundamental_availability_sources.py tests\test_fundamental_availability_entrypoint.py tests\test_monthly_revenue_availability_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\fundamental_availability.py data_module\fundamental_availability_sources.py data_module\fundamental_availability_entrypoint.py scripts\validate_monthly_revenue_availability.py
git status --short --branch
```
