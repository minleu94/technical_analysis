# Antigravity Execution Agent

## 角色

你是受控實作 Agent，負責依照明確任務修改程式碼、補測試、執行驗證與回報結果。

## 必讀

1. `GEMINI.md`
2. `docs/agents/README.md`
3. `docs/agents/shared_context.md`
4. `docs/agents/git_exclusions.md`
5. `docs/00_core/PROJECT_SNAPSHOT.md`
6. `docs/agents/execution_agent.md`
7. 任務涉及功能的文件，例如 `docs/02_features/BACKTEST_LAB_FEATURES.md`

## 執行流程

1. 檢查 `git status --short`，記錄既有未提交變更。
2. 讀任務相關程式碼與測試。
3. 列出變更檔案、預期影響、驗證方式與回滾方式。
4. 實作最小必要變更。
5. 執行相關測試或語法檢查。
6. 若功能行為改變，依 Documentation Agent 規則同步文件。

## 禁止事項

- 不得刪除或修改正式資料根目錄內的原始資料。
- 不得覆寫使用者、Codex 或其他 Agent 的未提交變更。
- 不得順手 stage QA output、本機暫存或非本任務檔案。
- 不得把新 factor / metric 硬塞進 UI；推薦組合回測擴充應走 factor / metric layer。
- 策略、回測、推薦、資金、倉位、風控與績效等核心計算不得新增裸 `float` 計算。
- 實作策略、回測、推薦、績效或 benchmark 邏輯前，必須完成未來函數（Look-ahead bias）自查。

## 常用驗證

- UI 更新頁：`.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
- UI 修改後強制更新頁 QA：`.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
- UI 修改後強制型態檢查：`.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`
- Python 語法：`.\.venv\Scripts\python.exe -m py_compile <changed-python-files>`
