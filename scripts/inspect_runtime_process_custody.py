"""唯讀盤點 Python／MCP／ML process custody，不提供終止程序功能。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.process_custody import (  # noqa: E402
    ProcessCustodyError,
    build_process_custody_report,
    collect_process_samples,
    write_process_custody_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-seconds",
        type=float,
        default=1.0,
        help="CPU delta sampling window; default 1 second",
    )
    parser.add_argument(
        "--all-processes",
        action="store_true",
        help="inspect non-Python processes too; default is Python/MCP/ML custody only",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        samples, skipped = collect_process_samples(
            sample_seconds=args.sample_seconds,
            python_only=not args.all_processes,
        )
        report = build_process_custody_report(
            samples,
            sample_seconds=args.sample_seconds,
            skipped_process_count=skipped,
        )
        file_hash = None
        if args.output is not None:
            file_hash = write_process_custody_report(args.output, report)
    except (OSError, ValueError, ProcessCustodyError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "read_only": True,
                    "termination_requested": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    summary = {
        "schema_version": report["schema_version"],
        "status": report["status"],
        "process_count": report["process_count"],
        "skipped_process_count": report["skipped_process_count"],
        "groups": report["groups"],
        "duplicate_mcp_groups": report["duplicate_mcp_groups"],
        "busy_single_core_processes": report["busy_single_core_processes"],
        "warnings": report["warnings"],
        "read_only": True,
        "termination_requested": False,
        "secret_values_emitted": False,
    }
    if file_hash is not None:
        summary["file_hash"] = file_hash
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
