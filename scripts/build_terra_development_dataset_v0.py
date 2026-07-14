"""Build an append-only Terra Development Dataset V0 from approved core sources only."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from development_module.contracts import DevelopmentGenerationRequest
from development_module.generation import TerraDevelopmentDatasetGenerator
from development_module.governance import load_development_data_usage_decision
from development_module.output_guard import validate_development_output_root
from development_module.source_adapter import CoreSourceAdapter
from development_module.writer import DevelopmentArtifactWriter


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--development-output-root", type=Path, required=True)
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--decision-date-start", required=True)
    parser.add_argument("--decision-date-end", required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--evaluation-as-of", required=True)
    parser.add_argument("--max-decision-dates", type=int)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _arguments(argv)
        database = args.database.expanduser().resolve()
        output_root = validate_development_output_root(
            args.development_output_root,
            data_root=Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")),
            formal_db=database,
        )
        decision = load_development_data_usage_decision(
            output_root / "governance" / "DevelopmentDataUsageDecision.jsonl",
            output_root=output_root,
        )
        if not database.is_file():
            raise FileNotFoundError(database)
        request = DevelopmentGenerationRequest(
            generation_id=args.generation_id,
            decision_date_start=args.decision_date_start,
            decision_date_end=args.decision_date_end,
            training_as_of=args.training_as_of,
            evaluation_as_of=args.evaluation_as_of,
            new_holdout_start=decision.new_holdout_start,
            usage_decision_sha256=decision.decision_record_sha256,
            max_decision_dates=args.max_decision_dates,
        )
        history_start = (
            date.fromisoformat(request.decision_date_start[:10]) - timedelta(days=600)
        ).isoformat()
        source_hash_before = _file_sha256(database)
        source_mtime_before = database.stat().st_mtime_ns
        snapshot = CoreSourceAdapter(database).load(history_start, request.evaluation_as_of)
        result = TerraDevelopmentDatasetGenerator(snapshot).generate(request)
        write_result = DevelopmentArtifactWriter(
            output_root,
            data_root=Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")),
            formal_db=database,
        ).write(result)
        if (source_hash_before, source_mtime_before) != (_file_sha256(database), database.stat().st_mtime_ns):
            raise RuntimeError("formal source database changed during Terra generation")
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({
        "generation_id": result.manifest.generation_id,
        "dataset_id": result.manifest.dataset_id,
        "manifest_path": str(write_result.manifest_path),
        "content_hash": result.manifest.content_hash,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "formal_rule_only_path_unchanged": True,
        "zero_formal_write": True,
    }, ensure_ascii=False, sort_keys=True))
    return 0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
