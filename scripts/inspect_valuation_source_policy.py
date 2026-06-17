from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.valuation_source_policy import inspect_valuation_source_policy


def main(argv: list[str] | None = None) -> int:
    _ = argv
    result = inspect_valuation_source_policy()
    print(result.to_markdown())
    for diagnostic in result.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
