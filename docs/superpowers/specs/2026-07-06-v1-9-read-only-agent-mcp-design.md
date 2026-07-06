# V1.9 Read-only Agent MCP Evidence Access Design

## 目標

V1.9 建立唯讀 Agent / MCP evidence access surface，讓 Codex、Antigravity 或其他受控 agent 可以查詢 evidence rows、research run metadata 與 portfolio review 相關保存證據，並用固定報告模板引用資料品質、warning 與 source trace。

這一版只交付查詢與報告約束，不交付 AI 推薦、DB 寫入、策略改動、下單、生命週期自動化或 production scheduler。

## 範圍

第一段交付 app-layer 唯讀查詢服務：

- 新增 `app_module/agent_evidence_access_service.py`。
- 使用 `ReadOnlyEvidenceEventRepository` 與 SQLite `mode=ro` / `PRAGMA query_only=ON` 查詢資料。
- 支援 evidence events、forward evidence summary、research run metadata、portfolio review saved evidence 查詢。
- 缺 DB 或缺 table 時回傳 diagnostics，不建立檔案、不建立 schema。

第二段交付 MCP tool surface：

- 新增 `mcp_servers/evidence_access_server.py`。
- 提供 permission model、AI report template、evidence query、research run query、portfolio review evidence query。
- 工具說明明確標示 read-only、evidence-only、not trading advice。

第三段交付文件與 QA closeout：

- 更新 MCP README、Architecture、Manual、Snapshot、Roadmap、Version Roadmap 與 Documentation Index。
- 新增 V1.9 QA closeout，列出 focused pytest、py_compile、quant guard、mypy 結果。

## 權限模型

Allowed：

- 讀取 evidence event、forward performance summary、research run metadata。
- 讀取已保存的 live research gap / lifecycle evidence rows。
- 產生引用 evidence rows 的研究報告草稿。

Denied：

- 寫入 SQLite、建立 schema、刪改資料或重建資料。
- 修改策略、推薦、分數、portfolio lifecycle 或 scheduler 狀態。
- 下單、送單、模擬真實券商流程或輸出買賣指令。
- 把 LLM thesis 當成 primary evidence。

## Evidence Query Schema

Evidence / Research Run / Portfolio Review 查詢輸出都必須包含：

- `access_boundary`: read-only / evidence-only 邊界。
- `filters`: 呼叫端使用的查詢條件。
- `rows` 或具名 row collection。
- `quality` / `warnings` / `source_trace` 相關欄位。
- `diagnostics`: 缺檔、缺 table、查詢限制或解析警示。
- `limitations`: 不可用於投資建議、不可視為策略變更或交易指令。

## No-look-ahead 自查

V1.9 不計算新訊號、不重跑回測、不讀未來價格。查詢服務只讀取已保存 evidence row 與 metadata；若呼叫端指定 `start_date` / `end_date` / `decision_date`，服務只做查詢過濾，不推導未來績效。

## 風險與防線

- MCP server 只暴露 service query，不暴露 generic SQL write path。
- Research DB 與 evidence DB 以 SQLite read-only URI 開啟。
- 缺 DB / table 時回傳 diagnostics，避免為了查詢而建立 schema。
- 報告模板要求引用 evidence row、source trace 與 data quality，不允許輸出「買進 / 賣出 / 加碼 / 減碼」式操作指令。

## 驗收

- Focused pytest 覆蓋 permission model、evidence events with outcomes、missing DB no-create、research run metadata、portfolio review saved evidence。
- `py_compile` 覆蓋新增 Python 檔。
- `quant_guard_linter.py` 通過，確認未新增金融核心裸 `float` 或 look-ahead AST 違規。
- `mypy` 覆蓋專案指定範圍。
