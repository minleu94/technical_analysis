# Parallel Workstream Start Prompt Pack

本文件的每一段都是可直接貼到「新 Codex 任務」的第一個 prompt。所有任務共用同一個 repository、同一個 `dev` branch 與同一個 working tree；同時建議最多四條互不重疊的實作流。Worker 可平行編輯 exclusive ownership 檔案並跑 focused tests，但所有 Git index／history／remote 寫入只能由單一 Git Coordinator 序列執行。Worker 不得自行建立或切換 branch/worktree，也不得 stage、commit 或 push。

---

## Prompt 0：Shared Dev Git Coordinator

```text
你現在負責 technical_analysis 的 Shared Dev Git Coordinator。所有 A、B、C、D、E1、E2、F、G worker 都在同一個 repository、同一個 `dev` branch 與同一個 working tree 平行工作；你是唯一允許操作 Git index、commit history 與 remote push 的任務。你不做 domain 實作，也不替 worker 修改 owned files。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前完整閱讀根目錄 AGENTS.md、docs/agents/git_exclusions.md、master design、master plan與各工作流 ownership。確認 `git rev-parse --abbrev-ref HEAD` 正好是 `dev`，記錄 `git rev-parse HEAD`、`git status --short` 與 `git diff --cached --name-only`。若 index 一開始已有不明 staged files，停止 Git 寫入並回報；不得 reset、restore、stash 或清除它們。Parallel wave 啟動後不得 pull、rebase、merge 或 cherry-pick；若 `origin/dev` 被外部推進，停止並回報 drift，不自行改寫歷史。

你只接收 `$env:TEMP\technical_analysis_parallel_handoffs\<workstream>-<slice>.json` 的 `ready_for_commit` handoff。每份 handoff 必須含 `workstream_id`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged`與`rollback_notes`。處理一份 handoff 時：
1. 確認所有檔案都在該工作流 exclusive ownership，且沒有與其他 active slice 重疊。
2. 重算每檔 SHA-256；任何不符代表 worker 在交付後仍改檔，拒絕該 handoff。
3. 依 git_exclusions 排除 raw data、DB、model artifact、temp、graph/tool output與非本 slice QA output。
4. 只執行 `git add -- <exact-ready-files>`；不得使用 `git add .`、`git add -A` 或目錄級模糊 stage。
5. 確認 `git diff --cached --name-only` 與 handoff ready file list完全相等；跑 `git diff --cached --check`，再確認 ready files 沒有 post-stage unstaged delta且SHA-256仍一致，並依風險重跑最小必要 focused test。
6. 以 suggested commit message commit；用 `git show --name-only --format= HEAD` 再確認 commit只含該 slice。
7. 在目前 queue 沒有其他 stage／commit 動作時執行一次 `git push origin dev`；push失敗就停止queue並保持worker frozen，不得pull/rebase/merge補救。
8. 只有push成功後才記錄 workstream/slice→dev commit SHA、通知 worker可解凍下一個 slice，再處理下一份 handoff。

當 A、B、C、D、E1、E2、F 任一工作流的所有必要 slices 都已 commit 並 push 到 `dev`，你必須在 `$env:TEMP\technical_analysis_parallel_handoffs\<workstream_id>-final-committed.json` 產生該流最終 manifest。欄位至少包含：`workstream_id`、`slice_id=final`、`shared_branch=dev`、`handoff_status=coordinator_committed`、全部 `coordinator_commit_shas`、合併後的 `owned_files_ready_with_sha256`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`known_blockers`、`external_gates_unchanged` 與 `rollback_notes`。`owned_files_ready_with_sha256` 必須固定輸出為 object array：`[{"path":"repo/relative/path","sha256":"lowercase-hex"}]`，不可輸出 path→hash object。這七份 manifest 是 G 的 hard startup gate；只記錄內部 queue 不算完成。

其他工作流的 unstaged changes 在 shared dev 是正常現象；不可把它們解讀為自己造成、不可順手 stage，也不可要求乾淨 working tree。若 handoff 互相重疊、檔案仍在變動、測試不可信、hash不符或 remote dev drift，拒絕該筆並回報 owner；不猜測、不代修。

重型 full pytest、全模組 mypy、UI mandatory QA 與整合 smoke 使用單一排程時槽，避免和 worker focused tests爭用資源。每個 worker使用自己的 TEMP／OUTPUT_ROOT／pytest `--basetemp`／`-o cache_dir=...`；你只接受被 git_exclusions允許的 source、test與document files。

持續處理 queue，直到所有已交付 slice都已精確 commit並push到`dev`，且已完成工作流的 `*-final-committed.json` 已產生。每次回報：已處理handoff、commit SHA、實際staged files、測試結果、push結果、final manifest path、仍待queue與拒絕原因。不要建立新branch/worktree，不要開PR，不要清理任何worker變更。
```

## Prompt A：Evidence Rehearsal 真實 E2E

```text
你現在負責 technical_analysis 工作流 A：「Evidence Rehearsal 真實 E2E Truth 修復」。這是長任務；請持續執行到子計畫 DoD，除非遇到正式資料寫入、外部授權或無法由repo推斷的高風險選擇，否則不要停在分析或建議。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前：
1. 依根目錄 AGENTS.md 順序完整閱讀所有必讀文件，特別是 git_exclusions、tech_lead、execution、testing_qa、Evidence runbook、兩日計畫與2026-07-14 Evidence closeout。
2. 以唯讀 `git rev-parse --abbrev-ref HEAD` 確認為 `dev`，記錄共同 dev baseline 與 `git status --short`；看到其他工作流的變更是預期狀態，不得清除、還原、暫存或納入自己的 ownership。
3. 使用 superpowers:executing-plans，逐項執行：
   - docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
   - docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
   - docs/superpowers/plans/2026-07-13-evidence-rehearsal-real-e2e.md
4. 嚴格TDD：每個 slice RED→確認失敗原因→GREEN→focused tests→`git diff --check -- <owned-files>`→handoff。每個工作流使用獨立的 `$env:TEMP\technical_analysis_parallel\A`、explicit `OUTPUT_ROOT`、pytest `--basetemp` 與 `-o cache_dir=...`，避免輸出互踩。

Git 規則：你是 worker，不是 Git Coordinator。禁止執行 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。每個 slice 完成後輸出 `workstream_id=A`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`；寫入 `$env:TEMP\technical_analysis_parallel_handoffs\A-<slice>.json`。交付後凍結該 slice，直到 Coordinator 確認已精確 stage／commit 到 `dev`。不得自行處理共用 index；重型 full pytest／mypy／UI QA 由 Coordinator 排程。

你的exclusive ownership是 scripts/run_evidence_rehearsal.py、app_module/evidence_rehearsal_*、app_module/historical_evidence_replay.py、對應Evidence/replay tests、EVIDENCE_REHEARSAL_RUNBOOK與A專屬QA closeout。不得修改ml_module/**、ui_qt/**、P0 ingestion、Broker、Dashboard、Recommendation、中央Snapshot/Roadmap/Architecture/Manual/Index或External Validation Register。

核心成果：保留projection_only相容模式，新增working_copy_e2e。Source SQLite即使在DATA_ROOT也只能URI mode=ro＋query_only；以SQLite backup建立DATA_ROOT外working copy，HistoricalEvidenceReplayService只能寫working copy。Orchestrator必須真的呼叫historical replay、P0 comparison、optional ML comparison、EvidenceRehearsalService.run()與lineage verifier。沒有Advice/paper/weekly/ML時誠實degraded/pending，禁止fixture補成完整鏈。五種failure injection必須改真實輸入並由真實detector產生blocker，不得靜態append。

第一個checkpoint：先完成 execution mode/report v2、scenario/replay date coherence、source/working-copy安全與semantic fingerprint的RED/GREEN contract slice，交付 Coordinator 後再做 orchestration。

完成時跑子計畫全部 focused tests、targeted mypy、quant guard、ML boundary、py_compile 與 owned-file diff check；確認 source bytes/mtime 不變、temp DB/output 位於 ignored 專屬路徑。回報 ready files 與 SHA-256、suggested commit messages、命令與真實結果、report contract、blockers、rollback notes 與 handoff 路徑；不得自行 stage、commit 或 push。
```

## Prompt B：Historical ML Shadow MVP

```text
你現在負責 technical_analysis 工作流 B：「Historical ML Shadow MVP」。這是長任務；目標是現在用歷史資料建立可重現的shadow模型工程，不是等待新資料，也不是把模型強行升級為正式決策。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前依AGENTS.md完整閱讀必讀文件與tech_lead、data_audit、execution、testing_qa規範；確認目前為共同 `dev`，記錄共同 baseline 與 `git status --short`，不得清理其他工作流的變更。使用superpowers:executing-plans與test-driven-development逐項執行：
- docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
- docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
- docs/superpowers/plans/2026-07-13-historical-ml-shadow-mvp.md
- docs/06_qa/GATE_7_ML_SHADOW_ENGINEERING.md

你是 worker，不是 Git Coordinator。禁止 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。只改 exclusive ownership；使用 `$env:TEMP\technical_analysis_parallel\B`、explicit `OUTPUT_ROOT` 與專屬 pytest `--basetemp`／`-o cache_dir=...`。每個 slice 完成後把 `workstream_id=B`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`寫入 `$env:TEMP\technical_analysis_parallel_handoffs\B-<slice>.json`，交付後凍結該 slice；Coordinator 才能序列 stage／commit／push `dev`。重型全量 QA 由 Coordinator 排程。

你擁有ml_module/dataset_manifest.py、purged_walk_forward.py、historical contracts/feature/label/dataset/trainer/evaluation新檔、data_module/ml_historical_snapshot_provider.py、三個historical ML CLI、專屬tests/runbook/closeout。不得修改model_prediction_registries.py（F owner）、monthly_revenue/fundamental availability（E2 owner）、ScoringEngine、Recommendation、runtime或中央SSOT。

不可違反：decision T只用前一交易日T-1或更早feature；label成熟且available_date<=training_as_of才可fit；universe按歷史decision date建立；split使用交易日expanding purged walk-forward，禁止random shuffle。2025 locked OOS的final fit固定training_as_of=2024-12-31，train rows必須同時滿足decision_date<=2024-12-31與label.available_date<=2024-12-31，並assert train label horizon/purge boundary早於OOS start；2026只可成熟late-2025 outcomes供OOS evaluation，不可回流fit/feature/tuning。Core只用price/technical/market/industry；broker是2025-10-24後獨立add-on且missing不補0；fundamental只做eligibility gate。ML永遠shadow-only，不改正式Score/Advice。

第一個checkpoint：完成 feature registry、label registry、decision timing、historical universe與trading-calendar purge/prefix-invariance的RED/GREEN contract slice並交付 Coordinator。先凍結contracts，不要急著看2025結果。

完成時用正式SQLite mode=ro建立final training dataset、訓練linear與HGB；research blend selection rows必須同時滿足oof_decision_date<=2024-12-31與oof_label_available_date<=2024-12-31。確認`max(train_label_available_date)<=2024-12-31`與`max(blend_selection_label_available_date)<=2024-12-31`並保存hash後，才以--confirm-locked-oos產生2025 append-only evaluation。Production alpha固定0。模型表現差也是合法結果，輸出reject/continue_shadow，不得回頭調參美化。跑全部focused ML tests、ML boundary、quant guard、targeted mypy、py_compile與owned-file diff check；raw artifacts只放explicit ignored output。回報 ready files/SHA-256、suggested commit messages、coverage、folds、dataset/model/OOS hashes、metrics、blockers與handoff；不得自行 stage、commit 或 push。
```

## Prompt C：Broker Flow SQLite-first 效能

```text
你現在負責 technical_analysis 工作流 C：「Broker Flow SQLite-first 效能與UI非阻塞重構」。這是長任務；請從真實benchmark開始，持續實作到latency與responsiveness gates有新鮮證據。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前依AGENTS.md完整閱讀必讀文件、tech_lead、execution、testing_qa、documentation與Application Manual；確認目前為共同 `dev`，記錄共同 baseline 與 `git status --short`，不得清理其他工作流的變更。使用superpowers:executing-plans、test-driven-development；遇到效能/測試異常先用systematic-debugging。執行：
- docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
- docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
- docs/superpowers/plans/2026-07-13-broker-flow-performance.md

你是 worker，不是 Git Coordinator。禁止 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。只改 exclusive ownership；使用 `$env:TEMP\technical_analysis_parallel\C`、explicit `OUTPUT_ROOT` 與專屬 pytest `--basetemp`／`-o cache_dir=...`。每個 slice 完成後把 `workstream_id=C`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`寫入 `$env:TEMP\technical_analysis_parallel_handoffs\C-<slice>.json`，交付後凍結該 slice；Coordinator 才能序列 stage／commit／push `dev`。重型全量 QA 由 Coordinator 排程。

Exclusive ownership：app_module/broker_flow_service.py、broker_flow_sqlite_read_repository.py、broker_flow_dashboard_query_service.py、broker_flow_dashboard_dtos.py、smart_money_semantic_service.py、smart_money semantic DTO、ui_qt/views/smart_money/**、對應tests、latency QA script與C closeout。禁止修改ui_qt/main.py、Decision Desk/Workbench/market_data_visibility、E1 files與中央SSOT/Manual。

核心成果：正式DB全程URI mode=ro＋query_only；day/week/month是截至明確as_of_date最近1/5/20個broker交易日。先鎖定股/張/金額Decimal單位parity；SQLite query下推日期、stock、branch與limit，不讀全歷史CSV、不iterrows、不物件化732k rows。市場summary只聚合一次；Top/Bottom裁切後才做batch 5/20/60 semantics與batch price。保留SmartMoneyFlowView必要constructor與SmartMoneySemanticService既有public signatures。

UI的dashboard、stock detail、branch tracker都用TaskWorker，各自request id、stale-result discard與cooperative cancel；GUI thread不做DB/CSV/domain aggregation，不用QThread.terminate。ETF不以名稱heuristic分流，production DB不建index；若未達標先以EXPLAIN/benchmark提出working-copy證據。

第一個checkpoint：完成現況分段latency、SQLite/CSV單位parity、period/as-of與dashboard DTO的RED/GREEN contract slice並交付 Coordinator。

驗收：week Top/Bottom50 warm p95<2s、month<3s、cold<5s、detail<0.5s、branch<1s、300ms內UI heartbeat/loading。跑子計畫focused tests、py_compile與owned-file diff check；輸出raw samples到專屬 ignored output。回報 ready files/SHA-256、suggested commit messages、query counts、latency samples、blockers、rollback notes與handoff；UI mandatory／Update QA／全量 mypy 由 Coordinator 在重型 QA 時槽執行。不得自行 stage、commit 或 push。
```

## Prompt D：Market Exploration 整合 Dashboard

```text
你現在負責 technical_analysis 工作流 D：「Market Exploration整合Dashboard與營收/三大法人資料可見性」。這是長任務；不要只交mockup，要完成read service、Decision Desk整合、導航、UI tests與Manual。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前依AGENTS.md完整閱讀必讀文件、tech_lead、execution、testing_qa、documentation與Application Manual；確認目前為共同 `dev`，記錄共同 baseline 與 `git status --short`，不得清理其他工作流的變更。使用superpowers:executing-plans與test-driven-development執行：
- docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
- docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
- docs/superpowers/plans/2026-07-13-market-dashboard-visibility.md

你是 worker，不是 Git Coordinator。禁止 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。只改 exclusive ownership；使用 `$env:TEMP\technical_analysis_parallel\D`、explicit `OUTPUT_ROOT` 與專屬 pytest `--basetemp`／`-o cache_dir=...`。每個 slice 完成後把 `workstream_id=D`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`寫入 `$env:TEMP\technical_analysis_parallel_handoffs\D-<slice>.json`，交付後凍結該 slice；Coordinator 才能序列 stage／commit／push `dev`。重型全量 QA 由 Coordinator 排程。

架構決定：不要建立第三套MarketDashboardView。把既有DecisionDeskView作為「市場探索」第一個「市場總覽」且全app只有一個instance；原大盤/強弱股/強弱產業/主力流向保留drill-down。Workbench不再嵌第二個Decision Desk，只提供導向市場總覽的按鈕。

Exclusive ownership：market_data_visibility_dtos/service、decision_desk DTO/service/composition、decision_desk_view.py、workbench_view.py、ui_qt/main.py、對應tests、D closeout與Application Manual。禁止修改BrokerFlow/SmartMoney files、C的新repository/query/DTO、E1 fetcher/ingestion與中央Snapshot/Roadmap/Architecture。

資料規則：所有SQLite只讀；不crawler/backfill/create table。Revenue只用available_date<=as_of、當時合法revision，以Decimal/integer bp計MoM/YoY；2025 as-of不可偷看2026-06-17 backfill，現有資料可顯示degraded/historical_pit_unverified。Institutional 0 rows必須顯示MISSING與「尚未匯入（0筆）」，不得顯示三法人皆0；合法rows出現後不改UI即可顯示。Institutional/credit/TDCC/broker/revenue即使0 rows都要有status。Visibility只做研究摘要，不得改Score、Advice、action summary或stock focus。

第一個checkpoint：完成SourceVisibilityStatus、MonthlyRevenueBreadthSummary、InstitutionalFlowMarketSummary與PIT/0-row/future-row RED/GREEN contract slice並交付 Coordinator，再接DecisionDesk。

UI沿用MIDNIGHT_ANALYST/MetricCard/SectionPanel/StatusBadge，state需文字+badge+action hint；1280x720與1440x800無水平卷軸，keyboard order正確，現有async/stale guard保留。完成時跑所有focused tests與py_compile；強制Update Workbench test、qa_validate_update_tab、全模組mypy與完整整合驗證由 Coordinator 排程。更新完整Manual，回報 ready files/SHA-256、suggested commit messages、UI/資料狀態案例、blockers、rollback notes與handoff；不得自行 stage、commit 或 push。
```

## Prompt E1：P0 Daily Source Candidate Ingestion

```text
你現在負責 technical_analysis 工作流 E1：「三大法人/信用/TDCC P0 Daily Source Candidate Ingestion」。這是長任務；工程目標是可治理candidate pipeline，不是宣稱source accepted。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前依AGENTS.md完整閱讀必讀文件與data_audit、tech_lead、execution、testing_qa規範；確認目前為共同 `dev`，記錄共同 baseline 與 `git status --short`，不得清理其他工作流的變更。使用superpowers:executing-plans與TDD執行：
- docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
- docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
- docs/superpowers/plans/2026-07-13-p0-daily-source-ingestion.md

你是 worker，不是 Git Coordinator。禁止 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。只改 exclusive ownership；使用 `$env:TEMP\technical_analysis_parallel\E1`、explicit `OUTPUT_ROOT` 與專屬 pytest `--basetemp`／`-o cache_dir=...`。每個 slice 完成後把 `workstream_id=E1`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`寫入 `$env:TEMP\technical_analysis_parallel_handoffs\E1-<slice>.json`，交付後凍結該 slice；Coordinator 才能序列 stage／commit／push `dev`。重型全量 QA 由 Coordinator 排程。

Exclusive ownership：official_phase3c_fetcher.py、update_phase3c_candidates.py、source_candidate_readiness.py、新的P0 contracts/parsers/manifest/repository、parser fixtures、對應tests/runbook/closeout。禁止修改Dashboard/SmartMoney、ScoringEngine、Recommendation/Portfolio/runtime、monthly revenue/statement availability與中央SSOT。

先以RED tests證明並修正：decision_date+1與TDCC period_end+3不能當verified available date；stock_code/decision_date與symbol/trade_date需在parser邊界統一；candidate apply不得接受production DB/DATA_ROOT；dry-run不得因DBManager建立DB/table/log；malformed/duplicate/schema drift需完整quarantine與row conservation。

時間政策：優先保存官方publication timestamp；官方沒提供時用本次實際fetched_at/first_observed_at並標degraded，絕不回填交易日。同日保留timezone timestamp。每筆含source/version/raw hash/availability evidence；missing不可補0。Dry-run零side effect；apply要求explicit working-copy與confirm，拒絕resolved production descendants；duplicate identical idempotent、conflict quarantine。Candidate永遠downstream_eligibility=none、human acceptance required、scheduler false。

第一個checkpoint：完成normalized observation/raw manifest contract、captured official parser fixtures、availability policy與production-path rejection的RED/GREEN contract slice並交付 Coordinator，再做bounded live probe。

完成時跑所有Phase3C/source readiness focused tests、quant guard、targeted mypy、py_compile與owned-file diff check；對各source回報raw/accepted/blocked/quarantine/coverage/schema/timestamp diagnostics。不得把network可用當license accepted。回報 ready files/SHA-256、suggested commit messages、官方schema證據、blockers、rollback notes與handoff；不得自行 stage、commit 或 push。
```

## Prompt E2：PIT Historical Data Repair

```text
你現在負責 technical_analysis 工作流 E2：「PIT Historical Data Repair」。這是長任務；要建立可稽核availability/corporate-action mapping與coverage，不能為了讓ML可用而猜日期。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前依AGENTS.md完整閱讀必讀文件與data_audit、tech_lead、execution、testing_qa規範；確認目前為共同 `dev`，記錄共同 baseline 與 `git status --short`，不得清理其他工作流的變更。先確認Git Coordinator已把B的fundamentals exclusion contract commit並push到`dev`，且E2不得修改B frozen dataset；若此commit尚未落地，只可做唯讀準備，不得修改repository files。使用superpowers:executing-plans與TDD執行：
- docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
- docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
- docs/superpowers/plans/2026-07-13-pit-historical-data-repair.md

你是 worker，不是 Git Coordinator。禁止 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。只改 exclusive ownership；使用 `$env:TEMP\technical_analysis_parallel\E2`、explicit `OUTPUT_ROOT` 與專屬 pytest `--basetemp`／`-o cache_dir=...`。每個 slice 完成後把 `workstream_id=E2`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`寫入 `$env:TEMP\technical_analysis_parallel_handoffs\E2-<slice>.json`，交付後凍結該 slice；Coordinator 才能序列 stage／commit／push `dev`。重型全量 QA 由 Coordinator 排程。

Exclusive ownership：fundamental/monthly revenue/statement availability、corporate_action_policy、P0 fundamental/corporate adapters、新的quarterly/corporate history、p0_ml_eligibility projection、對應scripts/tests/runbook/closeout。禁止修改B dataset/trainer、F registry、Score/Recommendation/Portfolio/UI/runtime與中央SSOT。

不可違反：2026-06-17 backfill date不是歷史公告日；period end、CSV/file date、mtime、FinMind create_time都不能自動當official announcement。需區分announcement/publication、first-observed、available、revision/effective date與source/version/hash。無可信歷史證據的row保持unmatched/blocked；retroactive baseline只能degraded。Revision append-only；corporate event date不等於announcement/effective，coverage未知時label window不得clean。正式DB全程只讀；mapping只寫explicit staging，production apply另需人工核准。

第一個checkpoint：完成backfill-date、available-before-announcement、revision no-overwrite、event/announcement distinction與coverage-unknown label blocker的RED/GREEN contract slice並交付 Coordinator。

依序完成月營收mapping、季度財報mapping、corporate/restriction timeline、p0-ml-eligibility.v1與source-by-source coverage。工程DoD可以是tooling完整但部分coverage deferred；不得捏造missing evidence或自行source accepted。完成時跑全部availability/corporate/eligibility tests、quant guard、targeted mypy、py_compile與owned-file diff check；回報official/observed-only/unmatched/future/revision/eligible counts、ready files/SHA-256、suggested commit messages、blockers、rollback notes與handoff；不得自行 stage、commit 或 push。
```

## Prompt F：ML Daily Inference Operations

```text
你現在負責 technical_analysis 工作流 F：「ML Daily Inference／Registry／Drift／Rollback」。這是長任務；不得重新fit、不得改正式Score，也不得繞過現有MLShadowBoundaryGuard。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

開始前依AGENTS.md完整閱讀必讀文件與tech_lead、execution、testing_qa、GATE_7_ML_SHADOW_ENGINEERING；確認目前為共同 `dev`，記錄共同 baseline 與 `git status --short`，不得清理其他工作流的變更。使用superpowers:executing-plans與TDD執行：
- docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
- docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
- docs/superpowers/plans/2026-07-13-ml-daily-inference-operations.md

你是 worker，不是 Git Coordinator。禁止 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。只改 exclusive ownership；使用 `$env:TEMP\technical_analysis_parallel\F`、explicit shadow `OUTPUT_ROOT` 與專屬 pytest `--basetemp`／`-o cache_dir=...`。每個 slice 完成後把 `workstream_id=F`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`寫入 `$env:TEMP\technical_analysis_parallel_handoffs\F-<slice>.json`，交付後凍結該 slice；Coordinator 才能序列 stage／commit／push `dev`。重型全量 QA 由 Coordinator 排程。

Dependency：F0～F3可先用fixtures；feature parity與真實inference必須等B提供feature registry hash/order/dtype、dataset manifest v2、model artifact manifest/hash與builder contract。B未交付時不得自行發明第二套feature transform。

Exclusive ownership：model_prediction_registries.py、drift comparison、model artifact/inference/lifecycle/calibration新檔、中立app_module/ml_shadow_projection_dtos.py、inference/inspect CLI、candidate dry-run wrapper與對應tests/runbook/closeout。禁止修改trainer、ScoringEngine、RecommendationService、runtime、production scheduler與中央SSOT。

硬邊界：app_module/runtime不得import ml_module；只由scripts composition root投影中立DTO。Inference不得呼叫.fit。Artifact load先驗hash/schema/family/shadow flags；registry需explicit shadow DB並拒絕production/DATA_ROOT，new predictions以integer bp append-only保存。B凍結的research blend可輸出shadow score，但production_blend_alpha_bp固定0，formal ranking不讀取。Duplicate identical idempotent、conflict拒絕、partial write atomic。Major drift只disable shadow/review，不auto retrain/promotion；calibration只用matured labels。任何missing model/hash/schema/future feature/drift/conflict都停止overlay，正式rule path完全不受影響。

第一個checkpoint：完成artifact store、inference identity、registry explicit-path/integer-bp/idempotency與lifecycle append-only的RED/GREEN contract slice並交付 Coordinator；B contract到位前不要做真實feature inference。

完成時用B artifact與正式read-only source跑one-date smoke到explicit shadow root，重跑證明idempotent並做rollback simulation。跑focused tests、ML boundary、quant guard、targeted mypy、py_compile與owned-file diff check；確認無app/runtime→ml import、scheduler仍false。回報 ready files/SHA-256、suggested commit messages、registry rows、hashes、drift/calibration、failure injection、blockers、rollback notes與handoff；不得自行 stage、commit 或 push。
```

## Prompt G：Cross-workstream Integration／QA／Closeout

```text
你現在負責 technical_analysis 工作流 G：「Cross-workstream Integration／QA／Truth Closeout」。這是最後單線任務，不是補做所有domain工作的救火分支。

Repository：C:\Projects\PythonProjects\technical_analysis
Branch：dev（共用 working tree；禁止切換）

硬啟動條件：A、B、C、D、E1、E2、F都必須交付 workstream/slice id、ready files與SHA-256、Coordinator 落在 `dev` 的 commit SHA、public interfaces、focused test paths與真實輸出、coverage/latency、known blockers、external gates unchanged與rollback notes。在此之前只可做read-only readiness matrix；不得寫integration code、中央文件或假closeout。

開始前依AGENTS.md完整閱讀所有必讀文件，以及documentation_agent、testing_qa_agent、execution_agent、git_exclusions、DOC_COVERAGE_MAP、FEATURE_TEST_ROUTING_MATRIX與所有七流plans/handoffs。確認目前仍是共同 `dev`；依A→C→E1→D→B→E2→F順序核對 Coordinator 已落在 `dev` 的 commits與handoff，每核對一流立即跑該流focused suite。不得 merge/cherry-pick任何分支。使用superpowers:executing-plans執行：
- docs/superpowers/specs/2026-07-13-parallel-evidence-ml-dashboard-design.md
- docs/superpowers/plans/2026-07-13-parallel-system-execution-master-plan.md
- docs/superpowers/plans/2026-07-13-cross-workstream-integration-closeout.md

你仍是 worker，不是 Git Coordinator。禁止 `git switch/checkout/branch/worktree/add/commit/push/pull/stash/rebase/reset/revert/cherry-pick/merge`。只改 G exclusive ownership；使用 `$env:TEMP\technical_analysis_parallel\G`、explicit `OUTPUT_ROOT` 與專屬 pytest `--basetemp`／`-o cache_dir=...`。G 的每個 slice 把 `workstream_id=G`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、path→SHA-256 mapping `sha256_by_file`、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged=true`與`rollback_notes`寫入 `$env:TEMP\technical_analysis_parallel_handoffs\G-<slice>.json`，交付後凍結；Coordinator 才能序列 stage／commit／push `dev`。重型 full pytest／mypy／UI QA 由 Coordinator 安排單一時槽，G 解析結果並產出 truth closeout。

Exclusive ownership：cross-workstream integration test、verify_system_execution_blueprint.py、QA inventory/routing、中央PROJECT_SNAPSHOT/Roadmaps/system/target architecture、Application Manual reconciliation、Documentation Index/Navigation與G closeout。Domain failure必須退回原owner；G只能修composition/adapter/import衝突。Recommendation/runtime shadow metadata若要接，只能注入中立DTO，不得讓app/runtime import ml_module，正式score/ranking/Advice需bit-for-bit或contract等價不變。

先建立temp SQLite RED chain：read-only governed source→working-copy Evidence replay→PIT-safe dataset→ML shadow prediction/rule comparison→Dashboard read model。必測train與blend-selection label available cutoff都<=2024-12-31、2025 locked boundary、future/immature exclusion、source zero-write、artifact lineage、Broker query limit pushdown、revenue/institutional/broker statuses、missing fail closed、production_blend_alpha_bp=0且ML不改formal decision。

第一個checkpoint：完成七流 readiness/ownership/dev-commit matrix；缺任一 handoff 或 Coordinator commit 就清楚列出並停止寫入階段，不得自行補造。

整合完成後建立pure verifier，跑bounded real-data read-only smoke與latency gates；執行Documentation Coverage Pass再Patch Pass。最後由 Coordinator 的單一重型 QA 時槽執行focused integration、強制UI QA、full pytest（取得本次真實exit code）、全模組mypy、encoding、relative links、quant guard、ML boundary、Gate 2–7 verifier、py_compile與diff check；G負責核對輸出。Closeout分開列engineering integration、historical shadow、dashboard visibility、forward evidence、source acceptance、production automation，絕不以一個complete取代。回報 ready files/SHA-256、suggested commit messages、所有命令/輸出/pending gates/rollback notes與handoff；不得自行 stage、commit 或 push。
```

---

## 啟動順序速查

1. 先保留一個主控任務擔任 Git Coordinator；worker 同時最多四條。第一批啟動 A、B、C、E1，任一 worker slot 釋出後立即啟動 D。所有 worker 都留在同一個 `dev` working tree，且 exclusive ownership 不得重疊。
2. B 完成 fundamentals exclusion contract handoff，且 Coordinator 已 commit 到 `dev` 後：E2 可啟動。
3. F0～F3可先用fixtures；F真實feature parity/inference必須等B artifact contract已由Coordinator commit到`dev`。
4. G只先做readiness；A～F全部handoff且對應commits已在`dev`後，才進入整合寫入與closeout。
