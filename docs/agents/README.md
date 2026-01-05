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

## ⛔ 強制流程（所有 Agent 必須遵守）

### 全 Agent 必讀文件清單（固定順序）

**任何 Agent 在執行任務前，必須依序閱讀：**

1. `docs/agents/README.md` - Agent 總覽（本文件）
2. `docs/agents/shared_context.md` - 共用上下文（不可違背前提）
3. `docs/00_core/PROJECT_SNAPSHOT.md` - 專案快照（開場 30 秒狀態）
4. 自身對應的 Agent 文件（如：`tech_lead.md`、`execution_agent.md`）

**未完成上述閱讀，不得執行任何任務。**

### 特定 Agent 補充必讀文件

以下文件僅特定 Agent 需要閱讀，其他 Agent 不需要：

#### Tech Lead Agent 補充必讀
- `docs/DEVELOPMENT_ROADMAP.md` - 開發路線圖（先讀「📍 Living Section 定義」，再看 Living Section 的「現況 / 下一步 Next / Blockers / Risks」段落）
- `docs/DOCUMENTATION_INDEX.md` - 文檔索引（只用來定位文件入口，不作為事實來源）

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

## 🔄 更新記錄

- 2026-01-03：初始建立 Agent 文檔結構
- 2026-01-03：統一所有 Agent 的必讀文件清單，明確定義全 Agent 必讀與特定 Agent 補充必讀

