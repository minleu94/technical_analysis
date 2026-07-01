# Evidence Pipeline Scheduler Dry-run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立手動 evidence pipeline runner，支援 dry-run、working-copy confirm、readiness summary 與 diagnostics report。

**Architecture:** 新增 application service `EvidencePipelineRunner` 串接既有 source coverage、snapshot repository、capture service、forward outcome service 與 read model。CLI 只做參數解析與 JSON/report 輸出，所有寫入都由 `--confirm + --db-path` gate 控制。

**Tech Stack:** Python dataclasses、SQLite repositories、pytest、既有 Evidence / Forward Performance service。

---

### Task 1: Runner DTOs

**Files:**
- Create: `app_module/evidence_pipeline_runner_dtos.py`
- Test: `tests/test_evidence_pipeline_scheduler_readiness.py`

- [x] Define `EvidencePipelineRunRequest`, `EvidencePipelineRunSummary`, `EvidencePipelineStepSummary`, `EvidencePipelineDiagnostic`.
- [x] Define readiness values `not_ready`, `dry_run_only`, `ready_for_design`, `ready_for_manual_confirm`.
- [x] Add `scheduler_readiness_after_run()` and tests proving it never returns `production_ready`.

### Task 2: Runner Service

**Files:**
- Create: `app_module/evidence_pipeline_runner.py`
- Test: `tests/test_evidence_pipeline_runner.py`

- [x] Implement `source_coverage_check`.
- [x] Implement `capture_decision_desk_snapshot` with dry-run default and confirm save.
- [x] Implement event capture through `EvidenceCaptureService`.
- [x] Implement forward outcome calculation with dry-run forwarding.
- [x] Implement read model summary step.
- [x] Add confirm gate and production-like DB guard.

### Task 3: CLI

**Files:**
- Create: `scripts/run_evidence_pipeline.py`
- Test: `tests/test_run_evidence_pipeline_cli.py`

- [x] Add CLI flags required by Round 6.
- [x] Default to dry-run.
- [x] Reject `--dry-run` with `--confirm`.
- [x] Reject confirm without explicit `--db-path`.
- [x] Emit deterministic JSON summary.

### Task 4: Diagnostics Report

**Files:**
- Modify: `app_module/evidence_pipeline_runner.py`
- Test: `tests/test_evidence_pipeline_report.py`

- [x] Add Markdown / JSON report writer.
- [x] Include run metadata, source coverage, steps, event/outcome/summary counts, warnings, blocking gaps, evidence boundary, readiness, next action.
- [x] Verify report has no forbidden trading language.

### Task 5: Docs and QA

**Files:**
- Create: `docs/superpowers/specs/2026-07-06-post-v1-evidence-scheduler-dry-run-design.md`
- Create: `docs/superpowers/plans/2026-07-06-post-v1-evidence-scheduler-dry-run.md`
- Create: `docs/06_qa/POST_V1_EVIDENCE_SCHEDULER_DRY_RUN_QA_2026_07_06.md`
- Modify: core docs and manual

- [x] Document dry-run runner scope.
- [x] Document production scheduler minimum bar.
- [x] Mark scheduler readiness at most `ready_for_manual_confirm`.
- [x] Keep production scheduler and alpha claims out of scope.
