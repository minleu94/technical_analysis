from decimal import Decimal
from pathlib import Path

import pytest

from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)


def _snapshot(snapshot_id: str = "paper-20260712") -> PaperPortfolioSnapshot:
    return PaperPortfolioSnapshot(
        snapshot_id=snapshot_id,
        portfolio_id="paper-main",
        decision_date="2026-07-12",
        source_result_id="rec-1",
        cash=Decimal("100000.00"),
        total_value=Decimal("500000.00"),
        positions=(
            PaperPortfolioPositionSnapshot(
                stock_code="2330",
                quantity=300,
                mark_price=Decimal("1000.00"),
                market_value=Decimal("300000.00"),
                weight_bp=6000,
            ),
        ),
    )


def test_repository_appends_and_reads_snapshot(tmp_path: Path) -> None:
    repository = PaperPortfolioSnapshotRepository(tmp_path / "paper.sqlite")

    repository.append(_snapshot())
    loaded = repository.get("paper-20260712")

    assert loaded == _snapshot()
    assert repository.list_for_portfolio("paper-main") == (_snapshot(),)


def test_duplicate_snapshot_id_cannot_overwrite_history(tmp_path: Path) -> None:
    repository = PaperPortfolioSnapshotRepository(tmp_path / "paper.sqlite")
    repository.append(_snapshot())

    with pytest.raises(ValueError, match="already exists"):
        repository.append(_snapshot())

    assert repository.get("paper-20260712") == _snapshot()


def test_weight_must_be_integer_basis_points() -> None:
    with pytest.raises(ValueError, match="weight_bp"):
        PaperPortfolioPositionSnapshot(
            stock_code="2330",
            quantity=1,
            mark_price=Decimal("1"),
            market_value=Decimal("1"),
            weight_bp=100.5,  # type: ignore[arg-type]
        )
