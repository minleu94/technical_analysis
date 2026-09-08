"""隔離的 Portfolio ML OOC 測試支援。

這個模組只保存跨測試共用的合成資料 builder 與 fixture；它不是正式 pytest
測試模組，也不應讀取 ``DATA_ROOT`` 或修改正式產物。容量探針只在明確使用
``synthetic_ml_capacity`` / ``synthetic_ml_capacity_module`` 時替換，fixture
結束後一定還原原始 probe。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import subprocess
from typing import Iterator
from typing import Any, Sequence
from unittest.mock import patch

import pytest

from data_module import ml_storage_capacity as storage_capacity
from data_module.ml_storage_capacity import BYTES_PER_GIB
from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.portfolio_ml_dataset_assembler import (
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
)
from data_module.portfolio_ml_out_of_core_store import (
    PortfolioMLOutOfCoreStoreBuilder,
    PortfolioMLOutOfCoreStoreRequest,
)
from ml_module.allocation_out_of_core_training_service import (
    AllocationOutOfCoreTrainingRequest,
    AllocationOutOfCoreTrainingService,
)
from tests.ml_teacher_fixture import attach_synthetic_teacher_provenance
from tests.test_portfolio_ml_dataset_assembler import _database


SYNTHETIC_CAPACITY_TOTAL_BYTES = 1_024 * BYTES_PER_GIB
SYNTHETIC_CAPACITY_FREE_BYTES = 512 * BYTES_PER_GIB


def run_synthetic_ml_cli(
    command: Sequence[str], **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """在子程序驗證CLI；只替換合成資料的容量觀測，不修改正式入口。"""
    script = Path(command[1]).resolve()
    scripts_root = Path(__file__).resolve().parents[2] / "scripts"
    if script.parent != scripts_root or script.name not in {
        "build_ml_pit_year_shards.py", "build_portfolio_ml_training_shards.py",
    }:
        raise ValueError("synthetic CLI wrapper only supports bounded fixture builders")
    wrapper = (
        "import runpy, sys; from unittest.mock import patch; "
        "from tests.fixtures.portfolio_ml_ooc_support import synthetic_filesystem_usage; "
        "sys.argv=sys.argv[1:]; "
        "scope=patch('data_module.ml_storage_capacity.filesystem_usage', synthetic_filesystem_usage); "
        "scope.start(); runpy.run_path(sys.argv[0], run_name='__main__')"
    )
    return subprocess.run([command[0], "-c", wrapper, *command[1:]], **kwargs)


@dataclass(frozen=True)
class BoundedE2E:
    raw_manifest_path: Path
    training_manifest_path: Path
    store_manifest_path: Path
    store_manifest_hash: str
    ridge_manifest_path: Path
    ridge_manifest_hash: str


def synthetic_filesystem_usage(path: Path) -> dict[str, int | str]:
    """回傳只供合成測試使用的可控容量觀測值。"""

    return {
        "probe_path": str(path),
        "total_bytes": SYNTHETIC_CAPACITY_TOTAL_BYTES,
        "used_bytes": SYNTHETIC_CAPACITY_TOTAL_BYTES - SYNTHETIC_CAPACITY_FREE_BYTES,
        "free_bytes": SYNTHETIC_CAPACITY_FREE_BYTES,
    }


@pytest.fixture
def synthetic_ml_capacity() -> Iterator[None]:
    """只在要求此 fixture 的單一測試內注入容量 probe。"""

    original = storage_capacity.filesystem_usage
    with patch.object(
        storage_capacity,
        "filesystem_usage",
        synthetic_filesystem_usage,
    ):
        yield
    assert storage_capacity.filesystem_usage is original


@pytest.fixture(scope="module")
def synthetic_ml_capacity_module() -> Iterator[None]:
    """只在要求此 fixture 的單一測試 module 內注入容量 probe。"""

    original = storage_capacity.filesystem_usage
    with patch.object(
        storage_capacity,
        "filesystem_usage",
        synthetic_filesystem_usage,
    ):
        yield
    assert storage_capacity.filesystem_usage is original


def _long_raw_publication(root: Path):
    """建立三年度、含合法 OHLC 關係的合成 raw publication。"""

    database = root / "source.db"
    _database(database)
    start = date(2024, 1, 1)
    stock_rows: list[tuple[object, ...]] = []
    market_rows: list[tuple[object, ...]] = []
    for index in range(240, 800):
        day = (start + timedelta(days=index)).strftime("%Y%m%d")
        market_open = 1_000 + index
        market_close = market_open + 1
        market_rows.append(
            (
                day,
                "TAIEX",
                str(market_open),
                str(market_close + 2),
                str(market_open - 2),
                str(market_close),
            )
        )
        positive_open = 100 + index
        negative_open = 1_200 - index
        stock_rows.extend(
            (
                (
                    day,
                    "2330",
                    "positive",
                    1_000_000 + index,
                    str(positive_open),
                    str(positive_open + 3),
                    str(positive_open - 2),
                    str(positive_open + 2),
                    None if index % 17 == 0 else "20.5",
                ),
                (
                    day,
                    "2317",
                    "negative",
                    900_000 + index,
                    str(negative_open),
                    str(negative_open + 2),
                    str(negative_open - 3),
                    str(negative_open - 1),
                    None if index % 19 == 0 else "12.0",
                ),
            )
        )
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            stock_rows,
        )
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?, ?, ?)",
            market_rows,
        )
    return PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=root / "raw",
            decision_at="2026-04-01T08:30:00+08:00",
            history_start_date="2024-01-01",
            symbols=None,
            years=(2024, 2025, 2026),
            batch_size=61,
        )
    )


@pytest.fixture(scope="module")
def bounded_e2e(
    tmp_path_factory: pytest.TempPathFactory,
    synthetic_ml_capacity_module: None,
) -> BoundedE2E:
    """供 OOC／release tests 共用的合成 end-to-end publication。"""

    root = tmp_path_factory.mktemp("portfolio-ml-ooc")
    raw = _long_raw_publication(root)
    raw_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    training = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=raw_manifest_path,
            output_root=root / "training",
            training_as_of="2026-04-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            minimum_train_dates=65,
            test_date_count=65,
            purge_trading_days=60,
            embargo_trading_days=5,
            batch_size=29,
        )
    )
    attach_synthetic_teacher_provenance(
        training.manifest_path,
        fixture_root=root / "synthetic-teacher-provenance",
    )
    store_request = PortfolioMLOutOfCoreStoreRequest(
        training_manifest_path=training.manifest_path,
        output_root=root / "store",
        batch_size=31,
        workers=2,
        memory_budget_mb=1_024,
    )
    store = PortfolioMLOutOfCoreStoreBuilder().build(store_request)
    resumed_store = PortfolioMLOutOfCoreStoreBuilder().build(store_request)
    assert resumed_store.run_id == store.run_id
    assert resumed_store.manifest_hash == store.manifest_hash
    assert resumed_store.manifest_file_hash == store.manifest_file_hash

    ridge_request = AllocationOutOfCoreTrainingRequest(
        store_manifest_path=store.manifest_path,
        output_root=root / "ridge",
        algorithms=("ridge_logistic",),
        horizons=(5,),
        batch_size=31,
        workers=2,
        memory_budget_mb=1_024,
        logistic_iterations=2,
    )
    ridge = AllocationOutOfCoreTrainingService().train(ridge_request)
    replay = AllocationOutOfCoreTrainingService().train(ridge_request)
    assert replay.run_id == ridge.run_id
    assert replay.manifest_hash == ridge.manifest_hash
    assert replay.manifest_file_hash == ridge.manifest_file_hash
    return BoundedE2E(
        raw_manifest_path=raw_manifest_path,
        training_manifest_path=training.manifest_path,
        store_manifest_path=store.manifest_path,
        store_manifest_hash=store.manifest_hash,
        ridge_manifest_path=ridge.manifest_path,
        ridge_manifest_hash=ridge.manifest_hash,
    )


__all__ = [
    "BoundedE2E",
    "_long_raw_publication",
    "bounded_e2e",
    "synthetic_filesystem_usage",
    "synthetic_ml_capacity",
    "synthetic_ml_capacity_module",
]
