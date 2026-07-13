from __future__ import annotations

from pathlib import Path

import pytest

from data_module.p0_candidate_repository import (
    ProductionPathRejectedError,
    validate_candidate_working_copy_path,
)


def test_candidate_apply_rejects_production_database_and_descendants(tmp_path: Path) -> None:
    data_root = tmp_path / "formal-data"
    production_db = data_root / "sqlite" / "twstock.db"

    with pytest.raises(ProductionPathRejectedError):
        validate_candidate_working_copy_path(
            production_db,
            production_data_root=data_root,
            production_db_path=production_db,
        )

    with pytest.raises(ProductionPathRejectedError):
        validate_candidate_working_copy_path(
            data_root / "candidate" / "working.sqlite",
            production_data_root=data_root,
            production_db_path=production_db,
        )


def test_candidate_apply_accepts_only_explicit_isolated_working_copy(tmp_path: Path) -> None:
    data_root = tmp_path / "formal-data"
    candidate_db = tmp_path / "isolated-output" / "candidate.sqlite"

    resolved = validate_candidate_working_copy_path(
        candidate_db,
        production_data_root=data_root,
        production_db_path=data_root / "sqlite" / "twstock.db",
    )

    assert resolved == candidate_db.resolve()
    assert candidate_db.exists() is False
    assert candidate_db.parent.exists() is False


def test_missing_working_copy_path_is_rejected_without_side_effect(tmp_path: Path) -> None:
    before = tuple(tmp_path.rglob("*"))

    with pytest.raises(ValueError, match="working-copy"):
        validate_candidate_working_copy_path(
            None,
            production_data_root=tmp_path / "formal-data",
            production_db_path=tmp_path / "formal-data" / "sqlite" / "twstock.db",
        )

    assert tuple(tmp_path.rglob("*")) == before
