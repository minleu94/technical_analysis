from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import pytest

from development_module.data_inventory import build_development_data_inventory
from development_module.pit_financial_ratio_materializer import (
    materialize_pit_fundamental_candidate_artifact,
    _to_int_bp,
    _to_int_cents,
)


def test_int_bp_and_cents_conversion() -> None:
    assert _to_int_bp(15.25) == 1525
    assert _to_int_bp("10.0") == 1000
    assert _to_int_bp(0) == 0
    assert _to_int_bp(None) == 0

    assert _to_int_cents(12.50) == 1250
    assert _to_int_cents("5.75") == 575
    assert _to_int_cents(None) == 0


def test_materialize_pit_fundamental_candidate_artifact_success(tmp_path: Path) -> None:
    sample_records = [
        {
            "stock_id": "2330",
            "quarter": "2026-Q1",
            "publication_timestamp": "2026-05-12T14:45:00+08:00",
            "roe_pct": 28.5,
            "operating_margin_pct": 42.0,
            "gross_margin_pct": 53.0,
            "debt_ratio_pct": 32.0,
            "eps_nwd": 13.8,
        }
    ]

    artifact_path, sha_hex, artifact_dict = materialize_pit_fundamental_candidate_artifact(
        records_input=sample_records,
        output_root=tmp_path,
    )

    assert artifact_path.exists()
    assert sha_hex.startswith("sha256:")
    assert artifact_dict["source_id"] == "pit.quarterly_financials"
    assert artifact_dict["record_count"] == 1

    content_bytes = artifact_path.read_bytes()
    expected_hex = "sha256:" + sha256(content_bytes).hexdigest()
    assert sha_hex == expected_hex


def test_materialize_fails_on_missing_required_fields(tmp_path: Path) -> None:
    bad_records = [
        {
            "stock_id": "2330",
            "quarter": "",
            "publication_timestamp": "2026-05-12T14:45:00+08:00",
        }
    ]
    with pytest.raises(ValueError, match="required for every PIT record"):
        materialize_pit_fundamental_candidate_artifact(
            records_input=bad_records,
            output_root=tmp_path,
        )


def test_materialize_fails_on_naive_timestamp(tmp_path: Path) -> None:
    bad_records = [
        {
            "stock_id": "2330",
            "quarter": "2026-Q1",
            "publication_timestamp": "2026-05-12 14:45:00",
        }
    ]
    with pytest.raises(ValueError, match="timezone-aware"):
        materialize_pit_fundamental_candidate_artifact(
            records_input=bad_records,
            output_root=tmp_path,
        )
