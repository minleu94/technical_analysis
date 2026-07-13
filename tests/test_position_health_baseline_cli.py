from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_writes_fail_closed_health_baseline(tmp_path: Path) -> None:
    source = tmp_path / "paper.json"
    output = tmp_path / "health.json"
    source.write_text(
        json.dumps(
            {
                "decision_date": "2026-07-12",
                "source_result_id": "rec-1",
                "research_only": True,
                "allocations": [{"stock_code": "1615", "stock_name": "大山", "executable_shares": 1000, "constrained_weight_bp": 1500}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "scripts/build_position_health_baseline.py", "--paper-baseline", str(source), "--output", str(output)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["positions"][0]["state"] == "WATCH"
    assert payload["auto_action_allowed"] is False
