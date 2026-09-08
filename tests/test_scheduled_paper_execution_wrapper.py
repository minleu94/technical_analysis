from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "scheduled" / "run_paper_execution_daily.cmd"


def test_scheduled_wrapper_uses_queue_without_fixed_recommendation_env(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "output"
    candidate_root = tmp_path / "candidate"
    receipt_root = tmp_path / "receipts"
    recommendation_root = tmp_path / "recommendations-not-created"
    env = os.environ.copy()
    for name in (
        "PAPER_EXECUTION_RECOMMENDATION_JSON",
        "PAPER_EXECUTION_CLOCK_MANIFEST",
    ):
        env.pop(name, None)
    env.update(
        {
            "DATA_ROOT": str(tmp_path / "data"),
            "OUTPUT_ROOT": str(output_root),
            "PAPER_EXECUTION_OUTPUT_ROOT": str(candidate_root),
            "PAPER_EXECUTION_STATE_DB": str(tmp_path / "state.sqlite"),
            "PAPER_EXECUTION_MARKET_DB": str(tmp_path / "market.sqlite"),
            "PAPER_EXECUTION_LEDGER_DB": str(tmp_path / "ledger.sqlite"),
            "PAPER_EXECUTION_RECOMMENDATION_ROOT": str(recommendation_root),
            "PAPER_EXECUTION_RECEIPT_ROOT": str(receipt_root),
            "PAPER_EXECUTION_APPEND": "0",
        }
    )

    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(WRAPPER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    candidate = json.loads(
        (candidate_root / "paper_execution_candidate.json").read_text(
            encoding="utf-8"
        )
    )
    assert candidate["status"] == "skipped_no_pending_recommendation"
    assert candidate["blockers"] == ["recommendation_root_missing"]
    receipts = list(receipt_root.glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["queue_state"] == "skipped"
    assert receipt["status"] == "skipped_no_pending_recommendation"
