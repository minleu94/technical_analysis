# V4 工作區清理收尾（2026-09-08）

本文件記錄本輪兩批有限、可回滾的工作區清理。清理範圍只包含 repo 內已確認可再生的快取與過期 QA 暫存；`.git`、`.venv`、`D:` 原始資料、`output` 正式證據／帳本／SQLite／WAL／raw／checkpoint，以及 `graphify-out` 均保留。

## 第一批：repo 快取

- 清理前（受保護根目錄之外）：5,613 個檔案。
- 預定清除：2,391 個 `.pyc/.pyo`（50,591,135 bytes）、5 個 `.pytest_cache` 檔案（384,266 bytes）、57 個快取目錄。
- 實際移除：2,324 個檔案（49,587,838 bytes）、40 個空目錄。
- 保留：72 個檔案；其中 65 個因存取被拒或仍被程序使用，7 個因檔案在清理期間變更／重新產生而跳過。沒有強制刪除或第二次掃除。
- 清理前後受保護根目錄未被寫入；活動中的 Python 程序繼續產生快取，因此剩餘快取數量不應被解讀為缺陷。

## 第二批：過期 full-app healthcheck 暫存

- 目標：`output/qa/full_app_healthcheck_tmp/`，僅含 2026-06 至 2026-08 的 `.md`／`.json` QA 報告，沒有 SQLite、WAL、raw、CSV、checkpoint、manifest、receipt 或 lock。
- 清理前：145 個檔案、666,244 bytes。
- 實際移除：145 個檔案、666,244 bytes、74 個空目錄；跳過 0、違規 0。
- 回滾：依逐檔 SHA-256、大小、修改時間與相對路徑清單重新執行同一 healthcheck，可產生新的 QA 結果；本輪沒有另存 145 份完整 bytes，因此不能宣稱恢復當時完全相同內容。清單不依賴 glob，也不包含受保護根目錄。
- 目標目錄已不存在；manifest 中 145 筆均驗證為缺失，沒有意外仍存在的項目。刪除目標內沒有 reparse point。

## 明確保留項目

- `.git`、`.venv` 與 `graphify-out` 全部保留。`graphify-out` 當時觀察到 5,434 個檔案且仍有近期寫入，不能視為暫存。
- `output` 只做分類盤點，沒有整包刪除。盤點快照為 24,799 個檔案、8,448,903,880 bytes；刪除後再次觀察為 24,695 個檔案、8,546,220,712 bytes，差異包含活動程序與本輪新增證據檔案，不能用總數推算刪除量。
- `output/qa/ui_visual_review_tmp` 的 14 個歷史截圖（954,340 bytes）保留，因用途與追溯需求無法由檔名安全排除。
- 活動 Python 程序觀察到 52 個，包含其他 agent 的 live pytest；沒有停止、重啟或刪除其輸出。受保護 output 中觀察到的三個 reparse fixture 位於刪除範圍外，均保留。

## 證據與驗證

第二批證據集中在 `output/v4_next_ops/workspace_cleanup_20260908/`：

- `batch2_delete_manifest_20260908.jsonl`：逐檔回滾 manifest。
- `batch2_rollback_plan_20260908.md`：刪除界線與回滾方式。
- `batch2_pre_delete_summary_20260908.json`：刪除前精確數量與 bytes。
- `batch2_deletion_result_20260908.json`：實際刪除結果。
- `batch2_post_delete_verification_20260908.json`：目標缺失、受保護路徑與 reparse 保留驗證。
- `batch2_output_inventory_20260908.jsonl`、`batch2_output_summary_20260908.json`：output 分類清冊；此清冊不是刪除授權。

第一批的 manifest、rollback、刪除結果與 post-delete 驗證亦保留在同一目錄，檔名以 `batch1_` 開頭。清理沒有改寫 D 槽原始資料，也沒有改變正式交易、ML、Paper、Formal 或活動排程程序。
