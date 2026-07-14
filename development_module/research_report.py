"""Append-only report and frozen ResearchConsole projection writer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

from development_module.output_guard import validate_development_output_root
from development_module.research_orchestration import DevelopmentResearchResult


def write_development_research_artifacts(
    result: DevelopmentResearchResult,
    *,
    output_root: str | Path,
    data_root: str | Path,
    formal_db: str | Path,
) -> dict[str, str]:
    root = validate_development_output_root(
        Path(output_root),
        data_root=Path(data_root),
        formal_db=Path(formal_db),
    )
    if root.exists():
        raise FileExistsError("development research output is append-only")
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.parent / f".{root.name}.{uuid.uuid4().hex}.tmp"
    staging.mkdir(exist_ok=False)
    try:
        _write_canonical(staging / "DevelopmentResearchComparison.json", result.report)
        _write_canonical(staging / "ResearchConsoleProjection.json", result.projection)
        staging.rename(root)
    except BaseException:
        if staging.exists():
            for child in staging.iterdir():
                child.unlink()
            staging.rmdir()
        raise
    report_path = root / "DevelopmentResearchComparison.json"
    projection_path = root / "ResearchConsoleProjection.json"
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
