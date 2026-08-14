from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable, Mapping

from ml_module.allocation_promotion_evidence_builder import (
    AllocationPromotionEvidenceBuildRequest,
    _load_formal_custody,
    build_compatible_allocation_promotion_evidence,
)
from ml_module.allocation_promotion_reference import (
    OUTCOME_CONTRACT_HASH,
    OUTCOME_CONTRACT_VERSION,
)
from ml_module.allocation_validation import (
    AllocationPromotionEvaluator,
    load_allocation_promotion_evidence,
)
from scripts.build_ml_allocation_promotion_evidence import main


HASH = "sha256:" + "1" * 64
DECISION_AT = datetime.fromisoformat("2026-04-01T08:30:00+08:00")
AS_OF_DATE = date(2026, 3, 31)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _with_hash(
    value: Mapping[str, object],
    field_name: str,
) -> dict[str, object]:
    result = dict(value)
    result[field_name] = _payload_hash(result)
    return result


def _mutate_latest_shadow_outcome(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    horizon: int,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    with sqlite3.connect(request.shadow_sidecar_database_path) as connection:
        rowid, raw = connection.execute(
            "SELECT rowid, payload_json FROM shadow_outcomes "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        outcome = json.loads(raw)
        rows = outcome["downside_outcomes"]
        target = next(
            row
            for row in rows
            if row["horizon_trading_sessions"] == horizon
        )
        mutate(target)
        target.pop("outcome_hash", None)
        target["outcome_hash"] = _payload_hash(target)
        outcome["outcome_source_custody"][
            "downside_outcome_hashes"
        ] = [row["outcome_hash"] for row in rows]
        outcome["outcome_source_custody_hash"] = _payload_hash(
            outcome["outcome_source_custody"]
        )
        outcome.pop("record_hash", None)
        outcome["record_hash"] = _payload_hash(outcome)
        connection.execute(
            "UPDATE shadow_outcomes SET payload_json = ? WHERE rowid = ?",
            (_canonical_json(outcome), rowid),
        )


def _artifact_file(path: Path, content: bytes) -> dict[str, object]:
    path.write_bytes(content)
    return {
        "path": path.name,
        "byte_count": len(content),
        "file_sha256": _file_hash(path),
    }


def _build_formal_ooc(root: Path) -> tuple[Path, Path]:
    run = root / "formal-ooc" / "runs" / "run-001"
    folds = [
        {
            "fold_id": f"fold-{index:03d}",
            "train": {"path": f"fold-{index}-train.refs"},
            "test": {"path": f"fold-{index}-test.refs"},
        }
        for index in range(1, 6)
    ]
    dataset_body: dict[str, object] = {
        "schema_version": "portfolio-ml-ooc-store.v3",
        "status": "complete",
        "dataset_id": "formal-ooc-dataset",
        "dataset_identity_hash": HASH,
        "formal_source_only": True,
        "research_shadow_included": False,
        "research_only": False,
        "readiness": {"full_market_ready": True},
        "safety": {
            "pit_contract_revalidated_per_row": True,
            "t_minus_1_contract_revalidated_per_row": True,
        },
        "folds": folds,
    }
    dataset = _with_hash(dataset_body, "manifest_hash")
    dataset_path = run / "store_manifest.json"
    _write(dataset_path, dataset)

    base_summaries: list[dict[str, object]] = []
    for index in range(1, 6):
        fold_id = f"fold-{index:03d}"
        directory = run / "artifacts" / "base" / fold_id
        directory.mkdir(parents=True, exist_ok=True)
        oof = _artifact_file(
            directory / "oof.i32",
            bytes([index]) * 80,
        )
        model = _artifact_file(
            directory / "head.joblib",
            f"model-{index}".encode(),
        )
        artifact_body: dict[str, object] = {
            "schema_version": "allocation-ooc-expert.v5",
            "artifact_kind": "base_oof_expert",
            "fold_id": fold_id,
            "expert_id": f"expert:{fold_id}",
            "oof_shape": [20, 1],
            "oof_dtype": "<i4",
            "artifacts": [model, oof],
        }
        artifact = _with_hash(artifact_body, "manifest_hash")
        _write(directory / "manifest.json", artifact)
        base_summaries.append(
            {
                **artifact,
                "artifact_path": directory.relative_to(run).as_posix(),
            }
        )

    meta_summaries: list[dict[str, object]] = []
    for index in range(2, 6):
        fold_id = f"fold-{index:03d}"
        directory = run / "artifacts" / "meta" / fold_id
        directory.mkdir(parents=True, exist_ok=True)
        oof = _artifact_file(
            directory / "oof.i32",
            bytes([index]) * 120,
        )
        model = _artifact_file(
            directory / "head.joblib",
            f"meta-{index}".encode(),
        )
        artifact_body = {
            "schema_version": "allocation-ooc-meta.v3",
            "artifact_kind": "meta_oof_allocator",
            "fold_id": fold_id,
            "oof_shape": [5, 6],
            "oof_dtype": "<i4",
            "artifacts": [model, oof],
        }
        artifact = _with_hash(artifact_body, "manifest_hash")
        _write(directory / "manifest.json", artifact)
        meta_summaries.append(
            {
                **artifact,
                "artifact_path": directory.relative_to(run).as_posix(),
            }
        )

    final_directory = run / "artifacts" / "meta" / "final"
    final_directory.mkdir(parents=True, exist_ok=True)
    final_head = _artifact_file(
        final_directory / "head.joblib",
        b"final-meta-model",
    )
    final_body: dict[str, object] = {
        "schema_version": "allocation-ooc-meta.v3",
        "artifact_kind": "final_meta_allocator",
        "fold_id": "final",
        "artifacts": [final_head],
    }
    final = _with_hash(final_body, "manifest_hash")
    _write(final_directory / "manifest.json", final)
    training_body: dict[str, object] = {
        "schema_version": "allocation-ooc-training.v5",
        "status": "complete",
        "run_id": "formal-ooc-model-001",
        "store_manifest_path": dataset_path.relative_to(run).as_posix(),
        "store_manifest_file_hash": _file_hash(dataset_path),
        "dataset_identity_hash": HASH,
        "formal_source_only": True,
        "research_shadow_included": False,
        "research_only": False,
        "fold_count": 5,
        "base_expert_count": 5,
        "base_experts": base_summaries,
        "meta_folds": meta_summaries,
        "final_meta": {
            **final,
            "artifact_path": final_directory.relative_to(run).as_posix(),
        },
        "validation": {
            "pit_violation_count": 0,
            "future_prefix_violation_count": 0,
            "constraint_violation_count": 0,
            "deterministic_custody": True,
        },
    }
    training = _with_hash(training_body, "manifest_hash")
    training_path = run / "manifest.json"
    _write(training_path, training)
    return training_path, dataset_path


def _request_skeleton(
    root: Path,
    *,
    training_path: Path,
    dataset_path: Path,
) -> AllocationPromotionEvidenceBuildRequest:
    return AllocationPromotionEvidenceBuildRequest(
        experiment_id="release-v4-prod",
        decision_at=DECISION_AT,
        as_of_date=AS_OF_DATE,
        training_manifest_path=training_path,
        dataset_manifest_path=dataset_path,
        replay_primary_path=root / "replay-primary.json",
        replay_verification_path=root / "replay-verification.json",
        shadow_sidecar_database_path=root / "shadow.sqlite",
        promotion_reference_path=root / "promotion-reference.json",
        promotion_reference_metrics_path=root / "promotion-metrics.json",
        output_root=root / "output",
    )


def _build_reference_and_metrics(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    model_hash: str,
    training_hash: str,
    dataset_hash: str,
) -> tuple[str, str]:
    reference_body: dict[str, object] = {
        "schema_version": "ml-allocation-promotion-reference-v2",
        "status": "complete",
        "custody": {
            "model_artifact_hash": model_hash,
            "training_manifest_file_hash": training_hash,
            "dataset_identity_hash": HASH,
            "dataset_manifest_file_hash": dataset_hash,
        },
        "safety": {
            "strict_pit_availability_verified": True,
            "future_outcomes_used_in_reference": False,
            "broker_order_allowed": False,
        },
    }
    reference = _with_hash(reference_body, "reference_hash")
    _write(request.promotion_reference_path, reference)
    reference_file_hash = _file_hash(request.promotion_reference_path)
    metrics_body: dict[str, object] = {
        "schema_version": "ml-allocation-promotion-reference-metrics-v2",
        "status": "evaluated",
        "reference_hash": reference["reference_hash"],
        "reference_file_hash": reference_file_hash,
        "blockers": [],
        "psi_bp": 260,
        "horizon_metrics": {
            str(horizon): {
                "status": "evaluated",
                "matured_unique_decision_date_count": 20,
                "calibration_ece_bp": 100 + horizon,
                "calibrated_brier_bp": 1200 + horizon,
                "uncalibrated_brier_bp": 1300 + horizon,
            }
            for horizon in (5, 10, 20, 60)
        },
    }
    metrics = _with_hash(metrics_body, "metrics_hash")
    _write(request.promotion_reference_metrics_path, metrics)
    return str(reference["reference_hash"]), reference_file_hash


def _build_replays(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    formal: object,
) -> None:
    custody = formal
    input_custody = {
        "training_manifest_file_hash": custody.training_manifest_file_hash,
        "model_artifact_hash": custody.model_artifact_hash,
        "dataset_identity_hash": custody.dataset_identity_hash,
        "dataset_manifest_file_hash": custody.dataset_manifest_file_hash,
        "oof_source_hash": custody.oof_source_hash,
    }
    lanes: list[dict[str, object]] = []
    for alpha in (0, 2000, 3500, 5000):
        fold_return = 0 if alpha == 0 else alpha // 100
        folds = [
            {
                "fold_id": f"fold-{index:03d}",
                "after_cost_excess_vs_rule_bp": (
                    0 if index == 1 else fold_return
                ),
                "daily_after_cost_excess_vs_rule_bp": (
                    [0] * 5
                    if alpha == 0 or index == 1
                    else [fold_return] * 5
                ),
            }
            for index in range(1, 6)
        ]
        lanes.append(
            {
                "alpha_bp": alpha,
                "folds": folds,
                "winning_fold_count": 0 if alpha == 0 else 4,
                "mdd_worsening_vs_rule_bp": 0,
                "cvar_worsening_vs_rule_bp": 0,
                "weekly_turnover_bp": 1000,
                "turnover_increment_vs_rule_bp": 100,
                "core_coverage_bp": 9800,
                "enriched_coverage_bp": 9500,
                "feasible_fill_coverage_bp": 9800,
                "pit_violation_count": 0,
                "future_prefix_violation_count": 0,
                "constraint_violation_count": 0,
            }
        )
    result_hash = _payload_hash(
        {"input_custody": input_custody, "lanes": lanes}
    )
    for run_id, path in (
        ("replay-a", request.replay_primary_path),
        ("replay-b", request.replay_verification_path),
    ):
        body: dict[str, object] = {
            "schema_version": "allocation-ooc-portfolio-replay.v1",
            "status": "complete",
            "replay_run_id": run_id,
            "formal_source_only": True,
            "research_shadow_included": False,
            "research_only": False,
            "formal_semantic_validation": {
                "schema_version": (
                    "allocation-oos-semantic-verification.v1"
                ),
                "verifier_id": "allocation-oos-semantic-verifier-v1",
                "verified": True,
                "blockers": [],
            },
            "promotion_eligible_input": True,
            "input_custody": input_custody,
            "lanes": lanes,
            "replay_result_hash": result_hash,
        }
        _write(path, _with_hash(body, "manifest_hash"))


def _build_shadow(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    model_hash: str,
    training_hash: str,
    dataset_hash: str,
    reference_hash: str,
    reference_file_hash: str,
) -> None:
    with sqlite3.connect(request.shadow_sidecar_database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE shadow_observations (payload_json TEXT NOT NULL);
            CREATE TABLE shadow_outcomes (payload_json TEXT NOT NULL);
            """
        )
        for index in range(20):
            decision_date = date(2026, 1, 1) + timedelta(days=index)
            observation_body: dict[str, object] = {
                "schema_version": "ml-allocation-shadow-observation-v3",
                "decision_date": decision_date.isoformat(),
                "revision": 1,
                "research_only": True,
                "formal_oos_allowed": False,
                "broker_order_allowed": False,
                "custody": {
                    "model_hash": model_hash,
                    "release_training_manifest_file_hash": training_hash,
                    "dataset_identity_hash": HASH,
                    "dataset_manifest_file_hash": dataset_hash,
                    "promotion_reference_hash": reference_hash,
                    "promotion_reference_file_hash": reference_file_hash,
                },
                "lanes": [
                    {"alpha_bp": alpha}
                    for alpha in (0, 2000, 3500, 5000)
                ],
                "pit_violation_count": 0,
                "future_prefix_violation_count": 0,
                "constraint_violation_count": 0,
            }
            observation = _with_hash(observation_body, "record_hash")
            connection.execute(
                "INSERT INTO shadow_observations(payload_json) VALUES (?)",
                (_canonical_json(observation),),
            )
            downside_outcomes: list[dict[str, object]] = []
            for horizon in (5, 10, 20, 60):
                calendar = tuple(
                    (decision_date + timedelta(days=offset)).isoformat()
                    for offset in range(horizon)
                )
                horizon_end = date.fromisoformat(calendar[-1])
                available_at = (
                    f"{horizon_end.isoformat()}T23:59:59+08:00"
                )
                stock_rows = [
                    {
                        "source_id": "sqlite.daily_prices",
                        "table": "daily_prices",
                        "event_date": calendar[0],
                        "symbol": "2330",
                        "open": "100",
                        "close": "100",
                        "available_at": (
                            f"{calendar[0]}T23:59:59+08:00"
                        ),
                    },
                    {
                        "source_id": "sqlite.daily_prices",
                        "table": "daily_prices",
                        "event_date": calendar[-1],
                        "symbol": "2330",
                        "open": "100",
                        "close": "101",
                        "available_at": available_at,
                    },
                ]
                benchmark_rows = [
                    {
                        "source_id": "sqlite.market_indices",
                        "table": "market_indices",
                        "event_date": calendar[0],
                        "benchmark_id": "TAIEX",
                        "open": "100",
                        "close": "100",
                        "available_at": (
                            f"{calendar[0]}T23:59:59+08:00"
                        ),
                    },
                    {
                        "source_id": "sqlite.market_indices",
                        "table": "market_indices",
                        "event_date": calendar[-1],
                        "benchmark_id": "TAIEX",
                        "open": "100",
                        "close": "100.5",
                        "available_at": available_at,
                    },
                ]
                stock_entry_hash = _payload_hash(stock_rows[0])
                stock_exit_hash = _payload_hash(stock_rows[1])
                benchmark_entry_hash = _payload_hash(benchmark_rows[0])
                benchmark_exit_hash = _payload_hash(benchmark_rows[1])
                stock_source_rows_hash = _payload_hash(
                    {
                        "source_id": "sqlite.daily_prices",
                        "entry_source_row_hash": stock_entry_hash,
                        "exit_source_row_hash": stock_exit_hash,
                    }
                )
                benchmark_source_rows_hash = _payload_hash(
                    {
                        "source_id": "sqlite.market_indices",
                        "benchmark_id": "TAIEX",
                        "entry_source_row_hash": benchmark_entry_hash,
                        "exit_source_row_hash": benchmark_exit_hash,
                    }
                )
                calendar_hash = _payload_hash(
                    {
                        "calendar_type": "per_symbol_market_sessions",
                        "symbol": "2330",
                        "decision_date": decision_date.isoformat(),
                        "horizon_trading_sessions": horizon,
                        "dates": list(calendar),
                    }
                )
                revision_id = _payload_hash(
                    {
                        "stock_entry_revision_id": stock_entry_hash,
                        "stock_exit_revision_id": stock_exit_hash,
                        "benchmark_entry_revision_id": (
                            benchmark_entry_hash
                        ),
                        "benchmark_exit_revision_id": (
                            benchmark_exit_hash
                        ),
                        "corporate_action_manifest_hash": HASH,
                        "corporate_action_canonical_events_hash": HASH,
                    }
                )
                row_body: dict[str, object] = {
                    "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
                    "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
                    "decision_date": decision_date.isoformat(),
                    "symbol": "2330",
                    "horizon_trading_sessions": horizon,
                    "entry_date": calendar[0],
                    "horizon_end_date": horizon_end.isoformat(),
                    "stock_open_to_close_return_bp": 100,
                    "taiex_open_to_close_return_bp": 50,
                    "buy_cost_bp": 25,
                    "sell_cost_bp": 55,
                    "benchmark_excess_return_bp": -30,
                    "actual_downside": 1,
                    "stock_source_rows_hash": stock_source_rows_hash,
                    "benchmark_source_rows_hash": (
                        benchmark_source_rows_hash
                    ),
                    "available_at": available_at,
                    "revision_id": revision_id,
                    "calendar_hash": calendar_hash,
                    "corporate_action_manifest_hash": HASH,
                    "corporate_action_canonical_events_hash": HASH,
                    "source_custody": {
                        "stock_rows": stock_rows,
                        "benchmark_rows": benchmark_rows,
                        "symbol_session_calendar": list(calendar),
                        "availability_basis": (
                            "official_market_session_end_of_day_conservative"
                        ),
                        "revision_basis": (
                            "content_addressed_source_row_snapshot"
                        ),
                        "benchmark_id": "TAIEX",
                        "label_formula": (
                            "stock_return_bp-taiex_return_bp-25-55"
                        ),
                    },
                }
                downside_outcomes.append(
                    _with_hash(row_body, "outcome_hash")
                )
            source_custody_body: dict[str, object] = {
                "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
                "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
                "corporate_action_manifest_hash": HASH,
                "corporate_action_manifest_file_hash": HASH,
                "corporate_action_canonical_events_hash": HASH,
                "corporate_action_source_registry_hash": HASH,
                "completed_horizons_trading_sessions": [5, 10, 20, 60],
                "downside_outcome_hashes": [
                    item["outcome_hash"] for item in downside_outcomes
                ],
                "source_row_hashes": [HASH],
                "blockers": [],
            }
            outcome_body: dict[str, object] = {
                "schema_version": "ml-allocation-shadow-outcome-v3",
                "observation_hash": observation["record_hash"],
                "decision_date": decision_date.isoformat(),
                "revision": 1,
                "status": "matured_all_horizons",
                "completed_horizons_trading_sessions": [5, 10, 20, 60],
                "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
                "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
                "outcome_source_custody": source_custody_body,
                "outcome_source_custody_hash": _payload_hash(
                    source_custody_body
                ),
                "downside_outcomes": downside_outcomes,
                "blockers": [],
                "pit_violation_count": 0,
                "future_prefix_violation_count": 0,
                "constraint_violation_count": 0,
            }
            outcome = _with_hash(outcome_body, "record_hash")
            connection.execute(
                "INSERT INTO shadow_outcomes(payload_json) VALUES (?)",
                (_canonical_json(outcome),),
            )


def _complete_fixture(
    tmp_path: Path,
) -> AllocationPromotionEvidenceBuildRequest:
    training_path, dataset_path = _build_formal_ooc(tmp_path)
    request = _request_skeleton(
        tmp_path,
        training_path=training_path,
        dataset_path=dataset_path,
    )
    formal = _load_formal_custody(request)
    reference_hash, reference_file_hash = _build_reference_and_metrics(
        request,
        model_hash=formal.model_artifact_hash,
        training_hash=formal.training_manifest_file_hash,
        dataset_hash=formal.dataset_manifest_file_hash,
    )
    _build_replays(request, formal=formal)
    _build_shadow(
        request,
        model_hash=formal.model_artifact_hash,
        training_hash=formal.training_manifest_file_hash,
        dataset_hash=formal.dataset_manifest_file_hash,
        reference_hash=reference_hash,
        reference_file_hash=reference_file_hash,
    )
    return request


def test_unready_dataset_blocker_exposes_failed_readiness_checks(
    tmp_path: Path,
) -> None:
    training_path, dataset_path = _build_formal_ooc(tmp_path)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset["readiness"] = {
        "full_market_ready": False,
        "readiness_failed_checks": [
            "pit_sector_membership_present",
            "causal_non_cash_portfolio_ledger_present",
        ],
    }
    dataset.pop("manifest_hash", None)
    _write(dataset_path, _with_hash(dataset, "manifest_hash"))

    training = json.loads(training_path.read_text(encoding="utf-8"))
    training["store_manifest_file_hash"] = _file_hash(dataset_path)
    training.pop("manifest_hash", None)
    _write(training_path, _with_hash(training, "manifest_hash"))

    request = _request_skeleton(
        tmp_path,
        training_path=training_path,
        dataset_path=dataset_path,
    )
    result = build_compatible_allocation_promotion_evidence(request)

    assert result.status == "blocked"
    assert result.blockers == (
        "formal_ooc_dataset_full_market_not_ready:"
        "causal_non_cash_portfolio_ledger_present,"
        "pit_sector_membership_present",
    )
    assert result.promotion_evidence_path is None


def _rehash_replay(path: Path) -> dict[str, object]:
    replay = json.loads(path.read_text(encoding="utf-8"))
    replay.pop("manifest_hash", None)
    replay["replay_result_hash"] = _payload_hash(
        {
            "input_custody": replay["input_custody"],
            "lanes": replay["lanes"],
        }
    )
    replay = _with_hash(replay, "manifest_hash")
    _write(path, replay)
    return replay


def test_complete_builder_publishes_unsigned_compatible_evidence(
    tmp_path: Path,
) -> None:
    request = _complete_fixture(tmp_path)
    first = build_compatible_allocation_promotion_evidence(request)
    assert first.status == "published"
    assert first.blockers == ()
    assert first.promotion_evidence_path is not None
    evidence = load_allocation_promotion_evidence(
        first.promotion_evidence_path
    )
    preview = AllocationPromotionEvaluator().evaluate(evidence)
    assert preview.eligible_alpha_bp == 2000
    assert preview.formal_oos_allowed is False
    assert preview.blockers == ("promotion_authorization_artifact_required",)
    raw = json.loads(first.promotion_evidence_path.read_text(encoding="utf-8"))
    assert "formal_oos_allowed" not in raw
    assert "signature" not in raw
    assert raw["authorization_artifact_created"] is False
    assert first.latest_pointer_path is not None
    pointer = json.loads(
        first.latest_pointer_path.read_text(encoding="utf-8")
    )
    pointer_hash = pointer.pop("pointer_hash")
    assert pointer_hash == _payload_hash(pointer)
    assert Path(pointer["promotion_evidence_path"]).is_absolute()
    assert pointer["decision_at"] == "2026-04-01T08:30:00+08:00"
    assert pointer["as_of_date"] == "2026-03-31"

    second = build_compatible_allocation_promotion_evidence(request)
    assert second.status == "published"
    assert second.idempotent is True
    assert second.publication_id == first.publication_id
    assert second.evidence_hash == first.evidence_hash


def test_missing_lane_metric_blocks_without_publication(tmp_path: Path) -> None:
    request = _complete_fixture(tmp_path)
    for path in (
        request.replay_primary_path,
        request.replay_verification_path,
    ):
        replay = json.loads(path.read_text(encoding="utf-8"))
        del replay["lanes"][1]["mdd_worsening_vs_rule_bp"]
        replay.pop("manifest_hash", None)
        replay["replay_result_hash"] = _payload_hash(
            {
                "input_custody": replay["input_custody"],
                "lanes": replay["lanes"],
            }
        )
        _write(path, _with_hash(replay, "manifest_hash"))
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert "lane.mdd_worsening_vs_rule_bp" in result.blockers[0]
    assert result.promotion_evidence_path is None
    assert not (request.output_root / "latest_pointer.json").exists()


def test_tampered_replay_is_rejected(tmp_path: Path) -> None:
    request = _complete_fixture(tmp_path)
    replay = json.loads(
        request.replay_primary_path.read_text(encoding="utf-8")
    )
    replay["lanes"][1]["weekly_turnover_bp"] = 9999
    _write(request.replay_primary_path, replay)
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "formal_replay_primary_logical_hash_mismatch",
    )


def test_research_only_replay_is_rejected(tmp_path: Path) -> None:
    request = _complete_fixture(tmp_path)
    replay = json.loads(
        request.replay_primary_path.read_text(encoding="utf-8")
    )
    replay["research_only"] = True
    replay.pop("manifest_hash", None)
    _write(
        request.replay_primary_path,
        _with_hash(replay, "manifest_hash"),
    )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "formal_replay_primary_research_lane_forbidden",
    )


def test_semantically_unverified_replay_is_rejected_even_when_rehashed(
    tmp_path: Path,
) -> None:
    request = _complete_fixture(tmp_path)
    replay = json.loads(
        request.replay_primary_path.read_text(encoding="utf-8")
    )
    replay["promotion_eligible_input"] = False
    replay["formal_semantic_validation"]["verified"] = False
    replay["formal_semantic_validation"]["blockers"] = [
        "production_rule_champion_replay_not_independently_rebuilt"
    ]
    replay.pop("manifest_hash", None)
    _write(
        request.replay_primary_path,
        _with_hash(replay, "manifest_hash"),
    )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "formal_replay_primary_semantic_validation_incomplete",
    )


def test_future_shadow_outcome_is_rejected(tmp_path: Path) -> None:
    request = _complete_fixture(tmp_path)
    with sqlite3.connect(request.shadow_sidecar_database_path) as connection:
        rows = connection.execute(
            "SELECT rowid, payload_json FROM shadow_outcomes ORDER BY rowid"
        ).fetchall()
        rowid, raw = rows[-1]
        outcome = json.loads(raw)
        row = outcome["downside_outcomes"][-1]
        row["horizon_end_date"] = "2026-04-02"
        row.pop("outcome_hash", None)
        row.update(_with_hash(row, "outcome_hash"))
        outcome["outcome_source_custody"]["downside_outcome_hashes"][-1] = (
            row["outcome_hash"]
        )
        outcome["outcome_source_custody_hash"] = _payload_hash(
            outcome["outcome_source_custody"]
        )
        outcome.pop("record_hash", None)
        outcome = _with_hash(outcome, "record_hash")
        connection.execute(
            "UPDATE shadow_outcomes SET payload_json = ? WHERE rowid = ?",
            (_canonical_json(outcome), rowid),
        )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "shadow_outcome_future_horizon:2026-01-20:60",
    )


def test_same_day_shadow_horizons_are_rejected(tmp_path: Path) -> None:
    request = _complete_fixture(tmp_path)

    def mutate(row: dict[str, object]) -> None:
        decision_date = str(row["decision_date"])
        row["horizon_end_date"] = decision_date
        row["available_at"] = f"{decision_date}T23:59:59+08:00"

    _mutate_latest_shadow_outcome(
        request,
        horizon=60,
        mutate=mutate,
    )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "shadow_outcome_noncausal_horizon:2026-01-20:60",
    )


def test_shortened_symbol_calendar_is_rejected(tmp_path: Path) -> None:
    request = _complete_fixture(tmp_path)

    def mutate(row: dict[str, object]) -> None:
        custody = row["source_custody"]
        assert isinstance(custody, dict)
        calendar = custody["symbol_session_calendar"]
        assert isinstance(calendar, list)
        custody["symbol_session_calendar"] = calendar[:-1]

    _mutate_latest_shadow_outcome(
        request,
        horizon=60,
        mutate=mutate,
    )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "shadow_downside_outcome_source_custody_invalid:"
        "downside outcome symbol calendar horizon mismatch",
    )


def test_tampered_return_is_rejected_against_source_rows(
    tmp_path: Path,
) -> None:
    request = _complete_fixture(tmp_path)

    def mutate(row: dict[str, object]) -> None:
        row["stock_open_to_close_return_bp"] = 200
        row["benchmark_excess_return_bp"] = 70
        row["actual_downside"] = 0

    _mutate_latest_shadow_outcome(
        request,
        horizon=60,
        mutate=mutate,
    )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "shadow_downside_outcome_source_custody_invalid:"
        "downside outcome stock return source mismatch",
    )


def test_horizon_metrics_must_cover_5_10_20_60(tmp_path: Path) -> None:
    request = _complete_fixture(tmp_path)
    metrics = json.loads(
        request.promotion_reference_metrics_path.read_text(encoding="utf-8")
    )
    del metrics["horizon_metrics"]["60"]
    metrics.pop("metrics_hash", None)
    _write(
        request.promotion_reference_metrics_path,
        _with_hash(metrics, "metrics_hash"),
    )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == (
        "promotion_reference_horizon_metrics_incomplete",
    )


def test_twenty_unique_latest_matured_dates_are_required(
    tmp_path: Path,
) -> None:
    request = _complete_fixture(tmp_path)
    with sqlite3.connect(request.shadow_sidecar_database_path) as connection:
        connection.execute(
            "DELETE FROM shadow_outcomes WHERE rowid = "
            "(SELECT MAX(rowid) FROM shadow_outcomes)"
        )
    result = build_compatible_allocation_promotion_evidence(request)
    assert result.status == "blocked"
    assert result.blockers == ("matured_shadow_days_insufficient:19/20",)
    assert not (request.output_root / "latest_pointer.json").exists()


def test_cli_returns_zero_with_structured_blocker(
    tmp_path: Path,
    capsys: object,
) -> None:
    training_path, dataset_path = _build_formal_ooc(tmp_path)
    exit_code = main(
        [
            "--experiment-id",
            "release-v4-prod",
            "--decision-at",
            "2026-04-01T08:30:00+08:00",
            "--as-of-date",
            "2026-03-31",
            "--training-manifest",
            str(training_path),
            "--dataset-manifest",
            str(dataset_path),
            "--replay-primary",
            str(tmp_path / "missing-primary.json"),
            "--replay-verification",
            str(tmp_path / "missing-verification.json"),
            "--shadow-sidecar",
            str(tmp_path / "missing.sqlite"),
            "--promotion-reference",
            str(tmp_path / "missing-reference.json"),
            "--promotion-reference-metrics",
            str(tmp_path / "missing-metrics.json"),
            "--output-root",
            str(tmp_path / "output"),
        ]
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["status"] == "blocked"
    assert output["blockers"] == ["promotion_reference_missing"]
