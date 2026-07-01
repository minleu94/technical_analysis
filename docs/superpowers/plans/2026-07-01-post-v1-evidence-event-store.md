# Post-V1 Evidence Event Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Evidence Event Store v1 與 Forward Outcome Calculator v1，讓 Post-V1 baldr 可保存事件並計算 5 / 10 / 20 / 60 交易日 forward research evidence。

**Architecture:** 新增 `app_module` DTO / repository / service 作為唯一寫入邊界，新增 `data_module` migration helper 提供 dry-run / working-copy / backup safety，新增 scripts 作最小 inspection 與 batch calculation。第一增量不接 UI、不改 scoring、不做 importer dashboard。

**Tech Stack:** Python dataclasses、SQLite、Decimal / integer basis points、pytest、PowerShell CLI execution。

---

## Files

- Create: `app_module/evidence_event_dtos.py`
- Create: `app_module/evidence_event_repository.py`
- Create: `app_module/evidence_event_service.py`
- Create: `app_module/forward_performance_service.py`
- Create: `data_module/evidence_event_migration.py`
- Create: `scripts/inspect_evidence_events.py`
- Create: `scripts/calculate_forward_outcomes.py`
- Create: `tests/test_evidence_event_repository.py`
- Create: `tests/test_evidence_event_service.py`
- Create: `tests/test_forward_performance_service.py`
- Create: `tests/test_evidence_event_cli.py`
- Create: `docs/06_qa/POST_V1_EVIDENCE_EVENT_STORE_QA_2026_07_01.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/01_architecture/system_vision_specification.md`

## Task 1: Schema And Repository

- [ ] Write failing tests for dry-run report, idempotent event insert, different reason hash, outcome upsert and list filters in `tests/test_evidence_event_repository.py`.
- [ ] Run focused repository tests and confirm failure because modules do not exist.
- [ ] Implement DTO enums/dataclasses and repository schema with `event_hash` unique key and outcome upsert.
- [ ] Run repository tests until green.

## Task 2: Event Service

- [ ] Write failing tests for required field validation, deterministic JSON, stable event hash and fail-closed quality policy in `tests/test_evidence_event_service.py`.
- [ ] Run service tests and confirm failure.
- [ ] Implement `EvidenceEventService.record_event()`, `record_events()`, `validate_event()`, `build_event_hash()` and JSON normalization helpers.
- [ ] Run service tests until green.

## Task 3: Forward Outcome Calculator

- [ ] Write failing tests for trading-day windows, insufficient future data, missing benchmark warning, missing industry warning and close-to-close metadata in `tests/test_forward_performance_service.py`.
- [ ] Run forward tests and confirm failure.
- [ ] Implement read-only price lookup from `daily_prices`, benchmark lookup from `market_indices`, industry lookup from `industry_indices`, integer bp return calculation and dry-run support.
- [ ] Run forward tests until green.

## Task 4: CLI

- [ ] Write failing tests that call `scripts/inspect_evidence_events.py` and `scripts/calculate_forward_outcomes.py` with isolated tmp SQLite DB.
- [ ] Confirm CLI tests fail before scripts exist.
- [ ] Implement CLI filters, `--dry-run`, `--decision-date`, `--start-date`, `--end-date`, `--event-type`, `--symbol`, `--windows`, `--limit` and diagnostics summary.
- [ ] Run CLI tests until green.

## Task 5: Documentation And QA

- [ ] Update QA doc with scope, files changed, schema safety, commands, results, limitations, not done, next increment and rollback note.
- [ ] Update documentation index as navigation only.
- [ ] Update Snapshot / 6M Roadmap / system vision to mark Evidence Event Store v1 and Forward Outcome Calculator v1 complete, while preserving investment-effectiveness-not-proven boundary.
- [ ] Run requested verification commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_event_repository.py tests\test_evidence_event_service.py tests\test_forward_performance_service.py tests\test_evidence_event_cli.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
.\.venv\Scripts\python.exe -m py_compile app_module\*.py data_module\*.py scripts\*.py
```

## Explicit Safety Checks

- Do not modify `decision_module/scoring_engine.py`.
- Do not modify recommendation weights.
- Do not modify UI files.
- Do not write formal DB during tests; use `tmp_path`.
- Do not create demo fake events outside tests.
- Do not output buy / sell / target price / fair price / high confidence trading language.

