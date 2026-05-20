# Codex Repository Instructions

> Codex 自動讀取入口。完整 Agent 架構仍維護在 `docs/agents/`。

## 必讀順序

在執行任何任務前，先閱讀並遵守下列文件：

1. `docs/agents/README.md` - Agent 總覽與強制流程
2. `docs/agents/shared_context.md` - 全 Agent 共用規範
3. `docs/00_core/PROJECT_SNAPSHOT.md` - 專案目前狀態
4. 與任務對應的 Agent 文件：
   - 架構判斷、技術決策：`docs/agents/tech_lead.md`
   - 資料完整性、資料對比：`docs/agents/data_audit_agent.md`
   - 清理、移除、整理：`docs/agents/data_cleanup_agent.md`
   - 受控實作：`docs/agents/execution_agent.md`
   - 文檔同步：`docs/agents/documentation_agent.md`

## Codex 載入規則

- Codex 會自動讀取作用範圍內的 `AGENTS.md`。
- 本檔位於 repo 根目錄，作用範圍是整個 repository。
- `docs/agents/*.md` 是專案 Agent 知識庫，不是 Codex 會自動載入的檔名；本檔負責把 Codex 指向那些文件。
- 若未來某個子目錄需要更細規則，可在該子目錄新增自己的 `AGENTS.md`，其規則只作用於該子目錄樹。

## 工作規範

- 使用繁體中文回覆與更新文檔。
- 不得刪除或破壞原始資料檔。
- 修改功能時同步更新相關文檔。
- 優先遵循既有架構與測試方式。
- 不要覆寫使用者或其他 agent 的未提交變更。
- 執行高風險操作、資料重建、分支清理前，先明確確認。

## 驗證建議

- UI 更新頁相關變更：先跑 `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
- 更新頁 QA：跑 `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
- 語法檢查：跑 `.\.venv\Scripts\python.exe -m py_compile <changed-python-files>`
