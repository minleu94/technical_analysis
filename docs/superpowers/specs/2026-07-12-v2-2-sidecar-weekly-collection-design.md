# V2.2 Sidecar Weekly Collection Design

> 日期：2026-07-12
> 狀態：已取得使用者設計核准；等待 written spec review 後才進入實作。

## 目標

以 Windows Task Scheduler 在每週日 18:00（Windows 本機時間）自動蒐集 V2.2 Evidence Review 所需的 working evidence，保存為待人工審核的紀錄；不得每週複製正式 SQLite DB，不得修改 `twstock.db` 的 schema、資料或既有 table。

## 範圍與非目標

排程會讀取正式資料庫 `D:/Min/Python/Project/FA_Data/sqlite/twstock.db`，並將自動蒐集的 metadata、report payload、diagnostic、失敗資訊與人工審核狀態寫入 sidecar DB：

```text
D:/Min/Python/Project/FA_Data/sqlite/evidence_scheduler.db
```

本功能不建立 production evidence confirm scheduler、不寫 `twstock.db`、不建立 broker order、不自動交易、不修改 portfolio、不套用 lifecycle action、不更動 scoring 或推薦權重。

## 設計選擇

### 採用：sidecar collection store

每一個排程 run 建立唯一 `collection_id`，在 `evidence_scheduler.db` 寫入：

- collection / period / created timestamp、runner version、source DB canonical path 與 source DB SHA-256；
- source coverage、dry-run、smoke 與 weekly review 的 JSON payload / report 路徑；
- `collection_status`：`pending_human_review`、`completed_with_follow_up` 或 `collection_failed`；
- blocking gaps、warnings、error details 與 immutable run metadata；
- 對應人工 review 欄位：`reviewed_at`、`reviewer`、`review_decision`（`reviewed` / `dismissed` / `follow_up`）、人工 note 與 approval timestamp。

`twstock.db` 僅以 SQLite read-only URI 開啟。sidecar schema migration 僅建立 sidecar 自身 table，採 schema version / idempotent migration；失敗時寫 `collection_failed`，不自動 `DROP TABLE` 或刪除既有 collection。

### 不採用：直接寫入正式 `twstock.db`

雖然新 table 不會改動既有資料列，SQLite DDL / WAL / checkpoint 仍會修改同一正式檔案並可能影響其他讀寫工作；同時錯誤時的 `DROP TABLE` 會刪除稽核資料。因此此方案不採用。

### 不採用：每週完整 DB copy

既有正式 DB 約 3.3GB；每週 copy 的 I/O 與空間成本高。sidecar 只保存結果 metadata / JSON，不複製原始價格與交易資料。

## 排程與資料流

Windows Task 名稱為 `baldr-v2-2-weekly-collection`，每週日 18:00 執行。

1. 任務以當週週一至週日為 review period，並以最後一個可用交易日作為 decision date；找不到可用交易日則保存 `collection_failed` 與原因。
2. 程式以 read-only 連線讀取 `twstock.db`，執行既有 source coverage / evidence dry-run 所需的唯讀查詢，不對正式 DB create、alter、insert、update、delete 或 checkpoint。
3. 程式將集合輸出保存到 sidecar DB，並在 `D:/Min/Python/Project/FA_Data/output/scheduled/v2_2_weekly_collection/` 寫入 JSON / Markdown report 與 log。
4. 任一子步驟失敗時，sidecar 寫入 `collection_failed`、error type、error message、已完成 step 與 report path；任務以 nonzero exit code 結束。
5. 成功集合不代表 Gate 通過，而是 `pending_human_review`；排程不會呼叫 `--confirm-action-items` 或 `--save-history`，也不會自行填寫 reviewer、decision 或 approval。
6. 人工審核工具讀取 sidecar collection，將 review decision 與 note append / update 到 sidecar；只有人工 owner 明確核准後，才可由受控命令把核准結果寫入既有 weekly history 機制。

## Fail-closed 與回退

- source DB 不存在、不是 read-only、period 無可用交易日、sidecar migration 失敗、report serialization 失敗或任一 pipeline step error 時，任務不得建立 pending success，也不得啟用任何交易或 lifecycle 行為。
- 同一 collection identity 重跑必須 idempotent：不得建立重複成功記錄；失敗 retry 必須有新的 retry identifier 或明確 retry attempt。
- 回退是停用 / unregister Windows Task，並保留 sidecar 的 collection 與 error evidence；不自動 drop sidecar table。
- 若需要移除 sidecar DB，必須由人工在確認無需保留 audit evidence 後執行，不屬於排程自動行為。

## 驗證

- unit tests：period / decision-date 選取、source DB read-only、sidecar migration、idempotency、failed collection、禁止 production DB schema write、禁止 automatic manual approval。
- integration test：以 temporary source SQLite 和 temporary sidecar DB 執行成功 collection，確認 source schema / row count / file hash 不變、sidecar 包含 report 與 `pending_human_review`。
- scheduler wrapper test：dry-run 僅顯示 Task definition；register 後 query 確認 task name、weekly trigger、cmd wrapper 與非互動設定正確。
- manual acceptance：檢查 Task 的 Last Run Result、sidecar collection ID / status、report 與 log；人工審核後才建立 weekly history。

## 文件同步

實作時必須同步更新 `V2_2_WEEKLY_REVIEW_RUNBOOK.md`、`PROJECT_SNAPSHOT.md`、scheduler README 與 scheduler approval SOP，明確區分「自動 collection」與「人工核准 weekly history」，並保留 `production_scheduler_allowed=false`。
