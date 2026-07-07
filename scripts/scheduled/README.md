# baldr Scheduled Evidence Dry-run Wrappers

These wrappers are intentionally conservative. They use CMD files and Windows built-in `schtasks.exe` because the previous PowerShell `.ps1` registration path was blocked by local execution policy. Do not use `Set-ExecutionPolicy`, do not bypass local policy, and do not create a production evidence confirm schedule.

## Tasks

| Task | State | Trigger | Behavior |
|---|---:|---|---|
| `baldr-data-update-quick-daily` | enabled after register | daily local time 04:20 | Runs the non-UI quick data update path for the recent weekday window. Writes market data CSV / SQLite updates plus status and logs under `OUTPUT_ROOT/scheduled/data_update_quick/`. If TPEX has failed dates, the task continues later steps and writes `passed_with_warnings`. |
| `baldr-data-freshness-check-daily` | enabled after register | daily local time 05:00 | Read-only SQLite / `DATA_ROOT` freshness check. Also verifies raw TWSE / TPEX daily price files for the latest SQLite daily date. Writes only status and logs under `OUTPUT_ROOT/scheduled/data_freshness/`. |
| `baldr-recommendation-snapshot-daily` | enabled after register | daily local time 05:10 | Runs the research-only recommendation snapshot path after freshness. Saves one recommendation result under `OUTPUT_ROOT/recommendation/runs/` and writes status/logs under `OUTPUT_ROOT/scheduled/recommendation_snapshot/`. It does not write the production evidence DB, does not confirm evidence, does not change portfolio state, and does not automate trading. |
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
baldr-data-update-quick-daily
  DAILY 04:20
  cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_update_quick.cmd"

baldr-data-freshness-check-daily
  DAILY 05:00
  cmd.exe /c "<repo>\scripts\scheduled\run_daily_data_freshness_check.cmd"

baldr-recommendation-snapshot-daily
  DAILY 05:10
  cmd.exe /c "<repo>\scripts\scheduled\run_recommendation_snapshot.cmd"

baldr-evidence-pipeline-dry-run-daily
  DAILY 05:15
  cmd.exe /c "<repo>\scripts\scheduled\run_evidence_pipeline_dry_run.cmd"
```

It does not create or enable `baldr-evidence-working-copy-smoke-manual` as a daily task.

## Query

```cmd
scripts\scheduled\query_baldr_scheduled_tasks.cmd
schtasks /Query /TN baldr-data-freshness-check-daily /V /FO LIST
schtasks /Query /TN baldr-recommendation-snapshot-daily /V /FO LIST
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
<OUTPUT_ROOT>/scheduled/data_update_quick/latest_status.json
<OUTPUT_ROOT>/scheduled/data_update_quick/YYYYMMDD_data_update_quick.log
<OUTPUT_ROOT>/scheduled/data_freshness/latest_status.json
<OUTPUT_ROOT>/scheduled/data_freshness/YYYYMMDD_data_freshness.log
```

`data_update_quick/latest_status.json` uses `passed_with_warnings` when TPEX failed dates remain, for example `TPEX 每日股價缺少日期：20260706`. `data_freshness/latest_status.json` uses `degraded` when SQLite is current but either `daily_price/YYYYMMDD.csv` or `daily_price_tpex/YYYYMMDD.csv` is missing for that latest daily date.

Recommendation snapshot:

```text
<OUTPUT_ROOT>/scheduled/recommendation_snapshot/latest_status.json
<OUTPUT_ROOT>/scheduled/recommendation_snapshot/YYYYMMDD_recommendation_snapshot.log
<OUTPUT_ROOT>/recommendation/runs/scheduled_rec_YYYYMMDD_HHMMSS.json
<OUTPUT_ROOT>/recommendation/runs/recommendation_runs.db
```

The recommendation snapshot status includes `result_id`, `recommendations_count`, `screening_matrix_rows`, `why_not_payload_rows`, `liquidity_gate_payload_rows`, `writes_recommendation_result`, `writes_evidence_db`, `auto_trading`, and `lifecycle_action`.

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

- non-UI quick market data updates for the recent weekday window;
- read-only data freshness checks;
- research-only recommendation snapshot generation and recommendation result save;
- evidence pipeline dry-run reports.

It does not run production evidence confirm, does not write the production evidence DB, does not run the UI, does not read UI state, does not change portfolio state, does not change `ScoringEngine`, does not change recommendation weights, does not promote / demote / retire strategies, and does not automate trading.

The recommendation snapshot is intentionally saved before the evidence dry-run so the dry-run can observe the latest recommendation payloads, including screening matrix / why-not / liquidity gate payloads when available.

The generated evidence reports are for human review only. They do not prove alpha and must not be converted into trading advice.

During dry-run, the runner may build a transient Daily Decision Desk snapshot for the same run. Reports mark this as `source_coverage_basis=dry_run_transient_decision_desk_snapshot`; this reconciles diagnostics only and does not persist the snapshot.

The evidence dry-run `latest_status.json` also includes selected pipeline summary fields from the same run, including `pipeline_diagnostic_codes`, `source_coverage_warnings`, `recommendation_screening_matrix_available`, `recommendation_exclusion_payload_available`, and `source_coverage_basis`. These fields are copied from the dry-run stdout only; the wrapper does not rerun the pipeline.

## Codex Morning Summary

The Codex app automation `baldr scheduled evidence morning report` runs separately at about local time 05:30. It only reads Windows Task Scheduler status, `latest_status.json`, the latest data update status, the latest recommendation snapshot status, the latest evidence dry-run report, and relevant log warning / error sections, then writes a Traditional Chinese summary to the user.

It must not rerun data update, rerun data freshness, rerun the evidence pipeline, enter confirm write mode, create or modify Windows Task Scheduler tasks, write the production evidence DB, change portfolio / scoring / recommendation weights, apply lifecycle actions, push, or produce trading advice.
