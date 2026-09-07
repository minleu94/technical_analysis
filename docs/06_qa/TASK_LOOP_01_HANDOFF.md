# TASK-LOOP-01 DATA 交接

## 交接狀態

本卡的隔離工程與驗收已完成。狀態 DTO、SQLite 落地、技術指標單一寫入者、唯讀狀態查詢、週末防誤收資料與離線 QA fixture 均已形成可重跑證據；正式資料、正式 availability mapping、網路下載與 candidate promotion 均未執行。本文件只代表工程驗證完成，不代表外部來源已接受或正式資料已更新。

基線與目前工作樹仍在同一個 commit：`678db2bb260bb1de5cee4a0869f4f402db3660a7`。本卡未 stage、commit 或 push。工作樹中另有其他任務的既存變更，回滾時必須依檔案 owner 分開處理。

## 變更邊界

| 檔案 | 變更 | 交接意義 |
|---|---|---|
| `app_module/dtos/update_loop_dtos.py` | 新增 | 定義來源、實際日期、品質、警告、candidate 與 read mode 的唯讀狀態 DTO；保留 dict 序列化相容層。 |
| `app_module/update_service.py` | 修改 | 在既有 dict API 補上狀態契約與 DTO wrapper；狀態檢查及來源明細不再寫入 manifest。 |
| `app_module/update_service_status_support.py` | 修改 | 以 opt-in 方式套用狀態契約，保留既有 read model 呼叫的相容結果。 |
| `scripts/qa_validate_update_tab.py` | 修改 | 使用暫存雙根建立離線 market、broker、technical 與可選 monthly fixture；加入落地與指標驗證，並在清理前關閉隔離 logger。 |
| `tests/test_update_service_status.py` | 修改 | 將來源明細契約改為驗證唯讀，不允許查詢副作用建立 manifest。 |
| `tests/test_task_loop_01_contract.py` | 新增 | 覆蓋 idempotency、broker 四欄身份鍵、週末拒收、指標父程序單一寫入者、缺 DB 唯讀狀態與 DTO 語意。 |
| `docs/06_qa/TASK_LOOP_01_HANDOFF.md` | 新增 | 本卡驗收、風險、回滾與未完成外部條件。 |

未修改白名單外檔案；`data_module/fundamental_schema.py` 僅被 QA fixture 作為隔離 schema helper 使用，沒有修改其內容，也沒有觸碰正式資料庫。

## 防禦與資料治理證據

- `check_data_status`、`check_data_overview` 與 `check_source_detail` 的查詢路徑不建立表、不修復資料、不寫入狀態 manifest；缺少 DB 的案例已由契約測試確認。
- 狀態 DTO 將來源 `actual_date` 與 `latest_date` 正規化為可比較日期；缺資料、降級、錯誤與警告不會被轉成 observed 或靜默成功。
- 雙批同步維持 SQLite idempotency；broker 的 `trade_type` 保留買超與賣超的身份鍵，技術指標由父程序集中寫入。
- 週末 CSV 在沒有官方交易 session 證據時不落地；QA 使用固定隔離日期與人工 fixture，沒有把檢查日推成交易日。
- QA 的資料與服務 artifacts 位於 `TemporaryDirectory` 的 data/output 雙根；QA 報告與日誌仍寫入既定、受忽略的 `output/qa/update_tab`。logger handler 在離開暫存根前關閉，沒有讀寫正式 Raw CSV、SQLite 或 availability 檔案。
- 本卡未新增資金、部位、PnL 或策略運算；全域金融浮點邊界與 future-function 檢查均通過。

## 驗收命令與結果

| 命令 | 結果 |
|---|---|
| `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_update_service_status.py tests\\test_update_service_status_support.py tests\\test_ui_qt_update_view_workbench.py tests\\test_technical_indicator_process_pool.py tests\\test_analysis\\test_technical_analysis.py tests\\test_task_loop_01_contract.py -q -o addopts=` | exit 0；158 passed，1 個既有 pytest cache 權限警告。 |
| `.\\.venv\\Scripts\\python.exe scripts\\qa_validate_update_tab.py` | exit 0；25 passed，0 failed，4 skipped。4 個 skip 為刻意略過真實下載與合併的既有介面案例。 |
| `.\\.venv\\Scripts\\python.exe -m py_compile app_module\\dtos\\update_loop_dtos.py app_module\\update_service.py app_module\\update_service_status_support.py scripts\\qa_validate_update_tab.py tests\\test_update_service_status.py tests\\test_task_loop_01_contract.py` | exit 0。 |
| `.\\.venv\\Scripts\\python.exe scripts\\check_financial_float_boundaries.py` | exit 0。 |
| `.\\.venv\\Scripts\\python.exe scripts\\check_look_ahead_bias.py` | exit 0。 |
| `.\\.venv\\Scripts\\python.exe -m mypy --follow-imports=skip app_module\\dtos\\update_loop_dtos.py app_module\\update_service.py app_module\\update_service_status_support.py scripts\\qa_validate_update_tab.py` | exit 0；本卡變更來源無型別錯誤。 |
| `git diff --check` | exit 0；僅有既有 CRLF 轉換提示。 |

全域 mypy 命令已執行但目前 exit 1，唯一報告為其他任務檔案 `app_module/backtest_service.py:403` 的 `Path | None` 型別賦值錯誤。本卡 DTO 的 tuple warning 已改為明確 `tuple[str, ...]`，不得為此跨越 owner 邊界修改回測檔案；請由該檔案 owner 在整合 gate 處理。

## 回滾清單與步驟

| 檔案 | 回滾方式 | 風險 |
|---|---|---|
| `app_module/dtos/update_loop_dtos.py` | 確認沒有其他 owner 依賴後移除新增檔，並同步回復本卡對 service 的 import。 | 服務狀態契約與新測試會失效，需同批回復。 |
| `app_module/update_service.py`、`app_module/update_service_status_support.py` | 先保存本卡限定 hunk，再以 `git apply --reverse --check` 驗證並逐 hunk 回復。 | 不得整檔 checkout，以免覆蓋其他 agent 變更。 |
| `scripts/qa_validate_update_tab.py` | 僅反向套用本卡 fixture／handler cleanup hunk。 | QA 會重新依賴外部或空資料根，可能恢復誤報。 |
| `tests/test_update_service_status.py`、`tests/test_task_loop_01_contract.py` | 既存測試逐 hunk 回復；新增契約測試可在確認無依賴後移除。 | 會失去唯讀與週末防禦回歸保護。 |
| `docs/06_qa/TASK_LOOP_01_HANDOFF.md` | 確認沒有整合引用後移除本文件。 | 交接證據與回滾說明遺失。 |

回滾前先檢查 `git status --short` 與各 owner 的未提交 diff；不得使用整體 `checkout`、`clean`、資料重建或正式資料 restore。回滾後重跑本卡 focused pytest 與 QA，並再次確認正式資料根沒有新檔案或時間戳變更。

## 未完成與外部條件

- 真實 TWSE／TPEX／broker 網路下載與正式資料接受不在本卡執行範圍；QA 的 4 個 skip 必須保留明示，不能解讀為來源健康通過。
- 全域 mypy 仍受其他任務的 `app_module/backtest_service.py:403` 阻擋；TASK-01 不得修改該檔案。
- 正式更新、candidate promotion、availability merge 與 process-pool production enablement 均未執行，需另由相應 owner 依 gate 審核。
