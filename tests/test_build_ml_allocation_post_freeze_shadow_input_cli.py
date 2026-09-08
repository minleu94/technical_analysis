from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any

import pytest

from data_module.ml_pit_year_shard_exporter import (
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.portfolio_ml_dataset_assembler import (
    PortfolioMLDatasetAssembler,
    _base_feature_definitions,
    _feature_pack_payloads,
    _finalize_long_format_definitions,
    _initialize_spool,
    _sha256_json as _assembler_sha256_json,
    _source_manifest_hashes,
)
from scripts.build_ml_allocation_post_freeze_shadow_input import (
    _sha256_json,
    _validate_snapshot_temporal_boundary,
    main,
)
from scripts.infer_ml_allocation_copilot import _load_rows
from tests.test_portfolio_ml_dataset_assembler import _database


ROOT = Path(__file__).resolve().parents[1]
DECISION_AT = "2024-08-28T08:30:00+08:00"
PRICE_DATE = "2024-08-27"
TRAINING_AS_OF = "2024-08-27T08:30:00+08:00"


@dataclass(frozen=True)
class _Fixture:
    raw_dataset_manifest: Path
    raw_publication_hash: str
    raw_dataset_hash: str
    training_manifest: Path
    training_manifest_file_hash: str
    symbols: tuple[str, ...]


@pytest.fixture(scope="module")
def post_freeze_fixture(
    tmp_path_factory: pytest.TempPathFactory,
    synthetic_ml_capacity_module: None,
) -> _Fixture:
    root = tmp_path_factory.mktemp("post-freeze-shadow-input")
    database = root / "source.db"
    _database(database)
    symbols = ("2317", "2330")
    raw = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database,
            output_root=root / "raw",
            decision_at=DECISION_AT,
            history_start_date="2024-01-01",
            symbols=symbols,
            years=(2024,),
            batch_size=31,
        )
    )
    raw_dataset_manifest = raw.dataset_manifest_paths[
        "all_field_enriched"
    ]
    raw_manifest = _read_json(raw_dataset_manifest)

    connection = sqlite3.connect(root / "schema-custody.sqlite")
    try:
        _initialize_spool(connection)
        base_definitions = _base_feature_definitions(raw_manifest)
        runtime_definitions = dict(base_definitions)
        PortfolioMLDatasetAssembler()._spool_raw_observations(
            connection=connection,
            dataset_manifest_path=raw_dataset_manifest,
            manifest=raw_manifest,
            definitions=runtime_definitions,
            source_digest=hashlib.sha256(),
            batch_size=29,
        )
        _finalize_long_format_definitions(
            runtime_definitions=runtime_definitions,
            base_definitions=base_definitions,
        )
    finally:
        connection.close()
    definitions = tuple(
        sorted(
            runtime_definitions.values(),
            key=lambda definition: definition.feature_id,
        )
    )
    feature_packs = _feature_pack_payloads(definitions)
    feature_registry_hash = _assembler_sha256_json(
        {
            "features": [
                asdict(definition) for definition in definitions
            ],
            "feature_packs": feature_packs,
        }
    )
    source_manifest_hashes = _source_manifest_hashes(
        definitions=definitions,
        raw_manifest_hash=raw_manifest["manifest_hash"],
        sector_manifest_hash="sha256:" + ("0" * 64),
    )
    training_payload = {
        "schema_version": "allocation-training-output-manifest-v2",
        "status": "training_completed",
        "dataset_id": "fixture-all-field-allocation",
        "dataset_identity_hash": _assembler_sha256_json(
            {"fixture": "frozen-model-dataset"}
        ),
        "dataset_manifest_file_hash": _assembler_sha256_json(
            {"fixture": "frozen-model-dataset-manifest-file"}
        ),
        "feature_registry_hash": feature_registry_hash,
        "source_manifest_hashes": [
            list(item) for item in source_manifest_hashes
        ],
        "training_as_of": TRAINING_AS_OF,
        "feature_packs": feature_packs,
        "artifact_hash": _assembler_sha256_json(
            {"fixture": "model-artifact"}
        ),
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "formal_oos_allowed": False,
    }
    training_manifest = root / "training_manifest_v2.json"
    training_manifest.write_text(
        json.dumps(
            training_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return _Fixture(
        raw_dataset_manifest=raw_dataset_manifest,
        raw_publication_hash=raw.manifest_hash,
        raw_dataset_hash=raw_manifest["manifest_hash"],
        training_manifest=training_manifest,
        training_manifest_file_hash=_hash_bytes(
            training_manifest.read_bytes()
        ),
        symbols=symbols,
    )


def test_builder_emits_deterministic_target_free_post_freeze_input(
    tmp_path: Path,
    post_freeze_fixture: _Fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "allocation_post_freeze_shadow.json.gz"
    audit_path = tmp_path / "allocation_post_freeze_shadow_audit.json"
    args = _arguments(
        fixture=post_freeze_fixture,
        input_path=input_path,
        audit_path=audit_path,
    )

    assert main(args) == 0
    first_input = input_path.read_bytes()
    first_audit = audit_path.read_bytes()
    assert main(args) == 0
    assert input_path.read_bytes() == first_input
    assert audit_path.read_bytes() == first_audit

    payload = json.loads(gzip.decompress(first_input).decode("utf-8"))
    assert set(payload) == {"schema_version", "rows"}
    assert payload["schema_version"] == "allocation-inference-input-v2"
    assert [row["symbol"] for row in payload["rows"]] == list(
        post_freeze_fixture.symbols
    )
    assert not _contains_key(payload, "targets")
    assert not _contains_key(payload, "horizon_labels")
    parsed_rows = _load_rows(input_path)
    assert len(parsed_rows) == len(post_freeze_fixture.symbols)
    assert all(row.targets is None for row in parsed_rows)
    assert all(row.decision_at == DECISION_AT for row in parsed_rows)
    assert all(
        row.portfolio_state.as_of_date == PRICE_DATE
        and row.portfolio_state.weights.positions_bp == ()
        and row.portfolio_state.weights.cash_bp == 10_000
        and row.portfolio_state.weekly_turnover_used_bp == 0
        for row in parsed_rows
    )
    strict_prefixes = (
        "daily_prices.",
        "technical_indicators.",
        "market_indices.",
        "industry_indices.",
    )
    for row in parsed_rows:
        assert any(
            feature.feature_id.startswith("data_quality.")
            for feature in row.features
        )
        assert all(
            feature.event_at[:10] == PRICE_DATE
            for feature in row.features
            if feature.observed
            and feature.feature_id.startswith(strict_prefixes)
        )

    audit = json.loads(first_audit.decode("utf-8"))
    assert audit["schema_version"] == (
        "allocation-inference-post-freeze-shadow-audit-v2"
    )
    assert audit["model_dataset_identity_hash"].startswith("sha256:")
    assert audit["model_dataset_manifest_file_hash"].startswith("sha256:")
    assert (
        audit["model_dataset_identity_hash"]
        != audit["model_dataset_manifest_file_hash"]
    )
    assert audit["mode"] == "post_freeze_shadow"
    assert audit["decision_at"] == DECISION_AT
    assert audit["expected_price_date"] == PRICE_DATE
    assert audit["raw_publication_manifest_hash"] == (
        post_freeze_fixture.raw_publication_hash
    )
    assert audit["raw_dataset_manifest_hash"] == (
        post_freeze_fixture.raw_dataset_hash
    )
    assert audit["training_manifest_file_hash"] == (
        post_freeze_fixture.training_manifest_file_hash
    )
    assert audit["selected_symbols"] == list(post_freeze_fixture.symbols)
    assert audit["portfolio_state_policy"]["reads_live_portfolio"] is False
    assert audit["supervised_field_occurrence_count"] == 0
    assert audit["live_data"] is False
    assert audit["formal_oos_allowed"] is False
    assert audit["production_action_allowed"] is False
    assert audit["production_blend_alpha_bp"] == 0
    assert audit["broker_order_allowed"] is False
    audit_body = dict(audit)
    assert audit_body.pop("audit_hash") == _sha256_json(audit_body)
    assert audit["inference_input_compressed_hash"] == _hash_bytes(
        first_input
    )

    output_lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert len(output_lines) == 2
    assert all(
        line["status"] == "post_freeze_shadow_input_built"
        and line["production_blend_alpha_bp"] == 0
        for line in output_lines
    )


def test_builder_rejects_raw_cutoff_before_requested_decision(
    tmp_path: Path,
    post_freeze_fixture: _Fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "cutoff_post_freeze_shadow.json.gz"
    audit_path = tmp_path / "cutoff_post_freeze_shadow_audit.json"
    args = _arguments(
        fixture=post_freeze_fixture,
        input_path=input_path,
        audit_path=audit_path,
    )
    _replace_argument(args, "--decision-at", "2024-08-29T08:30:00+08:00")
    _replace_argument(args, "--expected-price-date", "2024-08-28")

    assert main(args) == 2
    assert not input_path.exists()
    assert not audit_path.exists()
    error = json.loads(capsys.readouterr().err)
    assert "raw publication cutoff is inadequate" in error["message"]


def test_builder_rejects_training_manifest_file_hash_tamper(
    tmp_path: Path,
    post_freeze_fixture: _Fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tampered = tmp_path / "training_manifest_v2.json"
    tampered.write_bytes(
        post_freeze_fixture.training_manifest.read_bytes() + b"\n"
    )
    input_path = tmp_path / "hash_post_freeze_shadow.json.gz"
    audit_path = tmp_path / "hash_post_freeze_shadow_audit.json"
    args = _arguments(
        fixture=post_freeze_fixture,
        input_path=input_path,
        audit_path=audit_path,
    )
    _replace_argument(args, "--training-manifest", str(tampered))

    assert main(args) == 2
    assert not input_path.exists()
    assert not audit_path.exists()
    error = json.loads(capsys.readouterr().err)
    assert "training manifest external file hash mismatch" in error["message"]


def test_builder_rejects_frozen_feature_pack_schema_drift(
    tmp_path: Path,
    post_freeze_fixture: _Fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = deepcopy(_read_json(post_freeze_fixture.training_manifest))
    selected_pack = next(
        pack for pack in payload["feature_packs"]
        if len(pack["feature_ids"]) > 1
    )
    selected_pack["feature_ids"].pop()
    drifted = tmp_path / "drifted_training_manifest_v2.json"
    drifted.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    input_path = tmp_path / "drift_post_freeze_shadow.json.gz"
    audit_path = tmp_path / "drift_post_freeze_shadow_audit.json"
    args = _arguments(
        fixture=post_freeze_fixture,
        input_path=input_path,
        audit_path=audit_path,
    )
    _replace_argument(args, "--training-manifest", str(drifted))
    _replace_argument(
        args,
        "--expected-training-manifest-file-hash",
        _hash_bytes(drifted.read_bytes()),
    )

    assert main(args) == 2
    assert not input_path.exists()
    assert not audit_path.exists()
    error = json.loads(capsys.readouterr().err)
    assert "feature packs do not match frozen model" in error["message"]


def test_builder_allows_result_only_official_corporate_action_custody(
    tmp_path: Path,
    post_freeze_fixture: _Fixture,
) -> None:
    payload = deepcopy(_read_json(post_freeze_fixture.training_manifest))
    payload["source_manifest_hashes"] = sorted(
        [
            *payload["source_manifest_hashes"],
            [
                "sidecar:official_corporate_action_ledger",
                "sha256:" + ("c" * 64),
            ],
        ],
        key=lambda item: item[0],
    )
    training_manifest = tmp_path / "official_events_training_manifest.json"
    training_manifest.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    input_path = tmp_path / "official_events_post_freeze_shadow.json.gz"
    audit_path = tmp_path / "official_events_post_freeze_shadow_audit.json"
    args = _arguments(
        fixture=post_freeze_fixture,
        input_path=input_path,
        audit_path=audit_path,
    )
    _replace_argument(args, "--training-manifest", str(training_manifest))
    _replace_argument(
        args,
        "--expected-training-manifest-file-hash",
        _hash_bytes(training_manifest.read_bytes()),
    )

    assert main(args) == 0
    assert input_path.is_file()
    audit = _read_json(audit_path)
    assert [
        "sidecar:official_corporate_action_ledger",
        "sha256:" + ("c" * 64),
    ] in audit["model_source_manifest_hashes"]


def test_builder_rejects_unknown_model_only_source_identity(
    tmp_path: Path,
    post_freeze_fixture: _Fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = deepcopy(_read_json(post_freeze_fixture.training_manifest))
    payload["source_manifest_hashes"] = sorted(
        [
            *payload["source_manifest_hashes"],
            ["sidecar:unknown_unreviewed_source", "sha256:" + ("d" * 64)],
        ],
        key=lambda item: item[0],
    )
    training_manifest = tmp_path / "unknown_source_training_manifest.json"
    training_manifest.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    input_path = tmp_path / "unknown_source_post_freeze_shadow.json.gz"
    audit_path = tmp_path / "unknown_source_post_freeze_shadow_audit.json"
    args = _arguments(
        fixture=post_freeze_fixture,
        input_path=input_path,
        audit_path=audit_path,
    )
    _replace_argument(args, "--training-manifest", str(training_manifest))
    _replace_argument(
        args,
        "--expected-training-manifest-file-hash",
        _hash_bytes(training_manifest.read_bytes()),
    )

    assert main(args) == 2
    assert not input_path.exists()
    assert not audit_path.exists()
    error = json.loads(capsys.readouterr().err)
    assert "unsupported source schema identities" in error["message"]


def test_builder_rejects_non_latest_price_date_as_t_minus_one(
    tmp_path: Path,
    post_freeze_fixture: _Fixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "old_price_post_freeze_shadow.json.gz"
    audit_path = tmp_path / "old_price_post_freeze_shadow_audit.json"
    args = _arguments(
        fixture=post_freeze_fixture,
        input_path=input_path,
        audit_path=audit_path,
    )
    _replace_argument(args, "--expected-price-date", "2024-08-26")

    assert main(args) == 2
    assert not input_path.exists()
    assert not audit_path.exists()
    error = json.loads(capsys.readouterr().err)
    assert "not the latest provable T-1 OHLC date" in error["message"]


def test_temporal_boundary_rejects_available_same_day_price_poison() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _initialize_spool(connection)
        connection.execute(
            """
            INSERT INTO observations(
                scope, entity_key, feature_id, source_table,
                event_at, available_at, revision_id, quality,
                source_row_hash, source_value_hash, value_int, scale,
                stale_after_days, formal_training_eligible, missing_mask,
                quality_blocked_mask
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "stock",
                "2330",
                "daily_prices.close",
                "daily_prices",
                "2024-08-28T14:30:00+08:00",
                "2024-08-28T08:00:00+08:00",
                "poison",
                "accepted",
                "sha256:" + ("a" * 64),
                "sha256:" + ("b" * 64),
                100,
                1,
                5,
                1,
                0,
                0,
            ),
        )
        connection.commit()

        with pytest.raises(
            ValueError,
            match="future-prefix poison",
        ):
            _validate_snapshot_temporal_boundary(
                connection,
                raw_cutoff=datetime.fromisoformat(DECISION_AT),
                decision_at=datetime.fromisoformat(DECISION_AT),
            )
    finally:
        connection.close()


def test_help_is_utf8_safe_when_parent_encoding_is_cp1252() -> None:
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "scripts"
                / "build_ml_allocation_post_freeze_shadow_input.py"
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
    assert "--expected-training-manifest-file-hash" in decoded
    assert "post-freeze" in decoded


def _arguments(
    *,
    fixture: _Fixture,
    input_path: Path,
    audit_path: Path,
) -> list[str]:
    return [
        "--raw-dataset-manifest",
        str(fixture.raw_dataset_manifest),
        "--expected-raw-publication-manifest-hash",
        fixture.raw_publication_hash,
        "--expected-raw-dataset-manifest-hash",
        fixture.raw_dataset_hash,
        "--training-manifest",
        str(fixture.training_manifest),
        "--expected-training-manifest-file-hash",
        fixture.training_manifest_file_hash,
        "--decision-at",
        DECISION_AT,
        "--expected-price-date",
        PRICE_DATE,
        "--expected-symbol-count",
        str(len(fixture.symbols)),
        "--post-freeze-shadow-input-output",
        str(input_path),
        "--audit-output",
        str(audit_path),
        "--batch-size",
        "29",
    ]


def _replace_argument(
    arguments: list[str],
    flag: str,
    value: str,
) -> None:
    arguments[arguments.index(flag) + 1] = value


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
