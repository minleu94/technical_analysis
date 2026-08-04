from pathlib import Path
from scripts.acquire_mops_numeric_pit_batch import execute_mops_batch


def test_batch_max_items_enforced(tmp_path: Path) -> None:
    manifest = [
        {"stock_code": "2330", "market": "sii", "roc_year": 114, "season": 1},
        {"stock_code": "2317", "market": "sii", "roc_year": 114, "season": 1},
        {"stock_code": "2454", "market": "sii", "roc_year": 114, "season": 1},
    ]

    res = execute_mops_batch(
        manifest,
        output_root=tmp_path,
        canonical_manifest=tmp_path / "dummy_manifest.json",
        canonical_dataset=tmp_path / "dummy_dataset.json",
        max_items=2,
        dry_run=True,
    )

    assert res["max_items_requested"] == 2
    assert res["attempted"] == 2
    assert res["succeeded"] == 2


def test_batch_dry_run_mode(tmp_path: Path) -> None:
    manifest = [{"stock_code": "2330", "market": "sii", "roc_year": 114, "season": 1}]

    res = execute_mops_batch(
        manifest,
        output_root=tmp_path,
        canonical_manifest=tmp_path / "dummy_manifest.json",
        canonical_dataset=tmp_path / "dummy_dataset.json",
        max_items=1,
        dry_run=True,
    )

    assert res["dry_run"] is True
    assert res["attempted"] == 1
    assert res["failed"] == 0
