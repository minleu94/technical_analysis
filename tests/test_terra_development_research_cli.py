from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

import development_module.research_report as research_report_module
from app_module.research_console_source_service import ResearchConsoleSourceService
from development_module.dataset_integrity import persisted_dataset_content_hash
from development_module.research_orchestration import (
    FrozenDevelopmentResearchPolicy,
    TerraDevelopmentResearchOrchestrator,
)
from development_module.research_report import write_development_research_artifacts


def _write_cli_generation(tmp_path: Path) -> tuple[Path, Path, list[dict[str, object]]]:
    generation = tmp_path / "input" / "generations" / "cli-test"
    generation.mkdir(parents=True)
    manifest = {
        "schema_version": "terra-development-dataset.v0", "generation_id": "cli-test",
        "dataset_id": "terra-development-v0:cli-test", "dataset_status": "research_only_degraded",
        "formal_oos_allowed": False, "production_blend_alpha_bp": 0,
        "formal_rule_only_path_unchanged": True, "zero_formal_write": True,
        "feature_registry_hash": "sha256:" + "a" * 64, "label_registry_hash": "sha256:" + "b" * 64,
        "content_hash": "", "manifest_hash": "sha256:" + "d" * 64,
        "training_as_of": "2025-12-31", "new_holdout_start": "2026-07-15",
    }
    rows: list[dict[str, object]] = []
    for index in range(48):
        decision_date = date(2025, 1, 1) + timedelta(days=index)
        decision = decision_date.isoformat()
        available = (decision_date + timedelta(days=1)).isoformat()
        target = (index % 11 - 5) * 100
        rows.append({"symbol": f"{2000 + index:04d}", "decision_date": decision, "feature_as_of_date": "2024-12-31", "available_date": decision, "features": [["rsi_normalized_bp", (index % 9 - 4) * 250], ["adx_normalized_bp", 2500 + index], ["macd_normalized_bp", (index % 5 - 2) * 100]], "labels": [{"label_id": "relative_return_20d_bp", "value": target, "horizon_end_date": available, "available_date": available, "maturity_status": "ready", "quality": "research_only"}, {"label_id": "downside_20d_flag", "value": int(target <= -500), "horizon_end_date": available, "available_date": available, "maturity_status": "ready", "quality": "research_only"}]})
    dataset = {"fit_rows": rows, "evaluation_rows": []}
    manifest["fit_row_count"] = len(rows)
    manifest["evaluation_row_count"] = 0
    manifest["content_hash"] = persisted_dataset_content_hash(dataset)
    manifest_path = generation / "manifest.json"
    dataset_path = generation / "dataset.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    return manifest_path, dataset_path, rows


def test_cli_writes_only_report_and_frozen_projection(tmp_path: Path) -> None:
    manifest_path, dataset_path, rows = _write_cli_generation(tmp_path)
    output = tmp_path / "output"

    completed = subprocess.run(
        [sys.executable, "scripts/run_terra_development_research.py", "--manifest", str(manifest_path), "--dataset", str(dataset_path), "--output-root", str(output), "--bounded-smoke"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )

    projection = json.loads((output / "ResearchConsoleProjection.json").read_text(encoding="utf-8"))
    cli_result = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert projection["status"]["formal_oos"] is False
    assert projection["status"]["alpha_bp"] == 0
    assert set(projection) == {"identity", "status", "frozen_metrics", "blockers", "lineage"}
    console = ResearchConsoleSourceService(
        projection_path=output / "ResearchConsoleProjection.json"
    ).inspect()
    assert "projection_boundary_violation" not in console.blockers
    assert console.pipeline[0].identity == "terra-development-v0:cli-test"
    assert console.pipeline[0].row_count == len(rows)
    assert console.pipeline[0].cutoff == "2025-12-31"
    assert console.pipeline[3].generated_at == projection["lineage"]["generated_at"]
    assert console.pipeline[3].artifact_hash == cli_result["artifacts"]["projection_sha256"]


def test_research_writer_rejects_output_inside_data_root_before_creating_files(
    tmp_path: Path,
) -> None:
    manifest_path, dataset_path, _ = _write_cli_generation(tmp_path)
    result = TerraDevelopmentResearchOrchestrator().run(
        manifest_path=manifest_path,
        dataset_path=dataset_path,
        policy=FrozenDevelopmentResearchPolicy.bounded_for_test(),
    )
    data_root = tmp_path / "formal-data"
    output = data_root / "research-output"

    with pytest.raises(ValueError, match="outside DATA_ROOT"):
        write_development_research_artifacts(
            result,
            output_root=output,
            data_root=data_root,
            formal_db=data_root / "sqlite" / "twstock.db",
        )

    assert not output.exists()


def test_research_writer_does_not_publish_partial_pair_when_projection_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, dataset_path, _ = _write_cli_generation(tmp_path)
    result = TerraDevelopmentResearchOrchestrator().run(
        manifest_path=manifest_path,
        dataset_path=dataset_path,
        policy=FrozenDevelopmentResearchPolicy.bounded_for_test(),
    )
    output = tmp_path / "research-output"
    original_write = research_report_module._write_canonical

    def fail_projection(path: Path, value: object) -> None:
        if path.name == "ResearchConsoleProjection.json":
            raise OSError("injected projection write failure")
        original_write(path, value)

    monkeypatch.setattr(research_report_module, "_write_canonical", fail_projection)
    with pytest.raises(OSError, match="injected projection write failure"):
        write_development_research_artifacts(
            result,
            output_root=output,
            data_root=tmp_path / "formal-data",
            formal_db=tmp_path / "formal-data" / "sqlite" / "twstock.db",
        )

    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))

    monkeypatch.setattr(research_report_module, "_write_canonical", original_write)
    write_development_research_artifacts(
        result,
        output_root=output,
        data_root=tmp_path / "formal-data",
        formal_db=tmp_path / "formal-data" / "sqlite" / "twstock.db",
    )
    assert (output / "DevelopmentResearchComparison.json").is_file()
    assert (output / "ResearchConsoleProjection.json").is_file()


def test_research_cli_rejects_formal_output_root_before_orchestration(tmp_path: Path) -> None:
    manifest_path, dataset_path, _ = _write_cli_generation(tmp_path)
    data_root = tmp_path / "formal-data"
    output = data_root / "research-output"
    environment = os.environ.copy()
    environment["DATA_ROOT"] = str(data_root)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_terra_development_research.py",
            "--manifest",
            str(manifest_path),
            "--dataset",
            str(dataset_path),
            "--output-root",
            str(output),
            "--bounded-smoke",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )

    assert completed.returncode == 2
    assert "outside DATA_ROOT" in completed.stderr
    assert not output.exists()
