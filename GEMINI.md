# Antigravity Repository Instructions

> Antigravity 讀取入口。完整 Agent 架構仍以 `docs/agents/` 與 `docs/00_core/` 為權威來源。

## 角色定位

你是本專案的協作型開發 Agent。你可以協助分析、設計、實作、測試、文檔同步與交接，但必須先讀專案上下文，不得用一般 Python 專案假設取代本 repo 的規範。

## 必讀順序

在執行任何任務前，依序閱讀：

1. `docs/agents/README.md` - Agent 總覽與強制流程
2. `docs/agents/shared_context.md` - 全 Agent 共用規範
3. `docs/agents/git_exclusions.md` - Git 排除與不應提交清單
4. `docs/00_core/PROJECT_SNAPSHOT.md` - 專案目前狀態
5. `docs/00_core/DEVELOPMENT_ROADMAP.md` - Roadmap Hub 與文件權威入口
6. `docs/00_core/ROADMAP_6M_ENGINEERING.md` - 未來 6 個月工程路線（涉及方向、優先序或大型規劃時必讀）
7. `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` - 舊 Roadmap 移交與 Gate（涉及舊工作承接、Phase 或優先順序時必讀）
8. `docs/01_architecture/system_architecture.md` - 系統架構（涉及架構、模組邊界或資料流時必讀）
9. `docs/07_guides/APPLICATION_MANUAL.md` - 完整操作手冊（涉及 UI 流程、參數、結果判讀或安全限制時必讀）
10. `docs/agents/skills_registry.md` - Codex / Antigravity 共用的角色選擇與協作入口
11. `docs/agents/antigravity/README.md` - Antigravity 適配摘要與工作方式
12. 與任務對應的權威角色文件：
   - 技術判斷 / 架構建議：`docs/agents/tech_lead.md`
   - 受控實作 / Bug 修復：`docs/agents/execution_agent.md`
   - 文檔同步 / Coverage：`docs/agents/documentation_agent.md`
   - 資料驗證 / 對比：`docs/agents/data_audit_agent.md`
   - 清理 / 移除 / 整理：`docs/agents/data_cleanup_agent.md`
   - 測試路由 / QA healthcheck / 功能驗證 / healthcheck 結果解讀：`docs/agents/testing_qa_agent.md`

## 工作規範

- 一律使用繁體中文回覆與更新文檔。
- 不得刪除或破壞正式資料根目錄內的原始資料；資料位置以 `data_module/config.py` 的 `TWStockConfig` 為準。
- 目前主要 UI 是 `ui_qt/`（PySide6），入口為 `ui_qt/main.py`。
- 修改功能時同步檢查文檔更新需求；新增或刪除 Markdown 時必須更新 `docs/00_core/DOCUMENTATION_INDEX.md`。
- 修改使用者可見流程、參數、結果判讀或安全限制時，必須同步更新 `docs/07_guides/APPLICATION_MANUAL.md`。
- 文件判讀採 Scoped SSOT：目前狀態看 `PROJECT_SNAPSHOT.md`，未來 6 個月方向看 `ROADMAP_6M_ENGINEERING.md`，舊工作承接看 `LEGACY_ROADMAP_CARRYOVER.md`，架構看 `system_architecture.md`，操作看 `APPLICATION_MANUAL.md`，歷史看 `docs/09_archive/`。
- `AGENT_CONTEXT.md` 是給 Codex、Antigravity 與開發者快速理解專案入口、分支策略與文件權威的輔助導覽；強制規則仍以本檔、`AGENTS.md` 與 `docs/agents/` 為準。
- Stage / commit 前先看 `docs/agents/git_exclusions.md`，不要把本機暫存、工具輸出或非本任務 QA output 順手提交。
- 不要覆寫使用者、Codex 或其他 Agent 的未提交變更。
- 執行高風險操作、資料重建、分支清理、刪除檔案前，先明確確認。

## Antigravity 輔助規則

`.agent/rules/` 內的檔案是給 Antigravity 快速載入的工作規則摘要：

- `.agent/rules/00_project_entry.md`：專案入口與權威文件順序
- `.agent/rules/10_development_execution.md`：實作任務規則
- `.agent/rules/20_documentation_sync.md`：文檔同步規則
- `.agent/rules/30_git_safety.md`：Git 與多 Agent 安全規則

若這些規則與 `docs/agents/` 或 `docs/00_core/` 衝突，以 `docs/agents/` 權威 Agent 文件、`PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、`LEGACY_ROADMAP_CARRYOVER.md`、`system_architecture.md`、`APPLICATION_MANUAL.md`、`docs/agents/shared_context.md`、`docs/agents/git_exclusions.md` 為準。

## 驗證建議

- UI 更新頁相關變更：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
- 更新頁 QA：`.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
- 語法檢查：`.\.venv\Scripts\python.exe -m py_compile <changed-python-files>`
