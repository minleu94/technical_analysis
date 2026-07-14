# External Evidence Wave 2A 執行授權增補

> 日期：2026-07-13
>
> 授權人：使用者明確授權
>
> 動態基線：啟動每個 slice 前由唯一 Git Coordinator 在既有 `dev` working tree 重新記錄的 `HEAD`；本次首次 preflight 為 `e40aaef3aad87eb7a6124cecaacf450ab9029dcf`。
>
> 上位文件：[External Evidence Design](2026-07-13-external-evidence-investment-validation-design.md)、[External Evidence Master Plan](../plans/2026-07-13-external-evidence-investment-validation-master-plan.md)、[Wave 1 執行授權增補](2026-07-13-external-evidence-wave-1-authorization-addendum.md)。

## 1. 唯一授權範圍

本增補僅允許下列兩個 engineering slice 在既有 `dev` working tree 執行；不得建立或切換 branch/worktree。

| Slice | 授權內容 | 不可宣稱的結果 |
|---|---|---|
| EV2-A / Task 3 | `SourceAcceptanceDossier`、append-only `SourceAcceptanceDecisionRevision`、唯讀 dossier CLI 與指定測試。 | 任何 source 已 accepted、P0 Gate 已完成、candidate 可進正式下游。 |
| EV5-A / Task 5 | non-applying `MLPromotionReviewPackageV2` 與 neutral observability DTO/service；不新增或擴建 Qt widget。 | OOS 允許、模型優於 Rule、promotion eligible、任何套用或 production readiness。 |

## 2. 動態 preflight 與停止條件

每個 worker 啟動前，以及 Coordinator stage 前，必須重新確認：

1. `git branch --show-current` 為 `dev`，且 `HEAD == origin/dev`。
2. working tree 與 index 乾淨，或只含已登記、且完全屬於目前唯一 slice 的檔案。
3. `git merge-base --is-ancestor e40aaef HEAD` 成功。
4. 不讀取 2025 OOS outcome payload，且不執行 formal OOS verifier、frozen generation、training 或 comparison。
5. `formal_oos_allowed` 維持 `false`，`production_blend_alpha_bp` 維持 `0`。

任一條件失敗、發現未登記的 concurrent edit、任何命令會寫正式資料、或需求跨越 exclusive files 時，立即停止該 slice；不得自行 switch、pull、reset、stash、rebase、建立 worktree 或擴張範圍。

## 3. Exclusive ownership 與交接

| 角色 | Exclusive files | 不可操作 |
|---|---|---|
| EV2 worker | `data_module/source_acceptance_governance.py`、`data_module/source_acceptance_decision_registry.py`、`scripts/build_source_acceptance_dossier.py`、`tests/test_source_acceptance_governance.py`、`tests/test_source_acceptance_decision_registry.py`、`tests/test_source_acceptance_dossier_cli.py`，以及必要且最小的 P0 registry/verifier adapter 與其既有指定測試。 | Git mutation、正式資料寫入、source acceptance、Scoring/Advice/Portfolio/Exit/scheduler 修改。 |
| EV5 worker | `ml_module/promotion_review_package_v2.py`、`app_module/external_evidence_observability.py`、`tests/test_ml_promotion_review_v2.py`、`tests/test_external_evidence_observability_service.py`、`tests/test_ml_shadow_projection_boundary.py`。 | Git mutation、Qt widget、ML training/comparison、apply/promotion/retrain/scheduler/trade。 |
| 獨立唯讀 QA | 只讀取各 slice 的 diff、tests、型別與 boundary command output；不得修改檔案或 Git state。 | 所有寫入與 Git mutation。 |
| 唯一 Git Coordinator | 本 addendum、精確 stage/commit/push，以及必要的單一 slice 文件交接。 | `git add -A`、跨 slice 混合 commit、修改 External Gate/Register/Snapshot 完成狀態。 |

每個 worker handoff 必須包含：`task_id`、動態 baseline SHA、ready files、每檔 SHA-256、RED evidence、GREEN verification、boundary checks、blockers、pending human decisions、zero-write 聲明、rollback notes 與建議 commit message。Worker 只交接，不操作 Git。Coordinator 僅在獨立唯讀 QA 通過後，重算 SHA-256、重跑 focused checks、精確 stage 該 slice、驗證 cached diff、建立單一 slice commit 並 push `dev`。

## 4. Fail-closed 規則

EV2-A 的 P0 分母固定為 13，`broker_branch.revalidation` 是獨立 lane。HTTP 200、parser success、candidate rows、單一 coverage 數字均不得產生 `accepted`。缺 source/license owner、license、publication/available-date policy、revision、PIT coverage、row conservation、quarantine、quality、eligibility 或 rollback 任一項，一律 `deferred` 且 `allowed_use_cases=()`。

EV5-A 僅接受 artifact identity 與既有 metrics 的唯讀投影，不重算 domain logic。20 個 causal shadow observed days 最多令 `shadow_pipeline_operational=true`；缺 formal OOS、forward、paper、source decision revisions、comparison、drift/calibration 或 rollback 任一項，一律 `review_status="defer"`。所有 `apply_promotion`、promotion、retrain、scheduler 與 trading flags 固定 `false`；`production_blend_alpha_bp=0`。

EV1 真實 manual capture 可獨立持續，但不可回填，亦不可把 replay/rehearsal 計作 observed/forward evidence。

## 5. Rollback 與授權終點

EV2 rollback 只可 append 新的 disable/reject/deferred decision revision，eligibility projection 回到無可用 use case；不得刪改歷史 dossier、decision 或原始資料。EV5 rollback 為隱藏不可用 observability projection、回到正式 Rule Champion，alpha 保持 0；不得刪改歷史 citation 或 review artifact。

兩個 slice 完成並各自經獨立 QA、單一 slice commit 與 push 後立即停止。不得啟動 Task 6 以後、不得改 External Gate/Register/Snapshot 狀態、不得把本工程交付描述為 source acceptance、formal OOS、promotion 或 production closeout。
