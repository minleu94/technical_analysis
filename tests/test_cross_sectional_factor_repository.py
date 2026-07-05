from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app_module.cross_sectional_factor_dtos import (
    CrossSectionalFactorRow,
    CrossSectionalFactorSnapshot,
)
from app_module.cross_sectional_factor_repository import (
    CrossSectionalFactorRepository,
    CrossSectionalFactorSnapshotConflictError,
)
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy


def _sample_row(*, row_id: str = "row-1", score_bp: int | None = 8000) -> CrossSectionalFactorRow:
    return CrossSectionalFactorRow(
        row_id=row_id,
        stock_code="2330",
        factor_name="technical.total_score",
        as_of_date=date(2026, 7, 4),
        available_date=date(2026, 7, 5),
        value=Decimal("80"),
        score_bp=score_bp,
        rank=1,
        quantile_bp=10000,
        universe_size=1,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        sector="半導體",
        concept_basket="ai",
        metadata={"source": "unit-test"},
    )


def _sample_snapshot(*, rows: tuple[CrossSectionalFactorRow, ...] | None = None) -> CrossSectionalFactorSnapshot:
    return CrossSectionalFactorSnapshot(
        snapshot_id="csf_20260705_test",
        decision_date=date(2026, 7, 5),
        factor_set_version="v1.6-test",
        universe_id="test-universe",
        source_version="unit-test",
        rows=rows if rows is not None else (_sample_row(),),
        diagnostics=(),
        metadata={"sector_source": "unit-test"},
    )


def test_repository_saves_snapshot_idempotently(tmp_path):
    repository = CrossSectionalFactorRepository(tmp_path / "factors.db")
    snapshot = _sample_snapshot()

    first = repository.save_snapshot(snapshot)
    second = repository.save_snapshot(snapshot)

    assert first.snapshot_hash == second.snapshot_hash
    assert first.row_count == 1
    assert repository.get_latest_snapshot_id() == "csf_20260705_test"
    rows = repository.list_rows("csf_20260705_test")
    assert len(rows) == 1
    assert rows[0].stock_code == "2330"
    assert rows[0].value == Decimal("80")
    assert rows[0].quality == FactorQuality.OBSERVED
    assert rows[0].sector == "半導體"


def test_repository_rejects_same_snapshot_id_with_different_hash(tmp_path):
    repository = CrossSectionalFactorRepository(tmp_path / "factors.db")
    repository.save_snapshot(_sample_snapshot())

    changed = _sample_snapshot(rows=(_sample_row(score_bp=7000),))

    with pytest.raises(CrossSectionalFactorSnapshotConflictError):
        repository.save_snapshot(changed)


def test_snapshot_metadata_rejects_bool_values():
    with pytest.raises(TypeError):
        CrossSectionalFactorSnapshot(
            snapshot_id="csf_invalid",
            decision_date=date(2026, 7, 5),
            factor_set_version="v1.6-test",
            universe_id="test-universe",
            source_version="unit-test",
            rows=(_sample_row(),),
            metadata={"unsafe": True},
        )
