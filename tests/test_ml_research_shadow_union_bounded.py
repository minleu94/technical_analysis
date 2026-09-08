from __future__ import annotations

import sqlite3
from functools import wraps
from pathlib import Path
import tempfile

import pytest

import data_module.ml_research_shadow_union_bounded as bounded
from data_module.ml_research_shadow_union_bounded import (
    _capacity_checkpoint,
    _source_snapshot,
)
from data_module.ml_storage_capacity import MLStorageCapacityBudget, StorageCapacityError
from data_module.portfolio_ml_dataset_assembler import (
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
)
from tests.test_portfolio_ml_dataset_assembler import _raw_publication


def _source_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            'CREATE TABLE "daily_prices" '
            '("證券代號" TEXT NOT NULL, "日期" TEXT NOT NULL, "收盤價" INTEGER)'
        )
        connection.executemany(
            'INSERT INTO "daily_prices" VALUES (?, ?, ?)',
            [("2330", "2026-05-19", 100), ("2317", "2026-05-19", 90)],
        )
        connection.commit()
    finally:
        connection.close()


def _small_budget(*, persistent: int = 1024 * 1024) -> MLStorageCapacityBudget:
    return MLStorageCapacityBudget(
        persistent_new_bytes_budget=persistent,
        temporary_peak_bytes_budget=1024 * 1024,
        safety_reserve_bytes=1,
    )


def test_source_snapshot_records_selected_rows_and_rejects_tampered_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source.sqlite"
    _source_db(database)
    monkeypatch.setattr(bounded, "_SOURCE_TABLES", ("daily_prices",))
    output_root = tmp_path / "output"

    snapshot, lineage = _source_snapshot(
        database_path=database,
        output_root=output_root,
        symbols=("2317", "2330"),
        batch_size=1,
        budget=_small_budget(),
        baseline_bytes=0,
    )

    assert snapshot.is_file()
    assert lineage["read_only_source"] is True
    assert lineage["source_sidecar_stats"]["main"]["size_bytes"] > 0
    assert lineage["copied_row_counts"] == {"daily_prices": 2}
    assert lineage["selected_source_row_hashes"]["daily_prices"].startswith(
        "sha256:"
    )

    snapshot.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="content hash mismatch"):
        _source_snapshot(
            database_path=database,
            output_root=output_root,
            symbols=("2317", "2330"),
            batch_size=1,
            budget=_small_budget(),
            baseline_bytes=0,
        )


def test_source_snapshot_checks_projected_batch_before_write_and_cleans_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source.sqlite"
    _source_db(database)
    monkeypatch.setattr(bounded, "_SOURCE_TABLES", ("daily_prices",))
    output_root = tmp_path / "output"

    with pytest.raises(StorageCapacityError, match="persistent budget exceeded"):
        _source_snapshot(
            database_path=database,
            output_root=output_root,
            symbols=("2317", "2330"),
            batch_size=2,
            budget=_small_budget(persistent=1),
            baseline_bytes=0,
        )

    source_dir = output_root / "source_snapshots"
    assert not list(source_dir.glob("source-*.sqlite"))
    assert not list(source_dir.glob("*.tmp"))


def test_source_snapshot_rejects_external_wal_commit_during_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "source.sqlite"
    _source_db(database)
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.commit()
    writer.close()
    monkeypatch.setattr(bounded, "_SOURCE_TABLES", ("daily_prices",))
    original_copy = bounded._copy_table
    committed = False

    @wraps(original_copy)
    def copy_with_external_commit(*args: object, **kwargs: object) -> tuple[int, str]:
        nonlocal committed
        after_write = kwargs.get("after_write")

        def after(table: str) -> None:
            nonlocal committed
            if callable(after_write):
                after_write(table)
            if not committed:
                external = sqlite3.connect(database)
                try:
                    external.execute(
                        'INSERT INTO "daily_prices" VALUES (?, ?, ?)',
                        ("2330", "2026-05-20", 101),
                    )
                    external.commit()
                finally:
                    external.close()
                committed = True

        kwargs["after_write"] = after
        return original_copy(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(bounded, "_copy_table", copy_with_external_commit)
    with pytest.raises(RuntimeError, match="source changed"):
        _source_snapshot(
            database_path=database,
            output_root=tmp_path / "output",
            symbols=("2330",),
            batch_size=1,
            budget=_small_budget(),
            baseline_bytes=0,
        )


def test_capacity_checkpoint_counts_existing_temp_before_new_stage(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    temporary_root = output_root / ".tmp"
    temporary_root.mkdir(parents=True)
    (temporary_root / "orphan.sqlite").write_bytes(b"x" * 2048)

    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=1024 * 1024,
        temporary_peak_bytes_budget=1024,
        safety_reserve_bytes=1,
    )
    with pytest.raises(StorageCapacityError, match="temporary budget exceeded"):
        _capacity_checkpoint(
            output_root=output_root,
            baseline_bytes=0,
            budget=budget,
            temporary_path=temporary_root,
            stage="test_existing_temp",
        )


@pytest.mark.usefixtures("synthetic_ml_capacity")
def test_assembler_capacity_callback_stops_after_observed_spool_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_publication(tmp_path)
    output_root = tmp_path / "training"
    # 使用本測試專屬 TEMP；不可掃描全域 TEMP，否則其他 run 的殘留 spool
    # 可能令測試在 assembler 尚未寫入第一批資料時就停止。
    isolated_temp = tmp_path / "isolated-temp"
    isolated_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(isolated_temp))
    observed: list[tuple[str, int]] = []
    successful_raw_batches: list[tuple[str, int]] = []
    failed: tuple[str, int, dict[str, object]] | None = None
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=8 * 1024 * 1024,
        temporary_peak_bytes_budget=256 * 1024,
        safety_reserve_bytes=1,
    )

    def _spool_size() -> int:
        return sum(
            int(path.stat().st_size)
            for path in isolated_temp.rglob("*")
            if path.is_file()
        )

    def check_capacity(stage: str) -> None:
        nonlocal failed
        size = _spool_size()
        observed.append((stage, size))
        # schema 建立階段可通過；之後每一批都以真實目錄使用量執行
        # bounded checkpoint，不能用「檔案只要存在」冒充 growth。
        _capacity_checkpoint(
            output_root=output_root,
            baseline_bytes=0,
            budget=budget,
            temporary_path=isolated_temp,
            stage=stage,
        )
        if stage.startswith("raw_spool_observations_batch_written"):
            successful_raw_batches.append((stage, size))

    with pytest.raises(StorageCapacityError, match="temporary budget exceeded"):
        try:
            PortfolioMLDatasetAssembler().build(
                PortfolioMLDatasetAssemblyRequest(
                    dataset_manifest_path=raw.dataset_manifest_paths[
                        "all_field_enriched"
                    ],
                    output_root=output_root,
                    training_as_of="2024-09-01T08:30:00+08:00",
                    benchmark_entity_id="TAIEX",
                    batch_size=1,
                    minimum_train_dates=65,
                    test_date_count=21,
                    purge_trading_days=60,
                    embargo_trading_days=5,
                    capacity_callback=check_capacity,
                )
            )
        except StorageCapacityError as exc:
            if observed:
                last_stage, last_size = observed[-1]
                failed = (last_stage, last_size, dict(exc.preflight))
            raise

    assert successful_raw_batches
    assert failed is not None
    failed_stage, failed_size, failed_preflight = failed
    assert failed_stage.startswith("raw_spool_")
    assert failed_size > successful_raw_batches[0][1]
    assert failed_size > 0
    assert failed_preflight["temporary_bytes"] == failed_size
    assert not tuple(output_root.glob(".portfolio-ml-*"))
    # assembler 的 exception cleanup 應清掉本次專屬 spool；isolated temp
    # 本身保留，方便確認沒有誤掃或清除其他測試的檔案。
    assert not tuple(isolated_temp.glob("baldr-portfolio-ml-spool-*"))
