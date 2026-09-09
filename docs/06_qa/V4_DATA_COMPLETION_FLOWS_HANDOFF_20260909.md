# V4 flows 資料補齊交接（2026-09-09）

本片由 Formal/Paper owner 負責 `institutional_flows` 與 `credit_transactions`。集保、月營收、季報及共用 freshness／UpdateService 不在本片範圍；本文件不代表那些資料已完成。

## 實際來源與保存

以 2026-09-08 為最後可取得的完整交易日，向官方 TWSE／TPEx 來源向前取得 10 個交易日：

`2026-08-26, 2026-08-27, 2026-08-28, 2026-08-31, 2026-09-01, 2026-09-02, 2026-09-03, 2026-09-04, 2026-09-07, 2026-09-08`。

每個交易日保存四個 bounded HTTP response 及 metadata，來源為：

- TWSE T86（`twse:T86`，法人數量單位為 shares）。2026-09-08 raw SHA-256：`c9b55ec51872e5882762564f10f52dfc198dd046bf650064c42909c6716db0b5`。
- TPEx 三大法人（`tpex:3itrade`，shares）。2026-09-08 raw SHA-256：`afd5ea12b6a99a84f9c34862f473965dd8f1f0011c37a142fde3d8851d7b0eb7`。
- TWSE 融資融券（`twse:MI_MARGN`，官方交易單位 trading units）。2026-09-08 raw SHA-256：`cba697c208c6999f7ca79f3454f64e284a00ccf3fb8770e22b13e569032f73d0`。
- TPEx 融資融券（`tpex:margin_bal`，官方張數 lots）。2026-09-08 raw SHA-256：`4c84ae72d62952d242089511dd52d231afca90a27f581e514e5698f77357744b4`。

完整保存根目錄為：

`output/data_completion_20260909/flows/runs/20260909T051132394061Z/`

正式套用使用的 manifest 是：

`output/data_completion_20260909/flows/runs/20260909T051132394061Z/manifest.json`

SHA-256：`2c25065e529e38a23dc6e773a236a05bd7a681cc37fafbeeb239d4cfdfba548a`。

曾以原始 response 重播建立含明確 observed-at 的候選副本，未重新 GET、未覆寫 raw：

`output/data_completion_20260909/flows/runs/20260909T051132394061Z/manifest_with_observed_at.json`

SHA-256：`308169e7b42b65b0614bf08dd74942d925b1caeed380a67eadc9bb97625a4e41`。

兩版 candidate row 都保存 `values.observed_at`；root 的正式 receipt 指向前者，且 live readback 已確認兩張表所有寫入列都有非空 `observed_at`。

## 解析結果與可用邊界

10 日合計為 `institutional_flows=229,472`、`credit_transactions=22,163`。法人與信用資料均依官方欄位解析；TWSE／TPEx 的數量單位保留在 provenance，不將 trading units 或 lots 靜默換算成 shares。

官方這批回應沒有可驗證的公告日期欄位，因此全部列的 `available_date` 保持 `NULL`，只記錄實際 HTTP 完成時間 `observed_at`。這些資料可供目前查詢與顯示；未取得公告時間前，不授予歷史 PIT／ML training credit，也不把 observed date 冒充公告日期。

官方表中含 ETF、權證及其他非四碼商品代號，解析器保留原始官方列並在 manifest 明示：法人 37,519 個 distinct symbol 中 35,572 個非四碼；信用 2,219 個中 349 個非四碼。這些列沒有被假裝成一般股票，也沒有靜默刪除；下游若只顯示普通股票，必須在顯示邊界明確篩選。

候選 manifest 初始狀態為 `candidate_only=true`、`formal_apply_allowed=false`、`downstream_eligibility=none`；只有 root 的受控 apply wrapper 才能寫正式資料庫。

## 正式 apply readback

Root 已使用備份、heavy lock 及顯式 token 完成 apply，receipt：

`output/data_completion_20260909/flows/root_applied.json`

結果為 `251,635 inserted`、`0 duplicates`，`formal_credit_granted=false`。正式資料庫備份為：

`output/data_completion_20260909/backups/before_flows_20260909T051853.db`

root 的 live readback 另確認法人與信用所有列的 `observed_at` 非空，2330 的 2026-09-08 兩類資料可讀；`available_date` 仍為 `NULL`。

受控 apply 命令（需保留 root wrapper 的備份與鎖，不直接繞過）：

```powershell
.\.venv\Scripts\python.exe output\data_completion_20260909\apply_flows_verified.py output\data_completion_20260909\flows\runs\20260909T051132394061Z\manifest.json
```

重新抓取或重播命令如下；重播不連網、不改 raw：

```powershell
.\.venv\Scripts\python.exe scripts\complete_institutional_credit_flows.py capture --output-root output\data_completion_20260909\flows --as-of-date 2026-09-08 --sessions 10 --lookback-days 30
.\.venv\Scripts\python.exe scripts\complete_institutional_credit_flows.py rebuild --run-dir output\data_completion_20260909\flows\runs\20260909T051132394061Z
```

## 冪等與失敗安全

`data_module/institutional_credit_flows_service.py` 的 apply 會逐一驗證 raw bytes、metadata hash、candidate hash 及 manifest 子路徑 containment。相同 `source_version` 且數值完全相同的重跑列視為 duplicate，保留較早的 `observed_at`／`available_date`；數值或 source version 改變則 fail closed，不靜默覆寫正式列。候選資料不會因 CLI 存在而自動 promotion。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_institutional_credit_flows_service.py -q -o addopts= -p no:cacheprovider --tb=short
.\.venv\Scripts\python.exe -m mypy data_module\institutional_credit_flows_service.py scripts\complete_institutional_credit_flows.py --explicit-package-bases --follow-imports=silent
.\.venv\Scripts\python.exe -m py_compile data_module\institutional_credit_flows_service.py scripts\complete_institutional_credit_flows.py tests\test_institutional_credit_flows_service.py
```

本片測試結果為 `4 passed`，mypy 兩個 source 通過，py_compile 通過。正式 D 槽 apply、備份及 live readback 由 root 執行並另存 receipt；本 owner 沒有自行改寫 D 原始資料。
