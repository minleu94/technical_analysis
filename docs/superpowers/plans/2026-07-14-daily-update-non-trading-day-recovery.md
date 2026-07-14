# 每日資料更新無資料日恢復 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TWSE 明確查無資料日不再阻斷快速更新與排程，真正失敗必須在 UI 與 freshness 可見。

**Architecture:** `DataLoader` 先區分 TWSE 的明確「沒有符合條件的資料」回覆與其他錯誤；批次下載器只根據這個受限診斷輸出 `SKIPPED_NO_DATA`。共用解析器將它轉為 `skipped_dates` 而非失敗。排程與 UI coordinator 將跳過日列為 warning，但仍繼續 TPEX、SQLite 與技術指標。freshness 唯讀最新排程狀態，讓真正失敗不可被日曆容許值掩蓋。

**Tech Stack:** Python 3.11、pytest、PySide6、SQLite、Windows Task Scheduler。

## Global Constraints

- 使用繁體中文；不回補或覆寫正式 `DATA_ROOT`。
- 只有上游明確回覆查無資料可跳過；網路、格式、解析與未知例外仍是失敗。
- 不改投資、推薦、evidence 或自動交易邊界。
- 測試以 `tmp_path` 與 monkeypatch 隔離資料來源。

---

### Task 1: 將 TWSE 查無資料設為安全跳過

**Files:**
- Modify: `data_module/data_loader.py`
- Modify: `scripts/batch_update_daily_data.py`
- Modify: `app_module/update_daily_output.py`
- Test: `tests/test_core/test_data_loader.py`
- Test: `tests/test_update_daily_output.py`

**Interfaces:** `DataLoader.last_daily_download_outcome` 僅為 `success`、`no_data` 或 `failed`。只有 TWSE `stat` 文字含「沒有符合條件的資料」或「查無資料」才設為 `no_data`；例如「查詢日期大於今日」仍為 `failed`。下載器輸出 `[UPDATE_SUMMARY] SUCCESS: <n> days, SKIPPED_NO_DATA: <n> days, FAILED: <n> days`，解析器回傳 `success`、`skipped_dates`、`failed_dates`。

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_daily_update_output_treats_explicit_no_data_as_safe_skip():
    result = parse_daily_update_output(
        "SKIPPED_NO_DATA 2026-07-10 上游查無資料\n"
        "[UPDATE_SUMMARY] SUCCESS: 1 days, SKIPPED_NO_DATA: 1 days, FAILED: 0 days",
        ["2026-07-10", "2026-07-13"],
    )
    assert result["success"] is True
    assert result["skipped_dates"] == ["2026-07-10"]
    assert result["failed_dates"] == []


def test_parse_daily_update_output_keeps_failed_count_as_failure():
    result = parse_daily_update_output(
        "[UPDATE_SUMMARY] SUCCESS: 0 days, SKIPPED_NO_DATA: 0 days, FAILED: 1 days",
        ["2026-07-10"],
    )
    assert result["success"] is False
    assert result["failed_dates"] == ["失敗_1"]


def test_download_marks_only_explicit_twse_no_data_as_no_data(test_config, monkeypatch):
    monkeypatch.setattr("data_module.data_loader.requests.Session", _NoDataSession)
    monkeypatch.setattr("data_module.data_loader.time.sleep", lambda _: None)
    loader = DataLoader(test_config)
    assert loader.download_from_api("2026-07-10") is None
    assert loader.last_daily_download_outcome == "no_data"


def test_download_keeps_future_date_response_as_failure(test_config, monkeypatch):
    monkeypatch.setattr("data_module.data_loader.requests.Session", _FutureDateSession)
    monkeypatch.setattr("data_module.data_loader.time.sleep", lambda _: None)
    loader = DataLoader(test_config)
    assert loader.download_from_api("2026-07-10") is None
    assert loader.last_daily_download_outcome == "failed"
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_update_daily_output.py -q -o addopts=`

Expected: FAIL，現有摘要不接受 `SKIPPED_NO_DATA`。

- [ ] **Step 3: Implement minimal behavior**

```python
# data_module/data_loader.py
if all(_is_explicit_twse_no_data_status(status) for status in api_statuses):
    self.last_daily_download_outcome = "no_data"
    return None

# scripts/batch_update_daily_data.py
if df is None or df.empty:
    if loader.last_daily_download_outcome == "no_data":
        skipped_no_data_dates.append(date)
        print(f"SKIPPED_NO_DATA {date} 上游查無資料", flush=True)
        continue
    failed_dates.append(date)
    fail_count += 1

print(f"[UPDATE_SUMMARY] SUCCESS: {success_count} days, "
      f"SKIPPED_NO_DATA: {len(skipped_no_data_dates)} days, FAILED: {fail_count} days", flush=True)
```

`parse_daily_update_output()` 必須解析 `SKIPPED_NO_DATA` 行與新版 summary，並只以 `FAILED` 決定 `success`。

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_update_daily_output.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 5: Commit**

Run: `git add scripts/batch_update_daily_data.py app_module/update_daily_output.py tests/test_update_daily_output.py; git commit -m "fix(data): skip explicit TWSE no-data dates"`

### Task 2: 保留 UI 與排程的後續同步鏈路

**Files:**
- Modify: `scripts/scheduled/run_daily_data_update_quick.py`
- Modify: `ui_qt/views/update/update_all_coordinator.py`
- Test: `tests/test_scheduled_data_update_runner.py`
- Test: `tests/test_update_all_coordinator.py`

**Interfaces:** 成功但 `skipped_dates` 非空的每日更新，排程 status 為 `passed_with_warnings`；UI `run_update_all()` 成功結果含 TWSE warning，且包含 SQLite 同步步驟。

- [ ] **Step 1: Write failing tests**

```python
def test_scheduled_runner_continues_after_twse_no_data_skip(tmp_path, monkeypatch):
    service = FakeUpdateService(daily_result={"success": True, "skipped_dates": ["2026-07-10"]})
    monkeypatch.setattr(runner, "UpdateService", lambda config: service)
    assert runner.main(_runner_args(tmp_path)) == 0
    assert "sync_daily_prices_to_sqlite" in service.calls
    payload = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert payload["status"] == "passed_with_warnings"


def test_update_all_keeps_success_when_twse_date_was_safely_skipped():
    service, _progress, result = _run(
        "quick",
        daily_result={"success": True, "skipped_dates": ["2026-07-10"]},
    )
    assert result["success"] is True
    assert any("TWSE 上游查無資料" in warning for warning in result["warnings"])
    assert ("sync_source_to_sqlite", "daily_price_files", "2026-07-01", "2026-07-10") in service.calls
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_data_update_runner.py tests/test_update_all_coordinator.py -q -o addopts=`

Expected: FAIL，skip 診斷尚未傳遞為 warning。

- [ ] **Step 3: Implement minimal propagation**

```python
def _twse_skip_warning_messages(result: dict[str, Any]) -> list[str]:
    skipped_dates = sorted({str(item) for item in result.get("skipped_dates", []) if str(item).strip()})
    return [] if not skipped_dates else [f"TWSE 上游查無資料，已跳過日期：{', '.join(skipped_dates)}"]
```

每日更新結果成功時，兩個 coordinator 加入上述 warnings 並繼續；`success=False` 路徑不改變。

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_data_update_runner.py tests/test_update_all_coordinator.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 5: Commit**

Run: `git add scripts/scheduled/run_daily_data_update_quick.py ui_qt/views/update/update_all_coordinator.py tests/test_scheduled_data_update_runner.py tests/test_update_all_coordinator.py; git commit -m "fix(update): surface skipped TWSE dates without blocking sync"`

### Task 3: Freshness 顯示最近快速更新失敗

**Files:**
- Modify: `scripts/scheduled/data_freshness_probe.py`
- Test: `tests/test_scheduled_data_freshness_probe.py`

**Interfaces:** 讀取 `OUTPUT_ROOT/scheduled/data_update_quick/latest_status.json`；若 status 為 `failed`，輸出 `checks["data_update_quick_status"] == "failed"` 與 `data_update_quick_failed` warning。

- [ ] **Step 1: Write failing test**

```python
def test_probe_degrades_when_latest_quick_update_failed(tmp_path):
    path = tmp_path / "output" / "scheduled" / "data_update_quick" / "latest_status.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "failed", "errors": ["TWSE failure"]}), encoding="utf-8")
    assert main(_probe_args(tmp_path)) == 0
    payload = json.loads((tmp_path / "freshness.json").read_text(encoding="utf-8"))
    assert payload["status"] == "degraded"
    assert "data_update_quick_failed" in payload["warnings"]
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_data_freshness_probe.py -q -o addopts=`

Expected: FAIL，probe 尚未讀取快速更新結果。

- [ ] **Step 3: Implement minimal read-only check**

```python
path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
if path.exists():
    quick_status = str(json.loads(path.read_text(encoding="utf-8")).get("status", "unknown"))
    checks["data_update_quick_status"] = quick_status
    if quick_status == "failed":
        warnings.append("data_update_quick_failed")
```

JSON 無法讀取時，加入 `data_update_quick_status_unreadable` warning，不寫任何市場資料。

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_data_freshness_probe.py -q -o addopts=`

Expected: PASS。

- [ ] **Step 5: Commit**

Run: `git add scripts/scheduled/data_freshness_probe.py tests/test_scheduled_data_freshness_probe.py; git commit -m "fix(scheduler): expose failed quick updates in freshness"`

### Task 4: 文件與整體驗證

**Files:**
- Modify: `docs/03_data/daily_data_update_guide.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: 更新文件**

說明 `skipped_dates` 是 TWSE 上游明確查無資料的安全跳過；`failed_dates` 才代表阻斷。說明 `passed_with_warnings`、`failed`、`latest_status.json` 與當日 log 的判讀入口。

- [ ] **Step 2: Run full verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_update_daily_output.py tests/test_scheduled_data_update_runner.py tests/test_scheduled_data_freshness_probe.py tests/test_update_all_coordinator.py tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe -m py_compile app_module\update_daily_output.py scripts\batch_update_daily_data.py scripts\scheduled\run_daily_data_update_quick.py scripts\scheduled\data_freshness_probe.py ui_qt\views\update\update_all_coordinator.py
```

Expected: 指定 pytest、QA 與編譯命令 exit 0；mypy 的既有失敗必須逐項記錄並另外驗證本次檔案。

- [ ] **Step 3: Commit**

Run: `git add docs/03_data/daily_data_update_guide.md docs/07_guides/APPLICATION_MANUAL.md docs/superpowers/plans/2026-07-14-daily-update-non-trading-day-recovery.md; git commit -m "docs(data): explain daily update skip diagnostics"`
