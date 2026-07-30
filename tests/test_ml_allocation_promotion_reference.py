from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
)
from ml_module.allocation_promotion_reference import (
    OBSERVATION_SCHEMA_VERSION,
    OUTCOME_CONTRACT_HASH,
    OUTCOME_CONTRACT_VERSION,
    PROMOTION_HORIZONS,
    build_promotion_observation,
    build_promotion_reference,
    evaluate_matured_promotion_reference,
    load_promotion_reference,
    population_stability_index_bp,
)
from scripts.build_ml_allocation_promotion_reference import main


_DATASET_ID = "fixture-all-field-enriched"
_DATASET_IDENTITY_HASH = "sha256:" + "1" * 64
_REGISTRY_HASH = "sha256:" + "2" * 64
_SOURCE_HASH = "sha256:" + "3" * 64
_POLICY_HASH = "sha256:" + "4" * 64
_TRAINING_AS_OF = "2026-07-01T08:30:00+08:00"


def _sha_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha_text(payload: str) -> str:
    return _sha_bytes(payload.encode("utf-8"))


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha_bytes(encoded)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _frozen_fixture(tmp_path: Path) -> dict[str, Path | str | object]:
    root = tmp_path / "frozen"
    root.mkdir()
    shard_path = root / "year=2026.jsonl.gz"
    feature_packs_manifest = [
        {"pack_id": "price_liquidity_technical", "feature_ids": ["price.x"]}
    ]
    source_hashes = [["sqlite.daily_prices", _SOURCE_HASH]]
    header = {
        "record_type": "header",
        "dataset_id": _DATASET_ID,
        "dataset_identity_hash": _DATASET_IDENTITY_HASH,
    }
    samples = []
    for index in range(40):
        decision = date(2026, 1, 2) + timedelta(days=index)
        feature = {
            "feature_id": "price.x",
            "family_id": "price_liquidity_technical",
            "source_id": "sqlite.daily_prices",
            "value_int": (index - 20) * 100,
            "scale": 100,
            "event_at": f"{decision.isoformat()}T07:00:00+08:00",
            "available_at": f"{decision.isoformat()}T07:00:00+08:00",
            "revision_id": f"revision-{index}",
            "quality": "observed",
            "content_hash": _sha_text(f"feature-{index}"),
            "observed": True,
            "event_time_semantics": "realized_observation",
        }
        samples.append(
            {
                "record_type": "sample",
                "sample": {
                    "row": {
                        "row_id": f"row-{index}",
                        "decision_at": f"{decision.isoformat()}T08:30:00+08:00",
                        "symbol": f"{1000 + index:04d}",
                        "features": [feature],
                        "dataset_identity_hash": _DATASET_IDENTITY_HASH,
                        "feature_registry_hash": _REGISTRY_HASH,
                    }
                },
            }
        )
    with gzip.open(shard_path, "wt", encoding="utf-8") as handle:
        for record in (header, *samples):
            handle.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            )
    shard_hash = _sha_bytes(shard_path.read_bytes())

    dataset_body = {
        "schema_version": "portfolio-ml-training-shards.v2",
        "dataset_id": _DATASET_ID,
        "dataset_identity_hash": _DATASET_IDENTITY_HASH,
        "feature_registry_hash": _REGISTRY_HASH,
        "training_as_of": _TRAINING_AS_OF,
        "sample_count": 40,
        "feature_packs": feature_packs_manifest,
        "source_manifest_hashes": source_hashes,
        "feature_registry": {
            "features": [
                {
                    "feature_id": "price.x",
                    "family_id": "price_liquidity_technical",
                    "source_id": "sqlite.daily_prices",
                    "scale": 100,
                }
            ]
        },
        "shards": [
            {
                "path": shard_path.name,
                "compressed_sha256": shard_hash,
                "sample_count": 40,
            }
        ],
    }
    dataset_manifest = {
        **dataset_body,
        "manifest_hash": _payload_hash(dataset_body),
    }
    dataset_path = root / "manifest.json"
    _write_json(dataset_path, dataset_manifest)
    dataset_file_hash = _sha_bytes(dataset_path.read_bytes())

    matrix = np.asarray([[float(index - 20)] for index in range(40)])
    targets = np.asarray([0 if index < 20 else 1 for index in range(40)])
    estimator = Pipeline(
        (
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=200, random_state=42)),
        )
    )
    classifier = CalibratedClassifierCV(estimator, cv=2).fit(matrix, targets)
    expert_keys = tuple(
        f"price_liquidity_technical|h{horizon}|ridge_logistic"
        for horizon in PROMOTION_HORIZONS
    )
    artifact = {
        "dataset_id": _DATASET_ID,
        "dataset_identity_hash": _DATASET_IDENTITY_HASH,
        "dataset_manifest_file_hash": dataset_file_hash,
        "feature_registry_hash": _REGISTRY_HASH,
        "source_manifest_hashes": source_hashes,
        "training_as_of": _TRAINING_AS_OF,
        "feature_packs": (
            ("price_liquidity_technical", ("price.x",)),
        ),
        "expert_keys": expert_keys,
        "base_models": {
            expert_key: {
                "classification_models": {
                    "downside_probability_bp": classifier,
                },
                "head_missing_reasons": {},
            }
            for expert_key in expert_keys
        },
        "feature_family_weights_bp": (
            ("price_liquidity_technical", 10_000),
        ),
        "production_alpha_bp": 0,
        "formal_oos_allowed": False,
        "broker_order_allowed": False,
    }
    model_path = root / "allocation_model.joblib"
    joblib.dump(artifact, model_path)
    model_hash = _sha_bytes(model_path.read_bytes())
    training_manifest = {
        "artifact_hash": model_hash,
        "dataset_id": _DATASET_ID,
        "dataset_identity_hash": _DATASET_IDENTITY_HASH,
        "dataset_manifest_file_hash": dataset_file_hash,
        "feature_registry_hash": _REGISTRY_HASH,
        "source_manifest_hashes": source_hashes,
        "training_as_of": _TRAINING_AS_OF,
        "training_row_count": 40,
        "feature_packs": feature_packs_manifest,
        "input_shards": [
            {
                "file_name": shard_path.name,
                "content_hash": shard_hash,
                "row_count": 40,
            }
        ],
    }
    training_path = root / "training_manifest.json"
    _write_json(training_path, training_manifest)
    return {
        "model_path": model_path,
        "model_hash": model_hash,
        "dataset_path": dataset_path,
        "training_path": training_path,
        "classifier": classifier,
    }


def _publish_reference(
    fixture: dict[str, Path | str | object],
    output_root: Path,
):
    return build_promotion_reference(
        model_artifact_path=Path(fixture["model_path"]),
        training_manifest_path=Path(fixture["training_path"]),
        dataset_manifest_path=Path(fixture["dataset_path"]),
        promotion_policy_hash=_POLICY_HASH,
        output_root=output_root,
        bin_count=5,
        batch_size=7,
    )


def _runtime_row(decision: date, value_int: int) -> PortfolioMLDatasetRow:
    decision_at = f"{decision.isoformat()}T08:30:00+08:00"
    previous = decision - timedelta(days=1)
    weights = AllocationWeightContract(positions_bp=(), cash_bp=10_000)
    state = CausalPortfolioState.create(
        as_of_date=previous.isoformat(),
        weights=weights,
        weekly_turnover_used_bp=0,
    )
    return PortfolioMLDatasetRow(
        row_id=f"runtime-{decision.isoformat()}",
        decision_at=decision_at,
        symbol="2330",
        features=(
            PITFeatureValue(
                feature_id="price.x",
                family_id="price_liquidity_technical",
                source_id="sqlite.daily_prices",
                value_int=value_int,
                scale=100,
                event_at=f"{previous.isoformat()}T14:30:00+08:00",
                available_at=f"{previous.isoformat()}T14:30:00+08:00",
                revision_id=f"runtime-{decision.isoformat()}",
                quality="observed",
                content_hash=_sha_text(f"runtime-{decision.isoformat()}"),
                observed=True,
            ),
        ),
        missing_family_ids=(),
        portfolio_state=state,
        dataset_identity_hash=_DATASET_IDENTITY_HASH,
        feature_registry_hash=_REGISTRY_HASH,
        source_manifest_hashes=(("sqlite.daily_prices", _SOURCE_HASH),),
        targets=None,
    )


def _calibrated_bp(
    fixture: dict[str, Path | str | object],
    value_int: int,
) -> int:
    classifier = fixture["classifier"]
    assert isinstance(classifier, CalibratedClassifierCV)
    probability = float(classifier.predict_proba([[value_int / 100]])[0, 1])
    return int(
        Decimal(str(probability * 10_000)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _observation(
    *,
    fixture: dict[str, Path | str | object],
    reference_path: Path,
    reference_file_hash: str,
    decision: date,
    value_int: int,
) -> dict[str, object]:
    row = _runtime_row(decision, value_int)
    return build_promotion_observation(
        reference_path=reference_path,
        expected_reference_file_hash=reference_file_hash,
        model_artifact_path=Path(fixture["model_path"]),
        rows=(row,),
        calibrated_probability_by_symbol_bp={
            "2330": _calibrated_bp(fixture, value_int)
        },
        inference_input_hash=_sha_text(f"input-{decision.isoformat()}"),
        proposal_hash=_sha_text(f"proposal-{decision.isoformat()}"),
        promotion_policy_hash=_POLICY_HASH,
    )


def _downside_outcome(
    *,
    decision: date,
    horizon: int,
    actual_downside: int,
) -> dict[str, object]:
    horizon_end = decision + timedelta(days=horizon - 1)
    benchmark_return_bp = 100
    benchmark_excess_return_bp = -1 if actual_downside else 1
    stock_return_bp = (
        benchmark_return_bp
        + 25
        + 55
        + benchmark_excess_return_bp
    )
    stock_close = Decimal("100") * (
        Decimal("1") + Decimal(stock_return_bp) / Decimal("10000")
    )
    benchmark_close = Decimal("101")
    entry_available = f"{decision.isoformat()}T23:59:59+08:00"
    exit_available = f"{horizon_end.isoformat()}T23:59:59+08:00"
    stock_entry = {
        "source_id": "sqlite.daily_prices",
        "table": "daily_prices",
        "event_date": decision.isoformat(),
        "symbol": "2330",
        "security_name": "台積電",
        "open": "100",
        "close": "100",
        "availability_basis": (
            "official_market_session_end_of_day_conservative"
        ),
        "available_at": entry_available,
    }
    stock_exit = {
        **stock_entry,
        "event_date": horizon_end.isoformat(),
        "open": str(stock_close),
        "close": str(stock_close),
        "available_at": exit_available,
    }
    benchmark_entry = {
        "source_id": "sqlite.market_indices",
        "table": "market_indices",
        "event_date": decision.isoformat(),
        "benchmark_id": "TAIEX",
        "open": "100",
        "close": "100",
        "availability_basis": (
            "official_market_session_end_of_day_conservative"
        ),
        "available_at": entry_available,
    }
    benchmark_exit = {
        **benchmark_entry,
        "event_date": horizon_end.isoformat(),
        "open": str(benchmark_close),
        "close": str(benchmark_close),
        "available_at": exit_available,
    }
    stock_entry_hash = _payload_hash(stock_entry)
    stock_exit_hash = _payload_hash(stock_exit)
    benchmark_entry_hash = _payload_hash(benchmark_entry)
    benchmark_exit_hash = _payload_hash(benchmark_exit)
    stock_rows_hash = _payload_hash(
        {
            "source_id": "sqlite.daily_prices",
            "entry_source_row_hash": stock_entry_hash,
            "exit_source_row_hash": stock_exit_hash,
        }
    )
    benchmark_rows_hash = _payload_hash(
        {
            "source_id": "sqlite.market_indices",
            "benchmark_id": "TAIEX",
            "entry_source_row_hash": benchmark_entry_hash,
            "exit_source_row_hash": benchmark_exit_hash,
        }
    )
    calendar = [
        (decision + timedelta(days=index)).isoformat()
        for index in range(horizon)
    ]
    calendar_hash = _payload_hash(
        {
            "calendar_type": "per_symbol_market_sessions",
            "symbol": "2330",
            "decision_date": decision.isoformat(),
            "horizon_trading_sessions": horizon,
            "dates": calendar,
        }
    )
    corporate_manifest_hash = _sha_text("corporate-manifest")
    corporate_events_hash = _sha_text("corporate-events")
    revision_id = _payload_hash(
        {
            "stock_entry_revision_id": stock_entry_hash,
            "stock_exit_revision_id": stock_exit_hash,
            "benchmark_entry_revision_id": benchmark_entry_hash,
            "benchmark_exit_revision_id": benchmark_exit_hash,
            "corporate_action_manifest_hash": corporate_manifest_hash,
            "corporate_action_canonical_events_hash": corporate_events_hash,
        }
    )
    body: dict[str, object] = {
        "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
        "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
        "decision_date": decision.isoformat(),
        "symbol": "2330",
        "horizon_trading_sessions": horizon,
        "entry_date": decision.isoformat(),
        "horizon_end_date": horizon_end.isoformat(),
        "stock_open_to_close_return_bp": stock_return_bp,
        "taiex_open_to_close_return_bp": benchmark_return_bp,
        "buy_cost_bp": 25,
        "sell_cost_bp": 55,
        "actual_downside": actual_downside,
        "benchmark_excess_return_bp": benchmark_excess_return_bp,
        "stock_source_rows_hash": stock_rows_hash,
        "benchmark_source_rows_hash": benchmark_rows_hash,
        "calendar_hash": calendar_hash,
        "corporate_action_manifest_hash": corporate_manifest_hash,
        "corporate_action_canonical_events_hash": corporate_events_hash,
        "available_at": exit_available,
        "revision_id": revision_id,
        "source_custody": {
            "stock_rows": [stock_entry, stock_exit],
            "benchmark_rows": [benchmark_entry, benchmark_exit],
            "symbol_session_calendar": calendar,
            "availability_basis": (
                "official_market_session_end_of_day_conservative"
            ),
            "revision_basis": "content_addressed_source_row_snapshot",
            "benchmark_id": "TAIEX",
            "label_formula": "stock_return_bp-taiex_return_bp-25-55",
        },
    }
    return {**body, "outcome_hash": _payload_hash(body)}


def test_reference_is_deterministic_hash_bound_and_tamper_evident(
    tmp_path: Path,
) -> None:
    fixture = _frozen_fixture(tmp_path)
    first = _publish_reference(fixture, tmp_path / "reference-a")
    second = _publish_reference(fixture, tmp_path / "reference-b")

    assert first.reference_hash == second.reference_hash
    assert first.reference_file_hash == second.reference_file_hash
    assert first.row_count == 40
    assert first.feature_count == 1
    payload = load_promotion_reference(
        first.reference_path,
        expected_reference_file_hash=first.reference_file_hash,
        expected_model_artifact_hash=str(fixture["model_hash"]),
        expected_dataset_identity_hash=_DATASET_IDENTITY_HASH,
        expected_promotion_policy_hash=_POLICY_HASH,
    )
    assert payload["uncalibrated_probability_contract"]["method"].startswith(
        "mean_predict_proba"
    )
    assert [
        item["horizon_trading_sessions"]
        for item in payload["frozen_probability_distributions_by_horizon"]
    ] == list(PROMOTION_HORIZONS)
    assert payload["outcome_contract"]["contract_hash"] == OUTCOME_CONTRACT_HASH

    tampered = json.loads(first.reference_path.read_text(encoding="utf-8"))
    tampered["row_count"] = 41
    _write_json(first.reference_path, tampered)
    with pytest.raises(ValueError, match="canonical hash mismatch"):
        load_promotion_reference(first.reference_path)


def test_builder_rejects_dataset_manifest_tamper(tmp_path: Path) -> None:
    fixture = _frozen_fixture(tmp_path)
    dataset_path = Path(fixture["dataset_path"])
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    payload["sample_count"] = 41
    _write_json(dataset_path, payload)

    with pytest.raises(ValueError, match="canonical hash mismatch"):
        _publish_reference(fixture, tmp_path / "reference")


def test_observation_replays_calibrated_and_preserves_uncalibrated(
    tmp_path: Path,
) -> None:
    fixture = _frozen_fixture(tmp_path)
    publication = _publish_reference(fixture, tmp_path / "reference")
    observation = _observation(
        fixture=fixture,
        reference_path=publication.reference_path,
        reference_file_hash=publication.reference_file_hash,
        decision=date(2026, 7, 2),
        value_int=2_500,
    )

    assert observation["schema_version"] == OBSERVATION_SCHEMA_VERSION
    predictions = observation["prediction_rows"]
    assert {
        prediction["horizon_trading_sessions"] for prediction in predictions
    } == set(PROMOTION_HORIZONS)
    assert all(
        isinstance(prediction["calibrated_downside_probability_bp"], int)
        for prediction in predictions
    )
    assert all(
        isinstance(prediction["uncalibrated_downside_probability_bp"], int)
        for prediction in predictions
    )
    assert observation["strict_pit_availability_verified"] is True
    assert observation["future_prefix_violation_count"] == 0
    assert observation["formal_oos_allowed"] is False

    with pytest.raises(ValueError, match="does not replay frozen model"):
        build_promotion_observation(
            reference_path=publication.reference_path,
            expected_reference_file_hash=publication.reference_file_hash,
            model_artifact_path=Path(fixture["model_path"]),
            rows=(_runtime_row(date(2026, 7, 3), 2_500),),
            calibrated_probability_by_symbol_bp={"2330": 0},
            inference_input_hash=_sha_text("bad-input"),
            proposal_hash=_sha_text("bad-proposal"),
            promotion_policy_hash=_POLICY_HASH,
        )


def test_metrics_are_not_evaluated_until_twenty_unique_dates_then_compute(
    tmp_path: Path,
) -> None:
    fixture = _frozen_fixture(tmp_path)
    publication = _publish_reference(fixture, tmp_path / "reference")
    observations = []
    outcomes = []
    start = date(2026, 7, 2)
    for offset in range(20):
        decision = start + timedelta(days=offset)
        observations.append(
            _observation(
                fixture=fixture,
                reference_path=publication.reference_path,
                reference_file_hash=publication.reference_file_hash,
                decision=decision,
                value_int=(offset - 10) * 100,
            )
        )
        outcomes.extend(
            _downside_outcome(
                decision=decision,
                horizon=horizon,
                actual_downside=int(offset < 10),
            )
            for horizon in PROMOTION_HORIZONS
        )

    pending = evaluate_matured_promotion_reference(
        reference_path=publication.reference_path,
        expected_reference_file_hash=publication.reference_file_hash,
        observations=observations[:19],
        downside_outcomes=outcomes[: 19 * len(PROMOTION_HORIZONS)],
    )
    assert pending["status"] == "not_evaluated"
    assert pending["calibrated_brier_bp"] is None
    assert pending["psi_bp"] is None
    assert pending["blockers"] == [
        f"matured_shadow_days_insufficient:h{horizon}:19/20"
        for horizon in PROMOTION_HORIZONS
    ]
    assert pending["promotion_reference_status"][
        "uncalibrated_probability_baseline"
    ] == "ready"

    evaluated = evaluate_matured_promotion_reference(
        reference_path=publication.reference_path,
        expected_reference_file_hash=publication.reference_file_hash,
        observations=observations,
        downside_outcomes=outcomes,
    )
    assert evaluated["status"] == "evaluated"
    assert isinstance(evaluated["calibration_ece_bp"], int)
    assert isinstance(evaluated["calibrated_brier_bp"], int)
    assert isinstance(evaluated["uncalibrated_brier_bp"], int)
    assert isinstance(evaluated["psi_bp"], int)
    assert evaluated["matured_unique_decision_date_count"] == 20
    assert evaluated["formal_oos_allowed"] is False

    poisoned_outcome = dict(outcomes[0])
    poisoned_outcome["stock_open_to_close_return_bp"] = (
        int(poisoned_outcome["stock_open_to_close_return_bp"]) + 1
    )
    poisoned_body = dict(poisoned_outcome)
    poisoned_body.pop("outcome_hash")
    poisoned_outcome["outcome_hash"] = _payload_hash(poisoned_body)
    with pytest.raises(ValueError, match="excess return formula mismatch"):
        evaluate_matured_promotion_reference(
            reference_path=publication.reference_path,
            expected_reference_file_hash=publication.reference_file_hash,
            observations=observations,
            downside_outcomes=[poisoned_outcome, *outcomes[1:]],
        )

    broken = dict(observations[0])
    prediction = dict(broken["prediction_rows"][0])
    prediction.pop("uncalibrated_downside_probability_bp")
    broken["prediction_rows"] = [
        prediction,
        *broken["prediction_rows"][1:],
    ]
    body = dict(broken)
    body.pop("observation_hash")
    broken["observation_hash"] = _payload_hash(body)
    with pytest.raises(TypeError, match="uncalibrated_downside_probability_bp"):
        evaluate_matured_promotion_reference(
            reference_path=publication.reference_path,
            expected_reference_file_hash=publication.reference_file_hash,
            observations=[broken, *observations[1:]],
            downside_outcomes=outcomes,
        )


def test_psi_uses_deterministic_decimal_smoothing() -> None:
    assert population_stability_index_bp([10, 20, 30], [10, 20, 30]) == 0
    shifted = population_stability_index_bp([58, 1, 1], [1, 1, 58])
    assert shifted > 2_500
    assert shifted == population_stability_index_bp(
        [58, 1, 1],
        [1, 1, 58],
    )


def test_cli_builds_versioned_reference(tmp_path: Path, capsys) -> None:
    fixture = _frozen_fixture(tmp_path)
    output_root = tmp_path / "cli-reference"
    exit_code = main(
        [
            "--model-artifact",
            str(fixture["model_path"]),
            "--training-manifest",
            str(fixture["training_path"]),
            "--dataset-manifest",
            str(fixture["dataset_path"]),
            "--promotion-policy-hash",
            _POLICY_HASH,
            "--output-root",
            str(output_root),
            "--batch-size",
            "9",
        ]
    )
    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "promotion_reference_ready"
    assert summary["row_count"] == 40
    assert Path(summary["reference_path"]).is_file()
