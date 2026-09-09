# V4 TDCC 集保股權候選資料補齊（2026-09-09）

本片只建立官方 raw、完整級距 candidate 與可審核的 apply 工具；沒有寫入 D 槽原始檔，也沒有寫入任何正式 SQLite。候選仍是 `candidate_only=true`、`downstream_eligibility=none`，不授予 PIT、scoring、recommendation 或 scheduler credit。

## 官方來源與時間語意

- Endpoint：`https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5`
- HTTP：200，`Content-Type=text/csv; charset=UTF-8`
- Raw：`output/data_completion_20260909/tdcc/tdcc_1-5_raw_20260909T050303Z.csv`
- Raw SHA-256：`7fa8013d235ae5993d83f7cee962291ec09f9e2e572980f141b7e23711630fdf`
- 官方報表日（`資料日期`）：`2026-09-04`
- 實際觀測：`2026-09-09T05:03:24.444373Z`（台北 `2026-09-09 13:03:24`）
- 官方 payload 沒有可驗證 publication timestamp，因此 quality 固定 `degraded`、availability evidence 固定 `first_observed_only`。
- 日期型 individual reader 的安全 `available_date` 是觀測時間轉台北後翌日：`2026-09-10`。精確觀測時間仍保存在 `observed_at`、`first_observed_at`、`available_at`；不把 9/9 中午捕獲的資料提供給 9/9 早盤決策。

第 1–16 級是分布級距，第 17 級是官方總計列。candidate 保留全部 17 級；aggregate 只用第 1–16 級。原始百分比四捨五入造成的小殘差會以明示的 complement policy 對齊 P0 10,000 bp，並留下 `source_distribution_residual_bp`；超過 15 bp 或官方總計不為 10,000 bp 的個股不會被補成 ready。

## 產物與對帳

產物都在被 `.gitignore` 排除的 `output/data_completion_20260909/tdcc/`：

- `tdcc_1-5_20260904_tiers.csv`：68,867 列、4,051 檔、每檔 17 級，包含每列 raw row hash。
- `tdcc_1-5_20260904_aggregate.csv`：4,051 筆 P0 aggregate，保留 report／observed／availability provenance。
- `tdcc_1-5_20260904_ready_import.csv`：4,047 筆可供 owner 審核的既有 `tdcc_shareholding` table import rows。
- `tdcc_1-5_20260904_quarantine.csv`：4 筆 blocked：`00406A`、`00896`、`00961`、`00962`；完整 17 級仍在 tiers/raw，沒有刪掉或補值。
- `tdcc_1-5_20260904_p0_shadow.json`：完整 shadow payload，`writes_allowed=false`。
- `tdcc_1-5_20260904_manifest.json`：source hash、artifact hashes、時間語意、筆數與 formal write 狀態。

`tests/test_tdcc_shareholding_candidate.py` 與 `tests/test_apply_tdcc_shareholding_candidate.py` 共 10 tests 通過；涵蓋 full-tier conservation、report/observed 分離、future/date-only 防護、異常級距 quarantine、個股研究 reader 的 9/9 排除與 9/10 顯示，以及 apply dry-run、WAL-aware backup、冪等、衝突拒絕。真實 candidate dry-run 對 4,047 筆回報 `added=4047, conflicts=0, formal_db_written=false`。

## Root owner 審核與 apply

先做唯讀 dry-run（不改 target）：

```powershell
.\.venv\Scripts\python.exe scripts\apply_tdcc_shareholding_candidate.py `
  --candidate output\data_completion_20260909\tdcc\tdcc_1-5_20260904_ready_import.csv `
  --manifest output\data_completion_20260909\tdcc\tdcc_1-5_20260904_manifest.json `
  --target-db D:\Min\Python\Project\FA_Data\sqlite\twstock.db
```

Root 完成正式 DB 備份、確認 4 筆 quarantine 不納入後，才可使用明確 token 與備份路徑執行 apply：

```powershell
.\.venv\Scripts\python.exe scripts\apply_tdcc_shareholding_candidate.py `
  --candidate output\data_completion_20260909\tdcc\tdcc_1-5_20260904_ready_import.csv `
  --manifest output\data_completion_20260909\tdcc\tdcc_1-5_20260904_manifest.json `
  --target-db D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --backup-db D:\Min\Python\Project\FA_Data\sqlite\backup\twstock_tdcc_20260909_preapply.db `
  --apply --confirm apply-tdcc-shareholding-candidate
```

此 apply CLI 只接受 manifest 綁定的 ready CSV；會先用 SQLite online backup（可涵蓋 WAL 可見列）建立 backup 並執行 `PRAGMA quick_check`，再在同一交易內檢查既有 row。數值／級距內容改變時，同一 `(stock_code, decision_date)` 整批拒絕，不會部分寫入；單純重新觀測造成的 `observed_at`／`available_at`／`available_date` 變化不會覆寫第一次 custody 時間。舊 formal table 若沒有 `observed_at`，apply 會在同一交易內加入該 nullable alias 欄位並保存 capture timestamp。root 執行前仍須依正式 DB 的實際 `TWStockConfig` 路徑確認 target/backup，並把執行結果與 backup hash 另存 QA evidence。

## 可重跑更新

已有 raw 時可完全離線重建 candidate：

```powershell
.\.venv\Scripts\python.exe scripts\capture_tdcc_shareholding_candidate.py `
  --raw-file output\data_completion_20260909\tdcc\tdcc_1-5_raw_20260909T050303Z.csv `
  --output-dir output\data_completion_20260909\tdcc
```

未提供 `--raw-file` 時，CLI 才會抓固定官方 endpoint；每次 capture 保存新的 raw bytes、SHA-256 與 observed timestamp。它沒有 `--apply`，不會自行開啟 SQLite 或正式排程。

對既有 raw 重建時，CLI 會重算 bytes SHA 並拒絕 metadata 不一致；若已有 capture metadata，也不能用 `--observed-at` 覆寫真實觀測時間。
