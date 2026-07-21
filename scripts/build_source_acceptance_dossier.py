"""Build a read-only, fail-closed EV2 dossier projection from JSON input."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from data_module.source_acceptance_governance import SourceAcceptanceDossier


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only source dossier projection")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    _require_non_production_output(args.output)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    dossier = SourceAcceptanceDossier.from_dict(payload)
    output = {
        "read_only": True,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "dossier_content_hash": dossier.content_hash,
        "dossier": dossier.to_dict(),
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def _require_non_production_output(output_path: Path) -> None:
    production_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    resolved_output = output_path.resolve()
    try:
        resolved_output.relative_to(production_root)
    except ValueError:
        return
    raise ValueError("output must use an explicit non-production path outside DATA_ROOT")


if __name__ == "__main__":
    raise SystemExit(main())
