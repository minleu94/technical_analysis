# TWSE T86 Candidate Recovery Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立固定最近 20 個已完成交易日的 TWSE T86 official raw-envelope candidate recovery pilot。

**Architecture:** 使用全新 candidate-only contracts、transport 與 normalizer，避免改動既有正式 ingestion／EV2 registry。CLI 只讀 trading-date/universe SQLite，所有 response bytes 與報告只寫明確 DEVELOPMENT_OUTPUT_ROOT，並以 immutable content-addressed artifacts 保存。

**Tech Stack:** Python 3.11、dataclasses、requests、sqlite3、pytest、Decimal/integer parsing。

## Global Constraints

- 固定 shared `dev`，不切 branch/worktree，不碰 T3 Research Console/UI 檔案。
- source status 固定 deferred；`source_accepted=false`、`formal_validation_allowed=false`。
- 不寫正式 DB/DATA_ROOT，不觸發模型、Score、Recommendation、Portfolio、scheduler。
- observation date 與 retrieved/first-observed timestamp 分離；歷史 available_at 不推測。

---

### Task 1: Candidate contracts and normalization

**Files:**
- Create: `data_module/twse_t86_candidate_contracts.py`
- Create: `data_module/twse_t86_candidate_normalizer.py`
- Test: `tests/test_twse_t86_candidate_normalizer.py`

- [ ] 先寫正常、missing、subtotal、duplicate/conflict、schema drift 與 row conservation tests。
- [ ] 執行 targeted test，確認因 module/API 尚不存在而 RED。
- [ ] 實作 immutable envelope metadata、integer-safe normalizer 與 diagnostics。
- [ ] 重跑 targeted test，確認 GREEN。

### Task 2: Bounded official fetch and immutable raw writer

**Files:**
- Create: `data_module/twse_t86_candidate_source.py`
- Test: `tests/test_twse_t86_candidate_source.py`

- [ ] 先寫 retry/429/5xx/timeout、HTML/empty、hash/idempotency/no-overwrite tests。
- [ ] 確認 RED 後實作 bounded transport、attempt observations 與 content-addressed raw writer。
- [ ] 重跑 targeted test，確認 GREEN。

### Task 3: Twenty-day orchestration and reports

**Files:**
- Create: `scripts/recover_twse_t86_candidate.py`
- Test: `tests/test_recover_twse_t86_candidate.py`

- [ ] 先寫 frozen 20 dates、partial failure、coverage/universe、manifest flags、zero-production-write tests。
- [ ] 確認 RED 後實作 CLI orchestration、manifest、coverage/schema/revision/rate-limit 與 deferred dossier。
- [ ] 重跑 targeted test，確認 GREEN。

### Task 4: Bounded live pilot, QA, and exact commit

- [ ] 在獨立 DEVELOPMENT_OUTPUT_ROOT 執行真實 20 日 bounded CLI，fixture 與 live 證據分開。
- [ ] 驗證正式 DB bytes/mtime/hash 零變更，執行 targeted pytest、py_compile、targeted/full mypy 差異與 git diff boundary check。
- [ ] 精確 stage T4 檔案，檢查 cached names/diff，commit `feat(data): add TWSE T86 candidate recovery pilot`，不 push。
