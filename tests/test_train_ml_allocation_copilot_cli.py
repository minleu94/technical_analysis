from __future__ import annotations

from dataclasses import asdict
import gzip
from io import BytesIO
import json
from pathlib import Path

import joblib

from scripts.train_ml_allocation_copilot import main
from tests.fixtures.ml_allocation_training_support import _sample


def _fold_payloads() -> list[dict[str, object]]:
    definitions = (
        (19, 80, 85),
        (45, 106, 111),
        (71, 132, 137),
        (97, 158, 163),
    )
    folds: list[dict[str, object]] = []
    for fold_index, (train_end, test_start, test_end) in enumerate(
        definitions, start=1
    ):
        first_test = _sample(test_start)
        last_test = _sample(test_end - 1)
        folds.append(
            {
                "fold_id": f"fold-{fold_index:03d}",
                "train_row_ids": [
                    f"row-{index:03d}" for index in range(train_end)
                ],
                "test_row_ids": [
                    f"row-{index:03d}"
                    for index in range(test_start, test_end)
                ],
                "test_start": first_test.row.decision_at[:10],
                "test_end": last_test.row.decision_at[:10],
                "purge_trading_days": 60,
                "embargo_trading_days": 5,
            }
        )
    return folds


def _shard_payload(
    *,
    start: int,
    end: int,
    include_folds: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "allocation-training-input-v2",
        "dataset_id": "frozen-v4-cli-test",
        "training_as_of": "2026-12-31T23:59:59+08:00",
        "horizons": [5, 10, 20, 60],
        "feature_packs": [
            {
                "pack_id": "price",
                "feature_ids": ["return_20d_bp", "volume_rank_bp"],
            }
        ],
        "samples": [
            asdict(_sample(index)) for index in range(start, end)
        ],
        "assembly_blockers": ["broker_history_remains_research_shadow"],
    }
    if include_folds:
        payload["folds"] = _fold_payloads()
    return payload


def test_cli_merges_plain_and_gzip_shards_and_commits_frozen_outputs(
    tmp_path: Path,
    capsys,
) -> None:
    first_input = tmp_path / "2025-a.json"
    first_input.write_text(
        json.dumps(
            _shard_payload(start=0, end=80, include_folds=True),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second_input = tmp_path / "2025-b.json.gz"
    second_input.write_bytes(
        gzip.compress(
            json.dumps(
                _shard_payload(start=80, end=163, include_folds=False),
                ensure_ascii=False,
            ).encode("utf-8")
        )
    )
    artifact = tmp_path / "allocation.joblib"
    audit = tmp_path / "allocation.audit.json"
    manifest = tmp_path / "allocation.manifest.json"

    assert main(
        [
            "--input",
            str(first_input),
            "--input",
            str(second_input),
            "--artifact-output",
            str(artifact),
            "--audit-output",
            str(audit),
            "--manifest-output",
            str(manifest),
            "--random-state",
            "7",
            "--hgb-max-iter",
            "2",
        ]
    ) == 0

    stdout = json.loads(capsys.readouterr().out)
    assert stdout["status"] == "training_completed"
    assert stdout["production_alpha_bp"] == 0
    assert stdout["production_action_allowed"] is False
    assert artifact.is_file()
    assert audit.is_file()
    assert manifest.is_file()
    assert not tuple(tmp_path.glob("*.staged"))

    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert (
        manifest_payload["schema_version"]
        == "allocation-training-output-manifest-v2"
    )
    assert manifest_payload["training_row_count"] == 163
    assert len(manifest_payload["input_shards"]) == 2
    assert manifest_payload["production_alpha_bp"] == 0
    assert manifest_payload["production_action_allowed"] is False
    assert manifest_payload["formal_oos_allowed"] is False
    assert (
        "actual_db_dataset_assembly_not_performed_requires_"
        "eligibility_governed_frozen_shards"
        in manifest_payload["blockers"]
    )
    assert (
        "broker_history_remains_research_shadow"
        in manifest_payload["blockers"]
    )
    assert (
        manifest_payload["artifact_hash"]
        == stdout["artifact_hash"]
    )

    audit_payload = json.loads(audit.read_text(encoding="utf-8"))
    assert audit_payload["artifact_hash"] == manifest_payload["artifact_hash"]
    artifact_payload = joblib.load(BytesIO(artifact.read_bytes()))
    assert artifact_payload["dataset_id"] == "frozen-v4-cli-test"
    assert artifact_payload["dataset_identity_hash"]
    assert artifact_payload["dataset_manifest_file_hash"] == (
        "sha256:" + ("0" * 64)
    )
    assert artifact_payload["production_alpha_bp"] == 0
    assert artifact_payload["production_action_allowed"] is False


def test_cli_rejects_wildcard_feature_pack_without_writing_outputs(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "wildcard.json"
    payload = _shard_payload(start=0, end=1, include_folds=False)
    payload["feature_packs"] = [
        {"pack_id": "price", "feature_ids": ["*"]}
    ]
    source.write_text(json.dumps(payload), encoding="utf-8")
    artifact = tmp_path / "forbidden.joblib"
    audit = tmp_path / "forbidden.audit.json"
    manifest = tmp_path / "forbidden.manifest.json"

    assert main(
        [
            "--input",
            str(source),
            "--artifact-output",
            str(artifact),
            "--audit-output",
            str(audit),
            "--manifest-output",
            str(manifest),
        ]
    ) == 2

    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "blocked"
    assert "wildcard is forbidden" in error["message"]
    assert error["production_alpha_bp"] == 0
    assert not artifact.exists()
    assert not audit.exists()
    assert not manifest.exists()


def test_cli_refuses_conflicting_shard_metadata_before_training(
    tmp_path: Path,
    capsys,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(
        json.dumps(_shard_payload(start=0, end=1, include_folds=False)),
        encoding="utf-8",
    )
    conflicting = _shard_payload(start=1, end=2, include_folds=False)
    conflicting["dataset_id"] = "different-dataset"
    second.write_text(json.dumps(conflicting), encoding="utf-8")

    assert main(
        [
            "--input",
            str(first),
            "--input",
            str(second),
            "--artifact-output",
            str(tmp_path / "a.joblib"),
            "--audit-output",
            str(tmp_path / "a.audit.json"),
            "--manifest-output",
            str(tmp_path / "a.manifest.json"),
        ]
    ) == 2
    error = json.loads(capsys.readouterr().err)
    assert "share one dataset_id" in error["message"]
