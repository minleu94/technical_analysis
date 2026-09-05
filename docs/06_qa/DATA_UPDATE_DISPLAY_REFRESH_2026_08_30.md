# Data Update Display Refresh — 2026-08-30

## 發現

8/30 的實際 quick update 已成功完成，資料涵蓋至最後交易日 2026-08-28；同日 freshness probe 也以 2026-08-30 的檢查時間確認日價／技術指標最新日為 2026-08-28。原本共用時間軸卻把 freshness 的 `data_update_quick_checked_date`（檢查發生日期）當成資料 end date 比對，因而產生：

`freshness:quick_checked_date_mismatch:2026-08-30:target=2026-08-28`

這會把合法週末檢查誤顯示成 `degraded`，即使 quick status、日價、技術指標與原始日檔均正常。

## 修正

`app_module/update_status_timeline.py` 現在採用正確的語意：

- `data_update_quick_expected_date`、`daily_prices_latest_date`、`technical_indicators_latest_date` 必須與 quick-run 資料 `end_date` 一致。
- `data_update_quick_checked_date` 只檢查是否早於 `data_update_quick_expected_date`；它可以晚於資料 end date，因為 freshness probe 可能在週末或收盤後執行。
- 若檢查日早於預期日，仍回報 `freshness:quick_checked_date_before_expected` 並將時間軸降級。

## 實際重驗

唯讀重新載入：

- quick status：`passed`、run=`20260830-24700`、completed=`2026-08-30T04:21:04-07:00`、end date=`2026-08-28`
- freshness：`passed`、checked=`2026-08-30T05:00:01-07:00`
- daily／technical latest=`2026-08-28`
- 修正後 timeline：`status=current`
- 保留診斷：`tpex_path_not_configured`（TPEX refresh path 未設定）；不再有 `quick_checked_date_mismatch`

## QA

新增兩個 regression：

1. 檢查日晚於資料 end date（週末）仍為 `current`。
2. 檢查日晚於預期日的反例仍明確 `degraded`。

定向測試結果：`107 passed`（update timeline、formatters、Update View Workbench）。本修正不會重新跑下載、不會寫 SQLite、不會改 scheduler 或 freshness artifact，只修正 read-only projection 的日期語意。

## Readiness card 舊 artifact 標記

同一輪也補上 `program_readiness_projection` 的 bounded freshness hint：Update View 只把自己
已設定的 data-update／freshness status path 當 reference，若明確指定的 readiness artifact
mtime 較舊，就加入
`program_readiness_artifact_older_than_reference:<filename>` diagnostic。它不會自動掃描 TEMP、
替換 artifact、改 lane status 或授予任何 Gate；因此 cleanup 前的 readiness JSON 會被清楚標成
歷史候選，而不會被誤當成最新資料。

這個顯示邊界已有 regression 覆蓋，與現有 stale status／unknown path 的 fail-closed 行為一致。
