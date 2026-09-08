from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = ROOT / "scripts" / "scheduled" / "register_paper_portfolio_task.cmd"
PAPER_TASK = "baldr-paper-portfolio-daily"


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
    stdout = (result.stdout or b"").decode("utf-8", errors="replace")
    stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_dedicated_paper_portfolio_registration_is_one_task_and_dst_guarded() -> None:
    result = _run_registration("dryrun", env=os.environ.copy())

    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert PAPER_TASK in result.stdout
    assert "Schedule: DAILY 16:30 Pacific local time" in result.stdout
    assert "Taipei mapping: 07:30 PDT / 08:30 PST" in result.stdout
    assert "adapter waits for Taipei 08:30" in result.stdout
    assert "Execution policy: existing principal/settings preserved" in result.stdout
    assert "run_paper_portfolio_daily.cmd" in result.stdout
    assert "repo-isolated Paper state" in result.stdout
    assert "Dryrun only. No scheduled task was created." in result.stdout
    for other_task in (
        "baldr-formal-input-producer-daily",
        "baldr-paper-execution-eod-replay-daily",
        "baldr-ml-allocation-copilot-daily",
    ):
        assert other_task not in result.stdout


def test_dedicated_paper_portfolio_registration_register_calls_only_paper_task(
    tmp_path: Path,
) -> None:
    fake_schtasks = tmp_path / "fake_schtasks.cmd"
    fake_schtasks.write_text(
        "@echo off\n"
        "echo fake-schtasks %*\n"
        "echo %* | findstr /C:\"/Query\" >nul\n"
        "if errorlevel 1 exit /b 0\n"
        "if not exist \"%~dp0query_seen\" (\n"
        "  >\"%~dp0query_seen\" echo seen\n"
        "  echo ERROR: The system cannot find the path specified.\n"
        "  exit /b 1\n"
        ")\n"
        "exit /b 0\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["BALDR_SCHTASKS_EXE"] = str(fake_schtasks)

    result = _run_registration("register", env=env)

    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert (
        '/Create /TN "baldr-paper-portfolio-daily" '
        "/SC DAILY /ST 16:30"
    ) in result.stdout
    create_call = next(
        line for line in result.stdout.splitlines() if "/Create /TN" in line
    )
    assert not create_call.rstrip().endswith("/F")
    assert '/Query /TN "baldr-paper-portfolio-daily"' in result.stdout
    assert "baldr-formal-input-producer-daily" not in result.stdout
    assert "baldr-paper-execution-eod-replay-daily" not in result.stdout
    assert "baldr-ml-allocation-copilot-daily" not in result.stdout


def test_existing_paper_portfolio_task_uses_change_and_preserves_other_settings(
    tmp_path: Path,
) -> None:
    fake_schtasks = tmp_path / "fake_schtasks.cmd"
    fake_schtasks.write_text(
        "@echo off\n"
        "echo fake-schtasks %*\n"
        "exit /b 0\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["BALDR_SCHTASKS_EXE"] = str(fake_schtasks)

    result = _run_registration("register", env=env)

    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert (
        '/Change /TN "baldr-paper-portfolio-daily" '
        "/ST 16:30"
    ) in result.stdout
    assert '/Create /TN "baldr-paper-portfolio-daily"' not in result.stdout
    assert "Existing task found; updating only trigger and action." in result.stdout


def test_scheduler_query_error_is_fail_closed_and_does_not_create_task(
    tmp_path: Path,
) -> None:
    fake_schtasks = tmp_path / "fake_schtasks.cmd"
    fake_schtasks.write_text(
        "@echo off\n"
        "echo ERROR: Access is denied.\n"
        "exit /b 1\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["BALDR_SCHTASKS_EXE"] = str(fake_schtasks)

    result = _run_registration("register", env=env)

    assert result.returncode == 2, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "Scheduler query failed; refusing to create or change the task." in result.stdout
    assert "/Create" not in result.stdout
    assert "/Change" not in result.stdout


def test_dedicated_paper_portfolio_registration_rejects_non_pacific_timezone(
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

    assert result.returncode == 2, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "timezone must be Pacific Standard Time" in result.stdout
    assert "No scheduled task was created" not in result.stdout
