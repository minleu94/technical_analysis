# P0 官方來源 Evidence Refresh — 2026-08-30

## 結論

本次依既有 owner 授權執行一次 bounded、foreground、官方唯讀 probe，並載入既有
MOPS 季報 candidate。這次取得的是新的 machine evidence，不是 source acceptance；
`accepted=0`、`limited=0`、`downstream_eligibility=none`、`formal_oos_allowed=false`
與 `production_ingestion_allowed=false` 均維持不變。

本次 retry 的 machine matrix 為 `13/13` rows：`1 verified / 9 degraded / 3 missing`。
其中 3 個 `missing` 是本次請求日期的官方 `official_no_data`（`limit_lock`、
`institutional_flows`、`credit_transactions`），不是宣稱來源永遠不存在；下一個交易日
應以新的自然 observation 重試。`degraded` 主要仍是 publication timestamp／PIT 或
license／owner acceptance 尚未完成。

## 執行與 artifact custody

執行入口：

```powershell
.\.venv\Scripts\python.exe scripts\run_p0_source_evidence_audit.py `
  --decision-date 2026-08-30 `
  --live --confirm-live-readonly `
  --mops-quarterly-artifact <existing-validated-mops-candidate.json> `
  --output <TEMP>\p0_evidence_20260830_live_host_retry.json
```

| Artifact | 路徑 | SHA-256 |
|---|---|---|
| P0 live audit | `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_evidence_20260830_live_host_retry.json` | `594C6ED914FA250F0FDE715D7299ECF3FC66799F85EEB5A0B4F4CADAF34345EB` |
| Candidate intake | `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_candidate_intake_20260830_live_host_retry.json` | `B3370DC61EFBED3F203DC3498ECC6D26093EB5A8B1BC6B00C5841724CE904F28` |
| Owner packet | `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_owner_packet_20260830_live_host_retry.md` | `D73F1EE6C4794BE6596C022AD82B5E6DDCB02F3140F4136CA4C174DF50BF6F9F` |
| Intake readiness | `C:\Users\archi\AppData\Local\Temp\technical_analysis_p0_audit\p0_intake_readiness_20260830_live_host_retry.json` | `A8B36EF438F9E1D66E7659780E412BF744934A4BA3FB9F89003967E4261FF273` |

第一次在受限沙盒中執行的同日 artifact `p0_evidence_20260830_live_host.json` 只記錄
`network_error`，不取代既有成功 evidence，也不作為本節的 readiness 基線；它保留作
網路環境診斷。成功 retry 使用外部 bounded read-only connection 完成，並以不同檔名保存，
不覆寫任何舊 artifact。

## 本次 machine 結果

| Source | Machine status | Raw / accepted | 本次判讀 |
|---|---|---:|---|
| `corporate_action.ex_dividend_timeline` | `degraded` | `238 / 238` | 有官方列；publication timestamp 未證明 |
| `corporate_action.reduction_split_par_value` | `degraded` | `2 / 2` | 有官方列；publication timestamp 未證明 |
| `microstructure.suspended_halt_resume` | `degraded` | `1 / 1` | 有官方列；publication timestamp 未證明 |
| `microstructure.disposition_stock` | `degraded` | `2 / 2` | 有官方列；publication timestamp 未證明 |
| `microstructure.periodic_call_auction` | `degraded` | `2 / 2` | 有官方列；publication timestamp 未證明 |
| `microstructure.full_delivery` | `degraded` | `0 / 0` | response 可解析，但本次無列；仍需時間／覆蓋審核 |
| `microstructure.limit_lock` | `missing` | `0 / 0` | 官方 `official_no_data` for request date |
| `institutional_flows` | `missing` | `0 / 0` | 官方 `official_no_data` for request date |
| `credit_transactions` | `missing` | `0 / 0` | 官方 `official_no_data` for request date |
| `tdcc_shareholding` | `degraded` | `68,799 / 68,799` | 有官方列；publication／PIT／license 待審 |
| `twse.monthly_revenue_announcement` | `degraded` | `1,085 / 1,085` | 有官方列；current snapshot 不等於 historical PIT |
| `tpex.monthly_revenue_announcement` | `degraded` | `890 / 890` | 有官方列；current snapshot 不等於 historical PIT |
| `pit.quarterly_financials` | `verified` | `1 / 1` | MOPS candidate lineage 驗證通過；license／owner 仍待決 |

合計 row conservation：raw=`71,020`、accepted=`71,020`、quarantine=`0`、blocked=`0`。

## Owner／license handoff

本次已由成功 audit 產生 5 組 owner question、13 份 dossier；intake readiness 為
`deferred`、`owner_review_ready=0`、`deferred=13`。這表示 machine evidence 已可供
逐組審查，但仍不能由程式代填：

- source owner／license reviewer 必須具名。
- 每個 source 要綁定 publication／coverage／missingness／PIT／quality／license evidence。
- `accepted`／`limited` 必須使用 append-only decision revision，並綁定 dossier evidence。
- 缺證據或仍有 blocker 時維持 `deferred`／`blocked`；不可用這次的 verified／degraded
  machine status 自動升格。

## 下一步

1. 先請 owner 逐組回覆 packet 的 5 組問題；本次工程已把 machine facts 與人工作業分開。
2. `limit_lock`、`institutional_flows`、`credit_transactions` 在下一個自然交易日重新 probe，
   不以本次 `official_no_data` 回填歷史或推算數值。
3. 在 owner decision 與 evidence 完成前，不建立正式 source acceptance、Formal input、
   Paper fill、Scoring、Advice、scheduler 或 broker 權限。

## 安全與回滾

本次只新增 TEMP candidate artifacts；沒有寫正式 SQLite、SourceAcceptanceDecisionRegistry、
Evidence DB 或 repository source。若需回滾，刪除本節列出的四個 retry artifact 與同日
`p0_evidence_20260830_live_host.json` 即可；不得刪除既有成功 evidence 或原始資料。
