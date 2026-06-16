from __future__ import annotations

import argparse
from pathlib import Path

from data_module.config import TWStockConfig
from data_module.fundamental_availability_entrypoint import (
    validate_monthly_revenue_availability_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate governed monthly revenue availability mapping."
    )
    parser.add_argument("--path", type=Path, default=None)
    args = parser.parse_args(argv)

    path = args.path or TWStockConfig().monthly_revenue_availability_file
    result = validate_monthly_revenue_availability_file(path)
    print(result.to_markdown())
    for diagnostic in result.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.message}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
