# MainWindow UI Smoke Operation Design

> Date: 2026-06-30
> Scope: Full App Healthcheck 的 opt-in MainWindow 操作層。

## Goal

把現有 MainWindow smoke skeleton 升級為真正可執行的 opt-in UI smoke：啟動 PySide6 MainWindow、逐頁切換頂層 tab、擷取畫面證據、測試多 viewport resize、執行高風險 dialog cancel path，並把 evidence 寫入 Full App Healthcheck report。

## Non-Goals

- 不讓預設 `--mode quick` 或 `--mode full` 自動啟動 MainWindow。
- 不點擊任何會寫正式資料、刪除資料、執行 migration、backfill apply、外部大量抓取或長任務的確認按鈕。
- 不把 visual screenshot 通過解讀為人工 UX 完全通過；截圖是 evidence，不是審美判定。
- 不把這次改動變成 CI blocking release gate。

## User Entry Points

新增 opt-in CLI：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --ui-smoke --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
```

可附加：

```powershell
--ui-smoke-switch-tabs
--ui-smoke-screenshot
--ui-smoke-resize 1366x768 --ui-smoke-resize 390x844
--ui-smoke-dialog-cancel
```

`--ui-smoke` 是總開關；其他選項沒有總開關時不執行 MainWindow。

## Architecture

1. `qa/full_app_healthcheck/mainwindow_smoke.py`
   - 保留純 Python evidence shape 與 tab label 檢查。
   - 新增 viewport parser、screenshot evidence schema、dialog cancel evidence schema。
   - 可用 fake window 測，不直接 import `QApplication`。

2. `qa/full_app_healthcheck/mainwindow_smoke_runner.py`
   - 真正 import PySide6 與 `ui_qt.main.MainWindow`。
   - 建立或重用 `QApplication`，套用 app theme，建立 MainWindow。
   - 以 offscreen 平台顯示 window，處理 event loop，切 tab，resize，grab screenshot。
   - 執行 cancel-only dialog path：目前先覆蓋 UpdateView 的強制重新合併取消路徑，攔截 `QMessageBox` 並回傳取消，確認 service method 沒有被呼叫。
   - 所有輸出寫到 runner output dir 下的 run-specific evidence folder。

3. `scripts/run_full_app_healthcheck.py`
   - 新增 opt-in args 與 context。
   - 動態 append MainWindow smoke step 到 manifest；預設 manifest 不變。
   - action registry 加入 `run_mainwindow_ui_smoke`。

4. `qa/full_app_healthcheck/reporting.py`
   - 繼續把 evidence dict 寫入 `result.json` / `REPORT.md`。
   - Screenshot path 以相對或絕對字串呈現，方便人工打開。

## Evidence Contract

MainWindow UI smoke step 回傳：

- `window_title`
- `tab_labels`
- `missing_tabs`
- `switched_tabs`
- `screenshots`
- `resize_evidence`
- `dialog_cancel_evidence`
- `forbidden_actions_invoked`

若 `missing_tabs` 非空、screenshot pixmap 為 null、resize 後尺寸不符、dialog cancel 後仍呼叫高風險 service，step 失敗。

## Safety Rules

- MainWindow smoke 只在 `--ui-smoke` 明確傳入時加入 manifest。
- dialog test 只走 cancel path；不可按 confirm。
- resize / screenshot 只操作 widget，不改資料。
- 任何被偵測到的 forbidden action 要寫入 `forbidden_actions_invoked` 並讓 step fail。
- 使用 output dir / run id 子資料夾保存 evidence，不提交 `output/qa/` 或 `%TEMP%` 產物。

## Testing Strategy

- TDD 先補純邏輯測試：viewport parsing、evidence schema、dynamic manifest opt-in。
- 再補 runner action 測試：用 monkeypatch fake MainWindow / QApplication 驗證 orchestrator 呼叫順序與 output paths。
- 最後跑實際 offscreen MainWindow opt-in smoke，確認可啟動、切 tab、截圖、resize、dialog cancel。

## Rollback

本設計接在 `codex/full-app-healthcheck-ui-smoke` 分支上；原始 rollback tag 仍為 `rollback/full-app-healthcheck-ui-smoke-20260629`。本批次會再以小 commit 分段，必要時可回滾到上一個文檔或功能節點。
