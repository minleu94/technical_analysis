# Shared AI Skills Registry

> Codex 與 Antigravity 共用的技能總目錄索引。
> 本文件只負責「角色選擇、流程導引與共享上下文入口」，不保存第二套 Agent 規則，避免平行權威與上下文污染。

## 1. 定位

本文件是 Shared AI Layer 的技能入口。

- `docs/agents/*.md` 是唯一角色與規則權威。
- `docs/agents/skills/*.md` 只保存跨 AI 協作流程、交接規則與輕量調用指南，不得重新定義既有 Agent。
- `docs/agents/antigravity/` 與 `.agent/rules/` 僅為 Antigravity 適配摘要，不得維護平行規則。
- 若任何適配層與 `docs/agents/` 衝突，以 `docs/agents/` 為唯一真相。

## 2. 固定必讀文件

任何 AI 在使用技能前，必須先閱讀：

1. `docs/agents/README.md`
2. `docs/agents/shared_context.md`
3. `docs/agents/git_exclusions.md`
4. `docs/00_core/PROJECT_SNAPSHOT.md`
5. `docs/00_core/DEVELOPMENT_ROADMAP.md`
6. `docs/00_core/ROADMAP_6M_ENGINEERING.md`（涉及方向、優先順序或大型規劃時）
7. `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`（涉及舊工作承接或 Phase Gate 時）
8. `docs/07_guides/APPLICATION_MANUAL.md`（涉及 UI、使用流程、參數、結果判讀或安全限制時）
9. 與任務對應的 Agent 權威文件：
   - 架構判斷：`docs/agents/tech_lead.md`
   - 受控實作：`docs/agents/execution_agent.md`
   - 文檔同步：`docs/agents/documentation_agent.md`
   - 資料驗證：`docs/agents/data_audit_agent.md`
   - 清理整理：`docs/agents/data_cleanup_agent.md`
   - 測試驗證：`docs/agents/testing_qa_agent.md`

## 3. 權威 Agent 與協作流程

| 任務類型 | 權威文件 / 流程文件 | 用途 |
|---|---|---|
| 團隊分流、交接、角色選擇 | `docs/agents/skills/team.md` | Task Intake、Role Routing、Handoff Pack |
| 量化合規檢查（Float / 未來函數） | `docs/agents/skills/quant_defense_guard.md` | 量化精度防禦與未來函數審查技能 |
| 架構判斷、風險雷達、是否該做 | `docs/agents/tech_lead.md` | Tech Lead 權威角色 |
| 明確 scope 的實作或 bugfix | `docs/agents/execution_agent.md` | Execution 權威角色 |
| 測試路由、功能驗證、測試矩陣與 healthcheck 結果解讀 | `docs/agents/testing_qa_agent.md` | Testing / QA 權威角色，負責測試路由與結果解讀 |
| 實作完成後實際執行驗證命令、git safety、交付前檢查 | `docs/agents/execution_agent.md` + `docs/agents/shared_context.md` | 依專案驗證與安全規則執行交付 |
| 文檔 coverage、索引、Snapshot / Roadmap Hub / 6M Roadmap / Carryover / Architecture / Manual 同步 | `docs/agents/documentation_agent.md` | Documentation 權威角色 |
| 資料完整性、SQLite / CSV 一致性 | `docs/agents/data_audit_agent.md` | Data Audit 權威角色 |
| 清理、移除、死碼、依賴精簡 | `docs/agents/data_cleanup_agent.md` | Cleanup 權威角色 |

## 4. 載入規則

### 小任務

小型文檔更新、簡單查詢、單一低風險修正：

1. 讀固定必讀文件。
2. 只載入與任務直接相關的一份權威 Agent 文件；需要交接時再載入 `docs/agents/skills/team.md`。
3. 可用對話摘要交接，不強制寫入 shared state。

### 中大型任務

跨多檔案、跨模組、需要多輪交接或需要 Codex / Antigravity 輪流處理：

1. 先載入 `docs/agents/skills/team.md`。
2. 由 Team skill 判斷後續應使用哪一份權威 Agent 文件。
3. 必須定義 Scope In / Scope Out。
4. 必須在交接時更新 shared state。

### 高風險任務

涉及下列任一情況，必須使用嚴格流程：

- SQLite 寫入、migration、schema 變更、CSV fallback。
- 策略、回測、推薦、績效、風控、資金、倉位。
- 正式資料根目錄。
- 大規模重構、刪除、清理。
- 分支清理、commit、stage、push。

嚴格流程：

1. 載入 `docs/agents/skills/team.md`。
2. 依任務載入對應權威 Agent 文件，例如 `docs/agents/tech_lead.md`、`docs/agents/data_audit_agent.md`、`docs/agents/execution_agent.md`、`docs/agents/documentation_agent.md` 或 `docs/agents/testing_qa_agent.md`。
3. 寫入 `docs/agents/shared_state/active_task.yaml`。
4. 交接時追加 `docs/agents/shared_state/handoff_log.md`。
5. 完成前必須執行驗證與風險檢查。

## 5. 全技能硬性約束

所有技能都必須遵守：

- 一律使用繁體中文。
- 不得破壞正式資料。
- 資料位置以 `data_module/config.py` 的 `TWStockConfig` 為準。
- 不得覆寫使用者、Codex、Antigravity 或其他 Agent 的未提交變更。
- 不得擴張未被要求的 scope。
- 修改功能時必須檢查文檔同步需求。
- 文件判讀採 Scoped SSOT：目前狀態看 Snapshot，未來工程路線看 6M Roadmap，舊工作承接看 Legacy Carryover，架構看 system architecture，操作看 Application Manual，歷史看 archive。
- 使用者可見流程、參數、結果判讀或安全限制改變時，必須同步 Application Manual。
- Stage / commit 前必須先讀 `docs/agents/git_exclusions.md`。
- 涉及量化核心計算時，嚴禁新增裸 `float`。
- 涉及策略、回測、推薦、績效、風控時，必須先做 Look-ahead bias 自查。

## 6. 不建立第二權威

禁止在 `docs/agents/skills/` 中建立與既有 Agent 同名、同職責的完整規則文件，例如：

- `docs/agents/skills/tech_lead.md`
- `docs/agents/skills/execution.md`
- `docs/agents/skills/documentation.md`
- `docs/agents/skills/data_audit.md`
- `docs/agents/skills/data_cleanup.md`

若未來需要輕量操作卡，必須明確標示為「調用卡」或「流程卡」，且只能指回 `docs/agents/*.md` 權威文件，不得複製或改寫角色規則。

## 7. 本地輔助 MCP 伺服器

專案配備以下 Python 版本地 MCP 伺服器（基於 `fastmcp`）。程式碼存在不代表目前 Agent session 已載入；修改 MCP 設定後必須重啟 Codex / Antigravity，再由工具清單確認：

- **`twstock-context`** (`mcp_servers/project_context_server.py`)：提供專案啟動上下文與 `TWStockConfig` 配置快照。
- **`twstock-sqlite-inspector`** (`mcp_servers/sqlite_server.py`)：提供強制唯讀 SQLite 查詢、執行計劃審查與 Schema 檢索；最多回傳 1000 列。它可協助診斷索引與查詢計劃，但不保證消除 database lock。
- **`twstock-git-assistant`** (`mcp_servers/git_server.py`)：提供 Git 工作區狀態、Diff 與 Log 輔助；Git 失敗會明確拋錯，Diff 輸出設有安全上限。

本機註冊位置：

- Codex：`C:\Users\archi\.codex\config.toml`
- Antigravity：`C:\Users\archi\.gemini\config\mcp_config.json`

## 8. 更新記錄

- 2026-06-09：改為「索引 + 分冊」架構，將本文件降級為短索引，技能細則移至 `docs/agents/skills/`。
- 2026-06-09：修正為「既有 Agent 單一權威制」，`skills/` 僅保留團隊協作與交接流程，不建立同名角色分冊。
- 2026-06-13：更新固定必讀與文件同步描述，對齊 Snapshot / Roadmap Hub / 6M Roadmap / Architecture 的 Scoped SSOT。
- 2026-06-13：補入 Legacy Carryover 與 Application Manual 的條件式必讀及權威範圍。
- 2026-06-14：新增量化防禦技能 `quant_defense_guard.md` 與本地輔助 MCP 伺服器說明。
- 2026-06-23：新增 Testing / QA Agent 至權威與協作流程，指向 `docs/agents/testing_qa_agent.md`。
