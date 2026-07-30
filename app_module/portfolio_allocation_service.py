"""Rule/ML 同單位混合與確定性 Portfolio 風控投影。"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig
from app_module.portfolio_allocation_dtos import (
    ALLOWED_BLEND_ALPHA_BP,
    TOTAL_WEIGHT_BP,
    AllocationWeightContract,
    CausalPortfolioState,
    PortfolioAllocationContextRow,
    PortfolioAllocationRequestV2,
    PortfolioAllocationResultV2,
    PortfolioAllocationRowV2,
)
from financial_module.portfolio_turnover import canonical_turnover_bp
from financial_module.units import quantize_money, round_down_to_lot
from ml_module.allocation_validation import (
    AllocationPromotionEvaluator,
    PromotionAuthorizationVerifier,
)


_CASH_SORT_KEY = "CASH"
_BUY_COST_BP = 25
_SELL_COST_BP = 55
_MAX_VOLUME_PARTICIPATION_PERCENT = 5
_LOT_SIZE = 1000
_TAIPEI = ZoneInfo("Asia/Taipei")


class PortfolioAllocationService:
    """產生唯讀配置提案；本服務永遠不建立或送出訂單。"""

    def __init__(
        self,
        policy: PaperPortfolioPolicyConfig | None = None,
        *,
        promotion_authorization_verifier: PromotionAuthorizationVerifier | None = None,
        promotion_evaluator: AllocationPromotionEvaluator | None = None,
    ) -> None:
        self._policy = policy or PaperPortfolioPolicyConfig()
        self._promotion_authorization_verifier = promotion_authorization_verifier
        self._promotion_evaluator = (
            promotion_evaluator or AllocationPromotionEvaluator()
        )

    def blend_weights(
        self,
        *,
        rule_weights: AllocationWeightContract,
        ml_weights: AllocationWeightContract,
        alpha_bp: int,
    ) -> AllocationWeightContract:
        """安全的公開混合入口。

        這個低階 API 沒有足夠的 model/dataset/decision custody context 可驗證
        Promotion，因此任何非零 alpha 都必須 fail closed 為 Rule-only。
        正式非零混合只能經由 :meth:`project`。
        """
        self._validate_blend_inputs(
            rule_weights=rule_weights,
            ml_weights=ml_weights,
            alpha_bp=alpha_bp,
        )
        effective_alpha_bp = 0
        return self._blend_verified_weights(
            rule_weights=rule_weights,
            ml_weights=ml_weights,
            alpha_bp=effective_alpha_bp,
        )

    @staticmethod
    def _validate_blend_inputs(
        *,
        rule_weights: AllocationWeightContract,
        ml_weights: AllocationWeightContract,
        alpha_bp: int,
    ) -> None:
        if isinstance(alpha_bp, bool) or not isinstance(alpha_bp, int):
            raise ValueError("alpha_bp must be an integer")
        if alpha_bp not in ALLOWED_BLEND_ALPHA_BP:
            raise ValueError("alpha_bp must be one of 0, 2000, 3500, 5000")
        if not isinstance(rule_weights, AllocationWeightContract):
            raise ValueError("rule_weights must be AllocationWeightContract")
        if not isinstance(ml_weights, AllocationWeightContract):
            raise ValueError("ml_weights must be AllocationWeightContract")

    @staticmethod
    def _blend_verified_weights(
        *,
        rule_weights: AllocationWeightContract,
        ml_weights: AllocationWeightContract,
        alpha_bp: int,
    ) -> AllocationWeightContract:
        if alpha_bp == 0:
            return rule_weights
        symbols = sorted(
            set(rule_weights.symbol_weights_bp) | set(ml_weights.symbol_weights_bp)
        )
        keys = [*symbols, _CASH_SORT_KEY]
        numerators: dict[str, int] = {}
        floors: dict[str, int] = {}
        remainders: dict[str, int] = {}

        for key in keys:
            if key == _CASH_SORT_KEY:
                rule_bp = rule_weights.cash_weight_bp
                ml_bp = ml_weights.cash_weight_bp
            else:
                rule_bp = rule_weights.weight_for(key)
                ml_bp = ml_weights.weight_for(key)
            numerator = (
                (TOTAL_WEIGHT_BP - alpha_bp) * rule_bp
                + alpha_bp * ml_bp
            )
            numerators[key] = numerator
            floors[key], remainders[key] = divmod(numerator, TOTAL_WEIGHT_BP)

        remaining = TOTAL_WEIGHT_BP - sum(floors.values())
        priority = sorted(keys, key=lambda key: (-remainders[key], key))
        for key in priority[:remaining]:
            floors[key] += 1

        return AllocationWeightContract(
            symbol_weights_bp={symbol: floors[symbol] for symbol in symbols},
            cash_weight_bp=floors[_CASH_SORT_KEY],
        )

    def blend(
        self,
        rule_weights: AllocationWeightContract,
        ml_weights: AllocationWeightContract,
        alpha_bp: int,
    ) -> AllocationWeightContract:
        """保留簡短名稱，供 composition root 向後相容地呼叫。"""
        return self.blend_weights(
            rule_weights=rule_weights,
            ml_weights=ml_weights,
            alpha_bp=alpha_bp,
        )

    def project(self, request: PortfolioAllocationRequestV2) -> PortfolioAllocationResultV2:
        effective_alpha_bp, authorization_reasons = self._resolve_effective_alpha(
            request
        )
        blended = self._blend_verified_weights(
            rule_weights=request.rule_requested_weights,
            ml_weights=request.ml_proposal.requested_weights,
            alpha_bp=effective_alpha_bp,
        )
        contexts = {row.stock_code: row for row in request.contexts}
        causal_state_symbols = (
            set(request.causal_portfolio_state.complete_symbol_universe)
            if request.causal_portfolio_state is not None
            else set()
        )
        all_symbols = sorted(
            set(blended.symbol_weights_bp)
            | set(request.rule_requested_weights.symbol_weights_bp)
            | set(request.ml_proposal.requested_weights.symbol_weights_bp)
            | set(contexts)
            | causal_state_symbols
        )
        target = {symbol: blended.weight_for(symbol) for symbol in all_symbols}
        row_diagnostics: dict[str, list[str]] = {symbol: [] for symbol in all_symbols}
        reasons: list[str] = [
            *request.ml_proposal.reasons,
            *authorization_reasons,
        ]

        self._apply_health_and_hard_risk(
            target=target,
            contexts=contexts,
            row_diagnostics=row_diagnostics,
        )
        self._apply_position_and_sector_caps(
            target=target,
            contexts=contexts,
            row_diagnostics=row_diagnostics,
        )
        self._apply_cash_floor(target=target, row_diagnostics=row_diagnostics)
        self._apply_liquidity_caps(
            request=request,
            target=target,
            contexts=contexts,
            row_diagnostics=row_diagnostics,
        )

        target_contract = self._contract_from_symbol_weights(target)
        current_complete, current_weights = self._current_weights(
            decision_date=request.decision_date,
            symbols=all_symbols,
            contexts=contexts,
            current_cash_bp=request.current_cash_bp,
            causal_portfolio_state=request.causal_portfolio_state,
            row_diagnostics=row_diagnostics,
        )
        executable_contract: AllocationWeightContract | None
        executable_weights: dict[str, int | None]
        executable_shares: dict[str, int | None]
        executable_amounts: dict[str, Decimal]
        row_costs: dict[str, Decimal]
        post_cost_cash_amount = self._amount_from_bp(
            request.capital_amount,
            request.current_cash_bp,
        )

        if not current_complete:
            reasons.append("current_portfolio_state_incomplete_no_execution")
            executable_contract = None
            executable_weights = {symbol: None for symbol in all_symbols}
            executable_shares = {symbol: None for symbol in all_symbols}
            executable_amounts = {symbol: Decimal("0.00") for symbol in all_symbols}
            row_costs = {symbol: Decimal("0.00") for symbol in all_symbols}
        else:
            turnover_target = self._apply_rebalance_controls(
                target=target,
                current=current_weights,
                contexts=contexts,
                weekly_turnover_used_bp=request.weekly_turnover_used_bp,
                row_diagnostics=row_diagnostics,
            )
            (
                executable_contract,
                executable_weights_complete,
                executable_shares,
                executable_amounts,
                row_costs,
                post_cost_cash_amount,
            ) = self._apply_lot_cost_and_cash(
                request=request,
                turnover_target=turnover_target,
                current=current_weights,
                contexts=contexts,
                row_diagnostics=row_diagnostics,
            )
            hard_constraint_violations = self._execution_constraint_violations(
                request=request,
                executable=executable_weights_complete,
                current=current_weights,
                contexts=contexts,
                post_cost_cash_amount=post_cost_cash_amount,
            )
            if hard_constraint_violations:
                reasons.extend(hard_constraint_violations)
                for symbol in all_symbols:
                    row_diagnostics[symbol].extend(hard_constraint_violations)
                    row_diagnostics[symbol].append(
                        "infeasible_execution_projection_discarded"
                    )
                executable_contract = None
                executable_weights = {symbol: None for symbol in all_symbols}
                executable_shares = {symbol: None for symbol in all_symbols}
                executable_amounts = {
                    symbol: Decimal("0.00") for symbol in all_symbols
                }
                row_costs = {symbol: Decimal("0.00") for symbol in all_symbols}
                post_cost_cash_amount = self._amount_from_bp(
                    request.capital_amount,
                    request.current_cash_bp,
                )
            else:
                executable_weights = {
                    symbol: executable_weights_complete[symbol]
                    for symbol in all_symbols
                }

        if (
            target_contract.cash_weight_bp == TOTAL_WEIGHT_BP
            and blended.cash_weight_bp < TOTAL_WEIGHT_BP
        ):
            reasons.append(
                "cash_only_fallback"
                if executable_contract is not None
                and executable_contract.cash_weight_bp == TOTAL_WEIGHT_BP
                else "cash_only_target_fallback_no_execution"
            )

        rows = tuple(
            PortfolioAllocationRowV2(
                stock_code=symbol,
                stock_name=contexts[symbol].stock_name if symbol in contexts else "",
                rule_requested_weight_bp=request.rule_requested_weights.weight_for(symbol),
                ml_requested_weight_bp=request.ml_proposal.requested_weights.weight_for(symbol),
                blended_weight_bp=blended.weight_for(symbol),
                target_weight_bp=target[symbol],
                current_weight_bp=(
                    contexts[symbol].current_weight_bp if symbol in contexts else None
                ),
                gap_weight_bp=self._gap(target[symbol], contexts.get(symbol)),
                executable_weight_bp=executable_weights[symbol],
                executable_shares=executable_shares[symbol],
                reference_price=(
                    contexts[symbol].reference_price if symbol in contexts else None
                ),
                executable_amount=executable_amounts[symbol],
                estimated_cost=row_costs[symbol],
                diagnostics=tuple(dict.fromkeys(row_diagnostics[symbol])),
            )
            for symbol in all_symbols
        )
        total_cost = quantize_money(
            sum((row.estimated_cost for row in rows), Decimal("0.00"))
        )
        advice_action = self._advice_action(
            rows=rows,
            current_complete=current_complete,
            contexts=contexts,
        )
        all_reasons = tuple(
            dict.fromkeys(
                [
                    *reasons,
                    *(
                        reason
                        for symbol in all_symbols
                        for reason in row_diagnostics[symbol]
                    ),
                ]
            )
        )
        return PortfolioAllocationResultV2(
            decision_date=request.decision_date,
            alpha_bp=effective_alpha_bp,
            rule_requested_weights=request.rule_requested_weights,
            ml_requested_weights=request.ml_proposal.requested_weights,
            blended_weights=blended,
            target_weights=target_contract,
            executable_weights=executable_contract,
            rows=rows,
            current_cash_bp=request.current_cash_bp,
            post_cost_cash_amount=post_cost_cash_amount,
            total_estimated_cost=total_cost,
            advice_action=advice_action,
            coverage_bp=request.ml_proposal.coverage_bp,
            model_hash=request.ml_proposal.model_hash,
            dataset_identity_hash=request.ml_proposal.dataset_identity_hash,
            dataset_manifest_file_hash=(
                request.ml_proposal.dataset_manifest_file_hash
            ),
            universe_hash=request.ml_proposal.universe_hash,
            policy_hash=request.ml_proposal.policy_hash,
            rule_policy_hash=request.rule_policy_hash,
            causal_portfolio_state_hash=(
                request.causal_portfolio_state.state_hash
                if request.causal_portfolio_state is not None
                else None
            ),
            missing_family_ids=request.ml_proposal.missing_family_ids,
            reasons=all_reasons,
        )

    def _resolve_effective_alpha(
        self,
        request: PortfolioAllocationRequestV2,
    ) -> tuple[int, tuple[str, ...]]:
        if request.alpha_bp == 0:
            return 0, ()
        reference = request.promotion_authorization
        if reference is None:
            return 0, ("promotion_authorization_missing_rule_only",)
        verifier = self._promotion_authorization_verifier
        if verifier is None:
            return 0, ("promotion_authority_not_configured_rule_only",)
        try:
            decision_at = datetime.combine(
                date.fromisoformat(request.decision_date),
                time(8, 30),
                tzinfo=_TAIPEI,
            )
            verification = verifier.verify_files(
                decision_at=decision_at,
                evidence_path=Path(reference.evidence_path),
                authorization_path=Path(reference.authorization_path),
                registry_revision_path=Path(reference.registry_revision_path),
                model_artifact_path=Path(reference.model_artifact_path),
                dataset_manifest_path=Path(reference.dataset_manifest_path),
                oof_bundle_path=Path(reference.oof_bundle_path),
                shadow_evidence_path=Path(reference.shadow_evidence_path),
                expected_policy_hash=self._promotion_evaluator.policy_hash,
                expected_alpha_bp=request.alpha_bp,
                expected_model_id=request.ml_proposal.model_id,
                expected_dataset_id=request.ml_proposal.dataset_id,
                expected_model_hash=request.ml_proposal.model_hash,
                expected_dataset_identity_hash=(
                    request.ml_proposal.dataset_identity_hash
                ),
                expected_dataset_manifest_file_hash=(
                    request.ml_proposal.dataset_manifest_file_hash
                ),
                expected_authorization_artifact_hash=(
                    reference.authorization_artifact_hash
                ),
            )
        except (OSError, TypeError, ValueError) as exc:
            return 0, (
                f"promotion_authorization_consumer_error:{type(exc).__name__}",
            )
        if not verification.passed or verification.evidence is None:
            return 0, tuple(
                dict.fromkeys(
                    (
                        *verification.blockers,
                        "promotion_authorization_invalid_rule_only",
                    )
                )
            )
        evaluation = self._promotion_evaluator.evaluate(
            verification.evidence,
            authorization_verification=verification,
        )
        if (
            not evaluation.formal_oos_allowed
            or evaluation.production_blend_alpha_bp != request.alpha_bp
        ):
            return 0, tuple(
                dict.fromkeys(
                    (
                        *evaluation.blockers,
                        "promotion_authorization_not_selected_rule_only",
                    )
                )
            )
        return evaluation.production_blend_alpha_bp, (
            f"promotion_authorization_verified:{reference.authorization_artifact_hash}",
        )

    def _apply_health_and_hard_risk(
        self,
        *,
        target: dict[str, int],
        contexts: Mapping[str, PortfolioAllocationContextRow],
        row_diagnostics: dict[str, list[str]],
    ) -> None:
        for symbol in sorted(target):
            context = contexts.get(symbol)
            if context is None:
                if target[symbol] > 0:
                    target[symbol] = 0
                    row_diagnostics[symbol].append("missing_constraint_context_no_new_position")
                continue
            current = context.current_weight_bp
            if context.hard_risk_reasons:
                target[symbol] = 0
                row_diagnostics[symbol].extend(
                    f"hard_risk:{reason}" for reason in context.hard_risk_reasons
                )
                continue
            if context.health_state in {"EXIT_CANDIDATE", "CLOSED"}:
                target[symbol] = 0
                row_diagnostics[symbol].append(
                    f"health_{context.health_state.lower()}_target_zero"
                )
                continue
            if context.health_state in {"WATCH", "REDUCE_CANDIDATE"}:
                if current is None:
                    target[symbol] = 0
                    row_diagnostics[symbol].append(
                        "current_weight_unknown_health_cap_not_executable"
                    )
                elif target[symbol] > current:
                    target[symbol] = current
                    row_diagnostics[symbol].append(
                        "health_watch_no_add"
                        if context.health_state == "WATCH"
                        else "health_reduce_cannot_increase"
                    )

    def _apply_position_and_sector_caps(
        self,
        *,
        target: dict[str, int],
        contexts: Mapping[str, PortfolioAllocationContextRow],
        row_diagnostics: dict[str, list[str]],
    ) -> None:
        for symbol in sorted(target):
            if target[symbol] > self._policy.max_single_position_bp:
                target[symbol] = self._policy.max_single_position_bp
                row_diagnostics[symbol].append("single_position_cap_applied")

        positive = [symbol for symbol, weight in target.items() if weight > 0]
        if len(positive) > self._policy.max_positions:
            ranked = sorted(
                positive,
                key=lambda symbol: (
                    -int(
                        contexts.get(symbol) is not None
                        and (contexts[symbol].current_weight_bp or 0) > 0
                    ),
                    -target[symbol],
                    symbol,
                ),
            )
            keep = set(ranked[: self._policy.max_positions])
            for symbol in positive:
                if symbol not in keep:
                    target[symbol] = 0
                    row_diagnostics[symbol].append("max_positions_cap_applied")

        by_sector: dict[str, list[str]] = {}
        for symbol, weight in target.items():
            if weight <= 0:
                continue
            context = contexts.get(symbol)
            if context is None or context.sector_id is None:
                continue
            by_sector.setdefault(context.sector_id, []).append(symbol)
        for symbols in by_sector.values():
            total = sum(target[symbol] for symbol in symbols)
            if total <= self._policy.max_sector_weight_bp:
                continue
            scaled = self._scale_to_total(
                {symbol: target[symbol] for symbol in symbols},
                self._policy.max_sector_weight_bp,
            )
            for symbol in symbols:
                if target[symbol] != scaled[symbol]:
                    target[symbol] = scaled[symbol]
                    row_diagnostics[symbol].append("sector_weight_cap_applied")

    def _apply_cash_floor(
        self,
        *,
        target: dict[str, int],
        row_diagnostics: dict[str, list[str]],
    ) -> None:
        max_invested_bp = TOTAL_WEIGHT_BP - self._policy.minimum_cash_bp
        if sum(target.values()) <= max_invested_bp:
            return
        scaled = self._scale_to_total(target, max_invested_bp)
        for symbol in sorted(target):
            if target[symbol] != scaled[symbol]:
                target[symbol] = scaled[symbol]
                row_diagnostics[symbol].append("minimum_cash_floor_applied")

    def _apply_liquidity_caps(
        self,
        *,
        request: PortfolioAllocationRequestV2,
        target: dict[str, int],
        contexts: Mapping[str, PortfolioAllocationContextRow],
        row_diagnostics: dict[str, list[str]],
    ) -> None:
        for symbol in sorted(target):
            context = contexts.get(symbol)
            if context is None:
                continue
            current = context.current_weight_bp
            if current is None:
                if target[symbol] > 0:
                    target[symbol] = 0
                    row_diagnostics[symbol].append("current_weight_unknown_no_new_position")
                continue
            if target[symbol] <= current:
                continue
            if context.sector_id is None:
                target[symbol] = current
                row_diagnostics[symbol].append("sector_unknown_no_new_position")
                continue
            if not self._is_strictly_prior_market_data(
                decision_date=request.decision_date,
                as_of_date=context.market_data_as_of_date,
            ):
                target[symbol] = current
                row_diagnostics[symbol].append("pit_market_data_unavailable_no_new_position")
                continue
            if (
                context.reference_price is None
                or context.median_volume_20d_shares is None
                or context.median_volume_20d_shares <= 0
            ):
                target[symbol] = current
                row_diagnostics[symbol].append("liquidity_unknown_no_new_position")
                continue

            max_buy_shares = round_down_to_lot(
                context.median_volume_20d_shares
                * _MAX_VOLUME_PARTICIPATION_PERCENT
                // 100,
                lot_size=_LOT_SIZE,
            )
            max_increment_amount = quantize_money(
                Decimal(max_buy_shares) * context.reference_price
            )
            max_increment_bp = self._bp_from_amount(
                max_increment_amount,
                request.capital_amount,
            )
            capped = min(target[symbol], current + max_increment_bp)
            if capped < target[symbol]:
                target[symbol] = capped
                row_diagnostics[symbol].append("liquidity_5pct_participation_cap_applied")

    def _current_weights(
        self,
        *,
        decision_date: str,
        symbols: Iterable[str],
        contexts: Mapping[str, PortfolioAllocationContextRow],
        current_cash_bp: int,
        causal_portfolio_state: CausalPortfolioState | None,
        row_diagnostics: dict[str, list[str]],
    ) -> tuple[bool, dict[str, int]]:
        symbol_list = tuple(symbols)
        if causal_portfolio_state is None:
            for symbol in symbol_list:
                row_diagnostics[symbol].append("causal_portfolio_state_missing")
            return False, {}
        try:
            if date.fromisoformat(causal_portfolio_state.as_of_date) >= date.fromisoformat(
                decision_date
            ):
                for symbol in symbol_list:
                    row_diagnostics[symbol].append(
                        "causal_portfolio_state_not_strictly_prior"
                    )
                return False, {}
        except ValueError:
            for symbol in symbol_list:
                row_diagnostics[symbol].append(
                    "causal_portfolio_state_date_invalid"
                )
            return False, {}
        if (
            causal_portfolio_state.current_weights.cash_weight_bp
            != current_cash_bp
        ):
            for symbol in symbol_list:
                row_diagnostics[symbol].append(
                    "causal_portfolio_cash_mismatch"
                )
            return False, {}

        weights: dict[str, int] = {}
        complete = True
        for symbol in symbol_list:
            expected_weight = causal_portfolio_state.current_weights.weight_for(
                symbol
            )
            context = contexts.get(symbol)
            if context is None or context.current_weight_bp is None:
                complete = False
                row_diagnostics[symbol].append(
                    "causal_portfolio_symbol_context_missing"
                    if context is None
                    else "current_weight_unknown"
                )
            elif context.current_weight_bp != expected_weight:
                complete = False
                row_diagnostics[symbol].append(
                    "causal_portfolio_context_weight_mismatch"
                )
            else:
                weights[symbol] = expected_weight
        if complete and sum(weights.values()) + current_cash_bp != TOTAL_WEIGHT_BP:
            complete = False
            for symbol in weights:
                row_diagnostics[symbol].append("portfolio_current_weight_contract_invalid")
        return complete, weights

    def _apply_rebalance_controls(
        self,
        *,
        target: Mapping[str, int],
        current: Mapping[str, int],
        contexts: Mapping[str, PortfolioAllocationContextRow],
        weekly_turnover_used_bp: int,
        row_diagnostics: dict[str, list[str]],
    ) -> dict[str, int]:
        executable = dict(current)
        discretionary: list[tuple[str, int]] = []
        mandatory_reductions = self._mandatory_reduction_symbols(
            target=target,
            current=current,
            contexts=contexts,
        )

        for symbol in sorted(target):
            gap = target[symbol] - current[symbol]
            if gap == 0:
                continue
            context = contexts[symbol]
            if gap < 0 and symbol in mandatory_reductions:
                executable[symbol] = target[symbol]
                row_diagnostics[symbol].append(
                    "hard_constraint_repair_overrides_rebalance_controls"
                )
                continue
            trade_bp = abs(gap)
            if trade_bp <= self._policy.rebalance_band_bp:
                row_diagnostics[symbol].append("within_rebalance_band")
                continue
            if trade_bp < self._policy.minimum_trade_bp:
                row_diagnostics[symbol].append("below_minimum_trade")
                continue
            if (
                context.trading_days_since_last_trade is None
                or context.trading_days_since_last_trade
                < self._policy.same_symbol_cooldown_trading_days
            ):
                row_diagnostics[symbol].append("same_symbol_cooldown_active")
                continue
            discretionary.append((symbol, gap))

        turnover_limit = max(
            0,
            self._policy.weekly_turnover_cap_bp - weekly_turnover_used_bp,
        )
        ordered = sorted(
            discretionary,
            key=lambda item: (
                0 if item[1] < 0 else 1,
                -abs(item[1]),
                item[0],
            ),
        )
        for symbol, gap in ordered:
            proposed = dict(executable)
            proposed[symbol] = target[symbol]
            if self._portfolio_turnover_bp(current=current, target=proposed) <= (
                turnover_limit
            ):
                executable = proposed
                continue
            partial_gap = self._maximum_gap_within_turnover(
                symbol=symbol,
                requested_gap=gap,
                executable=executable,
                current=current,
                turnover_limit_bp=turnover_limit,
            )
            if abs(partial_gap) >= self._policy.minimum_trade_bp:
                executable[symbol] = current[symbol] + partial_gap
                row_diagnostics[symbol].append("weekly_turnover_cap_partial")
            else:
                row_diagnostics[symbol].append("weekly_turnover_cap_exceeded")
        return executable

    def _mandatory_reduction_symbols(
        self,
        *,
        target: Mapping[str, int],
        current: Mapping[str, int],
        contexts: Mapping[str, PortfolioAllocationContextRow],
    ) -> set[str]:
        positive_current = {
            symbol for symbol, weight in current.items() if weight > 0
        }
        current_sector_totals: dict[str, int] = {}
        for symbol, weight in current.items():
            context = contexts[symbol]
            if weight > 0 and context.sector_id is not None:
                current_sector_totals[context.sector_id] = (
                    current_sector_totals.get(context.sector_id, 0) + weight
                )
        cash_floor_violated = (
            TOTAL_WEIGHT_BP - sum(current.values())
            < self._policy.minimum_cash_bp
        )
        too_many_positions = len(positive_current) > self._policy.max_positions
        result: set[str] = set()
        for symbol in sorted(target):
            if target[symbol] >= current[symbol]:
                continue
            context = contexts[symbol]
            hard_exit = bool(context.hard_risk_reasons) or context.health_state in {
                "EXIT_CANDIDATE",
                "CLOSED",
            }
            single_cap_violated = (
                current[symbol] > self._policy.max_single_position_bp
            )
            sector_cap_violated = (
                context.sector_id is not None
                and current_sector_totals.get(context.sector_id, 0)
                > self._policy.max_sector_weight_bp
            )
            position_count_repair = (
                too_many_positions and target[symbol] == 0
            )
            if (
                hard_exit
                or single_cap_violated
                or sector_cap_violated
                or position_count_repair
                or cash_floor_violated
            ):
                result.add(symbol)
        return result

    @staticmethod
    def _portfolio_turnover_bp(
        *,
        current: Mapping[str, int],
        target: Mapping[str, int],
    ) -> int:
        symbols = sorted(set(current) | set(target))
        current_positions = tuple(current.get(symbol, 0) for symbol in symbols)
        target_positions = tuple(target.get(symbol, 0) for symbol in symbols)
        return canonical_turnover_bp(
            current_position_weights_bp=current_positions,
            current_cash_bp=TOTAL_WEIGHT_BP - sum(current_positions),
            target_position_weights_bp=target_positions,
            target_cash_bp=TOTAL_WEIGHT_BP - sum(target_positions),
        )

    def _maximum_gap_within_turnover(
        self,
        *,
        symbol: str,
        requested_gap: int,
        executable: Mapping[str, int],
        current: Mapping[str, int],
        turnover_limit_bp: int,
    ) -> int:
        direction = -1 if requested_gap < 0 else 1
        low = 0
        high = abs(requested_gap)
        while low < high:
            middle = (low + high + 1) // 2
            candidate = dict(executable)
            candidate[symbol] = current[symbol] + direction * middle
            if self._portfolio_turnover_bp(
                current=current,
                target=candidate,
            ) <= turnover_limit_bp:
                low = middle
            else:
                high = middle - 1
        return direction * low

    def _apply_lot_cost_and_cash(
        self,
        *,
        request: PortfolioAllocationRequestV2,
        turnover_target: Mapping[str, int],
        current: Mapping[str, int],
        contexts: Mapping[str, PortfolioAllocationContextRow],
        row_diagnostics: dict[str, list[str]],
    ) -> tuple[
        AllocationWeightContract,
        dict[str, int],
        dict[str, int | None],
        dict[str, Decimal],
        dict[str, Decimal],
        Decimal,
    ]:
        symbols = sorted(turnover_target)
        executable = dict(current)
        shares: dict[str, int | None] = {
            symbol: contexts[symbol].current_shares for symbol in symbols
        }
        amounts = {
            symbol: self._amount_from_bp(request.capital_amount, current[symbol])
            for symbol in symbols
        }
        costs = {symbol: Decimal("0.00") for symbol in symbols}
        cash = self._amount_from_bp(request.capital_amount, request.current_cash_bp)
        reserve = self._amount_from_bp(
            request.capital_amount,
            self._policy.minimum_cash_bp,
        )

        sell_symbols = sorted(
            (
                symbol
                for symbol in symbols
                if turnover_target[symbol] < current[symbol]
            ),
            key=lambda symbol: (
                -int(
                    bool(contexts[symbol].hard_risk_reasons)
                    or contexts[symbol].health_state in {"EXIT_CANDIDATE", "CLOSED"}
                ),
                symbol,
            ),
        )
        for symbol in sell_symbols:
            context = contexts[symbol]
            if not self._is_strictly_prior_market_data(
                decision_date=request.decision_date,
                as_of_date=context.market_data_as_of_date,
            ):
                row_diagnostics[symbol].append("sell_pit_reference_unavailable")
                continue
            if context.reference_price is None or context.current_shares is None:
                row_diagnostics[symbol].append("sell_execution_inputs_missing")
                continue
            desired_reduction_amount = self._amount_from_bp(
                request.capital_amount,
                current[symbol] - turnover_target[symbol],
            )
            raw_sell_shares = int(
                (desired_reduction_amount / context.reference_price).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
            sell_shares = min(
                context.current_shares,
                round_down_to_lot(raw_sell_shares, lot_size=_LOT_SIZE),
            )
            if sell_shares <= 0:
                row_diagnostics[symbol].append("sell_below_lot_size")
                continue
            notional = quantize_money(Decimal(sell_shares) * context.reference_price)
            cost = self._cost_from_bp(notional, _SELL_COST_BP)
            executed_bp = self._bp_from_amount(notional, request.capital_amount)
            executable[symbol] = max(
                turnover_target[symbol],
                current[symbol] - executed_bp,
            )
            shares[symbol] = context.current_shares - sell_shares
            amounts[symbol] = quantize_money(
                Decimal(shares[symbol] or 0) * context.reference_price
            )
            costs[symbol] = cost
            cash = quantize_money(cash + notional - cost)
            if executable[symbol] > turnover_target[symbol]:
                row_diagnostics[symbol].append("sell_lot_size_residual")

        buy_symbols = sorted(
            (
                symbol
                for symbol in symbols
                if turnover_target[symbol] > current[symbol]
            ),
            key=lambda symbol: (
                -(turnover_target[symbol] - current[symbol]),
                symbol,
            ),
        )
        for symbol in buy_symbols:
            context = contexts[symbol]
            if context.reference_price is None:
                row_diagnostics[symbol].append("buy_reference_price_missing")
                continue
            current_shares = context.current_shares
            if current[symbol] == 0 and current_shares is None:
                current_shares = 0
            if current_shares is None:
                row_diagnostics[symbol].append("buy_current_shares_missing")
                continue
            desired_increment_amount = self._amount_from_bp(
                request.capital_amount,
                turnover_target[symbol] - current[symbol],
            )
            raw_buy_shares = int(
                (desired_increment_amount / context.reference_price).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
            desired_buy_shares = round_down_to_lot(
                raw_buy_shares,
                lot_size=_LOT_SIZE,
            )
            volume_cap_shares = (
                round_down_to_lot(
                    (context.median_volume_20d_shares or 0)
                    * _MAX_VOLUME_PARTICIPATION_PERCENT
                    // 100,
                    lot_size=_LOT_SIZE,
                )
            )
            per_lot_notional = quantize_money(
                Decimal(_LOT_SIZE) * context.reference_price
            )
            per_lot_total = quantize_money(
                per_lot_notional + self._cost_from_bp(per_lot_notional, _BUY_COST_BP)
            )
            available_cash = max(Decimal("0.00"), cash - reserve)
            affordable_lots = int(
                (available_cash / per_lot_total).to_integral_value(rounding=ROUND_DOWN)
            )
            affordable_shares = affordable_lots * _LOT_SIZE
            buy_shares = min(
                desired_buy_shares,
                volume_cap_shares,
                affordable_shares,
            )
            if buy_shares <= 0:
                row_diagnostics[symbol].append("buy_blocked_by_lot_liquidity_or_cash")
                continue
            notional = quantize_money(Decimal(buy_shares) * context.reference_price)
            cost = self._cost_from_bp(notional, _BUY_COST_BP)
            executed_bp = self._bp_from_amount(notional, request.capital_amount)
            executable[symbol] = min(
                turnover_target[symbol],
                current[symbol] + executed_bp,
            )
            shares[symbol] = current_shares + buy_shares
            amounts[symbol] = quantize_money(
                Decimal(shares[symbol] or 0) * context.reference_price
            )
            costs[symbol] = quantize_money(costs[symbol] + cost)
            cash = quantize_money(cash - notional - cost)
            if executable[symbol] < turnover_target[symbol]:
                row_diagnostics[symbol].append("buy_lot_liquidity_or_cash_cap_applied")

        if cash < reserve:
            for symbol in symbols:
                row_diagnostics[symbol].append(
                    "portfolio_post_cost_cash_below_floor_existing_state"
                )
        contract = self._contract_from_symbol_weights(executable)
        return contract, executable, shares, amounts, costs, cash

    def _execution_constraint_violations(
        self,
        *,
        request: PortfolioAllocationRequestV2,
        executable: Mapping[str, int],
        current: Mapping[str, int],
        contexts: Mapping[str, PortfolioAllocationContextRow],
        post_cost_cash_amount: Decimal,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        executable_cash_bp = TOTAL_WEIGHT_BP - sum(executable.values())
        if executable_cash_bp < self._policy.minimum_cash_bp:
            violations.append("hard_constraint_cash_weight_floor_violated")
        reserve = self._amount_from_bp(
            request.capital_amount,
            self._policy.minimum_cash_bp,
        )
        if post_cost_cash_amount < reserve:
            violations.append("hard_constraint_post_cost_cash_floor_violated")
        if any(
            weight > self._policy.max_single_position_bp
            for weight in executable.values()
        ):
            violations.append("hard_constraint_single_position_cap_violated")
        if (
            sum(1 for weight in executable.values() if weight > 0)
            > self._policy.max_positions
        ):
            violations.append("hard_constraint_position_count_violated")

        sector_totals: dict[str, int] = {}
        for symbol, weight in executable.items():
            context = contexts[symbol]
            if weight > 0 and context.sector_id is not None:
                sector_totals[context.sector_id] = (
                    sector_totals.get(context.sector_id, 0) + weight
                )
            if (
                context.hard_risk_reasons
                or context.health_state in {"EXIT_CANDIDATE", "CLOSED"}
            ) and weight > 0:
                violations.append(
                    f"hard_constraint_exit_weight_nonzero:{symbol}"
                )
            if (
                context.health_state in {"WATCH", "REDUCE_CANDIDATE"}
                and weight > current[symbol]
            ):
                violations.append(
                    f"hard_constraint_health_add_prohibited:{symbol}"
                )
        if any(
            total > self._policy.max_sector_weight_bp
            for total in sector_totals.values()
        ):
            violations.append("hard_constraint_sector_cap_violated")
        return tuple(dict.fromkeys(violations))

    @staticmethod
    def _scale_to_total(weights: Mapping[str, int], target_total: int) -> dict[str, int]:
        total = sum(weights.values())
        if total <= target_total:
            return dict(weights)
        if target_total <= 0 or total <= 0:
            return {symbol: 0 for symbol in weights}
        floors: dict[str, int] = {}
        remainders: dict[str, int] = {}
        for symbol, weight in weights.items():
            floors[symbol], remainders[symbol] = divmod(
                weight * target_total,
                total,
            )
        remaining = target_total - sum(floors.values())
        priority = sorted(
            weights,
            key=lambda symbol: (-remainders[symbol], symbol),
        )
        for symbol in priority[:remaining]:
            floors[symbol] += 1
        return floors

    @staticmethod
    def _contract_from_symbol_weights(
        weights: Mapping[str, int],
    ) -> AllocationWeightContract:
        invested = sum(weights.values())
        if invested > TOTAL_WEIGHT_BP:
            raise ValueError("projected symbol weights exceed 10000 bp")
        return AllocationWeightContract(
            symbol_weights_bp={
                symbol: weight for symbol, weight in weights.items() if weight > 0
            },
            cash_weight_bp=TOTAL_WEIGHT_BP - invested,
        )

    @staticmethod
    def _is_strictly_prior_market_data(
        *,
        decision_date: str,
        as_of_date: str | None,
    ) -> bool:
        if as_of_date is None:
            return False
        try:
            return date.fromisoformat(as_of_date) < date.fromisoformat(decision_date)
        except ValueError:
            return False

    @staticmethod
    def _amount_from_bp(capital_amount: Decimal, weight_bp: int) -> Decimal:
        return quantize_money(
            capital_amount * Decimal(weight_bp) / Decimal(TOTAL_WEIGHT_BP)
        )

    @staticmethod
    def _bp_from_amount(amount: Decimal, capital_amount: Decimal) -> int:
        return int(
            (
                amount * Decimal(TOTAL_WEIGHT_BP) / capital_amount
            ).to_integral_value(rounding=ROUND_DOWN)
        )

    @staticmethod
    def _cost_from_bp(notional: Decimal, cost_bp: int) -> Decimal:
        return quantize_money(
            notional * Decimal(cost_bp) / Decimal(TOTAL_WEIGHT_BP)
        )

    @staticmethod
    def _gap(
        target_weight_bp: int,
        context: PortfolioAllocationContextRow | None,
    ) -> int | None:
        if context is None or context.current_weight_bp is None:
            return None
        return target_weight_bp - context.current_weight_bp

    @staticmethod
    def _advice_action(
        *,
        rows: tuple[PortfolioAllocationRowV2, ...],
        current_complete: bool,
        contexts: Mapping[str, PortfolioAllocationContextRow],
    ) -> str:
        if not current_complete:
            return "NO_NEW_POSITION"
        for row in rows:
            context = contexts[row.stock_code]
            if (
                row.current_weight_bp is not None
                and row.target_weight_bp < row.current_weight_bp
                and (
                    context.hard_risk_reasons
                    or context.health_state in {"EXIT_CANDIDATE", "CLOSED"}
                )
            ):
                return "EXIT_CANDIDATE"
        if rows and all(row.executable_weight_bp is None for row in rows):
            return "NO_NEW_POSITION"
        if any(
            row.executable_weight_bp is not None
            and row.current_weight_bp is not None
            and row.executable_weight_bp < row.current_weight_bp
            for row in rows
        ):
            return "REDUCE_CANDIDATE"
        if any(
            row.executable_weight_bp is not None
            and row.current_weight_bp is not None
            and row.executable_weight_bp > row.current_weight_bp
            for row in rows
        ):
            return "ADD_CANDIDATE"
        if all(row.target_weight_bp == 0 for row in rows):
            return "NO_NEW_POSITION"
        return "HOLD"


DeterministicPortfolioAllocationService = PortfolioAllocationService
