"""Fubon market-data shadow decision orchestration service.

Calculates Baseline Rule-only results and Fubon candidate shadow results (Score,
Recommendation, Portfolio, Exit / Position Health), preserves lineage, and computes
field-by-field differences without modifying formal Rule-only outputs or evidence credit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import json
import uuid
from typing import Any, Sequence

import pandas as pd

from data_module.fubon_shadow_authorization import FubonShadowComputationAuthorization
from data_module.fubon_pit_validator import FubonPITObservationValidator, FubonPITValidationResult
from decision_module.strategy_configurator import StrategyConfigurator
from app_module.portfolio_construction_service import PortfolioConstructionService
from app_module.portfolio_construction_dtos import PortfolioConstructionRequest


@dataclass(frozen=True)
class FubonShadowDecisionBundle:
    """Read-only, neutral shadow decision bundle."""

    schema_version: str = "fubon-shadow-decision-bundle.v1"
    run_id: str = ""
    decision_timestamp: str = ""
    symbol_or_universe_identity: tuple[str, ...] = ()
    input_lineage: dict[str, Any] = field(default_factory=dict)
    pit_validation_status: str = "passed"
    baseline_rule_result: dict[str, Any] = field(default_factory=dict)
    fubon_shadow_result: dict[str, Any] = field(default_factory=dict)
    score_candidate: dict[str, Any] = field(default_factory=dict)
    recommendation_candidate: dict[str, Any] = field(default_factory=dict)
    portfolio_candidate: dict[str, Any] = field(default_factory=dict)
    exit_candidate: dict[str, Any] = field(default_factory=dict)
    differences: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    formal_rule_unchanged: bool = True
    formal_decision_influence_allowed: bool = False
    formal_evidence_credit_authorized: bool = False
    formal_oos_allowed: bool = False
    production_blend_alpha_bp: int = 0
    production_action_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "decision_timestamp": self.decision_timestamp,
            "symbol_or_universe_identity": list(self.symbol_or_universe_identity),
            "input_lineage": self.input_lineage,
            "pit_validation_status": self.pit_validation_status,
            "baseline_rule_result": self.baseline_rule_result,
            "fubon_shadow_result": self.fubon_shadow_result,
            "score_candidate": self.score_candidate,
            "recommendation_candidate": self.recommendation_candidate,
            "portfolio_candidate": self.portfolio_candidate,
            "exit_candidate": self.exit_candidate,
            "differences": self.differences,
            "diagnostics": list(self.diagnostics),
            "blockers": list(self.blockers),
            "formal_rule_unchanged": True,
            "formal_decision_influence_allowed": False,
            "formal_evidence_credit_authorized": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "production_action_allowed": False,
        }

    def to_sanitized_json(self) -> str:
        """Produce sanitized JSON payload guaranteed to contain no secrets."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)


class FubonShadowDecisionService:
    """Orchestrates Fubon PIT-safe shadow decision pipeline."""

    def __init__(self, authorization: FubonShadowComputationAuthorization) -> None:
        authorization.validate()
        self.authorization = authorization
        self.pit_validator = FubonPITObservationValidator()

    def evaluate_shadow_decision(
        self,
        *,
        raw_observations: Sequence[dict[str, Any]],
        decision_timestamp: str,
        universe_df: pd.DataFrame,
        strategy_config: dict[str, Any],
        portfolio_request: PortfolioConstructionRequest | None = None,
        run_id: str | None = None,
    ) -> FubonShadowDecisionBundle:
        """Execute baseline Rule calculation vs Fubon shadow candidate calculation."""
        run_id = run_id or f"run-fubon-shadow-{uuid.uuid4().hex[:8]}"
        diagnostics: list[str] = ["fubon_shadow_decision_pipeline_executed"]
        blockers: list[str] = []

        # 1. Validate PIT observations
        pit_result: FubonPITValidationResult = self.pit_validator.validate_batch(
            raw_observations, decision_timestamp
        )
        diagnostics.extend(pit_result.diagnostics)

        pit_status = "passed"
        if pit_result.quarantined_observations or pit_result.rejected_count > 0:
            pit_status = "blocked"
            blockers.append("pit_validation_failed_quarantined_or_rejected")
        elif pit_result.degraded_observations:
            pit_status = "degraded"
            diagnostics.append("pit_validation_degraded")

        # Universe symbols
        symbols = tuple(sorted(list(set(universe_df["股票代號"].astype(str).tolist())))) if "股票代號" in universe_df.columns else ()

        # Lineage hash
        lineage = {
            "authorization_revision_id": self.authorization.authorization_revision_id,
            "authorization_content_hash": self.authorization.content_hash,
            "decision_timestamp": decision_timestamp,
            "pit_accepted_count": len(pit_result.accepted_observations),
            "pit_degraded_count": len(pit_result.degraded_observations),
            "pit_quarantined_count": len(pit_result.quarantined_observations),
            "pit_rejected_count": pit_result.rejected_count,
            "raw_observation_count": len(raw_observations),
        }

        # 2. Baseline Rule-only calculation (pure technical_analysis without Fubon)
        baseline_rule_res = self._compute_baseline(universe_df, strategy_config, portfolio_request)

        # 3. Fubon Candidate calculation
        candidate_res, shadow_diags = self._compute_candidate(
            pit_result=pit_result,
            universe_df=universe_df,
            strategy_config=strategy_config,
            portfolio_request=portfolio_request,
            decision_timestamp=decision_timestamp,
        )
        diagnostics.extend(shadow_diags)

        # 4. Compute differences
        differences = self._compute_differences(baseline_rule_res, candidate_res)

        return FubonShadowDecisionBundle(
            run_id=run_id,
            decision_timestamp=decision_timestamp,
            symbol_or_universe_identity=symbols,
            input_lineage=lineage,
            pit_validation_status=pit_status,
            baseline_rule_result=baseline_rule_res,
            fubon_shadow_result=candidate_res,
            score_candidate=candidate_res.get("score", {}),
            recommendation_candidate=candidate_res.get("recommendation", {}),
            portfolio_candidate=candidate_res.get("portfolio", {}),
            exit_candidate=candidate_res.get("exit", {}),
            differences=differences,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            blockers=tuple(dict.fromkeys(blockers)),
            formal_rule_unchanged=True,
            formal_decision_influence_allowed=False,
            formal_evidence_credit_authorized=False,
            formal_oos_allowed=False,
            production_blend_alpha_bp=0,
            production_action_allowed=False,
        )

    def _compute_baseline(
        self,
        df: pd.DataFrame,
        config: dict[str, Any],
        portfolio_request: PortfolioConstructionRequest | None,
    ) -> dict[str, Any]:
        """Compute pure Baseline Rule-only scores, recommendations, portfolio, and exit."""
        configurator = StrategyConfigurator()
        scored_df = configurator.generate_recommendations(df, config)

        scores_by_code: dict[str, int] = {}
        recs_list: list[dict[str, Any]] = []

        if not scored_df.empty:
            for _, row in scored_df.iterrows():
                code = str(row.get("股票代號", row.get("stock_code", "")))
                score_val = row.get("FinalScore", row.get("TotalScore", 0))
                score_bp = int(Decimal(str(score_val)) * Decimal("100"))
                scores_by_code[code] = score_bp
                recs_list.append(
                    {
                        "stock_code": code,
                        "stock_name": str(row.get("證券名稱", code)),
                        "score_bp": score_bp,
                        "status": "selected",
                    }
                )

        portfolio_res: dict[str, Any] = {"status": "not_requested"}
        if portfolio_request is not None:
            svc = PortfolioConstructionService()
            p_res = svc.construct(portfolio_request)
            portfolio_res = {
                "status": "calculated",
                "decision_date": p_res.decision_date,
                "capital_amount": str(p_res.capital_amount),
                "allocations": [
                    {
                        "stock_code": a.stock_code,
                        "target_weight_bp": a.target_weight_bp,
                        "constrained_weight_bp": a.constrained_weight_bp,
                        "executable_amount": str(a.executable_amount),
                        "executable_shares": a.executable_shares,
                    }
                    for a in p_res.allocations
                ],
                "residual_cash": str(p_res.residual_cash),
            }

        exit_res = {
            "status": "not_computable",
            "reason": "position_health_context_not_supplied",
            "auto_action_allowed": False,
        }

        return {
            "score": scores_by_code,
            "recommendation": {"selected": recs_list, "total_count": len(recs_list)},
            "portfolio": portfolio_res,
            "exit": exit_res,
        }

    def _compute_candidate(
        self,
        *,
        pit_result: FubonPITValidationResult,
        universe_df: pd.DataFrame,
        strategy_config: dict[str, Any],
        portfolio_request: PortfolioConstructionRequest | None,
        decision_timestamp: str,
    ) -> tuple[dict[str, Any], list[str]]:
        """Compute candidate results using Fubon feature mapping contract."""
        diagnostics: list[str] = []

        if pit_result.quarantined_observations or pit_result.rejected_count:
            return _not_computable_candidate(
                reason="pit_validation_blocked",
                missing_mapping="clean_pit_observations",
            ), ["fubon_candidate_blocked_by_pit_validation"]

        all_obs = pit_result.accepted_observations + pit_result.degraded_observations
        if not all_obs:
            return _not_computable_candidate(
                reason="no_valid_fubon_pit_observations",
                missing_mapping="no_observations",
            ), ["fubon_no_valid_pit_observations_candidate_not_computable"]

        from data_module.fubon_shadow_feature_mapping import FubonShadowFeatureMapping
        mapper = FubonShadowFeatureMapping()
        position_context = strategy_config.get("positions") or strategy_config.get("position_context")
        mapping_res = mapper.build_mapping(
            observations=all_obs,
            decision_timestamp=decision_timestamp,
            position_context_supplied=position_context is not None,
            portfolio_requested=portfolio_request is not None,
        )

        score_comp = mapping_res.component_results["score"]
        if score_comp.status != "computed":
            candidate = _not_computable_candidate(
                reason="no_proven_fubon_feature_mapped",
                missing_mapping="score_recommendation_portfolio_exit_policy",
            )
            candidate["mapping_result"] = mapping_res.to_dict()
            return candidate, ["fubon_feature_mapping_has_no_authoritative_consumer"]

        # 防禦式 fail-closed：目前 mapping contract 不允許這個分支，但若未來
        # 契約演進，仍不可在沒有明確 consumer 實作時重用 baseline 當候選結果。
        candidate = _not_computable_candidate(
            reason="candidate_consumer_execution_not_implemented",
            missing_mapping="authoritative_consumer_integration",
        )
        candidate["mapping_result"] = mapping_res.to_dict()
        return candidate, ["fubon_candidate_consumer_execution_not_implemented"]

    def _compute_differences(
        self, baseline: dict[str, Any], candidate: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute field-by-field differences between baseline and candidate."""
        if candidate.get("status") != "calculated":
            return {
                "status": "not_computable",
                "reason": candidate.get("reason", "candidate_not_computable"),
                "baseline_unchanged": True,
                "score_differences": {},
                "recommendation_difference": {"status": "not_computable"},
                "portfolio_status": "not_computable",
                "exit_status": "not_computable",
            }

        base_scores = baseline.get("score", {})
        cand_scores = candidate.get("score", {})
        score_diffs: dict[str, dict[str, int]] = {}
        all_codes = set(base_scores.keys()) | set(cand_scores.keys())
        for code in sorted(list(all_codes)):
            b_score = base_scores.get(code, 0)
            c_score = cand_scores.get(code, 0)
            diff_bp = c_score - b_score
            score_diffs[code] = {
                "baseline_score_bp": b_score,
                "candidate_score_bp": c_score,
                "difference_bp": diff_bp,
            }

        return {
            "status": "calculated",
            "score_differences": score_diffs,
            "recommendation_count_baseline": baseline.get("recommendation", {}).get("total_count", 0),
            "recommendation_count_candidate": candidate.get("recommendation", {}).get("total_count", 0),
            "portfolio_status": candidate.get("portfolio", {}).get("status", "same"),
            "exit_status": candidate.get("exit", {}).get("status", "same"),
        }


def _not_computable_candidate(*, reason: str, missing_mapping: str) -> dict[str, Any]:
    component = {
        "status": "not_computable",
        "reason": reason,
        "baseline_unchanged": True,
    }
    return {
        "status": "not_computable",
        "reason": reason,
        "affected_component": "all",
        "missing_mapping": missing_mapping,
        "baseline_unchanged": True,
        "score": dict(component),
        "recommendation": dict(component),
        "portfolio": dict(component),
        "exit": dict(component),
    }
