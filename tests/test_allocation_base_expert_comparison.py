from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from ml_module.allocation_base_expert_comparison import (
    AllocationBaseExpertComparisonRequest,
    COMPARISON_SCHEMA_VERSION,
    LIQUIDITY_POOL_POLICY_VERSION,
    LOT_EXECUTION_POLICY_VERSION,
    _LaneAccumulator,
    _LaneDefinition,
    _SelectedRow,
    _accumulate_lane,
    _close_to_close_return_bp,
    _equity_total_return_bp,
    _lane_daily_metrics,
    _lane_summary,
    _maximum_drawdown_from_equities,
    _research_no_sector_eligibility,
    _research_lot_aware_requested,
    _research_turnover_capped_requested,
    _select_liquidity_pool,
    build_allocation_base_expert_comparison,
    preflight_allocation_base_expert_comparison,
)
from ml_module.allocation_oos_replay_input_builder import (
    _ALLOWED_TRADABLE,
    _Bar,
    _Candidate,
    _LaneState,
    _eligible_for_new_position,
    _execute_day,
    _money_minor,
    _turnover_bp,
    INITIAL_CAPITAL,
)


pytest_plugins = ("tests.test_portfolio_ml_out_of_core_pipeline",)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _install_fixture_replay_sources(store_manifest_path: Path) -> None:
    """在隔離 fixture store 補上明確的 replay source 測試資料。"""

    store = _read_json(store_manifest_path)
    for year in store["years"]:
        year_directory = store_manifest_path.parent / f"year={int(year['year']):04d}"
        source_path = year_directory / "replay_source.sqlite"
        with sqlite3.connect(year_directory / "rows.sqlite") as rows_connection:
            rows = rows_connection.execute(
                "SELECT local_row_index, decision_at, decision_date, symbol "
                "FROM rows ORDER BY local_row_index"
            ).fetchall()
        source_rows: list[tuple[object, ...]] = []
        for local_row_index, decision_at, decision_date, symbol in rows:
            decision_datetime = datetime.fromisoformat(str(decision_at))
            previous_datetime = decision_datetime - timedelta(days=1)
            previous_date = (
                date.fromisoformat(str(decision_date)) - timedelta(days=1)
            ).isoformat()
            source_rows.append(
                (
                    int(local_row_index),
                    str(decision_at),
                    str(decision_date),
                    str(symbol),
                    None,
                    previous_datetime.isoformat(),
                    previous_datetime.isoformat(),
                    1_000,
                    100,
                    1_100,
                    100,
                    1_000_000,
                    1_000_000,
                    100,
                    "officially_tradable",
                    "fixture-source-" + str(local_row_index),
                )
            )
            # 這是隔離 fixture 的跨年可得 volume history；補足 20 個
            # distinct causal events，讓 sidecar 與 Direct writer 的 stored
            # median 做 parity。這些 rows 不寫入正式 store。
            for history_index in range(1, 21):
                history_decision_at = decision_datetime - timedelta(
                    days=history_index + 1
                )
                history_event_at = history_decision_at - timedelta(hours=1)
                history_date = (
                    date.fromisoformat(str(decision_date))
                    - timedelta(days=history_index + 1)
                ).isoformat()
                source_rows.append(
                    (
                        -2_000_000_000
                        - int(local_row_index) * 100
                        - history_index,
                        history_decision_at.isoformat(),
                        history_date,
                        str(symbol),
                        None,
                        history_event_at.isoformat(),
                        history_event_at.isoformat(),
                        1_000,
                        100,
                        1_000,
                        100,
                        1_000_000,
                        1_000_000,
                        100,
                        "officially_tradable",
                        "fixture-prior-source-"
                        + str(local_row_index)
                        + "-"
                        + str(history_index),
                    )
                )
        with sqlite3.connect(source_path) as connection:
            connection.execute(
                """
                CREATE TABLE replay_source(
                    local_row_index INTEGER PRIMARY KEY,
                    decision_at TEXT NOT NULL,
                    decision_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    sector_id TEXT,
                    price_event_at TEXT,
                    price_available_at TEXT,
                    open_int INTEGER,
                    open_scale INTEGER,
                    close_int INTEGER,
                    close_scale INTEGER,
                    volume_shares INTEGER,
                    median_volume_20d_shares INTEGER,
                    rule_score_bp INTEGER,
                    trade_restriction_status TEXT NOT NULL,
                    source_values_hash TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO replay_source(
                    local_row_index, decision_at, decision_date, symbol,
                    sector_id, price_event_at, price_available_at,
                    open_int, open_scale, close_int, close_scale,
                    volume_shares, median_volume_20d_shares, rule_score_bp,
                    trade_restriction_status, source_values_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                source_rows,
            )


def _fixture_candidate() -> _Candidate:
    decision_at = datetime(2026, 4, 2, 8, 30, tzinfo=timezone.utc)
    return _Candidate(
        fold_id="fold-004",
        decision_date=date(2026, 4, 2),
        decision_at=decision_at,
        symbol="AAA",
        sector_id=None,
        price_event_at=decision_at - timedelta(days=1),
        price_available_at=decision_at - timedelta(hours=1),
        median_volume_20d_shares=1_000_000,
        rule_score_bp=100,
        trade_restriction_status=next(iter(_ALLOWED_TRADABLE)),
        source_values_hash="sha256:" + ("a" * 64),
        ml_target_weight_bp=None,
        t_minus_one_close_price=Decimal("10"),
        t_minus_one_close_available_at=decision_at - timedelta(days=1),
        t_minus_one_close_source_values_hash="sha256:" + ("d" * 64),
    )


def _fixture_bar() -> _Bar:
    return _Bar(
        symbol="AAA",
        event_date=date(2026, 4, 2),
        available_at=datetime(2026, 4, 2, 8, 0, tzinfo=timezone.utc),
        open_price=Decimal("10"),
        close_price=Decimal("11"),
        open_int=10,
        open_scale=0,
        close_int=11,
        close_scale=0,
        volume_shares=1_000_000,
        source_values_hash="sha256:" + ("b" * 64),
    )


def test_close_to_close_equity_includes_overnight_gap() -> None:
    # 第一天收盤 100，隔夜跳到第二天開盤 110 並收在 110；連續 close
    # equity 必須留下 10% 隔夜收益，不能只計第二天 open-to-close。
    first_close_minor = 10_000
    second_day_close_minor = 11_000
    assert (
        _close_to_close_return_bp(
            previous_close_minor=first_close_minor,
            closing_minor=second_day_close_minor,
        )
        == 1_000
    )
    assert _equity_total_return_bp(
        [first_close_minor, second_day_close_minor],
        first_close_minor,
    ) == 1_000
    assert _maximum_drawdown_from_equities(
        [first_close_minor, second_day_close_minor, 10_500],
        first_close_minor,
    ) == 455


def test_execute_day_default_strict_contract_is_unchanged_by_research_option() -> None:
    candidate = _fixture_candidate()
    bars = {candidate.symbol: _fixture_bar()}
    requested = {candidate.symbol: 8_000, "CASH": 2_000}

    default_metrics, default_transition = _execute_day(
        state=_LaneState(),
        decision_day=candidate.decision_date,
        session_index=0,
        candidates=(candidate,),
        bars=bars,
        requested=requested,
    )
    explicit_strict_metrics, explicit_strict_transition = _execute_day(
        state=_LaneState(),
        decision_day=candidate.decision_date,
        session_index=0,
        candidates=(candidate,),
        bars=bars,
        requested=requested,
        eligibility_fn=_eligible_for_new_position,
        enforce_sector_cap=True,
    )
    assert default_metrics == explicit_strict_metrics
    assert default_transition == explicit_strict_transition
    assert default_transition["calculation"]["holdings"] == []

    research_metrics, research_transition = _execute_day(
        state=_LaneState(),
        decision_day=candidate.decision_date,
        session_index=0,
        candidates=(candidate,),
        bars=bars,
        requested=requested,
        eligibility_fn=lambda item: (
            item.price_event_at is not None
            and item.price_event_at < item.decision_at
            and bool(item.median_volume_20d_shares)
            and item.trade_restriction_status in _ALLOWED_TRADABLE
        ),
        enforce_sector_cap=False,
    )
    assert research_metrics["turnover_bp"] > 0
    assert research_transition["calculation"]["holdings"]
    assert research_transition["calculation"]["holdings"][0][
        "post_trade_shares"
    ] > 0


def test_execute_day_band_freeze_preserves_lots_when_bp_floor_would_drop_one() -> None:
    # 33.33 元的非整除價格使 1,000 股約為 666bp；target 667bp 在
    # rebalance band 內，量化回 shares 不得把現有一張錯誤 floor 成零張。
    candidate = _fixture_candidate()
    candidate = candidate.__class__(
        **{
            **candidate.__dict__,
            "sector_id": "S1",
        }
    )
    bar = _Bar(
        symbol="AAA",
        event_date=candidate.decision_date,
        available_at=candidate.decision_at,
        open_price=Decimal("33.33"),
        close_price=Decimal("33.33"),
        open_int=3333,
        open_scale=100,
        close_int=3333,
        close_scale=100,
        volume_shares=1_000_000,
        source_values_hash="sha256:" + ("e" * 64),
    )
    state = _LaneState(cash=Decimal("466670.00"), shares={"AAA": 1_000})
    metrics, transition = _execute_day(
        state=state,
        decision_day=candidate.decision_date,
        session_index=0,
        candidates=(candidate,),
        bars={"AAA": bar},
        requested={"AAA": 667, "CASH": 9_333},
    )
    assert metrics["turnover_bp"] == 0
    assert state.shares["AAA"] == 1_000
    assert transition["calculation"]["transaction_cost_minor"] == 0
    assert transition["calculation"]["holdings"][0]["post_trade_shares"] == 1_000


def test_two_day_execute_day_equity_summary_keeps_overnight_holdings() -> None:
    definition = _LaneDefinition(
        lane_id="research_no_sector_cap__fixture",
        lane_kind="base_expert_challenger",
        selection_policy="fixture",
        scenario="research_no_sector_cap",
        pack_id="fixture-pack",
        algorithm="ridge_logistic",
    )
    accumulator = _LaneAccumulator(
        definition=definition,
        state=_LaneState(),
        gross_returns_bp=[],
        net_returns_bp=[],
        net_equities_minor=[],
        gross_equities_minor=[],
        daily=[],
    )
    requested = {"AAA": 8_000, "CASH": 2_000}
    for session_index, (day, open_price, close_price) in enumerate(
        (
            (date(2026, 4, 2), Decimal("10"), Decimal("10")),
            (date(2026, 4, 3), Decimal("11"), Decimal("11")),
        )
    ):
        decision_at = datetime(
            day.year,
            day.month,
            day.day,
            8,
            30,
            tzinfo=timezone.utc,
        )
        candidate = _Candidate(
            fold_id="fold-004",
            decision_date=day,
            decision_at=decision_at,
            symbol="AAA",
            sector_id=None,
            price_event_at=decision_at - timedelta(days=1),
            price_available_at=decision_at,
            median_volume_20d_shares=1_000_000,
            rule_score_bp=100,
            trade_restriction_status="officially_tradable",
            source_values_hash="sha256:" + ("a" * 64),
            ml_target_weight_bp=None,
        )
        bar = _Bar(
            symbol="AAA",
            event_date=day,
            available_at=decision_at,
            open_price=open_price,
            close_price=close_price,
            open_int=int(open_price),
            open_scale=0,
            close_int=int(close_price),
            close_scale=0,
            volume_shares=1_000_000,
            source_values_hash="sha256:" + ("b" * 64),
        )
        metrics, transition = _execute_day(
            state=accumulator.state,
            decision_day=day,
            session_index=session_index,
            candidates=(candidate,),
            bars={"AAA": bar},
            requested=requested,
            eligibility_fn=_research_no_sector_eligibility,
            enforce_sector_cap=False,
        )
        calculation = transition["calculation"]
        closing_minor = int(calculation["closing_value_minor"])
        cost_minor = int(calculation["transaction_cost_minor"])
        previous_net = (
            accumulator.previous_net_close_minor
            if accumulator.previous_net_close_minor is not None
            else _money_minor(INITIAL_CAPITAL)
        )
        previous_gross = (
            accumulator.previous_gross_close_minor
            if accumulator.previous_gross_close_minor is not None
            else _money_minor(INITIAL_CAPITAL)
        )
        accumulator.cumulative_cost_minor += cost_minor
        gross_close = closing_minor + accumulator.cumulative_cost_minor
        selected = _SelectedRow(
            position=session_index,
            year_ordinal=0,
            local_row_index=session_index,
            row_id=f"row:{day.isoformat()}:AAA",
            candidate=candidate,
            label_observed=True,
            label_return_bp=0,
        )
        daily = _lane_daily_metrics(
            requested=requested,
            execution_requested=requested,
            metrics=metrics,
            transition=transition,
            candidates=(candidate,),
            selected=(selected,),
            day_labels={session_index: 0},
            gross_return_bp=_close_to_close_return_bp(
                previous_close_minor=previous_gross,
                closing_minor=gross_close,
            ),
            net_return_bp=_close_to_close_return_bp(
                previous_close_minor=previous_net,
                closing_minor=closing_minor,
            ),
            helper_after_cost_return_bp=int(metrics["after_cost_return_bp"]),
            eligibility_fn=_research_no_sector_eligibility,
            net_closing_equity_minor=closing_minor,
            gross_closing_equity_cost_addback_estimate_minor=gross_close,
        )
        accumulator.previous_net_close_minor = closing_minor
        accumulator.previous_gross_close_minor = gross_close
        accumulator.net_equities_minor.append(closing_minor)
        accumulator.gross_equities_minor.append(gross_close)
        accumulator.net_returns_bp.append(daily["net_return_bp"])
        accumulator.gross_returns_bp.append(daily["gross_return_bp"])
        accumulator.daily.append(daily)
        _accumulate_lane(accumulator, daily)

    assert accumulator.net_equities_minor[1] > accumulator.net_equities_minor[0]
    assert accumulator.daily[1]["net_return_bp"] == _close_to_close_return_bp(
        previous_close_minor=accumulator.net_equities_minor[0],
        closing_minor=accumulator.net_equities_minor[1],
    )
    summary = _lane_summary(
        accumulator,
        decision_dates=(date(2026, 4, 2), date(2026, 4, 3)),
        candidate_count=2,
        strict_eligible_count=0,
        label_observed_count=2,
        universe_scope_hash="sha256:" + ("c" * 64),
    )
    assert summary["net_total_return_bp"] == _equity_total_return_bp(
        accumulator.net_equities_minor,
        _money_minor(INITIAL_CAPITAL),
    )
    assert summary["net_max_drawdown_bp"] == _maximum_drawdown_from_equities(
        accumulator.net_equities_minor,
        _money_minor(INITIAL_CAPITAL),
    )


def test_research_turnover_step_does_not_release_formal_weekly_cap() -> None:
    candidate = _fixture_candidate()
    state = _LaneState()
    requested = {candidate.symbol: 8_000, "CASH": 2_000}
    stepped = _research_turnover_capped_requested(
        state=state,
        decision_day=candidate.decision_date,
        requested=requested,
        bars={candidate.symbol: _fixture_bar()},
    )
    assert _turnover_bp({"CASH": 10_000}, stepped) <= 2_000
    assert sum(stepped.values()) == 2_000


def test_liquidity_pool_uses_only_t_minus_one_dollar_volume_with_symbol_ties() -> None:
    rows: list[_SelectedRow] = []
    specs = (
        ("ZZZ", 1_000, Decimal("10")),
        ("AAA", 2_000, Decimal("5")),
        ("CCC", 10, Decimal("1")),
        ("DDD", 900, Decimal("9")),
        ("EEE", 800, Decimal("8")),
        ("FFF", 700, Decimal("7")),
        ("GGG", 600, Decimal("6")),
        ("HHH", 500, Decimal("5")),
        ("III", 400, Decimal("4")),
        ("MISS", 9_999, Decimal("1")),
    )
    for position, (symbol, median, close) in enumerate(specs):
        candidate = _fixture_candidate()
        candidate = candidate.__class__(
            **{
                **candidate.__dict__,
                "symbol": symbol,
                "median_volume_20d_shares": median,
                "t_minus_one_close_price": close,
                "t_minus_one_close_available_at": candidate.decision_at
                - timedelta(days=1),
                "t_minus_one_close_source_values_hash": (
                    "sha256:" + (str(position) * 64)[:64]
                ),
            }
        )
        if symbol == "MISS":
            candidate = candidate.__class__(
                **{
                    **candidate.__dict__,
                    "t_minus_one_close_price": None,
                    "t_minus_one_close_available_at": None,
                    "t_minus_one_close_source_values_hash": None,
                }
            )
        rows.append(
            _SelectedRow(
                position=position,
                year_ordinal=0,
                local_row_index=position,
                row_id=f"row:{symbol}",
                candidate=candidate,
                label_observed=True,
                label_return_bp=0,
            )
        )
    selected, record = _select_liquidity_pool(tuple(rows))
    selected_symbols = [item.candidate.symbol for item in selected]
    assert selected_symbols[:2] == ["AAA", "ZZZ"]
    assert "MISS" not in selected_symbols
    assert len(selected_symbols) == 8
    assert record["policy_version"] == LIQUIDITY_POOL_POLICY_VERSION
    assert record["same_pool_for_all_lanes"] is True
    selected_ranks = {
        item["symbol"]: item["selection_rank"]
        for item in record["selected"]
    }
    assert selected_ranks["AAA"] == 1
    assert selected_ranks["ZZZ"] == 2
    missing = next(item for item in record["excluded"] if item["symbol"] == "MISS")
    assert "t_minus_one_close_missing_or_unavailable" in missing[
        "exclusion_reasons"
    ]


def test_lot_aware_global_budget_can_buy_when_each_naive_step_is_sub_lot() -> None:
    candidates: list[_Candidate] = []
    bars: dict[str, _Bar] = {}
    requested: dict[str, int] = {"CASH": 2_000}
    for index in range(8):
        symbol = f"S{index:02d}"
        candidate = _fixture_candidate()
        candidate = candidate.__class__(
            **{
                **candidate.__dict__,
                "symbol": symbol,
                "t_minus_one_close_price": Decimal("25"),
                "t_minus_one_close_available_at": candidate.decision_at
                - timedelta(days=1),
            }
        )
        candidates.append(candidate)
        bars[symbol] = _Bar(
            symbol=symbol,
            event_date=candidate.decision_date,
            available_at=candidate.decision_at,
            open_price=Decimal("25"),
            close_price=Decimal("25"),
            open_int=25,
            open_scale=0,
            close_int=25,
            close_scale=0,
            volume_shares=1_000_000,
            source_values_hash="sha256:" + ("b" * 64),
        )
        requested[symbol] = 1_000
    naive = _research_turnover_capped_requested(
        state=_LaneState(),
        decision_day=candidates[0].decision_date,
        requested=requested,
        bars=bars,
    )
    # Naive equal per-name stepping produces 250 bp; at TWD 25 and 1,000
    # shares, each name needs 500 bp for one complete lot.
    assert all(
        int(naive.get(symbol, 0)) < 500 for symbol in requested if symbol != "CASH"
    )
    execution, evidence = _research_lot_aware_requested(
        state=_LaneState(),
        decision_day=candidates[0].decision_date,
        requested=requested,
        bars=bars,
        candidates=candidates,
    )
    assert sum(value for key, value in execution.items() if key != "CASH") > 0
    assert _turnover_bp({"CASH": 10_000}, execution) <= 2_000
    assert evidence["all_execution_shares_lot_aligned"] is True
    assert any(
        int(item["execution_shares"]) >= 1_000
        for item in evidence["symbols"]
    )
    assert evidence["policy_version"] == LOT_EXECUTION_POLICY_VERSION


def test_participation_cap_limits_new_buy_lots_without_selling_existing_holding() -> None:
    candidate = _fixture_candidate()
    candidate = candidate.__class__(
        **{
            **candidate.__dict__,
            "median_volume_20d_shares": 20_000,
        }
    )
    bar = _fixture_bar()
    state = _LaneState(cash=Decimal("480000.00"), shares={"AAA": 2_000})
    execution, evidence = _research_lot_aware_requested(
        state=state,
        decision_day=candidate.decision_date,
        requested={"AAA": 8_000, "CASH": 2_000},
        bars={"AAA": bar},
        candidates=(candidate,),
    )
    aaa = next(item for item in evidence["symbols"] if item["symbol"] == "AAA")
    assert aaa["volume_cap_shares"] == 1_000
    assert aaa["execution_shares"] >= 2_000
    assert aaa["execution_shares"] <= 3_000
    assert execution["AAA"] > 0

    sell_execution, sell_evidence = _research_lot_aware_requested(
        state=state,
        decision_day=candidate.decision_date,
        requested={"CASH": 10_000},
        bars={"AAA": bar},
        candidates=(candidate,),
    )
    sell_aaa = next(
        item for item in sell_evidence["symbols"] if item["symbol"] == "AAA"
    )
    assert sell_aaa["execution_shares"] == 1_000
    assert sell_execution["AAA"] > 0


def test_comparison_preflight_blocks_missing_replay_source_sidecar(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    request = AllocationBaseExpertComparisonRequest(
        parent_training_manifest_path=bounded_e2e.ridge_manifest_path,
        output_root=tmp_path / "missing-source-comparison",
        safety_reserve_bytes=1,
        acquire_heavy_lock=False,
    )
    with pytest.raises(ValueError, match="replay_source.sqlite missing"):
        preflight_allocation_base_expert_comparison(request)


def test_fixture_comparison_has_two_explicit_scenarios_and_is_idempotent(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    _install_fixture_replay_sources(bounded_e2e.store_manifest_path)
    request = AllocationBaseExpertComparisonRequest(
        parent_training_manifest_path=bounded_e2e.ridge_manifest_path,
        output_root=tmp_path / "base-comparison",
        batch_size=31,
        memory_budget_mb=1_024,
        safety_reserve_bytes=1,
        acquire_heavy_lock=False,
    )
    preflight = preflight_allocation_base_expert_comparison(request)
    assert preflight["status"] == "preflight_passed"
    assert preflight["selected_oof_row_count"] > 0
    assert preflight["selected_oof_artifact_count"] == 3
    assert preflight["formal_oos_allowed"] is False

    publication = build_allocation_base_expert_comparison(request)
    payload = _read_json(publication.comparison_path)
    assert payload["schema_version"] == COMPARISON_SCHEMA_VERSION
    assert payload["status"] == "complete_research"
    assert payload["selected_oof_row_count"] == preflight[
        "selected_oof_row_count"
    ]
    assert payload["meta_targets_read"] is False
    assert payload["teacher_targets_read"] is False
    assert payload["final_meta_used"] is False
    assert payload["formal_oos_allowed"] is False
    assert payload["research_only"] is True
    assert payload["execution_contract"]["transaction_costs_included"] is True
    assert len(payload["lanes"]) == 12
    assert {item["scenario"] for item in payload["lanes"]} == {
        "strict_sector",
        "research_no_sector_cap",
    }
    assert all(
        "same realized holdings" in item["performance_semantics"]
        for item in payload["lanes"]
    )
    assert all(
        item["universe_scope_hash"] == payload["universe"]["scope_hash"]
        for item in payload["lanes"]
    )
    assert payload["daily"]
    first_daily_lane = next(iter(payload["daily"][0]["lanes"].values()))
    assert isinstance(first_daily_lane["net_closing_equity_minor"], int)
    assert isinstance(
        first_daily_lane[
            "gross_closing_equity_cost_addback_estimate_minor"
        ],
        int,
    )
    first_pool = payload["daily"][0]["liquidity_pool"]
    assert first_pool["policy_version"] == LIQUIDITY_POOL_POLICY_VERSION
    assert first_pool["selected_count"] <= 8
    pool_symbols = tuple(item["symbol"] for item in first_pool["selected"])
    assert pool_symbols
    assert all(
        tuple(item["investment_pool_symbols"])
        == tuple(
            entry["symbol"] for entry in day["liquidity_pool"]["selected"]
        )
        for day in payload["daily"]
        for item in day["lanes"].values()
    )
    equal_lane = next(
        item
        for item in payload["lanes"]
        if item["lane_id"] == "research_no_sector_cap__equal_weight_t_minus_one_liquidity_pool"
    )
    assert equal_lane["execution_status"] == "executed_with_replay_constraints"
    assert equal_lane["executed_trade_count"] > 0
    assert all(
        lane_daily["complete_lot_execution"]["all_execution_shares_lot_aligned"]
        for day_record in payload["daily"]
        for lane_id, lane_daily in day_record["lanes"].items()
        if lane_id.endswith("equal_weight_t_minus_one_liquidity_pool")
        and lane_daily["complete_lot_execution"] is not None
    )

    replay = build_allocation_base_expert_comparison(request)
    assert replay.idempotent is True
    assert replay.comparison_hash == publication.comparison_hash


def test_fixture_comparison_rejects_partial_feature_pack_scope(
    bounded_e2e,
    tmp_path: Path,
) -> None:
    store = _read_json(bounded_e2e.store_manifest_path)
    pack_ids = [str(item["pack_id"]) for item in store["feature_packs"]]
    assert len(pack_ids) >= 2
    request = AllocationBaseExpertComparisonRequest(
        parent_training_manifest_path=bounded_e2e.ridge_manifest_path,
        output_root=tmp_path / "partial-comparison",
        pack_ids=(pack_ids[0],),
        safety_reserve_bytes=1,
        acquire_heavy_lock=False,
    )
    with pytest.raises(ValueError, match="complete selected feature-pack scope"):
        preflight_allocation_base_expert_comparison(request)
