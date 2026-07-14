"""Append-only artifact writer for Terra development generations."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

from development_module.contracts import GenerationWriteResult
from development_module.generation import DevelopmentGenerationResult
from development_module.output_guard import validate_development_output_root
from ml_module.historical_contracts import HistoricalDatasetRow


class DevelopmentArtifactWriter:
    """Writes one immutable generation below a caller-approved output root."""

    def __init__(
        self,
        output_root: str | Path,
        *,
        data_root: str | Path,
        formal_db: str | Path,
    ) -> None:
        self._output_root = validate_development_output_root(
            Path(output_root),
            data_root=Path(data_root),
            formal_db=Path(formal_db),
        )

    def write(self, result: DevelopmentGenerationResult) -> GenerationWriteResult:
        generation_directory = self._output_root / "generations" / result.manifest.generation_id
        if generation_directory.exists():
            raise FileExistsError(f"append-only generation already exists: {generation_directory}")
        staging_directory = generation_directory.parent / f".{generation_directory.name}.{uuid.uuid4().hex}.tmp"
        staging_directory.mkdir(parents=True, exist_ok=False)
        try:
            dataset_path = staging_directory / "dataset.json"
            manifest_path = staging_directory / "manifest.json"
            diagnostics_path = staging_directory / "diagnostics.json"
            _write_json(dataset_path, {
                "fit_rows": [_row_payload(row) for row in result.fit_rows],
                "evaluation_rows": [_row_payload(row) for row in result.evaluation_rows],
            })
            _write_json(manifest_path, result.manifest.to_dict())
            _write_json(diagnostics_path, {
                "accepted": dict(result.manifest.accepted_diagnostics),
                "excluded": dict(result.manifest.excluded_diagnostics),
            })
            staging_directory.rename(generation_directory)
        except BaseException:
            if staging_directory.exists():
                for child in staging_directory.iterdir():
                    child.unlink()
                staging_directory.rmdir()
            raise
        return GenerationWriteResult(
            generation_directory=generation_directory,
            manifest_path=generation_directory / "manifest.json",
            dataset_path=generation_directory / "dataset.json",
        )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _row_payload(row: HistoricalDatasetRow) -> dict[str, object]:
    return {
        "symbol": row.feature.symbol,
        "decision_date": row.feature.decision_date,
        "feature_as_of_date": row.feature.feature_as_of_date,
        "available_date": row.feature.available_date,
        "features": list(row.feature.values),
        "labels": [
            {
                "label_id": label.label_id,
                "value": label.value,
                "horizon_end_date": label.horizon_end_date,
                "available_date": label.available_date,
                "maturity_status": label.maturity_status,
                "quality": label.quality,
            }
            for label in row.labels
        ],
    }
