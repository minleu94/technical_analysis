from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

from data_module.portfolio_ml_dataset_assembler import (
    PortfolioMLDatasetAssembler,
    PortfolioMLDatasetAssemblyRequest,
    PortfolioMLDatasetPublication,
)
from scripts.build_ml_allocation_matured_replay_input import (
    _build_replay_input_payload,
    _load_publication_manifest,
    _sha256_json,
    main,
)
from scripts.infer_ml_allocation_copilot import _load_rows
from scripts.train_ml_allocation_copilot import (
    _load_jsonl_shard,
    _merge_shards,
)
from tests.test_portfolio_ml_dataset_assembler import _raw_publication


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def training_publication(
    tmp_path_factory: pytest.TempPathFactory,
) -> PortfolioMLDatasetPublication:
    root = tmp_path_factory.mktemp("matured-replay-publication")
    raw = _raw_publication(root)
    return PortfolioMLDatasetAssembler().build(
        PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=raw.dataset_manifest_paths[
                "all_field_enriched"
            ],
            output_root=root / "training",
            training_as_of="2024-09-01T08:30:00+08:00",
            benchmark_entity_id="TAIEX",
            minimum_train_dates=65,
            test_date_count=21,
            purge_trading_days=60,
            embargo_trading_days=5,
            batch_size=29,
        )
    )


def test_builder_emits_deterministic_single_date_target_free_replay(
    tmp_path: Path,
    training_publication: PortfolioMLDatasetPublication,
    capsys: pytest.CaptureFixture[str],
) -> None:
    replay_path = tmp_path / "allocation_matured_replay.json.gz"
    audit_path = tmp_path / "allocation_matured_replay_audit.json"
    args = _arguments(
        manifest_path=training_publication.manifest_path,
        manifest_hash=training_publication.manifest_hash,
        replay_path=replay_path,
        audit_path=audit_path,
    )

    assert main(args) == 0
    first_replay_bytes = replay_path.read_bytes()
    first_audit_bytes = audit_path.read_bytes()
    assert main(args) == 0
    assert replay_path.read_bytes() == first_replay_bytes
    assert audit_path.read_bytes() == first_audit_bytes

    payload = json.loads(gzip.decompress(first_replay_bytes).decode("utf-8"))
    assert set(payload) == {"schema_version", "rows"}
    assert payload["schema_version"] == "allocation-inference-input-v2"
    assert payload["rows"]
    assert not _contains_key(payload, "targets")
    assert not _contains_key(payload, "horizon_labels")
    replay_dates = {
        row["decision_at"][:10]
        for row in payload["rows"]
    }
    assert len(replay_dates) == 1
    parsed_rows = _load_rows(replay_path)
    assert len(parsed_rows) == len(payload["rows"])
    assert all(row.targets is None for row in parsed_rows)

    shards = tuple(
        _load_jsonl_shard(path)
        for path in training_publication.shard_paths
    )
    latest_source_date = max(
        sample.row.decision_at[:10]
        for sample in _merge_shards(shards).samples
    )
    assert replay_dates == {latest_source_date}

    audit = json.loads(first_audit_bytes.decode("utf-8"))
    assert audit["schema_version"] == (
        "allocation-inference-matured-replay-audit-v1"
    )
    assert audit["mode"] == "matured_replay"
    assert audit["selection_policy"] == (
        "latest_fully_matured_publication_decision_date"
    )
    assert audit["decision_date"] == latest_source_date
    assert audit["publication_manifest_hash"] == (
        training_publication.manifest_hash
    )
    assert audit["inference_input_compressed_hash"] == _hash_bytes(
        first_replay_bytes
    )
    assert audit["all_publication_rows_for_decision_date_selected"] is True
    assert audit["supervised_field_occurrence_count"] == 0
    assert audit["live_data"] is False
    assert audit["current_snapshot_claimed"] is False
    assert audit["formal_oos_allowed"] is False
    assert audit["production_action_allowed"] is False
    assert audit["production_blend_alpha_bp"] == 0
    assert audit["broker_order_allowed"] is False
    audit_body = dict(audit)
    assert audit_body.pop("audit_hash") == _sha256_json(audit_body)

    output_lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert len(output_lines) == 2
    assert all(
        line["status"] == "matured_replay_input_built"
        and line["formal_oos_allowed"] is False
        for line in output_lines
    )


def test_builder_selects_all_rows_for_an_explicit_mature_date(
    tmp_path: Path,
    training_publication: PortfolioMLDatasetPublication,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shards = tuple(
        _load_jsonl_shard(path)
        for path in training_publication.shard_paths
    )
    samples = _merge_shards(shards).samples
    requested_date = min(sample.row.decision_at[:10] for sample in samples)
    expected_symbols = sorted(
        sample.row.symbol
        for sample in samples
        if sample.row.decision_at[:10] == requested_date
    )
    replay_path = tmp_path / "explicit_matured_replay.json.gz"
    audit_path = tmp_path / "explicit_matured_replay_audit.json"
    args = _arguments(
        manifest_path=training_publication.manifest_path,
        manifest_hash=training_publication.manifest_hash,
        replay_path=replay_path,
        audit_path=audit_path,
    )
    args.extend(("--decision-date", requested_date))

    assert main(args) == 0
    payload = json.loads(
        gzip.decompress(replay_path.read_bytes()).decode("utf-8")
    )
    assert sorted(row["symbol"] for row in payload["rows"]) == expected_symbols
    assert {
        row["decision_at"][:10]
        for row in payload["rows"]
    } == {requested_date}
    audit = _read_json(audit_path)
    assert audit["selection_policy"] == (
        "explicit_fully_matured_publication_decision_date"
    )
    assert audit["selected_row_count"] == len(expected_symbols)
    assert json.loads(capsys.readouterr().out)["decision_date"] == requested_date


def test_builder_rejects_valid_gzip_shard_whose_bytes_were_tampered(
    tmp_path: Path,
    training_publication: PortfolioMLDatasetPublication,
    capsys: pytest.CaptureFixture[str],
) -> None:
    publication_root = _copy_publication(training_publication, tmp_path)
    manifest_path = publication_root / "manifest.json"
    manifest = _read_json(manifest_path)
    shard_path = publication_root / manifest["shards"][0]["path"]
    shard_path.write_bytes(
        gzip.compress(
            gzip.decompress(shard_path.read_bytes()) + b"\n",
            mtime=0,
        )
    )
    replay_path = tmp_path / "tampered_matured_replay.json.gz"
    audit_path = tmp_path / "tampered_matured_replay_audit.json"

    assert main(
        _arguments(
            manifest_path=manifest_path,
            manifest_hash=training_publication.manifest_hash,
            replay_path=replay_path,
            audit_path=audit_path,
        )
    ) == 2
    assert not replay_path.exists()
    assert not audit_path.exists()
    error = json.loads(capsys.readouterr().err)
    assert "compressed shard hash mismatch" in error["message"]


def test_builder_rejects_manifest_with_new_self_hash_but_old_custody_hash(
    tmp_path: Path,
    training_publication: PortfolioMLDatasetPublication,
    capsys: pytest.CaptureFixture[str],
) -> None:
    publication_root = _copy_publication(training_publication, tmp_path)
    manifest_path = publication_root / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["dataset_id"] = "poisoned-dataset-id"
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_hash", None)
    manifest["manifest_hash"] = _sha256_json(manifest_body)
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    replay_path = tmp_path / "manifest_poison_matured_replay.json.gz"
    audit_path = tmp_path / "manifest_poison_matured_replay_audit.json"

    assert main(
        _arguments(
            manifest_path=manifest_path,
            manifest_hash=training_publication.manifest_hash,
            replay_path=replay_path,
            audit_path=audit_path,
        )
    ) == 2
    assert not replay_path.exists()
    assert not audit_path.exists()
    error = json.loads(capsys.readouterr().err)
    assert "external custody hash mismatch" in error["message"]


def test_replay_payload_rejects_mixed_decision_dates(
    training_publication: PortfolioMLDatasetPublication,
) -> None:
    manifest, shard_paths = _load_publication_manifest(
        training_publication.manifest_path,
        expected_manifest_hash=training_publication.manifest_hash,
    )
    assert manifest["manifest_hash"] == training_publication.manifest_hash
    samples = _merge_shards(
        tuple(_load_jsonl_shard(path) for path in shard_paths)
    ).samples
    first = samples[0]
    second = next(
        sample
        for sample in samples
        if sample.row.decision_at[:10] != first.row.decision_at[:10]
    )

    with pytest.raises(
        ValueError,
        match="exactly one decision date",
    ):
        _build_replay_input_payload(
            samples=(first, second),
            decision_date=first.row.decision_at[:10],
        )


def test_help_is_utf8_safe_when_parent_encoding_is_cp1252() -> None:
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "scripts"
                / "build_ml_allocation_matured_replay_input.py"
            ),
            "--help",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    decoded = result.stdout.decode("utf-8")
    assert "--expected-publication-manifest-hash" in decoded
    assert "matured replay" in decoded


def _arguments(
    *,
    manifest_path: Path,
    manifest_hash: str,
    replay_path: Path,
    audit_path: Path,
) -> list[str]:
    return [
        "--publication-manifest",
        str(manifest_path),
        "--expected-publication-manifest-hash",
        manifest_hash,
        "--matured-replay-output",
        str(replay_path),
        "--audit-output",
        str(audit_path),
    ]


def _copy_publication(
    publication: PortfolioMLDatasetPublication,
    root: Path,
) -> Path:
    target = root / "publication"
    shutil.copytree(publication.publication_directory, target)
    return target


def _read_json(path: Path) -> dict[str, Any]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key(item, key) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_key(item, key) for item in value)
    return False


def _hash_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
