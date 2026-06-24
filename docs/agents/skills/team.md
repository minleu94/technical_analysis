# Team Skills

> 團隊協作分冊。
> 用於 Codex、Antigravity 與人類調度者之間的任務分流、角色選擇與交接管理。

## 1. 分冊定位

本分冊只處理「團隊協作流程」，不處理具體實作細節。

適用於：

- 新任務開始前的任務分流。
- 判斷應啟用哪個 Agent 角色。
- 判斷是否需要 Tech Lead、Data Audit、Testing / QA、Execution 或 Documentation。
- Codex 與 Antigravity 之間的交接。
- 中大型任務與高風險任務的狀態管理。

## 2. 必讀文件

使用本分冊前，必須先閱讀：

1. `docs/agents/README.md`
2. `docs/agents/shared_context.md`
3. `docs/agents/git_exclusions.md`
4. `docs/00_core/PROJECT_SNAPSHOT.md`
5. `docs/00_core/DEVELOPMENT_ROADMAP.md`

若涉及技術方向、Roadmap、架構邊界或中高風險任務，額外閱讀：

6. `docs/00_core/ROADMAP_6M_ENGINEERING.md`
7. `docs/01_architecture/system_architecture.md`

若涉及交接，額外閱讀：

8. `docs/agents/shared_state/active_task.yaml`
9. `docs/agents/shared_state/handoff_log.md`

若需要判斷任務類型，依情況閱讀對應的權威 Agent 文件：

- `docs/agents/tech_lead.md`
- `docs/agents/execution_agent.md`
- `docs/agents/documentation_agent.md`
- `docs/agents/data_audit_agent.md`
- `docs/agents/data_cleanup_agent.md`
- `docs/agents/testing_qa_agent.md`

## 3. 協作原則

- 人類調度者擁有最終決策權。
- Codex 與 Antigravity 使用同一套 `docs/agents/` 權威規則。
- `docs/agents/antigravity/` 與 `.agent/rules/` 只作為 Antigravity 適配摘要。
- 不允許 Codex 與 Antigravity 各自維護平行角色規則。
- 小任務可口頭交接。
- 中大型任務、高風險任務、SQLite 寫入、量化核心計算，必須寫入 shared state。
- 任何 AI 不得覆寫另一個 AI 或使用者的未提交變更。

## 4. Skill：TEAM - Task Intake & Role Routing

### 適用場景

用於任務開始時，判斷任務類型、風險等級、應啟用的 Agent 角色與後續技能分冊。也包括判斷是否適用於：
- 測試路由、功能驗證、feature-to-test matrix 判讀。
- Full App Healthcheck / healthcheck runner 結果解讀。
- 為 Tech Lead 準備測試證據。

### 硬性約束

- 不得直接進入實作。
- 不得修改檔案。
- 必須定義 Scope In 與 Scope Out。
- 必須判斷風險等級。
- 必須指定建議角色。
- 資訊不足時，列出「需要確認事項」並停止。
- 若任務屬於中大型或高風險，必須要求更新 `active_task.yaml`。
- 若任務涉及 SQLite 寫入或量化核心計算，必須升級為高風險流程。

### 輸出格式

```markdown
## 任務入口判斷

### 任務目標

- 

### Scope In

- 

### Scope Out

- 

### 風險等級

- 等級：Low / Medium / High
- 理由：

### 建議啟用角色

- Primary Role：
- Review Role：
- Documentation Role：
- Data / Quant Role：

### 建議載入文件

- 

### 是否需要 Shared State

- `active_task.yaml`：需要 / 不需要
- `handoff_log.md`：需要 / 不需要
- 理由：

### 需要確認事項

- 
```

### 角色選擇規則

| 任務特徵 | 建議角色 | 權威文件 |
|---|---|---|
| 是否該做、架構選型、風險判斷 | Tech Lead | `docs/agents/tech_lead.md` |
| 明確 scope 的實作或 bugfix | Execution | `docs/agents/execution_agent.md` |
| 文檔 coverage、索引、Snapshot / Roadmap Hub / 6M Roadmap / Architecture 同步 | Documentation | `docs/agents/documentation_agent.md` |
| 資料完整性、資料對比、SQLite / CSV 一致性 | Data Audit | `docs/agents/data_audit_agent.md` |
| 清理、移除、死碼、依賴精簡 | Cleanup | `docs/agents/data_cleanup_agent.md` |
| 測試路由、功能驗證、QA healthcheck 結果解讀、feature-to-test matrix 判讀 | Testing / QA | `docs/agents/testing_qa_agent.md` |
| 實作完成後實際執行驗證命令、git safety、交付前檢查 | Execution | `docs/agents/execution_agent.md` 與 `docs/agents/shared_context.md` |
| Codex / Antigravity 交接 | Orchestrator | `docs/agents/skills/team.md` |

### 風險分級規則

Low：

- 單一文件說明調整。
- 不影響程式碼。
- 不涉及資料、SQLite、量化邏輯或 Git 操作。

Medium：

- 修改多個文件。
- 修改非核心程式碼。
- 需要測試但不涉及正式資料或金融核心計算。
- 需要 Codex 與 Antigravity 交接。

High：

- 涉及 SQLite 寫入、migration、schema、CSV fallback。
- 涉及正式資料根目錄。
- 涉及策略、回測、推薦、績效、風控、資金、倉位。
- 涉及刪除、清理、大規模重構。
- 涉及 stage、commit、push、branch 清理。
- 任何無法確認不會破壞資料或不會引入 Look-ahead bias 的任務。

## 5. Skill：TEAM - Handoff Pack

### 適用場景

用於 Codex 與 Antigravity 交接、AI 暫停任務、任務轉交人類決策、或高風險任務進入下一階段前。

### 硬性約束

- 不得省略未完成事項。
- 不得把未執行驗證描述成已通過。
- 必須列出已修改檔案與未修改但參考過的文件。
- 必須標示下一位 AI 的安全接手點。
- 中大型與高風險任務必須更新 shared state。
- 若涉及量化或 SQLite，必須明確填寫安全檢查狀態。
- 若工作區有非本任務變更，必須明確標示，不得清理或覆寫。

### 輸出格式

```markdown
## AI 交接包

### 交接方向

- From：
- To：
- 交出角色：
- 接手角色：

### 任務摘要

- 任務 ID：
- 任務名稱：
- 目前狀態：planning / in_progress / blocked / review / verification / documentation / done

### Scope In

- 

### Scope Out

- 

### 已完成事項

- 

### 已讀取或參考文件

- 

### 已修改或新增檔案

- 

### 已執行命令與結果

| 指令 | 結果 | 備註 |
|---|---|---|
|  |  |  |

### 驗證狀態

- pytest：not_run / pass / fail / not_required
- QA script：not_run / pass / fail / not_required
- mypy：not_run / pass / fail / not_required
- py_compile：not_run / pass / fail / not_required
- 其他：

### 資料與量化安全狀態

- 是否涉及 SQLite 寫入：是 / 否
- 是否涉及 CSV fallback：是 / 否
- 是否涉及正式資料根目錄：是 / 否
- 是否涉及策略 / 回測 / 推薦 / 績效 / 風控：是 / 否
- Look-ahead bias 自查：not_required / pending / pass / fail
- 裸 float / Decimal / 整數基點檢查：not_required / pending / pass / fail

### 文檔同步狀態

- 是否需要更新文檔：是 / 否
- 需要更新：
- 已更新：
- 尚未更新原因：

### Git / 工作區狀態

- 是否檢查 dirty tree：是 / 否
- 非本任務變更：
- 本任務變更：
- 不應 stage 的檔案：

### 阻塞與風險

- 

### 下一步建議

1. 
2. 
3. 

### 安全接手點

下一位 AI 應從這裡開始：

> 
```

## 6. Shared State 使用規則

### 可口頭交接

以下情況允許只在對話中摘要：

- 單一低風險問題回答。
- 單一 Markdown 小修。
- 不涉及程式碼、不涉及資料、不涉及 Git。
- 不需要另一個 AI 接手。

### 必須更新 `active_task.yaml`

以下情況必須更新：

- 中大型任務。
- 需要 Codex 與 Antigravity 輪流處理。
- 涉及多個模組或多個文件。
- 涉及 SQLite 寫入、migration、schema、CSV fallback。
- 涉及策略、回測、推薦、績效、風控。
- 涉及正式資料根目錄。
- 涉及刪除、清理、大規模重構。
- 任務被阻塞，需要之後恢復。

### 必須追加 `handoff_log.md`

以下情況必須追加：

- Codex → Antigravity。
- Antigravity → Codex。
- AI → Human，需要人類決策。
- 高風險任務進入下一階段。
- 任務暫停但尚未完成。
- 完成前需要 Testing / QA Agent、Reviewer 或交付前驗證接手。

## 7. 與權威 Agent 文件的銜接

Team 分冊只負責分流與交接。後續應依任務載入既有權威 Agent 文件：

- 架構風險：`docs/agents/tech_lead.md`
- 受控實作：`docs/agents/execution_agent.md`
- 文檔同步：`docs/agents/documentation_agent.md`
- 資料驗證與 SQLite / CSV 一致性：`docs/agents/data_audit_agent.md`
- 清理整理：`docs/agents/data_cleanup_agent.md`
- 測試路由、功能驗證、healthcheck 結果解讀：`docs/agents/testing_qa_agent.md`

`docs/agents/skills/` 不得建立第二套 Tech Lead、Execution、Documentation、Data Audit 或 Cleanup 規則。若需要額外輕量指南，只能以調用卡形式指回上述權威文件。

若任務同時符合多個類型，優先順序為：

1. 高風險安全檢查
2. Tech Lead 風險判斷
3. Data / Quant 稽核
4. Testing / QA Agent 測試路由與結果解讀
5. Execution
6. Documentation
7. Handoff

## 8. 更新記錄

- 2026-06-09：建立 Team Skills 分冊草案，定義 Task Intake、Role Routing、Handoff Pack 與 shared state 分級規則。
- 2026-06-09：調整為既有 Agent 單一權威制，Team 分冊只負責分流與交接，後續一律指回 `docs/agents/*.md` 權威角色文件。
- 2026-06-23：新增 Testing / QA Agent 任務分流、分工與交接規則，確立其測試路由與結果解讀之單一權威。
