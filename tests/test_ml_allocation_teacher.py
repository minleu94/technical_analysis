from __future__ import annotations

from dataclasses import replace

import pytest

from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
)
from ml_module.allocation_teacher import (
    CausalAllocationTeacher,
    CausalAllocationTeacherPolicy,
    CausalTeacherRequest,
    TeacherCandidateOutcome,
)


_HASH = "sha256:" + "c" * 64


def _candidate(
    symbol: str,
    *,
    sector_id: str,
    return_bp: int,
    cvar_bp: int = 500,
    drawdown_bp: int = 700,
    **overrides: object,
) -> TeacherCandidateOutcome:
    values: dict[str, object] = {
        "symbol": symbol,
        "sector_id": sector_id,
        "realized_after_cost_excess_20d_bp": return_bp,
        "cvar_loss_bp": cvar_bp,
        "max_drawdown_bp": drawdown_bp,
        "horizon_end_date": "2026-02-01",
        "label_available_at": "2026-02-02T18:00:00+08:00",
        "label_source_hash": _HASH,
        "eligible": True,
    }
    values.update(overrides)
    return TeacherCandidateOutcome(**values)  # type: ignore[arg-type]


def _state(
    *,
    positions_bp: tuple[tuple[str, int], ...] = (),
    cash_bp: int = 10_000,
    as_of_date: str = "2026-01-01",
    weekly_turnover_used_bp: int = 0,
) -> CausalPortfolioState:
    return CausalPortfolioState.create(
        as_of_date=as_of_date,
        weights=AllocationWeightContract(
            positions_bp=positions_bp,
            cash_bp=cash_bp,
        ),
        weekly_turnover_used_bp=weekly_turnover_used_bp,
    )


def _request(
    *,
    state: CausalPortfolioState | None = None,
    candidates: tuple[TeacherCandidateOutcome, ...] | None = None,
    training_as_of: str = "2026-02-03T08:30:00+08:00",
) -> CausalTeacherRequest:
    return CausalTeacherRequest(
        decision_date="2026-01-02",
        training_as_of=training_as_of,
        portfolio_state=state or _state(),
        candidates=candidates
        or (
            _candidate("1101", sector_id="cement", return_bp=900),
            _candidate("1102", sector_id="cement", return_bp=800),
            _candidate("2330", sector_id="semiconductor", return_bp=700),
            _candidate("2317", sector_id="electronics", return_bp=600),
        ),
    )


def test_teacher_uses_grid_and_satisfies_all_hard_limits() -> None:
    result = CausalAllocationTeacher().build_targets(_request())
    weights = dict(result.targets.target_weights.positions_bp)

    assert result.portfolio_state_as_of_date == "2026-01-01"
    assert result.max_label_available_at == "2026-02-02T18:00:00+08:00"
    assert result.new_turnover_bp <= 2000
    assert result.total_weekly_turnover_bp <= 2000
    assert result.targets.cash_bp >= 2000
    assert len(weights) <= 8
    assert all(value % 100 == 0 and value <= 1500 for value in weights.values())
    assert sum(value for symbol, value in weights.items() if symbol in {"1101", "1102"}) <= 3000
    assert sum(weights.values()) + result.targets.cash_bp == 10_000
    assert sum(dict(result.targets.risk_contributions_bp).values()) == sum(
        weights.values()
    )
    assert result.targets.rebalance_worthwhile is True
    assert result.search_complete is True


def test_primary_values_within_ten_bp_use_cvar_then_drawdown_tie_break() -> None:
    policy = CausalAllocationTeacherPolicy(max_positions=1)
    candidates = (
        _candidate(
            "2330",
            sector_id="semiconductor",
            return_bp=1000,
            cvar_bp=900,
            drawdown_bp=900,
        ),
        _candidate(
            "2317",
            sector_id="electronics",
            return_bp=995,
            cvar_bp=100,
            drawdown_bp=100,
        ),
    )

    result = CausalAllocationTeacher(policy).build_targets(
        _request(candidates=candidates)
    )

    assert result.targets.target_weights.positions_bp == (("2317", 1500),)


def test_primary_difference_over_tolerance_keeps_higher_return_candidate() -> None:
    policy = CausalAllocationTeacherPolicy(max_positions=1)
    candidates = (
        _candidate(
            "2330",
            sector_id="semiconductor",
            return_bp=1000,
            cvar_bp=900,
        ),
        _candidate(
            "2317",
            sector_id="electronics",
            return_bp=800,
            cvar_bp=100,
        ),
    )

    result = CausalAllocationTeacher(policy).build_targets(
        _request(candidates=candidates)
    )

    # 1,400 bp 與 primary 最大值相差正好 10 bp，因此依契約改採較低風險。
    assert result.targets.target_weights.positions_bp == (("2330", 1400),)


def test_turnover_is_measured_from_t_minus_one_state_not_future_portfolio() -> None:
    policy = CausalAllocationTeacherPolicy(max_positions=1)
    state = _state(positions_bp=(("1101", 1500),), cash_bp=8500)
    candidates = (
        _candidate("1101", sector_id="cement", return_bp=-1000),
        _candidate("2330", sector_id="semiconductor", return_bp=1000),
    )

    result = CausalAllocationTeacher(policy).build_targets(
        _request(state=state, candidates=candidates)
    )

    # 500 bp 是 primary 最大值；400 bp 落在 10 bp tolerance 內且風險較低。
    assert result.targets.target_weights.positions_bp == (("2330", 400),)
    assert dict(result.targets.delta_weights_bp) == {"1101": -1500, "2330": 400}
    # 完整投組（含現金）的 one-way turnover：
    # |A -1500| + |B +400| + |cash +1100| = 3000，除以二為 1500 bp。
    assert result.new_turnover_bp == 1500


def test_teacher_rejects_same_day_state_unmatured_labels_and_off_grid_state() -> None:
    teacher = CausalAllocationTeacher()
    with pytest.raises(ValueError, match="T-1"):
        teacher.build_targets(
            _request(state=_state(as_of_date="2026-01-02"))
        )
    with pytest.raises(ValueError, match="matured"):
        teacher.build_targets(
            _request(training_as_of="2026-02-02T12:00:00+08:00")
        )
    with pytest.raises(ValueError, match="teacher grid"):
        teacher.build_targets(
            _request(
                state=_state(
                    positions_bp=(("1101", 550),),
                    cash_bp=9450,
                )
            )
        )


def test_teacher_rejects_missing_current_outcome_and_future_horizon_leakage() -> None:
    teacher = CausalAllocationTeacher()
    with pytest.raises(ValueError, match="current position"):
        teacher.build_targets(
            _request(
                state=_state(
                    positions_bp=(("9999", 500),),
                    cash_bp=9500,
                )
            )
        )
    invalid = replace(
        _candidate("2330", sector_id="semiconductor", return_bp=1000),
        horizon_end_date="2026-01-02",
    )
    with pytest.raises(ValueError, match="horizon"):
        teacher.build_targets(_request(candidates=(invalid,)))


def test_bounded_candidate_search_is_explicitly_ineligible_for_formal_labels() -> None:
    candidates = tuple(
        _candidate(
            f"{index:04d}",
            sector_id=f"sector-{index}",
            return_bp=1000 - index,
        )
        for index in range(9)
    )
    teacher = CausalAllocationTeacher(
        CausalAllocationTeacherPolicy(
            max_positions=1,
            search_candidate_limit=8,
        )
    )

    result = teacher.build_targets(_request(candidates=candidates))

    assert result.search_candidate_count == 8
    assert result.search_complete is False
    assert result.formal_label_eligible is False
