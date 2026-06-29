# Full App Healthcheck UI Smoke Design

> 建立日期：2026-06-29
> Rollback baseline：`rollback/full-app-healthcheck-ui-smoke-20260629` (`a73ac65`)
> 工作分支：`codex/full-app-healthcheck-ui-smoke`

## 目標

把現有 Full App Healthcheck 從「非破壞式 metadata / bridge 輔助」推進到更接近真人 UI 操作的驗證流程，同時保留分 tab 執行能力，讓未來驗證單一工作區時不必每次跑完整 UI 測試。

本輪不把 healthcheck 變成 CI release gate；runner 通過不代表人工 healthcheck 母檔全部完成。完整人工 UI smoke test 仍以 `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` 為母檔。

## 非目標

- 不自動確認高風險 dialog。
- 不執行正式資料寫入、migration、backfill apply、harvester 或大量外部來源更新。
- 不修改策略、回測、推薦、Portfolio 或 fundamental 核心計算。
- 不把 quick / full mode 改成 blocking release gate。
- 不移除人工驗證要求；manual-only 與 write-risk-manual 仍需保留。

## 使用者需求對應

1. 目前節點必須可回滾。
   - 已建立本地 tag：`rollback/full-app-healthcheck-ui-smoke-20260629`。
   - 後續每個 batch 都獨立 commit。

2. 未來測試要能分不同 tab 驗證。
   - Runner 新增 tab/workspace 分流，例如 `--tab update`、`--tab research`、`--tab portfolio`。
   - 指定 tab 時只跑該 tab 對應的 direct / candidate-safe suites 與 report sections。

3. 接近真人 UI 操作測試。
   - 新增受控 MainWindow smoke 骨架：可在 offscreen 模式啟動主視窗、檢查 tab 順序、切換 tab、收集文字 / widget evidence。
   - 高風險按鈕只測存在、文案與 cancel route metadata，不點擊 confirm。

4. 文件與 commit 分批。
   - 文件 spec / plan 先獨立 commit。
   - 每個 runner 行為變更與文件同步分批 commit。
   - 每批 commit 後跑該批 focused tests。

## 架構設計

### 1. Tab 路由層

新增一個輕量 routing layer，把 workspace tab 對應到可執行 suites：

- `update`：UpdateView direct quick / full bridge 與 Update QA script。
- `market`：Market Regime、Smart Money，以及後續強弱股 / 產業 candidate。
- `decision`：Daily Decision Desk quick bridge。
- `research`：Research workflow、Registry compare、Research Run save / report export candidate。
- `recommendation`：Recommendation profile / result candidate 與 recommendation service oracle metadata。
- `watchlist`：Watchlist candidate pool / batch handoff candidate。
- `portfolio`：Portfolio view / condition monitor candidate；write-risk 操作保留 manual。
- `runtime`：Runtime view candidate。
- `cross-flow`：推薦到回測、持倉到主力流向、session strip 等跨工作區項目。

Tab routing 不取代 mode。`mode` 控制安全級別與 runner 深度，`tab` 控制工作區範圍。

### 2. Existing Suite Registry 擴充

現有 `ExistingSuite` 保留 `modes` 與 `covered_healthcheck_ids`，新增或等價導入 `tabs` 欄位。`suites_for_mode()` 保持向後相容；新增 `suites_for_mode_and_tabs()` 給 CLI 使用。

預設不傳 `--tab` 時，runner 行為必須與目前相同。

### 3. MainWindow Smoke 骨架

MainWindow smoke 採明確 opt-in，預設不跑。第一版只做：

- 啟動 `ui_qt.main` 或主視窗 factory 所需的非破壞初始化。
- 確認 8 個頂層工作區 tab 存在且順序符合 Manual。
- 切換每個 tab，確認不拋例外。
- 收集 status bar / tab label / visible widget evidence。

若任何流程需要正式資料寫入、按下更新、保存、清空、刪除或 confirm，第一版只產生 report-only / manual gap，不執行。

### 4. Reporting

報告需清楚顯示：

- `mode`
- `tabs`
- 實際執行 suites
- manual-only / write-risk-manual gaps
- blocked reason
- 對應 healthcheck IDs

這讓未來單 tab 驗證可以留下可比對 evidence。

## 錯誤處理

- 未知 `--tab` 由 argparse 拒絕。
- 指定 tab 沒有可執行 suites 時，runner 不應誤報通過完整驗證；應在報告標示 `no-executable-suite` 或 report-only gaps。
- suite 若不在 direct bridge allowlist，仍由既有 `is_allowed_in_bridge()` 擋下。
- `write-risk-manual` 項目不得因 tab routing 被拉進 runner。

## 測試策略

採 TDD 分批：

1. 先寫 `--tab` 解析與 suite filtering 的失敗測試。
2. 再實作 minimal routing。
3. 補 CLI 行為測試，確認不傳 `--tab` 時 full / quick 行為不變。
4. 補 report evidence 測試。
5. MainWindow smoke 先寫 plan / metadata 測試，再加入 opt-in smoke action。

必要驗證命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_full_app_healthcheck_test_suite_bridge.py tests\test_full_app_healthcheck_runner.py tests\test_full_app_healthcheck_reporting.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir $env:TEMP\baldr_hc_quick --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab update --output-dir $env:TEMP\baldr_hc_update --fail-fast
```

## 文件同步

本輪必須同步：

- `docs/06_qa/FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md`
- `docs/06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md`
- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`

若新增設計或 plan 文件，必須在 Documentation Index 登錄。

## 回滾策略

- 回到本輪起點：`git reset --hard rollback/full-app-healthcheck-ui-smoke-20260629`
- 回滾單批：`git revert <commit>`
- 文件與 runner 分批 commit，避免一次回滾大量不相關變更。
