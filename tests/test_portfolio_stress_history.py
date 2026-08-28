from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from app_module.portfolio_stress_history import (
    PortfolioStressHistoryReadService,
    PortfolioStressHistoryRecord,
    PortfolioStressHistoryRepository,
)
from app_module.portfolio_stress_lab_service import PortfolioStressLabService


def _stress_payload(*, research_only: bool = True) -> dict[str, object]:
    position = SimpleNamespace(
        is_holding=True,
        stock_code="2330",
        stock_name="台積電",
        quantity=Decimal("10"),
        current_price=Decimal("100.00"),
    )
    result = PortfolioStressLabService().evaluate_positions(
        [position],
        scenario_id="fast_drop",
        as_of_date="2026-08-27",
    )
    payload = result.to_dict()
    payload["research_only"] = research_only
    return payload


def test_record_from_stress_payload_is_deterministic_and_research_only() -> None:
    payload = _stress_payload()

    first = PortfolioStressHistoryRecord.from_payload(payload)
    second = PortfolioStressHistoryRecord.from_payload(payload)

    assert first.record_id == second.record_id
    assert first.payload_hash == second.payload_hash
    assert first.as_of_date == "2026-08-27"
    assert first.value_delta == Decimal("-100.00")
    assert first.research_only is True
    assert first.investment_effectiveness_claim is False


def test_repository_append_and_read_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "portfolio" / "stress_history.sqlite"
    record = PortfolioStressHistoryRecord.from_payload(_stress_payload())

    PortfolioStressHistoryRepository(db_path).append(record)
    result = PortfolioStressHistoryReadService(db_path).inspect()

    assert result.status == "ready"
    assert len(result.records) == 1
    assert result.records[0].payload_hash == record.payload_hash
    assert result.records[0].base_market_value == Decimal("1000.00")
    assert result.read_only is True
    assert result.writes_allowed is False


def test_read_service_missing_database_is_read_only_and_does_not_initialize(tmp_path: Path) -> None:
    db_path = tmp_path / "not_created" / "stress_history.sqlite"

    result = PortfolioStressHistoryReadService(db_path).inspect()

    assert result.status == "not_configured"
    assert "stress_history_not_configured" in result.warnings
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_repository_rejects_duplicate_deterministic_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "stress_history.sqlite"
    record = PortfolioStressHistoryRecord.from_payload(_stress_payload())
    repository = PortfolioStressHistoryRepository(db_path)
    repository.append(record)

    with pytest.raises(ValueError, match="already exists"):
        repository.append(record)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM portfolio_stress_history").fetchone()[0] == 1


def test_record_rejects_unsafe_input() -> None:
    with pytest.raises(ValueError, match="research_only"):
        PortfolioStressHistoryRecord.from_payload(_stress_payload(research_only=False))


def test_read_service_fails_closed_on_tampered_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "stress_history.sqlite"
    record = PortfolioStressHistoryRecord.from_payload(_stress_payload())
    PortfolioStressHistoryRepository(db_path).append(record)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE portfolio_stress_history SET payload_json = ? WHERE record_id = ?",
            (json.dumps({"tampered": True}), record.record_id),
        )
        connection.commit()

    result = PortfolioStressHistoryReadService(db_path).inspect()

    assert result.status == "degraded"
    assert result.records == ()
    assert "stress_history_invalid_row" in result.blockers
