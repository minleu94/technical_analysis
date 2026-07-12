# V2.2 Engineering Readiness

> 日期：2026-07-12
> 狀態：**Engineering readiness recorded**；不得據此建立 formal closeout。
> 範圍：Evidence Operations 的 weekly review、append-only history、working-copy recovery 與 scheduler approval package 操作準備。
> 非範圍：正式 evidence DB 寫入、production scheduler、交易、broker、lifecycle action 與投資有效性。

## 1. 目前 Gate 狀態

| Gate | 目前狀態 | 判讀 |
|---|---|---|
| weekly history | `0/3 waiting_for_time` | 尚無三個真實且可稽核的 weekly review history；不得以 fixture、replay、單次 smoke 或手動改文件補足。 |
| multi-day dry-run | `3/3 ready` | 多日 dry-run 紀錄已達工程前置條件；它不取代 weekly history、manual review 或 action-item rhythm。 |
| scheduler | 未獲核准 | `production_scheduler_allowed=false`；既有排程只產生受控 freshness / dry-run 產物，不是 production evidence write-mode。 |
| formal closeout | 不可建立 | V2.2 尚缺三個真實週期、人工 review、backup / rollback / recovery 演練與明確 scheduler approval。 |

上述判讀與 `PROJECT_SNAPSHOT.md` 的目前狀態一致。`V2_2_EVIDENCE_OPERATING_LOOP_READONLY_CHECK_2026_07_07.md` 的正式 DB 唯讀檢查仍顯示 weekly history 為零；歷史 replay、simulated phase progress 與 raw scheduled report 沒有 official gate credit。

## 2. 已具備的工程操作能力

- `scripts/build_evidence_operations_weekly_review.py` 預設建立唯讀 weekly review JSON / Markdown；沒有 `--save-history` 與 `--confirm-action-items` 時不寫入 DB。
- `--save-history` 可在明確指定且經人工核准的 working-copy DB append-only 保存 weekly review snapshot；`--list-history` 以 SQLite read-only mode 檢查既有 history，缺 DB / table 只輸出 diagnostics，不建立目錄、schema 或 index。
- `--action-owner` 會保存 action-item owner；`--plan-action-items` 僅預覽。正式週期以同一次 `--confirm-action-items --save-history --action-owner` 寫入，將 confirmed action 的 owner / plan / write result 封存在 history snapshot。
- working-copy DB 必須與正式 DB 分離；production-like 路徑一律拒絕保存或 confirm，沒有 allow 旗標。既有 working-copy smoke copy/guard 是建立隔離副本的必要起點。
- recovery 操作與三週記錄格式見 `docs/07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md`；操作包只提供人工節奏，不改變 scheduler、資料庫或交易行為。

## 3. CLI 契約驗證

執行：

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --help
```

結果：2026-07-12 成功顯示 `--save-history`、`--list-history`、`--action-owner` 與 `--db-path`；`--help` 不再提供 production-like DB 繞過旗標。focused CLI 測試確認 production-like target 會在開檔前以 exit code `2` 拒絕，且 QA 暫存路徑沒有被建立為 DB。

## 4. 固定三週人工紀錄要求

正式 Gate 必須使用連續三個真實週期的人工紀錄。每一週均必填：

1. 週期日期與人工 review timestamp。
2. data freshness 與來源 / quality 判讀。
3. dry-run 狀態與 `production_scheduler_allowed`。
4. warnings、blocking gaps 與 degraded reason。
5. reviewed / dismissed / follow-up 的人工結論。
6. action owner。
7. working-copy DB 絕對或可追溯路徑，以及與正式 DB 分離的確認。
8. `--save-history` 結果（review ID / hash / status 或拒絕寫入原因）。
9. 下一步、backup / rollback / recovery 演練狀態。

可直接複製的三週模板、命令順序與拒絕條件收錄於 runbook。每一列只記錄同一週實際觀察到的資料；不得回填舊 raw report，也不得把未執行的寫入描述為已保存 history。

## 5. Formal Closeout 前的必要人工條件

- 三個真實 weekly periods 都有 append-only history 與人工 review，且沒有由 replay、fixture 或文件編修補入的紀錄。
- 每個週期的 action item 都有 reviewed / dismissed / follow-up 結論、owner 與下一步；沒有將 lifecycle candidate 自動套用。
- 完成 working-copy backup、rollback 與 recovery 演練，並記錄可驗證結果。
- scheduler approval package 完整，並由具權限的人工 owner 明確核准；在核准前維持 `production_scheduler_allowed=false`。
- formal closeout 另立有日期的 QA artifact，記錄人工 evidence、residual、non-goals 與 rollback commit SHA；本文件不能替代該 artifact。

## 6. 回退與追溯

- 本文件記錄的是工程與操作準備度，不宣稱 V2.2 version complete。
- 若 weekly runbook 或文件判讀需回退，回退本次文件 commit 並保留既有 evidence / review artifact；不得刪除正式資料、working-copy history 或用回退掩蓋人工記錄。
- 現況權威為 `docs/00_core/PROJECT_SNAPSHOT.md`；V2.2 maturity definition 為 `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`；正式使用順序為 `docs/07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md`。

## 更新記錄

- 2026-07-12：建立 V2.2 engineering readiness，固定三週人工紀錄欄位，記錄 weekly `0/3 waiting_for_time`、multi-day `3/3 ready` 與 scheduler 未核准邊界。
- 2026-07-12：reviewer P1/P2 修正 read-only history、owner snapshot trace 與 production-like hard reject；runbook 補上既有 copy/guard 操作。
