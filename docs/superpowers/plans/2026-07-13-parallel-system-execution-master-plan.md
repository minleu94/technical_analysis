# Parallel System Execution Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以可平行、可分工、可驗證的工作流，完成真實 Evidence E2E、歷史 ML Shadow、券商效能、Market Dashboard、P0/PIT 資料、每日 inference 與最終整合 closeout。

**Architecture:** 八條工作流共用同一個 `dev` working tree，但各自只擁有 exclusive 檔案與 focused tests，並只透過 frozen DTO／Protocol／artifact 交接。Worker 不操作 Git 狀態；單一 Git Coordinator 依 SHA-256 handoff queue 精確 stage、序列 commit並push `dev`。共享 UI、Recommendation、runtime 與中央 SSOT 文件由 Integration 工作流最後依序接線。執行分成 Coordinator Preflight 與 Wave 1～3，避免共享檔案並行覆寫，也避免把工程 readiness 冒充 external validation。

**Tech Stack:** Python 3.11、PySide6、SQLite read-only／working-copy、dataclasses、Decimal／integer bp、scikit-learn shadow models、pytest、mypy、JSON／Markdown artifacts、Windows PowerShell。

## Global Constraints

- 回覆、文件與操作說明使用繁體中文；code identifier 保持既有英文慣例。
- 不刪除或改寫正式原始資料；正式資料根目錄由 `TWStockConfig` 決定。
- 正式 DB 只允許 read-only；寫入只允許 `tmp_path`、隔離 working-copy 或經明確人工確認的 candidate ingestion。
- 核心金融值禁止新增裸 `float`；使用 `Decimal`、整數 bp／股數／分。ML analytics float 必須隔離在 `ml_module`。
- 所有feature必須符合本模型的T-1 cutoff；所有label必須成熟後才能進fit／evaluation。2025 locked OOS final fit固定`training_as_of=2024-12-31`，train label的available date也不得晚於該日。
- 不修改正式 Score、Advice、Portfolio、scheduler、lifecycle 或 broker execution；ML 固定 shadow-only。
- Historical replay／retrospective OOS 不得標為 forward／paper／live evidence。
- 不覆寫使用者或其他 agent 的未提交變更；所有工作流固定共用目前的 `dev` working tree，且只修改自己的 exclusive ownership 檔案。
- 所有 worker 禁止執行 `git switch`、`git checkout`、`git branch`、`git worktree`、`git add`、`git commit`、`git push`、`git stash`、`git pull`、`git rebase`、`git reset`、`git revert`、`git cherry-pick`、`git merge`。各子計畫與 Prompt Pack 內若仍有相反指令，一律由本 Master Plan 覆蓋，不得執行。
- 每一 task 必須 RED → GREEN、focused verification、對 ready files執行read-only diff check、計算SHA-256後才 handoff；交付後凍結該 slice，直到 Git Coordinator 明確接受或退回。
- 只有單一 Git Coordinator 可以操作共用 Git index，並精確 stage 已ready且hash一致的檔案；Coordinator每次只處理一個slice，序列commit並push `dev`。使用者對本次計畫的push授權只由Coordinator執行，不授權worker自行push。
- Git Coordinator是互斥角色，不同時擔任domain worker或修改domain內容；若同一agent需要轉任Coordinator，必須先handoff並凍結自己的worker slice，再明確進入Coordinator queue處理階段。
- 每個工作流使用獨立 `$env:TEMP` 子目錄、`OUTPUT_ROOT`、pytest `--basetemp`與`-o cache_dir=...`。全量pytest／mypy、UI全量QA、正式資料benchmark、Gate verifier與共用index一律序列化；重型QA執行期間啟用global QA barrier，所有worker暫停repository寫入直到該run完成。

---

## 1. Design Authority 與子計畫

**Design authority：**

- `docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md`

**子計畫：**

| ID | 子計畫 |
|---|---|
| A | `2026-07-13-evidence-rehearsal-real-e2e.md` |
| B | `2026-07-13-historical-ml-shadow-mvp.md` |
| C | `2026-07-13-broker-flow-performance.md` |
| D | `2026-07-13-market-dashboard-visibility.md` |
| E1 | `2026-07-13-p0-daily-source-ingestion.md` |
| E2 | `2026-07-13-pit-historical-data-repair.md` |
| F | `2026-07-13-ml-daily-inference-operations.md` |
| G | `2026-07-13-cross-workstream-integration-closeout.md` |

**啟動 Prompt Pack：**

- `docs/superpowers/prompts/2026-07-13-parallel-workstream-start-prompts.md`

## 2. Parallel Wave Matrix

| Wave | 可同時執行 | 啟動條件 | 結束 Gate |
|---|---|---|---|
| Preflight | Git Coordinator 單獨 | 目前working tree確定為`dev`且狀態可解釋 | dev baseline、ownership、TEMP與handoff contract凍結 |
| 1 | A、B、C、E1 | Preflight 完成 | 每流 focused suite 綠燈、public contract固定、ready slice已handoff |
| 1b | D 可與 Wave 1 同時 | D 只改 Decision Desk／Market Exploration／visibility owned files，不改 C/E1 files | 唯一Dashboard instance、PIT visibility與UI tests通過 |
| 2 | E2、F | F需B feature/model artifact contract；E2不改B frozen dataset | daily inference與PIT repair tests通過 |
| 3 | G 單獨 | A～F handoff已由Coordinator核對且對應slice已提交至`dev` | dev integration核對、full suite、SSOT、truth closeout完成 |

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
| H0～H2 | Coordinator Preflight：記錄dev baseline、ownership、TEMP命名與handoff格式 | Git Coordinator | 八份計畫與prompt存在，shared files owner唯一，worker Git禁令已確認 |
| H2～H12 | 第一批平行啟動 | A、B、C、E1 | 每流第一個RED→GREEN contract slice完成focused tests並handoff；無shared-file越界 |
| H12～H24 | 深化第一批 | A、B、C、E1 | A read-only/working copy；B snapshot/split；C SQLite query；E1 parser/safety |
| H24 Gate | 核對handoff hashes／tests／artifacts與dev commit queue，不以口頭進度換流 | Git Coordinator | B fundamentals exclusion與artifact interface、各流ready files／blockers可追溯 |
| H24～H36 | 有slot才啟動第二批 | D可立即；E2在B exclusion contract已提交後；F0～F3可用fixtures | 不打斷已handoff且尚未獲Coordinator確認的frozen slice |
| H36～H48 | 完成slice與交接 | 依可用slot續跑A～F；G只做readiness matrix | 每流ready files／SHA-256、focused output、blockers、next exact task |

若只有四個執行slot，優先順序是A、B、C、E1；任一流完成可驗收handoff後，slot依序轉給D、E2、F。若有第五個以上執行slot，D可從H2直接開工；不要因此讓G提前寫中央文件。每個slot仍必須使用自己的TEMP／OUTPUT_ROOT／pytest basetemp。

### 可以平行但要遵守的限制

- A／B／C／E1 完全不同 ownership，可直接同時開工。
- D 可與C／E1完全平行：直接重用既有`DecisionDeskView`作唯一市場總覽，並由自身read-only visibility service顯示正式表status；不得修改`broker_flow_service.py`、Smart Money子目錄或`official_phase3c_fetcher.py`。
- E2 可與 F 平行；B 已明確排除 fundamentals，因此 E2 不應改 B frozen dataset。
- F的artifact store／registry／lifecycle fixture可先開工；feature parity與真實inference必須等B artifact contract slice已由Coordinator提交至`dev`。F不必等待E2；新增資料源只建立未來dataset/model version。
- Worker可平行跑focused tests，但命令必須指定自己的`--basetemp`，且所有會寫artifact的命令必須指向自己的TEMP／OUTPUT_ROOT。

### 不可平行

- B的feature／artifact contract尚未由Coordinator提交至`dev`前，F不得實作feature transformation或真實inference；F0～F3 fixture工作可先做。
- C 與 D 不得同時修改 `ui_qt/views/smart_money/*`。
- D 與 G 不得同時修改 `ui_qt/main.py`、Decision Desk DTO/service、Application Manual。
- Recommendation／runtime wiring完全由G擁有；F不得修改，因此不存在跨層import或平行衝突。
- A～F handoff尚未由Coordinator核對且對應slice尚未提交至`dev`前，不啟動 G 的中央文件與 full-suite closeout。
- 任一工作流不得自行修改 `PROJECT_SNAPSHOT.md`、Roadmap、Architecture、Documentation Index 或 `PROJECT_NAVIGATION.md`；全部由 G 一次同步。
- 共用 Git index任何時刻只允許Git Coordinator操作；全量pytest／mypy、UI全量QA、正式資料benchmark與Gate verifier必須取得Coordinator序列槽，不能與另一個重型QA同時執行。

## 3. Task 0：建立執行基線與 ownership freeze

**Files:**
- Create outside repository: `$env:TEMP\technical_analysis_parallel_coordinator\dev_baseline.json`
- Create outside repository: `$env:TEMP\technical_analysis_parallel_coordinator\handoff_commit_queue.json`
- Read: `docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md`
- Read: 本 Master Plan 與八份子計畫

**Interfaces:**
- Produces: dev baseline SHA、working-tree ownership snapshot、每個workstream的TEMP／OUTPUT_ROOT／pytest basetemp、dependency slice與handoff queue path。

- [ ] **Step 1: 由Git Coordinator確認dev baseline**

Run:

```powershell
$current = git rev-parse --abbrev-ref HEAD
if ($current -ne 'dev') { throw "Expected shared dev working tree, got: $current" }
git status --short
git rev-parse HEAD
git rev-parse origin/dev
git log --oneline --max-count=12
```

Expected: 目前就是`dev`；工作樹狀態可解釋。若有既存變更，Coordinator先記錄owner，不得切換狀態、清除或覆寫。Worker不執行此Git preflight。

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

- [ ] **Step 3: 分配每流隔離執行目錄**

Coordinator為每個`workstream/slice`分配：

```text
TEMP_ROOT=$env:TEMP\technical_analysis_parallel\<workstream>\<slice>
OUTPUT_ROOT=<TEMP_ROOT>\output
PYTEST_BASETEMP=<TEMP_ROOT>\pytest
PYTEST_CACHE_DIR=<TEMP_ROOT>\pytest-cache
```

Worker執行pytest時必須加`--basetemp <PYTEST_BASETEMP> -o cache_dir=<PYTEST_CACHE_DIR>`；會寫檔的CLI必須顯式使用該slice的`OUTPUT_ROOT`。不得使用repo內共用output、其他worker的temp DB／artifact或預設pytest basetemp／cache。

- [ ] **Step 4: 確認worker Git禁令與ownership**

每個任務開始前，在commentary明確列出：workstream/slice、owned paths、禁止修改paths、依賴的已提交contract、TEMP／OUTPUT_ROOT／pytest basetemp，以及完整Git mutation禁令。子計畫中的worktree／branch／stage／commit／push步驟全部跳過，改由本Master的handoff流程接管。

## 4. Task 1：Wave 1 平行啟動

**Files:**
- Read: A、B、C、E1 子計畫
- Read: Prompt Pack 的 A、B、C、E1 區段

- [ ] **Step 1: 啟動 A Evidence E2E**

Expected first checkpoint: 真實 read-only DB preflight、scenario date coherence RED tests、orchestrator interface ready slice。

- [ ] **Step 2: 啟動 B Historical ML**

Expected first checkpoint: safe feature catalog、label timing contract、trading-calendar split RED tests。

- [ ] **Step 3: 啟動 C Broker Performance**

Expected first checkpoint: current latency baseline、SQLite query provider contract、batch snapshot RED tests。

- [ ] **Step 4: 啟動 E1 P0 Daily Sources**

Expected first checkpoint: official endpoint parser fixture、source status DTO、dry-run conservation tests。

- [ ] **Step 5: 確認各流ready files沒有ownership衝突**

每個worker在handoff前列出完整ready files並計算SHA-256；Git Coordinator把各handoff檔案集合與ownership matrix逐一比對。Expected：每個檔案只有一個active owner，且ready files只包含子計畫ownership內的路徑及該流專屬tests／runbook／QA closeout。若同一路徑被兩個slice宣告，兩者都不得進commit queue，直到owner與依賴順序釐清。

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
- [ ] E2 在共用`dev` working tree內只修改自身exclusive files，修復availability history、公告日與label blocker，不改B dataset artifact。
- [ ] 每一 source 產出 coverage／unmatched／future-blocked／revision diagnostics。

### F ML Daily Inference

- [ ] Git Coordinator 已將 B 的 feature schema、artifact manifest、model record 與 load contract slice提交至`dev`。
- [ ] F 只載入 frozen artifact，不呼叫 trainer `.fit()`。
- [ ] F在`ml_module`完成shadow inference／registry；由`scripts/`composition root投影成不依賴ML package的DTO。Recommendation candidate metadata接線留給G，正式ranking不變。

## 7. Task 4：工作流 Handoff 契約

每一 A～G 的ready slice都必須交付以下內容。A～F 缺一項就不能進Coordinator commit queue或G寫入階段；G自己的adapter／QA／文件slice缺一項也不能進最終commit／push：

```text
workstream_id
slice_id
handoff_status=ready_for_commit
ready_files
sha256_by_file
suggested_commit_message
public_interfaces
focused_test_paths
focused_tests_and_results
boundary_checks_and_results
performance_or_data_coverage_results
blockers
external_gates_unchanged
rollback_notes
```

- [ ] **Step 1: 確認 focused tests 有實際輸出，不只列命令**
- [ ] **Step 2: 確認每個ready file都在exclusive ownership內、具有重新計算一致的SHA-256，且不含production DB／raw data／TEMP／OUTPUT_ROOT artifacts**
- [ ] **Step 3: 確認所有 external／formal 狀態保持 pending**
- [ ] **Step 4: Worker對ready files完成read-only diff check後交付並凍結slice；在Coordinator明確接受或退回前不得再修改這些檔案**
- [ ] **Step 5: Coordinator只按handoff列出的精確檔案操作共用index；hash不符、檔案被其他worker修改或tests/blockers不合格時退回，不得自行混入其他檔案**
- [ ] **Step 6: Ready slice若import或依賴尚未由Coordinator提交至`dev`的另一個slice，先保持blocked，不得靠working tree中的未提交檔案通過commit gate**

Worker以PowerShell計算handoff hash，不使用Git index：

```powershell
$readyFiles = @('<exact-relative-path-1>', '<exact-relative-path-2>')
$sha256ByFile = @{}
foreach ($path in $readyFiles) {
  $sha256ByFile[$path] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
}
```

Handoff送出後狀態為`handed_off_frozen`。Coordinator只有在重新核對hash／tests、完成精確commit與push，或明確退回slice時才能發出確認；worker收到確認前不得繼續修改該slice的ready files。

當 A、B、C、D、E1、E2、F 任一工作流的所有必要 slices 都已由 Coordinator 提交並push至`dev`，Coordinator 必須把各 slice handoff與commit queue彙總成：

```text
$env:TEMP\technical_analysis_parallel_handoffs\<workstream_id>-final-committed.json
```

Final manifest 必須含 `workstream_id`、`slice_id=final`、`shared_branch=dev`、`handoff_status=coordinator_committed`、全部 `coordinator_commit_shas`、合併後的 `owned_files_ready_with_sha256`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`known_blockers`、`external_gates_unchanged` 與 `rollback_notes`。其中 `owned_files_ready_with_sha256` 的固定形狀是 object array：`[{"path":"repo/relative/path","sha256":"lowercase-hex"}]`；不得輸出 path→hash object，否則 G verifier 無法逐項讀取 `.path`／`.sha256`。這七份 final manifests 是 G 的 hard startup gate；只有 slice queue 紀錄不算完成。

## 8. Task 5：Wave 3 Integration Closeout

G不做branch整合。Git Coordinator不等待固定的「整條工作流合併順序」，而是一次處理一個已ready且dependency已落在`dev`的slice；每個slice完成後在commit queue記錄`workstream_id`、`slice_id`、檔案hash、dev commit SHA、tests與push結果。Queue優先規則如下：

1. B 的 fundamentals exclusion與feature／artifact contract slices一ready就優先處理，讓E2與F依賴不被不必要阻塞。
2. A、C、E1、D與B其餘不互相依賴的slices可依ready時間序列提交；「序列」只表示Git index一次處理一筆，不表示必須等整條工作流完成。
3. E2 只有在B exclusion contract已提交至`dev`後才可進queue。
4. F的fixture-only slices可先進queue；feature parity與真實inference slices必須等B artifact contract已提交至`dev`。
5. A～F必要slices與七份final manifests齊全後，G才依自身子計畫的A→C→E1→D→B→E2→F順序做契約驗證；該順序不是Git整合順序。

七流必要slices都已出現在`dev`後，G先核對handoff hashes與commit queue中的dev commit，再建立跨流Dashboard adapters：把E1 candidate status與E2 eligibility投影到D的visibility read model，明確標candidate／degraded；C的Smart Money snapshot維持既有drill-down。這不是D的完成前置條件，且不得把candidate冒充正式observed source。

在G進入寫入階段前，Coordinator還必須確認 A、B、C、D、E1、E2、F 七份 `<workstream_id>-final-committed.json` 都已依Task 4 schema建立；G不接受只有slice queue紀錄或仍為`ready_for_commit`的worker handoff。

每接受一個ready slice時，Git Coordinator必須序列化執行：

```powershell
$tests = @($handoff.focused_test_paths)
$baseTemp = Join-Path $env:TEMP "technical_analysis_parallel\coordinator\$($handoff.workstream_id)-$($handoff.slice_id)\pytest"
$cacheDir = Join-Path $env:TEMP "technical_analysis_parallel\coordinator\$($handoff.workstream_id)-$($handoff.slice_id)\pytest-cache"
& .\.venv\Scripts\python.exe -m pytest @tests -q -o addopts= --basetemp $baseTemp -o "cache_dir=$cacheDir"
```

Focused tests與hash核對通過後，Coordinator只能stage該handoff的ready files，檢查staged file list與hash，再建立一個commit並push `dev`；完成前不處理下一個slice。任何其他worker在此期間不得操作index或修改已handoff的frozen files。

Coordinator-only mutation sequence：

```powershell
$readyFiles = @($handoff.ready_files)
$expectedFiles = @($readyFiles | Sort-Object)
$actualHashes = @{}
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  throw 'Shared Git index is not empty; stop the queue before staging this slice.'
}
foreach ($path in $readyFiles) {
  $actualHashes[$path] = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
  if ($actualHashes[$path] -ne $handoff.sha256_by_file.$path) {
    throw "SHA256 mismatch: $path"
  }
}

git diff --check -- @readyFiles
git add -- @readyFiles
$stagedFiles = @(git diff --cached --name-only | Sort-Object)
if (Compare-Object $expectedFiles $stagedFiles) {
  throw 'Staged files differ from this handoff; stop without committing and request coordinator resolution.'
}
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Staged diff check failed.' }
foreach ($path in $readyFiles) {
  $postStageHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
  if ($postStageHash -ne $handoff.sha256_by_file.$path) {
    throw "Ready file changed after staging: $path"
  }
}
$postStageWorkingDelta = @(git diff --name-only -- @readyFiles)
if ($postStageWorkingDelta) {
  throw 'A ready file changed after staging; stop before commit and return the handoff.'
}
git commit -m $handoff.suggested_commit_message
$devCommit = git rev-parse HEAD
git push origin dev
```

這段只允許Git Coordinator執行。若任何一步失敗，停止queue、保留可診斷狀態並回報；不得讓worker接手Git修復，也不得用reset／stash等方式清除其他人的working-tree變更。

最後由G取得重型QA序列槽，執行G子計畫的全量suite、UI QA、mypy、encoding、relative links、quant guard、ML boundary與Gate verifier。G只核對`dev`上的commits與整合狀態，不執行merge／cherry-pick或其他branch操作。

G完成adapter／QA／SSOT／closeout後，也必須依Task 4產生ready files＋SHA-256 handoff並凍結slice；最終Git mutation仍由同一Coordinator按上述sequence精確commit／push `dev`，G不得自行操作index或Git history。

## 9. Master Completion Gate

- [ ] A～G handoff完整、每檔SHA-256可追溯、對應slice已由Coordinator序列提交至`dev`並push成功，且ownership無未解衝突。
- [ ] Evidence CLI 真正開 DB、跑 adapters／ML comparison／lineage，且 real failure injections 可重跑。
- [ ] Historical ML具有frozen dataset、purged folds、2025 locked OOS與model artifact hash，且`max(train_label_available_date) <= 2024-12-31`。
- [ ] Broker current dataset warm p95 < 2 秒且 GUI thread 不做 DB／CSV／domain 計算。
- [ ] Market Dashboard 顯示營收、三大法人／信用／TDCC status 與 freshness；missing 不隱形。
- [ ] Daily inference append-only、schema mismatch fail closed、rule-only fallback。
- [ ] PIT 修復結果以 source-by-source coverage 呈現，未 accepted 資料不進 Score。
- [ ] 全量驗證通過；中央文件與程式真實狀態一致。
- [ ] Closeout 只允許 `engineering_complete`／`shadow_ready` 等實際狀態，不建立 formal product、source acceptance 或 ML promotion 宣稱。
