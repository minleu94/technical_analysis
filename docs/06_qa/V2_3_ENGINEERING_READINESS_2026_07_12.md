# V2.3 P0 Data Credibility Engineering Readiness

> 日期：2026-07-12
> 狀態：`engineering_readiness_only` / `requires_human_acceptance`
> 前一可回滾提交：`498ba8b6d7c7d70748213030288171bfae878515`
> 正式 closeout：未建立

## 結論

V2.3 已建立 P0 source-by-source 人工決策台帳，將 Gate 3 的每個目前未決來源標示為 `requires_human_acceptance`。這是工程 readiness 文件，不是 V2.3 formal closeout：沒有來源被標示為 accepted、沒有新增正式 ingestion、沒有新增 `ScoringEngine` feature、沒有 scheduler 核准，也沒有投資有效性結論。

## 已交付的決策證據

- [V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md](V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md) 逐一列出 corporate action、交易限制、三大法人、信用交易、TDCC 與 PIT fundamentals 的 source id、用途、available-date、quality、license、missing / outage policy、candidate status、人工作業、owner / date 與 downstream eligibility。
- 所有尚未決策列的 `human decision` 均為 `requires_human_acceptance`，`downstream eligibility=none`。
- 台帳明確區分 `decision_ready_candidate` 與人工接受：前者僅代表單次候選資料通過自動診斷，不能成為 accepted feature。
- 未建立「暫時 accepted」或預設 owner / date；未指定的人類決策資料保持未填，避免偽造 formal evidence。

## Candidate boundary 驗證

執行：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_source_candidate_readiness.py --help
```

結果：PASS。help 明確描述為「Read-only Phase 3C source candidate readiness dry-run」，可用選項僅為 `--sample`、唯讀 `--db-path`、`--decision-date`、`--format` 與 `--output`。沒有 `--confirm`、`ScoringEngine` write 或 scheduler enablement 選項。

既有 service access boundary 亦固定為：

- `writes_allowed=false`
- `production_scheduler_allowed=false`
- `scoring_engine_write_allowed=false`
- `investment_effectiveness_claim=false`

## 未完成的正式 Gate

下列工作必須由具名人工決策人以真實來源證據完成，不能以 fixture、candidate sample、文件改字或單次 CLI 成功替代：

1. 對每個 P0 source 審核授權、使用範圍、rate limit、版本、freshness、coverage 與 quality。
2. 審核 PIT 語意、公告 / 可得日與 `available_date <= decision_date` 的 look-ahead 證據。
3. 對 missing / outage、quarantine、retry 與 stale behavior 作出可稽核決議。
4. 填入決策人、日期與 `accepted` / `limited` / `rejected` / `deferred` 結論，並僅在明確許可時指定 downstream eligibility。
5. 如需 formal closeout，另建立具真實人工證據與 rollback commit SHA 的正式 closeout 文件；本文件不得替代該紀錄。

## 範圍外與安全邊界

- 不修改 production DB、raw data、SQLite schema、來源 adapter、策略、評分、threshold、profile 權重、portfolio 或 lifecycle。
- 不啟用 production scheduler、不串 broker、不自動交易、不自動平倉。
- 既有 registry 的 `ready` / `partial` 是 capability metadata；不是本次 V2.3 的人工接受結論。
- `unregistered.pit_quarterly_financials` 僅是台帳的待登錄識別字，不能被當成可呼叫的資料來源或 adapter。

## 驗證紀錄

| 檢查 | 結果 | 說明 |
|---|---|---|
| `inspect_source_candidate_readiness.py --help` | PASS | 只揭露 candidate dry-run / diagnostics 邊界。 |
| 文件欄位完整性 | PASS | 台帳每列均具 task 要求的 11 項欄位。 |
| 未決狀態檢查 | PASS | 無 `accepted`；所有未決來源均為 `requires_human_acceptance` 且 eligibility 為 `none`。 |
| `git diff --check` | PASS | 最終文件變更沒有空白錯誤。 |
