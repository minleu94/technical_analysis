from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from qa.full_app_healthcheck.mainwindow_smoke_runner import (
    MainWindowSmokeOptions,
    run_mainwindow_smoke,
)


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated MainWindow UI smoke and write evidence JSON.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--switch-tabs", action="store_true")
    parser.add_argument("--screenshot", action="store_true")
    parser.add_argument("--resize", action="append", default=[])
    parser.add_argument("--dialog-cancel", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "evidence.json"
    try:
        evidence: dict[str, Any] = run_mainwindow_smoke(
            MainWindowSmokeOptions(
                output_dir=output_dir,
                switch_tabs=bool(args.switch_tabs),
                capture_screenshots=bool(args.screenshot),
                resize_viewports=tuple(args.resize),
                dialog_cancel=bool(args.dialog_cancel),
            )
        )
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"MainWindow UI smoke evidence written: {evidence_path}")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    except BaseException as exc:  # noqa: BLE001
        evidence_path.write_text(
            json.dumps(
                {"status": "failed", "error": str(exc), "type": exc.__class__.__name__},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"MainWindow UI smoke failed: {exc}", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
