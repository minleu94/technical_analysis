from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.audit_ml_allocation_v3_linear_release import (
    _validate_distinct_output_paths,
    _validate_external_output_path,
)


def test_audit_outputs_cannot_overwrite_release_or_input(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    release_root.mkdir()
    model_path = release_root / "model.joblib"
    model_path.write_bytes(b"immutable-model")
    input_path = tmp_path / "input.json.gz"
    input_path.write_bytes(b"immutable-input")

    before_model = model_path.read_bytes()
    before_input = input_path.read_bytes()
    with pytest.raises(ValueError, match="immutable release root"):
        _validate_external_output_path(
            model_path,
            release_root=release_root,
            input_path=input_path,
            field_name="output",
        )
    with pytest.raises(ValueError, match="v3 input"):
        _validate_external_output_path(
            input_path,
            release_root=release_root,
            input_path=input_path,
            field_name="readback_output",
        )
    assert model_path.read_bytes() == before_model
    assert input_path.read_bytes() == before_input

    alias_path = tmp_path / "model-alias.joblib"
    try:
        os.link(model_path, alias_path)
    except OSError:
        pytest.skip("hard links are unavailable in this Windows test environment")
    with pytest.raises(ValueError, match="immutable release file"):
        _validate_external_output_path(
            alias_path,
            release_root=release_root,
            input_path=input_path,
            field_name="output",
        )
    assert model_path.read_bytes() == before_model


def test_audit_summary_and_readback_outputs_must_be_distinct(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    release_root.mkdir()
    input_path = tmp_path / "input.json.gz"
    input_path.write_bytes(b"input")
    output_path = tmp_path / "audit.json"
    output_path.write_bytes(b"audit")

    with pytest.raises(ValueError, match="must be distinct"):
        _validate_distinct_output_paths(output_path, output_path)

    alias_path = tmp_path / "audit-alias.json"
    try:
        os.link(output_path, alias_path)
    except OSError:
        pytest.skip("hard links are unavailable in this Windows test environment")
    with pytest.raises(ValueError, match="must be distinct"):
        _validate_distinct_output_paths(output_path, alias_path)
