# Agent 總覽

> **一切從這裡開始** - 這是所有 Agent 的入口文檔

## 📋 目錄

本資料夾包含專案中使用的各種 AI Agent 定義與 Prompt 模板。每個 Agent 都有其特定的職責與使用場景。

### 核心 Agent

1. **[技術總管 Agent](./tech_lead.md)** (`tech_lead.md`)
   - 負責技術決策、架構方向與風險評估
   - 提供是否應該實作的判斷與建議（不進行實作）

2. **[資料對比/驗證 Agent](./data_audit_agent.md)** (`data_audit_agent.md`)
   - 資料完整性驗證
   - 資料一致性檢查
   - 資料品質評估

3. **[專案清理 Agent](./data_cleanup_agent.md)** (`data_cleanup_agent.md`)
   - 識別並清理冗餘代碼
   - 移除未使用的檔案與依賴
   - 優化專案結構

4. **[執行型 Prompt Agent](./execution_agent.md)** (`execution_agent.md`)
   - 僅依照明確指令執行指定任務（不補步驟、不最佳化）
   - 指令不完整必須先列「需要確認事項」
   - 產出可回滾的變更清單（檔案 / diff / steps）

5. **[文檔覆蓋完整性 Agent](./documentation_agent.md)** (`documentation_agent.md`)
   - 確保文件與實際系統行為、專案狀態、使用流程完全一致
   - 識別所有需要更新的文件（包括容易被忽略的）
   - 檢查 Snapshot / Index / Roadmap 一致性

### 共用資源

- **[共用上下文](./shared_context.md)** (`shared_context.md`)
  - 所有 Agent 必須遵守的前提條件
  - 專案規範與約定
  - 不可違背的規則
- **[Git 排除與不應提交清單](./git_exclusions.md)** (`git_exclusions.md`)
  - 說明哪些本機輸出、暫存目錄與 tracked QA output 不應被順手 stage
- **[Shared AI Skills Registry](./skills_registry.md)** (`skills_registry.md`)
  - Codex 與 Antigravity 共用的角色選擇、流程導引與 shared context 入口
  - 僅指向既有 Agent 權威文件，不重新定義角色規則
- **[Antigravity Agent 入口](./antigravity/README.md)** (`antigravity/README.md`)
  - 給 Antigravity 使用的角色分流與必讀規則
  - 與 repo 根目錄 `GEMINI.md`、`.agent/rules/` 搭配使用

## 目前專案現況速記

- 主要 UI 是 `ui_qt/`，入口為 `python ui_qt/main.py`，使用 PySide6。
- 目前可見 UI 功能包含：數據更新工作台、市場觀察（大盤/強弱股/強弱產業/主力流向）、策略回測、推薦分析、觀察清單與 Runtime Observatory。
- 推薦組合回測 MVP 已完成：推薦 Tab 可把 Profile/Config 送到回測 Tab，由回測頁在歷史日期重播推薦邏輯，評估整組推薦組合而不是只回測當下股票清單。
- 處理推薦 replay / backtest 日期時，必須留意台股資料 `日期` 欄可能是數字型 `YYYYMMDD`，請使用共用解析工具避免誤判成 1970 epoch。
- 資料位置由 `data_module/config.py` 的 `TWStockConfig` 管理；正式資料根目錄預設為 `D:/Min/Python/Project/FA_Data`，可由 `DATA_ROOT` 覆蓋。
- repo 內沒有固定的正式 `data/` 目錄時，不代表資料不存在；Agent 必須先查設定，不可憑相對路徑推斷。
- Codex 自動入口是 repo 根目錄 `AGENTS.md`；本目錄保存完整 Agent 職責與 Prompt 模板。

## ⛔ 強制流程（所有 Agent 必須遵守）

### 全 Agent 必讀文件清單（固定順序）

**任何 Agent 在執行任務前，必須依序閱讀：**

1. `docs/agents/README.md` - Agent 總覽（本文件）
2. `docs/agents/shared_context.md` - 共用上下文（不可違背前提）
3. `docs/agents/git_exclusions.md` - Git 排除與不應提交清單
4. `docs/00_core/PROJECT_SNAPSHOT.md` - 專案快照（開場 30 秒狀態）
5. `docs/agents/skills_registry.md` - Codex / Antigravity 共用的角色選擇與協作入口
6. 自身對應的 Agent 文件（如：`tech_lead.md`、`execution_agent.md`）

**未完成上述閱讀，不得執行任何任務。**

### 特定 Agent 補充必讀文件

以下文件僅特定 Agent 需要閱讀，其他 Agent 不需要：

#### Tech Lead Agent 補充必讀
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - 開發路線圖（先讀「📍 Living Section 定義」，再看 Living Section 的「現況 / 下一步 Next / Blockers / Risks」段落）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 文檔索引（只用來定位文件入口，不作為事實來源）

#### Documentation Agent 補充必讀
- `docs/00_core/DOC_COVERAGE_MAP.md` - 文檔覆蓋矩陣（判斷 coverage 的規則文件）⭐ **必須讀取**
- `docs/00_core/DOCUMENTATION_INDEX.md` - 文檔索引（了解文檔結構）
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - 開發路線圖（先讀「📍 Living Section 定義」，再看 Living Section 段落）
- 本次變更涉及的檔案（由使用者提供，或由 Agent 提出需求）

#### 其他 Agent
- 無補充必讀文件（僅需閱讀全 Agent 必讀文件清單）

## 🚀 使用方式

### 基本流程

1. **閱讀共用上下文**：開始任何任務前，先閱讀 `shared_context.md`
2. **選擇合適的 Agent**：根據任務類型選擇對應的 Agent 文檔
3. **參考 Agent Prompt**：使用文檔中的 Prompt 模板與 AI 協作
4. **遵循規範**：確保所有操作符合共用上下文中的規範

### 範例場景

**場景 1：需要進行資料驗證**
```
1. 閱讀 shared_context.md 了解專案規範
2. 參考 data_audit_agent.md 中的 Prompt
3. 使用對應的 Agent 進行資料驗證
```

**場景 2：需要清理專案**
```
1. 閱讀 shared_context.md 了解專案結構
2. 參考 data_cleanup_agent.md 中的清理策略
3. 執行清理任務並確認不影響現有功能
```

**場景 3：需要技術決策**
```
1. 閱讀 shared_context.md 了解技術棧與架構
2. 參考 tech_lead.md 中的決策框架
3. 進行技術評估與決策
```
## 📤 Agent 輸出原則（重要）

- **必須使用繁體中文**（所有文檔、對話、回答、註解都必須使用繁體中文，禁止使用簡體中文）
- 所有 Agent 回覆必須結構化（條列或段落）
- 不使用模糊詞彙（例如：也許、可能、應該）
- 未被請求的行為視為違規
- 不確定時必須明確標示「需要確認」

## 🎯 Tech Lead Agent 設計理念

**Tech Lead Agent 不記得專案，是刻意的設計。**

專案上下文必須由人類顯式指定，避免 AI 代替你做隱性決策。

這個系統不是在「用 AI 幫你寫程式」，而是在做：

**「把決策權留在人類，執行與審查外包給 AI」**

這個方向是完全正確的。


## 📝 注意事項

- **所有 Agent 都必須遵守 `shared_context.md` 中的規範**
- **在執行任何破壞性操作前，務必先進行驗證**
- **保持文檔與代碼同步更新**
- **記錄所有重要的決策與變更**

## Codex 載入方式

Codex 不會自動把 `docs/agents/*.md` 當成 repo 指令載入。Codex 的自動入口是作用範圍內的 `AGENTS.md`。

本專案已在 repo 根目錄建立 `AGENTS.md`，作為 Codex 可識別的入口文件。該文件保留輕量索引與強制必讀順序，完整 Agent 職責、Prompt 與工作流仍以本目錄為唯一來源。

## Antigravity 載入方式

Antigravity 的 repo 根目錄入口是 `GEMINI.md`，輔助規則放在 `.agent/rules/`。完整角色文件放在 `docs/agents/antigravity/`，並指回本目錄既有的權威 Agent 文件。

`docs/agents/antigravity/` 與 `.agent/rules/` 只作為 Antigravity 適配摘要；若與本目錄權威 Agent 文件衝突，以 `docs/agents/*.md`、`shared_context.md` 與 `git_exclusions.md` 為準。

使用方式：

1. 在 Antigravity 開新任務時，確認工作目錄位於 repo 根目錄。
2. 先讀 `GEMINI.md`。
3. 再讀 `docs/agents/skills_registry.md` 判斷應啟用哪一個權威 Agent。
4. 依任務類型讀本目錄中的對應 Agent 文件；`docs/agents/antigravity/README.md` 僅作為 Antigravity 適配摘要。
5. 若 Antigravity 與 Codex 指令描述不同，以 `docs/agents/*.md`、`docs/agents/shared_context.md`、`docs/agents/git_exclusions.md` 與 `docs/00_core/DEVELOPMENT_ROADMAP.md` 為準。

使用方式：

1. 開新 Codex 任務時，確認工作目錄位於 repo 根目錄或其子目錄。
2. Codex 會讀取根目錄 `AGENTS.md`。
3. 根據任務類型，先讀 `docs/agents/skills_registry.md`，再讀取本目錄中的對應 Agent 文件。
4. 若子目錄未來需要專屬規範，可在該子目錄新增自己的 `AGENTS.md`。

## 🔄 更新記錄

- 2026-01-03：初始建立 Agent 文檔結構
- 2026-01-03：統一所有 Agent 的必讀文件清單，明確定義全 Agent 必讀與特定 Agent 補充必讀
- 2026-05-20：新增根目錄 `AGENTS.md` 作為 Codex 自動識別入口，保留 `docs/agents/` 作為完整 Agent 架構來源
- 2026-05-20：補充目前 `ui_qt`、資料根目錄與 Codex 載入現況，避免 Agent 使用舊版路徑假設
- 2026-05-27：新增 Antigravity 入口說明，對齊 `GEMINI.md`、`.agent/rules/` 與 `docs/agents/antigravity/`
- 2026-06-09：新增 `skills_registry.md` 作為 Codex / Antigravity 共用協作入口，明確 `docs/agents/*.md` 為唯一角色權威，Antigravity 文件降級為適配摘要

