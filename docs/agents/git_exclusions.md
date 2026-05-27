# Git 排除與不應提交清單

> 給 Codex / Agent 接手時判斷 working tree 用。看到這些項目時，不要因為它們出現在 `git status` 就順手 stage。

## 已由 `.gitignore` 排除

這些是本機快取、工具暫存或 agent 工作目錄，不應提交：

- `.superpowers/`：Superpowers plugin 的本機工作狀態。
- `docs/.tmp.driveupload/`：文件/雲端上傳流程的暫存目錄。
- `.pytest_cache/`、`.coverage`、`htmlcov/`、`.tox/`、`.cache/`：測試與 coverage 輸出。
- `*.log`、`logs/`：執行日誌。
- `venv/`、`env/`、`ENV/`：本機虛擬環境。
- `.env*`：本機環境變數與密鑰設定；`.env.example` 例外，可提交。
- `*.db`、`*.sqlite*`：本機資料庫輸出。
- `downloads/`、`temp_downloads/`、`tmp/`、`temp/`：下載與暫存檔。

## 目前 tracked 但屬於易變輸出

以下檔案目前仍在 Git 追蹤中，因此 `.gitignore` 無法阻止它們顯示為 modified。除非任務明確要求更新 QA 報告或驗證輸出，否則不要 stage：

- `output/qa/update_tab/RUN_LOG.txt`
- `output/qa/update_tab/VALIDATION_REPORT.md`

如果未來要正式讓這些 QA output 不再被 Git 追蹤，需另開清理任務，評估是否保留範例報告、移到 archive，或用 `git rm --cached` 搭配 `.gitignore`。不要在一般功能開發中順手處理。

## Agent 操作規則

- Stage 前一定先跑 `git status --short`，確認只包含本次任務檔案。
- 不要 revert、刪除或清理你沒有產生的 dirty files。
- 若遇到不在本文件中的新暫存/輸出目錄，先判斷來源並更新本文件，再決定是否加入 `.gitignore`。
- 若是正式資料根目錄 `DATA_ROOT` / `OUTPUT_ROOT` 內的資料，遵守 `docs/agents/shared_context.md` 的資料完整性規則，不做破壞性操作。
