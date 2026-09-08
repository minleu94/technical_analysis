from __future__ import annotations

import pytest

import json
import os
from pathlib import Path
import subprocess
import sys

from tests.fixtures.portfolio_ml_ooc_support import run_synthetic_ml_cli

from tests.test_portfolio_ml_dataset_assembler import (
    _official_corporate_action_publication,
    _raw_publication,
    _sector_membership_row,
    _write_sector_membership_sidecar,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "build_portfolio_ml_training_shards.py"


# 小型合成資料驗證使用可控容量；實體低空間另由專用capacity tests驗證。
pytestmark = pytest.mark.usefixtures("synthetic_ml_capacity")


def test_cli_publishes_direct_training_input_without_touching_raw(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    official = _official_corporate_action_publication(tmp_path)
    raw_manifest = raw.dataset_manifest_paths["all_field_enriched"]
    before = raw_manifest.read_bytes()
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"

    result = run_synthetic_ml_cli(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-manifest",
            str(raw_manifest),
            "--output-dir",
            str(tmp_path / "training"),
            "--training-as-of",
            "2024-09-01T08:30:00+08:00",
            "--benchmark-entity",
            "TAIEX",
            "--corporate-action-manifest",
            str(official.manifest_path),
            "--minimum-train-dates",
            "65",
            "--test-date-count",
            "21",
            "--purge-trading-days",
            "60",
            "--embargo-trading-days",
            "5",
            "--batch-size",
            "31",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "published"
    assert payload["direct_training_input"] is True
    assert payload["fold_count"] >= 4
    assert payload["sample_count"] > 0
    assert payload["production_alpha_bp"] == 0
    assert payload["production_action_allowed"] is False
    assert raw_manifest.read_bytes() == before
    manifest = json.loads(
        Path(payload["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["direct_training_input"] is True
    assert manifest["target_cli"] == "scripts/train_ml_allocation_copilot.py"
    assert manifest["corporate_action_custody"]["manifest_hash"] == (
        official.manifest_hash
    )


def test_cli_blocks_unaccepted_sector_membership_sidecar(
    tmp_path: Path,
) -> None:
    raw = _raw_publication(tmp_path)
    raw_manifest = raw.dataset_manifest_paths["all_field_enriched"]
    sidecar_path = tmp_path / "untrusted-sector.json"
    _write_sector_membership_sidecar(
        sidecar_path,
        [_sector_membership_row(status="research_shadow")],
    )
    output_root = tmp_path / "training"
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"

    result = run_synthetic_ml_cli(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-manifest",
            str(raw_manifest),
            "--output-dir",
            str(output_root),
            "--training-as-of",
            "2024-09-01T08:30:00+08:00",
            "--benchmark-entity",
            "TAIEX",
            "--sector-membership",
            str(sidecar_path),
            "--minimum-train-dates",
            "65",
            "--test-date-count",
            "21",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stderr)
    assert payload["status"] == "blocked"
    assert (
        "blocker:sector_membership_status_not_accepted"
        in payload["message"]
    )
    assert payload["direct_training_input"] is False
    assert payload["production_alpha_bp"] == 0
    assert payload["production_action_allowed"] is False
    assert not (output_root / "latest_manifest.json").exists()
