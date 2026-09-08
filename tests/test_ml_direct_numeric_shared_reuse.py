from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, cast

import numpy as np

from data_module import portfolio_ml_direct_numeric_store as direct_store_module
from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.portfolio_ml_direct_numeric_store import (
    PortfolioMLDirectNumericRequest,
    PortfolioMLDirectNumericStoreBuilder,
)
from ml_module.allocation_out_of_core_training_service import (
    AllocationOutOfCoreTrainingRequest,
    AllocationOutOfCoreTrainingService,
    _NumericStore,
)
from tests.test_portfolio_ml_dataset_assembler import _database
from tests.test_portfolio_ml_dataset_assembler import (
    _sector_membership_row,
    _write_sector_membership_sidecar,
)
from tests.ml_teacher_fixture import attach_synthetic_teacher_provenance


_SAFETY_RESERVE_BYTES = 200 * (1024**3)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _directory_bytes(path: Path) -> int:
    return sum(
        item.stat().st_size
        for item in path.rglob("*")
        if item.is_file() and not item.is_symlink()
    )


def _prepare_three_year_database(
    path: Path,
    *,
    changed_year: int | None = None,
) -> None:
    _database(path)
    with sqlite3.connect(path) as connection:
        daily_rows = connection.execute(
            "SELECT * FROM daily_prices"
        ).fetchall()
        market_rows = connection.execute(
            "SELECT * FROM market_indices"
        ).fetchall()
        for year in (2022, 2023):
            connection.executemany(
                "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (f"{year}{str(row[0])[4:]}", *row[1:])
                    for row in daily_rows
                ],
            )
            connection.executemany(
                "INSERT INTO market_indices VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f"{year}{str(row[0])[4:]}", *row[1:])
                    for row in market_rows
                ],
            )
        if changed_year == 2024:
            connection.execute(
                "UPDATE daily_prices SET 收盤價 = ? "
                "WHERE 日期 = ? AND 證券代號 = ?",
                ("999.99", "20240110", "2317"),
            )
        elif changed_year == 2022:
            # 改年末 volume，確實改變該年度輸出的 bounded carry，
            # 令後續年度以 carry-input key 失效。
            connection.execute(
                "UPDATE daily_prices SET 成交股數 = ? "
                "WHERE 日期 = ? AND 證券代號 = ?",
                (7_654_321, "20220827", "2317"),
            )


def _build_raw(root: Path, *, changed_year: int | None = None):
    root.mkdir(parents=True, exist_ok=True)
    database = root / "source.db"
    _prepare_three_year_database(database, changed_year=changed_year)
    return PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=root / "raw",
            decision_at="2025-01-01T08:30:00+08:00",
            history_start_date="2022-01-01",
            symbols=("2317", "2330"),
            years=(2022, 2023, 2024),
            batch_size=31,
        )
    )


def _direct_request(
    raw: Any,
    *,
    output_root: Path,
    shared_root: Path,
    sector_path: Path | None = None,
) -> PortfolioMLDirectNumericRequest:
    return PortfolioMLDirectNumericRequest(
        raw_manifest_path=raw.dataset_manifest_paths["all_field_enriched"],
        output_root=output_root,
        training_as_of="2025-01-01T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        sector_membership_path=sector_path,
        minimum_train_dates=65,
        test_date_count=65,
        purge_trading_days=60,
        embargo_trading_days=5,
        batch_size=31,
        workers=1,
        memory_budget_mb=1_024,
        temporary_storage_budget_bytes=1 << 30,
        persistent_new_bytes_budget=1 << 30,
        safety_reserve_bytes=_SAFETY_RESERVE_BYTES,
        resume=False,
        shared_numeric_store_root=shared_root,
    )


def _years_by_year(publication: Any) -> dict[int, dict[str, Any]]:
    manifest = _read_json(publication.manifest_path)
    return {
        int(item["year"]): cast(dict[str, Any], item)
        for item in manifest["years"]
    }


def _artifact_hashes(year_manifest: dict[str, Any]) -> dict[str, str]:
    return {
        str(item["artifact_id"]): str(item["file_sha256"])
        for item in year_manifest["artifacts"]
    }


def test_direct_year_path_receives_resolved_capacity_budget(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """真實年度建置不得依賴外層未定義的暫存預算。"""

    raw = _build_raw(tmp_path / "capacity-year-source")
    request = _direct_request(
        raw,
        output_root=tmp_path / "capacity-year-direct",
        shared_root=tmp_path / "capacity-year-registry",
    )
    observed: list[dict[str, Any]] = []
    original_build_year = PortfolioMLDirectNumericStoreBuilder._build_year

    def spy_build_year(self: Any, **kwargs: Any) -> Any:
        budget = kwargs.get("capacity_budget")
        assert budget is not None
        observed.append(budget.as_dict())
        return original_build_year(self, **kwargs)

    monkeypatch.setattr(
        PortfolioMLDirectNumericStoreBuilder,
        "_build_year",
        spy_build_year,
    )
    publication = PortfolioMLDirectNumericStoreBuilder().build(request)

    assert publication.row_count > 0
    assert observed
    assert all(item["temporary_peak_bytes_budget"] == 1 << 30 for item in observed)
    assert all(item["persistent_new_bytes_budget"] == 1 << 30 for item in observed)
    assert all(item["safety_reserve_bytes"] == _SAFETY_RESERVE_BYTES for item in observed)


def test_unchanged_year_is_reused_before_numeric_build_and_ooc_reads_shared(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    baseline_raw = _build_raw(tmp_path / "baseline")
    shared_root = tmp_path / "numeric-registry"
    baseline_request = _direct_request(
        baseline_raw,
        output_root=tmp_path / "direct-baseline",
        shared_root=shared_root,
    )
    baseline = PortfolioMLDirectNumericStoreBuilder().build(baseline_request)
    baseline_years = _years_by_year(baseline)
    assert set(baseline_years) == {2022, 2023, 2024}
    assert all(
        item["artifact_storage"] == "immutable_shared"
        and "shared_year_descriptor" in item
        and all(
            str(artifact["storage"]) == "immutable_shared"
            for artifact in item["artifacts"]
        )
        for item in baseline_years.values()
    )
    before_bytes = _directory_bytes(shared_root)

    changed_raw = _build_raw(tmp_path / "changed-final", changed_year=2024)
    calls: list[int] = []
    original_build_year = PortfolioMLDirectNumericStoreBuilder._build_year

    def spy_build_year(self: Any, **kwargs: Any) -> Any:
        calls.append(int(kwargs["year"]))
        return original_build_year(self, **kwargs)

    monkeypatch.setattr(
        PortfolioMLDirectNumericStoreBuilder,
        "_build_year",
        spy_build_year,
    )
    created_prefixes: list[str] = []
    real_mkdtemp = direct_store_module.tempfile.mkdtemp

    def spy_mkdtemp(*args: Any, **kwargs: Any) -> str:
        created_prefixes.append(str(kwargs.get("prefix", "")))
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(direct_store_module.tempfile, "mkdtemp", spy_mkdtemp)
    changed = PortfolioMLDirectNumericStoreBuilder().build(
        _direct_request(
            changed_raw,
            output_root=tmp_path / "direct-changed-final",
            shared_root=shared_root,
        )
    )
    changed_years = _years_by_year(changed)
    assert 2022 not in calls
    assert not any(".year-2022-" in prefix for prefix in created_prefixes)
    assert changed_years[2022]["shared_artifact_publication"][
        "reuse_before_build"
    ] is True
    assert changed_years[2022]["shared_artifact_publication"][
        "new_bytes_written"
    ] == 0
    assert _artifact_hashes(changed_years[2022]) == _artifact_hashes(
        baseline_years[2022]
    )
    assert _directory_bytes(shared_root) > before_bytes
    assert changed_years[2023]["shared_artifact_publication"].get(
        "reuse_before_build", False
    ) is False
    assert changed_years[2024]["shared_artifact_publication"].get(
        "reuse_before_build", False
    ) is False
    assert all(
        {
            path.name
            for path in (
                changed.run_directory / f"year={year:04d}"
            ).iterdir()
        }
        == {"manifest.json"}
        for year in changed_years
    )

    # OOC 的 public consumer 直接 mmap shared numeric artifacts；run-local
    # 年度檔案只有 manifest，rows.sqlite 也必須走 shared resolver。
    numeric_store = _NumericStore(
        changed.manifest_path,
        shared_numeric_store_root=shared_root,
    )
    refs = np.asarray([[0, 0], [1, 0]], dtype=np.int64)
    feature_positions = (0, 1)
    values = numeric_store.read_feature_batch(refs, feature_positions)
    assert values.shape == (2, 2)
    assert numeric_store.years[0].rows_path.is_relative_to(shared_root)
    assert list(numeric_store.iter_decision_dates(refs))
    patched_manifest_hash = attach_synthetic_teacher_provenance(
        changed.manifest_path,
        fixture_root=tmp_path / "synthetic-teacher-provenance",
    )
    trained = AllocationOutOfCoreTrainingService().train(
        AllocationOutOfCoreTrainingRequest(
            store_manifest_path=changed.manifest_path,
            output_root=tmp_path / "ooc-from-shared-numeric",
            shared_numeric_store_root=shared_root,
            algorithms=("ridge_logistic",),
            horizons=(5,),
            batch_size=128,
            workers=1,
            memory_budget_mb=1_024,
            logistic_iterations=1,
            temporary_storage_budget_bytes=1 << 30,
            persistent_new_bytes_budget=1 << 30,
            safety_reserve_bytes=_SAFETY_RESERVE_BYTES,
            resume=False,
        )
    )
    trained_manifest = _read_json(trained.manifest_path)
    assert trained_manifest["store_manifest_hash"] == patched_manifest_hash
    assert trained_manifest["row_count"] == _read_json(
        changed.manifest_path
    )["row_count"]


def test_carry_change_invalidates_later_year_shared_numeric_blocks(
    tmp_path: Path,
) -> None:
    baseline_raw = _build_raw(tmp_path / "carry-baseline")
    changed_raw = _build_raw(tmp_path / "carry-changed", changed_year=2022)
    shared_root = tmp_path / "carry-registry"
    baseline = PortfolioMLDirectNumericStoreBuilder().build(
        _direct_request(
            baseline_raw,
            output_root=tmp_path / "direct-carry-baseline",
            shared_root=shared_root,
        )
    )
    changed = PortfolioMLDirectNumericStoreBuilder().build(
        _direct_request(
            changed_raw,
            output_root=tmp_path / "direct-carry-changed",
            shared_root=shared_root,
        )
    )
    baseline_years = _years_by_year(baseline)
    changed_years = _years_by_year(changed)
    assert changed_years[2022]["shared_artifact_publication"].get(
        "reuse_before_build", False
    ) is False
    assert changed_years[2023]["shared_artifact_publication"].get(
        "reuse_before_build", False
    ) is False
    # The bounded 20-event carry is naturally aged out by the complete 2023
    # shard, so the later 2024 year can become reusable again.
    assert changed_years[2024]["shared_artifact_publication"].get(
        "reuse_before_build", False
    ) is True
    assert _artifact_hashes(changed_years[2023]) != _artifact_hashes(
        baseline_years[2023]
    )
    assert _artifact_hashes(changed_years[2024]) == _artifact_hashes(
        baseline_years[2024]
    )
    baseline_semantic = dict(
        baseline_years[2023]["shared_year_descriptor"]["block_reference"][
            "key"
        ]["source_manifest_hashes"]
    )
    changed_semantic = dict(
        changed_years[2023]["shared_year_descriptor"]["block_reference"][
            "key"
        ]["source_manifest_hashes"]
    )
    assert baseline_semantic["direct:carry-input"] != changed_semantic[
        "direct:carry-input"
    ]


def test_sector_custody_change_invalidates_all_annual_shared_blocks(
    tmp_path: Path,
) -> None:
    raw = _build_raw(tmp_path / "sector-source")
    first_sector = tmp_path / "sector-first.json"
    second_sector = tmp_path / "sector-second.json"
    _write_sector_membership_sidecar(
        first_sector,
        [_sector_membership_row(symbol="2330", sector_id="SEMI")],
    )
    _write_sector_membership_sidecar(
        second_sector,
        [_sector_membership_row(symbol="2330", sector_id="OTHER")],
    )
    shared_root = tmp_path / "sector-registry"
    baseline = PortfolioMLDirectNumericStoreBuilder().build(
        _direct_request(
            raw,
            output_root=tmp_path / "direct-sector-baseline",
            shared_root=shared_root,
            sector_path=first_sector,
        )
    )
    changed = PortfolioMLDirectNumericStoreBuilder().build(
        _direct_request(
            raw,
            output_root=tmp_path / "direct-sector-changed",
            shared_root=shared_root,
            sector_path=second_sector,
        )
    )
    baseline_years = _years_by_year(baseline)
    changed_years = _years_by_year(changed)
    assert all(
        year_manifest["shared_artifact_publication"].get(
            "reuse_before_build", False
        )
        is False
        for year_manifest in changed_years.values()
    )
    baseline_key = baseline_years[2022]["shared_year_descriptor"][
        "block_reference"
    ]["key"]
    changed_key = changed_years[2022]["shared_year_descriptor"][
        "block_reference"
    ]["key"]
    baseline_sources = dict(baseline_key["source_manifest_hashes"])
    changed_sources = dict(changed_key["source_manifest_hashes"])
    assert baseline_sources["direct:sector-membership"] != changed_sources[
        "direct:sector-membership"
    ]


def test_moved_shared_registry_and_tamper_are_verified(
    tmp_path: Path,
) -> None:
    raw = _build_raw(tmp_path / "move-source")
    shared_root = tmp_path / "move-registry"
    publication = PortfolioMLDirectNumericStoreBuilder().build(
        _direct_request(
            raw,
            output_root=tmp_path / "move-direct",
            shared_root=shared_root,
        )
    )
    moved_root = tmp_path / "moved-registry"
    shutil.copytree(shared_root, moved_root)
    moved_store = _NumericStore(
        publication.manifest_path,
        shared_numeric_store_root=moved_root,
    )
    refs = np.asarray([[0, 0]], dtype=np.int64)
    expected = moved_store.read_target_batch(refs)
    assert expected.shape[0] == 1

    artifact = next(
        item
        for item in moved_store.manifest["years"][0]["artifacts"]
        if item["artifact_id"] == "targets.i32"
    )
    object_path = moved_root / str(
        artifact["block_reference"]["object"]["path"]
    )
    with object_path.open("ab") as stream:
        stream.write(b"tamper")
    try:
        _NumericStore(
            publication.manifest_path,
            shared_numeric_store_root=moved_root,
        )
    except ValueError as exc:
        assert "hash" in str(exc)
    else:
        raise AssertionError("tampered shared artifact was accepted")

    # Resume still uses the immutable references and does not rewrite the
    # published objects or local year payloads.
    before = _directory_bytes(shared_root)
    replay = PortfolioMLDirectNumericStoreBuilder().build(
        replace(
            _direct_request(
                raw,
                output_root=tmp_path / "move-direct",
                shared_root=shared_root,
            ),
            resume=True,
        )
    )
    assert replay.manifest_hash == publication.manifest_hash
    assert _directory_bytes(shared_root) == before
