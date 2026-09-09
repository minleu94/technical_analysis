from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig
from data_module.portfolio_ml_dataset_assembler import (
    SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
    SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
)
from data_module.paper_daily_execution_producer import (
    PaperExecutionPaths,
    _Position,
    _State,
    _append_and_read_back,
    _apply_prior_paper_fills,
    _build_fills,
    resolve_pending_recommendation,
    run_paper_execution_daily_from_queue,
    run_paper_execution_daily,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.official_trading_calendar_cache import (
    build_twse_calendar_cache,
    write_twse_calendar_cache,
)
from app_module.paper_trade_ledger import PaperTradeLedgerRepository


TAIPEI = ZoneInfo("Asia/Taipei")
DECISION_DATE = "2026-09-04"
EXECUTION_DATE = "2026-09-07"
NOW = datetime(2026, 9, 7, 10, 0, tzinfo=TAIPEI)
EOD_REPLAY_NOW = datetime(2026, 9, 7, 15, 0, tzinfo=TAIPEI)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sector_sidecar(path: Path) -> str:
    rows = [
        {
            "symbol": "2330",
            "sector_id": "SEMICONDUCTOR",
            "available_at": "2026-01-01T00:00:00+00:00",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "status": "accepted",
            "source_id": "official:twse:t187ap03_L",
            "license_id": "twse-open-data-license-v1",
            "source_hash": "sha256:" + ("1" * 64),
        }
    ]
    canonical = lambda value: json.dumps(  # noqa: E731 - fixture canonicalizer
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    rows_hash = "sha256:" + hashlib.sha256(canonical(rows)).hexdigest()
    manifest_body = {
        "schema_version": SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION,
        "row_count": len(rows),
        "rows_hash": rows_hash,
    }
    manifest = {
        **manifest_body,
        "canonical_hash": "sha256:" + hashlib.sha256(
            canonical(
                {
                    "sidecar_schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
                    "manifest": manifest_body,
                }
            )
        ).hexdigest(),
    }
    payload = {
        "schema_version": SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION,
        "manifest": manifest,
        "rows": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(payload) + b"\n")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class _Calendar:
    def __init__(self, open_dates: set[str]) -> None:
        self.open_dates = open_dates

    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool, str]:
        del allow_online_probe
        key = target_date.isoformat()
        return (
            key in self.open_dates,
            "test_official_schedule_open" if key in self.open_dates else "test_closed",
        )


class _UnknownCalendar:
    def is_official_trading_day(
        self,
        _target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[None, str]:
        del allow_online_probe
        return None, "twse_holiday_schedule_unavailable"


def _recommendation(
    path: Path,
    *,
    created_at: str = "2026-09-04T20:00:00+08:00",
    decision_date: str = DECISION_DATE,
    price: str = "10.00",
) -> None:
    path.write_text(
        json.dumps(
            {
                "result_id": "scheduled_rec_20260904_200000",
                "created_at": created_at,
                "config": {
                    "research_only": True,
                    "decision_date": decision_date,
                    "top_n": 8,
                    "profile_id": "scheduled_daily_research_default_v1",
                    "safety_boundary": {
                        "confirm": False,
                        "writes_evidence_db": False,
                        "auto_trading": False,
                        "lifecycle_action": False,
                    },
                },
                "recommendations": [
                    {
                        "證券代號": "2330",
                        "證券名稱": "測試公司",
                        "總分": "100.00",
                        "收盤價": price,
                        "產業": "半導體",
                        "eligible_universe_date": decision_date,
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _state(
    path: Path,
    *,
    decision_date: str = DECISION_DATE,
    quantity: int = 0,
) -> None:
    repository = PaperPortfolioSnapshotRepository(path)
    repository.append(
        PaperPortfolioSnapshot(
            snapshot_id=f"snapshot-{decision_date.replace('-', '')}",
            portfolio_id="paper-main",
            decision_date=decision_date,
            source_result_id="scheduled_rec_prior",
            cash=Decimal("100000.00"),
            total_value=Decimal("100000.00"),
            positions=(
                PaperPortfolioPositionSnapshot(
                    stock_code="2330",
                    quantity=quantity,
                    mark_price=Decimal("10.00"),
                    market_value=(
                        Decimal("0.00")
                        if quantity == 0
                        else Decimal("10.00") * quantity
                    ),
                    weight_bp=0,
                ),
            ),
        )
    )


def _market(
    path: Path,
    *,
    recommendation_close: str = "10.00",
    execution_open: str = "10.20",
    execution_close: str = "10.50",
    recommendation_volume: int = 90000,
    execution_volume: int | None = 100000,
    with_calendar: bool = False,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE daily_prices ("
            "日期 TEXT, 證券代號 TEXT, 證券名稱 TEXT, "
            "開盤價 TEXT, 收盤價 TEXT, 成交股數 INTEGER)"
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?)",
            (
                (
                    "20260904",
                    "2330",
                    "測試公司",
                    "9.80",
                    recommendation_close,
                    recommendation_volume,
                ),
                (
                    "20260907",
                    "2330",
                    "測試公司",
                    execution_open,
                    execution_close,
                    execution_volume,
                ),
            ),
        )
        if with_calendar:
            connection.execute("CREATE TABLE market_indices (日期 TEXT, 指數名稱 TEXT)")
            connection.execute(
                "INSERT INTO market_indices VALUES (?, ?)",
                ("20260904", "TAIEX"),
            )
            connection.execute(
                "INSERT INTO market_indices VALUES (?, ?)",
                ("20260907", "TAIEX"),
            )


def _paths(
    tmp_path: Path,
    *,
    with_calendar: bool = False,
    recommendation_close: str = "10.00",
    execution_open: str = "10.20",
    execution_close: str = "10.50",
    recommendation_volume: int = 90000,
    execution_volume: int | None = 100000,
) -> PaperExecutionPaths:
    recommendation = tmp_path / "recommendation.json"
    _recommendation(recommendation, price=recommendation_close)
    state = tmp_path / "state.sqlite"
    _state(state)
    market = tmp_path / "market.sqlite"
    _market(
        market,
        recommendation_close=recommendation_close,
        execution_open=execution_open,
        execution_close=execution_close,
        recommendation_volume=recommendation_volume,
        execution_volume=execution_volume,
        with_calendar=with_calendar,
    )
    ledger = tmp_path / "paper-ledger.sqlite"
    PaperTradeLedgerRepository(ledger)
    sector_path = tmp_path / "sector-membership.json"
    sector_hash = _write_sector_sidecar(sector_path)
    return PaperExecutionPaths(
        recommendation_json=recommendation,
        state_db=state,
        market_db=market,
        output_root=tmp_path / "candidate",
        ledger_db=ledger,
        sector_membership_path=sector_path,
        sector_membership_file_hash=sector_hash,
    )


def _open_calendar() -> _Calendar:
    return _Calendar({DECISION_DATE, EXECUTION_DATE})


def test_t1_next_session_uses_official_open_and_prior_close_binding(
    tmp_path: Path,
) -> None:
    result = run_paper_execution_daily(
        _paths(tmp_path),
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )

    assert result["status"] == "machine_verified_candidate"
    assert result["decision_date"] == DECISION_DATE
    assert result["execution_date"] == EXECUTION_DATE
    assert result["execution_contract"] == "t_plus_one_next_official_session_open"
    assert result["snapshot_semantics"] == "preopen_t_minus_one_mark_to_market"
    assert result["fill_count"] == 1
    fill = result["fills"][0]
    assert fill["event_date"] == EXECUTION_DATE
    assert fill["reference_price"] == "10.20"
    assert fill["fill_price"] == "10.25"
    assert result["recommendation"]["decision_date"] == DECISION_DATE
    assert result["market_source"]["execution_price_field"] == "開盤價"
    assert result["market_source"]["recommendation_reference_price_field"] == "收盤價"
    assert result["market_source"]["liquidity_volume_date"] == DECISION_DATE
    assert result["market_source"]["execution_data_availability"] == (
        "delayed_eod_replay_after_session_close"
    )
    assert result["market_source"]["realtime_execution_allowed"] is False
    assert result["cash_settlement_semantics"] == (
        "gross_amount_plus_commission_plus_tax_v1"
    )
    assert result["cost_attribution_semantics"] == (
        "commission_plus_tax_plus_slippage_attribution_v1"
    )
    assert result["fills"][0]["source_type"] == (
        "paper_daily_execution_delayed_eod_replay_v1"
    )


def test_recommendation_from_prior_natural_day_is_allowed_for_t1(
    tmp_path: Path,
) -> None:
    result = run_paper_execution_daily(
        _paths(tmp_path),
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )
    assert result["status"] == "machine_verified_candidate"


def test_sunday_decision_binds_previous_official_reference_session(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _recommendation(
        paths.recommendation_json,
        created_at="2026-09-06T20:00:00+08:00",
        decision_date="2026-09-06",
    )
    result = run_paper_execution_daily(
        paths,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )

    assert result["status"] == "machine_verified_candidate"
    assert result["decision_date"] == "2026-09-06"
    assert result["execution_date"] == EXECUTION_DATE
    assert result["market_reference_date"] == DECISION_DATE
    market_source = result["market_source"]
    assert isinstance(market_source, dict)
    assert market_source["decision_date"] == "2026-09-06"
    assert market_source["recommendation_reference_date"] == DECISION_DATE
    assert market_source["execution_date"] == EXECUTION_DATE
    assert market_source["recommendation_reference_date_basis"] == (
        "latest_proven_official_session_on_or_before_decision_date"
    )


def test_before_next_session_open_waits_without_reading_market_or_state(
    tmp_path: Path,
) -> None:
    result = run_paper_execution_daily(
        _paths(tmp_path),
        now=datetime(2026, 9, 7, 8, 59, tzinfo=TAIPEI),
        calendar=_open_calendar(),
    )

    assert result["status"] == "waiting_for_execution_session"
    assert result["execution_date"] == EXECUTION_DATE
    assert "fill_count" not in result


def test_before_delayed_eod_source_waits_without_reading_market_or_state(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    early_paths = PaperExecutionPaths(
        recommendation_json=paths.recommendation_json,
        state_db=tmp_path / "state-not-read.sqlite",
        market_db=tmp_path / "market-not-read.sqlite",
        output_root=tmp_path / "early-candidate",
    )
    result = run_paper_execution_daily(
        early_paths,
        now=NOW,
        calendar=_open_calendar(),
    )

    assert result["status"] == "waiting_for_execution_source"
    assert result["execution_date"] == EXECUTION_DATE
    assert result["execution_source_available_after"] == (
        "2026-09-07T15:00:00+08:00"
    )
    assert "fill_count" not in result
    assert not early_paths.state_db.exists()
    assert not early_paths.market_db.exists()


def test_late_next_session_is_not_historically_backfilled(tmp_path: Path) -> None:
    result = run_paper_execution_daily(
        _paths(tmp_path),
        now=datetime(2026, 9, 8, 10, 0, tzinfo=TAIPEI),
        calendar=_open_calendar(),
    )

    assert result["status"] == "blocked"
    assert any("session was missed" in item for item in result["blockers"])


def test_preopen_snapshot_is_reused_as_t1_state_without_overwrite(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _state(paths.state_db, decision_date=EXECUTION_DATE)
    state_before = _sha256(paths.state_db)
    result = run_paper_execution_daily(
        paths,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )

    assert result["status"] == "machine_verified_candidate"
    assert result["state_source"]["execution_snapshot_exists"] is True
    assert result["state_source"]["snapshot_transition_policy"] == (
        "preopen_snapshot_reused_append_only_postfill_transition"
    )
    assert result["ledger"]["appended"] is False
    assert _sha256(paths.state_db) == state_before


def test_existing_preopen_snapshot_can_append_after_candidate_and_retry_once(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _state(paths.state_db, decision_date=EXECUTION_DATE)
    ledger = paths.ledger_db
    assert ledger is not None
    state_before = _sha256(paths.state_db)

    candidate = run_paper_execution_daily(
        PaperExecutionPaths(**{**paths.__dict__, "output_root": tmp_path / "candidate"}),
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=False,
    )
    assert candidate["status"] == "machine_verified_candidate"
    assert candidate["ledger"]["appended"] is False
    assert _sha256(paths.state_db) == state_before
    assert PaperTradeLedgerRepository(ledger).list() == ()

    appended = run_paper_execution_daily(
        PaperExecutionPaths(**{**paths.__dict__, "output_root": tmp_path / "appended"}),
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert appended["status"] == "machine_verified_candidate"
    assert appended["ledger"]["appended"] is True
    assert appended["state_source"]["execution_snapshot_exists"] is True
    assert _sha256(paths.state_db) == state_before
    with sqlite3.connect(f"file:{ledger.resolve().as_posix()}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_trade_ledger").fetchone()[0] == 1


def test_explicit_append_is_exactly_idempotent_after_preopen_snapshot_exists(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    ledger = paths.ledger_db
    assert ledger is not None
    first = run_paper_execution_daily(
        paths,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert first["status"] == "machine_verified_candidate"
    assert first["ledger"]["appended"] is True
    assert first["ledger"]["idempotent_replay"] is False

    _state(paths.state_db, decision_date=EXECUTION_DATE)
    retry_paths = PaperExecutionPaths(
        recommendation_json=paths.recommendation_json,
        state_db=paths.state_db,
        market_db=paths.market_db,
        output_root=tmp_path / "retry-candidate",
        ledger_db=ledger,
        sector_membership_path=paths.sector_membership_path,
        sector_membership_file_hash=paths.sector_membership_file_hash,
    )
    second = run_paper_execution_daily(
        retry_paths,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert second["status"] == "machine_verified_candidate"
    assert second["ledger"]["appended"] is True
    assert second["ledger"]["idempotent_replay"] is True
    with sqlite3.connect(f"file:{ledger.resolve().as_posix()}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_trade_ledger").fetchone()[0] == 1


def test_missing_append_confirmation_does_not_create_ledger(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = run_paper_execution_daily(
        paths,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )

    assert result["status"] == "machine_verified_candidate"
    assert result["append_requested"] is False
    assert result["ledger"]["appended"] is False
    assert paths.ledger_db is not None
    assert PaperTradeLedgerRepository(paths.ledger_db).list() == ()


def test_zero_liquidity_cap_is_order_level_rejection(
    tmp_path: Path,
) -> None:
    result = run_paper_execution_daily(
        _paths(tmp_path, recommendation_volume=1000, execution_volume=999999),
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )

    assert result["status"] == "machine_verified_candidate"
    assert result["fill_count"] == 1
    fill = result["fills"][0]
    assert isinstance(fill, dict)
    assert fill["status"] == "rejected"
    assert fill["requested_quantity"] == 1000
    assert fill["filled_quantity"] == 0
    assert fill["remaining_quantity"] == 1000
    assert fill["execution_reason"] == "liquidity_cap_zero"
    projection = result["post_execution_projection"]
    assert isinstance(projection, dict)
    assert projection["positions"] == []


def test_partial_liquidity_continues_other_orders_and_carries_remaining_on_retry(
    tmp_path: Path,
) -> None:
    """低流動性只影響單筆委託，append/retry 與下一日 projection 均守恆。"""

    state = _State(
        snapshot_id="snapshot-partial",
        portfolio_id="paper-main",
        decision_date=date(2026, 9, 4),
        source_result_id="partial-test",
        cash=Decimal("70000.00"),
        total_value=Decimal("100000.00"),
        positions=(
            _Position(
                stock_code="2330",
                quantity=3000,
                mark_price=Decimal("10.00"),
                market_value=Decimal("30000.00"),
            ),
        ),
        content_hash="sha256:" + "1" * 64,
        file_hash="sha256:" + "2" * 64,
    )
    fills, projection = _build_fills(
        state=state,
        target={"2317": 3000, "2330": 0},
        prices={"2317": Decimal("10.00"), "2330": Decimal("10.00")},
        # 2330 的 5% 只有 1,500 股，向下取整後只能成交一張；
        # 2317 仍有足夠流動性，應繼續完成三張買入。
        volumes={"2317": 100000, "2330": 30000},
        execution_date=date(2026, 9, 7),
        policy=PaperPortfolioPolicyConfig(),
        recommendation_hash="sha256:" + "3" * 64,
    )

    assert [(fill.stock_code, fill.side, fill.status) for fill in fills] == [
        ("2330", "sell", "partially_filled"),
        ("2317", "buy", "filled"),
    ]
    outcomes = projection["order_outcomes"]
    assert isinstance(outcomes, list)
    assert outcomes[0]["requested_quantity"] == 3000
    assert outcomes[0]["filled_quantity"] == 1000
    assert outcomes[0]["remaining_quantity"] == 2000
    assert outcomes[0]["reason"] == "liquidity_cap_partial"
    assert outcomes[1]["requested_quantity"] == 3000
    assert outcomes[1]["filled_quantity"] == 3000
    assert outcomes[1]["remaining_quantity"] == 0

    # 獨立按每筆 fill 的結算費用重算，slippage_cost 只存在於 total_cost
    # 歸因，不可再從 gross 重扣。
    expected_cash = state.cash
    for fill in fills:
        if fill.side == "sell":
            expected_cash += fill.gross_amount - fill.cash_settlement_cost
        else:
            expected_cash -= fill.gross_amount + fill.cash_settlement_cost
    expected_cash = expected_cash.quantize(Decimal("0.01"))
    # 70000 + (9950 - 20 - 29.85) - (30150 + 45.23) = 49704.92。
    # 這個固定常數獨立於 property，避免 cash settlement property 本身錯誤時
    # 測試仍用同一錯誤公式得到綠燈。
    assert expected_cash == Decimal("49704.92")
    assert Decimal(str(projection["cash_after"])) == Decimal("49704.92")
    assert any(fill.total_cost > fill.cash_settlement_cost for fill in fills)
    positions = projection["positions"]
    assert isinstance(positions, list)
    assert {(item["stock_code"], item["quantity"]) for item in positions} == {
        ("2317", 3000),
        ("2330", 2000),
    }

    ledger = tmp_path / "partial-ledger.sqlite"
    assert _append_and_read_back(ledger, fills) is False
    assert _append_and_read_back(ledger, fills) is True
    assert len(PaperTradeLedgerRepository(ledger).list()) == 2

    projected_cash, _, projected_positions, event_ids, _ = _apply_prior_paper_fills(
        ledger,
        portfolio_id=state.portfolio_id,
        after_date=date(2026, 9, 7),
        before_date=date(2026, 9, 8),
        initial_cash=state.cash,
        initial_total=state.total_value,
        initial_positions=state.positions,
    )
    assert projected_cash == expected_cash
    assert event_ids == tuple(sorted(fill.fill_id for fill in fills))
    assert {item.stock_code: item.quantity for item in projected_positions} == {
        "2317": 3000,
        "2330": 2000,
    }


def test_low_cash_does_not_block_multiple_legal_sell_orders() -> None:
    """保留現金只限制買入，賣出可先增加現金再供後續委託使用。"""

    state = _State(
        snapshot_id="snapshot-low-cash",
        portfolio_id="paper-main",
        decision_date=date(2026, 9, 4),
        source_result_id="low-cash-test",
        cash=Decimal("1.00"),
        total_value=Decimal("20001.00"),
        positions=(
            _Position("2317", 1000, Decimal("10.00"), Decimal("10000.00")),
            _Position("2330", 1000, Decimal("10.00"), Decimal("10000.00")),
        ),
        content_hash="sha256:" + "4" * 64,
        file_hash="sha256:" + "5" * 64,
    )
    fills, projection = _build_fills(
        state=state,
        target={"2317": 0, "2330": 0},
        prices={"2317": Decimal("10.00"), "2330": Decimal("10.00")},
        volumes={"2317": 100000, "2330": 100000},
        execution_date=date(2026, 9, 7),
        policy=PaperPortfolioPolicyConfig(),
        recommendation_hash="sha256:" + "6" * 64,
    )

    assert len(fills) == 2
    assert all(fill.status == "filled" for fill in fills)
    assert all(fill.filled_quantity == 1000 for fill in fills)
    assert Decimal(str(projection["cash_after"])) > Decimal("1.00")


def test_execution_day_eod_volume_cannot_change_frozen_open_fill_or_cap(
    tmp_path: Path,
) -> None:
    normal_root = tmp_path / "normal"
    changed_root = tmp_path / "changed"
    normal_root.mkdir()
    changed_root.mkdir()
    normal = run_paper_execution_daily(
        _paths(
            normal_root,
            recommendation_volume=90000,
            execution_volume=100000,
        ),
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )
    changed = run_paper_execution_daily(
        _paths(
            changed_root,
            recommendation_volume=90000,
            execution_volume=1,
        ),
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )

    assert normal["status"] == "machine_verified_candidate"
    assert changed["status"] == "machine_verified_candidate"
    normal_fill = normal["fills"][0]
    changed_fill = changed["fills"][0]
    assert isinstance(normal_fill, dict)
    assert isinstance(changed_fill, dict)
    for field in (
        "reference_price",
        "fill_price",
        "requested_quantity",
        "filled_quantity",
    ):
        assert changed_fill[field] == normal_fill[field]
    normal_projection = normal["post_execution_projection"]
    changed_projection = changed["post_execution_projection"]
    assert isinstance(normal_projection, dict)
    assert isinstance(changed_projection, dict)
    assert changed_projection["volume_cap_shares"] == normal_projection["volume_cap_shares"]
    assert changed["market_source"]["liquidity_volume_date"] == DECISION_DATE


def test_queue_selects_due_frozen_recommendation_and_persists_processed_receipt(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    input_paths = _paths(input_root)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    queued_recommendation = recommendation_root / "scheduled_rec_20260904.json"
    queued_recommendation.write_bytes(input_paths.recommendation_json.read_bytes())
    receipts = tmp_path / "receipts"
    ledger = tmp_path / "paper-ledger.sqlite"
    PaperTradeLedgerRepository(ledger)
    queue_paths = PaperExecutionPaths(
        recommendation_json=tmp_path / "unused-placeholder.json",
        state_db=input_paths.state_db,
        market_db=input_paths.market_db,
        output_root=tmp_path / "queue-candidate",
        ledger_db=ledger,
        sector_membership_path=input_paths.sector_membership_path,
        sector_membership_file_hash=input_paths.sector_membership_file_hash,
    )

    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected == queued_recommendation
    assert reason == "next_official_session_due"

    result = run_paper_execution_daily_from_queue(
        queue_paths,
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )

    assert result["status"] == "machine_verified_candidate"
    assert result["ledger"]["appended"] is True
    receipt = result["operational_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["queue_state"] == "processed"
    receipt_path = Path(str(receipt["path"]))
    assert receipt_path.is_file()
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt_payload["source_file_hash"] == result["recommendation"]["file_hash"]
    assert receipt_payload["queue_state"] == "processed"
    selected_again, reason_again = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected_again is None
    assert reason_again == "no_pending_recommendation"


def test_same_day_retry_keeps_first_pending_recommendation_when_newer_source_arrives(
    tmp_path: Path,
) -> None:
    """EOD retry must keep the durable frozen decision for one session."""

    input_root = tmp_path / "inputs"
    input_root.mkdir()
    input_paths = _paths(input_root)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    original = recommendation_root / "original.json"
    original.write_bytes(input_paths.recommendation_json.read_bytes())
    receipts = tmp_path / "receipts"
    queue_paths = PaperExecutionPaths(
        recommendation_json=tmp_path / "unused-placeholder.json",
        state_db=input_paths.state_db,
        market_db=input_paths.market_db,
        output_root=tmp_path / "waiting-candidate",
        ledger_db=tmp_path / "paper-ledger.sqlite",
        sector_membership_path=input_paths.sector_membership_path,
        sector_membership_file_hash=input_paths.sector_membership_file_hash,
    )
    PaperTradeLedgerRepository(queue_paths.ledger_db)

    waiting = run_paper_execution_daily_from_queue(
        queue_paths,
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert waiting["status"] == "waiting_for_execution_source"
    waiting_receipt = waiting["operational_receipt"]
    assert isinstance(waiting_receipt, dict)
    assert waiting_receipt["queue_state"] == "pending_execution"

    newer = recommendation_root / "newer.json"
    _recommendation(newer, created_at="2026-09-04T21:00:00+08:00")
    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected == original
    assert reason == "pending_execution_retry"
    assert not any(
        json.loads(path.read_text(encoding="utf-8")).get("queue_state") == "superseded"
        for path in receipts.glob("*.json")
    )

    retry = run_paper_execution_daily_from_queue(
        PaperExecutionPaths(
            **{
                **queue_paths.__dict__,
                "output_root": tmp_path / "retry-candidate",
            }
        ),
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert retry["status"] == "machine_verified_candidate"
    assert retry["recommendation"]["path"] == str(original)
    assert retry["ledger"]["readback_verified"] is True


def test_retryable_missing_execution_source_is_pinned_until_market_row_arrives(
    tmp_path: Path,
) -> None:
    """A 15:05 source miss remains a legal same-day retry at 21:00."""

    input_root = tmp_path / "inputs"
    input_root.mkdir()
    input_paths = _paths(input_root)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    queued = recommendation_root / "queued.json"
    queued.write_bytes(input_paths.recommendation_json.read_bytes())
    with sqlite3.connect(input_paths.market_db) as connection:
        connection.execute(
            "DELETE FROM daily_prices WHERE 日期 = ? AND 證券代號 = ?",
            ("20260907", "2330"),
        )
    receipts = tmp_path / "receipts"
    queue_paths = PaperExecutionPaths(
        recommendation_json=tmp_path / "unused-placeholder.json",
        state_db=input_paths.state_db,
        market_db=input_paths.market_db,
        output_root=tmp_path / "failed-candidate",
        ledger_db=tmp_path / "paper-ledger.sqlite",
        sector_membership_path=input_paths.sector_membership_path,
        sector_membership_file_hash=input_paths.sector_membership_file_hash,
    )
    PaperTradeLedgerRepository(queue_paths.ledger_db)
    failed = run_paper_execution_daily_from_queue(
        queue_paths,
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert failed["status"] == "blocked"
    assert failed["retryable"] is True
    failed_receipt = failed["operational_receipt"]
    assert isinstance(failed_receipt, dict)
    assert failed_receipt["queue_state"] == "pending_execution"
    # Simulate a receipt written by the pre-pending producer: keep the original
    # immutable source/candidate payload, but retain its legacy ``failed``
    # queue state and omit the newer retryable marker.
    failed_receipt_path = Path(str(failed_receipt["path"]))
    legacy = json.loads(failed_receipt_path.read_text(encoding="utf-8"))
    legacy["queue_state"] = "failed"
    legacy["result"].pop("retryable", None)
    unsigned_legacy = dict(legacy)
    unsigned_legacy.pop("content_sha256")
    legacy["content_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(
            unsigned_legacy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    failed_receipt_path.write_text(
        json.dumps(legacy, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    legacy_bytes_before_retry = failed_receipt_path.read_bytes()

    with sqlite3.connect(input_paths.market_db) as connection:
        connection.execute(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?)",
            ("20260907", "2330", "測試公司", "10.20", "10.50", 100000),
        )
    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=datetime(2026, 9, 7, 21, 0, tzinfo=TAIPEI),
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected == queued
    assert reason == "pending_execution_retry"
    assert failed_receipt_path.read_bytes() == legacy_bytes_before_retry

    retried = run_paper_execution_daily_from_queue(
        PaperExecutionPaths(
            **{
                **queue_paths.__dict__,
                "output_root": tmp_path / "retried-candidate",
            }
        ),
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=datetime(2026, 9, 7, 21, 0, tzinfo=TAIPEI),
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert retried["status"] == "machine_verified_candidate"
    assert retried["operational_receipt"]["queue_state"] == "processed"


def test_legacy_pending_adoption_rejects_mixed_source_and_identity_blockers(
    tmp_path: Path,
) -> None:
    """A missing row cannot mask a clock/identity violation in a receipt."""

    input_root = tmp_path / "inputs"
    input_root.mkdir()
    input_paths = _paths(input_root)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    queued = recommendation_root / "queued.json"
    queued.write_bytes(input_paths.recommendation_json.read_bytes())
    with sqlite3.connect(input_paths.market_db) as connection:
        connection.execute(
            "DELETE FROM daily_prices WHERE 日期 = ? AND 證券代號 = ?",
            ("20260907", "2330"),
        )
    receipts = tmp_path / "receipts"
    result = run_paper_execution_daily_from_queue(
        PaperExecutionPaths(
            recommendation_json=tmp_path / "unused-placeholder.json",
            state_db=input_paths.state_db,
            market_db=input_paths.market_db,
            output_root=tmp_path / "candidate",
            ledger_db=tmp_path / "paper-ledger.sqlite",
        ),
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    receipt = result["operational_receipt"]
    assert isinstance(receipt, dict)
    receipt_path = Path(str(receipt["path"]))
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["queue_state"] = "failed"
    payload["result"].pop("retryable", None)
    payload["result"]["blockers"].append("clock identity mismatch")
    unsigned = dict(payload)
    unsigned.pop("content_sha256")
    payload["content_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    receipt_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected == queued
    assert reason == "next_official_session_due"


def test_pending_execution_session_missed_blocks_cross_day_source_switch(
    tmp_path: Path,
) -> None:
    """A late pending session is explicit no-credit, never silently replaced."""

    input_root = tmp_path / "inputs"
    input_root.mkdir()
    input_paths = _paths(input_root)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    original = recommendation_root / "original.json"
    original.write_bytes(input_paths.recommendation_json.read_bytes())
    receipts = tmp_path / "receipts"
    queue_paths = PaperExecutionPaths(
        recommendation_json=tmp_path / "unused-placeholder.json",
        state_db=input_paths.state_db,
        market_db=input_paths.market_db,
        output_root=tmp_path / "waiting-candidate",
        ledger_db=tmp_path / "paper-ledger.sqlite",
    )
    waiting = run_paper_execution_daily_from_queue(
        queue_paths,
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    waiting_receipt = waiting["operational_receipt"]
    assert isinstance(waiting_receipt, dict)
    receipt_path = Path(str(waiting_receipt["path"]))
    receipt_bytes = receipt_path.read_bytes()

    # A later decision maps to the next official session.  The stale 9/7
    # pending source must stop queue selection before that new source can win.
    newer = recommendation_root / "next-session.json"
    _recommendation(
        newer,
        created_at="2026-09-07T20:00:00+08:00",
        decision_date="2026-09-07",
    )
    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=datetime(2026, 9, 8, 10, 0, tzinfo=TAIPEI),
        market_db=input_paths.market_db,
        calendar=_Calendar({DECISION_DATE, EXECUTION_DATE, "2026-09-08"}),
        receipt_root=receipts,
    )
    assert selected is None
    assert reason == "pending_execution_session_missed:2026-09-07"
    assert receipt_path.read_bytes() == receipt_bytes


def test_missing_queue_is_observable_and_persists_skipped_receipt(
    tmp_path: Path,
) -> None:
    receipt_root = tmp_path / "receipts"
    result = run_paper_execution_daily_from_queue(
        PaperExecutionPaths(
            recommendation_json=tmp_path / "unused-placeholder.json",
            state_db=tmp_path / "state.sqlite",
            market_db=tmp_path / "market.sqlite",
            output_root=tmp_path / "candidate",
            ledger_db=tmp_path / "ledger.sqlite",
        ),
        recommendation_root=tmp_path / "missing-recommendation-root",
        receipt_root=receipt_root,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )

    assert result["status"] == "skipped_no_pending_recommendation"
    assert result["blockers"] == ["recommendation_root_missing"]
    receipt = result["operational_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["queue_state"] == "skipped"
    assert Path(str(receipt["path"])).is_file()
    assert not (tmp_path / "ledger.sqlite").exists()


def test_queue_freezes_one_latest_recommendation_per_execution_session(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    input_paths = _paths(input_root)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    older = recommendation_root / "older.json"
    newer = recommendation_root / "newer.json"
    _recommendation(older, created_at="2026-09-04T20:00:00+08:00")
    _recommendation(newer, created_at="2026-09-04T21:00:00+08:00")
    receipts = tmp_path / "receipts"
    queue_paths = PaperExecutionPaths(
        recommendation_json=tmp_path / "unused-placeholder.json",
        state_db=input_paths.state_db,
        market_db=input_paths.market_db,
        output_root=tmp_path / "queue-candidate",
        ledger_db=tmp_path / "paper-ledger.sqlite",
        sector_membership_path=input_paths.sector_membership_path,
        sector_membership_file_hash=input_paths.sector_membership_file_hash,
    )
    PaperTradeLedgerRepository(queue_paths.ledger_db)

    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected == newer
    assert reason == "next_official_session_due"
    superseded = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in receipts.glob("*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("queue_state") == "superseded"
    ]
    assert len(superseded) == 1
    assert superseded[0]["result"]["recommendation"]["path"] == str(older)

    result = run_paper_execution_daily_from_queue(
        queue_paths,
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    assert result["status"] == "machine_verified_candidate"
    assert result["recommendation"]["path"] == str(newer)
    selected_again, reason_again = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected_again is None
    assert reason_again == "no_pending_recommendation"
    states = {
        json.loads(path.read_text(encoding="utf-8"))["queue_state"]
        for path in receipts.glob("*.json")
    }
    assert {"superseded", "processed"}.issubset(states)


def test_rehashed_processed_receipt_with_false_ledger_readback_does_not_skip(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    input_paths = _paths(input_root)
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    queued_recommendation = recommendation_root / "queued.json"
    queued_recommendation.write_bytes(input_paths.recommendation_json.read_bytes())
    receipts = tmp_path / "receipts"
    queue_paths = PaperExecutionPaths(
        recommendation_json=tmp_path / "unused-placeholder.json",
        state_db=input_paths.state_db,
        market_db=input_paths.market_db,
        output_root=tmp_path / "queue-candidate",
        ledger_db=tmp_path / "paper-ledger.sqlite",
        sector_membership_path=input_paths.sector_membership_path,
        sector_membership_file_hash=input_paths.sector_membership_file_hash,
    )
    PaperTradeLedgerRepository(queue_paths.ledger_db)
    result = run_paper_execution_daily_from_queue(
        queue_paths,
        recommendation_root=recommendation_root,
        receipt_root=receipts,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
        confirm_append=True,
    )
    receipt = result["operational_receipt"]
    assert isinstance(receipt, dict)
    receipt_path = Path(str(receipt["path"]))
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["ledger"]["readback_verified"] = False
    payload["result"]["ledger"]["readback_verified"] = False
    unsigned = dict(payload)
    unsigned.pop("content_sha256")
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["content_sha256"] = "sha256:" + hashlib.sha256(encoded).hexdigest()
    receipt_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=input_paths.market_db,
        calendar=_open_calendar(),
        receipt_root=receipts,
    )
    assert selected == queued_recommendation
    assert reason == "next_official_session_due"

    payload["schema_version"] = "paper-execution-receipt-unknown"
    unsigned = dict(payload)
    unsigned.pop("content_sha256")
    payload["content_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    receipt_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected_after_schema_tamper, reason_after_schema_tamper = (
        resolve_pending_recommendation(
            recommendation_root,
            observed=EOD_REPLAY_NOW,
            market_db=input_paths.market_db,
            calendar=_open_calendar(),
            receipt_root=receipts,
        )
    )
    assert selected_after_schema_tamper == queued_recommendation
    assert reason_after_schema_tamper == "next_official_session_due"


def test_invalid_queue_source_is_reported_instead_of_no_pending(
    tmp_path: Path,
) -> None:
    recommendation_root = tmp_path / "recommendation-queue"
    recommendation_root.mkdir()
    (recommendation_root / "broken.json").write_text("{not-json", encoding="utf-8")

    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=EOD_REPLAY_NOW,
        market_db=tmp_path / "unused-market.sqlite",
        calendar=_open_calendar(),
    )

    assert selected is None
    assert reason.startswith("no_pending_recommendation_invalid_source:broken.json:")


def test_recommendation_close_must_match_prior_official_close(tmp_path: Path) -> None:
    paths = _paths(tmp_path, recommendation_close="10.01")
    with sqlite3.connect(paths.market_db) as connection:
        connection.execute(
            "UPDATE daily_prices SET 收盤價 = ? WHERE 日期 = ?",
            ("10.00", "20260904"),
        )
    result = run_paper_execution_daily(
        paths,
        now=EOD_REPLAY_NOW,
        calendar=_open_calendar(),
    )

    assert result["status"] == "blocked"
    assert any("market-reference-date close" in item for item in result["blockers"])


def test_unknown_calendar_keeps_next_session_blocked(tmp_path: Path) -> None:
    result = run_paper_execution_daily(
        _paths(tmp_path),
        now=EOD_REPLAY_NOW,
        calendar=_UnknownCalendar(),
    )

    assert result["status"] == "blocked"
    assert result["next_proven_trading_day"]["status"] == "blocked"
    assert result["next_proven_trading_day"]["date"] is None


def test_calendar_falls_back_to_local_market_indices_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path, with_calendar=True)
    monkeypatch.setattr(
        "data_module.official_trading_calendar.safe_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    result = run_paper_execution_daily(
        paths,
        now=EOD_REPLAY_NOW,
    )

    assert result["status"] == "machine_verified_candidate"
    calendar = result["official_calendar"]
    assert calendar["is_trading_day"] is True
    assert calendar["reason_code"] == "twstock_db_market_indices_evidence"
    assert calendar["fallback_evidence"]["mode"] == "read_only_market_indices_date_evidence"


def test_real_paper_consumer_reads_hash_bound_calendar_cache(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    cache_dir = tmp_path / "calendar-cache"
    cache_path = cache_dir / "twse_holiday_schedule_2026.json"
    raw = json.dumps(
        [
            {
                "Name": "中華民國開國紀念日",
                "Date": "1150101",
                "Description": "依規定放假1日。",
            },
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    captured = EOD_REPLAY_NOW.astimezone(timezone.utc) - timedelta(minutes=1)
    cache = build_twse_calendar_cache(
        calendar_year=2026,
        raw_response=raw,
        requested_at=captured - timedelta(seconds=1),
        captured_at=captured,
        response_status=200,
        response_headers={"Content-Type": "application/json"},
    )
    cache_dir.mkdir()
    write_twse_calendar_cache(cache_path, cache, allowed_root=tmp_path)
    calendar = OfficialTradingCalendar(
        paths.market_db,
        calendar_cache_path=cache_dir,
    )

    with patch(
        "data_module.official_trading_calendar.safe_request",
        side_effect=AssertionError("valid cache must be consumed before network"),
    ):
        result = run_paper_execution_daily(
            paths,
            now=EOD_REPLAY_NOW,
            calendar=calendar,
        )

    assert result["status"] == "machine_verified_candidate"
    assert result["official_calendar"]["source_evidence"]["mode"] == (
        "hash_bound_official_calendar_cache"
    )
    assert result["official_calendar"]["source_evidence"]["source_hash"] == (
        cache["source"]["response_sha256"]
    )


def test_schedule_snapshots_before_t1_candidate_handoff() -> None:
    text = Path("scripts/scheduled/run_paper_portfolio_daily.cmd").read_text(
        encoding="utf-8"
    ).lower()
    valuation = text.index("run_paper_portfolio_daily_isolated.py")
    execution = text.index("run_paper_execution_daily.py")
    assert valuation < execution
    assert "--confirm-append-paper-ledger" not in text
