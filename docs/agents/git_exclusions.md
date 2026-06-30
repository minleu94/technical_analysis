# Git 排除與不應提交清單

> 給 Codex / Agent 接手時判斷 working tree 用。看到這些項目時，不要因為它們出現在 `git status` 就順手 stage。

## 已由 `.gitignore` 排除

這些是本機快取、工具暫存或 agent 工作目錄，不應提交：

- `.superpowers/`：Superpowers plugin 的本機工作狀態。
- `/meta_data/`：repo 根目錄下的背景任務狀態與 runtime log；正式資料根目錄 `{DATA_ROOT}/meta_data/` 不在 repo 內，不受此規則影響。
- `**/.tmp.driveupload/`：文件或工具在任意工作目錄建立的雲端上傳暫存目錄。
- `docs/agents/shared_state/active_task.yaml`：Agent 本機任務交接狀態；各工作階段可自行更新，不應提交。
- `docs/agents/shared_state/handoff_log.md`：本機跨 Agent 交接紀錄；可能包含進行中工作資訊，不應提交。
- `.pytest_cache/`、`.coverage`、`htmlcov/`、`.tox/`、`.cache/`：測試與 coverage 輸出。
- `*.log`、`logs/`：執行日誌。
- `venv/`、`env/`、`ENV/`：本機虛擬環境。
- `.env*`：本機環境變數與密鑰設定；`.env.example` 例外，可提交。
- `*.db`、`*.sqlite*`：本機資料庫輸出。
- `output/`：QA、驗證、報告匯出與本機執行輸出；2026-06-30 起不應再追蹤於乾淨 `main`。
- `/test.parquet`：根目錄臨時資料樣本 / 測試產物，不應提交。
- `downloads/`、`temp_downloads/`、`tmp/`、`temp/`：下載與暫存檔。

## 已從乾淨 main 移出的易變輸出

以下檔案類型曾經被 Git 追蹤，但屬於本機驗證輸出；2026-06-30 清理後，乾淨 `main` 不應再包含這些產物。若它們在本機重新生成，應維持 ignored，不要 stage：

- `output/**`
- `output/qa/**`
- `test.parquet`

若任務需要保存可分享的 QA 結論，請寫入 `docs/06_qa/` 的摘要 / audit / issue 文件，而不是提交 `output/` 底下的 raw output。

## Agent 操作規則

- Stage 前一定先跑 `git status --short`，確認只包含本次任務檔案。
- 不要 revert、刪除或清理你沒有產生的 dirty files。
- 若遇到不在本文件中的新暫存/輸出目錄，先判斷來源並更新本文件，再決定是否加入 `.gitignore`。
- 若是正式資料根目錄 `DATA_ROOT` / `OUTPUT_ROOT` 內的資料，遵守 `docs/agents/shared_context.md` 的資料完整性規則，不做破壞性操作。
