# Post-V1 V1.3 Evidence Operations QA（2026-07-03）

## 變更摘要

V1.3 新增 `EvidenceOperationsService` 與 `scripts/build_evidence_operations_weekly_review.py`，把 scheduler readiness、Decision Quality review / action item、Signal Decay candidate 彙總成每週人工覆盤包。

本輪不啟用 production scheduler，不自動套用 demote / retire，不改 Strategy Lifecycle state，不改 portfolio，不改 `ScoringEngine`，也不宣稱任何 alpha 或投資有效性。

## Scope

### In

- Weekly evidence operations JSON / Markdown report。
- Manual approval package，固定揭露 `production_scheduler_allowed=false`。
- Decision Quality open item / action item 摘要。
- Signal Decay demote / retire candidate 人工審核清單，`apply_action=false`。
- Action item planning：dry-run 預覽；`--confirm-action-items` 才 append-only 寫入指定 DB。

### Out

- Production write-mode scheduler。
- 自動 lifecycle action。
- 自動交易、持倉異動、策略版本刪除或權重調整。
- 將 evidence 樣本不足解讀成策略有效 / 無效。

## CLI

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-24 --end-date 2026-06-30 --db-path <working-copy-db> --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-24 --end-date 2026-06-30 --db-path <working-copy-db> --plan-action-items --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-24 --end-date 2026-06-30 --db-path <working-copy-db> --confirm-action-items --action-owner human --json-output
```

`--confirm-action-items` 必須指定 explicit `--db-path`；疑似正式 DB 需額外 `--allow-production-like-db`。一般 QA 應使用 working-copy DB。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_operations_service.py tests\test_evidence_operations_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\evidence_operations_dtos.py app_module\evidence_operations_service.py scripts\build_evidence_operations_weekly_review.py
```

本輪 focused 驗證結果：

- `tests/test_evidence_operations_service.py tests/test_evidence_operations_cli.py`：5 passed。
- `py_compile`：通過。

## 驗收

- Weekly report 在無 review / decay 樣本時輸出 `coverage_only` 與 `collect_more_evidence`，不輸出策略結論。
- readiness package 固定 `production_scheduler_allowed=false`。
- Signal Decay demote / retire 只進 `manual_lifecycle_candidates`，且每筆 `apply_action=false`。
- Action item planning 預設 dry-run 不寫入；confirm 後 append-only 建立 action item；重跑同一 open item 會跳過既有 action item。
- CLI JSON payload 固定 `write_performed=false`，除非使用 `--confirm-action-items` 且實際建立 action item。

## Remaining Gaps

- Evidence 樣本仍需持續累積；樣本不足只能判讀覆蓋率與資料品質。
- Production scheduler 仍未啟用；未來仍需 explicit approval、backup、rollback 與 production design。
- V2.0 Unified Decision Workbench 仍需等 V1.1 至 V1.3 的實際使用證據後再設計。

