from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest

from data_module.portfolio_ml_out_of_core_store import (
    LABEL_FIELDS,
    TARGET_FIELDS,
    STORE_SCHEMA_VERSION,
    YEAR_SCHEMA_VERSION,
)
from ml_module import allocation_out_of_core_training_service as ooc_module
from ml_module.allocation_out_of_core_training_service import (
    AllocationOutOfCoreTrainingRequest,
    AllocationOutOfCoreTrainingService,
)
from data_module.portfolio_ml_target_diagnostics import (
    TargetDiagnosticError,
    diagnose_direct_numeric_store,
    evaluate_allocation_teacher_eligibility,
)
from scripts.diagnose_ml_allocation_target_degeneracy import main


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _with_hash(payload: dict[str, object]) -> dict[str, object]:
    result = dict(payload)
    result["manifest_hash"] = _payload_hash(result)
    return result


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _canonical_json(payload) + "\n",
        encoding="utf-8",
    )


def _artifact(path: Path, content: bytes) -> dict[str, object]:
    path.write_bytes(content)
    return {
        "path": path.name,
        "byte_count": len(content),
        "file_sha256": _file_hash(path),
    }


def _target_summary(*, non_cash: bool = False) -> dict[str, dict[str, int]]:
    values = {
        field: {
            "min": 0,
            "max": 0,
            "nonzero_count": 0,
            "observed_count": 2,
        }
        for field in TARGET_FIELDS
    }
    values["cash_bp"] = {
        "min": 10_000,
        "max": 10_000,
        "nonzero_count": 2,
        "observed_count": 2,
    }
    if non_cash:
        values["target_weight_bp"] = {
            "min": 0,
            "max": 2_000,
            "nonzero_count": 1,
            "observed_count": 2,
        }
        values["cash_bp"] = {
            "min": 8_000,
            "max": 10_000,
            "nonzero_count": 2,
            "observed_count": 2,
        }
    return values


def _teacher_diagnostics(
    *,
    non_cash: bool = False,
    unknown_sector_count: int = 0,
) -> dict[str, int]:
    return {
        "decision_date_count": 2,
        "label_row_count": 2,
        "input_candidate_count": 4,
        "eligible_candidate_count": 4 - unknown_sector_count,
        "unknown_sector_candidate_count": unknown_sector_count,
        "teacher_incomplete_decision_count": 0,
        "non_cash_target_decision_count": 2 if non_cash else 0,
        "cash_only_target_decision_count": 0 if non_cash else 2,
    }


def _teacher_input_provenance(tmp_path: Path) -> dict[str, object]:
    decision_dates = ["2020-01-02", "2020-01-03"]
    decision_cutoffs = {
        "2020-01-02": "2020-01-02T08:30:00+08:00",
        "2020-01-03": "2020-01-03T08:30:00+08:00",
    }
    decision_rows = [
        {
            "decision_date": decision_date,
            "candidate_row_count": 2,
            "eligible_candidate_count": 2,
            "complete_candidate_set": True,
            "target_mode": "cash_only",
        }
        for decision_date in decision_dates
    ]
    sources: dict[str, object] = {}
    for index, source_name in enumerate(
        (
            "pit_sector_membership",
            "causal_non_cash_portfolio_ledger",
            "formal_rule_champion_snapshot_history",
        )
    ):
        readback = tmp_path / f"{source_name}.json"
        source_schema_version = f"{source_name}.v1"
        source_identity = {
            "source_name": source_name,
            "source_schema_version": source_schema_version,
            "dataset_id": f"fixture-{index}",
        }
        source_identity_hash = _payload_hash(source_identity)
        manifest = _with_hash(
            {
                "source_name": source_name,
                "source_schema_version": source_schema_version,
                "source_identity_hash": source_identity_hash,
                "storage_mode": "read_only",
                "decision_dates": decision_dates,
                "decision_cutoffs": decision_cutoffs,
                "row_count": 2,
            }
        )
        manifest_path = tmp_path / f"{source_name}.manifest.json"
        _write_json(manifest_path, manifest)
        rows = [
            {
                **row,
                "available_at": cutoff.replace("08:30:00", "08:00:00"),
            }
            for row, cutoff in zip(decision_rows, decision_cutoffs.values())
        ]
        receipt = {
            "schema_version": "allocation-teacher-input-readback.v1",
            "source_name": source_name,
            "source_schema_version": source_schema_version,
            "source_identity": source_identity,
            "source_identity_hash": source_identity_hash,
            "source_manifest_hash": manifest["manifest_hash"],
            "decision_dates": decision_dates,
            "decision_cutoffs": decision_cutoffs,
            "rows": rows,
            "rows_hash": _payload_hash(rows),
            "custody": {
                "access_mode": "read_only",
                "query_only": True,
                "write_performed": False,
            },
        }
        receipt["receipt_hash"] = _payload_hash(receipt)
        _write_json(readback, receipt)
        sources[source_name] = {
            "readback_path": str(readback),
            "readback_file_sha256": _file_hash(readback),
            "readback_verified": True,
            "source_manifest_path": str(manifest_path),
            "source_manifest_file_sha256": _file_hash(manifest_path),
            "source_manifest_hash": manifest["manifest_hash"],
            "source_identity_hash": source_identity_hash,
            "source_schema_version": source_schema_version,
            "source_row_count": 2,
            "covered_decision_dates": decision_dates,
            "read_only": True,
            "available_before_decision": True,
        }
    return {
        "schema_version": "allocation-teacher-input-provenance.v1",
        "decision_dates": decision_dates,
        "decision_date_count": 2,
        "decision_cutoffs": decision_cutoffs,
        "input_candidate_count": 4,
        "eligible_candidate_count": 4,
        "decision_rows": decision_rows,
        "sources": sources,
    }


def _build_fixture(
    root: Path,
    *,
    sectors: tuple[str | None, str | None] = (None, None),
    blockers: tuple[str, ...] = (
        "formal_rule_champion_snapshot_history_missing_formal_replay_blocked",
        "pit_sector_membership_missing_teacher_new_positions_disabled",
        "portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned",
    ),
) -> Path:
    run = root / "direct-run"
    year_directory = run / "year=2020"
    year_directory.mkdir(parents=True, exist_ok=True)
    row_count = 2
    targets = np.asarray(
        (
            (0, 0, 0, 0, 10_000, 0),
            (0, 0, 0, 0, 10_000, 0),
        ),
        dtype="<i4",
    )
    labels = np.zeros(
        (row_count, 4, len(LABEL_FIELDS)),
        dtype="<i4",
    )
    labels[0, 2, 0] = 100
    labels[1, 2, 0] = -50
    labels[0, 2, 3] = -200
    labels[1, 2, 3] = 300
    masks = np.zeros(labels.shape, dtype="u1")
    targets_path = year_directory / "targets.i32"
    labels_path = year_directory / "labels.i32"
    masks_path = year_directory / "labels.masks.u8"
    targets.tofile(targets_path)
    labels.tofile(labels_path)
    masks.tofile(masks_path)

    rows_path = year_directory / "rows.sqlite"
    with sqlite3.connect(rows_path) as connection:
        connection.execute(
            "CREATE TABLE rows ("
            "local_row_index INTEGER PRIMARY KEY,"
            "target_available_at TEXT NOT NULL,"
            "max_label_available_at TEXT NOT NULL,"
            "portfolio_state_hash TEXT NOT NULL,"
            "decision_date TEXT NOT NULL"
            ")"
        )
        connection.executemany(
            "INSERT INTO rows VALUES (?, ?, ?, ?, ?)",
            (
                (
                    0,
                    "2020-01-03T08:30:00+08:00",
                    "2020-01-06T08:30:00+08:00",
                    "state-a",
                    "2020-01-02",
                ),
                (
                    1,
                    "2020-01-04T08:30:00+08:00",
                    "2020-01-07T08:30:00+08:00",
                    "state-b",
                    "2020-01-03",
                ),
            ),
        )

    replay_path = year_directory / "replay_source.sqlite"
    with sqlite3.connect(replay_path) as connection:
        connection.execute(
            "CREATE TABLE replay_source ("
            "local_row_index INTEGER PRIMARY KEY,"
            "sector_id TEXT,"
            "price_event_at TEXT,"
            "price_available_at TEXT,"
            "open_int INTEGER,"
            "close_int INTEGER,"
            "volume_shares INTEGER,"
            "median_volume_20d_shares INTEGER,"
            "rule_score_bp INTEGER"
            ")"
        )
        connection.executemany(
            "INSERT INTO replay_source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    0,
                    sectors[0],
                    "2020-01-01T14:30:00+08:00",
                    "2020-01-02T08:00:00+08:00",
                    100,
                    101,
                    1_000,
                    900,
                    10,
                ),
                (
                    1,
                    sectors[1],
                    "2020-01-02T14:30:00+08:00",
                    "2020-01-03T08:00:00+08:00",
                    101,
                    102,
                    1_100,
                    950,
                    20,
                ),
            ),
        )

    artifacts = [
        _artifact(targets_path, targets_path.read_bytes()),
        _artifact(labels_path, labels_path.read_bytes()),
        _artifact(masks_path, masks_path.read_bytes()),
        _artifact(rows_path, rows_path.read_bytes()),
        _artifact(replay_path, replay_path.read_bytes()),
    ]
    year_manifest = _with_hash(
        {
            "schema_version": YEAR_SCHEMA_VERSION,
            "year": 2020,
            "year_ordinal": 0,
            "row_count": row_count,
            "artifacts": artifacts,
        }
    )
    year_manifest_path = year_directory / "manifest.json"
    _write_json(year_manifest_path, year_manifest)

    store_manifest = _with_hash(
        {
            "schema_version": STORE_SCHEMA_VERSION,
            "status": "complete",
            "run_id": "diagnostic-fixture",
            "dataset_identity_hash": "sha256:" + "a" * 64,
            "training_as_of": "2020-01-10T08:30:00+08:00",
            "horizons": [5, 10, 20, 60],
            "target_fields": list(TARGET_FIELDS),
            "label_fields": list(LABEL_FIELDS),
            "row_count": row_count,
            "years": [year_manifest],
            "assembly_blockers": list(blockers),
        }
    )
    manifest_path = run / "manifest.json"
    _write_json(manifest_path, store_manifest)
    return manifest_path


def test_diagnostic_separates_sector_block_from_variable_label(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture(tmp_path)

    report = diagnose_direct_numeric_store(manifest_path)

    assert report["classification"]["category"] == (
        "data_blocked_no_eligible_sector_candidates"
    )
    assert report["classification"]["matured_benchmark_label_varies"] is True
    assert report["classification"]["numeric_targets_constant_zero"] is True
    assert report["candidate_inputs"]["sector_missing_count"] == 2
    assert report["candidate_input_missing_counts"]["sector_missing_count"] == 2
    assert report["maturity"]["target_available_mature_count"] == 2
    assert report["provenance"]["label_producer"].endswith(
        "_build_label_spool"
    )
    assert report["provenance"]["labels_are_teacher_independent"] is True
    assert report["labels"]["fields"]["h20.benchmark_excess_return_bp"] == {
        "min": -50,
        "max": 100,
        "nonzero_count": 2,
        "observed_count": 2,
        "missing_count": 0,
    }
    assert report["years"][0]["target_summary"]["cash_bp"]["min"] == 10_000
    assert report["allocation_teacher_eligibility"]["allowed"] is False
    assert report["allocation_teacher_eligibility"]["status"] == (
        "blocked_missing_formal_teacher_inputs"
    )


def test_diagnostic_identifies_policy_cash_only_when_sector_is_observed(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture(
        tmp_path,
        sectors=("S1", "S1"),
        blockers=(
            "portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned",
        ),
    )

    report = diagnose_direct_numeric_store(manifest_path)

    assert report["classification"]["category"] == (
        "strategy_or_policy_cash_only_with_candidates"
    )
    assert report["classification"]["sector_candidates_all_missing"] is False
    assert report["candidate_inputs"]["sector_observed_count"] == 2


def test_teacher_gate_rejects_missing_formal_inputs_even_with_nonconstant_targets(
    ) -> None:
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(non_cash=True),
        assembly_blockers=(
            "pit_sector_membership_missing_teacher_new_positions_disabled",
        ),
        teacher_target_diagnostics=_teacher_diagnostics(non_cash=True),
    )

    assert gate["allowed"] is False
    assert gate["status"] == "blocked_missing_formal_teacher_inputs"
    assert gate["uses_future_labels"] is False
    assert "missing_formal_teacher_input:pit_sector_membership_missing_teacher_new_positions_disabled" in gate["reasons"]
    assert gate["outcome_research_allowed"] is True


def test_teacher_gate_blocks_counter_only_candidates_without_source_readback(
    ) -> None:
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(),
        teacher_target_diagnostics=_teacher_diagnostics(),
    )

    assert gate["allowed"] is False
    assert gate["status"] == "blocked_missing_teacher_provenance"
    assert gate["reasons"] == ["teacher_input_provenance_missing"]


def test_teacher_gate_allows_only_hash_bound_complete_source_readback(
    tmp_path: Path,
) -> None:
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(),
        teacher_target_diagnostics=_teacher_diagnostics(),
        teacher_input_provenance=_teacher_input_provenance(tmp_path),
    )

    assert gate["allowed"] is True
    assert gate["status"] == "allowed_strategy_cash_only_with_candidates"
    assert gate["teacher_input_provenance_present"] is True
    assert gate["target_summary_scope"]["all_cash_target"] is True
    assert gate["formal_oos_allowed"] is False
    assert gate["production_alpha_bp"] == 0


def test_teacher_gate_rejects_arbitrary_bytes_with_correct_outer_hash(
    tmp_path: Path,
) -> None:
    provenance = _teacher_input_provenance(tmp_path)
    sources = provenance["sources"]
    assert isinstance(sources, dict)
    source = sources["pit_sector_membership"]
    assert isinstance(source, dict)
    readback = Path(str(source["readback_path"]))
    readback.write_text("{}\n", encoding="utf-8")
    source["readback_file_sha256"] = _file_hash(readback)

    with pytest.raises(TargetDiagnosticError, match="receipt_hash"):
        evaluate_allocation_teacher_eligibility(
            target_summary=_target_summary(),
            teacher_target_diagnostics=_teacher_diagnostics(),
            teacher_input_provenance=provenance,
        )


def test_teacher_gate_rejects_late_source_even_when_receipt_flags_are_true(
    tmp_path: Path,
) -> None:
    provenance = _teacher_input_provenance(tmp_path)
    sources = provenance["sources"]
    assert isinstance(sources, dict)
    source = sources["pit_sector_membership"]
    assert isinstance(source, dict)
    readback = Path(str(source["readback_path"]))
    receipt = json.loads(readback.read_text(encoding="utf-8"))
    receipt["rows"][0]["available_at"] = "2020-01-02T09:00:00+08:00"
    receipt["rows_hash"] = _payload_hash(receipt["rows"])
    receipt["receipt_hash"] = _payload_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    _write_json(readback, receipt)
    source["readback_file_sha256"] = _file_hash(readback)
    source["readback_verified"] = True
    source["read_only"] = True
    source["available_before_decision"] = True

    with pytest.raises(TargetDiagnosticError, match="after decision"):
        evaluate_allocation_teacher_eligibility(
            target_summary=_target_summary(),
            teacher_target_diagnostics=_teacher_diagnostics(),
            teacher_input_provenance=provenance,
        )


def test_teacher_gate_rejects_receipt_identity_or_date_tamper(
    tmp_path: Path,
) -> None:
    provenance = _teacher_input_provenance(tmp_path)
    sources = provenance["sources"]
    assert isinstance(sources, dict)
    source = sources["pit_sector_membership"]
    assert isinstance(source, dict)
    readback = Path(str(source["readback_path"]))
    receipt = json.loads(readback.read_text(encoding="utf-8"))
    receipt["source_identity"]["dataset_id"] = "tampered"
    receipt["source_identity_hash"] = _payload_hash(receipt["source_identity"])
    receipt["receipt_hash"] = _payload_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    _write_json(readback, receipt)
    source["readback_file_sha256"] = _file_hash(readback)

    with pytest.raises(TargetDiagnosticError, match="source identity hash mismatch"):
        evaluate_allocation_teacher_eligibility(
            target_summary=_target_summary(),
            teacher_target_diagnostics=_teacher_diagnostics(),
            teacher_input_provenance=provenance,
        )

    # 第二個負例在相同測試中確認 receipt 的日期宣告不能偏離 outer scope。
    receipt = json.loads(readback.read_text(encoding="utf-8"))
    receipt["source_identity"]["dataset_id"] = "fixture-0"
    receipt["source_identity_hash"] = _payload_hash(receipt["source_identity"])
    receipt["decision_dates"] = ["2020-01-02", "2020-01-04"]
    receipt["receipt_hash"] = _payload_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    _write_json(readback, receipt)
    source["readback_file_sha256"] = _file_hash(readback)

    with pytest.raises(TargetDiagnosticError, match="receipt has partial date coverage"):
        evaluate_allocation_teacher_eligibility(
            target_summary=_target_summary(),
            teacher_target_diagnostics=_teacher_diagnostics(),
            teacher_input_provenance=provenance,
        )


def test_teacher_gate_rejects_partial_decision_date_candidate_coverage(
    tmp_path: Path,
) -> None:
    provenance = _teacher_input_provenance(tmp_path)
    rows = provenance["decision_rows"]
    assert isinstance(rows, list)
    rows[0] = {
        **rows[0],
        "candidate_row_count": 4,
        "eligible_candidate_count": 4,
    }
    rows[1] = {
        **rows[1],
        "candidate_row_count": 0,
        "eligible_candidate_count": 0,
    }
    with pytest.raises(
        TargetDiagnosticError,
        match="receipt row does not bind decision row",
    ):
        evaluate_allocation_teacher_eligibility(
            target_summary=_target_summary(),
            teacher_target_diagnostics=_teacher_diagnostics(),
            teacher_input_provenance=provenance,
        )


def test_teacher_gate_rejects_target_row_count_mismatch(
    tmp_path: Path,
) -> None:
    diagnostics = _teacher_diagnostics()
    diagnostics["label_row_count"] = 3
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(),
        teacher_target_diagnostics=diagnostics,
        teacher_input_provenance=_teacher_input_provenance(tmp_path),
    )

    assert gate["allowed"] is False
    assert "target_summary_row_count_mismatch" in gate["reasons"]


def test_teacher_gate_treats_cash_only_state_fallback_as_missing_ledger() -> None:
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(),
        teacher_target_diagnostics=_teacher_diagnostics(),
        portfolio_state_policy={"cash_only_fallback": True},
    )

    assert gate["allowed"] is False
    assert gate["status"] == "blocked_missing_formal_teacher_inputs"
    assert any(
        "portfolio_ledger_missing_cash_only_fallback" in str(reason)
        for reason in gate["reasons"]
    )


def test_teacher_gate_rejects_unclassified_cash_without_provenance() -> None:
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(),
    )

    assert gate["allowed"] is False
    assert gate["status"] == "blocked_missing_teacher_provenance"
    assert gate["reasons"] == ["teacher_target_diagnostics_missing"]


def test_teacher_gate_rejects_unknown_sector_or_unbalanced_diagnostics(
    tmp_path: Path,
) -> None:
    gate = evaluate_allocation_teacher_eligibility(
        target_summary=_target_summary(non_cash=True),
        teacher_target_diagnostics=_teacher_diagnostics(
            non_cash=True,
            unknown_sector_count=1,
        ),
        teacher_input_provenance=_teacher_input_provenance(tmp_path),
    )

    assert gate["allowed"] is False
    assert gate["status"] == "blocked_incomplete_teacher_eligibility"
    assert "unknown_sector_candidate_count_is_nonzero" in gate["reasons"]


def test_teacher_gate_rejects_target_summary_contract_tamper() -> None:
    summary = _target_summary()
    summary.pop("cash_bp")
    with pytest.raises(TargetDiagnosticError, match="missing field: cash_bp"):
        evaluate_allocation_teacher_eligibility(target_summary=summary)


def test_ooc_training_gate_stops_before_output_or_fit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = np.asarray(
        (
            (0, 0, 0, 0, 10_000, 0),
            (0, 0, 0, 0, 10_000, 0),
        ),
        dtype="<i4",
    )
    fake_store = type(
        "FakeStore",
        (),
        {
            "manifest": {
                "assembly_blockers": [
                    "pit_sector_membership_missing_teacher_new_positions_disabled",
                ],
            },
            "years": (
                type(
                    "FakeYear",
                    (),
                    {"row_count": 2, "targets": targets},
                )(),
            ),
        },
    )()
    monkeypatch.setattr(
        ooc_module,
        "_NumericStore",
        lambda *args, **kwargs: fake_store,
    )
    preflight_calls: list[str] = []

    def _unexpected_preflight(**kwargs: object) -> object:
        preflight_calls.append(str(kwargs.get("stage")))
        raise AssertionError("teacher rejection must precede capacity preflight")

    monkeypatch.setattr(ooc_module, "preflight_capacity", _unexpected_preflight)
    output_root = tmp_path / "must-not-create"
    request = AllocationOutOfCoreTrainingRequest(
        store_manifest_path=tmp_path / "source-manifest.json",
        output_root=output_root,
        algorithms=("ridge_logistic",),
        horizons=(5,),
        memory_budget_mb=256,
    )

    with pytest.raises(
        ValueError,
        match="allocation teacher eligibility gate blocked",
    ):
        AllocationOutOfCoreTrainingService().train(request)
    assert preflight_calls == []
    assert not output_root.exists()


def test_diagnostic_fails_closed_on_manifest_or_artifact_tamper(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["run_id"] = "tampered"
    manifest_path.write_text(
        _canonical_json(payload) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TargetDiagnosticError, match="manifest_hash mismatch"):
        diagnose_direct_numeric_store(manifest_path)

    manifest_path = _build_fixture(tmp_path / "artifact-tamper")
    target_path = manifest_path.parent / "year=2020" / "targets.i32"
    tampered = bytearray(target_path.read_bytes())
    tampered[0] ^= 1
    target_path.write_bytes(tampered)
    with pytest.raises(TargetDiagnosticError, match="local artifact hash mismatch"):
        diagnose_direct_numeric_store(manifest_path)


def test_diagnostic_cli_writes_external_report_and_protects_source(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture(tmp_path)
    original_manifest_bytes = manifest_path.read_bytes()
    report_path = tmp_path / "repo-output" / "diagnostic.json"

    assert main(
        [
            "--manifest",
            str(manifest_path),
            "--output",
            str(report_path),
        ]
    ) == 0
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert manifest_path.read_bytes() == original_manifest_bytes

    source_output = manifest_path.parent / "must-not-write.json"
    assert main(
        [
            "--manifest",
            str(manifest_path),
            "--output",
            str(source_output),
        ]
    ) == 2
    assert not source_output.exists()
    assert manifest_path.read_bytes() == original_manifest_bytes
