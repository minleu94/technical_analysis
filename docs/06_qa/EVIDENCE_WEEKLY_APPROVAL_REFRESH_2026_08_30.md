# Evidence Weekly Approval Refresh — 2026-08-30

## 結論

本次以正式 output 下的 weekly collection sidecar 做唯讀重驗，並產生新的 owner／reviewer
approval input。8/30 自然 collection 已追加一筆真實週期，因此目前 sidecar 是
`10` 筆 `pending_human_review`；它們全部仍不計入 weekly Gate、Formal credit 或
production scheduler approval。

這一步完成了「可交給人審」的工程 handoff，但沒有代替具名 owner／reviewer 決策。packet
仍是 `candidate_only=true`、`write_performed=false`、`formal_credit_authorized=false`、
`production_scheduler_allowed=false`。

## 唯讀來源與 artifact

來源 sidecar：

`D:\Min\Python\Project\FA_Data\output\scheduled\v2_2_weekly_collection\evidence_scheduler.db`

本次 exporter 使用 SQLite URI `mode=ro` 與 `PRAGMA query_only=ON`；未寫入、migration、
delete 或 vacuum source sidecar。

| Artifact | 路徑 | SHA-256 |
|---|---|---|
| Sidecar（source observation） | `D:\Min\Python\Project\FA_Data\output\scheduled\v2_2_weekly_collection\evidence_scheduler.db` | `sha256:a6a7746fe40f6ca4d3c00d4bcb4d6c706a39f8b370be32973de7e4f361a5b7aa` |
| Approval input JSON | `C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\evidence_weekly_approval_input_20260830.json` | `sha256:EC3EBCFF169DC50A86EB91D6C948D6A09E0BFF0A2502813DCE4690781860931A` |
| Approval input Markdown | `C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\evidence_weekly_approval_input_20260830.md` | `sha256:CB9F3077D89C909D90C6C71C4DF144C02BDAA96AD8ABD3C5FF12908E1A077773` |

Exporter 產生時間為 `2026-08-31T04:16:35.634228+00:00`（America/Los_Angeles 的
2026-08-30 晚間）。packet 內 10 筆 period 由 `2026-07-06..2026-07-12` 延伸至
`2026-08-24..2026-08-30`；最後一筆的 last trading date 為 `2026-08-28`，因週末不
自行填造交易日。

## 審核狀態

| 欄位 | 本次值 |
|---|---|
| `record_count` | `10` |
| `pending_human_review_count` | `10` |
| `collection_failed_count` | `0` |
| `packet_status` | `needs_named_owner_reviewer` |
| `owner_review_ready` | 尚未具名，不能進入 approved projection |
| `formal_credit_authorized` | `false` |
| `production_scheduler_allowed` | `false` |
| `downstream_eligibility` | `none` |

每期必須由具名 owner／reviewer 填寫 `review_decision`、`reviewed_at`、`review_note`，
並檢查來源 freshness、quality、warnings、missingness、rollback 與 follow-up。只有另外
產生相容的 `approved-weekly-history-projection.v1`，才能更新 UI 的 approved weekly
顯示；即使如此也不授予 Formal credit。

## 為什麼這是進展但不是 Gate closeout

- 新增了真實自然週期，沒有 replay 或人工改數字。
- 10 筆 sidecar record 與 source hash 已集中到可審核 packet，減少「資料存在但不知道
  要審什麼」的落差。
- 仍缺具名 review、正式 approved projection、backup／rollback／recovery 與 scheduler
  approval；因此 weekly credit 仍保持 `0/3`，Formal／scheduler／broker 維持關閉。

## 下一步

1. 由 owner／reviewer 逐期完成 10 筆 review。
2. 取得下一個自然交易週期後，重跑同一唯讀 exporter；不清除歷史 sidecar。
3. review 完成後才走 approved projection 的獨立驗證；禁止直接修改 sidecar 或正式 DB。
