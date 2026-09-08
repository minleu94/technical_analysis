"""以唯讀 bounded 掃描產生 Direct numeric target 退化診斷。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.portfolio_ml_target_diagnostics import (  # noqa: E402
    TargetDiagnosticError,
    diagnose_direct_numeric_store,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _same_existing_file(first: Path, second: Path) -> bool:
    if not first.exists() or not second.exists():
        return False
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _validate_output_path(output: Path, *, manifest: Path) -> Path:
    """輸出只能落在來源 run 之外，且不得以 hardlink 覆蓋來源。"""

    resolved_output = output.expanduser().resolve()
    resolved_manifest = manifest.expanduser().resolve()
    source_root = resolved_manifest.parent
    if (
        resolved_output == resolved_manifest
        or source_root == resolved_output
        or source_root in resolved_output.parents
        or _same_existing_file(resolved_output, resolved_manifest)
    ):
        raise ValueError(
            "diagnostic output must be outside the immutable Direct run"
        )
    return resolved_output


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            stream.write(_canonical_json(payload) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "read-only bounded diagnosis of Direct numeric all-cash targets"
        )
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="completed portfolio-ml-ooc-store.v3 manifest",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="repository output JSON path outside the source run",
    )
    parser.add_argument(
        "--shared-numeric-store-root",
        type=Path,
        default=None,
        help="immutable shared numeric registry, when manifest uses references",
    )
    parser.add_argument(
        "--year",
        action="append",
        type=int,
        default=[],
        help="optional year filter; repeat for more than one year",
    )
    parser.add_argument(
        "--chunk-rows",
        type=int,
        default=65_536,
        help="bounded memmap scan chunk size",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.manifest.expanduser().resolve()
    try:
        output = _validate_output_path(args.output, manifest=manifest)
        report = diagnose_direct_numeric_store(
            manifest,
            shared_numeric_store_root=args.shared_numeric_store_root,
            years=tuple(args.year),
            chunk_rows=args.chunk_rows,
        )
        _atomic_write_json(output, report)
    except (OSError, TargetDiagnosticError, TypeError, ValueError) as exc:
        print(f"target diagnostic failed: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
