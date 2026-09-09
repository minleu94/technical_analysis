from __future__ import annotations

import os
from pathlib import Path
import subprocess

import scripts.inspect_scheduler_health_observability as cli


ROOT = Path(__file__).resolve().parents[1]


def test_scheduler_health_cli_defaults_honor_environment_without_config_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "configured-data"
    output_root = tmp_path / "configured-output"
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))

    args = cli.build_parser().parse_args([])

    assert args.data_root is None
    assert args.output_root is None
    assert not data_root.exists()
    assert not output_root.exists()


def test_scheduler_health_data_root_override_derives_output_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATA_ROOT", raising=False)
    monkeypatch.delenv("OUTPUT_ROOT", raising=False)

    class FakeReport:
        audited_at = "2026-09-08T13:00:00"
        overall_health = "HEALTHY"
        production_scheduler_allowed = False
        ordering_valid = True
        tasks = ()
        advisory_notes = ()

        def to_dict(self) -> dict[str, object]:
            return {"overall_health": self.overall_health}

    class FakeService:
        def __init__(self, config: object) -> None:
            assert getattr(config, "data_root") == tmp_path / "only-data"
            assert getattr(config, "output_root") == tmp_path / "only-data" / "output"

        def audit_scheduler_health(self) -> FakeReport:
            return FakeReport()

    monkeypatch.setattr(cli, "SchedulerHealthService", FakeService)
    cli.run_scheduler_health_inspection(data_root=tmp_path / "only-data")


def test_scheduler_health_run_writes_only_explicit_report_paths(tmp_path: Path, monkeypatch) -> None:
    class FakeReport:
        audited_at = "2026-09-08T13:00:00"
        overall_health = "HEALTHY"
        production_scheduler_allowed = False
        ordering_valid = True
        tasks = ()
        advisory_notes = ()

        def to_dict(self) -> dict[str, object]:
            return {"overall_health": self.overall_health}

    class FakeService:
        def __init__(self, config: object) -> None:
            assert getattr(config, "data_root") == tmp_path / "data"
            assert getattr(config, "output_root") == tmp_path / "output"

        def audit_scheduler_health(self) -> FakeReport:
            return FakeReport()

    monkeypatch.setattr(cli, "SchedulerHealthService", FakeService)
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    result = cli.run_scheduler_health_inspection(
        data_root=data_root,
        output_root=output_root,
    )

    assert result == {"overall_health": "HEALTHY"}
    assert not data_root.exists()
    assert not output_root.exists()

    output_path = tmp_path / "reports" / "health.json"
    cli.run_scheduler_health_inspection(
        data_root=data_root,
        output_root=output_root,
        output=output_path,
    )
    assert output_path.is_file()


def test_scheduler_health_help_is_zero_exit_and_does_not_create_reports(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["DATA_ROOT"] = str(tmp_path / "data")
    env["OUTPUT_ROOT"] = str(tmp_path / "output")
    result = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            str(ROOT / "scripts" / "inspect_scheduler_health_observability.py"),
            "--help",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=False,
        check=False,
    )

    stdout = (result.stdout or b"").decode("utf-8", errors="replace")
    stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    assert result.returncode == 0, stderr
    assert "唯讀稽核排程健康" in stdout
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "output").exists()
