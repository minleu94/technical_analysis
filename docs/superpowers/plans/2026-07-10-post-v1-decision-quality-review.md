# Decision Quality Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Decision Quality Review v1，以 append-only review / item / action item 記錄週期性流程覆盤，檢查來源追溯、journal、manual override、portfolio alert、live gap 與 signal decay review coverage。

**Architecture:** 新增 DTO / repository / service / CLI。Service 只讀 portfolio / journal / evidence / live gap / signal decay；Repository 只寫 Decision Quality 自己的 review tables；CLI 預設 dry-run。

**Tech Stack:** Python dataclass、SQLite、argparse、integer bp、pytest。

---

### Task 1: Repository and DTO

**Files:**
- Create: `app_module/decision_quality_dtos.py`
- Create: `app_module/decision_quality_repository.py`
- Test: `tests/test_decision_quality_repository.py`

- [x] Write failing tests for idempotent review save, item listing, status history and action item append.
- [x] Implement review / item / metric / diagnostic / summary / action DTOs.
- [x] Implement SQLite tables.
- [x] Implement deterministic JSON serialization and idempotent save.
- [x] Implement status history for reviewed / dismissed.

### Task 2: Review Service

**Files:**
- Create: `app_module/decision_quality_service.py`
- Test: `tests/test_decision_quality_service.py`
- Test: `tests/test_decision_quality_review_items.py`

- [x] Write failing tests for source trace gap, manual override, portfolio alert, live gap, signal decay and missed evidence items.
- [x] Implement read-only source loading.
- [x] Implement conservative item detection.
- [x] Implement integer bp score formula.
- [x] Treat no journal / insufficient sample as warning, not blame.
- [x] Keep dry-run build free of DB writes.

### Task 3: CLI

**Files:**
- Create: `scripts/capture_decision_quality_review.py`
- Create: `scripts/inspect_decision_quality.py`
- Test: `tests/test_decision_quality_cli.py`

- [x] Write failing CLI tests for dry-run, confirm, explicit DB path and inspect.
- [x] Implement capture CLI with dry-run default.
- [x] Require explicit `--db-path` for confirm.
- [x] Keep production-like DB confirm guarded.
- [x] Implement read-only inspect CLI.

### Task 4: Safety Tests

**Files:**
- Test: `tests/test_decision_quality_no_trading_language.py`

- [x] Add forbidden-language scan for new Decision Quality production files.
- [x] Add forbidden-boundary scan for UI, scoring, portfolio mutation and lifecycle mutation calls.

### Task 5: Documents and QA

**Files:**
- Create: `docs/superpowers/specs/2026-07-10-post-v1-decision-quality-review-design.md`
- Create: `docs/superpowers/plans/2026-07-10-post-v1-decision-quality-review.md`
- Create: `docs/06_qa/POST_V1_DECISION_QUALITY_REVIEW_QA_2026_07_10.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_vision_specification.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Document scope, files changed and CLI examples.
- [x] Document score policy and item types.
- [x] Document safety boundary and not-done items.
- [x] Record final verification command results.
