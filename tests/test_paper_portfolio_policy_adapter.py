import sqlite3
from datetime import date

import pytest

from app_module.paper_portfolio_policy import PaperPortfolioAction
from app_module.paper_portfolio_policy_adapter import (
    PaperPolicyCandidate,
    PaperPortfolioPolicyAdapter,
    PaperPortfolioPolicyContext,
)


def _create_ledger(path, rows):
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE paper_trade_ledger (
            fill_id TEXT PRIMARY KEY,
            portfolio_id TEXT NOT NULL,
            event_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            requested_quantity INTEGER NOT NULL,
            filled_quantity INTEGER NOT NULL,
            turnover_bp INTEGER,
            status TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO paper_trade_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()


def _context(
    *,
    decision_date=date(2026, 9, 9),
    days=tuple(date(2026, 9, day) for day in range(1, 10)),
    weights=None,
    sectors=None,
    current_cash_bp=6000,
    history_start=date(2026, 9, 1),
    coverage_start=date(2026, 9, 1),
    coverage_end=date(2026, 9, 30),
):
    current_weights = weights or {"AAA": 1000, "BBB": 1000}
    sector_by_symbol = sectors or {
        "AAA": "technology",
        "BBB": "finance",
        "CCC": "technology",
    }
    return PaperPortfolioPolicyContext(
        decision_date=decision_date,
        current_cash_bp=current_cash_bp,
        current_weights_bp=current_weights,
        sector_by_symbol=sector_by_symbol,
        official_trading_days=days,
        ledger_history_start=history_start,
        official_calendar_coverage_start=coverage_start,
        official_calendar_coverage_end=coverage_end,
        official_calendar_source_hash="sha256:calendar-source",
        official_calendar_complete=True,
        snapshot_id=f"paper-main-{decision_date.isoformat()}",
    )


def _fill(fill_id, event_date, symbol, turnover, status="filled", filled=1000, requested=1000):
    return (fill_id, "paper-main", event_date, symbol, requested, filled, turnover, status)


def test_inspect_derives_week_turnover_cooldown_and_sector_from_ledger(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(
        ledger,
        [
            _fill("f-aaa", "2026-09-07", "AAA", 1500),
            _fill("f-bbb", "2026-09-08", "BBB", 500, "partially_filled", filled=500),
            _fill("f-rejected", "2026-09-08", "CCC", None, "rejected", filled=0),
        ],
    )

    result = PaperPortfolioPolicyAdapter(ledger).inspect(_context())

    assert result.status == "ready"
    assert result.blockers == ()
    assert result.state is not None
    assert result.state.weekly_turnover_used_bp == 2000
    assert result.state.last_trade_date_by_symbol == {
        "AAA": date(2026, 9, 7),
        "BBB": date(2026, 9, 8),
    }
    assert result.state.trading_days_since_last_trade_by_symbol == {"AAA": 1, "BBB": 0}
    assert result.state.sector_weights_bp == {"technology": 1000, "finance": 1000}
    assert result.state.ledger_rows_sha256.startswith("sha256:")
    assert result.state.ledger_data_version >= 1


def test_future_row_is_excluded_before_value_validation_and_cannot_change_past_state(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(
        ledger,
        [
            _fill("future", "2026-09-09", "AAA", None, "malformed_future_status", filled=999, requested=0),
        ],
    )
    context = _context(
        decision_date=date(2026, 9, 8),
        days=tuple(date(2026, 9, day) for day in (1, 7, 8)),
        coverage_end=date(2026, 9, 8),
    )

    result = PaperPortfolioPolicyAdapter(ledger).inspect(context)

    assert result.status == "ready"
    assert result.state is not None
    assert result.state.weekly_turnover_used_bp == 0
    assert result.state.future_rows_excluded == 1


def test_weekly_turnover_from_real_fills_blocks_candidate_above_cap(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(
        ledger,
        [
            _fill("f-1", "2026-09-08", "AAA", 1500),
            _fill("f-2", "2026-09-08", "BBB", 1000, "partially_filled", filled=500),
        ],
    )

    result = PaperPortfolioPolicyAdapter(ledger).evaluate(
        _context(),
        PaperPolicyCandidate(stock_code="CCC", target_weight_bp=1000),
    )

    assert result.status == "ready"
    assert result.decision is not None
    assert result.decision.action is PaperPortfolioAction.NO_PAPER_TRADE
    assert result.decision.reasons == ("weekly_turnover_cap_exceeded",)
    assert result.state is not None
    assert result.state.weekly_turnover_used_bp == 2500


def test_batch_reserves_turnover_between_candidates(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(ledger, [])
    context = _context(
        weights={"AAA": 0, "BBB": 0},
        sectors={"AAA": "technology", "BBB": "finance"},
    )

    result = PaperPortfolioPolicyAdapter(ledger).evaluate_batch(
        context,
        (
            PaperPolicyCandidate(stock_code="AAA", target_weight_bp=1000),
            PaperPolicyCandidate(stock_code="BBB", target_weight_bp=1500),
        ),
    )

    assert result.status == "ready"
    assert len(result.results) == 2
    assert result.results[0].decision is not None
    assert result.results[0].decision.action is PaperPortfolioAction.PAPER_TRADE_CANDIDATE
    assert result.results[0].reservation_weekly_turnover_used_bp == 0
    assert result.results[1].decision is not None
    assert result.results[1].decision.action is PaperPortfolioAction.NO_PAPER_TRADE
    assert result.results[1].decision.reasons == ("weekly_turnover_cap_exceeded",)
    assert result.results[1].reservation_weekly_turnover_used_bp == 1000


def test_batch_sector_reservation_is_evaluated_independently_of_turnover(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(ledger, [])
    context = _context(
        weights={"AAA": 0, "BBB": 0, "CCC": 1500},
        sectors={"AAA": "technology", "BBB": "technology", "CCC": "technology"},
    )

    from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig

    result = PaperPortfolioPolicyAdapter(
        ledger,
        PaperPortfolioPolicyConfig(weekly_turnover_cap_bp=10_000),
    ).evaluate_batch(
        context,
        (
            PaperPolicyCandidate(stock_code="AAA", target_weight_bp=1500),
            PaperPolicyCandidate(stock_code="BBB", target_weight_bp=1000),
        ),
    )

    assert result.status == "ready"
    assert result.results[0].decision is not None
    assert result.results[0].decision.action is PaperPortfolioAction.PAPER_TRADE_CANDIDATE
    assert result.results[1].decision is not None
    assert result.results[1].decision.action is PaperPortfolioAction.NO_PAPER_TRADE
    assert result.results[1].decision.reasons == ("sector_cap_exceeded",)
    assert result.results[1].projected_sector_weight_after_bp == 4000


def test_batch_does_not_release_unfilled_sell_proceeds_to_next_buy(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(ledger, [])
    context = _context(
        current_cash_bp=2500,
        weights={"AAA": 1000, "BBB": 0},
        sectors={"AAA": "technology", "BBB": "finance"},
    )

    result = PaperPortfolioPolicyAdapter(ledger).evaluate_batch(
        context,
        (
            PaperPolicyCandidate(stock_code="AAA", target_weight_bp=0),
            PaperPolicyCandidate(stock_code="BBB", target_weight_bp=1000),
        ),
    )

    assert result.cash_reservation_semantics == "sell_proceeds_not_released_until_actual_fill"
    assert (
        result.sector_reservation_semantics
        == "sell_exposure_not_released_until_actual_fill_readback"
    )
    assert result.results[0].decision is not None
    assert result.results[0].decision.action is PaperPortfolioAction.PAPER_TRADE_CANDIDATE
    assert result.results[1].decision is not None
    assert result.results[1].decision.action is PaperPortfolioAction.NO_PAPER_TRADE
    assert result.results[1].decision.reasons == (
        "minimum_cash_reserve_after_batch_reservation",
    )


def test_batch_rejects_duplicate_symbol_reservation(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(ledger, [])
    context = _context(weights={"AAA": 0}, sectors={"AAA": "technology"})

    result = PaperPortfolioPolicyAdapter(ledger).evaluate_batch(
        context,
        (
            PaperPolicyCandidate(stock_code="AAA", target_weight_bp=1000),
            PaperPolicyCandidate(stock_code="AAA", target_weight_bp=1200),
        ),
    )

    assert result.status == "blocked"
    assert result.blockers == ("duplicate_candidate_symbol",)
    assert result.results[1].decision is None


def test_wal_readback_uses_canonical_rows_visible_in_one_read_transaction(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(ledger, [])
    writer = sqlite3.connect(ledger)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "INSERT INTO paper_trade_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            _fill("wal-fill", "2026-09-08", "AAA", 700),
        )
        writer.commit()
        result = PaperPortfolioPolicyAdapter(ledger).inspect(_context())
    finally:
        writer.close()

    assert result.status == "ready"
    assert result.state is not None
    assert result.state.weekly_turnover_used_bp == 700
    assert result.state.ledger_rows_sha256.startswith("sha256:")
    assert result.state.ledger_data_version >= 1


def test_missing_sector_is_unknown_and_missing_ledger_is_unknown(tmp_path) -> None:
    missing_sector_context = _context(sectors={"AAA": "technology"})
    missing_sector = PaperPortfolioPolicyAdapter(tmp_path / "ledger.sqlite").inspect(
        missing_sector_context
    )
    assert missing_sector.status == "unknown"
    assert missing_sector.blockers == ("sector_mapping_missing:BBB",)

    complete_context = _context()
    missing_ledger = PaperPortfolioPolicyAdapter(tmp_path / "ledger.sqlite").inspect(
        complete_context
    )
    assert missing_ledger.status == "unknown"
    assert missing_ledger.blockers == ("ledger_source_missing",)


def test_calendar_must_be_official_complete_and_cover_decision(tmp_path) -> None:
    with pytest.raises(ValueError, match="official_calendar_complete"):
        PaperPortfolioPolicyContext(
            decision_date=date(2026, 9, 9),
            current_cash_bp=6000,
            current_weights_bp={"AAA": 1000},
            sector_by_symbol={"AAA": "technology"},
            official_trading_days=(date(2026, 9, 9),),
            ledger_history_start=date(2026, 9, 1),
            official_calendar_coverage_start=date(2026, 9, 1),
            official_calendar_coverage_end=date(2026, 9, 9),
            official_calendar_source_hash="sha256:calendar-source",
            official_calendar_complete=False,
        )

    context = _context(days=(date(2026, 9, 8),), coverage_end=date(2026, 9, 9))
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(ledger, [])
    result = PaperPortfolioPolicyAdapter(ledger).inspect(context)
    assert result.status == "unknown"
    assert result.blockers == ("official_calendar_missing_or_not_trading_day",)


def test_missing_turnover_on_historical_fill_is_blocked(tmp_path) -> None:
    ledger = tmp_path / "paper_trade_ledger.sqlite"
    _create_ledger(ledger, [_fill("f-missing", "2026-09-08", "AAA", None)])

    result = PaperPortfolioPolicyAdapter(ledger).inspect(_context())

    assert result.status == "blocked"
    assert result.blockers == ("executed ledger row missing integer turnover:f-missing",)
