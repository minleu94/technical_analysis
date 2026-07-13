# Parallel System Execution Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以可平行、可隔離、可驗證的工作流，完成真實 Evidence E2E、歷史 ML Shadow、券商效能、Market Dashboard、P0/PIT 資料、每日 inference 與最終整合 closeout。

**Architecture:** 八條工作流各自擁有檔案與測試，只透過 frozen DTO／Protocol／artifact 交接；共享 UI、Recommendation、runtime 與中央 SSOT 文件由 Integration 工作流最後依序接線。執行分成 Wave 0～3，避免同時修改共享檔案與把工程 readiness 冒充 external validation。

**Tech Stack:** Python 3.11、PySide6、SQLite read-only／working-copy、dataclasses、Decimal／integer bp、scikit-learn shadow models、pytest、mypy、JSON／Markdown artifacts、Windows PowerShell。

## Global Constraints

- 回覆、文件與操作說明使用繁體中文；code identifier 保持既有英文慣例。
- 不刪除或改寫正式原始資料；正式資料根目錄由 `TWStockConfig` 決定。
- 正式 DB 只允許 read-only；寫入只允許 `tmp_path`、隔離 working-copy 或經明確人工確認的 candidate ingestion。
- 核心金融值禁止新增裸 `float`；使用 `Decimal`、整數 bp／股數／分。ML analytics float 必須隔離在 `ml_module`。
- 所有feature必須符合本模型的T-1 cutoff；所有label必須成熟後才能進fit／evaluation。2025 locked OOS final fit固定`training_as_of=2024-12-31`，train label的available date也不得晚於該日。
- 不修改正式 Score、Advice、Portfolio、scheduler、lifecycle 或 broker execution；ML 固定 shadow-only。
- Historical replay／retrospective OOS 不得標為 forward／paper／live evidence。
- 不覆寫使用者或其他 agent 的未提交變更；每個工作流使用獨立 `codex/` branch／worktree。
- 每一 task 必須 RED → GREEN、focused verification、`git diff --check` 後才 commit。
- 使用者已對本次八流計畫明確授權push；Prompt Pack只允許各任務push自己的`codex/` branch，禁止merge或push `dev`。若Prompt脫離本主控計畫另作他用，必須重新取得授權。

---

## 1. Design Authority 與子計畫

**Design authority：**

- `docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md`

**子計畫：**

| ID | 子計畫 | 建議 branch |
|---|---|---|
| A | `2026-07-13-evidence-rehearsal-real-e2e.md` | `codex/evidence-rehearsal-real-e2e` |
| B | `2026-07-13-historical-ml-shadow-mvp.md` | `codex/historical-ml-shadow-mvp` |
| C | `2026-07-13-broker-flow-performance.md` | `codex/broker-flow-performance` |
| D | `2026-07-13-market-dashboard-visibility.md` | `codex/market-dashboard-visibility` |
| E1 | `2026-07-13-p0-daily-source-ingestion.md` | `codex/p0-daily-source-ingestion` |
| E2 | `2026-07-13-pit-historical-data-repair.md` | `codex/pit-historical-data-repair` |
| F | `2026-07-13-ml-daily-inference-operations.md` | `codex/ml-daily-inference-operations` |
| G | `2026-07-13-cross-workstream-integration-closeout.md` | `codex/system-integration-closeout` |

**啟動 Prompt Pack：**

- `docs/superpowers/prompts/2026-07-13-parallel-workstream-start-prompts.md`

## 2. Parallel Wave Matrix

| Wave | 可同時執行 | 啟動條件 | 結束 Gate |
|---|---|---|---|
| 0 | Master owner 單獨 | 工作樹與 branch 基線可辨識 | ownership／interface freeze artifact 建立 |
| 1 | A、B、C、E1 | Wave 0 完成 | 每流 focused suite 綠燈、public contract 固定 |
| 1b | D 可與 Wave 1 同時 | D 只改 Decision Desk／Market Exploration／visibility owned files，不改 C/E1 files | 唯一Dashboard instance、PIT visibility與UI tests通過 |
| 2 | E2、F | F需B feature/model artifact contract；E2不改B frozen dataset | daily inference與PIT repair tests通過 |
| 3 | G 單獨 | A～F 都有 handoff + commit list + verification | full suite、SSOT、truth closeout 完成 |

### 工作類型、估計量與 Critical Path

| ID | 類型 | 粗估工程量 | Critical path | 兩天內合理成果 |
|---|---|---:|---|---|
| A | Evidence／orchestration | 5～8 engineer-days | G前置 | execution contract、read-only/working-copy、主要RED/GREEN slices |
| B | Data science platform／ML | 8～12 engineer-days | F、G前置 | feature/label contract、snapshot、split、dataset first build |
| C | Data access／performance／Qt | 6～9 engineer-days | G前置 | baseline、SQLite repository、batch query、worker first slice |
| D | Product UI／read model | 5～7 engineer-days | G前置 | visibility service、DecisionDesk schema、唯一instance first slice |
| E1 | External data／governance | 4～7 engineer-days | G前置 | parser fixtures、timestamp contract、working-copy safety |
| E2 | PIT data repair／audit | 8～17 engineer-days | 下一版fundamental ML | contracts、月營收/statement coverage與eligibility tooling；外部coverage可未完 |
| F | MLOps／shadow operations | 5～8 engineer-days | 依賴B contract、G前置 | artifact/registry/lifecycle fixtures；真實inference視B進度 |
| G | Integration／QA／docs | 3～5 engineer-days | 最後單線 | 只能先做readiness；正式closeout等A～F handoff |

這些是工程量，不是日曆承諾。兩個calendar days足以讓多條流完成contracts與首批可驗證切片，但不應承諾E2外部歷史coverage或整體G closeout必然完成。

### 48 小時主控排程（建議同時最多四條）

| 時段 | 主控動作 | 可執行工作流 | Checkpoint |
|---|---|---|---|
| H0～H2 | Wave 0：固定base SHA、ownership、branches、handoff格式 | Coordinator | 八份計畫與prompt存在，shared files owner唯一 |
| H2～H12 | 第一批平行啟動 | A、B、C、E1 | 每流第一個RED→GREEN contract commit；無shared-file越界 |
| H12～H24 | 深化第一批 | A、B、C、E1 | A read-only/working copy；B snapshot/split；C SQLite query；E1 parser/safety |
| H24 Gate | 檢查commit/tests/artifacts，不以口頭進度換流 | Coordinator | B fundamentals exclusion與artifact interface、各流rollback清單 |
| H24～H36 | 有slot才啟動第二批 | D可立即；E2在B exclusion contract後；F0～F3可用fixtures | 不打斷尚未形成可handoff commit的工作流 |
| H36～H48 | 完成slice與交接 | 依可用slot續跑A～F；G只做readiness matrix | 每流commit list、focused output、blockers、next exact task |

若只有四個執行slot，優先順序是A、B、C、E1；任一流完成可驗收handoff後，slot依序轉給D、E2、F。若有第五個以上隔離slot，D可從H2直接開工；不要因此讓G提前寫中央文件。

### 可以平行但要遵守的限制

- A／B／C／E1 完全不同 ownership，可直接同時開工。
- D 可與C／E1完全平行：直接重用既有`DecisionDeskView`作唯一市場總覽，並由自身read-only visibility service顯示正式表status；不得修改`broker_flow_service.py`、Smart Money子目錄或`official_phase3c_fetcher.py`。
- E2 可與 F 平行；B 已明確排除 fundamentals，因此 E2 不應改 B frozen dataset。
- F的artifact store／registry／lifecycle fixture可先開工；feature parity與真實inference必須等B artifact contract commit。F不必等待E2；新增資料源只建立未來dataset/model version。

### 不可平行

- B的feature／artifact contract尚未commit前，F不得實作feature transformation或真實inference；F0～F3 fixture工作可先做。
- C 與 D 不得同時修改 `ui_qt/views/smart_money/*`。
- D 與 G 不得同時修改 `ui_qt/main.py`、Decision Desk DTO/service、Application Manual。
- Recommendation／runtime wiring完全由G擁有；F不得修改，因此不存在跨層import或平行衝突。
- A～F 尚未提交 handoff前，不啟動 G 的中央文件與 full-suite closeout。
- 任一工作流不得自行修改 `PROJECT_SNAPSHOT.md`、Roadmap、Architecture、Documentation Index 或 `PROJECT_NAVIGATION.md`；全部由 G 一次同步。

## 3. Task 0：建立執行基線與 ownership freeze

**Files:**
- Create: `output/qa/parallel_execution_baseline.json`（ignored local output，不提交）
- Read: `docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md`
- Read: 本 Master Plan 與八份子計畫

**Interfaces:**
- Produces: 每個工作流的 base commit、branch、owned paths、dependency commit 與 handoff path。

- [ ] **Step 1: 確認 repository 基線**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/dev
git log --oneline --max-count=12
```

Expected: 工作樹狀態可解釋；若有既存變更，先記錄 owner，不得清除或覆寫。

- [ ] **Step 2: 確認所有計畫文件存在**

Run:

```powershell
$plans = @(
  'docs/superpowers/plans/2026-07-13-evidence-rehearsal-real-e2e.md',
  'docs/superpowers/plans/2026-07-13-historical-ml-shadow-mvp.md',
  'docs/superpowers/plans/2026-07-13-broker-flow-performance.md',
  'docs/superpowers/plans/2026-07-13-market-dashboard-visibility.md',
  'docs/superpowers/plans/2026-07-13-p0-daily-source-ingestion.md',
  'docs/superpowers/plans/2026-07-13-pit-historical-data-repair.md',
  'docs/superpowers/plans/2026-07-13-ml-daily-inference-operations.md',
  'docs/superpowers/plans/2026-07-13-cross-workstream-integration-closeout.md'
)
$missing = $plans | Where-Object { -not (Test-Path $_) }
if ($missing) { throw "Missing plans: $($missing -join ', ')" }
```

Expected: command exits 0 without output.

- [ ] **Step 3: 為每個新任務建立獨立 worktree／branch**

在每個 Codex 任務使用 `superpowers:using-git-worktrees`；branch 必須使用表格中的 `codex/` 名稱。若 Codex App 已提供獨立 worktree，保留 App 建立的路徑，不自行建立第二層 worktree。

- [ ] **Step 4: 記錄 ownership handoff**

每個任務第一個 commit 前，在該任務 commentary 明確列出：base commit、owned paths、禁止修改 paths、依賴的其他工作流 contract。不要建立會被提交的 lock file；協調紀錄留在任務與 commit history。

## 4. Task 1：Wave 1 平行啟動

**Files:**
- Read: A、B、C、E1 子計畫
- Read: Prompt Pack 的 A、B、C、E1 區段

- [ ] **Step 1: 啟動 A Evidence E2E**

Expected first checkpoint: 真實 read-only DB preflight、scenario date coherence RED tests、orchestrator interface commit。

- [ ] **Step 2: 啟動 B Historical ML**

Expected first checkpoint: safe feature catalog、label timing contract、trading-calendar split RED tests。

- [ ] **Step 3: 啟動 C Broker Performance**

Expected first checkpoint: current latency baseline、SQLite query provider contract、batch snapshot RED tests。

- [ ] **Step 4: 啟動 E1 P0 Daily Sources**

Expected first checkpoint: official endpoint parser fixture、source status DTO、dry-run conservation tests。

- [ ] **Step 5: 確認各流沒有共享檔案衝突**

Run in each worktree:

```powershell
git diff --name-only $(git merge-base HEAD dev)..HEAD
```

Expected: 只出現子計畫 ownership 內的路徑及該流專屬 tests/runbook/QA closeout。

## 5. Task 2：Wave 1b Dashboard 並行開發

**Files:**
- Read: D 子計畫
- Test: visibility service、Decision Desk與UI contract tests

- [ ] **Step 1: 先實作PIT-safe visibility DTO／read service tests**

Expected: 正式DB只讀；月營收historical as-of不偷看2026 backfill；institutional／credit／TDCC即使0 rows仍有typed status。

- [ ] **Step 2: 鎖定 D ownership**

D可以修改`app_module/decision_desk_*`、新`market_data_visibility_*`、既有`decision_desk_view.py`／Workbench與`ui_qt/main.py`；不得建立第三套`market_dashboard_view.py`，也不得修改C/E1 owned files。

- [ ] **Step 3: 完成唯一instance與drill-down導航**

Market Exploration index 0使用唯一`DecisionDeskView`；Workbench只導航到該instance。既有Smart Money tab保持drill-down，因此D不等待C的新snapshot contract。E1 candidate status日後由G以adapter整合，不得冒充正式observed source。

## 6. Task 3：Wave 2 啟動條件與執行

### E2 PIT Historical Data Repair

- [ ] B 已將 fundamentals 明確列為 excluded feature family。
- [ ] E2 在獨立 branch 修復 availability history、公告日與 label blocker，不改 B dataset artifact。
- [ ] 每一 source 產出 coverage／unmatched／future-blocked／revision diagnostics。

### F ML Daily Inference

- [ ] B 已提交 feature schema、artifact manifest、model record 與 load contract。
- [ ] F 只載入 frozen artifact，不呼叫 trainer `.fit()`。
- [ ] F在`ml_module`完成shadow inference／registry；由`scripts/`composition root投影成不依賴ML package的DTO。Recommendation candidate metadata接線留給G，正式ranking不變。

## 7. Task 4：工作流 Handoff 契約

每一 A～F 任務結束時必須交付以下內容；缺一項就不能進 G：

```text
workstream_id
branch
base_commit
head_commit
commit_list
owned_files_changed
public_interfaces
focused_test_paths
focused_tests_and_results
boundary_checks_and_results
performance_or_data_coverage_results
known_blockers
external_gates_unchanged
rollback_commits
```

- [ ] **Step 1: 確認 focused tests 有實際輸出，不只列命令**
- [ ] **Step 2: 確認沒有 production DB／raw data／output artifacts 被 stage**
- [ ] **Step 3: 確認所有 external／formal 狀態保持 pending**
- [ ] **Step 4: 確認 `git diff --check` 與 worktree status**

## 8. Task 5：Wave 3 Integration Closeout

G 必須依下列順序整合，不可全分支一次 merge 後才除錯：

1. A Evidence E2E。
2. C Broker Performance。
3. E1 P0 Daily Source。
4. D Dashboard。
5. B Historical ML。
6. E2 PIT Repair。
7. F Daily Inference。

七流整合後，G才建立跨流Dashboard adapters：把E1 candidate status與E2 eligibility投影到D的visibility read model，明確標candidate／degraded；C的Smart Money snapshot維持既有drill-down。這不是D的完成前置條件，且不得把candidate冒充正式observed source。

每整合一條工作流後：

```powershell
$tests = @($handoff.focused_test_paths)
git diff --check
& .\.venv\Scripts\python.exe -m pytest @tests -q -o addopts=
```

最後執行 G 子計畫的全量 suite、UI QA、mypy、encoding、relative links、quant guard、ML boundary 與 Gate verifier。

## 9. Master Completion Gate

- [ ] A～F handoff 完整且 ownership 無未解衝突。
- [ ] Evidence CLI 真正開 DB、跑 adapters／ML comparison／lineage，且 real failure injections 可重跑。
- [ ] Historical ML具有frozen dataset、purged folds、2025 locked OOS與model artifact hash，且`max(train_label_available_date) <= 2024-12-31`。
- [ ] Broker current dataset warm p95 < 2 秒且 GUI thread 不做 DB／CSV／domain 計算。
- [ ] Market Dashboard 顯示營收、三大法人／信用／TDCC status 與 freshness；missing 不隱形。
- [ ] Daily inference append-only、schema mismatch fail closed、rule-only fallback。
- [ ] PIT 修復結果以 source-by-source coverage 呈現，未 accepted 資料不進 Score。
- [ ] 全量驗證通過；中央文件與程式真實狀態一致。
- [ ] Closeout 只允許 `engineering_complete`／`shadow_ready` 等實際狀態，不建立 formal product、source acceptance 或 ML promotion 宣稱。
