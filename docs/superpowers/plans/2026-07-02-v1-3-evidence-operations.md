# V1.3 Evidence Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 V1.3 weekly evidence operations 與 manual lifecycle 審核節奏。

**Architecture:** 新增唯讀 application service 彙總 scheduler readiness、Decision Quality 與 Signal Decay。所有 lifecycle candidate 都停在人工審核包，不自動套用。

**Tech Stack:** Python dataclasses、SQLite-backed existing repositories、pytest、read-only CLI。

---

### Task 1: Weekly Evidence Operations Package

**Files:**
- Create: `app_module/evidence_operations_dtos.py`
- Create: `app_module/evidence_operations_service.py`
- Create: `scripts/build_evidence_operations_weekly_review.py`
- Test: `tests/test_evidence_operations_service.py`
- Test: `tests/test_evidence_operations_cli.py`

- [x] Write failing tests for weekly package, coverage-only status, and CLI JSON.
- [x] Implement DTOs and service.
- [x] Add CLI with JSON / Markdown output.
- [x] Verify focused tests pass.
- [ ] Commit checkpoint.

### Task 2: Action Item Loop

**Files:**
- Modify: `app_module/evidence_operations_service.py`
- Modify: `app_module/decision_quality_service.py`
- Test: `tests/test_evidence_operations_service.py`

- [ ] Add tests for planning action items from open Decision Quality items without duplicate descriptions.
- [ ] Implement append-only action item planning via `DecisionQualityService`.
- [ ] Verify no lifecycle action is applied and scheduler remains disabled.
- [ ] Commit checkpoint.

### Task 3: QA And Documentation Closeout

**Files:**
- Create/Modify: `docs/06_qa/*V1_3*`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] Add V1.3 QA checklist and validation evidence.
- [ ] Update Manual with weekly review CLI and safety interpretation.
- [ ] Update scoped authority docs after V1.3 completion only.
- [ ] Run focused tests, py_compile, and relevant evidence tests.
- [ ] Commit and push branch.

