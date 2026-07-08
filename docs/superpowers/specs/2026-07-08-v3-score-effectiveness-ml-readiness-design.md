# V3 Score Effectiveness Audit and ML Readiness Bridge Design

> Date: 2026-07-08
> Active milestone candidate: `V3.0 engineering candidate closeout/readiness report`
> Status: Engineering candidate inputs complete / nightly closeout handoff

## Purpose

This design turns the current V3 engineering candidate into a stricter evidence question:

> Does `TotalScore`, its fixed thresholds, and its components have observable forward usefulness before baldr considers ML?

ML is not the next replacement for the rule-based recommendation framework. It is a later shadow / research layer that can learn weights, calibrate probabilities, meta-label existing rule signals, or rank candidates only after score effectiveness has been measured with no-look-ahead evidence.

## Current Reality

Already available:

- Evidence Event Store and forward outcomes can preserve recommendation / screening / alert evidence.
- Forward performance summaries can group by existing dimensions, including score percentile bucket.
- V3 effectiveness read model, gap classifier, review scaffold, and readiness inspector exist as an engineering candidate.
- Recommendation DTOs already expose `total_score`, `indicator_score`, `pattern_score`, and `volume_score` at application boundary.
- Research Run Registry / FactorGate already provide the governance pattern needed for feature / label snapshots.

Engineering inputs now implemented:

- Raw `TotalScore` buckets such as `0-40`, `40-50`, `50-60`, `60-70`, `70-80`, `80-100`.
- Read-only forward outcome report shape for return, max drawdown, win rate, benchmark excess, and industry excess by score bucket.
- Fixed-threshold neighborhood robustness around buy/sell thresholds, confirmation days, and cooldown.
- Component ablation readiness for technical / pattern / volume score combinations.
- Governed ML feature / label contract, calibration contract, meta-labeling contract, and ranking evaluation contract.

Still not complete:

- Production ML training or model registry.
- Direct recommendation threshold, profile weight, `ScoringEngine`, portfolio, lifecycle, scheduler, or broker integration.
- Investment effectiveness conclusion.

## Design Decision

The roadmap should insert a V3 score audit gate before any ML milestone:

1. Score bucket audit proves whether higher `TotalScore` buckets have better forward outcomes.
2. Threshold robustness proves whether fixed threshold performance is stable near neighboring parameters.
3. Component ablation proves which score components contribute signal.
4. ML readiness only defines shadow-mode contracts until the previous gates are reviewable.

If these audits do not show useful and stable evidence, ML must remain diagnostics-only. A model trained on a weak or overfit score surface will make the system more opaque without making it more trustworthy.

## Scope In

- Read-only score effectiveness report.
- Raw score bucket grouping using decision-time `score_bp` / `TotalScore` data.
- Forward horizon metrics: 1D, 5D, 10D, 20D return, max drawdown, win rate, benchmark excess, industry excess when available.
- Threshold robustness matrix for nearby fixed thresholds and operating settings.
- Component ablation readiness and, if safe, new-evidence component score metadata capture.
- ML readiness contract for feature snapshots, labels, walk-forward split policy, calibration, meta-labeling, ranking, and model registry.
- Disclosure that all outputs are research evidence, not trading advice or production scheduler approval.

## Scope Out

- No production model training.
- No model output used by recommendation decisions.
- No ScoringEngine weight changes.
- No automatic threshold promotion.
- No backfilled mutation of old evidence payloads.
- No production evidence DB write unless a later explicit migration / confirm plan is approved.
- No auto trading, broker order, portfolio mutation, or lifecycle action.
- No claim that score effectiveness or investment effectiveness has been proven.

## Proposed Architecture

```text
Existing evidence / forward outcome sources
  EvidenceEvent.score_bp
  Forward outcome summaries
  RecommendationDTO component scores
  Screening matrix / negative evidence payload
        |
        v
ScoreEffectivenessReadModel
        |
        +--> TotalScoreBucketPolicy
        +--> HorizonOutcomeSummary
        +--> ThresholdRobustnessMatrix
        +--> ComponentAblationReadiness
        |
        v
ScoreEffectivenessReport
        |
        +--> CLI JSON / Markdown
        +--> V3 manual review package
        +--> MLReadinessContract
```

The ML layer starts only as a contract:

```text
ScoreEffectivenessReport
        |
        v
MLReadinessContract
  features: decision-time only
  labels: future outcome generated after horizon matures
  split: walk-forward / expanding T-1
  outputs: calibration / meta-label / ranking diagnostics
  mode: shadow-only
```

## Score Bucket Contract

Required raw score buckets:

| Bucket | Meaning |
|---|---|
| `0-40` | Weak score bucket. |
| `40-50` | Below neutral. |
| `50-60` | Neutral / low positive. |
| `60-70` | Current lower buy-threshold neighborhood. |
| `70-80` | Stronger candidate area. |
| `80-100` | Highest score bucket. |

The report must show sample count, ready / pending / missing outcomes, and limitations for every bucket. Empty buckets must be displayed as empty, not hidden.

## Threshold Robustness Contract

Initial matrix:

- buy score: `58`, `60`, `62`, `65`, `70`
- sell score: `38`, `40`, `42`, `45`, `50`
- confirmation days: `1`, `2`, `3`
- cooldown days: `2`, `3`, `5`

The report is not allowed to pick one winning parameter and call it optimal. It must identify neighborhoods:

- `stable_positive`: neighboring settings point in similar direction.
- `fragile`: only one exact setting looks good.
- `inconclusive`: sample count or outcome maturity is insufficient.
- `harmful_or_noisy`: results are consistently weak or worse than benchmark.

## Component Ablation Contract

Initial component sets:

- technical only
- pattern only
- volume only
- technical + pattern
- technical + volume
- pattern + volume
- technical + pattern + volume

Because historical persisted evidence may not contain component scores, the first implementation may emit `component_payload_missing` diagnostics. New evidence capture may store component scores in metadata only after a separate no-look-ahead and write-boundary review.

## ML Readiness Contract

Allowed after score audit gates are reviewable:

- Weight learning by market regime.
- Probability calibration of existing score / component features.
- Meta-labeling existing rule-generated buy signals.
- Ranking model for cross-sectional candidate ordering.

Initial labels:

- future 5-day return > 0
- future 10-day return > 0
- future 20-day return > 0
- future 20-day return beats TAIEX
- future 20-day return enters same-day universe top 20%

Minimum model sequence:

1. Logistic Regression baseline.
2. Random Forest or gradient boosting only after baseline and audit report exist.
3. XGBoost / LightGBM only if dependency, reproducibility, and model registry costs are accepted.

All ML outputs must remain `shadow_only=true` until manual approval and separate production-readiness gates exist.

## Safety Boundaries

- Features must be available at or before decision date.
- Labels are generated only after horizon maturity.
- Cross-sectional normalization must use expanding T-1 or an equivalent no-look-ahead policy.
- Financial core calculations use integer basis points / Decimal, not new bare floats.
- Reports must include sample sufficiency and confidence labels.
- Any model artifact must record training window, label definition, feature list, seed, dependencies, and evaluation split.

## Nightly Automation Handoff

Tonight's automation should not repeat this implementation milestone. It should choose:

`V3.0 engineering candidate closeout/readiness report`

Preferred deliverables:

1. Focused tests and py_compile for score/source readiness modules.
2. V3.0 closeout / manual validation report consistency.
3. Roadmap / Snapshot / Blueprint / Manual safety-boundary consistency.
4. Explicit `SCORE_EFFECTIVENESS_AUDIT_ENGINEERING_CANDIDATE_COMPLETE` and `PHASE_3C_SOURCE_CANDIDATE_DRY_RUN_COMPLETE` evidence in QA / handoff docs.

The sprint must stop at research evidence and closeout validation. It must not train or deploy a production model.
