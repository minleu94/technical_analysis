# Full App Healthcheck / Testing QA Agent 收束報告 2026-06-23

> 範圍：本文件總結非破壞式 Testing / QA Agent + Full App Healthcheck Runner 路線在 Track A-E 完成後的狀態。這是一份收束與交接文件，不是新的實作計畫。

## 目前狀態

Track A-E 的 metadata 路線已於 commit `7a8db37` 完成到 E-4。後續 report-only integration 已延伸到 commit `8e5b182`，將 coverage burn-down、flow diagnostics、quick gate proposal、full release checklist 與 run history comparison 接入 healthcheck 報告輸出，但仍維持 opt-in、report-only。

目前交付的是一層圍繞既有 Full App Healthcheck Runner 的非破壞式 QA metadata、測試路由、結果解讀與 release review 輔助能力。它沒有把 quick mode 或 full mode 轉成強制 CI / release gate。

目前 repo HEAD 已有後續功能提交，例如 `591ea9b` 的券商分點 MoneyDJ HTTP fast path 與 `7419295` 的 UpdateView / Market Regime UI 收斂。這些提交可能需要同步人工 healthcheck 測項備註，但不改變本 closeout 對 Testing / QA Agent 路線的結論。

## 狀態判讀

本 closeout 的「已完成」代表 Testing / QA Agent 與 Full App Healthcheck Runner 的輔助層已完成，不代表整份人工 healthcheck 母檔已被完全自動化。

- 已完成：測試 inventory、direct bridge allowlist、candidate bridge policy、service oracle metadata、coverage / flow diagnostics、run history comparison，以及 opt-in report sections。
- 已完成：quick / full runner 仍只呼叫已核准的非破壞 direct bridge suites 與 QA script。
- 未啟用：正式 release gate、CI blocking、預設 MainWindow 自動 smoke、資料寫入、migration 或 backfill apply。MainWindow 啟動 / tab 切換 / screenshot / resize / cancel-only dialog 已有 explicit opt-in `--ui-smoke` 執行層。
- 仍需人工：`docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` 內的完整 UI smoke test、manual UX gaps、write-risk paths 與跨工作區可用性判讀。

換句話說，本文件是「Testing / QA Agent 工具鏈收束」；`FULL_APP_HEALTHCHECK_2026_06_16.md` 仍是完整人工 UI healthcheck 的母檔。

## 已完成 Track

| Track | 狀態 | 結果 |
|---|---|---|
| A | 已完成 | 已具備結果解讀、Markdown 渲染、known issue matching、handoff recommendation 與 command advice。 |
| B | 已完成 | 已具備 candidate bridge policy、service oracle metadata 與 coverage burn-down report。 |
| C | 已完成 | 已具備 closed-loop flow model、flow diagnostics 與 known UX gap mapping。 |
| D | 已完成 | 已具備 offscreen widget check metadata、MainWindow smoke plan metadata、viewport resize evidence plan 與 high-risk dry-run dialog plan。 |
| E | 已完成 | 已具備 run history manifest、run comparison、quick mode release gate proposal 與 full mode release checklist。 |

## 現在可以安全使用什麼

- 使用 Testing / QA Agent 文件把功能請求映射到可能的測試命令、安全模式與預期證據。
- 使用 result interpreter / known issue matcher / handoff contract metadata 解釋 healthcheck output，並把失敗導向可能 owner。
- 使用 service oracle metadata 作為功能覆蓋證據，但不要把 service tests 當成 UI flow steps。
- 使用 flow diagnostics、UX gap mapping 與 coverage burn-down metadata 說明哪些功能已覆蓋、僅 oracle-only，或仍是 manual gap。
- 使用 run history manifest 與 comparison helpers，在記憶體中比較歷史 run 與候選 run 的差異。
- 使用 quick gate proposal 與 full release checklist 作為人工 review 與後續 agent 交接輔助。
- 透過 opt-in `--report-section` 把上述 metadata 附加到 `REPORT.md` / `result.json`，但不改變預設 runner 行為。

目前已核准 bridge 範圍：

- Quick mode：`ui-update-workbench`、`ui-decision-desk`。
- Full mode：Quick mode 兩項，加上 `ui-research-workflow`、`ui-market-regime-view`、`ui-run-registry-compare`、`ui-smart-money-flow`、`ui-recommendation-profiles`、`ui-recommendation-next-steps`、`ui-watchlist-candidate-pool`、`ui-portfolio-view`、`ui-runtime-view`、`qa-update-tab`。
- Tab filter：`--tab update|market|decision|research|recommendation|watchlist|portfolio|runtime|cross-flow` 可分頁執行 full mode 的安全 direct bridge，不必每次跑完整 UI 測試。
- MainWindow smoke：已具備 executable opt-in `--ui-smoke`；會用隔離子程序啟動真實 MainWindow、切換頂層 tab、擷取 screenshot、測 viewport resize evidence，並執行 Update 強制合併 cancel-only dialog probe。未傳 `--ui-smoke` 時預設 runner 不啟動 MainWindow。

## 不能誤用或誤判什麼

- Quick mode 不是正式 release gate。
- Full mode 不是正式 release gate。
- E-3 與 E-4 只是 proposal / checklist metadata；它們不啟用 CI、不修改 runner bridge，也不阻擋 release。
- MainWindow smoke、viewport resize 與 Update 強制合併 cancel-only dialog 已可受控執行；其他 high-risk dialog 仍需逐項加入 cancel-only probe，且不得自動 confirm。
- Manual UX gaps、manual-only tests、write-risk tests 與 high-risk dry-run paths 不會因 quick 或 full mode 通過而自動被認證。
- Service oracle tests 是證據，不是 UI flow step。

## 下一階段選項

### 選項 1：維持 Metadata-Only

停在目前穩定邊界。Testing / QA Agent 使用這些模組回答問題、準備證據與交接工作，但不改 runner 行為。

適合優先考量低風險、易回滾、不想引入 release gate noise 的情境。

### 選項 2：加入可選報告區段

把 coverage burn-down、flow diagnostics、run comparison、quick gate proposal 或 full release checklist Markdown 做成 healthcheck output 的 opt-in report sections。

此選項仍必須維持 report-only：不啟用 CI gate、不自動 blocking、不啟動 MainWindow、不執行 dialog、不寫資料。

適合希望把既有 metadata 出現在 QA 報告中的情境。

狀態：已完成。未傳 `--report-section` 時，預設 healthcheck output 與 runner bridge 行為不變。

### 選項 3：設計真正 Release Gate Roadmap

先建立新的 roadmap，再開始實作。該 roadmap 必須定義 gate scope、blocking rules、override policy、failure ownership、allowed modes、manual gaps、rollback behavior、CI / local invocation，以及如何避免 noisy 或誤導性的 release block。

只有在使用者明確要求把 healthcheck output 變成可執行 gate 時，才建議走這條路。

## 建議下一步

不要自動開始新的高風險實作批次。

若要繼續，請先選擇以下之一：

1. 維持 metadata-only，直接作為 QA Agent 的操作知識庫使用。
2. 使用 [`FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md`](FULL_APP_HEALTHCHECK_COVERAGE_MAPPING_2026_06_24.md) 維護逐列 coverage mapping，標記每個人工測項目前是 direct bridge、candidate bridge、service oracle evidence、report-only 還是 manual-only。
3. 另開真正 release gate roadmap。

逐列 coverage mapping 已建立。2026-06-29 已完成第一批 `candidate` 且非 write-risk 的升級：Recommendation Profile / next steps、Watchlist candidate pool、Portfolio fake-service UI 與 Runtime Observatory 進入 full direct bridge，並可透過 `--tab` 分頁驗證。下一批仍應採小批次、先測試再升級；不應把真實資料寫入、dialog 執行或完整 MainWindow 真人操作混入預設 runner。

補充：選項 2 已完成為 opt-in report-only sections，可透過 `--report-section` 將 coverage burn-down、flow diagnostics、quick gate proposal 與 full release checklist 加入 `REPORT.md` / `result.json`。未傳 `--report-section` 時預設 healthcheck output 與 runner bridge 行為不變。Run history comparison 也已支援，但必須明確提供 `--compare-baseline-manifest` 與 `--compare-candidate-manifest` 兩個 manifest JSON 路徑，才會附加 `run-history-comparison` section。

常用命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast

.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --tab recommendation --output-dir output\qa\full_app_healthcheck_tmp --fail-fast

.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir output\qa\full_app_healthcheck_tmp --fail-fast

.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast --report-section coverage-burndown --report-section flow-diagnostics --report-section quick-gate-proposal --report-section full-release-checklist
```

## 驗證快照

本收束報告原始 E-4 驗證如下：

- Focused healthcheck metadata tests：`43 passed`
- Pytest collection：`1031 tests collected`
- Quick healthcheck runner：`Healthcheck passed`
- `py_compile`：E-4 相關 Python 檔通過
- `git diff --check`：無 whitespace error，只有 CRLF 提醒

2026-06-24 補充盤點：

- 測試 inventory 文件目前顯示：`208` 個有效測試區 Python 檔。
- 預設 pytest gate 目前顯示：`177 files / 1051 tests`。
- `healthcheck-runner-owned`：`28` files。
- `ui-healthcheck-direct-bridge`：`6` files。
- `ui-healthcheck-candidate-bridge`：`15` files。
- Runner bridge 另接 `scripts/qa_validate_update_tab.py` 作為 QA script bridge，不屬 `tests/` 208 files。

2026-06-29 補充盤點：

- `ui-healthcheck-direct-bridge`：`11` files。
- `ui-healthcheck-candidate-bridge`：`10` files。
- Runner 支援 `--tab` 分頁篩選；`update`、`research`、`recommendation`、`watchlist`、`portfolio`、`runtime` 可各自跑 full direct bridge 子集。
- MainWindow smoke 已升級為 executable opt-in / non-default；驗證過可產生 8 個頂層 tab 切換、startup / resize screenshots、viewport resize evidence 與 Update 強制合併 cancel dialog evidence。窄 viewport 目前會被 MainWindow 最小寬度限制，report 會以 `constrained_by_minimum` 呈現。

2026-06-30 補充盤點：

- `--ui-smoke` 由父 runner 呼叫隔離子程序執行，避免 PySide6 / Qt native teardown 影響 healthcheck exit code。
- `--ui-smoke-dialog-cancel` 目前只覆蓋 UpdateView 強制重新合併 cancel path；其他 dialog 仍需逐項加入。

## 交接規則

- 每個新批次先執行 `git status --short --branch`。
- 除非任務明確要求更新 QA 報告，否則不要 stage `output/qa/update_tab/` 底下 tracked 易變輸出。
- 除非後續任務明確傳入 `--ui-smoke`，否則不要啟動 MainWindow。
- 不要從本 roadmap 直接執行 migration、backfill apply、真實資料寫入或 high-risk dry-run implementation。
- 若失敗涉及 SQLite / CSV 新鮮度、schema、available date 或資料完整性，交接給 Data Audit Agent。
- 若下一步會改 runner 行為或 release blocking，先建立新的明確計畫，再編輯程式碼。
