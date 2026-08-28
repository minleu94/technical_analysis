# 排程與日常證據可觀測性健康報告 (Scheduler Health & Observability Report)

*報告生成時間: 2026-08-27T01:18:05.023358*

> [!IMPORTANT]
> 本報告為唯讀排程健康與可觀測性稽核報告，**不改動 Windows Task 或 Codex 自動化任務本身**。
> **`production_scheduler_allowed=false` 為正式 DB Evidence 寫入限制，不代表禁止每日市場價格資料更新。**

## 1. 排程整體健康總覽
- **整體健康狀態 (Overall Health)**: `WARNING`
- **正式排程寫入許可 (Production Scheduler Allowed)**: `False`
- **執行順序相依性驗證 (Ordering Valid)**: `True`

## 2. 5 大排程任務單元狀態矩陣
| 順序 | 任務名稱 | 上次執行時間 | 狀態 | 寫入意圖 (Write Intent) | 狀態檔路徑 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| #1 | `daily_data_update_quick` | `2026-08-26T04:31:39.371578` | `SUCCESS` | `MARKET_DATA_UPDATE_WRITE` | `D:\Min\Python\Project\FA_Data\output\scheduled\data_update_quick\latest_status.json` |
| #2 | `daily_data_freshness_check` | `2026-08-26T05:00:02.257117` | `SUCCESS` | `DRY_RUN_NO_WRITE` | `D:\Min\Python\Project\FA_Data\output\scheduled\data_freshness\latest_status.json` |
| #3 | `scheduled_recommendation_snapshot` | `2026-08-26T05:10:19.392981` | `SUCCESS` | `DRY_RUN_NO_WRITE` | `D:\Min\Python\Project\FA_Data\output\scheduled\recommendation_snapshot\latest_status.json` |
| #4 | `scheduled_evidence_pipeline_dry_run` | `2026-08-26T05:16:23.010587` | `DEGRADED` | `DRY_RUN_NO_WRITE` | `D:\Min\Python\Project\FA_Data\output\scheduled\evidence_pipeline_dry_run\latest_status.json` |
| #5 | `v2_2_weekly_collection` | `2026-08-24 01:00:11` | `PASSED_WITH_WARNINGS` | `SIDECAR_PENDING_HUMAN_REVIEW` | `D:\Min\Python\Project\FA_Data\output\scheduled\v2_2_weekly_collection\v2_2_weekly_collection_20260823.json` |

## 3. 建議事項與運作提示 (Advisory Notes)
- 提示：`production_scheduler_allowed=false` 為正式 DB 寫入限制，不影響 daily_data_update_quick 之市場價格更新。
