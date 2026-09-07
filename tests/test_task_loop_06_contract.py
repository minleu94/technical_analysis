"""TASK-LOOP-06 的隔離帳本、重播與 migration 契約。"""

from decimal import Decimal
import json
from pathlib import Path
import shutil

import pytest

from app_module.portfolio_service import PortfolioService
from data_module.config import TWStockConfig
from data_module.portfolio_ledger_migration import PortfolioLedgerMigration
from data_module.portfolio_ledger_repository import (
    PortfolioLedgerEvent,
    PortfolioLedgerRepository,
)
from portfolio_module.core import PortfolioValidationError, rebuild_ledger_projection


def _event(
    event_id: str,
    *,
    side: str = "buy",
    quantity: int = 10,
    price: str = "100.00",
    occurred_at: str = "2026-01-02",
    source_namespace: str = "manual",
    fees: str = "0.00",
    taxes: str = "0.00",
    source_id: str = "ticket-1",
    thesis_id: str = "thesis-1",
) -> PortfolioLedgerEvent:
    return PortfolioLedgerEvent(
        event_id=event_id,
        portfolio_id="default",
        source_namespace=source_namespace,
        occurred_at=occurred_at,
        stock_code="2330",
        stock_name="台積電",
        side=side,
        quantity=quantity,
        price=Decimal(price),
        fees=Decimal(fees),
        taxes=Decimal(taxes),
        source_id=source_id,
        thesis_id=thesis_id,
    )


def test_precise_replay_covers_fees_realized_cash_and_deterministic_positions(tmp_path):
    repository = PortfolioLedgerRepository(tmp_path / "candidate.db")
    buy = _event("buy-1", fees="1.00")
    sell = _event(
        "sell-1",
        side="sell",
        quantity=4,
        price="125.00",
        occurred_at="2026-01-03",
        fees="0.50",
    )
    repository.append_many((buy, sell))

    first = rebuild_ledger_projection(
        repository.list_events(),
        initial_cash=Decimal("10000.00"),
        reject_negative_cash=True,
    )
    second = rebuild_ledger_projection(
        tuple(reversed(repository.list_events())),
        initial_cash=Decimal("10000.00"),
        reject_negative_cash=True,
    )

    assert first == second
    assert first.positions[0].quantity == 6
    assert first.positions[0].average_cost == Decimal("100.10")
    assert first.realized_pnl == Decimal("99.10")
    assert first.cash == Decimal("9498.50")


def test_duplicate_oversell_and_negative_cash_are_fail_closed(tmp_path):
    repository = PortfolioLedgerRepository(tmp_path / "candidate.db")
    buy = _event("buy-1")
    repository.append(buy)
    with pytest.raises(ValueError, match="already exists"):
        repository.append(buy)

    with pytest.raises(PortfolioValidationError, match="negative cash"):
        rebuild_ledger_projection(
            repository.list_events(),
            initial_cash=Decimal("1.00"),
            reject_negative_cash=True,
        )

    oversell = _event("sell-oversell", side="sell", quantity=11, occurred_at="2026-01-03")
    with pytest.raises(PortfolioValidationError, match="exceeds"):
        rebuild_ledger_projection((buy, oversell), initial_cash=Decimal("10000.00"))


def test_compensation_is_append_only_and_rebuildable(tmp_path):
    repository = PortfolioLedgerRepository(tmp_path / "candidate.db")
    buy = _event("buy-1")
    repository.append(buy)
    compensation = repository.append_compensation(
        "buy-1",
        event_id="comp-1",
        occurred_at="2026-01-03",
        reason="manual correction",
    )

    assert compensation.event_type == "compensation"
    assert repository.get("buy-1") is not None
    projection = rebuild_ledger_projection(
        repository.list_events(), initial_cash=Decimal("1000.00")
    )
    assert projection.positions == ()
    assert projection.cash == Decimal("1000.00")
    assert projection.compensated_event_ids == ("buy-1",)


def test_namespace_separation_and_query_only_do_not_mutate_schema(tmp_path):
    repository = PortfolioLedgerRepository(tmp_path / "candidate.db")
    repository.append(_event("manual-1"))
    repository.append(_event("paper-1", source_namespace="paper"))
    assert len(repository.list_events(source_namespace="manual")) == 1
    assert len(repository.list_events(source_namespace="paper")) == 1
    with pytest.raises(PortfolioValidationError, match="namespaces"):
        rebuild_ledger_projection(repository.list_events())

    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        PortfolioLedgerRepository.open_read_only(missing)
    assert not missing.exists()


def test_candidate_repository_closes_connections_for_windows_cleanup(tmp_path):
    candidate_root = tmp_path / "candidate-root"
    repository = PortfolioLedgerRepository(candidate_root / "portfolio.db")
    repository.append(_event("cleanup-1"))
    assert repository.list_events()[0].event_id == "cleanup-1"
    read_only = PortfolioLedgerRepository.open_read_only(candidate_root / "portfolio.db")
    assert read_only.source_hash().startswith("sha256:")
    del read_only
    del repository

    # Windows cannot remove a directory while a SQLite handle is still open.
    shutil.rmtree(candidate_root)
    assert not candidate_root.exists()


def test_portfolio_service_freezes_read_model_date_quality_and_hash(tmp_path):
    repository = PortfolioLedgerRepository(tmp_path / "candidate.db")
    service = PortfolioService(
        TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output", profile="unit"),
        ledger_repository=repository,
    )
    service.record_precise_trade(
        event_id="buy-1",
        portfolio_id="default",
        stock_code="2330",
        stock_name="台積電",
        side="buy",
        quantity=10,
        price=Decimal("100.00"),
        occurred_at="2026-01-02",
        source_id="source-1",
        thesis_id="thesis-1",
    )
    blocked = service.build_ledger_read_model(
        portfolio_id="default", as_of_date="2026-01-02"
    )
    complete = service.build_ledger_read_model(
        portfolio_id="default",
        as_of_date="2026-01-02",
        market_prices={"2330": Decimal("110.00")},
    )
    assert blocked.quality == "blocked"
    assert "market_prices" in blocked.missing_inputs
    assert complete.quality == "complete"
    assert complete.source_ledger_hash.startswith("sha256:")
    assert complete.as_of_date == "2026-01-02"
    assert complete.positions[0].unrealized_pnl == Decimal("100.00")


def test_missing_thesis_and_source_are_degraded_with_positions_preserved(tmp_path):
    repository = PortfolioLedgerRepository.create_synthetic_fixture(
        tmp_path / "candidate.db",
        events=(_event("buy-1", source_id="", thesis_id=""),),
    )
    service = PortfolioService(
        TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output", profile="unit"),
        ledger_repository=repository,
    )
    model = service.build_ledger_read_model(
        portfolio_id="default",
        as_of_date="2026-01-02",
        market_prices={"2330": Decimal("100.00")},
    )
    assert model.quality == "degraded"
    assert "source_id_missing" in model.warnings
    assert "thesis_missing" in model.warnings
    assert model.positions[0].quantity == 10


def test_jsonl_to_isolated_sqlite_is_hash_preserving_and_idempotent(tmp_path):
    source = tmp_path / "trades.jsonl"
    source.write_text(
        json.dumps(
            {
                "trade_id": "trade-1",
                "portfolio_id": "default",
                "stock_code": "2330",
                "stock_name": "台積電",
                "side": "buy",
                "quantity": 10.0,
                "price": 100.0,
                "fees": 1.0,
                "taxes": 0.0,
                "trade_date": "2026-01-02",
                "source_id": "manual-ticket",
                "thesis_id": "thesis-1",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    original = source.read_bytes()
    candidate = tmp_path / "candidate.db"
    migration = PortfolioLedgerMigration(source, candidate)

    preview = migration.preview()
    first = migration.migrate_copy()
    second = migration.migrate_copy()

    assert preview.status == "ready"
    assert first.status == "completed"
    assert first.migrated_event_count == 1
    assert second.status == "already_present"
    assert second.migrated_event_count == 0
    assert second.duplicate_event_count == 1
    assert source.read_bytes() == original
    assert len(PortfolioLedgerRepository.open_read_only(candidate).list_events()) == 1


def test_missing_jsonl_is_blocked_and_true_fills_are_not_invented(tmp_path):
    migration = PortfolioLedgerMigration(tmp_path / "missing.jsonl", tmp_path / "candidate.db")
    report = migration.migrate_copy()
    assert report.status == "blocked"
    assert "legacy_trade_source_missing" in report.blockers
    assert report.write_performed is False


def test_backtest_namespace_cannot_be_migrated_or_recorded_as_fills(tmp_path):
    with pytest.raises(ValueError, match="backtest"):
        PortfolioLedgerMigration(
            tmp_path / "backtest.jsonl",
            tmp_path / "candidate.db",
            source_namespace="backtest",
        )
    repository = PortfolioLedgerRepository(tmp_path / "candidate.db")
    service = PortfolioService(
        TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output", profile="unit"),
        ledger_repository=repository,
    )
    with pytest.raises(PortfolioValidationError, match="backtest"):
        service.record_precise_trade(
            event_id="bt-1",
            portfolio_id="default",
            stock_code="2330",
            stock_name="台積電",
            side="buy",
            quantity=1,
            price=Decimal("100.00"),
            occurred_at="2026-01-02",
            source_namespace="backtest",
        )
