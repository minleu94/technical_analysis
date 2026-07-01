# Post-V1 Evidence Production Scheduler Approval Checklist

日期：2026-07-07

## Scope

本文件是未來 production scheduler 的人工批准清單。它不是啟用紀錄，也不包含正式排程指令。本輪只允許 working-copy smoke、readiness evaluation 與人工審核文件。

## Preconditions

- latest data update completed
- evidence source coverage ready
- durable Daily Decision Desk snapshot ready
- recommendation persisted source ready
- watchlist / portfolio alert / risk prompt snapshot source ready
- why-not / liquidity payload limitation acknowledged
- working-copy smoke passed at least N times
- dashboard read-only inspection available
- diagnostics report reviewed
- backup path verified
- rollback path verified
- no production DB writes without explicit approval

## Manual Approval Steps

1. Run source coverage check.
2. Run evidence pipeline dry-run.
3. Review diagnostics report.
4. Run working-copy confirm smoke.
5. Review idempotency / duplicate check.
6. Review dashboard.
7. Approve or reject production confirm.

## Production Schedule Future Design

Future schedule design must remain disabled until explicitly approved by a human reviewer.

Future flow:

```text
latest data update completed
-> source coverage check
-> dry-run evidence pipeline
-> write dry-run diagnostics
-> require manual approval
-> confirm run
-> write confirm diagnostics
-> dashboard inspection
```

Production scheduler must never skip dry-run diagnostics or manual approval.

## Rollback / Recovery

- evidence DB backup must exist before any approved production confirm.
- identify last run_id from diagnostics report and evidence metadata.
- disable future schedule before recovery work begins.
- archive bad events instead of deleting when append-only policy applies.
- mark bad outcomes stale / superseded rather than rewriting historical evidence silently.
- keep QA report and diagnostics report with the recovery record.

## Explicit Non-goals

- no trading recommendation
- no auto lifecycle action
- no portfolio mutation
- no scoring mutation
- no alpha claim

## Verification Commands

Latest local verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_pipeline_working_copy_smoke.py tests/test_evidence_scheduler_readiness.py tests/test_production_scheduler_approval_checklist.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_pipeline_runner.py tests/test_run_evidence_pipeline_cli.py tests/test_evidence_pipeline_report.py tests/test_evidence_pipeline_scheduler_readiness.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
$files = @(Get-ChildItem app_module -Filter *.py | ForEach-Object { $_.FullName }) + @(Get-ChildItem scripts -Filter *.py | ForEach-Object { $_.FullName }); .\.venv\Scripts\python.exe -m py_compile @files
git diff --check
```

Latest results:

- working-copy smoke / readiness / checklist tests: 9 passed
- pipeline runner regression tests: 19 passed
- financial float boundary: exit 0
- py_compile: exit 0
- git diff check: exit 0 with line-ending warnings only

## Approval State

- production scheduler allowed: false
- current readiness ceiling: `ready_for_manual_confirm`
- approval owner: human reviewer required
- next evidence increment: Live vs Research Gap linkage
