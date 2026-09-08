from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_ml_allocation_label_extreme import (
    _scan_label_extreme,
    audit_label_extreme,
    main,
)
from tests.test_portfolio_ml_target_diagnostics import _build_fixture


def test_label_extreme_audit_selects_observed_row_without_source_rewrite(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture(tmp_path)
    original_manifest = manifest_path.read_bytes()

    selection = _scan_label_extreme(
        manifest_path,
        horizon=20,
        field_name="benchmark_excess_return_bp",
        shared_numeric_store_root=None,
        chunk_rows=65_536,
    )

    assert selection["label_field"] == (
        "benchmark_excess_return_bp"
    )
    assert selection["horizon"] == 20
    assert selection["label_value_bp"] == 100
    assert selection["local_row_index"] == 0
    assert manifest_path.read_bytes() == original_manifest


def test_label_extreme_audit_rejects_source_output_alias(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture(tmp_path)
    original_manifest = manifest_path.read_bytes()

    assert main(
        [
            "--manifest",
            str(manifest_path),
            "--output",
            str(manifest_path),
        ]
    ) == 2
    assert manifest_path.read_bytes() == original_manifest
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == (
        "complete"
    )
