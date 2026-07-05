# V1.6 Cross-sectional Factor Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete V1.6 Cross-sectional Factor Pipeline & Sector Rotation v2 on `dev`, preserving the no-scoring-change and no-production-scheduler boundaries.

**Architecture:** Add V1.6 DTOs, an idempotent SQLite repository, a cross-sectional pipeline service, and a read-only attribution summary CLI. The pipeline consumes existing `FactorRecord` / `FactorGate` behavior, attaches governed sector / concept metadata, saves rank / quantile as integers, and never writes to `ScoringEngine` or portfolio state.

**Tech Stack:** Python dataclasses, sqlite3, argparse CLIs, pytest, existing `FactorService`, existing `TWStockConfig`, Decimal / integer bp numeric boundaries.

---

### Task 0: Spec / Plan Commit

**Files:**
- Create: `docs/superpowers/specs/2026-07-05-v1-6-cross-sectional-factor-pipeline-design.md`
- Create: `docs/superpowers/plans/2026-07-05-v1-6-cross-sectional-factor-pipeline.md`

- [ ] **Step 1: Commit V1.6 design and implementation plan**

```powershell
git add docs/superpowers/specs/2026-07-05-v1-6-cross-sectional-factor-pipeline-design.md docs/superpowers/plans/2026-07-05-v1-6-cross-sectional-factor-pipeline.md
git commit -m "docs: plan v1.6 factor pipeline"
```

### Task 1: DTO and Repository

**Files:**
- Create: `app_module/cross_sectional_factor_dtos.py`
- Create: `data_module/cross_sectional_factor_migration.py`
- Create: `app_module/cross_sectional_factor_repository.py`
- Create: `tests/test_cross_sectional_factor_repository.py`

- [ ] **Step 1: Write failing repository tests**

```python
from datetime import date
from decimal import Decimal
import sqlite3

from app_module.cross_sectional_factor_dtos import (
    CrossSectionalFactorRow,
    CrossSectionalFactorSnapshot,
)
from app_module.cross_sectional_factor_repository import CrossSectionalFactorRepository
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy


def test_repository_saves_snapshot_idempotently(tmp_path):
    db_path = tmp_path / "factors.db"
    repository = CrossSectionalFactorRepository(db_path)
    snapshot = CrossSectionalFactorSnapshot(
        snapshot_id="csf_20260705",
        decision_date=date(2026, 7, 5),
        factor_set_version="v1.6-test",
        universe_id="test-universe",
        source_version="unit-test",
        rows=(
            CrossSectionalFactorRow(
                row_id="row-1",
                stock_code="2330",
                factor_name="technical.total_score",
                as_of_date=date(2026, 7, 4),
                available_date=date(2026, 7, 5),
                value=Decimal("80"),
                score_bp=8000,
                rank=1,
                quantile_bp=10000,
                universe_size=1,
                quality=FactorQuality.OBSERVED,
                missing_policy=MissingPolicy.FAIL_CLOSED,
                sector="半導體",
                concept_basket="ai",
            ),
        ),
    )

    first = repository.save_snapshot(snapshot)
    second = repository.save_snapshot(snapshot)

    assert first.snapshot_hash == second.snapshot_hash
    assert repository.get_latest_snapshot_id() == "csf_20260705"
    assert len(repository.list_rows("csf_20260705")) == 1
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_repository.py -q -o addopts=`
Expected: FAIL because modules do not exist.

- [ ] **Step 2: Implement DTOs**

Implement immutable dataclasses:

- `ConceptBasketDefinition`
- `CrossSectionalFactorDiagnostic`
- `CrossSectionalFactorRow`
- `CrossSectionalFactorSnapshot`

Each DTO must expose `to_dict()` with Decimal serialized as string, dates as ISO strings, enum values as strings, and bool metadata rejected through existing factor DTO JSON safety expectations.

- [ ] **Step 3: Implement migration helper**

`apply_cross_sectional_factor_schema(conn)` creates:

- `cross_sectional_factor_snapshots`
- `cross_sectional_factor_rows`
- indexes on `decision_date`, `factor_name`, `stock_code`, `sector`, `concept_basket`

- [ ] **Step 4: Implement repository**

`CrossSectionalFactorRepository` must:

- call schema creation on init
- save snapshot idempotently by `snapshot_hash`
- replace same `snapshot_id` only when the hash is identical; reject hash conflict
- read latest snapshot id by `decision_date DESC, snapshot_id DESC`
- list rows by snapshot id

- [ ] **Step 5: Verify Task 1**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_repository.py -q -o addopts=`
Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add app_module/cross_sectional_factor_dtos.py data_module/cross_sectional_factor_migration.py app_module/cross_sectional_factor_repository.py tests/test_cross_sectional_factor_repository.py
git commit -m "feat: add cross-sectional factor snapshot storage"
```

### Task 2: Pipeline Service

**Files:**
- Create: `app_module/cross_sectional_factor_pipeline.py`
- Create: `tests/test_cross_sectional_factor_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

```python
from datetime import date
from decimal import Decimal

from app_module.cross_sectional_factor_dtos import ConceptBasketDefinition
from app_module.cross_sectional_factor_pipeline import CrossSectionalFactorPipeline
from decision_module.factors.factor_adapters import build_technical_total_score_factor


def test_pipeline_ranks_factor_rows_with_stable_tie_rank():
    records = [
        build_technical_total_score_factor(
            stock_code="2330",
            as_of_date=date(2026, 7, 4),
            available_date=date(2026, 7, 5),
            total_score=Decimal("80"),
        ),
        build_technical_total_score_factor(
            stock_code="2317",
            as_of_date=date(2026, 7, 4),
            available_date=date(2026, 7, 5),
            total_score=Decimal("80"),
        ),
    ]

    snapshot = CrossSectionalFactorPipeline().build_snapshot(
        records,
        decision_date=date(2026, 7, 5),
        universe_id="test-universe",
    )

    assert [row.rank for row in snapshot.rows] == [1, 1]
    assert [row.stock_code for row in snapshot.rows] == ["2317", "2330"]
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_pipeline.py -q -o addopts=`
Expected: FAIL because service does not exist.

- [ ] **Step 2: Implement pipeline**

`CrossSectionalFactorPipeline.build_snapshot()` should:

- call `FactorService.build_snapshot()`
- generate rows from accepted + neutralized records
- keep skipped / diagnostics as snapshot diagnostics
- rank within each factor by `score_bp DESC`, `stock_code ASC`
- assign same rank for same score
- compute `quantile_bp = 10000` for rank 1 and `0` for the last unique rank when universe size is greater than 1; single-row universe gets `10000`
- attach sector by provided `sector_by_stock`
- attach concept basket only when the definition is available by decision date and the stock is a member

- [ ] **Step 3: Verify no-look-ahead concept gate**

Add a test where `ConceptBasketDefinition.available_date` is after `decision_date`; expected row `concept_basket is None` and diagnostics include `concept_basket_unavailable`.

- [ ] **Step 4: Verify Task 2**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_pipeline.py tests/test_factor_service_research_run.py -q -o addopts=`
Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add app_module/cross_sectional_factor_pipeline.py tests/test_cross_sectional_factor_pipeline.py
git commit -m "feat: build cross-sectional factor snapshots"
```

### Task 3: Attribution Summary CLI

**Files:**
- Create: `app_module/cross_sectional_factor_attribution.py`
- Create: `scripts/inspect_cross_sectional_factor_snapshot.py`
- Create: `tests/test_cross_sectional_factor_attribution.py`
- Create: `tests/test_inspect_cross_sectional_factor_snapshot_cli.py`

- [ ] **Step 1: Write failing summary tests**

```python
def test_attribution_summary_counts_quality_and_rank_buckets(repository_with_snapshot):
    summary = build_cross_sectional_factor_attribution_summary(
        repository_with_snapshot,
        snapshot_id="csf_20260705",
    )

    assert summary["row_count"] == 2
    assert summary["quality_counts"]["observed"] == 2
    assert summary["rank_bucket_counts"]["8001-10000"] >= 1
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_attribution.py tests/test_inspect_cross_sectional_factor_snapshot_cli.py -q -o addopts=`
Expected: FAIL because summary and CLI do not exist.

- [ ] **Step 2: Implement attribution summary**

Summary should include:

- snapshot metadata
- row count
- factor counts
- quality counts
- rank bucket counts
- sector counts
- concept basket counts
- diagnostics counts

- [ ] **Step 3: Implement CLI**

`scripts/inspect_cross_sectional_factor_snapshot.py` supports:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_cross_sectional_factor_snapshot.py --db-path path\to\db --latest --json
.\.venv\Scripts\python.exe scripts\inspect_cross_sectional_factor_snapshot.py --db-path path\to\db --snapshot-id csf_20260705 --markdown
```

CLI must be read-only and must not create a DB when the path is missing.

- [ ] **Step 4: Verify Task 3**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_attribution.py tests/test_inspect_cross_sectional_factor_snapshot_cli.py -q -o addopts=`
Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add app_module/cross_sectional_factor_attribution.py scripts/inspect_cross_sectional_factor_snapshot.py tests/test_cross_sectional_factor_attribution.py tests/test_inspect_cross_sectional_factor_snapshot_cli.py
git commit -m "feat: add factor snapshot attribution summary"
```

### Task 4: Documentation and QA Closeout

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Create: `docs/06_qa/V1_6_CROSS_SECTIONAL_FACTOR_PIPELINE_CLOSEOUT_2026_07_05.md`

- [ ] **Step 1: Coverage Pass**

Mark V1.6 complete only for:

- DTO / repository / migration
- pipeline service
- concept basket governance v1
- attribution CLI / summary

Keep external ingestion, negative evidence, scoring integration, production scheduler, and investment validity out of scope.

- [ ] **Step 2: Update docs**

Update Snapshot / Roadmap / Version Roadmap / Architecture / Manual / Index and add QA closeout.

- [ ] **Step 3: Run verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cross_sectional_factor_repository.py tests/test_cross_sectional_factor_pipeline.py tests/test_cross_sectional_factor_attribution.py tests/test_inspect_cross_sectional_factor_snapshot_cli.py tests/test_factor_service_research_run.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\cross_sectional_factor_dtos.py app_module\cross_sectional_factor_repository.py app_module\cross_sectional_factor_pipeline.py app_module\cross_sectional_factor_attribution.py data_module\cross_sectional_factor_migration.py scripts\inspect_cross_sectional_factor_snapshot.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
git diff --check
```

- [ ] **Step 4: Commit docs and QA**

```powershell
git add docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md docs/00_core/DEVELOPMENT_ROADMAP.md docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md docs/00_core/DOCUMENTATION_INDEX.md docs/06_qa/V1_6_CROSS_SECTIONAL_FACTOR_PIPELINE_CLOSEOUT_2026_07_05.md
git commit -m "docs: close out v1.6 factor pipeline"
```

### Task 5: Final Git Safety

- [ ] **Step 1: Check segmented commits**

```powershell
git status --short --branch
git log --oneline -n 8
```

- [ ] **Step 2: Stop before push unless explicitly requested**

User requested segmented commits, not push. Do not push unless user asks.
