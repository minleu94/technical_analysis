# Runtime Observatory 架構治理檢查表

以下規則適用於 Runtime Subsystem 與 UI 整合，確保 State Machine Observatory 維持唯讀、可追溯與 fail-closed 邊界。

## 1. 禁止依賴

- **UI Layer (`ui_qt/`)**：不得 import `json`／`os` 或直接讀寫 Runtime／scheduled 檔案；不得 import `RuntimeStore` 或 `local_file_store.py`；只能透過 `app_module.dtos.runtime_dtos` DTO 與 Qt signal 溝通。
- **Orchestration Layer (`app_module/`)**：不得 import `PySide6`、`PyQt5` 或任何 Qt-specific library；不得持有 UI formatting string（HTML／CSS）。
- **Core Subsystem Layer (`runtime/`)**：不得 import `app_module` 或 `ui_qt`；只依賴 Python standard library。

## 2. DTO 與讀取邊界

- `RuntimeSnapshotService`、`RuntimeHealthService` 與 `RuntimeEventStreamService` 是唯一可 query `IRuntimeStore` 並將 raw Runtime JSON 轉為 DTO 的 application services。
- `ScheduledOperationsStatusService` 是唯一可直接讀取 `OUTPUT_ROOT/scheduled/*/latest_status.json` 的 application service。
- `QtRuntimeBridge` 是唯一可 subscribe `EventBus` 並 emit Qt `Signal` 的元件。
- UI 元件（如 `RuntimeView`）只能接受 DTO 並純渲染，不得對 Runtime／scheduled storage 執行 I/O。

## 3. 雙觀測平面與 side-effect 禁令

- Governance Runtime（state／context／append-only event）與 Scheduled Operations（已保存 `latest_status.json`）是不同資料面；不得由任一 DTO、service 或 UI 將一方狀態映射成另一方的健康度、FSM state 或 task 成功。
- Scheduled Operations 只表達 artifact read result；不得宣稱 Windows Task Scheduler 已註冊、正在執行、`Last Result=0`，亦不得呼叫、建立、啟用、停用或重排 task。
- Runtime controller 的 poll 為唯讀：不得寫 DB、更新資料、重訓、改變 ML promotion／alpha、改寫 Runtime event、執行 Paper 操作或送單。
- `QtRuntimeBridge` 仍是 EventBus 唯一 subscriber／Qt signal translator；排程 DTO 必須經相同 bridge，不得讓 view 自讀檔案。

## 4. 時間、狀態與 fail-closed 規則

- Runtime event 缺少、無法解析或明顯在未來的時間時，禁止以「現在」補值；只有 current window 的可解析事件可觸發 `ERROR`／`HALTED`。歷史事件必須以 `historical_only`，無效時間以 `timestamp_invalid`，未來時間以 `timestamp_future` 揭露。
- Incremental event stream 讀取必須保留 `read_state`／`diagnostic`；I/O 失敗要停留在原 cursor 並發出明確診斷，不得被當成「沒有新事件」吞掉。
- 事件檔 I/O 失敗或含無法解析的行時，health 必須以 `event_log_unreadable`／`event_log_degraded` 明示，不得回傳 no events／healthy。
- status artifact 必須保留 raw status、read_state、timestamp source、source path、diagnostic。缺失／無法讀取／過期的 core artifact 為 attention，不得預設為通過；狀態時間只能採 `checked_at`／`generated_at` 或檔案修改時間，不能採市場決策日期。
- `guarded` 是安全 gate 仍有效的狀態，不是 successful promotion、formal approval 或可交易許可；ML alpha=0 必須維持既有權威。
- UI event list 只可裁切記憶體中的呈現列；不得修改底層 append-only JSONL。

## 5. 治理檢查表

- [x] DTO 與 storage format 無關。
- [x] EventBus 不依賴 `PySide6`，使用 pure Python `Callable` lists。
- [x] Qt translation layer 隔離在 `ui_qt/bridges/`。
- [x] HealthService 產生 rejection trend，並將 current／historical／invalid／future／unreadable 分開揭露。
- [x] FSM States 已完整宣告（`IDLE`、`THINKING`、`ERROR`、`RECOVERY`、`HALTED` 等）。
- [x] 兩個 DTO family 均 storage agnostic，bridge 含 scheduled signal，歷史事件不會讓 current FSM 偽為 `HALTED`。
