# Controlled Evidence Rehearsal Runbook

> 本 Runbook 僅用於工程／歷史 replay 演練，不是 forward evidence，也不是正式資料、策略、模型或 scheduler 的核准流程。

## 目的與責任人

- Owner：`human_evidence_operations_owner`。
- 目的：以既有 scenario 與 historical replay summary 產生可重跑的 rehearsal 報告與 forward handoff package。
- 完成定義：三份輸出均已產生、所有 blocker 已由人工檢閱，且 `forward-handoff.json` 仍為 `forward_handoff_pending`。
- 非完成定義：本命令不得把任何 product／external gate、scheduler、Advice 或 promotion 標示為完成。

## 前置輸入與安全條件

| 輸入 | 用途 | 安全要求 |
|---|---|---|
| `--scenario` | JSON object；至少含 `scenario_id`、`decision_date`，可選 `tier` | 僅讀取；`decision_date` 必須是 ISO 日期。 |
| `--source-db` | 現有 fixture 或核准來源 DB 的路徑 metadata | 必須存在；CLI 不開啟、不複製、不寫入。不可為 production-like 路徑。 |
| `--working-copy-db` | 預先規畫的 temp working-copy 路徑 metadata | 必須與 source 不同；CLI 不建立、不開啟、不寫入。不可為 production-like 路徑。 |
| `--replay-summary` | Historical replay JSON summary，以及可選的 `p0_shadow_observations` / `ml_shadow` 唯讀投影 | 僅讀取；`days` 必須是 list，資料日期需符合既有 adapter 的 PIT 規則。缺少 P0 或 ML 投影時，報告會明確列為 missing / `insufficient_sample`，不會以 fixture 補足。 |
| `--output-root` | 演練報告目錄 | 唯一允許寫入位置；不可為 production-like 路徑。 |

`production-like` 包含 `prod`／`production` 路徑 token，以及 `TWStockConfig` 的正式 `DATA_ROOT` 本身與所有子目錄（包括 `sqlite/twstock.db`）。若 source 與 working-copy 是同一路徑，命令會拒絕，並輸出 `working-copy DB must differ from source DB`。

## 執行命令

在 repository 根目錄執行；範例必須使用 temp working-copy 路徑：

```powershell
$tempRoot = Join-Path $env:TEMP "evidence-rehearsal"
.\.venv\Scripts\python.exe scripts\run_evidence_rehearsal.py `
  --scenario "$tempRoot\scenario.json" `
  --source-db "$tempRoot\source-fixture.db" `
  --working-copy-db "$tempRoot\working-copy\rehearsal.db" `
  --replay-summary "$tempRoot\replay-summary.json" `
  --output-root "$tempRoot\reports"
```

預設模式固定為 `dry_read_only`；沒有 confirm、apply、scheduler、broker、Advice 或 promotion 旗標。

## 輸出與判讀

| 輸出 | 內容 | 人工判讀 |
|---|---|---|
| `rehearsal-report.json` | scenario、固定 safety flags、replay coverage、13 個 P0 shadow projection、ML shadow projection 與 blockers | 確認所有 execution flags 都是 `false`；P0 或 ML 投影缺漏時狀態不得為 `complete`，並依 blocker 決定是否進入人工後續。 |
| `rehearsal-report.md` | 人可讀的 status、safety boundary、blockers 與 handoff 摘要 | 確認沒有被描述為 forward evidence 或正式完成。 |
| `forward-handoff.json` | 真實資料／授權／人工核准所需的 handoff | 必須維持 `forward_handoff_pending`；不得由本 CLI 自動完成。 |

成功產生報告時 process exit code 為 `0`；這只代表演練封包已生成。若 `status=degraded`，必須先處理或接受 blocker，不能把演練結果升格為正式證據。

若要在 Workbench 顯示最新的受控報告，僅能設定 `EVIDENCE_REHEARSAL_REPORT` 為此 CLI 產生之 `rehearsal-report.json` 絕對路徑。Workbench 只讀取 JSON，不開啟 source / working-copy DB；找不到或無法讀取時會顯示封鎖狀態，不會顯示 ready 或 forward evidence。

## 故障注入

故障注入只改變記憶體中的受控 DTO 投影，絕不修改 scenario、replay summary、source DB 或 working-copy DB。每次只能注入一種，且結果固定為 `degraded`：

| `--inject-failure` | 固定 blocker | 用途 |
|---|---|---|
| `missing_day` | `missing_required_adapter_output:source` | 驗證缺少來源日資料時 fail-closed。 |
| `source_outage` | `adapter_failure:source:source_outage` | 驗證來源不可用時不建立替代資料。 |
| `future_available_date` | `future_available_date:source-data` | 驗證 PIT 可得日落後時阻擋。 |
| `schema_missing` | `missing_field:source-data:source_version` | 驗證必要 schema metadata 遺失時阻擋。 |
| `immature_label` | `immature_label:ml-shadow` | 驗證未成熟 label 不得進入 forward handoff completion。 |

範例：

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_rehearsal.py --scenario "$tempRoot\scenario.json" --source-db "$tempRoot\source-fixture.db" --working-copy-db "$tempRoot\working-copy\rehearsal.db" --replay-summary "$tempRoot\replay-summary.json" --output-root "$tempRoot\future-date" --inject-failure future_available_date
```

## 回滾與清理

此 CLI 不寫資料庫，因此沒有 DB rollback。若要清理演練，僅刪除明確指定的 temp `--output-root`（以及外部流程建立的 temp working-copy，如有）；不得對來源 DB 或正式資料根目錄執行刪除。

若需要回滾程式與文件，使用 Task 7 atomic commit：

```powershell
git revert <task-7-commit-sha>
```

回滾後重新執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_rehearsal_cli.py -q -o addopts=
```

## 明確禁止事項

- 不得把正式 `twstock.db`、任何 production-like 路徑或 source DB 指為 working-copy／output target。
- 不得期待此 CLI 建立、複製、migrate 或寫入 working-copy DB。
- 不得啟用或建立 production scheduler task、broker 呼叫、Advice 呼叫、策略／模型 promotion、source acceptance、lifecycle transition 或資料 pruning。
- 不得把 replay、fixture、shadow comparison、缺失資料或未成熟 label 標為 forward／paper／live／formal product evidence。
- 不得以 0、平均數或未揭露 forward-fill 靜默掩蓋缺失資料。
