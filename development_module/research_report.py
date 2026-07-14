"""Append-only report and frozen ResearchConsole projection writer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from development_module.research_orchestration import DevelopmentResearchResult


def write_development_research_artifacts(
    result: DevelopmentResearchResult, *, output_root: str | Path
) -> dict[str, str]:
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "DevelopmentResearchComparison.json"
    projection_path = root / "ResearchConsoleProjection.json"
    if report_path.exists() or projection_path.exists():
        raise FileExistsError("development research output is append-only")
    _write_canonical(report_path, result.report)
    _write_canonical(projection_path, result.projection)
    return {
        "report_id": _sha256(result.report),
        "report_sha256": _file_sha256(report_path),
        "projection_id": _sha256(result.projection),
        "projection_sha256": _file_sha256(projection_path),
    }


def _write_canonical(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
