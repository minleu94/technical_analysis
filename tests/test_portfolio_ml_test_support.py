from __future__ import annotations

from pathlib import Path
import sys
import pytest

from data_module import ml_storage_capacity as storage_capacity
from tests.fixtures.portfolio_ml_ooc_support import (
    SYNTHETIC_CAPACITY_FREE_BYTES,
    synthetic_filesystem_usage,
    run_synthetic_ml_cli,
)


def test_synthetic_capacity_fixture_is_explicitly_scoped(
    synthetic_ml_capacity,
) -> None:
    observed = storage_capacity.filesystem_usage(Path("fixture"))

    assert observed is not None
    assert observed["free_bytes"] == SYNTHETIC_CAPACITY_FREE_BYTES
    assert storage_capacity.filesystem_usage is synthetic_filesystem_usage


def test_synthetic_capacity_probe_is_not_global_after_fixture_teardown() -> None:
    assert storage_capacity.filesystem_usage is not synthetic_filesystem_usage


def test_synthetic_cli_wrapper_rejects_nonfixture_entrypoints(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only supports bounded fixture builders"):
        run_synthetic_ml_cli([sys.executable, str(tmp_path / "arbitrary.py")])
