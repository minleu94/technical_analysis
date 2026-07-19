# P0 候選資料來源品質稽核操作手冊

本工具只做候選資料的唯讀探測與品質投影。它不寫正式資料庫、不啟用排程、不改 `ScoringEngine`、Advice、Portfolio 或交易路徑。

## 執行

```powershell
.\.venv\Scripts\python.exe scripts\run_p0_candidate_audit.py --decision-date 2026-07-16 --output $env:TEMP\p0_candidate_audit.json
```

`twse_full_delivery` probes the official TWT85U daily altered-trading-method list; `twse_halt_resume` probes TWTAWU halt/resume effective dates and times. Both preserve only first-observed evidence because neither payload supplies a verified official publication timestamp.

`twse_monthly_revenue` and `tpex_monthly_revenue` probe the current official open-data snapshots. Their `出表日期` is retained as a report date, but it is not treated as an intraday publication timestamp; the free endpoints are current-period snapshots and do not prove historical PIT availability.

目前可直接探測的官方候選來源是三大法人、信用交易、TDCC 股權分散，以及 TWSE 的處置、處置中的分盤撮合、除權息計算與減資恢復買賣資訊。`microstructure.disposition_stock` 會保留公告日、處置起迄日、處置條件、措施與原始 payload SHA-256；`microstructure.periodic_call_auction` 僅保留處置內容明確含「分鐘撮合」或「分盤」的列，絕不從一般處置推定分盤；`corporate_action.ex_dividend_timeline` 會保留除權息生效日與權／息類別；`corporate_action.reduction_split_par_value` 會保留減資恢復日、原因與參考價。這些 TWSE payload 都未提供可驗證的官方發布 timestamp，因此固定為 `degraded` / `official_publication_timestamp_missing`，不可宣稱 PIT 完整。其餘 P0 項目會以 `not_started_no_candidate_adapter` 顯示，代表尚未建立候選 adapter，不代表來源不可用或已接受。

## 判讀

- `observed_candidate`：本次官方端點可連線且解析契約相符；不是正式接受。
- `degraded` 與 `official_publication_timestamp_missing`：只保存本次實際觀測時間，不能主張已取得正式公告時間或 PIT 完整性。
- `not_started_no_candidate_adapter`：尚未建立來源端點與解析契約；不補值、不猜測品質。

所有輸出固定為 `production_scheduler_allowed=false`、`downstream_eligibility=none` 與 `human_decision=requires_human_acceptance`。因此執行本工具不會影響任何排程 gate。

輸出的 `lineage` 會保存 `probe_date`、`probe_mode=bounded_official_read_only` 與 canonical `probe_report_sha256`。Builder 會在投影前拒絕日期、mode、license/source acceptance、downstream eligibility、scheduler 或 human decision 邊界不符，以及重複 `source_id`；hash 對 source row 排序不敏感，但不代表來源已正式接受。

已標記 `schema_status=matched` 的 probe row 必須有 64 位 SHA-256 payload digest，並維持 `raw_row_count = accepted + duplicate + quarantine + blocked`；缺欄、布林值、負值、非整數或不守恆都會 fail-closed。這些是 candidate diagnostics 的資料品質邊界，不會提升 source acceptance 或 formal evidence 狀態。

即使未經 `capture()` 而直接建立 raw manifest，manifest 本身也會重新檢查 timezone、非負整數 counts、row conservation、payload size 與 SHA-256 digest 格式；因此 candidate repository 不會接受由直接建構繞過的無效 provenance。
