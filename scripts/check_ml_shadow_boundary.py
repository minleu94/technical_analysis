"""Check the repository ML shadow-only dependency boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.shadow_boundary_guard import MLShadowBoundaryGuard


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    report = MLShadowBoundaryGuard(ROOT).inspect()
    print(
        json.dumps(
            {
                "inspected_files": report.inspected_files,
                "shadow_only": report.shadow_only,
                "violations": list(report.violations),
            },
            ensure_ascii=False,
        )
    )
    return 1 if report.violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
