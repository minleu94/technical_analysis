from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"
REGISTRATION = SCHEDULED_DIR / "register_paper_execution_task.cmd"
PAPER_TASK = "baldr-paper-execution-eod-replay-daily"


def _run_registration(
    mode: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", str(REGISTRATION), mode],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=False,
    )
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        stdout=(result.stdout or b"").decode("utf-8", errors="replace"),
        stderr=(result.stderr or b"").decode("utf-8", errors="replace"),
    )


def test_dedicated_paper_registration_dryrun_is_eod_safe_and_single_task() -> None:
    result = _run_registration("dryrun", env=os.environ.copy())

    assert result.returncode == 0, result.stdout + result.stderr
    assert PAPER_TASK in result.stdout
    assert "Schedule: DAILY 06:00 Pacific local time" in result.stdout
    assert "Taipei mapping: 21:00 PDT / 22:00 PST" in result.stdout
    assert "existing principal/settings preserved" in result.stdout
    assert "bounded retry" in result.stdout
    assert "run_paper_execution_daily_isolated.cmd" in result.stdout
    assert "repo-isolated Paper ledger" in result.stdout
    assert "Dryrun only. No scheduled task was created." in result.stdout
    for other_task in (
        "baldr-formal-input-producer-daily",
        "baldr-paper-portfolio-daily",
        "baldr-ml-allocation-copilot-daily",
    ):
        assert other_task not in result.stdout


def test_dedicated_paper_registration_register_calls_only_paper_task(
    tmp_path: Path,
) -> None:
    fake_schtasks = tmp_path / "fake_schtasks.cmd"
    fake_schtasks.write_text(
        "@echo off\n"
        "echo fake-schtasks %*\n"
        "exit /b 0\n",
        encoding="utf-8",
    )
    fake_powershell = tmp_path / "fake_powershell.cmd"
    fake_powershell.write_text(
        "@echo off\n"
        "echo fake-powershell %*\n"
        "exit /b 0\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["BALDR_SCHTASKS_EXE"] = str(fake_schtasks)
    env["BALDR_POWERSHELL_EXE"] = str(fake_powershell)

    result = _run_registration("register", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        '/Change /TN "baldr-paper-execution-eod-replay-daily" '
        '/ST 06:00'
    ) in result.stdout
    assert '/Create /TN "baldr-paper-execution-eod-replay-daily"' not in result.stdout
    assert "fake-powershell" not in result.stdout
    assert "Existing task found; updating only trigger and action." in result.stdout
    assert '/Query /TN "baldr-paper-execution-eod-replay-daily"' in result.stdout
    assert "baldr-formal-input-producer-daily" not in result.stdout
    assert "baldr-paper-portfolio-daily" not in result.stdout
    assert "baldr-ml-allocation-copilot-daily" not in result.stdout


def test_missing_paper_task_is_created_with_bounded_policy_only(
    tmp_path: Path,
) -> None:
    fake_schtasks = tmp_path / "fake_schtasks.cmd"
    fake_schtasks.write_text(
        "@echo off\n"
        "echo fake-schtasks %*\n"
        "if exist \"%~dp0created\" goto success\n"
        "echo %* | findstr /I /C:\"/Query\" >nul\n"
        "if not errorlevel 1 (\n"
        "  echo ERROR: The system cannot find the file specified.\n"
        "  exit /b 1\n"
        ")\n"
        ">\"%~dp0created\" echo created\n"
        ":success\n"
        "exit /b 0\n",
        encoding="utf-8",
    )
    fake_powershell = tmp_path / "fake_powershell.cmd"
    fake_powershell.write_text(
        "@echo off\n"
        "echo fake-powershell %*\n"
        "exit /b 0\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["BALDR_SCHTASKS_EXE"] = str(fake_schtasks)
    env["BALDR_POWERSHELL_EXE"] = str(fake_powershell)

    result = _run_registration("register", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        '/Create /TN "baldr-paper-execution-eod-replay-daily" '
        '/SC DAILY /ST 06:00'
    ) in result.stdout
    assert "fake-powershell" in result.stdout
    assert "MultipleInstances IgnoreNew" in result.stdout
    assert "ExecutionTimeLimit" in result.stdout


def test_dedicated_paper_registration_rejects_non_pacific_timezone(
    tmp_path: Path,
) -> None:
    fake_tzutil = tmp_path / "tzutil.cmd"
    fake_tzutil.write_text(
        "@echo off\n"
        "echo UTC\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path};{env['PATH']}"

    result = _run_registration("dryrun", env=env)

    assert result.returncode == 2
    assert "timezone must be Pacific Standard Time" in result.stdout
    assert "No scheduled task was created" not in result.stdout
