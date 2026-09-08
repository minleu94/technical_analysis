from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, cast

import pytest

from data_module.ml_pit_shared_block_resolver import (
    build_shared_pit_publication,
    load_shared_pit_publication,
    resolve_pit_shard_record,
)
from data_module.portfolio_ml_dataset_assembler import (
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
    _base_feature_definitions,
    _initialize_spool,
)
from data_module import portfolio_ml_direct_numeric_store as direct_store_module
from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from ml_module.allocation_out_of_core_training_service import (
    AllocationOutOfCoreTrainingRequest,
    AllocationOutOfCoreTrainingService,
)
from tests.test_portfolio_ml_dataset_assembler import _database
from tests.test_portfolio_ml_out_of_core_pipeline import _long_raw_publication
from tests.ml_teacher_fixture import attach_synthetic_teacher_provenance


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha256_json(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(raw)


def _prepare_multi_year_database(path: Path, *, change_2024: bool) -> None:
    _database(path)
    with sqlite3.connect(path) as connection:
        daily_rows = connection.execute("SELECT * FROM daily_prices").fetchall()
        market_rows = connection.execute("SELECT * FROM market_indices").fetchall()
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [("2023" + str(row[0])[4:], *row[1:]) for row in daily_rows],
        )
        connection.executemany(
            "INSERT INTO market_indices VALUES (?, ?, ?, ?, ?, ?)",
            [("2023" + str(row[0])[4:], *row[1:]) for row in market_rows],
        )
        if change_2024:
            connection.execute(
                "UPDATE daily_prices SET 收盤價 = ? "
                "WHERE 日期 = ? AND 證券代號 = ?",
                ("999.99", "20240101", "2317"),
            )


def _multi_year_raw_publications(tmp_path: Path):
    first_database = tmp_path / "source-first.db"
    second_database = tmp_path / "source-second.db"
    _prepare_multi_year_database(first_database, change_2024=False)
    _prepare_multi_year_database(second_database, change_2024=True)
    first = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=first_database,
            output_root=tmp_path / "raw-first",
            decision_at="2025-01-01T08:30:00+08:00",
            history_start_date="2023-01-01",
            symbols=("2317", "2330"),
            years=(2023, 2024),
            batch_size=31,
        )
    )
    second = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=second_database,
            output_root=tmp_path / "raw-second",
            decision_at="2025-01-01T08:30:00+08:00",
            history_start_date="2023-01-01",
            symbols=("2317", "2330"),
            years=(2023, 2024),
            batch_size=31,
        )
    )
    return first, second


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _assembler_spool_snapshot(
    *,
    dataset_manifest_path: Path,
    dataset_manifest: dict[str, object],
    shared_store_root: Path | None,
) -> tuple[tuple[int, int], str, int, int]:
    connection = sqlite3.connect(":memory:")
    try:
        _initialize_spool(connection)
        definitions = _base_feature_definitions(dataset_manifest)
        digest = hashlib.sha256()
        counts = PortfolioMLDatasetAssembler()._spool_raw_observations(
            connection=connection,
            dataset_manifest_path=dataset_manifest_path,
            manifest=dataset_manifest,
            definitions=definitions,
            source_digest=digest,
            batch_size=17,
            shared_block_store_root=shared_store_root,
        )
        observation_count = int(
            connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        )
        price_count = int(
            connection.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        )
        return counts, digest.hexdigest(), observation_count, price_count
    finally:
        connection.close()


def test_legacy_local_manifest_resolves_without_shared_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, _changed_raw = _multi_year_raw_publications(tmp_path)
    dataset_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    dataset_manifest = _read_json(dataset_manifest_path)
    shards = dataset_manifest["shards"]
    assert isinstance(shards, list) and shards
    monkeypatch.setattr(
        "data_module.ml_pit_shared_block_resolver.gzip.decompress",
        lambda _raw: pytest.fail("content hash must stream gzip bytes"),
    )
    resolved = resolve_pit_shard_record(
        record=shards[0],
        publication_root=dataset_manifest_path.parent.parent,
    )
    assert resolved.shared is False
    assert resolved.path.is_relative_to(dataset_manifest_path.parent.parent)
    assert resolved.read_bytes()


def test_real_pit_publications_reuse_unchanged_shards_and_add_changed_one(
    tmp_path: Path,
) -> None:
    raw, changed_raw = _multi_year_raw_publications(tmp_path)
    dataset_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    source_before = dataset_manifest_path.read_bytes()
    shared_root = tmp_path / "shared-registry"
    derived_root = tmp_path / "derived-shared-pit"

    first = build_shared_pit_publication(
        dataset_manifest_path=dataset_manifest_path,
        shared_store_root=shared_root,
        output_root=derived_root,
    )
    first_store_bytes = sum(
        path.stat().st_size
        for path in shared_root.rglob("*")
        if path.is_file()
    )
    assert first.shard_count == 2
    assert len(load_shared_pit_publication(
        manifest_path=first.manifest_path,
        shared_store_root=shared_root,
    )) == first.shard_count
    first_objects = {
        str(result["object_hash"]) for result in first.block_results
    }
    assert all(
        not Path(str(result["block_reference"]["object"]["path"])).is_absolute()
        for result in first.block_results
    )
    assert dataset_manifest_path.read_bytes() == source_before

    mutated_dataset_manifest_path = changed_raw.dataset_manifest_paths[
        "all_field_enriched"
    ]
    second = build_shared_pit_publication(
        dataset_manifest_path=mutated_dataset_manifest_path,
        shared_store_root=shared_root,
        output_root=derived_root,
    )
    second_store_bytes = sum(
        path.stat().st_size
        for path in shared_root.rglob("*")
        if path.is_file()
    )
    statuses = [str(result["status"]) for result in second.block_results]
    assert statuses.count("immutable_block_reused") == 1
    assert statuses.count("immutable_block_created") == 1
    second_objects = {
        str(result["object_hash"]) for result in second.block_results
    }
    assert len(second_objects - first_objects) == 1
    assert second_store_bytes > first_store_bytes
    assert len(list((shared_root / "objects" / "sha256").glob("*.blob"))) == 3
    resolved = load_shared_pit_publication(
        manifest_path=second.manifest_path,
        shared_store_root=shared_root,
    )
    assert all(item.shared for item in resolved)
    assert all(item.read_bytes() for item in resolved)

    rerun = build_shared_pit_publication(
        dataset_manifest_path=mutated_dataset_manifest_path,
        shared_store_root=shared_root,
        output_root=derived_root,
    )
    assert [str(result["status"]) for result in rerun.block_results] == [
        "immutable_block_reused",
        "immutable_block_reused",
    ]
    assert second.manifest_path.read_bytes() == rerun.manifest_path.read_bytes()
    assert second_store_bytes == sum(
        path.stat().st_size
        for path in shared_root.rglob("*")
        if path.is_file()
    )


def test_assembler_consumes_shared_dataset_view_without_local_shard_bytes(
    tmp_path: Path,
) -> None:
    raw, _changed_raw = _multi_year_raw_publications(tmp_path)
    source_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    source_manifest = _read_json(source_manifest_path)
    shared_root = tmp_path / "shared-registry"
    derived_root = tmp_path / "derived-shared-pit"
    shared = build_shared_pit_publication(
        dataset_manifest_path=source_manifest_path,
        shared_store_root=shared_root,
        output_root=derived_root,
    )
    shared_manifest = _read_json(shared.dataset_manifest_path)
    shared_shards = shared_manifest["shards"]
    assert isinstance(shared_shards, list) and shared_shards
    assert all(
        isinstance(shard, dict)
        and "block_reference" in shard
        and "path" not in shard
        for shard in shared_shards
    )

    local_snapshot = _assembler_spool_snapshot(
        dataset_manifest_path=source_manifest_path,
        dataset_manifest=source_manifest,
        shared_store_root=None,
    )
    # 移除 producer 的 run-local publication 後仍能消費 shared object，
    # 證明 assembler 沒有 fallback 讀取原始 gzip。
    shutil.rmtree(raw.publication_directory)
    shared_snapshot = _assembler_spool_snapshot(
        dataset_manifest_path=shared.dataset_manifest_path,
        dataset_manifest=shared_manifest,
        shared_store_root=shared_root,
    )
    assert shared_snapshot == local_snapshot

    publication = PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=shared.dataset_manifest_path,
            output_root=tmp_path / "training-from-shared",
            training_as_of="2024-09-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            minimum_train_dates=65,
            test_date_count=21,
            purge_trading_days=60,
            embargo_trading_days=5,
            batch_size=29,
            shared_block_store_root=shared_root,
        )
    )
    assert publication.sample_count > 0
    output_manifest = json.loads(
        publication.manifest_path.read_text(encoding="utf-8")
    )
    assert output_manifest["direct_training_input"] is True


@pytest.mark.parametrize(
    ("field_name", "bad_value", "message"),
    (
        (
            "schema_version",
            "ml-immutable-block-store.v0",
            "block store schema",
        ),
        (
            "feature_contract_hash",
            "sha256:" + ("f" * 64),
            "feature contract hash",
        ),
    ),
)
def test_assembler_rejects_shared_view_schema_or_semantic_tampering(
    tmp_path: Path,
    field_name: str,
    bad_value: str,
    message: str,
) -> None:
    raw, _changed_raw = _multi_year_raw_publications(tmp_path)
    source_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    shared_root = tmp_path / "shared-registry"
    shared = build_shared_pit_publication(
        dataset_manifest_path=source_manifest_path,
        shared_store_root=shared_root,
        output_root=tmp_path / "derived-shared-pit",
    )
    tampered = _read_json(shared.dataset_manifest_path)
    shared_contract = tampered["shared_block_store"]
    assert isinstance(shared_contract, dict)
    shared_contract[field_name] = bad_value
    tampered.pop("manifest_hash", None)
    tampered["manifest_hash"] = _sha256_json(tampered)
    tampered_path = tmp_path / "tampered" / "manifest.json"
    tampered_path.parent.mkdir(parents=True)
    tampered_path.write_text(
        json.dumps(tampered, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=message):
        _assembler_spool_snapshot(
            dataset_manifest_path=tampered_path,
            dataset_manifest=tampered,
            shared_store_root=shared_root,
        )
    with pytest.raises(ValueError, match=message):
        PortfolioMLDatasetAssembler().build(
            PortfolioMLDatasetAssemblyRequest(
                dataset_manifest_path=tampered_path,
                output_root=tmp_path / "tampered-training",
                training_as_of="2025-01-01T08:30:00+08:00",
                benchmark_entity_id="TAIEX",
                minimum_train_dates=65,
                test_date_count=21,
                purge_trading_days=60,
                embargo_trading_days=5,
                batch_size=31,
                shared_block_store_root=shared_root,
            )
        )


def test_direct_discovery_consumes_shared_view_after_local_publication_removed(
    tmp_path: Path,
) -> None:
    raw, _changed_raw = _multi_year_raw_publications(tmp_path)
    source_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    shared_root = tmp_path / "shared-registry"
    shared = build_shared_pit_publication(
        dataset_manifest_path=source_manifest_path,
        shared_store_root=shared_root,
        output_root=tmp_path / "derived-shared-pit",
    )
    shutil.rmtree(raw.publication_directory)
    shared_manifest = _read_json(shared.dataset_manifest_path)
    shared_contract = direct_store_module.legacy._validate_shared_block_dataset_manifest(
        shared_manifest
    )
    assert shared_contract is not None
    discovery = direct_store_module._discover(
        raw_manifest_path=shared.dataset_manifest_path,
        raw_manifest=shared_manifest,
        cutoff=direct_store_module.legacy._available_datetime(
            "2025-01-01T08:30:00+08:00",
            field_name="training_as_of",
        ),
        benchmark_entity_id="TAIEX",
        minimum_train_dates=65,
        test_date_count=21,
        purge_trading_days=60,
        embargo_trading_days=5,
        shared_block_store_root=shared_root,
        shared_contract=shared_contract,
    )
    assert len(discovery.shard_by_year) == 2
    assert len(discovery.fold_windows) >= 4


def test_public_direct_builder_reads_shared_view_and_replays_full_manifest(
    tmp_path: Path,
) -> None:
    """公用 Direct builder 必須直接消費 shared shard 並完成 readback。"""

    # 使用既有 bounded 三年度來源，讓所有公開 fold index 都有實際 train/test
    # rows；這仍是隔離 fixture，不會觸碰正式 Direct/OOC 父產物。
    raw = _long_raw_publication(tmp_path)
    source_manifest_path = raw.dataset_manifest_paths["all_field_enriched"]
    shared_root = tmp_path / "shared-registry"
    shared = build_shared_pit_publication(
        dataset_manifest_path=source_manifest_path,
        shared_store_root=shared_root,
        output_root=tmp_path / "derived-shared-pit",
    )
    # 這個 bounded run 只保留不可變 shared objects；Direct 公用入口不能
    # 回退讀取 producer 的 run-local gzip。
    shutil.rmtree(raw.publication_directory)

    request = direct_store_module.PortfolioMLDirectNumericRequest(
        raw_manifest_path=shared.dataset_manifest_path,
        output_root=tmp_path / "direct-from-shared",
        training_as_of="2026-04-01T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        minimum_train_dates=65,
        test_date_count=65,
        purge_trading_days=60,
        embargo_trading_days=5,
        batch_size=31,
        workers=1,
        memory_budget_mb=1_024,
        resume=False,
        shared_block_store_root=shared_root,
    )
    publication = direct_store_module.PortfolioMLDirectNumericStoreBuilder().build(
        request
    )
    manifest = cast(dict[str, Any], _read_json(publication.manifest_path))
    assert publication.manifest_path.is_file()
    assert manifest["status"] == "complete"
    assert manifest["execution"]["direct_numeric_store"] is True
    assert manifest["execution"]["direct_store_complete"] is True
    assert manifest["execution"]["full_period_observation_sqlite"] is False
    assert manifest["execution"]["training_jsonl_intermediate"] is False
    assert manifest["store_identity"]["direct_identity"][
        "shared_block_store_mode"
    ] == "content_addressed"
    assert manifest["dataset_manifest_file_hash"] == (
        direct_store_module._file_sha256(shared.dataset_manifest_path)
    )
    assert int(manifest["row_count"]) > 0
    assert int(manifest["fold_count"]) >= 4

    # Verify actual numeric artifacts and every annual/fold manifest before
    # testing idempotent public readback.
    run_files_before = {
        path.relative_to(publication.run_directory).as_posix():
        direct_store_module._file_sha256(path)
        for path in publication.run_directory.rglob("*")
        if path.is_file()
        and path.name != "heartbeat.json"
    }
    year_manifests = manifest["years"]
    assert isinstance(year_manifests, list) and year_manifests
    for year_manifest in year_manifests:
        year = int(year_manifest["year"])
        year_directory = publication.run_directory / f"year={year:04d}"
        assert year_directory.is_dir()
        assert int(year_manifest["row_count"]) > 0
        artifacts = year_manifest["artifacts"]
        assert isinstance(artifacts, list) and artifacts
        for artifact in artifacts:
            artifact_path = year_directory / str(artifact["path"])
            assert artifact_path.is_file()
            assert direct_store_module._file_sha256(artifact_path) == (
                artifact["file_sha256"]
            )
    folds = manifest["folds"]
    assert isinstance(folds, list) and folds
    for fold_manifest in folds:
        fold_directory = publication.run_directory / "folds"
        for split in ("train", "test"):
            split_manifest = fold_manifest[split]
            split_path = fold_directory / str(split_manifest["path"])
            assert split_path.is_file()
            assert direct_store_module._file_sha256(split_path) == (
                split_manifest["file_sha256"]
            )

    replay = direct_store_module.PortfolioMLDirectNumericStoreBuilder().build(
        replace(request, resume=True)
    )
    assert replay.run_id == publication.run_id
    assert replay.manifest_hash == publication.manifest_hash
    assert replay.manifest_file_hash == publication.manifest_file_hash
    run_files_after = {
        path.relative_to(replay.run_directory).as_posix():
        direct_store_module._file_sha256(path)
        for path in replay.run_directory.rglob("*")
        if path.is_file()
        and path.name != "heartbeat.json"
    }
    assert run_files_after == run_files_before
    assert _read_json(replay.run_directory / "heartbeat.json")["status"] == (
        "complete"
    )
    latest = _read_json(replay.latest_manifest_path)
    assert latest["run_id"] == publication.run_id
    assert latest["manifest_hash"] == publication.manifest_hash

    # OOC 下游只依賴 direct numeric manifest；共享 PIT object 不應被複製
    # 到 training output，但 source store identity/hash 必須完整向下綁定。
    patched_manifest_hash = attach_synthetic_teacher_provenance(
        publication.manifest_path,
        fixture_root=tmp_path / "synthetic-teacher-provenance",
    )
    patched_manifest_file_hash = "sha256:" + hashlib.sha256(
        publication.manifest_path.read_bytes()
    ).hexdigest()
    training_request = AllocationOutOfCoreTrainingRequest(
        store_manifest_path=publication.manifest_path,
        output_root=tmp_path / "ooc-from-shared-direct",
        algorithms=("ridge_logistic",),
        horizons=(5,),
        batch_size=512,
        workers=1,
        memory_budget_mb=1_024,
        logistic_iterations=2,
        resume=False,
    )
    trained = AllocationOutOfCoreTrainingService().train(training_request)
    training_manifest = cast(
        dict[str, Any], _read_json(trained.manifest_path)
    )
    assert training_manifest["store_manifest_hash"] == patched_manifest_hash
    assert training_manifest["store_manifest_file_hash"] == (
        patched_manifest_file_hash
    )
    assert training_manifest["row_count"] == manifest["row_count"]
    assert training_manifest["feature_count"] == manifest["feature_count"]
    assert training_manifest["fold_count"] == manifest["fold_count"]
    assert training_manifest["formal_oos_allowed"] is False
    assert training_manifest["production_alpha_bp"] == 0
    assert training_manifest["promotion"]["promotion_eligible"] is False

    training_files_before = {
        path.relative_to(trained.run_directory).as_posix():
        direct_store_module._file_sha256(path)
        for path in trained.run_directory.rglob("*")
        if path.is_file()
    }
    training_replay = AllocationOutOfCoreTrainingService().train(
        replace(training_request, resume=True)
    )
    assert training_replay.run_id == trained.run_id
    assert training_replay.manifest_hash == trained.manifest_hash
    assert training_replay.manifest_file_hash == trained.manifest_file_hash
    training_files_after = {
        path.relative_to(training_replay.run_directory).as_posix():
        direct_store_module._file_sha256(path)
        for path in training_replay.run_directory.rglob("*")
        if path.is_file()
    }
    assert training_files_after == training_files_before
