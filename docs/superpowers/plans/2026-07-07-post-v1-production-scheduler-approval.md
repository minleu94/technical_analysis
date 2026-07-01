# Production Scheduler Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 working-copy DB smoke、scheduler readiness evaluator 與 production scheduler approval checklist。

**Architecture:** 使用既有 `EvidencePipelineRunner` 執行 confirm smoke，但只寫 working-copy DB。新增 readiness evaluator 讀取 source coverage / smoke report / dashboard availability，並固定 `production_scheduler_allowed=false`。

**Tech Stack:** Python argparse、SQLite、`shutil.copy2`、dataclass-like JSON summaries、pytest。

---

### Task 1: Working-copy Smoke Script

**Files:**
- Create: `scripts/smoke_evidence_pipeline_working_copy.py`
- Test: `tests/test_evidence_pipeline_working_copy_smoke.py`

- [x] Copy source DB to working-copy DB when needed.
- [x] Reject identical source and working-copy paths.
- [x] Run repeat confirm through `EvidencePipelineRunner`.
- [x] Report event / outcome counts and idempotency check.
- [x] Keep source DB read-only.

### Task 2: Scheduler Readiness Evaluator

**Files:**
- Create: `app_module/evidence_scheduler_readiness.py`
- Create: `scripts/evaluate_evidence_scheduler_readiness.py`
- Test: `tests/test_evidence_scheduler_readiness.py`

- [x] Evaluate source coverage and smoke report status.
- [x] Return readiness no higher than `ready_for_manual_confirm`.
- [x] Keep `production_scheduler_allowed=false`.
- [x] Emit JSON from CLI.

### Task 3: Approval Checklist

**Files:**
- Create: `docs/06_qa/POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md`
- Create: `docs/superpowers/specs/2026-07-07-post-v1-production-scheduler-approval-design.md`
- Create: `docs/superpowers/plans/2026-07-07-post-v1-production-scheduler-approval.md`
- Test: `tests/test_production_scheduler_approval_checklist.py`

- [x] Document preconditions.
- [x] Document manual approval steps.
- [x] Document future schedule design without enabling it.
- [x] Document rollback / recovery notes.
- [x] Document explicit non-goals.

### Task 4: Core Docs and QA

**Files:**
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_vision_specification.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Mark working-copy smoke / approval checklist v1 complete.
- [x] Keep production scheduler marked as not enabled.
- [x] Record verification commands and results.
