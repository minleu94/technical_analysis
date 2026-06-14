# 本地 MCP Servers

本目錄提供三個 FastMCP 3.x stdio server。它們是本機輔助工具，不取代 repo 的 Agent 規範、測試或人工 code review。

## Servers

- `project_context_server.py`：讀取 `TWStockConfig` 路徑快照與 `PROJECT_SNAPSHOT.md`。
- `sqlite_server.py`：強制 `mode=ro` 與 `query_only` 的 SQLite 查詢、Schema 和 Query Plan；單次最多 1000 列。
- `git_server.py`：唯讀 Git status、diff 與 log；失敗會拋錯，輸出有長度上限。

## 本機註冊

已使用絕對 Python / script 路徑註冊於：

- Codex：`C:\Users\archi\.codex\config.toml`
- Antigravity：`C:\Users\archi\.gemini\config\mcp_config.json`

設定異動後必須重啟對應應用。舊 session 不會熱載入新增 MCP 工具。

## 手動啟動

```powershell
.\.venv\Scripts\python.exe mcp_servers\project_context_server.py
.\.venv\Scripts\python.exe mcp_servers\sqlite_server.py
.\.venv\Scripts\python.exe mcp_servers\git_server.py
```

## 安全限制

- SQLite MCP 的資料庫連線強制唯讀，但仍應使用窄查詢與必要的 `LIMIT`。
- WAL 只能降低讀寫阻塞，不代表永遠不會出現 lock。
- Git MCP 不提供 add、commit、checkout、reset、clean 或 push。
- `TWStockConfig` 初始化沿用既有行為；測試環境應以 `DATA_ROOT`、`OUTPUT_ROOT`、`PROFILE=test` 隔離正式資料。
