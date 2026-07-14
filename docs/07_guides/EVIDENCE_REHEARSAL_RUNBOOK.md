# Controlled Evidence Rehearsal Runbook

> 本 Runbook 僅適用於工程／歷史 replay 演練。rehearsal、fixture 與 shadow comparison 都不是 forward、paper、live 或正式產品證據。

## 執行模式與安全邊界

CLI 有兩種模式：

- `projection_only`（預設）：只讀 scenario 與 replay summary，不開啟、不複製、不寫入資料庫。
- `working_copy_e2e`：以 SQLite read-only URI 開啟 source，使用 SQLite backup 建立 working copy，並由真實 `EvidenceRehearsalOrchestrator`、historical replay、P0 comparison、ML comparison、lineage verifier 與 rehearsal service 產生報告。所有 replay 寫入與 mutation 都只能發生在 working copy。

共同限制：

- `--source-db` 必須存在；`--working-copy-db` 必須不同於 source，且位於 `DATA_ROOT` 之外。
- `--output-root` 與 working copy 必須使用明確的 temp／工程演練位置，不得指向 production-like 路徑。
- source 以 `mode=ro`／`query_only` 邊界讀取；報告必須維持 `source_db_write_performed=false` 與 `production_db_write_performed=false`。
- working copy 已存在時預設拒絕覆寫；只有明確加上 `--overwrite-working-copy` 才能重建該演練副本。
- `formal_product_closeout` 與 `production_actions_allowed` 永遠為 `false`。

## 輸入

| 參數 | 契約 |
|---|---|
| `--scenario` | JSON object，至少包含 `scenario_id`、ISO `decision_date`，可選 `tier`。 |
| `--source-db` | SQLite fixture 或經核准的唯讀來源。不得同時作為 working copy。 |
| `--working-copy-db` | 僅供演練寫入的副本，必須位於 `DATA_ROOT` 之外。 |
| `--replay-summary` | Historical replay JSON summary；可含 `p0_shadow_observations`。 |
| `--start-date` / `--end-date` | working-copy E2E 的 replay 範圍；`end-date` 必須與 scenario decision date 一致。未指定時兩者都取 decision date。 |
| `--ml-evidence-root` | 可選目錄；其中必須有 `rehearsal-ml-input.json`。僅在 working-copy E2E 使用。 |
| `--output-root` | 寫出 JSON、Markdown 與 pending handoff 的目錄。 |

`rehearsal-ml-input.json` 必須提供 frozen、shadow-only、production-ineligible manifest，以及 `accepted_rows`、`rejected_rows`、`predictions`、可選 `training_as_of`。輸入自報的 `status` 會被忽略；狀態必須由 manifest、available-date／label maturity boundary 與 shadow prediction 安全旗標重新計算。不安全 manifest、prediction 或格式直接 fail closed。

## working-copy E2E 範例

```powershell
$tempRoot = Join-Path $env:TEMP "evidence-rehearsal"
.\.venv\Scripts\python.exe scripts\run_evidence_rehearsal.py `
  --execution-mode working_copy_e2e `
  --scenario "$tempRoot\scenario.json" `
  --source-db "$tempRoot\source-fixture.db" `
  --working-copy-db "$tempRoot\working\rehearsal.db" `
  --replay-summary "$tempRoot\replay-summary.json" `
  --start-date 2026-07-12 `
  --end-date 2026-07-12 `
  --ml-evidence-root "$tempRoot\ml-evidence" `
  --output-root "$tempRoot\reports"
```

## 報告判讀

`rehearsal-report.json` 使用 contract v2，重要欄位包括：

- `execution.service_call_facts` 與 `execution.adapter_statuses`：哪些真實服務已呼叫，以及成功／缺輸入／失敗狀態。
- `source_snapshot`：唯讀 source 的 schema fingerprint、row counts 與 diagnostics。
- `historical_replay_artifacts`、`coverage`：working-copy replay 的實際 artifacts 與覆蓋投影。
- `lineage.artifact_dag`、`lineage.artifact_hashes`：本次實際產物的 lineage；缺 stage 時保持 `incomplete`。
- `p0_source_shadow`、`ml_shadow`：由比較服務計算的結果，不接受 supplied status 代替驗證。
- `blockers`：任何缺輸入、PIT、schema、label maturity 或 lineage 阻擋。
- `formal_product_closeout=false`、`production_actions_allowed=false`：不可由此 CLI 升格。

`rehearsal-report.md` 是人工摘要；`forward-handoff.json` 必須保持 `forward_handoff_pending`。process exit code `0` 只表示工程演練封包已產生，不表示 external、forward、paper、live 或產品 gate 完成。

## 故障注入

`--inject-failure` 只允許搭配 `working_copy_e2e`；projection-only 會直接拒絕。每次只能注入一種：

| 故障 | 實際 mutation／boundary | 真實 detector |
|---|---|---|
| `missing_day` | 從 working-copy `daily_prices` 刪除 scenario decision day；source 不變。 | Historical replay 交易日缺口檢查。 |
| `source_outage` | 由受控 source gateway 回報 failure，不建立替代來源。 | Source adapter／rehearsal service。 |
| `future_available_date` | 將 P0 observation 的 available date 推至 decision date 之後。 | P0 source shadow comparison。 |
| `schema_missing` | 只在 working copy 將 `daily_prices` 改名。 | Historical replay schema 檢查。 |
| `immature_label` | 注入結構化 rejected ML row 與 `label_not_mature` diagnostics。 | ML rehearsal comparison service。 |

範例：

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_rehearsal.py `
  --execution-mode working_copy_e2e `
  --scenario "$tempRoot\scenario.json" `
  --source-db "$tempRoot\source-fixture.db" `
  --working-copy-db "$tempRoot\working\missing-day.db" `
  --replay-summary "$tempRoot\replay-summary.json" `
  --output-root "$tempRoot\missing-day-report" `
  --inject-failure missing_day
```

## 回滾與清理

資料層回滾只需刪除本次明確指定的 temp working copy 與 temp output；不得刪除、移動或修改 source DB／`DATA_ROOT`。working-copy mutation 不會回寫 source。程式回滾應針對本 slice 的 atomic commit 進行，不得以清理分支為名覆寫其他未提交變更。

## 尚未完成的 gate

本流程只完成 engineering real-E2E 能力。下列項目維持 pending：外部來源與授權核准、真實 forward observation、paper/live 操作、scheduler、正式 source acceptance、ML promotion、Advice／Portfolio／broker production action，以及 formal product closeout。
