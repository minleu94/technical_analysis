from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from runtime.process_custody import (
    ProcessCustodyError,
    build_process_custody_report,
    classify_process,
    write_process_custody_report,
)


def _sample(
    pid: int,
    command: list[str],
    *,
    cpu_seconds: float = 0.0,
    memory_bytes: int = 1_000,
    thread_count: int = 4,
    cwd: str = r"C:\Projects\PythonProjects\technical_analysis",
) -> dict[str, object]:
    return {
        "pid": pid,
        "ppid": 1,
        "name": "python.exe",
        "executable": r"C:\Program Files\Python311\python.exe",
        "cmdline": command,
        "cwd": cwd,
        "cpu_seconds": cpu_seconds,
        "memory_bytes": memory_bytes,
        "thread_count": thread_count,
        "status": "running",
    }


def test_groups_duplicate_mcp_without_emitting_command_lines() -> None:
    secret = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY=do-not-emit"
    report = build_process_custody_report(
        [
            _sample(10, ["-m", "mcp_server_yfinance", secret]),
            _sample(11, ["-m", "mcp_server_yfinance", secret]),
            _sample(12, ["mcp_servers/evidence_access_server.py"]),
        ],
        sample_seconds=2.0,
    )
    assert report["status"] == "attention_required"
    duplicates = cast(list[dict[str, object]], report["duplicate_mcp_groups"])
    assert duplicates == [
        {
            "role": "mcp:yfinance",
            "scopes": ["technical_analysis"],
            "instance_count": 2,
            "pids": [10, 11],
            "memory_bytes": 2_000,
        }
    ]
    assert secret not in json.dumps(report, ensure_ascii=False)
    assert report["termination_requested"] is False


def test_busy_external_probe_is_flagged_as_single_core() -> None:
    report = build_process_custody_report(
        [
            _sample(
                27036,
                ["-c", "tempfile.NamedTemporaryFile", "inkscope_probe_"],
                cpu_seconds=1.9,
                thread_count=1,
                cwd=r"C:\Projects\PythonProjects\ig_tracking",
            )
        ],
        sample_seconds=2.0,
    )
    busy = cast(list[dict[str, object]], report["busy_single_core_processes"])
    assert busy[0]["role"] == "external:inkscope_probe"
    assert busy[0]["scope"] == "external"
    assert busy[0]["cpu_percent_of_one_core"] == 95.0


def test_ml_and_ui_classification_is_safe() -> None:
    assert classify_process(
        name="python.exe",
        executable="python.exe",
        cmdline=["scripts/maintain_ml_direct_v3_refresh_chain.py"],
        cwd=r"C:\Projects\PythonProjects\technical_analysis",
    ) == ("ml_or_data_pipeline", "technical_analysis")
    assert classify_process(
        name="python.exe",
        executable="python.exe",
        cmdline=["ui_qt/main.py"],
        cwd=r"C:\Projects\PythonProjects\technical_analysis",
    ) == ("technical_analysis_ui", "technical_analysis")


def test_report_writer_is_create_only(tmp_path: Path) -> None:
    report = build_process_custody_report([], sample_seconds=1.0)
    output = tmp_path / "process-custody.json"
    file_hash = write_process_custody_report(output, report)
    assert file_hash.startswith("sha256:")
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["report_hash"].startswith("sha256:")
    with pytest.raises(ProcessCustodyError, match="already exists"):
        write_process_custody_report(output, report)


def test_invalid_sample_seconds_and_fields_fail_closed() -> None:
    with pytest.raises(ProcessCustodyError, match="positive"):
        build_process_custody_report([], sample_seconds=0)
    invalid = _sample(1, ["-m", "mcp_server_yfinance"])
    invalid["pid"] = True
    with pytest.raises(ProcessCustodyError, match="pid"):
        build_process_custody_report([invalid], sample_seconds=1)
