"""以 T-1 投組狀態建立 100 bp 格點的 causal allocation teacher。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Iterable

from financial_module.portfolio_turnover import canonical_turnover_bp
from ml_module.allocation_contracts import (
    AllocationTargets,
    AllocationWeightContract,
    CausalPortfolioState,
)


@dataclass(frozen=True)
class CausalAllocationTeacherPolicy:
    grid_bp: int = 100
    minimum_cash_bp: int = 2000
    max_positions: int = 8
    max_single_position_bp: int = 1500
    max_sector_weight_bp: int = 3000
    weekly_turnover_cap_bp: int = 2000
    primary_tolerance_bp: int = 10
    search_beam_width: int = 4096
    search_candidate_limit: int = 24

    def __post_init__(self) -> None:
        for field_name in (
            "grid_bp",
            "minimum_cash_bp",
            "max_positions",
            "max_single_position_bp",
            "max_sector_weight_bp",
            "weekly_turnover_cap_bp",
            "primary_tolerance_bp",
            "search_beam_width",
            "search_candidate_limit",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if 10_000 % self.grid_bp != 0:
            raise ValueError("grid_bp must divide 10000 exactly")
        for field_name in (
            "minimum_cash_bp",
            "max_single_position_bp",
            "max_sector_weight_bp",
            "weekly_turnover_cap_bp",
        ):
            if getattr(self, field_name) % self.grid_bp != 0:
                raise ValueError(f"{field_name} must align to grid_bp")
        if not 1 <= self.max_positions <= 8:
            raise ValueError("max_positions must be within 1..8")
        if not self.minimum_cash_bp <= 10_000:
            raise ValueError("minimum_cash_bp must not exceed 10000")
        if not self.max_single_position_bp <= 1500:
            raise ValueError("max_single_position_bp must not exceed 1500")
        if not self.max_sector_weight_bp <= 3000:
            raise ValueError("max_sector_weight_bp must not exceed 3000")
        if not self.weekly_turnover_cap_bp <= 2000:
            raise ValueError("weekly_turnover_cap_bp must not exceed 2000")
        if self.search_candidate_limit < self.max_positions:
            raise ValueError("search_candidate_limit must cover max_positions")


@dataclass(frozen=True)
class TeacherCandidateOutcome:
    """決策後成熟的 supervised outcome；不得拿來構造當日 portfolio state。"""

    symbol: str
    sector_id: str
    realized_after_cost_excess_20d_bp: int
    cvar_loss_bp: int
    max_drawdown_bp: int
    horizon_end_date: str
    label_available_at: str
    label_source_hash: str
    eligible: bool = True

    def __post_init__(self) -> None:
        if not self.symbol or not self.symbol.strip():
            raise ValueError("symbol is required")
        if not self.sector_id or not self.sector_id.strip():
            raise ValueError("sector_id is required")
        _require_integer(
            "realized_after_cost_excess_20d_bp",
            self.realized_after_cost_excess_20d_bp,
        )
        for field_name in ("cvar_loss_bp", "max_drawdown_bp"):
            value = _require_integer(field_name, getattr(self, field_name))
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        _parse_date(self.horizon_end_date, field_name="horizon_end_date")
        _parse_datetime(self.label_available_at, field_name="label_available_at")
        _require_sha256(self.label_source_hash, field_name="label_source_hash")
        if not isinstance(self.eligible, bool):
            raise TypeError("eligible must be bool")


@dataclass(frozen=True)
class CausalTeacherRequest:
    decision_date: str
    training_as_of: str
    portfolio_state: CausalPortfolioState
    candidates: tuple[TeacherCandidateOutcome, ...]


@dataclass(frozen=True)
class CausalTeacherResult:
    targets: AllocationTargets
    primary_after_cost_excess_bp: int
    weighted_cvar_loss_numerator: int
    weighted_max_drawdown_numerator: int
    new_turnover_bp: int
    total_weekly_turnover_bp: int
    evaluated_state_count: int
    input_candidate_count: int
    search_candidate_count: int
    search_complete: bool
    formal_label_eligible: bool
    portfolio_state_as_of_date: str
    max_label_available_at: str


@dataclass(frozen=True)
class _ScoredState:
    weights: tuple[int, ...]
    primary_numerator: int
    cvar_numerator: int
    drawdown_numerator: int
    turnover_bp: int
    concentration: int


class CausalAllocationTeacher:
    """建立受硬限制約束的配置標籤，不讀取未來 portfolio state。"""

    def __init__(self, policy: CausalAllocationTeacherPolicy | None = None) -> None:
        self._policy = policy or CausalAllocationTeacherPolicy()

    def build_targets(self, request: CausalTeacherRequest) -> CausalTeacherResult:
        decision = _parse_date(request.decision_date, field_name="decision_date")
        training_as_of = _parse_datetime(
            request.training_as_of, field_name="training_as_of"
        )
        state_date = _parse_date(
            request.portfolio_state.as_of_date,
            field_name="portfolio_state.as_of_date",
        )
        if state_date >= decision:
            raise ValueError("portfolio state must be observed no later than T-1")
        if request.portfolio_state.weekly_turnover_used_bp > (
            self._policy.weekly_turnover_cap_bp
        ):
            raise ValueError("portfolio state already exceeds weekly turnover cap")
        if not request.candidates:
            raise ValueError("teacher candidates are required")
        by_symbol = self._validate_candidates(
            request.candidates,
            decision=decision,
            training_as_of=training_as_of,
        )
        current = dict(request.portfolio_state.weights.positions_bp)
        missing_current = sorted(set(current) - set(by_symbol))
        if missing_current:
            raise ValueError(
                "every current position requires a matured teacher outcome: "
                + ",".join(missing_current)
            )
        self._validate_current_state(request.portfolio_state, by_symbol)

        selected_candidates = self._select_search_candidates(
            by_symbol.values(),
            current_symbols=frozenset(current),
        )
        relevant_symbols = {
            candidate.symbol
            for candidate in request.candidates
            if candidate.eligible or candidate.symbol in current
        }
        candidate_selection_complete = {
            candidate.symbol for candidate in selected_candidates
        } == relevant_symbols
        symbols = tuple(candidate.symbol for candidate in selected_candidates)
        current_weights = tuple(current.get(symbol, 0) for symbol in symbols)
        remaining_turnover_bp = (
            self._policy.weekly_turnover_cap_bp
            - request.portfolio_state.weekly_turnover_used_bp
        )
        states, search_complete = self._search(
            candidates=selected_candidates,
            current_weights=current_weights,
            remaining_turnover_bp=remaining_turnover_bp,
        )
        chosen = self._select_best_state(states)
        target_positions = tuple(
            (symbol, weight)
            for symbol, weight in zip(symbols, chosen.weights)
            if weight > 0
        )
        target_cash = 10_000 - sum(weight for _, weight in target_positions)
        target_contract = AllocationWeightContract(
            positions_bp=target_positions,
            cash_bp=target_cash,
        )

        current_all = dict(request.portfolio_state.weights.positions_bp)
        target_all = dict(target_positions)
        delta = tuple(
            (symbol, target_all.get(symbol, 0) - current_all.get(symbol, 0))
            for symbol in sorted(set(current_all) | set(target_all))
            if target_all.get(symbol, 0) != current_all.get(symbol, 0)
        )
        risk_contributions = _risk_contributions(
            target_positions=target_positions,
            candidates=by_symbol,
            risky_budget_bp=target_contract.invested_bp,
        )
        max_label_available = max(
            request.candidates,
            key=lambda row: _parse_datetime(
                row.label_available_at, field_name="label_available_at"
            ),
        ).label_available_at
        max_horizon_end = max(
            request.candidates,
            key=lambda row: _parse_date(
                row.horizon_end_date, field_name="horizon_end_date"
            ),
        ).horizon_end_date
        targets = AllocationTargets(
            decision_date=decision.isoformat(),
            horizon_end_date=max_horizon_end,
            available_at=max_label_available,
            target_weights=target_contract,
            delta_weights_bp=delta,
            risk_contributions_bp=risk_contributions,
            risky_budget_bp=target_contract.invested_bp,
            cash_bp=target_cash,
            rebalance_worthwhile=bool(delta),
        )
        return CausalTeacherResult(
            targets=targets,
            primary_after_cost_excess_bp=_round_ratio(
                chosen.primary_numerator, 10_000
            ),
            weighted_cvar_loss_numerator=chosen.cvar_numerator,
            weighted_max_drawdown_numerator=chosen.drawdown_numerator,
            new_turnover_bp=chosen.turnover_bp,
            total_weekly_turnover_bp=(
                request.portfolio_state.weekly_turnover_used_bp
                + chosen.turnover_bp
            ),
            evaluated_state_count=len(states),
            input_candidate_count=len(request.candidates),
            search_candidate_count=len(selected_candidates),
            search_complete=search_complete and candidate_selection_complete,
            formal_label_eligible=search_complete and candidate_selection_complete,
            portfolio_state_as_of_date=request.portfolio_state.as_of_date,
            max_label_available_at=max_label_available,
        )

    def _validate_candidates(
        self,
        candidates: tuple[TeacherCandidateOutcome, ...],
        *,
        decision: date,
        training_as_of: datetime,
    ) -> dict[str, TeacherCandidateOutcome]:
        symbols = tuple(candidate.symbol for candidate in candidates)
        if len(symbols) != len(set(symbols)):
            raise ValueError("teacher candidate symbols must be unique")
        for candidate in candidates:
            horizon_end = _parse_date(
                candidate.horizon_end_date, field_name="horizon_end_date"
            )
            if horizon_end <= decision:
                raise ValueError("teacher horizon must be after decision_date")
            available_at = _parse_datetime(
                candidate.label_available_at, field_name="label_available_at"
            )
            if available_at.date() < horizon_end:
                raise ValueError("label_available_at must not precede horizon_end_date")
            if available_at > training_as_of:
                raise ValueError("teacher may use only labels matured by training_as_of")
        return {candidate.symbol: candidate for candidate in candidates}

    def _validate_current_state(
        self,
        state: CausalPortfolioState,
        candidates: dict[str, TeacherCandidateOutcome],
    ) -> None:
        weights = dict(state.weights.positions_bp)
        values = (*weights.values(), state.weights.cash_bp)
        if any(value % self._policy.grid_bp != 0 for value in values):
            raise ValueError("current portfolio must align to the teacher grid")
        if state.weights.cash_bp < self._policy.minimum_cash_bp:
            raise ValueError("current portfolio violates minimum cash")
        if len(weights) > self._policy.max_positions:
            raise ValueError("current portfolio violates max positions")
        if any(
            weight > self._policy.max_single_position_bp
            for weight in weights.values()
        ):
            raise ValueError("current portfolio violates single-position cap")
        sector_weights: dict[str, int] = {}
        for symbol, weight in weights.items():
            sector = candidates[symbol].sector_id
            sector_weights[sector] = sector_weights.get(sector, 0) + weight
        if any(
            weight > self._policy.max_sector_weight_bp
            for weight in sector_weights.values()
        ):
            raise ValueError("current portfolio violates sector cap")

    def _select_search_candidates(
        self,
        candidates: Iterable[TeacherCandidateOutcome],
        *,
        current_symbols: frozenset[str],
    ) -> tuple[TeacherCandidateOutcome, ...]:
        by_symbol = {candidate.symbol: candidate for candidate in candidates}
        selected = set(current_symbols)
        eligible = sorted(
            (candidate for candidate in by_symbol.values() if candidate.eligible),
            key=lambda row: (
                -row.realized_after_cost_excess_20d_bp,
                row.cvar_loss_bp,
                row.max_drawdown_bp,
                row.sector_id,
                row.symbol,
            ),
        )
        new_per_sector: dict[str, int] = {}
        for candidate in eligible:
            if candidate.symbol in selected:
                continue
            if new_per_sector.get(candidate.sector_id, 0) >= 2:
                continue
            selected.add(candidate.symbol)
            new_per_sector[candidate.sector_id] = (
                new_per_sector.get(candidate.sector_id, 0) + 1
            )
            if len(selected) >= self._policy.search_candidate_limit:
                break
        return tuple(by_symbol[symbol] for symbol in sorted(selected))

    def _search(
        self,
        *,
        candidates: tuple[TeacherCandidateOutcome, ...],
        current_weights: tuple[int, ...],
        remaining_turnover_bp: int,
    ) -> tuple[tuple[_ScoredState, ...], bool]:
        initial = self._score_state(
            weights=current_weights,
            candidates=candidates,
            current_weights=current_weights,
        )
        frontier: tuple[tuple[int, ...], ...] = (current_weights,)
        visited: set[tuple[int, ...]] = {current_weights}
        scored_states: list[_ScoredState] = [initial]
        search_complete = True
        step_count = remaining_turnover_bp // self._policy.grid_bp

        for _ in range(step_count):
            generated: set[tuple[int, ...]] = set()
            for weights in frontier:
                for index, candidate in enumerate(candidates):
                    for delta in (-self._policy.grid_bp, self._policy.grid_bp):
                        updated_weight = weights[index] + delta
                        if updated_weight < 0:
                            continue
                        updated = list(weights)
                        updated[index] = updated_weight
                        state = tuple(updated)
                        if state in visited:
                            continue
                        if not self._is_feasible(
                            state,
                            candidates=candidates,
                            current_weights=current_weights,
                        ):
                            continue
                        turnover = _turnover_bp(state, current_weights)
                        if turnover > remaining_turnover_bp:
                            continue
                        if (
                            not candidate.eligible
                            and updated_weight > current_weights[index]
                        ):
                            continue
                        generated.add(state)

            if not generated:
                break
            ranked = sorted(
                (
                    self._score_state(
                        weights=weights,
                        candidates=candidates,
                        current_weights=current_weights,
                    )
                    for weights in generated
                ),
                key=_beam_key,
            )
            if len(ranked) > self._policy.search_beam_width:
                search_complete = False
                ranked = ranked[: self._policy.search_beam_width]
            frontier = tuple(row.weights for row in ranked)
            visited.update(frontier)
            scored_states.extend(ranked)
        return tuple(scored_states), search_complete

    def _is_feasible(
        self,
        weights: tuple[int, ...],
        *,
        candidates: tuple[TeacherCandidateOutcome, ...],
        current_weights: tuple[int, ...],
    ) -> bool:
        if any(
            weight < 0
            or weight > self._policy.max_single_position_bp
            or weight % self._policy.grid_bp != 0
            for weight in weights
        ):
            return False
        invested = sum(weights)
        if 10_000 - invested < self._policy.minimum_cash_bp:
            return False
        if sum(weight > 0 for weight in weights) > self._policy.max_positions:
            return False
        sector_weights: dict[str, int] = {}
        for candidate, weight in zip(candidates, weights):
            sector_weights[candidate.sector_id] = (
                sector_weights.get(candidate.sector_id, 0) + weight
            )
        if any(
            value > self._policy.max_sector_weight_bp
            for value in sector_weights.values()
        ):
            return False
        return _turnover_bp(weights, current_weights) <= (
            self._policy.weekly_turnover_cap_bp
        )

    @staticmethod
    def _score_state(
        *,
        weights: tuple[int, ...],
        candidates: tuple[TeacherCandidateOutcome, ...],
        current_weights: tuple[int, ...],
    ) -> _ScoredState:
        return _ScoredState(
            weights=weights,
            primary_numerator=sum(
                weight * candidate.realized_after_cost_excess_20d_bp
                for candidate, weight in zip(candidates, weights)
            ),
            cvar_numerator=sum(
                weight * candidate.cvar_loss_bp
                for candidate, weight in zip(candidates, weights)
            ),
            drawdown_numerator=sum(
                weight * candidate.max_drawdown_bp
                for candidate, weight in zip(candidates, weights)
            ),
            turnover_bp=_turnover_bp(weights, current_weights),
            concentration=sum(weight * weight for weight in weights),
        )

    def _select_best_state(
        self, states: tuple[_ScoredState, ...]
    ) -> _ScoredState:
        if not states:
            raise ValueError("teacher search produced no feasible state")
        best_primary = max(state.primary_numerator for state in states)
        tolerance_numerator = self._policy.primary_tolerance_bp * 10_000
        near_best = tuple(
            state
            for state in states
            if state.primary_numerator >= best_primary - tolerance_numerator
        )
        return min(
            near_best,
            key=lambda state: (
                state.cvar_numerator,
                state.drawdown_numerator,
                state.turnover_bp,
                state.concentration,
                state.weights,
            ),
        )


def _beam_key(state: _ScoredState) -> tuple[object, ...]:
    return (
        -state.primary_numerator,
        state.cvar_numerator,
        state.drawdown_numerator,
        state.turnover_bp,
        state.concentration,
        state.weights,
    )


def _turnover_bp(
    target_weights: tuple[int, ...], current_weights: tuple[int, ...]
) -> int:
    return canonical_turnover_bp(
        current_position_weights_bp=current_weights,
        current_cash_bp=10_000 - sum(current_weights),
        target_position_weights_bp=target_weights,
        target_cash_bp=10_000 - sum(target_weights),
    )


def _risk_contributions(
    *,
    target_positions: tuple[tuple[str, int], ...],
    candidates: dict[str, TeacherCandidateOutcome],
    risky_budget_bp: int,
) -> tuple[tuple[str, int], ...]:
    if not target_positions:
        return ()
    raw = tuple(
        (
            symbol,
            weight * max(candidates[symbol].cvar_loss_bp, 1),
        )
        for symbol, weight in target_positions
    )
    denominator = sum(value for _, value in raw)
    floors = {
        symbol: risky_budget_bp * value // denominator for symbol, value in raw
    }
    remaining = risky_budget_bp - sum(floors.values())
    remainders = sorted(
        (
            (-(risky_budget_bp * value % denominator), symbol)
            for symbol, value in raw
        )
    )
    for _, symbol in remainders[:remaining]:
        floors[symbol] += 1
    return tuple((symbol, floors[symbol]) for symbol, _ in target_positions)


def _round_ratio(numerator: int, denominator: int) -> int:
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )


def _require_integer(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer units")
    return value


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _parse_datetime(value: str, *, field_name: str) -> datetime:
    try:
        if len(value) == 10:
            parsed = datetime.fromisoformat(f"{value}T23:59:59+08:00")
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be a sha256: digest")
