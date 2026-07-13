"""Verify Gate 2-7 pure-engineering artifacts and separate external gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.engineering_gate_registry import EngineeringGateRegistry
from app_module.gate_2_to_7_closeout_verifier import Gate2To7CloseoutVerifier


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate-db", type=Path)
    args = parser.parse_args(argv)
    completed = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    subjects = tuple(line for line in completed.stdout.splitlines() if line)
    statuses = ("open",)
    if args.gate_db and args.gate_db.exists():
        statuses = tuple(item.status for item in EngineeringGateRegistry(args.gate_db).list_latest())
    report = Gate2To7CloseoutVerifier(ROOT).verify(
        commit_subjects=subjects, external_gate_statuses=statuses
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False))
    return 0 if report.engineering_package_status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
