# Historical Evidence Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working-copy historical replay runner that replays evidence pipeline days without using future recommendation results or future outcome prices.

**Architecture:** Add an app-layer replay service that copies a source SQLite DB to a replay DB, discovers trading dates, selects recommendation results whose `created_at` is not after each decision date, captures daily evidence with replay metadata, and calculates outcomes only up to the current replay date. A small CLI wraps the service; docs describe the boundary as research evidence that does not replace real scheduler time gates.

**Tech Stack:** Python dataclasses, existing SQLite-backed evidence repositories, existing `EvidencePipelineRunner`, pytest, PowerShell-friendly CLI.

---

### Task 1: Core Replay Service

**Files:**
- Create: `app_module/historical_evidence_replay.py`
- Modify: `app_module/evidence_pipeline_runner_dtos.py`
- Modify: `app_module/evidence_event_importer_dtos.py`
- Modify: `app_module/evidence_pipeline_runner.py`
- Modify: `app_module/evidence_capture_service.py`
- Modify: `app_module/forward_performance_service.py`
- Test: `tests/test_historical_evidence_replay.py`

- [x] Write failing tests for replay DB safety, as-of recommendation selection, replay metadata, and outcome data-as-of gating.
- [x] Implement minimal DTO fields and metadata propagation.
- [x] Implement `ForwardPerformanceService.calculate(data_as_of_date=...)`.
- [x] Implement `HistoricalEvidenceReplayService`.
- [x] Run focused tests and commit.

### Task 2: CLI

**Files:**
- Create: `scripts/replay_historical_evidence_pipeline.py`
- Test: `tests/test_replay_historical_evidence_pipeline_cli.py`

- [x] Write failing CLI tests for dry-run JSON output and source/replay DB path safety.
- [x] Implement CLI parser and JSON/Markdown output.
- [x] Run focused CLI tests and commit.

### Task 3: Documentation

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Document Historical Evidence Replay as a research-only, working-copy flow.
- [x] Explicitly state it does not replace weekly / multi-day real-time gates or production scheduler approval.
- [x] Run relevant checks and commit.

### Task 4: Verification

**Files:**
- No new files.

- [x] Run focused pytest files.
- [x] Run `py_compile` on changed Python files.
- [x] Run quant guard if financial/evidence boundary touched.
- [ ] Inspect `git status --short` and final commit history.
