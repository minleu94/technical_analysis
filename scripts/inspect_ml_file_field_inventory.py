"""唯讀掃描 DATA_ROOT 的 CSV/JSON/JSONL file-backed ML 欄位治理清冊。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_file_field_inventory import inspect_ml_file_fields  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data"))
    output_root = Path(
        os.environ.get("OUTPUT_ROOT", str(data_root / "output"))
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=data_root,
        help="正式資料根目錄；只會以唯讀模式掃描。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=output_root / "release_v4",
        help="JSON artifact 目錄，預設為 OUTPUT_ROOT/release_v4。",
    )
    parser.add_argument(
        "--max-csv-header-bytes",
        type=int,
        default=256 * 1024,
    )
    parser.add_argument("--max-json-bytes", type=int, default=256 * 1024)
    parser.add_argument("--max-jsonl-lines", type=int, default=5)
    parser.add_argument("--max-json-fields", type=int, default=512)
    parser.add_argument(
        "--max-output-detail-bytes",
        type=int,
        default=1024 * 1024,
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    inventory = inspect_ml_file_fields(
        args.data_root,
        max_csv_header_bytes=args.max_csv_header_bytes,
        max_json_bytes=args.max_json_bytes,
        max_jsonl_lines=args.max_jsonl_lines,
        max_json_fields=args.max_json_fields,
        max_output_detail_bytes=args.max_output_detail_bytes,
    )
    report = inventory.to_dict()
    output_path = args.output_dir.resolve() / "ml_file_field_inventory.json"
    _atomic_write_json(output_path, report)
    summary = {
        "schema_version": report["schema_version"],
        "output_path": str(output_path),
        "inventory_hash": inventory.inventory_hash,
        "summary": report["summary"],
        "safety": report["safety"],
    }
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    rendered = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    try:
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

