# V2.2 Sidecar Weekly Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立週日 Windows Task，自動將 Evidence Review collection 保存到 sidecar DB，並保留人工審核與既有 weekly history 的分界。

**Architecture:** `twstock.db` 只讀；新的 collection repository 只寫入 `evidence_scheduler.db`。CLI 建立 collection 和報告；CMD wrapper 每週觸發，絕不呼叫 `--confirm-action-items` 或 `--save-history`。

**Tech Stack:** Python 3.11、SQLite、Pytest、PowerShell、CMD、`schtasks.exe`。

## Global Constraints

- 不修改 `D:/Min/Python/Project/FA_Data/sqlite/twstock.db` 的 schema 或資料。
- 不建立 broker order、不自動交易、不套用 lifecycle action、不修改 scoring / portfolio。
- collection 只能是 `pending_human_review` 或 `collection_failed`；不得自動核准或寫入 weekly history。
- sidecar migration 與 collection 必須 idempotent；失敗保留 error record，禁止自動 `DROP TABLE`。

### Task 1: Sidecar collection DTO 與 repository

**Files:**

- Create: `app_module/evidence_weekly_collection_dtos.py`
- Create: `app_module/evidence_weekly_collection_repository.py`
- Test: `tests/test_evidence_weekly_collection_repository.py`

**Interfaces:** `EvidenceWeeklyCollectionRecord` 包含 collection ID、period、source path/hash、status、payload、error 和 timestamp。Repository 提供 `save_pending`、`save_failed`、`get_by_identity`。

- [ ] 寫 failing test：對 temporary source SQLite 執行相同 `save_pending(period_start="2026-07-06", period_end="2026-07-12", payload_json={"status":"coverage_only"})` 兩次；兩次 ID 相同、status 為 `pending_human_review`，且 source 檔案 bytes 完全相同。
- [ ] 執行 `./.venv/Scripts/python.exe -m pytest tests/test_evidence_weekly_collection_repository.py -q -o addopts=`，確認因模組缺失而 FAIL。
- [ ] 最小實作：sidecar-only schema version 與 `evidence_weekly_collections`；以 buffered SHA-256、period 與 canonical JSON 生成 deterministic identity；`save_failed` 保留 error type/message。
- [ ] 重跑同一測試，預期 PASS。
- [ ] Commit：`git add app_module/evidence_weekly_collection_dtos.py app_module/evidence_weekly_collection_repository.py tests/test_evidence_weekly_collection_repository.py`，再 `git commit -m "feat(v2.2): add sidecar weekly collection store"`。

### Task 2: Collection CLI and reports

**Files:**

- Create: `scripts/collect_v2_2_weekly_evidence.py`
- Test: `tests/test_collect_v2_2_weekly_evidence_cli.py`

**Interfaces:** CLI 接受 `--source-db-path`、`--sidecar-db-path`、`--output-root`、可選 `--period-end`、`--json-output`；產生 sidecar record 與 `<output-root>/scheduled/v2_2_weekly_collection/` 的 JSON/Markdown。

- [ ] 寫 failing subprocess test：呼叫 CLI 後預期 `collection_status == "pending_human_review"`，temporary source SQLite bytes 不變。
- [ ] 執行 `./.venv/Scripts/python.exe -m pytest tests/test_collect_v2_2_weekly_evidence_cli.py -q -o addopts=`，確認因 script 缺失而 FAIL。
- [ ] 實作：使用 SQLite read-only URI 取得不晚於週期結束日的最後交易日，建立 read-only coverage/review payload。任一錯誤保存 `collection_failed` 及 error details、回傳 nonzero；不可 instantiate history repository、不可 action confirm。
- [ ] 執行 `./.venv/Scripts/python.exe -m pytest tests/test_collect_v2_2_weekly_evidence_cli.py tests/test_evidence_weekly_collection_repository.py -q -o addopts=`，預期 PASS。
- [ ] Commit：`git add scripts/collect_v2_2_weekly_evidence.py tests/test_collect_v2_2_weekly_evidence_cli.py`，再 `git commit -m "feat(v2.2): collect weekly evidence into sidecar"`。

### Task 3: Windows Task wrapper and registration

**Files:**

- Create: `scripts/scheduled/run_v2_2_weekly_collection.ps1`
- Create: `scripts/scheduled/run_v2_2_weekly_collection.cmd`
- Modify: `scripts/scheduled/register_baldr_scheduled_tasks.cmd`
- Modify: `scripts/scheduled/query_baldr_scheduled_tasks.cmd`
- Modify: `scripts/scheduled/unregister_baldr_scheduled_tasks.cmd`
- Test: `tests/test_scheduled_cmd_scripts_task_names.py`

**Interfaces:** Task 名稱 `baldr-v2-2-weekly-collection`，Trigger 為 `/SC WEEKLY /D SUN /ST 18:00`，wrapper 只執行 collection CLI。

- [ ] 寫 failing test：register CMD 含 task name 和 `/SC WEEKLY /D SUN /ST 18:00`；PowerShell wrapper 不含 `--save-history` 或 `--confirm-action-items`。
- [ ] 執行 `./.venv/Scripts/python.exe -m pytest tests/test_scheduled_cmd_scripts_task_names.py -q -o addopts=`，確認 FAIL。
- [ ] 依現有 CMD pattern 實作 wrapper、dryrun / register / query / unregister。PowerShell wrapper 以 explicit source、sidecar、output path 執行，保留 log 並傳回 CLI exit code。
- [ ] 執行 `./.venv/Scripts/python.exe -m pytest tests/test_scheduled_cmd_scripts_task_names.py tests/test_scheduled_scripts_no_trading_language.py tests/test_scheduled_scripts_exist.py -q -o addopts=`，預期 PASS。
- [ ] Commit：`git add scripts/scheduled tests/test_scheduled_cmd_scripts_task_names.py`，再 `git commit -m "feat(v2.2): schedule weekly sidecar collection"`。

### Task 4: Documentation and registration verification

**Files:**

- Modify: `docs/07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/06_qa/POST_V1_EVIDENCE_SCHEDULER_APPROVAL_SOP.md`
- Modify: `scripts/scheduled/README.md`

- [ ] 文件明確說明 scheduled collection 僅保存 `pending_human_review`，不算 manual review、不寫 weekly history，`production_scheduler_allowed=false` 不變；rollback 是 task disable/unregister，絕非自動 table drop。
- [ ] 執行 `scripts\scheduled\register_baldr_scheduled_tasks.cmd dryrun`；預期輸出 weekly task / `WEEKLY SUN 18:00` 且不建立 Task。
- [ ] 執行 `scripts\scheduled\register_baldr_scheduled_tasks.cmd register`，再執行 `schtasks /Query /TN baldr-v2-2-weekly-collection /V /FO LIST`；預期 task 存在且只指向 weekly collection CMD wrapper。
- [ ] 執行 `./.venv/Scripts/python.exe -m pytest tests/test_evidence_weekly_collection_repository.py tests/test_collect_v2_2_weekly_evidence_cli.py tests/test_scheduled_cmd_scripts_task_names.py tests/test_scheduled_scripts_no_trading_language.py tests/test_scheduled_scripts_exist.py tests/test_audit_document_encoding.py -q -o addopts=`，預期 PASS。
- [ ] Commit：`git add docs scripts/scheduled`，再 `git commit -m "docs(v2.2): document sidecar weekly collection"`。
