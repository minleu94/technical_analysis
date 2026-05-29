# PATCH_MEMO

> openmarkets / yahoo-finance MCP 相容性修補備忘錄。若未來重建 `.venv`，請依本檔重新套用。

## 背景

`mcp-server-yfinance` 依賴 `openmarkets`。目前環境使用 Python 3.11、Pydantic 2、FastMCP 3.x 時，`openmarkets` 會遇到兩個問題：

1. `openmarkets.schemas.technical_analysis` 使用 `typing.TypedDict`，Pydantic 2 在 Python 3.11 會要求改用 `typing_extensions.TypedDict`，否則 MCP server 註冊工具時會失敗。
2. `openmarkets` 以 stdio transport 啟動 MCP server 時，FastMCP banner / logging 可能寫到 stdout，污染 JSON-RPC stdio 通道，造成 client 出現 `Failed to parse JSONRPC message from server`。

## 修補內容

### 1. TypedDict 相容性

檔案：

`.venv/Lib/site-packages/openmarkets/schemas/technical_analysis.py`

修補行：

```python
from typing import Annotated

from typing_extensions import TypedDict
```

也就是把原本的：

```python
from typing import Annotated, TypedDict
```

改成由 `typing_extensions` 匯入 `TypedDict`。

### 2. stdio log / banner 污染與 yfinance 快取

檔案：

`.venv/Lib/site-packages/openmarkets/core/server.py`

修補行：

```python
import logging
import os
import sys
```

以及 `run_stdio_server()` 內：

```python
    try:
        logging.disable(logging.CRITICAL)
        cache_dir = os.environ.get("YFINANCE_CACHE_DIR")
        if cache_dir:
            import yfinance.cache as yfcache

            os.makedirs(cache_dir, exist_ok=True)
            yfcache.set_cache_location(cache_dir)
        mcp.run(show_banner=False)
```

目的：

- 禁用 stdio MCP server 的 logging，避免 stdout 混入非 JSON-RPC 訊息。
- 強制 `show_banner=False`，避免 FastMCP banner 污染通道。
- 若有設定 `YFINANCE_CACHE_DIR`，讓 yfinance 使用可寫快取目錄，避免 `unable to open database file`。

## Codex MCP 設定建議

`C:/Users/archi/.codex/config.toml` 的 `yahoo-finance` MCP 建議使用隔離 cwd 與環境變數：

```toml
[mcp_servers.yahoo-finance]
enabled = true
command = 'C:\Projects\PythonProjects\technical_analysis\.venv\Scripts\python.exe'
args = ["-m", "mcp_server_yfinance"]
cwd = 'C:\Users\archi\.codex\tmp'
startup_timeout_sec = 120

[mcp_servers.yahoo-finance.env]
TRANSPORT = "stdio"
FASTMCP_SHOW_SERVER_BANNER = "false"
FASTMCP_LOG_LEVEL = "ERROR"
FASTMCP_LOG_ENABLED = "false"
FINMIND_TOKEN = ""
YFINANCE_CACHE_DIR = 'C:\Projects\PythonProjects\technical_analysis\.cache\yfinance-mcp'
```

重點：

- `cwd` 不要指向 repo 根目錄，避免 `openmarkets` 讀到 repo `.env` 裡的 `FINMIND_TOKEN`。
- `FINMIND_TOKEN = ""` 用來強制清空外部同名環境變數。
- `YFINANCE_CACHE_DIR` 指到 repo 內可寫快取目錄。

## 重建環境後驗證

重建 `.venv` 並重套修補後，使用 MCP client 檢查：

- `list_tools` 應成功回傳約 71 個工具。
- 工具清單應包含 `get_history`。
- `call_tool("get_history", {"ticker": "2330.TW", "period": "5d", "interval": "1d"})` 應可回傳台積電日線資料。
