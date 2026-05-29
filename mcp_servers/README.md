# 本地 MCP Server 草稿

## technical-analysis-context

目的：讓未來對話可以直接取得專案啟動上下文，減少重複讀取大型文件的 token 成本。

入口：

- `mcp_servers/project_context_server.py`

提供工具：

- `get_twstock_config_status`：讀取 `data_module.config.TWStockConfig` 解析後的路徑與參數。
- `get_project_snapshot`：讀取 `docs/00_core/PROJECT_SNAPSHOT.md`。
- `get_project_boot_context`：一次回傳上述兩者。

執行方式：

```powershell
.\.venv\Scripts\python.exe mcp_servers\project_context_server.py
```

注意：`TWStockConfig` 初始化會沿用專案既有行為，可能建立必要資料夾與 log handler；測試或沙盒環境應使用 `DATA_ROOT`、`OUTPUT_ROOT`、`PROFILE=test` 隔離正式資料根目錄。
