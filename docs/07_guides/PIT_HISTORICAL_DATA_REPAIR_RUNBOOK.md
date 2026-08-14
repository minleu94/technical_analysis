# PIT 歷史資料修復 Runbook

## 1. 目的與邊界

本 Runbook 說明如何重跑月營收、季度財報與 corporate-action／restriction 的 PIT availability mapping、coverage audit，以及 `p0-ml-eligibility.v1` 投影。

本流程只建立可稽核 staging artifacts，不會：

- 猜測歷史公告日、publication／first-observed、available 或 revision 日期。
- 寫入正式 SQLite、raw source 或既有 availability mapping。
- 修改 B 已凍結的 dataset／trainer。
- 自動接受外部來源、接入 Score／Recommendation，或宣稱正式 OOS 成效。

## 2. 時間語意

- `period_or_event_date`：資料期間或事件本身日期，不代表市場當時已知。
- `announcement_at`：官方公告／publication 日期。
- `first_observed_at`：無官方 publication 證據時，可稽核的首次觀測日期；只能標 observed-only。
- `available_at`：系統在決策邊界可使用的日期，不得早於 announcement。
- `effective_from`／`effective_to`：事件或交易限制生效區間，不授予提前可見性。
- `revision`／`parent_revision`：append-only 版本鏈；後來版本不得覆寫舊 snapshot。

`2026-06-17` retroactive backfill、period end、filing deadline、檔名日期、mtime 與 FinMind `create_time` 都不是歷史 official announcement evidence。

### 正式 availability mapping provenance（`formal-availability.v2`）

新建立或新寫入 staging 的月營收／季報正式 mapping，必須逐列帶有：

- `availability_contract_version=formal-availability.v2`；
- `evidence_class=official_announcement` 與明確 `announced_date`；
- 可稽核的 `source_hash`（SHA-256）；
- append-only 的 `revision`／`parent_revision` lineage（初版為 `revision=1`、空白 parent）。

`first_observed`、`local_first_seen`、本機 observation 或 `manual.available_date_mapping` 類來源一律只屬 shadow／研究證據，不得作為正式 PIT mapping 的輸入。retroactive baseline 仍可保留為 degraded coverage，但不能轉換成歷史公告證據。

為了不倒退既有 Owner 可用性，僅目前已 materialize 的 2026-06 月營收 mapping 可走限縮 legacy compatibility：`twse.monthly_revenue_announcement / twse-openapi-t187ap05-l-2026-07-14` 與 `tpex.monthly_revenue_announcement / tpex-openapi-mopsfin-t187ap05-o-2026-07-14`。此例外是精確 source/version pair，不是新 ingestion 的模板；任何新 source snapshot 都必須使用 v2 provenance。

## 3. 隔離執行環境

```powershell
$slice = Join-Path $env:TEMP 'technical_analysis_parallel\E2\coverage-closeout'
$env:TEMP = Join-Path $slice 'temp'
$env:TMP = $env:TEMP
$env:OUTPUT_ROOT = Join-Path $slice 'output'
New-Item -ItemType Directory -Force $env:TEMP,$env:OUTPUT_ROOT | Out-Null
```

所有 mapping／coverage／eligibility 輸出都必須傳入 explicit output path。不得使用正式 `OUTPUT_ROOT` 預設值執行本流程。

## 4. 季度財報 mapping

```powershell
.\.venv\Scripts\python.exe scripts\build_quarterly_statement_availability_history.py `
  --statement-keys-json <explicit-staging-input> `
  --evidence-json <explicit-staging-evidence> `
  --feature-cutoff 2024-12-31 `
  --output-root (Join-Path $env:OUTPUT_ROOT 'quarterly')
```

輸出 mapping、coverage、manifest。缺 publication／first-observed 或 explicit available date 的 natural key 保持 unmatched；個別／合併 statement scope 不得 cross-match。

## 5. Corporate-action／restriction timeline

```powershell
.\.venv\Scripts\python.exe scripts\build_corporate_action_availability_history.py `
  --evidence-json <explicit-staging-evidence> `
  --coverage-json <explicit-source-coverage> `
  --as-of-date 2024-12-31 `
  --output-root (Join-Path $env:OUTPUT_ROOT 'corporate')
```

Restriction release 必須是新事件。日期 window 沒有 event rows 不能推論為 clean；source coverage 未證明時維持 `coverage_unknown`。

## 6. P0 ML eligibility

```powershell
.\.venv\Scripts\python.exe scripts\project_p0_ml_eligibility.py `
  --candidates-json <explicit-candidate-input> `
  --mapping-hashes-json <explicit-mapping-hashes> `
  --corporate-coverage-json <explicit-source-coverage> `
  --mode strict `
  --output-root (Join-Path $env:OUTPUT_ROOT 'eligibility')
```

- Strict：unknown corporate coverage 直接 blocked。
- Research：可標 degraded，但 `formal_oos_allowed=false`。
- Retroactive baseline、unmatched mapping、future revision 或 `available_at > feature_cutoff` 一律 blocked。
- Artifact hash 不含 machine-specific output path。

此 artifact 只供未來新 dataset generation 選擇是否消費；不得用它覆寫 B frozen dataset。

## 7. 正式 DB 唯讀 coverage audit

```powershell
$db = 'D:\Min\Python\Project\FA_Data\sqlite\twstock.db'
$report = Join-Path $env:OUTPUT_ROOT 'formal-coverage-2024-12-31.json'
.\.venv\Scripts\python.exe scripts\audit_pit_historical_coverage.py `
  --db-path $db `
  --audit-cutoff 2024-12-31 `
  --output $report
```

工具以 SQLite URI `mode=ro` 開啟既有 DB。DB 不存在時 fail closed，且不建立檔案。報告依 family／source／year 輸出：

- `total`
- `matched_official`
- `matched_observed_only`
- `unmatched`
- `future_blocked`
- `revision`
- `eligible`

正式表缺 revision 欄位時，`revision=0` 必須搭配 `revision_column_missing` blocker 解讀，不能宣稱「已證明沒有 revision」。Corporate table 不存在時為 `coverage_deferred`／`coverage_unknown`；0 rows 不代表 clean。

## 8. 人工來源決策包

任何來源只能由人工選擇 `accepted`、`limited`、`rejected` 或 `deferred`。決策前至少需要：

1. License／使用條款與保存權限。
2. Source id、version、hash 與可重跑取得方式。
3. 逐年 coverage、unmatched samples hash、duplicate／revision evidence。
4. Publication／first-observed／available 時間語意證明。
5. Coverage 門檻、完成規則與失敗降級方式。

本 E2 closeout 不把任何來源標為 accepted。

## 9. Production apply Gate

Production backfill／migration 是新任務，至少需要：

1. 明確人工核准與 accepted／limited source decision。
2. 正式 DB 備份與 hash／mtime／row-count 基線。
3. Working-copy dry-run、row conservation、逐表 diff 與 unmatched review。
4. Apply command 的 explicit confirmation token。
5. Apply 後唯讀 audit與可執行 rollback。

本 Runbook 沒有授權或隱含執行 production apply。

## 10. 排錯

- `source_table_missing`：正式 DB 尚無該 family；保持 deferred，不補 0。
- `revision_column_missing`：無法稽核 revision；不得把 revision count 0 解讀為完整。
- `coverage_unknown`：label window fail closed；補 coverage evidence，而非修改 eligibility 結果。
- `available_before_announcement`：拒絕 row，檢查來源欄位映射。
- `retroactive_backfill_not_historical_availability`：資料只能作 degraded baseline，不能進歷史 PIT feature。
