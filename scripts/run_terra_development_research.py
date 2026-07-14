"""Run the bounded Dataset V0 development research pipeline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from development_module.research_orchestration import (
    FrozenDevelopmentResearchPolicy,
    TerraDevelopmentResearchOrchestrator,
)
from development_module.research_report import write_development_research_artifacts
from development_module.output_guard import validate_development_output_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dataset V0 → Rule → ML → comparison → frozen projection")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--bounded-smoke", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data"))
    formal_db = data_root / "sqlite" / "twstock.db"
    try:
        output_root = validate_development_output_root(
            args.output_root,
            data_root=data_root,
            formal_db=formal_db,
        )
        policy = FrozenDevelopmentResearchPolicy.bounded_for_test() if args.bounded_smoke else FrozenDevelopmentResearchPolicy()
        result = TerraDevelopmentResearchOrchestrator().run(
            manifest_path=args.manifest,
            dataset_path=args.dataset,
            policy=policy,
        )
        artifacts = write_development_research_artifacts(
            result,
            output_root=output_root,
            data_root=data_root,
            formal_db=formal_db,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"artifacts": artifacts, "status": result.projection["status"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
