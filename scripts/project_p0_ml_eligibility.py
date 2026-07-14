from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.p0_ml_eligibility_projection import (
    project_p0_ml_eligibility,
    write_p0_ml_eligibility,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project p0-ml-eligibility.v1 in staging.")
    parser.add_argument("--candidates-json", type=Path, required=True)
    parser.add_argument("--mapping-hashes-json", type=Path, required=True)
    parser.add_argument("--corporate-coverage-json", type=Path, required=True)
    parser.add_argument("--mode", choices=("strict", "research"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    artifact = project_p0_ml_eligibility(
        candidates=json.loads(args.candidates_json.read_text(encoding="utf-8-sig")),
        mapping_hashes=json.loads(
            args.mapping_hashes_json.read_text(encoding="utf-8-sig")
        ),
        corporate_coverage=json.loads(
            args.corporate_coverage_json.read_text(encoding="utf-8-sig")
        ),
        mode=args.mode,
    )
    path = write_p0_ml_eligibility(artifact, output_root=args.output_root)
    print(json.dumps({"output": str(path), "canonical_hash": artifact.canonical_hash}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
