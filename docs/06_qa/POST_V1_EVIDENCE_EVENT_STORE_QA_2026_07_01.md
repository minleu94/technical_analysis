# Post-V1 Evidence Event Store QA（2026-07-01）

## Scope

本次完成 Post-V1 Evidence-Driven baldr 的第一個低風險增量：

- Evidence Event Store v1：append-only evidence event model、idempotent hash、deterministic JSON。
- Evidence Outcome v1：保存 5 / 10 / 20 / 60 交易日 close-to-close forward research outcome。
- Forward Outcome Calculator v1：讀 SQLite `daily_prices`、`market_indices`、`industry_indices`，計算 forward return / benchmark excess / industry excess。
- CLI inspection：最小事件檢視與 outcome 計算入口。

本次沒有建立 UI dashboard，沒有接 importer，沒有修改 scoring / recommendation weight / portfolio position。

## Files Changed

新增：

- `app_module/evidence_event_dtos.py`
- `app_module/evidence_event_repository.py`
- `app_module/evidence_event_service.py`
- `app_module/forward_performance_service.py`
- `data_module/evidence_event_migration.py`
- `scripts/inspect_evidence_events.py`
- `scripts/calculate_forward_outcomes.py`
- `tests/test_evidence_event_repository.py`
- `tests/test_evidence_event_service.py`
- `tests/test_forward_performance_service.py`
- `tests/test_evidence_event_cli.py`
- `docs/superpowers/specs/2026-07-01-post-v1-evidence-event-store-design.md`
- `docs/superpowers/plans/2026-07-01-post-v1-evidence-event-store.md`
- `docs/06_qa/POST_V1_EVIDENCE_EVENT_STORE_QA_2026_07_01.md`

修改：

- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_vision_specification.md`
- `docs/01_architecture/system_architecture.md`

## Schema / Migration Safety

- 新 schema 只新增 `evidence_events` 與 `evidence_outcomes`，不修改既有核心 tables。
- `data_module/evidence_event_migration.py` 提供 working-copy dry-run report 與 backup apply helper。
- repository `ensure_schema()` 可重入，建立缺少 evidence tables / indexes。
- 測試全程使用 `tmp_path` 與測試 SQLite，不碰正式 `D:/Min/Python/Project/FA_Data` DB。

## Test Commands

目前已執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_evidence_event_repository.py tests\test_evidence_event_service.py tests\test_forward_performance_service.py tests\test_evidence_event_cli.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
$files = Get-ChildItem app_module,data_module,scripts -Filter *.py | Select-Object -ExpandProperty FullName; .\.venv\Scripts\python.exe -m py_compile @files
```

註：`python -m py_compile app_module\*.py data_module\*.py scripts\*.py` 在本機 PowerShell/Python 組合未展開萬用字元，回傳 `[Errno 22] Invalid argument: 'app_module\\*.py'`；因此改用 PowerShell 展開檔案清單後執行同等 py_compile 檢查。

## Test Results

- Focused pytest：`18 passed in 6.34s`。
- 金融 float boundary：exit code 0。
- py_compile：PowerShell 展開 `app_module`、`data_module`、`scripts` 下 `.py` 後 exit code 0。

## Known Limitations

- v1 outcome 使用 close-to-close event-date basis，不是可執行績效。
- benchmark 只嘗試 `market_indices`；找不到會保存 NULL + warning。
- industry benchmark 只嘗試 `industry_indices` 的 `industry_benchmark_id` / `sector`；找不到會保存 NULL + warning。
- concept basket 欄位已保留，但 v1 不計算 concept excess。
- 未處理完整交易限制、處置股、分盤、全額交割、跳空鎖死、除權息時間軸。
- 未建立 Forward Performance Dashboard read model。

## Not Done

- Recommendation result importer。
- Daily Decision Desk snapshot importer。
- Live vs Research Gap Dashboard。
- Signal Decay Monitor。
- Decision Quality Review。
- UI integration。

## Next Increment

1. 接 Recommendation / Daily Decision Desk importer。
2. 建 Forward Performance Dashboard read model。
3. 補 concept basket / industry mapping governance。
4. 接 Live vs Research Gap Dashboard。
5. 接 Signal Decay Monitor 與 Decision Quality Review。

## Rollback Note

若正式 DB 已套用 evidence schema，需要回復時可使用 `apply_evidence_event_schema_migration()` 產生的 backup file 覆蓋回原 DB。因本次 schema 只新增 evidence tables，程式層停用可先停止呼叫 repository / CLI，不需修改既有 scoring、recommendation、portfolio 或 UI 模組。
