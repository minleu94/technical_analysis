from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from data_module import portfolio_ml_direct_numeric_store as direct_store_module
from data_module.portfolio_ml_dataset_assembler import (
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
)
from data_module.portfolio_ml_direct_numeric_store import (
    PortfolioMLDirectNumericRequest,
    PortfolioMLDirectNumericStoreBuilder,
)
from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.portfolio_ml_out_of_core_store import (
    PortfolioMLOutOfCoreStoreBuilder,
    PortfolioMLOutOfCoreStoreRequest,
)
from data_module.portfolio_ml_raw_to_ooc_pipeline import (
    PortfolioMLRawToOOCBuilder,
    PortfolioMLRawToOOCRequest,
)
from ml_module.allocation_out_of_core_training_service import (
    AllocationOutOfCoreTrainingRequest,
    AllocationOutOfCoreTrainingService,
    _LinearBoundaryModel,
    _NumericStore,
    _PeakRSSMonitor,
    _feature_family_weights,
)
from ml_module.allocation_training_service import EXPERT_VECTOR_WIDTH
from tests.test_portfolio_ml_dataset_assembler import _database
from tests.test_portfolio_ml_dataset_assembler import (
    _official_corporate_action_publication,
    _raw_publication,
)


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class _BoundedE2E:
    raw_manifest_path: Path
    training_manifest_path: Path
    store_manifest_path: Path
    store_manifest_hash: str
    ridge_manifest_path: Path
    ridge_manifest_hash: str


def _long_raw_publication(root: Path):
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
def bounded_e2e(tmp_path_factory: pytest.TempPathFactory) -> _BoundedE2E:
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
    return _BoundedE2E(
        raw_manifest_path=raw_manifest_path,
        training_manifest_path=training.manifest_path,
        store_manifest_path=store.manifest_path,
        store_manifest_hash=store.manifest_hash,
        ridge_manifest_path=ridge.manifest_path,
        ridge_manifest_hash=ridge.manifest_hash,
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _logical_hash(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body.pop("manifest_hash", None)
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def test_store_resume_hash_coverage_and_memory_budget(
    bounded_e2e: _BoundedE2E,
) -> None:
    store = _read_json(bounded_e2e.store_manifest_path)
    training = _read_json(bounded_e2e.ridge_manifest_path)

    assert store["manifest_hash"] == bounded_e2e.store_manifest_hash
    assert store["execution"]["resume_supported"] is True
    assert store["execution"]["sample_python_objects_retained"] == 0
    assert store["execution"]["oof_python_objects_retained"] == 0
    assert store["feature_family_coverage"]
    assert all(
        isinstance(item["observed_count"], int)
        and isinstance(item["coverage_bp"], int)
        and 0 <= item["coverage_bp"] <= 10_000
        for item in store["feature_family_coverage"]
    )
    assert training["manifest_hash"] == bounded_e2e.ridge_manifest_hash
    assert training["execution"]["within_memory_budget"] is True
    assert (
        training["execution"]["peak_rss_bytes"]
        <= training["execution"]["memory_budget_mb"] * 1024 * 1024
    )
    with pytest.raises(ValueError, match="at least 256"):
        PortfolioMLOutOfCoreStoreRequest(
            training_manifest_path=bounded_e2e.training_manifest_path,
            output_root=bounded_e2e.store_manifest_path.parent,
            memory_budget_mb=255,
        )


def test_formal_and_research_overlay_are_fail_closed(
    bounded_e2e: _BoundedE2E,
    tmp_path: Path,
) -> None:
    research_manifest = _read_json(bounded_e2e.training_manifest_path)
    research_manifest["research_only"] = True
    research_manifest["promotion_eligible"] = False
    research_manifest["formal_consumer_compatible"] = False
    research_manifest["manifest_hash"] = _logical_hash(research_manifest)
    research_manifest_path = (
        bounded_e2e.training_manifest_path.parent
        / "research-shadow-manifest.json"
    )
    research_manifest_path.write_text(
        json.dumps(
            research_manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="research_only=false"):
        PortfolioMLOutOfCoreStoreBuilder().build(
            PortfolioMLOutOfCoreStoreRequest(
                training_manifest_path=research_manifest_path,
                output_root=tmp_path / "formal-reject",
                memory_budget_mb=1_024,
                lane="formal",
            )
        )
    research_store = PortfolioMLOutOfCoreStoreBuilder().build(
        PortfolioMLOutOfCoreStoreRequest(
            training_manifest_path=research_manifest_path,
            output_root=tmp_path / "research-store",
            batch_size=31,
            memory_budget_mb=256,
            lane="research_shadow",
        )
    )
    research_store_manifest = _read_json(research_store.manifest_path)
    assert research_store_manifest["formal_source_only"] is False
    assert research_store_manifest["research_only"] is True
    assert research_store_manifest["promotion_eligible"] is False
    with pytest.raises(ValueError, match="formal source only"):
        AllocationOutOfCoreTrainingService().train(
            AllocationOutOfCoreTrainingRequest(
                store_manifest_path=research_store.manifest_path,
                output_root=tmp_path / "formal-training-reject",
                algorithms=("ridge_logistic",),
                horizons=(5,),
                memory_budget_mb=256,
            )
        )


def test_base_oof_and_meta_use_only_prior_mature_folds(
    bounded_e2e: _BoundedE2E,
) -> None:
    manifest = _read_json(bounded_e2e.ridge_manifest_path)
    assert manifest["fold_count"] >= 4
    assert manifest["base_expert_count"] == (
        manifest["fold_count"] * len(manifest["feature_packs"])
    )
    assert manifest["meta_fold_count"] == manifest["fold_count"] - 1
    fold_order = [
        str(item["fold_id"])
        for item in _read_json(bounded_e2e.store_manifest_path)["folds"]
    ]
    for artifact in manifest["meta_folds"]:
        fold_position = fold_order.index(str(artifact["fold_id"]))
        assert artifact["training_source_fold_ids"] == fold_order[:fold_position]
        assert artifact["causal_prior_fold_oof_only"] is True
        assert (
            artifact["label_maturity_cutoff_exclusive"]
            == _read_json(bounded_e2e.store_manifest_path)["folds"][
                fold_position
            ]["test_start"]
        )
        assert artifact["oof_dtype"] == "<i4"
    for artifact in manifest["base_experts"]:
        fold_position = fold_order.index(str(artifact["fold_id"]))
        assert artifact["label_maturity_filter_applied_before_feature_fit"] is True
        assert (
            artifact["label_maturity_cutoff_exclusive"]
            == _read_json(bounded_e2e.store_manifest_path)["folds"][
                fold_position
            ]["test_start"]
        )
        assert artifact["raw_train_row_count"] >= artifact[
            "label_mature_train_row_count"
        ]
        assert artifact["label_maturity_excluded_row_count"] == (
            artifact["raw_train_row_count"]
            - artifact["label_mature_train_row_count"]
        )
    assert manifest["validation"]["pit_violation_count"] == 0
    assert manifest["validation"]["future_prefix_violation_count"] == 0


def test_hgb_fit_population_is_bounded_and_disclosed(
    bounded_e2e: _BoundedE2E,
    tmp_path: Path,
) -> None:
    publication = AllocationOutOfCoreTrainingService().train(
        AllocationOutOfCoreTrainingRequest(
            store_manifest_path=bounded_e2e.store_manifest_path,
            output_root=tmp_path / "hgb",
            algorithms=("hist_gradient_boosting",),
            horizons=(5,),
            batch_size=31,
            workers=1,
            memory_budget_mb=1_024,
            hgb_max_iter=1,
            hgb_max_fit_rows=16,
        )
    )
    manifest = _read_json(publication.manifest_path)
    assert manifest["base_experts"]
    assert manifest["final_base_experts"]
    for artifact in (
        manifest["base_experts"] + manifest["final_base_experts"]
    ):
        assert artifact["fit_population"] == (
            "deterministic_evenly_spaced_bounded_challenger_sample"
        )
        assert artifact["hgb_max_fit_rows"] == 16
        assert artifact["full_train_rows_fit"] is False
        assert all(
            head["fit_row_count"] <= 16
            for head in artifact["head_models"]
            if head["status"] == "fit"
        )


def test_zero_coverage_family_receives_zero_explanation_weight() -> None:
    expert_ids = ("observed|h5|ridge", "all_missing|h5|ridge")
    width = len(expert_ids) * EXPERT_VECTOR_WIDTH
    model = _LinearBoundaryModel(
        head_id="target_weight_bp",
        medians=np.zeros(width, dtype=np.float64),
        means=np.zeros(width, dtype=np.float64),
        standard_deviations=np.ones(width, dtype=np.float64),
        coefficients=np.ones(width, dtype=np.float64),
        intercept=0.0,
        classifier=False,
    )
    weights = dict(
        _feature_family_weights(
            expert_ids=expert_ids,
            models={"target_weight_bp": model},
            family_coverage_bp={"observed": 10_000, "all_missing": 0},
        )
    )
    assert weights == {"all_missing": 0, "observed": 10_000}


def test_raw_adapter_rejects_impossible_temporary_budget_before_writes(
    bounded_e2e: _BoundedE2E,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "raw-adapter"
    with pytest.raises(ValueError, match="compressed raw input lower bound"):
        PortfolioMLRawToOOCBuilder().build(
            PortfolioMLRawToOOCRequest(
                raw_manifest_path=bounded_e2e.raw_manifest_path,
                output_root=output_root,
                training_as_of="2026-04-01T08:30:00+08:00",
                benchmark_entity_id="TAIEX",
                minimum_train_dates=65,
                test_date_count=65,
                purge_trading_days=60,
                embargo_trading_days=5,
                batch_size=29,
                memory_budget_mb=256,
                temporary_storage_budget_bytes=1,
            )
        )
    manifests = tuple(output_root.rglob("manifest.json"))
    assert not manifests


def test_transitional_raw_adapter_binds_corporate_action_custody(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    official = _official_corporate_action_publication(tmp_path)
    request = PortfolioMLRawToOOCRequest(
        raw_manifest_path=raw.dataset_manifest_paths["all_field_enriched"],
        output_root=tmp_path / "raw-adapter-corporate",
        training_as_of="2024-09-01T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        corporate_action_manifest_path=official.manifest_path,
        minimum_train_dates=65,
        test_date_count=21,
        purge_trading_days=60,
        embargo_trading_days=5,
        batch_size=29,
        memory_budget_mb=256,
    )
    publication = PortfolioMLRawToOOCBuilder().build(request)
    replay = PortfolioMLRawToOOCBuilder().build(request)
    pipeline = _read_json(publication.manifest_path)
    training = _read_json(publication.training_manifest_path)

    assert replay.pipeline_id == publication.pipeline_id
    assert pipeline["execution"]["direct_numeric_store"] is False
    assert pipeline["execution"]["full_market_ready"] is False
    assert training["corporate_action_custody"]["manifest_hash"] == (
        official.manifest_hash
    )
    assert training["corporate_action_excluded_label_count"] > 0
    assert training["safety"][
        "corporate_action_affected_horizons_excluded"
    ] is True
    assert training["safety"][
        "post_event_corporate_action_used_as_feature"
    ] is False
    assert (
        "corporate_action_adjustment_timeline_not_in_raw_publication_"
        "labels_are_research_shadow"
        not in training["assembly_blockers"]
    )


def test_direct_annual_numeric_store_has_no_full_period_spool_or_jsonl(
    bounded_e2e: _BoundedE2E,
    tmp_path: Path,
) -> None:
    official = _official_corporate_action_publication(tmp_path)
    request = PortfolioMLDirectNumericRequest(
        raw_manifest_path=bounded_e2e.raw_manifest_path,
        output_root=tmp_path / "direct-store",
        training_as_of="2026-04-01T08:30:00+08:00",
        benchmark_entity_id="TAIEX",
        corporate_action_manifest_path=official.manifest_path,
        minimum_train_dates=65,
        test_date_count=65,
        purge_trading_days=60,
        embargo_trading_days=5,
        batch_size=61,
        workers=2,
        memory_budget_mb=1_024,
    )
    publication = PortfolioMLDirectNumericStoreBuilder().build(request)
    replay = PortfolioMLDirectNumericStoreBuilder().build(request)
    manifest = _read_json(publication.manifest_path)

    assert replay.run_id == publication.run_id
    assert replay.manifest_hash == publication.manifest_hash
    assert replay.manifest_file_hash == publication.manifest_file_hash
    assert manifest["execution"]["direct_numeric_store"] is True
    assert manifest["execution"]["direct_store_complete"] is True
    assert manifest["execution"]["full_market_scale_capable"] is True
    assert manifest["execution"]["full_market_ready"] is False
    assert (
        "causal_non_cash_portfolio_ledger_present"
        in manifest["execution"]["readiness_failed_checks"]
    )
    assert (
        "official_trade_restriction_timeline_present"
        in manifest["execution"]["readiness_failed_checks"]
    )
    assert (
        "formal_rule_champion_snapshot_history_present"
        in manifest["execution"]["readiness_failed_checks"]
    )
    assert manifest["execution"]["full_period_observation_sqlite"] is False
    assert manifest["execution"]["training_jsonl_intermediate"] is False
    assert manifest["execution"]["annual_atomic_checkpoint"] is True
    assert manifest["execution"]["peak_temporary_bytes"] > 0
    assert manifest["corporate_action_custody"]["manifest_hash"] == (
        official.manifest_hash
    )
    assert manifest["corporate_action_excluded_label_count"] > 0
    assert not tuple(publication.run_directory.glob(".work-year-*"))
    assert not tuple(publication.run_directory.rglob("assembly.sqlite"))
    assert not tuple(publication.run_directory.rglob("*.jsonl"))
    assert not tuple(publication.run_directory.rglob("*.jsonl.gz"))

    checkpoint_path = publication.run_directory / "checkpoint.json"
    checkpoint = _read_json(checkpoint_path)
    finalized_year = checkpoint["completed_years"].pop()
    checkpoint["complete"] = False
    checkpoint.pop("manifest_hash", None)
    checkpoint.pop("manifest_file_hash", None)
    checkpoint_path.write_text(
        json.dumps(
            checkpoint,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    publication.manifest_path.unlink()
    adopted = PortfolioMLDirectNumericStoreBuilder().build(request)
    adopted_checkpoint = _read_json(checkpoint_path)
    assert adopted.run_id == publication.run_id
    assert finalized_year in adopted_checkpoint["completed_years"]
    assert adopted_checkpoint["complete"] is True

    trained = AllocationOutOfCoreTrainingService().train(
        AllocationOutOfCoreTrainingRequest(
            store_manifest_path=publication.manifest_path,
            output_root=tmp_path / "direct-training",
            algorithms=("ridge_logistic",),
            horizons=(5,),
            batch_size=61,
            workers=2,
            memory_budget_mb=1_024,
            logistic_iterations=2,
        )
    )
    trained_manifest = _read_json(trained.manifest_path)
    assert trained_manifest["base_expert_count"] == (
        manifest["fold_count"] * len(manifest["feature_packs"])
    )
    assert trained_manifest["meta_fold_count"] == (
        manifest["fold_count"] - 1
    )
    assert trained_manifest["promotion"]["production_alpha_bp"] == 0


def test_direct_numeric_preflight_rejects_low_temporary_budget(
    bounded_e2e: _BoundedE2E,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "direct-low-temp"
    with pytest.raises(
        ValueError,
        match="conservative annual workspace estimate",
    ):
        PortfolioMLDirectNumericStoreBuilder().build(
            PortfolioMLDirectNumericRequest(
                raw_manifest_path=bounded_e2e.raw_manifest_path,
                output_root=output_root,
                training_as_of="2026-04-01T08:30:00+08:00",
                benchmark_entity_id="TAIEX",
                minimum_train_dates=65,
                test_date_count=65,
                purge_trading_days=60,
                embargo_trading_days=5,
                batch_size=61,
                # 此案例只驗 temporary-storage preflight；完整 suite 先載入
                # Qt/sklearn 後 process RSS 可能已超過 256 MiB，不能讓不相干
                # 的 memory guard 搶先失敗。
                memory_budget_mb=1_024,
                temporary_storage_budget_bytes=1,
            )
        )
    assert not tuple(output_root.rglob("manifest.json"))


def test_formal_store_rejects_missing_lane_markers(
    bounded_e2e: _BoundedE2E,
    tmp_path: Path,
) -> None:
    manifest = _read_json(bounded_e2e.training_manifest_path)
    for missing_field in (
        "research_only",
        "formal_consumer_compatible",
        "research_shadow_included",
        "formal_source_only",
        "promotion_eligible",
    ):
        poisoned = dict(manifest)
        poisoned.pop(missing_field)
        poisoned["manifest_hash"] = _logical_hash(poisoned)
        poisoned_path = (
            bounded_e2e.training_manifest_path.parent
            / f"missing-{missing_field}.json"
        )
        poisoned_path.write_text(
            json.dumps(
                poisoned,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=missing_field):
            PortfolioMLOutOfCoreStoreBuilder().build(
                PortfolioMLOutOfCoreStoreRequest(
                    training_manifest_path=poisoned_path,
                    output_root=tmp_path / f"reject-{missing_field}",
                    memory_budget_mb=256,
                    lane="formal",
                )
            )


def test_long_halt_label_maturity_poison_is_excluded(
    tmp_path: Path,
) -> None:
    year_directory = tmp_path / "year=2025"
    year_directory.mkdir()
    with sqlite3.connect(year_directory / "rows.sqlite") as connection:
        connection.execute(
            """
            CREATE TABLE rows (
                local_row_index INTEGER PRIMARY KEY,
                max_label_available_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO rows VALUES (?, ?)",
            (
                (0, "2025-06-01T14:30:00+08:00"),
                (1, "2025-09-15T14:30:00+08:00"),
            ),
        )
    store = object.__new__(_NumericStore)
    store.years = (SimpleNamespace(directory=year_directory),)
    refs = np.asarray(((0, 0), (0, 1)), dtype=np.int64)
    selected = store.mature_positions(refs, cutoff="2025-08-01")
    assert selected.tolist() == [0]
    assert np.asarray(refs[selected], dtype=np.int64).tolist() == [[0, 0]]


def test_rss_measurement_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        direct_store_module,
        "_current_rss_bytes",
        lambda: None,
    )
    with pytest.raises(RuntimeError, match="fails closed"):
        direct_store_module._MemoryBudgetGuard.create(256)

    import ml_module.allocation_out_of_core_training_service as trainer_module

    monkeypatch.setattr(
        trainer_module,
        "_current_rss_bytes",
        lambda: None,
    )
    with pytest.raises(RuntimeError, match="fails closed"):
        _PeakRSSMonitor(memory_budget_mb=256)


@pytest.mark.parametrize(
    ("script", "required_flag"),
    (
        ("build_portfolio_ml_ooc_from_raw.py", "--raw-manifest"),
        ("build_portfolio_ml_direct_numeric_store.py", "--raw-manifest"),
        ("build_portfolio_ml_out_of_core_store.py", "--training-manifest"),
        ("train_ml_allocation_out_of_core.py", "--store-manifest"),
        (
            "continue_ml_direct_ooc_after_store.py",
            "--direct-process-id",
        ),
    ),
)
def test_ooc_cli_help_is_utf8_and_complete(
    script: str,
    required_flag: str,
) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode(
        "utf-8",
        errors="replace",
    )
    output = completed.stdout.decode("utf-8")
    assert required_flag in output
    assert "\ufffd" not in output
    if script == "build_portfolio_ml_ooc_from_raw.py":
        assert "--corporate-action-manifest" in output
        assert "--temporary-storage-budget-bytes" in output
