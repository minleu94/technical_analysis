# baldr Scheduled Evidence Dry-run Wrappers

These scripts are intentionally conservative. They do not run the UI, do not mutate portfolio state, do not change scoring, and do not create an automated write-mode evidence task.

## Tasks

| Task | Default state | Trigger | Behavior |
|---|---:|---|---|
| `baldr-data-freshness-check-daily` | enabled | daily 07:30 | Read-only SQLite / `DATA_ROOT` freshness check. Writes only status and logs under `OUTPUT_ROOT/scheduled/data_freshness/`. |
| `baldr-evidence-pipeline-dry-run-daily` | enabled | daily 07:45 | Runs `scripts/run_evidence_pipeline.py` with `--dry-run`. Reads freshness status first and marks the report degraded if freshness is not passed. |
| `baldr-evidence-working-copy-smoke-manual` | disabled | disabled manual task | Manual-only smoke against a working-copy DB. It requires explicit source and working-copy DB paths. |

## Register

```powershell
.\scripts\scheduled\register_baldr_scheduled_tasks.ps1 -Mode DryRun
.\scripts\scheduled\register_baldr_scheduled_tasks.ps1 -Mode Register
```

If Windows blocks registration through permissions or execution policy, do not bypass local security policy. Record the error in the QA note and use Task Scheduler UI to create the two enabled daily tasks manually.

Manual Task Scheduler fields:

| Task | Trigger | Program | Arguments |
|---|---|---|---|
| `baldr-data-freshness-check-daily` | Daily 07:30 | `powershell.exe` | `-NoProfile -File "<repo>\scripts\scheduled\run_daily_data_freshness_check.ps1"` |
| `baldr-evidence-pipeline-dry-run-daily` | Daily 07:45 | `powershell.exe` | `-NoProfile -File "<repo>\scripts\scheduled\run_evidence_pipeline_dry_run.ps1"` |
| `baldr-evidence-working-copy-smoke-manual` | Disabled/manual | `powershell.exe` | `-NoProfile -File "<repo>\scripts\scheduled\run_evidence_working_copy_smoke.ps1" -SourceDbPath "<source-db>" -WorkingCopyDbPath "<working-copy-db>"` |

Set "Start in" to the repository root. Keep the working-copy smoke task disabled unless you are deliberately running a working-copy smoke.

## Unregister

```powershell
.\scripts\scheduled\unregister_baldr_scheduled_tasks.ps1 -Mode DryRun
.\scripts\scheduled\unregister_baldr_scheduled_tasks.ps1 -Mode Unregister
```

## Evidence Boundary

The automated daily evidence task is dry-run only. It creates logs and reports for human review. It cannot prove that any event type is useful, and it cannot approve lifecycle changes.
