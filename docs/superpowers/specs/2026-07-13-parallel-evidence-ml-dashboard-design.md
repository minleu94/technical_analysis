# 系統 Evidence／ML／Dashboard 平行推進設計

## 1. 目的

把 2026-07-13 系統狀態稽核轉成可由多個 Codex 長任務在同一個 `dev` working tree 內協作推進的工程方案，完整涵蓋：

1. Evidence Rehearsal 從投影 shell 修成真實唯讀 E2E。
2. 使用 2024 年（含）以前的 PIT 安全歷史資料建立 ML dataset、purged walk-forward 訓練與 2025 locked OOS。
3. 將券商分點路徑改為 SQLite-first、batch semantics、off-main-thread。
4. 將市場探索改造成整合 Dashboard，讓營收與三大法人狀態不再隱形。
5. 將目前只有 fetcher／candidate contract 的 P0 資料轉成可治理 ingestion 與歷史 PIT 修復工作。
6. 建立每日 ML shadow inference、prediction registry、drift／calibration 與 rule-only rollback。
7. 以獨立 integration 任務做跨工作流接線、全量 QA、文件 SSOT 與 closeout truth audit。

本設計的目標是「可自動運作的研究／Shadow 系統」，不是自動下單、production ML promotion 或投資有效性保證。

## 2. 核心設計決策

### 2.1 採用方案：共享 `dev` working tree、獨立 ownership、分波整合

採用一份 Master Plan 管理八條工作流。所有 worker 共用同一個 `dev` working tree，每條工作流仍只擁有自己的 exclusive 檔案集合、focused tests 與 closeout；跨工作流只透過明確 DTO／Protocol／artifact 交接。Worker 不操作 Git 狀態，單一 Git Coordinator 依 handoff queue 精確 stage、依序 commit 並 push `dev`。共享 UI 入口、正式 Recommendation 接線、中央文件與全量 QA 留給最後的 Integration 工作流。

未採用的方案：

- 單一巨型任務：context 過大、無法平行、難以定位回歸。
- 完全獨立且各自修改共享檔案：容易在 `ui_qt/main.py`、Decision Desk DTO、Recommendation 與中央文件發生並行覆寫或語意漂移。
- 先完成所有資料源再開始 ML：不必要地延後已有十年安全價量資料可完成的工作。

### 2.2 工作流

| ID | 工作流 | 主要產出 | 是否影響正式決策 |
|---|---|---|---|
| A | Evidence Rehearsal Real E2E | 真實 source DB read-only、adapter orchestration、lineage、real failure injection | 否 |
| B | Historical ML Shadow MVP | feature／label snapshot、dataset freeze、purged WF、2025 OOS、shadow model artifact | 否 |
| C | Broker Flow Performance | SQLite-first query、batch aggregation／semantics、worker、latency gates | 否 |
| D | Market Dashboard Visibility | 以既有 Decision Desk 作唯一市場總覽、營收卡、法人 source status | 否 |
| E1 | P0 Daily Source Ingestion | 三大法人、信用、TDCC current／range candidate ingestion 與 QA | 否；accepted 前 eligibility=none |
| E2 | PIT Historical Data Repair | 月營收／財報公告日、corporate-action label blocker、歷史 coverage | 否 |
| F | ML Daily Inference Operations | model load、每日 inference、prediction registry、drift、rollback | Gate 前否 |
| G | Cross-workstream Integration | 正式接線、全量 QA、SSOT 文件、truth closeout | 不提升 external Gate |

### 2.3 分波策略

```text
Coordinator Preflight（先做，短）
  確認目前 working tree 位於 dev、記錄 dev baseline、凍結 ownership / interface / handoff contract

Wave 1（可同時）
  A Evidence E2E
  B Historical ML Shadow MVP
  C Broker Performance
  E1 P0 Daily Source Ingestion

Wave 1b（可與 Wave 1 完全重疊，但不得碰 C 的 Smart Money 檔案）
  D 將既有 DecisionDeskView 接到 Market Exploration，並以自身 read-only visibility service 開發

Wave 2（依賴介面凍結）
  E2 PIT Historical Data Repair
  F ML Daily Inference（依賴 B 的 artifact／feature contracts）

Wave 3（不可提前）
  G 核對 dev 上已提交的 handoff slices / integration state，再執行 full QA / central docs / closeout
```

同時運行建議不超過四條實作工作流；第五條以上優先排成下一波，降低共享測試資源、SQLite fixture 與人工 review 壓力。Focused tests 可在 exclusive ownership 與隔離暫存目錄下平行；共用 Git index、全量 pytest／mypy、UI 全量 QA、正式資料 benchmark 與 Gate verifier 必須序列化。

### 2.4 共用 Working Tree 執行協議

- 所有 worker 固定在目前的 `dev` working tree；不得建立或切換 branch／worktree。
- 所有 worker 禁止執行 `git switch`、`git checkout`、`git branch`、`git worktree`、`git add`、`git commit`、`git push`、`git stash`、`git pull`、`git rebase`、`git reset`、`git revert`、`git cherry-pick`、`git merge`。子計畫或 Prompt Pack 內若仍有這些步驟，一律由本協議覆蓋，不得執行。
- Worker 只可平行修改其 exclusive ownership 檔案並執行 focused tests；共享檔案維持單一 owner與既定依賴順序。發現需要跨 owner 修改時停止該檔，登錄 blocker／adapter需求，不自行越界。
- 每個 `workstream/slice` 使用自己的 `$env:TEMP` 子目錄、`OUTPUT_ROOT`、pytest `--basetemp`與`-o cache_dir=...`；不得共用 temp DB、model artifact、benchmark output 或 pytest cache。
- Worker handoff 必須列出 `workstream_id`、`slice_id`、`handoff_status=ready_for_commit`、完整 `ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、實際 tests／結果與 blockers。交付後 worker 凍結該 slice，不再修改 ready files，直到 Git Coordinator 明確接受或退回。
- 單一 Git Coordinator 重新計算 SHA-256、核對 ownership／tests／blockers後，才可精確 stage handoff列出的檔案；共用 Git index 同一時間只由 Coordinator 操作。Coordinator 每次只處理一個 ready slice，依序 commit並push `dev`，再通知worker該slice已接受。
- A～F 任一工作流的必要slices全數push至`dev`後，Coordinator必須在TEMP handoff root產生 `<workstream_id>-final-committed.json`；七份final manifests是G進入寫入階段的hard gate，只有slice queue紀錄不算完成。
- Git Coordinator是互斥角色，不同時修改domain內容。全量pytest／mypy、UI全量QA、正式資料benchmark與Gate verifier使用global QA barrier：同一時間只跑一項，且run期間所有worker暫停repository寫入，確保驗證對應穩定快照。
- G 不整合任何 branch，也不執行 merge／cherry-pick；G 只核對 `dev` 上各 handoff對應的已提交檔案、commit queue紀錄與跨流整合狀態。

## 3. 資料與決策安全邊界

### 3.1 立即可用資料

- `daily_prices`、`technical_indicators`、`market_indices`、`industry_indices` 可建立 Core Long-History Model。
- 第一版 ML 將決策日 `T` 的 feature cutoff 固定為前一交易日 `T-1`；同日收盤值不進 `T` 的 feature，避免決策時間語意不清。
- Universe 必須按 decision date 重建，禁止以目前上市清單回套歷史。
- 2025 locked OOS的final fit固定`training_as_of=2024-12-31`；train row必須同時滿足`decision_date <= 2024-12-31`與`label.available_date <= 2024-12-31`，不可用2025才成熟的late-2024 label反向訓練。

### 3.2 不可混入 Core Model 的資料

- `fundamental_monthly_revenues` 與 `fundamental_statement_items` 的歷史 `available_date` 目前集中於 2026-06-17，修復前不得進 2024 訓練／2025 OOS。
- `broker_flows` 只涵蓋 2025-10-24 之後，必須是獨立 short-history add-on，不可把早期缺失補零。
- `institutional_flows`、`credit_transactions`、`tdcc_shareholding` 正式表目前為空；accepted 前不得進 Score／Advice。
- Corporate action／restriction coverage 不完整時，return label 必須標示 `research_only` 與 blocker，不得宣稱正式績效。

### 3.3 正式 Score 邊界

Gate 前保留目前 rule champion：pattern 3000 bp、technical 5000 bp、volume 2000 bp，以及既有 Regime 權重政策。Production blend的`alpha_bp`固定為0。B的research blend selection rows必須同時滿足`oof_decision_date <= 2024-12-31`與`oof_label_available_date <= 2024-12-31`，才可凍結research-only candidate並由2025 locked OOS評估；F可輸出shadow blend metadata，但不得改正式ranking，且本計畫不自動提升production alpha。

## 4. 跨工作流契約

### 4.1 Evidence 契約

```python
@dataclass(frozen=True)
class EvidenceRehearsalExecutionReport:
    scenario_id: str
    decision_date: str
    execution_mode: str
    source_db_opened: bool
    source_db_write_performed: bool
    working_copy_created: bool
    working_copy_write_performed: bool
    adapter_statuses: tuple[tuple[str, str], ...]
    artifact_dag: Mapping[str, tuple[str, ...]]
    artifact_hashes: Mapping[str, str]
    blockers: tuple[str, ...]
    formal_product_closeout: bool = False
    production_actions_allowed: bool = False
```

A 產生此報告；G 只負責把它接到 Workbench 與中央 closeout，不在 UI 重算 lineage。

### 4.2 Historical ML 契約

```python
@dataclass(frozen=True)
class HistoricalMLShadowRunReport:
    run_id: str
    dataset_id: str
    model_id: str | None
    training_end_date: str
    oos_start_date: str
    oos_end_date: str
    accepted_rows: int
    excluded_rows: int
    fold_ids: tuple[str, ...]
    metrics_bp: Mapping[str, int]
    blockers: tuple[str, ...]
    shadow_only: bool = True
    production_action_allowed: bool = False
```

B 產生 frozen dataset、model artifact 與此報告；F 只消費已凍結的 feature schema、artifact hash 與 model record，不重新 fit。

### 4.3 Broker Dashboard 契約

```python
@dataclass(frozen=True)
class BrokerFlowDashboardSnapshot:
    as_of_date: str
    period: str
    top_signals: tuple[FlowSignalDTO, ...]
    bottom_signals: tuple[FlowSignalDTO, ...]
    summary: SmartMoneySummaryDTO
    semantics_by_code: Mapping[str, SmartMoneySemanticSummary]
    tracked_branches: tuple[tuple[str, str], ...]
    quality: str
    warnings: tuple[str, ...]
```

C 擁有 query／batch semantics 與此 snapshot；既有 Smart Money tab消費它。D不修改或直接依賴C的新類別，因此C／D可完全平行；G最後驗證兩者共同存在。

### 4.4 Dashboard Visibility／Candidate Status 契約

```python
@dataclass(frozen=True)
class SourceVisibilityStatus:
    source_id: str
    as_of_date: str | None
    available_date: str | None
    row_count: int
    quality: str
    eligibility: str
    warnings: tuple[str, ...]
```

D擁有正式read-only `SourceVisibilityStatus`與市場摘要，即使row_count=0也必須顯示。E1另產生candidate-only `P0SourceCandidateStatus`，E2另產生`p0-ml-eligibility.v1`；G只能透過adapter整合，不能把candidate／eligibility冒充正式source observed。

## 5. 檔案 Ownership

| 路徑 | 唯一 owner | 其他工作流規則 |
|---|---|---|
| `scripts/run_evidence_rehearsal.py`、`app_module/evidence_rehearsal_*` | A | B/F 只提供輸入 artifact，不修改 CLI |
| `ml_module/purged_walk_forward.py`、歷史 dataset/trainer 新檔 | B | F 只消費，不改 split 語意 |
| `ml_module/model_prediction_registries.py`、daily inference 新檔 | F | B 以現有 public contract 寫 model metadata |
| `app_module/broker_flow_service.py`、`smart_money_semantic_service.py` | C | D 不修改 |
| `ui_qt/views/smart_money/*` | C | D保留既有drill-down，不修改Smart Money view |
| `app_module/decision_desk_*`、`app_module/market_data_visibility_*`、`ui_qt/views/decision_desk_view.py`、`ui_qt/views/workbench_view.py`、`ui_qt/main.py` | D | G只做必要composition整合修正 |
| `data_module/official_phase3c_fetcher.py`、`scripts/update_phase3c_candidates.py` | E1 | D不修改candidate ingestion；G日後adapter status |
| `data_module/monthly_revenue_*`、fundamental availability／corporate-action 新檔 | E2 | B 修復前排除這些 feature |
| `app_module/recommendation_service.py`、任何runtime／composition接線 | G | F只交中立projection DTO；不得讓app/runtime import ml_module |
| `PROJECT_SNAPSHOT.md`、Roadmap、Architecture、Documentation Index、`PROJECT_NAVIGATION.md` | G | 其他流只寫各自 runbook／QA closeout |
| `docs/07_guides/APPLICATION_MANUAL.md` | D（使用者可見 UI）後由 G reconcile | C 不同時修改 |
| `qa/full_app_healthcheck/test_inventory.py` | G | 其他流新增測試但不改 inventory |

任何工作流發現必須修改不屬於自己的共享檔案，先以新 Protocol／adapter 解耦；仍無法解耦時停止該修改並在 handoff 登錄，交由 G 依序整合。

## 6. 故障與降級設計

- 所有正式資料庫只允許 URI `mode=ro`；寫入測試只允許 `tmp_path`／明確 working-copy。
- Source outage、schema mismatch、future available date、immature label、artifact hash mismatch 必須由真實輸入觸發，不得只 append 預設 blocker。
- Broker／Dashboard 請求使用 request id；舊請求完成時不得覆蓋新日期結果。
- ML inference 遇到 schema、artifact、drift 或 model load 問題時回到 rule-only，不能回傳無版本預測。
- P0 ingestion 的 malformed rows 進 quarantine／diagnostics，不以 0 補值。
- Historical replay、OOS、scheduled dry-run、forward、paper、live tier 必須分離。

## 7. 驗證策略

每一工作流都必須遵循 RED → GREEN → focused suite → boundary checks → SHA-256 handoff；commit／push 只由 Git Coordinator 序列化執行：

- Python：`py_compile`、focused pytest、targeted mypy。
- 金融安全：`scripts/quant_guard_linter.py`、`scripts/check_ml_shadow_boundary.py`。
- UI：指定 Qt tests、Update Tab QA、off-main-thread／stale-result tests。
- 效能：固定 fixture 與 current read-only DB benchmark；warm p95 < 2 秒，loading state < 300 ms。
- 資料：row conservation、date coverage、available-date、missing/outage、source version。
- 整合：全量 pytest、全模組 mypy、encoding、relative links、Gate 2–7 verifier、`git diff --check`；上述重型 QA 由 G／Git Coordinator 取得單一執行槽後序列化執行。

## 8. 完成定義

只有同時滿足下列條件，G 才能建立工程 closeout：

1. A～F handoff的ready files與SHA-256都能對應到Git Coordinator已序列commit／push至`dev`的slice；沒有worker自行操作Git history。
2. 一個 command 能以真實唯讀 DB 產生 replay／source／ML／lineage report。
3. 2024 年底前資料完成 purged walk-forward，2025 locked OOS 只評估一次並保存 fingerprint。
4. 每日 inference 使用相同 feature builder，prediction append-only 且失敗回 rule-only。
5. Market Dashboard 顯示營收與法人 source status，missing／degraded 不隱形。
6. Broker Top/Bottom 不再先建立全部 semantics，GUI 不被同步工作阻塞。
7. 五種 Evidence failure、PIT violation、stale UI result、model schema mismatch 都有真實測試。
8. 中央文件只描述實際已驗證狀態；external／forward／promotion 仍保持 pending。G的最終slice也走相同handoff／Coordinator commit流程。

## 9. 非目標

- 不自動下單、不接 broker execution、不自動 rebalance／exit。
- 不把 historical replay 或 2025 retrospective OOS 稱為 forward evidence。
- 不讓 ML 自動修改 rule weights、Score、Portfolio 或 scheduler。
- 不為了 ML 直接採用目前 PIT 不合格的營收／財報。
- 不用 ETF 分離取代 query／batch／threading 的根因修復。
- 不因工程完成就把 P0 source、V3.3 或產品版本標成 formal closeout。
