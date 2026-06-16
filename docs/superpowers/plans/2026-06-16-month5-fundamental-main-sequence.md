# Month 5 Fundamental Main Sequence Plan

> **For agentic workers:** This is a sequencing memo, not an execution plan. Pick exactly one linked plan and implement it with `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Steps in the linked plans use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the execution order for the next five Month 5 Fundamental Layer plans.

**Architecture:** Month 5 must continue through governed data contracts, explicit `available_date`, factor adapters, diagnostics, and documentation sync. No step may connect fundamental data directly to `ScoringEngine`, mutate formal data without a backup / rollback path, or infer availability from raw CSV dates.

**Tech Stack:** Python, pytest, SQLite working copies, existing `data_module/fundamental_*`, `decision_module/factors/*`, `app_module/factor_service.py`, docs under `docs/`.

---

## Execution Order

Run these plans in order. Do not start a later plan until the prior plan is committed and its focused verification passes.

1. `docs/superpowers/plans/2026-06-16-month5-availability-data-entrypoint.md`
   - Establishes the formal validation entrypoint for `monthly_revenue_availability.csv`.
   - Required before migration because normalized monthly revenue rows need governed `available_date`.

2. `docs/superpowers/plans/2026-06-16-month5-fundamental-sqlite-migration-v1.md`
   - Turns the existing schema dry-run into an explicit, backed-up SQLite migration workflow.
   - Required before data layer features can persist normalized fundamental records.

3. `docs/superpowers/plans/2026-06-16-month5-revenue-factor-pack-v1.md`
   - Adds Revenue YoY / MoM / 3M trend / new high factor adapters.
   - Requires validated availability and stable storage contract.

4. `docs/superpowers/plans/2026-06-16-month5-valuation-data-layer-v1.md`
   - Adds governed valuation metric observations and industry percentile input for the existing presentation policy.
   - Runs after migration so valuation metrics have a formal table contract.

5. `docs/superpowers/plans/2026-06-16-month5-abnormal-fundamental-diagnostics.md`
   - Adds abnormal fundamental flags and diagnostics integration into Research Run / Daily Decision Desk surfaces.
   - Runs last because it consumes revenue, valuation, and quality diagnostics from prior steps.

## Shared Non-Goals

- Do not connect fundamental factors to `decision_module/scoring_engine.py`.
- Do not infer `available_date` from raw monthly revenue CSV `date`.
- Do not output target price, fair value, upside percent, buy/sell signals, or recommendation.
- Do not rewrite financial statements or automatically deduct one-off gains.
- Do not modify formal `D:/Min/Python/Project/FA_Data` data without explicit backup / rollback steps in the active plan.

## Shared Verification

Every implementation plan must finish with:

```powershell
.\.venv\Scripts\python.exe -m pytest <focused-tests> -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile <changed-python-files>
git status --short --branch
```

Plans touching factors must also run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_gate.py tests\test_factor_contract.py -q -o addopts=
```

Plans touching SQLite schema or formal DB workflow must validate a working copy before any apply command and must not stage local `.db` / `.sqlite*` files.

## Documentation Sync Rule

After each plan completes, update at least these files when status changes:

- `docs/03_data/FUNDAMENTAL_SOURCE_INVENTORY.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_architecture.md`
- `docs/00_core/DOCUMENTATION_INDEX.md` when a new Markdown file is added
