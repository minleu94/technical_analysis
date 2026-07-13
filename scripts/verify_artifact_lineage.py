"""Validate a canonical artifact-lineage manifest without writing domain storage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.artifact_lineage_verifier import ArtifactIdentity, ArtifactLineageVerifier


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    artifacts = tuple(
        ArtifactIdentity(
            **{**item, "parent_artifact_ids": tuple(item.get("parent_artifact_ids", ()))},
        )
        for item in payload.get("artifacts", ())
    )
    report = ArtifactLineageVerifier().verify(artifacts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps(report.to_dict(), ensure_ascii=False))
    return 0 if report.status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
