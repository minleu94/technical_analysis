# Governance-aware AI Runtime MVP

此 Runtime Layer 是一個輕量級的外掛執行環境，專為輔助既有的 Markdown-agent 系統而設計。
核心理念為 **Explainability-first** 與 **Governance-first**，完全基於 Python 標準函式庫與 JSON 實作。

## 1. Runtime Data Flow

當前系統的資料流如下：

1. **State Injection**: 當一個 Agent 被喚醒時，系統只會將 `state/current_task.json` (目前任務目標) 與 `state/runtime_context.json` (動態環境資訊) 注入，避免傳統對話產生 Context Overload 或是 Lost-in-the-middle 效應。
2. **Agent Execution**: Agent 根據上述 JSON 狀態以及原有的 markdown roles (`docs/agents/*`) 進行決策。
3. **Structured Output**: Agent 將思考與行動結果格式化為 JSON Envelope，寫入 `outputs/` 目錄（如 `sample_output_envelope.json`）。
4. **Validation Check**: 系統透過 `validation/validate_output.py` 檢查該 Envelope。
5. **State Update / Handoff**: 若驗證通過，則系統（或下一個 Agent）接手處理 payload，並更新 `current_task.json` 狀態。

## 2. Validation Lifecycle

本系統的驗證層（Validation Layer）區分為 Hard-fail 與 Warning 兩種機制：

* **Hard-fail (強制阻擋)**：
  * Schema 結構錯誤（漏填必填欄位、型態錯誤）。
  * 違反 Registry 約束（例如輸出的狀態不是 enum 規定的狀態）。
  * 缺乏 Governance Check（沒有撰寫 Rollback Plan 或是 Audit Trail）。
  * *結果*：拒絕寫入狀態或程式碼，強制 Agent 重新生成。
* **Warning only (警告)**：
  * `human_readable_summary` 描述過短，可能影響 Explainability。
  * *結果*：記錄於日誌，但不阻擋流程繼續進行。

## 3. Governance Boundaries

* **No DB, No Magic**: 所有狀態皆為純文字 JSON 檔案，人類可以隨時開啟修改（Human-in-the-loop），透明且無需依賴任何 Database。
* **Clear Allowed/Forbidden Actions**: 透過 `registry/agents_registry.json`，嚴格規範每個角色的邊界，例如禁止 Execution Agent 修改架構規則。
* **Enforced Rollback**: 任何系統變更輸出都必須包含人類可讀的 `rollback_plan`，確保具備災難復原能力。

## 4. MVP Limitations (目前尚未支援的能力)

基於 MVP 限制，目前**尚未實作**以下功能：
* **Intent Router & Autonomous Workflow**: 尚未實作自動將任務分派給不同 Agent 的 Python 控制迴圈。目前流程為手動將 output 轉發。
* **Memory Retrieval System**: 尚未結合 Vector DB 或 RAG 機制來檢索過去的記憶，僅依賴輕量級的 JSON Context。
* **Async / Concurrency**: Agent 與驗證流程均為同步 (Synchronous) 執行，無併發設計，確保日誌清晰與易於除錯。
