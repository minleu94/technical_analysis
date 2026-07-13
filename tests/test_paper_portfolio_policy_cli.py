import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_paper_portfolio_policy_sample_cli_emits_research_only_report() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/inspect_paper_portfolio_policy.py", "--sample", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert payload["research_only"] is True
    assert payload["decision"]["action"] == "PAPER_TRADE_CANDIDATE"
    assert payload["policy"]["initial_capital"] == "500000"
    assert payload["policy"]["max_sector_weight_bp"] == 3000

