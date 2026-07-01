# Live vs Research Gap Linkage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Live vs Research Gap event linkage v1，將 portfolio source trace、Research Run metadata 與 Evidence Event / Outcome 串成只讀 gap observation。

**Architecture:** 新增 DTO / repository / service / CLI。Repository 採 SQLite append-only / idempotent save；service 只讀 Portfolio positions、Evidence Event / Outcome 與 source trace，不修改 portfolio、research registry 或 lifecycle evidence。

**Tech Stack:** Python dataclass、SQLite、argparse、Decimal / integer bp、pytest。

---

### Task 1: Repository and DTO

**Files:**
- Create: `app_module/live_research_gap_dtos.py`
- Create: `app_module/live_research_gap_repository.py`
- Test: `tests/test_live_research_gap_repository.py`

- [x] Write failing repository tests for idempotent save and summary grouping.
- [x] Implement observation / attribution / diagnostic / summary DTOs.
- [x] Implement `live_research_gap_observations` table.
- [x] Implement deterministic JSON serialization and idempotent save.
- [x] Implement read-only summary groups.

### Task 2: Service and Source Matching

**Files:**
- Create: `app_module/live_research_gap_service.py`
- Test: `tests/test_live_research_gap_service.py`
- Test: `tests/test_live_research_gap_source_matching.py`

- [x] Write failing service tests for explicit source trace, diagnostics and dry-run/confirm.
- [x] Implement `build_gap_for_position`.
- [x] Implement `build_gaps_for_portfolio`.
- [x] Implement conservative matching: explicit trace only for confirmed link.
- [x] Keep symbol/date matching as low-confidence candidate only.
- [x] Implement attribution categories.

### Task 3: CLI

**Files:**
- Create: `scripts/capture_live_research_gap.py`
- Create: `scripts/inspect_live_research_gap.py`
- Test: `tests/test_live_research_gap_cli.py`

- [x] Write failing CLI tests for dry-run, confirm, explicit DB path and inspect.
- [x] Implement capture CLI with dry-run default.
- [x] Require explicit `--db-path` for confirm.
- [x] Implement inspect CLI as read-only summary.

### Task 4: Safety and Documents

**Files:**
- Create: `tests/test_live_research_gap_no_trading_language.py`
- Create: `docs/superpowers/specs/2026-07-08-post-v1-live-research-gap-linkage-design.md`
- Create: `docs/superpowers/plans/2026-07-08-post-v1-live-research-gap-linkage.md`
- Create: `docs/06_qa/POST_V1_LIVE_RESEARCH_GAP_LINKAGE_QA_2026_07_08.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_vision_specification.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [x] Add forbidden-language / forbidden-import tests.
- [x] Document source trace coverage and matching policy.
- [x] Document portfolio mode policy.
- [x] Keep production scheduler, lifecycle action and portfolio mutation marked not done.
