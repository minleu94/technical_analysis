# Terra External Evidence Execution Handoff and Prompt Pack

> Handoff 日期：2026-07-13
>
> 狀態：ready for explicit execution authorization；本文件本身不啟動 worker
>
> 第一個任務：EV3-A 2025 OOS Exposure／Custody Audit，且只執行這一項
>
> 執行計畫：[OOS Audit Plan](../plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md)
>
> Master Plan：[External Evidence Master Plan](../plans/2026-07-13-external-evidence-investment-validation-master-plan.md)

## 1. Authority 與目前真相

- A～G engineering integration 已驗證但不得重做；immutable engineering anchor=`4f72766a1d1e7bd4b80ccb595ad3cb2fa84bd84a`。
- Terra 啟動時由 Coordinator 動態封存 `execution_baseline_sha`；必須是 clean、同步 `dev` 且為工程錨點後代。
- `historical_ml_shadow=continue_shadow`、`formal_oos_allowed=false`、`production_blend_alpha_bp=0`。
- forward evidence、source acceptance、production automation、ML promotion 與 formal product closeout 均未完成。
- 第一個任務只建立 audit capability／report；不讀 2025 outcome values，不改任何上述狀態。

## 2. 第一個任務 Hard Gates

1. `dev`、`HEAD == origin/dev`、working tree/index clean；不 switch、pull、reset、stash 或建立 branch/worktree。
2. `4f72766...` 必須是 HEAD ancestor；不得把 HEAD 回退到該工程錨點。
3. Terra 不執行 `git add/commit/push`；Git Coordinator 只在 handoff 完整且驗證通過後精確提交。
4. 禁止開啟 `--oos-payload`、outcome DB、2025 return/metric report body；只能查 metadata／hash／access evidence。
5. 禁止 fit、retrain、calibrate、compare、threshold/feature/label/universe/Rule 變更。
6. 禁止 production/source DB write、scheduler、broker、promotion、UI 或 central SSOT status 修改。
7. 缺 signed declaration 或 machine evidence 時必須輸出 `indeterminate`；不得猜測或代簽。
8. 所有測試只寫 `tmp_path`／`%TEMP%`；`formal_oos_allowed` 保持 false、alpha 保持 0。

## 3. Terra Executor Prompt

```text
你是 Terra EV3 OOS Custody Reviewer。只執行 docs/superpowers/plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md，不啟動 EV1、EV2、EV4、EV5 或任何後續 formal OOS task。

先完整讀 AGENTS.md 的強制 reading order、docs/agents/shared_context.md、docs/agents/git_exclusions.md、PROJECT_SNAPSHOT、Roadmap Hub、Product/6M/Version Roadmaps、current/target architecture、Application Manual、External Evidence Design、Master Plan、External Validation Register 與本 handoff。

Preflight 必須確認 branch=dev、HEAD==origin/dev、working tree/index clean，且 git merge-base --is-ancestor 4f72766a1d1e7bd4b80ccb595ad3cb2fa84bd84a HEAD 成功；將當下 HEAD 記為 ignored execution_baseline_sha。4f72766 只是 A～G engineering anchor，不得要求回退。任一條件不符即停止，不自行 switch/pull/reset/stash。

只建立：
- ml_module/oos_exposure_custody.py
- scripts/audit_ml_oos_exposure.py
- tests/test_ml_oos_exposure_custody.py
- tests/test_ml_oos_exposure_cli.py

只能讀 Git/manifest/report/access/CLI invocation metadata 與具名 signed declaration；不得開啟或傳入 2025 outcome payload、return、metric、ranking、comparison 或 report body，不得重訓、fit、calibrate 或修改 Feature/Label/Universe/Rule/threshold/model/hyperparameter。CLI 必須拒絕 --oos-payload 類參數，並明示 oos_payload_read=false、training_performed=false、formal_oos_changed=false。

狀態只能是 custody_verified_unopened、exposed_no_design_influence_declared、seen_oos、indeterminate；priority 固定 seen_oos > exposed_no_design_influence_declared > custody_verified_unopened，缺聲明、缺 machine evidence、矛盾或無法安全檢查一律 indeterminate。不得把 exposed/seen/indeterminate 改名為 virgin/untouched OOS。

以 TDD 執行 RED→GREEN，跑 plan 指定 pytest、targeted mypy、check_ml_shadow_boundary.py、quant_guard_linter.py 與 TEMP CLI smoke。不得寫正式資料、production evidence DB、scheduler、broker、UI、External Register 或 central SSOT；formal_oos_allowed保持false，production_blend_alpha_bp保持0。

完成後不要 git add/commit/push。只回傳 execution baseline SHA、ready files、每檔 SHA-256、RED/GREEN證據、完整驗證命令與結果、audit status/blockers（若有合規輸入）、source/production zero-write聲明、oos_payload_read=false、建議 commit message。
```

## 4. Terra Independent QA Prompt

```text
你是 Terra Independent OOS Audit QA Reviewer。不要修改檔案、不要操作Git、不要讀2025 outcome payload。依 OOS Audit Execution Plan 與 Executor handoff，逐項核對：exclusive files、dynamic baseline preflight、4f72766 ancestor、CLI拒絕outcome輸入、四狀態priority、missing declaration=>indeterminate、canonical hash、tmp-only writes、formal_oos unchanged、alpha=0。重跑指定pytest、targeted mypy、ML boundary、quant guard與git diff --check。若任何測試只用fixture卻宣稱custody verified、任何report body被讀取、任何central SSOT/Gate被改、或handoff缺SHA-256/zero-write聲明，結論必須blocked。只回傳pass/blocked、逐項證據與精確修正清單；不commit、不push。
```

## 5. Required Handoff Schema

```yaml
task_id: ev3-a-oos-exposure-custody-audit
execution_baseline_sha: REQUIRED
engineering_anchor_sha: 4f72766a1d1e7bd4b80ccb595ad3cb2fa84bd84a
ready_files: REQUIRED_EXACT_LIST
sha256_by_file: REQUIRED
red_evidence: REQUIRED
green_verification: REQUIRED
audit_status: indeterminate_or_evidence_backed_status
blockers: REQUIRED_LIST
oos_payload_read: false
training_performed: false
formal_oos_changed: false
production_blend_alpha_bp: 0
source_db_write_performed: false
production_db_write_performed: false
git_mutation_performed: false
suggested_commit_message: REQUIRED
```

## 6. 後續任務禁止自動串接

Executor／QA 完成不會自動允許 sealed OOS evaluation。EV4 也不得先 unblind；真正建立 Experiment V1 前，具名人類 owner 必須完成 [Preregistration Template](../../06_qa/EXPERIMENT_V1_PREREGISTRATION_TEMPLATE.md) 的 material-effect 與 downside-margin 決策。所有 External Gate 仍由 append-only Register 的真實 evidence／owner decision 解鎖。
