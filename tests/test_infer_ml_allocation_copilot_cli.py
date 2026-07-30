from __future__ import annotations

from dataclasses import asdict
import gzip
import json
from pathlib import Path

import pytest

from app_module.ml_allocation_inference_service import (
    _feature_snapshot_hash,
    _sha256_json,
)
from scripts.infer_ml_allocation_copilot import (
    INPUT_SCHEMA_VERSION,
    main,
)
from tests.test_ml_allocation_inference_service import _inference_rows
from tests.test_ml_allocation_training_service import (  # noqa: F401
    folds,
    samples,
    training_result,
)


_POLICY_HASH = "sha256:" + ("d" * 64)


def _write_input(path: Path, *, targets: object | None = None) -> None:
    rows = [asdict(row) for row in _inference_rows()]
    if targets is not None:
        rows[0]["targets"] = targets
    payload = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "rows": rows,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    path.write_bytes(gzip.compress(encoded, mtime=0))


def _args(
    *,
    artifact_path: Path,
    artifact_hash: str,
    dataset_id: str,
    input_path: Path,
    proposal_output: Path,
    audit_output: Path,
) -> list[str]:
    rows = tuple(sorted(_inference_rows(), key=lambda row: row.symbol))
    universe_hash = _sha256_json(
        [
            {
                "row_id": row.row_id,
                "symbol": row.symbol,
                "feature_snapshot_hash": _feature_snapshot_hash(row),
            }
            for row in rows
        ]
    )
    return [
        "--artifact",
        str(artifact_path),
        "--artifact-hash",
        artifact_hash,
        "--dataset-id",
        dataset_id,
        "--input",
        str(input_path),
        "--model-id",
        "allocation-model:test",
        "--universe-id",
        "twse:test",
        "--policy-id",
        "balanced:test",
        "--policy-hash",
        _POLICY_HASH,
        "--expected-universe-hash",
        universe_hash,
        "--proposal-output",
        str(proposal_output),
        "--audit-output",
        str(audit_output),
    ]


def test_cli_reads_json_gz_and_writes_deterministic_immutable_outputs(
    tmp_path: Path,
    training_result,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_path = tmp_path / "model.joblib"
    input_path = tmp_path / "current_rows.json.gz"
    proposal_output = tmp_path / "proposal.json"
    audit_output = tmp_path / "audit.json"
    artifact_path.write_bytes(training_result.artifact_bytes)
    _write_input(input_path)
    args = _args(
        artifact_path=artifact_path,
        artifact_hash=training_result.artifact_hash,
        dataset_id=training_result.dataset_id,
        input_path=input_path,
        proposal_output=proposal_output,
        audit_output=audit_output,
    )

    assert main(args) == 0
    first_stdout = json.loads(capsys.readouterr().out)
    first_proposal = proposal_output.read_bytes()
    first_audit = audit_output.read_bytes()

    # 相同 immutable 輸出可安全重播，但不得產生不同內容或殘留 staged 檔。
    assert main(args) == 0
    second_stdout = json.loads(capsys.readouterr().out)
    assert proposal_output.read_bytes() == first_proposal
    assert audit_output.read_bytes() == first_audit
    assert first_stdout["proposal_hash"] == second_stdout["proposal_hash"]
    assert first_stdout["replay_hash"] == second_stdout["replay_hash"]
    assert list(tmp_path.glob(".*.staged")) == []

    output = json.loads(first_proposal)
    audit = json.loads(first_audit)
    proposal = output["proposal"]
    requested = proposal["requested_weights"]
    assert (
        sum(requested["symbol_weights_bp"].values())
        + requested["cash_weight_bp"]
        == 10_000
    )
    assert sum(proposal["feature_family_weights_bp"].values()) == 10_000
    assert output["proposal_hash"] == audit["proposal_hash"]
    assert output["replay_hash"] == audit["replay_hash"]
    assert proposal["formal_oos_allowed"] is False
    assert proposal["production_action_allowed"] is False
    assert proposal["production_blend_alpha_bp"] == 0
    assert proposal["broker_order_allowed"] is False


def test_cli_rejects_tampered_artifact_before_writing_outputs(
    tmp_path: Path,
    training_result,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_path = tmp_path / "model.joblib"
    input_path = tmp_path / "current_rows.json.gz"
    proposal_output = tmp_path / "proposal.json"
    audit_output = tmp_path / "audit.json"
    artifact_path.write_bytes(training_result.artifact_bytes + b"tamper")
    _write_input(input_path)

    assert (
        main(
            _args(
                artifact_path=artifact_path,
                artifact_hash=training_result.artifact_hash,
                dataset_id=training_result.dataset_id,
                input_path=input_path,
                proposal_output=proposal_output,
                audit_output=audit_output,
            )
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert error["message"] == "artifact hash mismatch"
    assert error["production_blend_alpha_bp"] == 0
    assert not proposal_output.exists()
    assert not audit_output.exists()


def test_cli_rejects_teacher_targets_and_unknown_inference_data(
    tmp_path: Path,
    training_result,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_path = tmp_path / "model.joblib"
    input_path = tmp_path / "current_rows.json.gz"
    proposal_output = tmp_path / "proposal.json"
    audit_output = tmp_path / "audit.json"
    artifact_path.write_bytes(training_result.artifact_bytes)
    _write_input(input_path, targets={"oracle": True})

    assert (
        main(
            _args(
                artifact_path=artifact_path,
                artifact_hash=training_result.artifact_hash,
                dataset_id=training_result.dataset_id,
                input_path=input_path,
                proposal_output=proposal_output,
                audit_output=audit_output,
            )
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert error["message"] == "inference row targets must be absent or null"
    assert not proposal_output.exists()
    assert not audit_output.exists()


def test_cli_refuses_to_overwrite_different_immutable_output(
    tmp_path: Path,
    training_result,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_path = tmp_path / "model.joblib"
    input_path = tmp_path / "current_rows.json.gz"
    proposal_output = tmp_path / "proposal.json"
    audit_output = tmp_path / "audit.json"
    artifact_path.write_bytes(training_result.artifact_bytes)
    _write_input(input_path)
    proposal_output.write_bytes(b"different")

    assert (
        main(
            _args(
                artifact_path=artifact_path,
                artifact_hash=training_result.artifact_hash,
                dataset_id=training_result.dataset_id,
                input_path=input_path,
                proposal_output=proposal_output,
                audit_output=audit_output,
            )
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert "refusing to overwrite different immutable output" in error["message"]
    assert proposal_output.read_bytes() == b"different"
    assert not audit_output.exists()
    assert list(tmp_path.glob(".*.staged")) == []
