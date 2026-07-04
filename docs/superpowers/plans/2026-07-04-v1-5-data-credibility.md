# V1.5 Data Credibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete V1.5 Data Credibility & Corporate Action Gate without switching branches, while keeping all data writes non-production and read-only by default.

**Architecture:** Add read-only data source capability and corporate action policy services in `data_module`, wire microstructure preflight metadata into the existing recommendation replay diagnostics, and centralize evidence source coverage in `app_module`. Do not modify `ScoringEngine`, production scheduler, formal raw data, or portfolio state.

**Tech Stack:** Python dataclasses, argparse CLIs, pytest, existing `TWStockConfig`, existing Evidence / Recommendation services.

---

### Task 1: Data Source Capability Registry

**Files:**
- Create: `data_module/data_source_capability_registry.py`
- Create: `scripts/inspect_data_source_capabilities.py`
- Create: `tests/test_data_source_capability_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
def test_registry_contains_v1_5_p0_sources():
    registry = build_default_data_source_capability_registry()
    assert registry.require("corporate_action.ex_dividend_timeline").status == "planned"
    assert registry.require("microstructure.disposition_stock").available_date_policy
    assert registry.require("recommendation.exclusion.why_not_payload").status == "partial"
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_data_source_capability_registry.py -q -o addopts=`
Expected: FAIL because module does not exist.

- [ ] **Step 2: Implement registry DTO and default sources**

Create immutable dataclasses for `DataSourceField`, `DataSourceCapability`, `DataSourceCapabilityInspection`, and a small registry wrapper with `require`, `get`, `list_by_status`, `to_dict`.

- [ ] **Step 3: Add CLI inspection**

`scripts/inspect_data_source_capabilities.py` should output JSON by default and Markdown when `--markdown` is passed.

- [ ] **Step 4: Verify Task 1**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_data_source_capability_registry.py -q -o addopts=`
Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add data_module/data_source_capability_registry.py scripts/inspect_data_source_capabilities.py tests/test_data_source_capability_registry.py
git commit -m "feat: add data source capability registry"
```

### Task 2: Corporate Action Policy Inspection

**Files:**
- Create: `data_module/corporate_action_policy.py`
- Create: `scripts/inspect_corporate_action_policy.py`
- Create: `tests/test_corporate_action_policy.py`

- [ ] **Step 1: Write failing corporate action policy tests**

```python
def test_policy_forbids_hindsight_adjusted_prices_for_decisions():
    inspection = inspect_corporate_action_policy()
    forbidden = inspection.policy_by_id["full_hindsight_adjusted_price"]
    assert forbidden.allowed_for_decision_features is False
    assert "look_ahead" in forbidden.warnings
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corporate_action_policy.py -q -o addopts=`
Expected: FAIL because module does not exist.

- [ ] **Step 2: Implement policy DTO and inspection**

Define raw price, decision-date adjusted candidate, and full hindsight adjusted price policies. Include table candidate fields for corporate action events without creating a migration.

- [ ] **Step 3: Add CLI inspection**

CLI supports `--json-output` and `--markdown`.

- [ ] **Step 4: Verify Task 2**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_corporate_action_policy.py -q -o addopts=`
Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add data_module/corporate_action_policy.py scripts/inspect_corporate_action_policy.py tests/test_corporate_action_policy.py
git commit -m "feat: document corporate action price policy"
```

### Task 3: Microstructure Governed Preflight

**Files:**
- Create: `data_module/microstructure_source_preflight.py`
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
- Modify: `tests/test_recommendation_portfolio_backtest.py`

- [ ] **Step 1: Write failing metadata regression**

Add assertions to existing microstructure tests:

```python
assert preflight["governed_sources"]["disposition_stock"]["status"] in {"planned", "ready", "partial"}
assert preflight["source_capability_status"]["disposition_stock"] == "planned"
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py -q -o addopts=`
Expected: FAIL because metadata keys are absent.

- [ ] **Step 2: Implement helper and integrate service**

`build_microstructure_source_preflight(data_columns)` should map risk type to candidate columns, source capability status, available date policy, missing policy, and warnings. Existing risk detection remains unchanged.

- [ ] **Step 3: Verify Task 3**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_recommendation_portfolio_backtest.py -q -o addopts=`
Expected: PASS.

- [ ] **Step 4: Commit Task 3**

```powershell
git add data_module/microstructure_source_preflight.py app_module/recommendation_portfolio_backtest_service.py tests/test_recommendation_portfolio_backtest.py
git commit -m "feat: add governed microstructure preflight metadata"
```

### Task 4: Evidence Source Coverage Service

**Files:**
- Create: `app_module/evidence_source_coverage_service.py`
- Modify: `scripts/inspect_evidence_source_coverage.py`
- Modify: `app_module/evidence_scheduler_readiness.py`
- Modify: `app_module/evidence_pipeline_runner.py`
- Modify: `tests/test_evidence_source_coverage_cli.py`
- Create: `tests/test_evidence_source_coverage_service.py`

- [ ] **Step 1: Write failing service tests**

Test that missing recommendation payloads are warnings when recommendation and durable snapshot sources are otherwise present, while missing durable snapshot sections remain blocking gaps.

- [ ] **Step 2: Implement shared service**

Move current source coverage logic to `EvidenceSourceCoverageService.inspect(...)`. Include capability metadata and keep scheduler readiness limited to existing non-production values.

- [ ] **Step 3: Wire CLI, runner, readiness evaluator**

Replace duplicate coverage logic with the shared service. Keep CLI JSON keys backward compatible.

- [ ] **Step 4: Verify Task 4**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_source_coverage_service.py tests/test_evidence_source_coverage_cli.py tests/test_evidence_pipeline_runner.py tests/test_evidence_scheduler_readiness.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```powershell
git add app_module/evidence_source_coverage_service.py scripts/inspect_evidence_source_coverage.py app_module/evidence_scheduler_readiness.py app_module/evidence_pipeline_runner.py tests/test_evidence_source_coverage_service.py tests/test_evidence_source_coverage_cli.py
git commit -m "feat: centralize evidence source coverage"
```

### Task 5: Documentation, QA, Verification

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Create: `docs/06_qa/V1_5_DATA_CREDIBILITY_CLOSEOUT_2026_07_04.md`

- [ ] **Step 1: Update docs**

Mark V1.5 v1 complete only for registry / policy / governed metadata / coverage service. Keep external data ingestion, full negative evidence, production scheduler, and investment validity out of scope.

- [ ] **Step 2: Run verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_data_source_capability_registry.py tests/test_corporate_action_policy.py tests/test_recommendation_portfolio_backtest.py tests/test_evidence_source_coverage_service.py tests/test_evidence_source_coverage_cli.py tests/test_evidence_pipeline_runner.py tests/test_evidence_scheduler_readiness.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module/data_source_capability_registry.py data_module/corporate_action_policy.py data_module/microstructure_source_preflight.py app_module/evidence_source_coverage_service.py scripts/inspect_data_source_capabilities.py scripts/inspect_corporate_action_policy.py scripts/inspect_evidence_source_coverage.py
.\.venv\Scripts\python.exe scripts/quant_guard_linter.py
git diff --check
```

- [ ] **Step 3: Commit docs and QA**

```powershell
git add docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/ROADMAP_6M_ENGINEERING.md docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md docs/00_core/DEVELOPMENT_ROADMAP.md docs/01_architecture/system_architecture.md docs/07_guides/APPLICATION_MANUAL.md docs/00_core/DOCUMENTATION_INDEX.md docs/06_qa/V1_5_DATA_CREDIBILITY_CLOSEOUT_2026_07_04.md
git commit -m "docs: close out v1.5 data credibility"
```

- [ ] **Step 4: Final git safety and push**

Run:

```powershell
git status --short --branch
git log --oneline -n 8
git push origin dev
```

Only push after documentation commit and verification evidence are complete.
