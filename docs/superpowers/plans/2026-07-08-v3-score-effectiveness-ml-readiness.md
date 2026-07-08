# V3 Score Effectiveness Audit and ML Readiness Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:systematic-debugging before changing direction after a failing test.

**Goal:** Build the first read-only V3 score effectiveness audit and ML readiness bridge so baldr can decide whether `TotalScore`, fixed thresholds, and score components deserve ML assistance later.

**Architecture:** Add read-only application services and CLIs on top of existing evidence / forward outcome sources. Treat ML as a shadow research contract, not a production decision layer.

**Tech Stack:** Python dataclasses, existing app-layer service style, argparse JSON / Markdown output, pytest, integer basis points / Decimal-compatible boundaries.

## Global Constraints

- 使用繁體中文撰寫文件與使用者可見輸出。
- No production DB write, no `--confirm`, no scheduler enablement.
- No ScoringEngine weight changes, no recommendation threshold promotion.
- No auto trading, broker order, portfolio mutation, or lifecycle action.
- No investment-effectiveness claim.
- No new bare `float` in strategy, backtest, recommendation, performance, risk, or benchmark core logic.
- Perform a no-look-ahead self-check before touching score / threshold / forward outcome logic.
- If implementation changes UI-visible workflow, update `docs/07_guides/APPLICATION_MANUAL.md`.

---

## File Structure

Preferred new files:

- `app_module/score_effectiveness_dtos.py`
- `app_module/score_effectiveness_read_model.py`
- `app_module/threshold_robustness_read_model.py`
- `app_module/component_ablation_readiness.py`
- `app_module/ml_readiness_contract.py`
- `scripts/inspect_score_effectiveness.py`
- `scripts/inspect_ml_readiness_contract.py`
- `tests/test_score_effectiveness_read_model.py`
- `tests/test_threshold_robustness_read_model.py`
- `tests/test_component_ablation_readiness.py`
- `tests/test_ml_readiness_contract.py`

Documentation files already created for this milestone:

- `docs/superpowers/specs/2026-07-08-v3-score-effectiveness-ml-readiness-design.md`
- `docs/superpowers/plans/2026-07-08-v3-score-effectiveness-ml-readiness.md`

## Task 1: Score Bucket Audit Read Model

**Goal:** produce a deterministic read-only report that groups saved evidence by raw `TotalScore` buckets.

**Files:**

- Create: `app_module/score_effectiveness_dtos.py`
- Create: `app_module/score_effectiveness_read_model.py`
- Create: `scripts/inspect_score_effectiveness.py`
- Test: `tests/test_score_effectiveness_read_model.py`

- [ ] Step 1: Write tests for bucket policy and no-claim disclosure.

Required assertions:

- score `0`, `39.99` -> `0-40`
- score `40`, `49.99` -> `40-50`
- score `50`, `59.99` -> `50-60`
- score `60`, `69.99` -> `60-70`
- score `70`, `79.99` -> `70-80`
- score `80`, `100` -> `80-100`
- empty buckets are present.
- payload includes `writes_allowed=false`, `production_scheduler_allowed=false`, and `investment_effectiveness_claim=false`.

- [ ] Step 2: Implement DTOs and read model.

Minimum DTO fields:

- `bucket`
- `sample_count`
- `ready_outcome_count`
- `pending_outcome_count`
- `missing_outcome_count`
- `forward_return_bp_by_horizon`
- `benchmark_excess_bp_by_horizon`
- `industry_excess_bp_by_horizon`
- `max_drawdown_bp_by_horizon`
- `win_rate_bp_by_horizon`
- `warnings`
- `limitations`

The first implementation may support `--sample` and read-only row input. If reading SQLite, require an explicit `--db-path` and open read-only.

- [ ] Step 3: Add CLI.

CLI options:

```text
--sample
--db-path PATH
--format json|markdown
--output PATH
--min-sample-size INT
```

Markdown must state that this is score effectiveness research evidence, not a recommendation.

- [ ] Step 4: Verify.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_score_effectiveness_read_model.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\score_effectiveness_dtos.py app_module\score_effectiveness_read_model.py scripts\inspect_score_effectiveness.py
```

## Task 2: Fixed Threshold Robustness Matrix

**Goal:** evaluate whether nearby fixed threshold settings behave consistently, rather than finding one lucky parameter.

**Files:**

- Create: `app_module/threshold_robustness_read_model.py`
- Extend: `scripts/inspect_score_effectiveness.py`
- Test: `tests/test_threshold_robustness_read_model.py`

- [x] Step 1: Write tests for matrix generation.

Initial matrix:

- buy score: `58`, `60`, `62`, `65`, `70`
- sell score: `38`, `40`, `42`, `45`, `50`
- confirmation days: `1`, `2`, `3`
- cooldown days: `2`, `3`, `5`

Required labels:

- `stable_positive`
- `fragile`
- `inconclusive`
- `harmful_or_noisy`

- [x] Step 2: Implement read-only evaluator.

The first implementation may classify sample rows and mark missing historical signal replay inputs as `inconclusive`. Do not promote thresholds or change defaults.

- [x] Step 3: Verify.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_threshold_robustness_read_model.py tests/test_score_effectiveness_read_model.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\threshold_robustness_read_model.py scripts\inspect_score_effectiveness.py
```

## Task 3: Component Ablation Readiness

**Goal:** separate what can be ablated now from what requires new component score persistence.

**Files:**

- Create: `app_module/component_ablation_readiness.py`
- Test: `tests/test_component_ablation_readiness.py`

- [x] Step 1: Write tests for component set contract.

Component sets:

- technical only
- pattern only
- volume only
- technical + pattern
- technical + volume
- pattern + volume
- technical + pattern + volume

Required diagnostic when old evidence lacks components:

- `component_payload_missing`
- `new_evidence_metadata_required`

- [x] Step 2: Implement readiness report.

Do not backfill old evidence. If adding capture support for future evidence, store only decision-time component scores and include source trace.

- [x] Step 3: Verify.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_component_ablation_readiness.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\component_ablation_readiness.py
```

## Task 4: ML Readiness Contract

**Goal:** define the exact gate for later ML without training a production model.

**Files:**

- Create: `app_module/ml_readiness_contract.py`
- Create: `scripts/inspect_ml_readiness_contract.py`
- Test: `tests/test_ml_readiness_contract.py`

- [x] Step 1: Write tests for allowed ML roles.

Allowed roles:

- `weight_learning`
- `probability_calibration`
- `meta_labeling`
- `ranking`

Forbidden until later approval:

- production model training
- replacing rule-generated signals
- changing recommendation thresholds
- auto lifecycle action
- trading advice

- [x] Step 2: Implement contract report.

Minimum payload:

- feature list policy
- label list policy
- walk-forward split policy
- model family sequence
- shadow-only boundary
- required preconditions from Tasks 1-3

- [x] Step 3: Verify.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_readiness_contract.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\ml_readiness_contract.py scripts\inspect_ml_readiness_contract.py
```

## Final Verification

Run focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_score_effectiveness_read_model.py tests/test_threshold_robustness_read_model.py tests/test_component_ablation_readiness.py tests/test_ml_readiness_contract.py -q -o addopts=
```

Run syntax checks:

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\score_effectiveness_dtos.py app_module\score_effectiveness_read_model.py app_module\threshold_robustness_read_model.py app_module\component_ablation_readiness.py app_module\ml_readiness_contract.py scripts\inspect_score_effectiveness.py scripts\inspect_ml_readiness_contract.py
```

Run repository hygiene:

```powershell
git diff --check
git status --short
```

## Completion Criteria

- Score bucket report exists and includes all raw buckets.
- Threshold robustness matrix exists and does not auto-promote settings.
- Component ablation readiness report distinguishes available evidence from missing component payloads.
- ML readiness report is shadow-only and lists score audit preconditions.
- Roadmap / blueprint keep ML after score effectiveness gates.
- Production scheduler, trading, lifecycle action, and investment-effectiveness claims remain disabled.
