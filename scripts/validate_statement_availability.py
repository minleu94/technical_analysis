from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.fundamental_statement_availability_entrypoint import (
    validate_statement_availability_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate governed quarterly statement availability mapping."
    )
    parser.add_argument("--path", type=Path, default=None)
    args = parser.parse_args(argv)

    path = args.path or TWStockConfig().statement_availability_file
    result = validate_statement_availability_file(path)
    print(result.to_markdown())
    for diagnostic in result.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.message}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
