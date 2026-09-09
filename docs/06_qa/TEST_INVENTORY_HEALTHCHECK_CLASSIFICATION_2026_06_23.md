# 測試清冊與 Healthcheck 執行邊界

> 本文件只維護目前分類摘要；逐檔清單以 `qa/full_app_healthcheck/test_inventory.py` 為準。歷史執行紀錄不可當作本次通過證據。

## 2026-09-08 machine refresh

Current filesystem Python files: `777`

| 分類 | 數量 |
|---|---:|
| `general-unit-keep-in-pytest` | 148 |
| `governance-doc-tooling` | 147 |
| `healthcheck-runner-owned` | 29 |
| `legacy-or-low-priority` | 3 |
| `manual-only` | 14 |
| `service-oracle-data-market` | 114 |
| `service-oracle-portfolio-decision-runtime` | 118 |
| `service-oracle-recommendation` | 20 |
| `service-oracle-research-backtest` | 72 |
| `slow-e2e-or-environment` | 3 |
| `ui-healthcheck-candidate-bridge` | 28 |
| `ui-healthcheck-direct-bridge` | 12 |
| `write-risk-dry-run-required` | 69 |

- 預設收集檔案：750；support：4；不收集：23。
- 歷史對照：本段更新前的機器摘要曾記錄總數 `743`、general `147`、governance `138`、data `110`、portfolio-runtime `106`、research-backtest `71`、UI candidate `26`、write-risk `64`；以上數字保留作舊 QA 快照，不代表目前清冊。
- 本次 machine refresh 以實際 `tests/` 目錄取得 31 份新增測試並依責任分類登錄；`run_test_inventory_audit()` 的 missing/stale 均為零。新增測試不因此進入 direct bridge。
- 本輪清理前實測為 748 個 Python 檔、4639 測項；舊 679 檔／4005 測項是較早檢查點。
- 本輪補登 69 個檔案（含既有 ml_teacher_fixture 支援檔），刪除七份一次性診斷，兩份欄位測試合為參數化雙入口測試。
- 2026-09-08 最終 collection 為 4,655；全量 pytest 為 4,652 passed、3 skipped；missing／stale／count drift 為零。見 [LUNA 三線整合驗收](LUNA_INTEGRATION_CLOSEOUT_2026_09_08.md)；[前次查核](PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md) 保留為歷史。

## Runner 規則

- quick 模式只允許已明確註冊的快速、非破壞 UI 檢查。
- direct bridge 的允許清單仍只有原先 12 份 UI 測試；candidate、service oracle 與新登錄測試不自動成為 direct bridge。
- full mode 也不是執行正式資料 migration、harvester 或大型外部請求的授權。
- manual-only、write-risk-dry-run-required 不得直接進非破壞 runner；僅在測試明確使用 tmp_path、mock 或 dry-run 時定向執行。
- high-risk-dry-run 只驗證 dialog、cancel、dry-run 與 mock service 未被呼叫。
- bridge 保留 covered_healthcheck_ids、covered_flow_ids；同一功能在不同層級的 oracle 與 UI 測試不可只因相似就刪除。
- tests/manual 與 tests/scripts 不由預設 pytest 收集；保留的 14 份 manual、6 份 scripts 不保證可直接執行。

## 使用與驗證

```powershell
.\.venv\Scripts\python.exe scripts/audit_test_inventory.py --output-json output/qa/test_inventory.json
.\.venv\Scripts\python.exe -m pytest tests/test_audit_test_inventory.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=
```

執行前將 DATA_ROOT、OUTPUT_ROOT 指向本次隔離目錄；UI 測試使用 QT_QPA_PLATFORM=offscreen。新增任何 tests 下的 Python helper 也須登錄，並正確標為 support。

## 歷史與整併

舊文件反覆附加 2026-06-23、08-14、08-28 的清單、數量與中途測試結果，形成多份「current」敘述。本輪收斂成單一機器摘要，原文可由基線 `71500ef6fc834da285c19255e5c03f1846412329` 的同路徑或本輪精確備份還原。沒有刪除獨立測試的斷言來迎合清冊。

七份 retired diagnostics 的精確檔名、原因與回滾，統一保存在[整併查核](PROJECT_CONSOLIDATION_REVIEW_2026_09_07.md)；不再維護另一份重複 README 或當前檔案列表。
