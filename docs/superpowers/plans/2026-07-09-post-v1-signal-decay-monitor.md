# Signal Decay Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Signal Decay Monitor v1，以 append-only observation 保存近期 evidence 相對長窗的衰退診斷，並產生 lifecycle proposed payload，但不套用任何 lifecycle action。

**Architecture:** 新增 DTO / repository / service / CLI。Service 只讀 Evidence Event / Outcome 與 Live vs Research Gap observation；Repository 寫入 `signal_decay_observations`；Lifecycle adapter 只輸出 proposed payload。

**Tech Stack:** Python dataclass、SQLite、argparse、integer bp、pytest。

---

### Task 1: Repository and DTO

**Files:**
- Create: `app_module/signal_decay_dtos.py`
- Create: `app_module/signal_decay_repository.py`
- Test: `tests/test_signal_decay_repository.py`

- [x] Write failing repository tests for idempotent save and summary counts.
- [x] Implement observation / metric / diagnostic / suggestion / summary DTOs.
- [x] Implement `signal_decay_observations` table.
- [x] Implement deterministic JSON serialization and idempotent save.
- [x] Implement read-only summary.

### Task 2: Service and Rule Policy

**Files:**
- Create: `app_module/signal_decay_service.py`
- Test: `tests/test_signal_decay_service.py`

- [x] Write failing service tests for insufficient sample, decay, severe decay, missing evidence and stable state.
- [x] Implement scope filtering for event type, event family, strategy version and profile.
- [x] Implement event-count short/long window evaluation.
- [x] Implement rule-based decay score with integer bp metrics.
- [x] Block demote / retire suggestions when sample is insufficient.
- [x] Lower confidence when benchmark or live gap evidence is missing.

### Task 3: CLI

**Files:**
- Create: `scripts/capture_signal_decay.py`
- Create: `scripts/inspect_signal_decay.py`
- Test: `tests/test_signal_decay_cli.py`

- [x] Write failing CLI tests for dry-run, confirm, explicit DB path and inspect.
- [x] Implement capture CLI with dry-run default.
- [x] Require explicit `--db-path` for confirm.
- [x] Keep production-like DB confirm guarded.
- [x] Implement read-only inspect CLI.

### Task 4: Lifecycle Payload and Safety

**Files:**
- Test: `tests/test_signal_decay_lifecycle_payload.py`
- Test: `tests/test_signal_decay_no_trading_language.py`

- [x] Implement `SignalDecayLifecycleEvidenceAdapter`.
- [x] Ensure payload has `apply_action=false`.
- [x] Do not write lifecycle repository by default.
- [x] Add forbidden-language and forbidden-boundary checks.

### Task 5: Documents and QA

**Files:**
- Create: `docs/superpowers/specs/2026-07-09-post-v1-signal-decay-monitor-design.md`
- Create: `docs/superpowers/plans/2026-07-09-post-v1-signal-decay-monitor.md`
- Create: `docs/06_qa/POST_V1_SIGNAL_DECAY_MONITOR_QA_2026_07_09.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_vision_specification.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Document scope, files changed and CLI examples.
- [x] Document lifecycle payload-only policy.
- [x] Document scheduler and UI not done.
- [x] Keep evidence boundary explicit.

