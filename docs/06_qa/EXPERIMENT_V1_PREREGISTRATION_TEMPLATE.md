# Experiment V1 Preregistration Template

> 狀態：未填寫模板；不是 experiment approval、OOS unblind 或 promotion evidence
>
> 上位設計：[External Evidence Design §11](../superpowers/specs/2026-07-13-external-evidence-investment-validation-design.md)
>
> 前置稽核：[OOS Exposure／Custody Audit Plan](../superpowers/plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md)

## 使用規則

1. 複製本模板建立新的 immutable artifact；不得直接在模板上填寫正式決策。
2. 必須在任何 formal holdout outcome unblind 前 freeze。
3. `minimum_material_effect_bp` 與 `downside_noninferiority_margin_bp` 必須由具名 Quant Validation／Risk owner 以整數 bp 決定；Agent、fixture 或預設 0 不得替代。
4. 任一 `REQUIRES_*`、hash、owner、timestamp 或 signature 未完成，狀態固定 `invalid_preregistration`。
5. 本模板不改 `formal_oos_allowed`；production blend alpha 固定 0。

## Canonical payload

```yaml
schema_version: ExperimentPreregistration.v1
experiment_id: REQUIRES_UNIQUE_ID
generation_id: REQUIRES_FROZEN_GENERATION_ID
created_at: REQUIRES_ISO8601_TIMESTAMP
frozen_at: REQUIRES_ISO8601_TIMESTAMP
unblinded_at_freeze: false
frozen: false

hypothesis: REQUIRES_HUMAN_APPROVED_HYPOTHESIS
champion_snapshot_family_id: REQUIRES_FORMAL_RULE_ONLY_CHAMPION_ID
challenger_model_id: REQUIRES_EXACTLY_ONE_CHALLENGER_ID

primary_label_id: relative_return_20d_bp
primary_horizon_trading_days: 20
downside_guardrail_id: downside_20d_flag
downside_threshold_bp: -500
sensitivity_horizons_trading_days: [5, 10]
diagnostic_horizons_trading_days: [60]
confidence_level_bp: 9500

minimum_material_effect_bp: REQUIRES_HUMAN_DECISION_INTEGER_BP
downside_noninferiority_margin_bp: REQUIRES_HUMAN_DECISION_INTEGER_BP

k_policy_hash: REQUIRES_SHA256
cost_policy_hash: REQUIRES_SHA256
sample_policy_hash: REQUIRES_SHA256
bootstrap_policy_hash: REQUIRES_SHA256
search_budget_hash: REQUIRES_SHA256
multiple_testing_policy_hash: REQUIRES_SHA256
failure_policy_hash: REQUIRES_SHA256

point_in_time_universe_id: REQUIRES_FROZEN_ID
point_in_time_universe_hash: REQUIRES_SHA256
benchmark_policy_id: REQUIRES_FROZEN_ID
restriction_policy_id: REQUIRES_FROZEN_ID
liquidity_policy_id: REQUIRES_FROZEN_ID
outcome_revision_policy: append_only_verified_current_projection

sample_unit: decision_date_symbol_paired
missing_pair_policy: exclude_and_disclose
pending_outcome_policy: exclude_from_denominator
cost_basis: after_cost
bootstrap_unit: decision_date_block
random_seed: REQUIRES_LOCKED_INTEGER
search_budget: REQUIRES_LOCKED_NONNEGATIVE_INTEGER

primary_success_rule: primary_ci_low_bp_gte_minimum_material_effect_bp
downside_success_rule: downside_ci_low_bp_gte_negative_noninferiority_margin_bp
sensitivity_override_allowed: false
post_unblind_mutation_allowed: false
production_blend_alpha_bp: 0

oos_custody_report_id: REQUIRES_CANDIDATE_HOLDOUT_CUSTODY_REPORT_ID
formal_oos_readiness_gate: separate_pre_unblind_gate
source_decision_revision_ids: REQUIRES_DECLARED_SOURCE_REVISION_LIST
dataset_manifest_hash: REQUIRES_SHA256
model_manifest_hash: REQUIRES_SHA256
rule_champion_content_hash: REQUIRES_SHA256

quant_validation_owner: REQUIRES_NAMED_HUMAN
risk_owner: REQUIRES_NAMED_HUMAN
independent_experiment_reviewer: REQUIRES_NAMED_HUMAN
owner_decision_timestamp: REQUIRES_ISO8601_TIMESTAMP
owner_signature_artifact_ids: REQUIRES_NONEMPTY_LIST

status: invalid_preregistration
blockers:
  - template_not_completed
content_hash: REQUIRES_CANONICAL_SHA256_AFTER_FREEZE
```

## Freeze checklist

- [ ] Preregistration freeze 已綁定 generation／candidate holdout 與 custody report ID；custody 尚未 verified 時仍可鎖定 hypothesis，但不得 unblind 或執行 evaluation。
- [ ] Unblind 前的獨立 Gate 要求 custody=`custody_verified_unopened` 且 `formal_oos_allowed=true` 來自 pure verifier artifact；seen/exposed/indeterminate 不可執行 formal locked OOS experiment。
- [ ] Champion 是 persisted formal rule-only snapshot，不是 neutral-zero、重算舊 Rule 或 research blend。
- [ ] Challenger 只有一個且 ID 在 unblind 前固定。
- [ ] Primary／guardrail／5/10 sensitivity／60 diagnostic 與 `confidence_level_bp=9500` 未被修改。
- [ ] 兩個 human-bound bp 已由具名 owner 簽核，且不是 fixture 值。
- [ ] K、cost/slippage、sample、bootstrap、search budget、multiple-testing、failure policies 全部 hash frozen。
- [ ] Rule 與 ML 使用同一 point-in-time universe、outcome revision、benchmark、restriction、liquidity 與成本政策。
- [ ] pending、unpaired、missing cost／Champion／prediction rows 只排除並揭露，不補零。
- [ ] 所有 source decision revisions、dataset/model/champion hashes 與 owner signatures 可引用。
- [ ] 未讀取、摘要、排序或挑選 formal holdout outcome；`unblinded_at_freeze=false`。
- [ ] `production_blend_alpha_bp=0`，沒有 apply／promotion／scheduler／trading 權限。

## 人工決策區

| 欄位 | 決策 | Owner | Timestamp | Evidence / signature |
|---|---|---|---|---|
| `minimum_material_effect_bp` | `REQUIRES_HUMAN_DECISION` | `REQUIRES_NAMED_HUMAN` | `REQUIRES_TIMESTAMP` | `REQUIRES_ARTIFACT_ID` |
| `downside_noninferiority_margin_bp` | `REQUIRES_HUMAN_DECISION` | `REQUIRES_NAMED_HUMAN` | `REQUIRES_TIMESTAMP` | `REQUIRES_ARTIFACT_ID` |

填寫完成後由獨立 reviewer 重新計算 canonical hash；任何 post-unblind 變更必須關閉原 experiment、保留負面結果並建立新 generation／新 holdout。
