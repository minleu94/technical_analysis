# Broker Branch Registry Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 8 verified broker branches to the formal registry, smoke-test one trading day, sync SQLite, then backfill the missing historical range in the background.

**Architecture:** Treat `D:/Min/Python/Project/FA_Data/meta_data/broker_branch_registry.csv` as the registry SSOT. Use existing `BrokerBranchUpdateService` and `UpdateService.sync_source_to_sqlite("broker_branch_files")` so daily CSV, merged CSV, and SQLite follow the current pipeline.

**Tech Stack:** Python csv/sqlite3, `app_module.broker_branch_update_service.BrokerBranchUpdateService`, `app_module.update_service.UpdateService`, formal `TWStockConfig` data root.

## Global Constraints

- Do not delete or overwrite existing raw data.
- Backup registry CSV and SQLite before writing formal data.
- Add only these keys: `9800_9875`, `9600_9658`, `5850_5854`, `9600_9692`, `7000_700F`, `7000_7001`, `7000_700a`, `9800_984K`.
- Smoke-test date: `2026-07-06`, because local `daily_prices` and `broker_flows` both have this date.
- Historical backfill range: `2025-10-24` to `2026-07-06`, matching the current `broker_flows` local coverage.
- Do not stage, commit, or modify unrelated existing dirty files.

---

### Task 1: Registry Backup And Append

**Files:**
- Modify: `D:/Min/Python/Project/FA_Data/meta_data/broker_branch_registry.csv`
- Create: timestamped backup under `D:/Min/Python/Project/FA_Data/meta_data/backups/`

**Interfaces:**
- Consumes: existing registry CSV columns.
- Produces: 48 active branch rows with the 8 new branch keys.

- [ ] **Step 1: Create backups**

Run a Python script that copies the formal registry CSV and SQLite DB to timestamped backup paths.

- [ ] **Step 2: Append missing rows**

Use `csv.DictReader` and `csv.DictWriter`; keep existing rows intact; append only rows whose `branch_system_key` is absent.

- [ ] **Step 3: Validate registry**

Load `BrokerBranchUpdateService._load_branch_registry(active_only=True, repair_registry=False)` and assert all 8 keys are present.

### Task 2: One-Day Pipeline Smoke Test

**Files:**
- Create: `D:/Min/Python/Project/FA_Data/broker_flow/<branch_key>/daily/2026-07-06.csv`
- Create/update: `D:/Min/Python/Project/FA_Data/broker_flow/<branch_key>/meta/merged.csv`
- Modify: `D:/Min/Python/Project/FA_Data/sqlite/twstock.db`

**Interfaces:**
- Consumes: Task 1 registry rows.
- Produces: daily CSV, merged CSV, and SQLite `broker_flows` rows for `2026-07-06`.

- [ ] **Step 1: Fetch one day**

Run `BrokerBranchUpdateService.update_broker_branch_data("2026-07-06", "2026-07-06", branch_system_keys=[...], force_all=False)`.

- [ ] **Step 2: Merge one day**

Run `BrokerBranchUpdateService.merge_broker_branch_data(branch_system_keys=[...], force_all=False)`.

- [ ] **Step 3: Sync one day to SQLite**

Run `UpdateService.sync_source_to_sqlite("broker_branch_files", "2026-07-06", "2026-07-06")`.

- [ ] **Step 4: Verify one-day results**

Assert each new branch has daily CSV rows, merged CSV rows, and SQLite rows for `20260706`.

### Task 3: Historical Backfill

**Files:**
- Create/update: broker daily CSV and merged CSV under each new branch directory.
- Modify: SQLite `broker_flows`.

**Interfaces:**
- Consumes: Task 2 verified branch keys.
- Produces: historical broker-flow coverage for the new branches.

- [ ] **Step 1: Run historical update**

Run `BrokerBranchUpdateService.update_broker_branch_data("2025-10-24", "2026-07-06", branch_system_keys=[...], force_all=False)`.

- [ ] **Step 2: Merge historical data**

Run `BrokerBranchUpdateService.merge_broker_branch_data(branch_system_keys=[...], force_all=False)`.

- [ ] **Step 3: Sync historical range**

Run `UpdateService.sync_source_to_sqlite("broker_branch_files", "2025-10-24", "2026-07-06")`.

- [ ] **Step 4: Final validation**

Report per-branch daily file count, merged CSV row count, SQLite row count, and date range.
