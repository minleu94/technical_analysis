# P0 候選資料來源品質稽核操作手冊

本工具只做候選資料的唯讀探測與品質投影。它不寫正式資料庫、不啟用排程、不改 `ScoringEngine`、Advice、Portfolio 或交易路徑。

## 執行

```powershell
.\.venv\Scripts\python.exe scripts\run_p0_candidate_audit.py --decision-date 2026-07-16 --output $env:TEMP\p0_candidate_audit.json
```

目前可直接探測的官方候選來源是三大法人、信用交易與 TDCC 股權分散；其餘 P0 項目會以 `not_started_no_candidate_adapter` 顯示，代表尚未建立候選 adapter，不代表來源不可用或已接受。

## 判讀

- `observed_candidate`：本次官方端點可連線且解析契約相符；不是正式接受。
- `degraded` 與 `official_publication_timestamp_missing`：只保存本次實際觀測時間，不能主張已取得正式公告時間或 PIT 完整性。
- `not_started_no_candidate_adapter`：尚未建立來源端點與解析契約；不補值、不猜測品質。

所有輸出固定為 `production_scheduler_allowed=false`、`downstream_eligibility=none` 與 `human_decision=requires_human_acceptance`。因此執行本工具不會影響任何排程 gate。
