from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

from scripts.scheduled import run_scheduled_evidence_pipeline_dry_run


def test_scheduled_wrapper_stdout_survives_cp1252_console_with_chinese_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "輸出"
    db_path = tmp_path / "資料" / "sqlite" / "twstock.db"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="pipeline ok\n")

    output_buffer = io.BytesIO()
    stdout = io.TextIOWrapper(output_buffer, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code = run_scheduled_evidence_pipeline_dry_run.main(
        [
            "--dry-run",
            "--data-root",
            str(tmp_path / "資料"),
            "--output-root",
            str(output_root),
            "--db-path",
            str(db_path),
            "--sources",
            "all",
        ]
    )

    stdout.flush()
    raw_output = output_buffer.getvalue().decode("cp1252")
    payload = json.loads(raw_output)
    assert exit_code == 0
    assert payload["db_path"] == str(db_path)
    assert "輸出" in payload["report_path"]
    assert "\\u8f38\\u51fa" in raw_output
    assert (output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json").exists()
