# V1.9 Read-only Agent / MCP Evidence Access Closeout

日期：2026-07-06

## 範圍

V1.9 完成 read-only Agent / MCP evidence access v1：

- `app_module/agent_evidence_access_service.py`
  - `build_agent_permission_model()`
  - `build_ai_report_template()`
  - `AgentEvidenceAccessService.query_evidence_events()`
  - `AgentEvidenceAccessService.summarize_forward_evidence()`
  - `AgentEvidenceAccessService.query_research_runs()`
  - `AgentEvidenceAccessService.query_portfolio_review_evidence()`
- `mcp_servers/evidence_access_server.py`
  - `twstock-evidence-access` FastMCP server
  - permission model / report template / evidence / research run / portfolio review saved evidence tools
- `tests/test_v1_9_agent_evidence_access.py`
  - permission model
  - evidence events + outcomes + source trace
  - forward evidence summary
  - research run metadata read-only query
  - missing research DB no-create behavior
  - live research gap + lifecycle evidence saved-evidence-only query

## 安全邊界

- 只讀 evidence / source trace / quality / warnings / diagnostics。
- SQLite 開啟使用 `mode=ro` 與 `PRAGMA query_only=ON`。
- 缺 DB 或缺 table 只回 diagnostics，不建立檔案、不建立 schema。
- MCP server 只包裝 app-layer service，不直接操作 SQLite。
- 不寫 DB、不改策略、不改推薦分數、不下單、不建立 broker order、不套用 promote / demote / retire lifecycle action。
- AI report template 要求引用 evidence rows；LLM thesis 不得當 primary evidence。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_v1_9_agent_evidence_access.py -q -o addopts=
```

結果：`4 passed in 1.28s`

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\agent_evidence_access_service.py mcp_servers\evidence_access_server.py
```

結果：通過。

```powershell
@'
from mcp_servers.evidence_access_server import create_evidence_access_mcp_server
server = create_evidence_access_mcp_server()
print(type(server).__name__)
'@ | .\.venv\Scripts\python.exe -
```

結果：`FastMCP`。此 smoke 只建立 server 物件，不啟動 stdio loop；`TWStockConfig` 初始化會輸出目前資料根目錄 log。

```powershell
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
```

結果：`check_financial_float_boundaries.py` 與 `check_look_ahead_bias.py` 皆通過，無違規項。

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

結果：`Success: no issues found in 283 source files`

本次沒有修改 UI，因此未執行 `tests/test_ui_qt_update_view_workbench.py` 與 `scripts/qa_validate_update_tab.py`。

## 進 V2.0 前仍需補齊

- 多週 weekly evidence operations + history 實際紀錄，而不只是一筆 working-copy operating-cycle。
- Evidence Review 人工 UI smoke closeout 與多日 dry-run record。
- 真實 watchlist / portfolio workflow 樣本，補足目前 durable source gaps。
- read-only Agent report 樣本審核，確認 AI summary 能穩定引用 evidence rows、quality、warnings 與 source trace。
- 若 production scheduler 要進一步設計，需先補 explicit approval、backup、rollback 與 production write-mode boundary 文件。
