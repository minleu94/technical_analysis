# V2.2 每週 Evidence Review Runbook

> 日期：2026-07-12
> 用途：以真實時間建立 V2.2 的三週人工 weekly review history；本文件不是 scheduler 核准，也不授權對正式 DB 寫入。

## 1. 開始前的安全邊界

- 現況為 weekly `0/3 waiting_for_time`、multi-day `3/3 ready`、`production_scheduler_allowed=false`；不能 formal closeout。
- 此流程不產生交易建議、不串 broker、不自動交易、不自動套用 lifecycle action。
- `--save-history` 與 `--confirm-action-items` 只能在明確、可回溯且經人工核准的 working-copy DB 使用。正式 DB、production-like DB 與 scheduler write-mode 均不在本 runbook 的授權範圍。
- replay、fixture、單次 smoke、raw scheduled report 或手動補表不計入三週 Gate。每列只記錄該週實際取得的證據。

## 2. 每週固定操作順序

1. 確認本週觀察期間、reviewer 與 working-copy DB 路徑。確認 working-copy DB 與正式 DB 並非相同檔案；正式資料庫不得寫入。
2. 讀取當週 freshness、source coverage、scheduled dry-run / manual dry-run 與 Evidence Review dashboard。記錄 warning、blocking gap、degraded reason 與資料品質。
3. 先產生唯讀週報；不得帶 `--save-history` 或 `--confirm-action-items`：

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --db-path <working-copy-db> --plan-action-items --json-output
```

4. 檢查輸出：`write_performed=false`、`production_scheduler_allowed=false`，以及每個 manual lifecycle candidate 的 `apply_action=false`。不符合任一條件時，停止並在本週紀錄填入 follow-up；不寫 history。
5. 人工填寫本文件的週期紀錄格式，做出 reviewed / dismissed / follow-up 結論。結論只描述 evidence、quality、warning、來源與後續工作，不得寫成買賣、倉位或 lifecycle 指令。
6. 取得本週 append-only 保存的明確人工核准後，才在同一 working-copy DB 保存 history：

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --db-path <working-copy-db> --save-history --action-owner <owner> --json-output
```

7. 將輸出的 review ID / hash / status 記入週期紀錄，並以唯讀方式核對：

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> --db-path <working-copy-db> --list-history --json-output
```

8. 記錄下一步與本週 backup / rollback / recovery 演練狀態。三週都完成後，仍須人工彙整 scheduler approval package；不可自動進入 formal closeout。

## 3. 固定三週人工紀錄格式

下表必須完整填寫三列。`待執行` 不是通過；若未保存 history，`--save-history` 欄必須填入拒絕原因而非虛構 review ID。

| 週次 | 週期日期 / review timestamp | 資料 freshness 與 quality | dry-run 狀態 | warnings / blocking gaps | reviewed / dismissed / follow-up | action owner | working-copy DB path 與隔離確認 | `--save-history` 結果 | backup / rollback / recovery | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|
| Week 1 | `<YYYY-MM-DD>.. <YYYY-MM-DD> / <timestamp>` | `<fresh / degraded / reason>` | `<dry_run / confirm / scheduler_allowed=false>` | `<逐項列出或 none>` | `<人工結論>` | `<姓名或角色>` | `<path>; 與正式 DB 不同=true>` | `<review_id/hash/status 或未保存原因>` | `<狀態與證據>` | `<可驗證下一步>` |
| Week 2 | `<YYYY-MM-DD>.. <YYYY-MM-DD> / <timestamp>` | `<fresh / degraded / reason>` | `<dry_run / confirm / scheduler_allowed=false>` | `<逐項列出或 none>` | `<人工結論>` | `<姓名或角色>` | `<path>; 與正式 DB 不同=true>` | `<review_id/hash/status 或未保存原因>` | `<狀態與證據>` | `<可驗證下一步>` |
| Week 3 | `<YYYY-MM-DD>.. <YYYY-MM-DD> / <timestamp>` | `<fresh / degraded / reason>` | `<dry_run / confirm / scheduler_allowed=false>` | `<逐項列出或 none>` | `<人工結論>` | `<姓名或角色>` | `<path>; 與正式 DB 不同=true>` | `<review_id/hash/status 或未保存原因>` | `<狀態與證據>` | `<可驗證下一步>` |

## 4. 三週完成後的判讀

只有三週都具備真實時間、人工 review 與 append-only history 時，weekly history 才能從 `0/3 waiting_for_time` 進入人工審查。即使三週齊備，下列項目未完成前仍不能建立 formal closeout：

- scheduler approval 未由授權 owner 明確核准；
- backup、rollback、recovery 演練未完成或無可追溯記錄；
- 任一週缺 owner、`--save-history` 結果、warnings 判讀或下一步；
- 將 raw report、replay、fixture 或人工補表當作真實週期。

在所有條件完成並獲人工核准前，維持 `production_scheduler_allowed=false`；production scheduler 若日後獲准，也只能保存 evidence，不得自動交易或套用 lifecycle action。

## 5. 排錯與停止條件

| 情況 | 必須動作 |
|---|---|
| `--help` 沒有顯示 `--save-history`、`--list-history` 或 `--action-owner` | 停止，不執行保存；確認目前程式碼與虛擬環境。 |
| working-copy DB 路徑等於或指向正式 DB | 停止，不使用 `--save-history` / `--confirm-action-items`；建立經核准的隔離副本後重做唯讀檢查。 |
| dry-run 輸出出現 `write_performed=true`、scheduler allowed 或 lifecycle `apply_action=true` | 停止，保留輸出作診斷；不得把該週列為通過。 |
| freshness / source coverage 有 blocking gap | 填入 follow-up 與 owner；不得以手動編輯或舊 report 補足。 |
| 無法寫入或 list history 找不到剛保存的記錄 | 填入未保存原因與 recovery follow-up；此週不計入三週 Gate。 |

## 更新記錄

- 2026-07-12：建立 V2.2 固定三週人工記錄格式與 working-copy weekly review 操作順序；明確保留 scheduler 未核准與不可 formal closeout 邊界。
