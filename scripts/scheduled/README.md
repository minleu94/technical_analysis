# baldr Scheduled Evidence Dry-run Wrappers

These wrappers are intentionally conservative. They use CMD files and Windows built-in `schtasks.exe` because the previous PowerShell `.ps1` registration path was blocked by local execution policy. Do not use `Set-ExecutionPolicy`, do not bypass local policy, and do not create a production evidence confirm schedule.

## Tasks

| Task | State | Trigger | Behavior |
|---|---:|---|---|
| `baldr-data-freshness-check-daily` | enabled after register | daily local time 05:00 | Read-only SQLite / `DATA_ROOT` freshness check. Writes only status and logs under `OUTPUT_ROOT/scheduled/data_freshness/`. |
| `baldr-evidence-pipeline-dry-run-daily` | enabled after register | daily local time 05:15 | Runs `scripts/run_evidence_pipeline.py` with `--dry-run`. Writes only report, status, and logs under `OUTPUT_ROOT/scheduled/evidence_pipeline_dry_run/`. |
| `baldr-evidence-working-copy-smoke-manual` | manual-only | no daily schedule | Manual smoke against a working-copy DB. This repo keeps the script only; `register_baldr_scheduled_tasks.cmd` does not create a daily task for it. |

## Register

Preview:

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun
```

Create or replace the two daily tasks:

```cmd
scripts\scheduled\register_baldr_scheduled_tasks.cmd register
```

The register script creates:

```text
baldr-data-freshness-check-daily
  DAILY 05:00
  cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_freshness_check.cmd"

baldr-evidence-pipeline-dry-run-daily
  DAILY 05:15
  cmd.exe /c "<repo>\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"
```

It does not create or enable `baldr-evidence-working-copy-smoke-manual` as a daily task.

## Query

```cmd
scripts\scheduled\query_baldr_scheduled_tasks.cmd
schtasks /Query /TN baldr-data-freshness-check-daily /V /FO LIST
schtasks /Query /TN baldr-evidence-pipeline-dry-run-daily /V /FO LIST
```

Missing tasks are reported as friendly `Task not found` messages by the query wrapper.

## Unregister

Preview:

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd dryrun
```

Remove the scheduled tasks:

```cmd
scripts\scheduled\unregister_baldr_scheduled_tasks.cmd unregister
```

You can also open Windows Task Scheduler and disable or delete the two daily tasks manually.

## Logs And Reports

Data freshness:

```text
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log
```

Evidence dry-run:

```text
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/latest_status.json
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/YYYYMMDD_evidence_pipeline_dry_run.log
<OUTPUT_ROOT>/scheduled/evidence_pipeline_dry_run/reports/YYYYMMDD_evidence_pipeline_dry_run.md
```

Working-copy smoke manual script:

```cmd
scripts\scheduled\run_evidence_working_copy_smoke.cmd <source-db-path> <working-copy-db-path> [YYYY-MM-DD] [repeat]
```

If the DB paths are missing, the wrapper prints usage and exits. Repeat defaults to 2.

## Evidence Boundary

The daily automation runs only:

- read-only data freshness checks;
- evidence pipeline dry-run reports.

It does not run production evidence confirm, does not write the production evidence DB, does not update production data, does not run the UI, does not read UI state, does not change portfolio state, does not change `ScoringEngine`, does not change recommendation weights, does not promote / demote / retire strategies, and does not automate trading.

The generated evidence reports are for human review only. They do not prove alpha and must not be converted into trading advice.
