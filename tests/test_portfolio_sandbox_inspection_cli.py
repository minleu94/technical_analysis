from __future__ import annotations

import json
import subprocess
import sys


def test_inspection_cli_outputs_sample_json() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_portfolio_sandbox.py",
            "--sample",
            "--format",
            "json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)

    assert payload["research_basis"] is True
    assert payload["policy"] == "research_only_portfolio_construction_v1"
    assert payload["trace_events"]
    assert payload["trace_events"][0]["event_type"] == "created"
    assert payload["trace_events"][0]["research_only"] is True

