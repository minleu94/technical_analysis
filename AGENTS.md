# Codex Repository Instructions

> Codex 自動讀取入口。完整 Agent 架構仍維護在 `docs/agents/`。

## 必讀順序

在執行任何任務前，先閱讀並遵守下列文件：

1. `docs/agents/README.md` - Agent 總覽與強制流程
2. `docs/agents/shared_context.md` - 全 Agent 共用規範
3. `docs/agents/git_exclusions.md` - Git 排除與不應提交清單
4. `docs/00_core/PROJECT_SNAPSHOT.md` - 專案目前狀態
5. `docs/00_core/DEVELOPMENT_ROADMAP.md` - Roadmap Hub 與文件權威入口
6. `docs/00_core/ROADMAP_6M_ENGINEERING.md` - 未來 6 個月工程路線（涉及方向、優先序或大型規劃時必讀）
7. `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` - 舊 Roadmap 移交與 Gate（涉及舊工作承接、Phase 或優先順序時必讀）
8. `docs/01_architecture/system_architecture.md` - 系統架構（涉及架構、模組邊界或資料流時必讀）
9. `docs/agents/skills_registry.md` - Codex / Antigravity 共用的角色選擇與協作入口
10. `docs/07_guides/APPLICATION_MANUAL.md` - 完整操作手冊（涉及 UI、使用流程、參數、結果判讀或安全限制時必讀）
11. 與任務對應的 Agent 文件：
   - 架構判斷、技術決策：`docs/agents/tech_lead.md`
   - 資料完整性、資料對比：`docs/agents/data_audit_agent.md`
   - 清理、移除、整理：`docs/agents/data_cleanup_agent.md`
   - 受控實作：`docs/agents/execution_agent.md`
   - 文檔同步：`docs/agents/documentation_agent.md`

## Codex 載入規則

- Codex 會自動讀取作用範圍內的 `AGENTS.md`。
- 本檔位於 repo 根目錄，作用範圍是整個 repository。
- `docs/agents/*.md` 是專案 Agent 知識庫，不是 Codex 會自動載入的檔名；本檔負責把 Codex 指向那些文件。
- `docs/agents/skills_registry.md` 是 Codex 與 Antigravity 共用的協作入口，只負責角色選擇、流程導引與 shared context，不重新定義 Agent。
- 若未來某個子目錄需要更細規則，可在該子目錄新增自己的 `AGENTS.md`，其規則只作用於該子目錄樹。

## 工作規範

- 使用繁體中文回覆與更新文檔。
- 不得刪除或破壞原始資料檔。
- 資料位置以 `data_module/config.py` 的 `TWStockConfig` 為準；正式資料根目錄預設 `D:/Min/Python/Project/FA_Data`，可由 `DATA_ROOT` 覆蓋。
- 目前主要 UI 是 `ui_qt/`（PySide6），入口為 `ui_qt/main.py`。
- 股票/量化防禦條款：策略、回測、資金、倉位、風控與績效等核心計算嚴禁新增裸 `float` 計算；必須使用 `Decimal`、整數基點/股數/分為單位，或在明確隔離的資料分析/視覺化邊界內處理。
- 實作任何策略、回測、推薦或績效邏輯前，必須先做未來函數（Look-ahead bias）自查，確認訊號、特徵、篩選、標準化、停損停利與 benchmark 都只使用決策當下可取得的資料。
- 修改功能時同步更新相關文檔。
- 使用者可見功能變更時，完整 Manual 必須同步入口、操作步驟、參數意義、結果判讀、安全限制與排錯。
- 文件判讀採 Scoped SSOT：目前狀態看 `PROJECT_SNAPSHOT.md`，未來 6 個月方向看 `ROADMAP_6M_ENGINEERING.md`，舊工作承接看 `LEGACY_ROADMAP_CARRYOVER.md`，架構看 `system_architecture.md`，操作看 `APPLICATION_MANUAL.md`，歷史看 `docs/09_archive/`。
- Stage / commit 前先看 `docs/agents/git_exclusions.md`，不要把本機暫存、工具輸出或非本任務 QA output 順手提交。
- 優先遵循既有架構與測試方式。
- 不要覆寫使用者或其他 agent 的未提交變更。
- 執行高風險操作、資料重建、分支清理前，先明確確認。

## 驗證建議

- UI 修改後強制作業：先跑 `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
- UI 修改後強制作業：再跑 `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
- UI 修改後強制作業：執行型態檢查 `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`
- 語法檢查：跑 `.\.venv\Scripts\python.exe -m py_compile <changed-python-files>`
