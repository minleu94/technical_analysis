from __future__ import annotations

import json
import io
from pathlib import Path
import sys

import pytest

from scripts.inspect_ml_storage_retention import (
    inspect_storage_retention,
    main,
)


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_inventory_is_read_only_and_ranks_review_candidates(tmp_path: Path) -> None:
    root = tmp_path / "release_v4"
    _write(root / "old_run" / "checkpoint.bin", 32)
    (root / "old_run" / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "allocation-ooc-training.v5",
                "status": "complete",
                "run_id": "old-run",
            }
        ),
        encoding="utf-8",
    )
    _write(root / "active" / "model.bin", 8)
    before = sorted(path.relative_to(root) for path in root.rglob("*"))

    report = inspect_storage_retention(
        [root],
        minimum_free_space_bytes=1,
        max_files=20,
        min_candidate_size_bytes=1,
        top_n=10,
    )

    assert report["status"] in {"headroom_ok", "capacity_blocked"}
    assert report["safety"]["read_only"] is True
    assert report["safety"]["deletion_attempted"] is False
    candidates = report["retention_candidates"]
    assert candidates
    assert candidates[0]["size_bytes"] >= candidates[-1]["size_bytes"]
    assert any(item["kind"] == "retention_review_candidate" for item in candidates)
    old_run = next(item for item in candidates if item["path"].endswith("old_run"))
    assert old_run["status"] == "complete"
    assert old_run["schema_version"] == "allocation-ooc-training.v5"
    after = sorted(path.relative_to(root) for path in root.rglob("*"))
    assert after == before


def test_inventory_marks_bounded_scan_as_partial_recheck(tmp_path: Path) -> None:
    root = tmp_path / "release_v4"
    for index in range(3):
        _write(root / "runs" / f"run-{index}" / "payload.bin", 4)

    report = inspect_storage_retention(
        [root],
        minimum_free_space_bytes=1,
        max_files=1,
        min_candidate_size_bytes=1,
        top_n=5,
    )

    assert report["safety"]["truncated_scan_requires_manual_recheck"] is True
    assert report["root_reports"][0]["scan_truncated"] is True


def test_inventory_cli_writes_json_only_to_temp(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(root / "snapshot" / "payload.bin", 3)
    output = Path(__import__("tempfile").gettempdir()) / "ml-storage-retention-test.json"
    try:
        assert main(
            [
                "--root",
                str(root),
                "--minimum-free-space-bytes",
                "1",
                "--min-candidate-size-bytes",
                "1",
                "--output",
                str(output),
            ]
        ) == 0
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "ml-storage-retention-inventory.v1"
        assert payload["safety"]["automatic_delete_allowed"] is False
    finally:
        output.unlink(missing_ok=True)


def test_inventory_rejects_output_outside_temp(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    output = Path.cwd() / "ml-storage-retention-test-outside-temp.json"
    with pytest.raises(ValueError, match="OS TEMP"):
        main(
            [
                "--root",
                str(root),
                "--output",
                str(output),
            ]
        )


def test_cli_help_reconfigures_windows_console_before_argparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chinese storage help must remain printable on a cp1252 Windows host."""

    payload = io.BytesIO()
    stream = io.TextIOWrapper(payload, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    stream.flush()
    assert exc_info.value.code == 0
    assert "唯讀" in payload.getvalue().decode("utf-8")
