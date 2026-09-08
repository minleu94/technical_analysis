from __future__ import annotations

import io
from pathlib import Path
import sys

import pytest

from scripts.apply_monthly_revenue_availability_candidate import main
from data_module.monthly_revenue_availability_merge import (
    apply_monthly_revenue_availability_merge,
    plan_monthly_revenue_availability_merge,
)


_HEADER = (
    "stock_code,period,as_of_date,announced_date,available_date,source,source_version,"
    "availability_contract_version,evidence_class,source_hash,revision,parent_revision\n"
)


def _formal_row(
    *,
    stock_code: str = "2330",
    period: str = "2026-07",
    announced_date: str = "2026-08-17",
    available_date: str = "2026-08-18",
    source_version: str = "twse-openapi-t187ap05-l-2026-08-28",
    source_hash: str = "sha256:" + "a" * 64,
    revision: str = "1",
    parent_revision: str = "",
) -> str:
    return (
        f"{stock_code},{period},{period}-31,{announced_date},{available_date},"
        f"twse.monthly_revenue_announcement,{source_version},formal-availability.v2,"
        f"official_announcement,{source_hash},{revision},{parent_revision}\n"
    )


def _legacy_row() -> str:
    return (
        "1101,2026-06,2026-06-30,2026-07-14,2026-07-15,"
        "twse.monthly_revenue_announcement,"
        "twse-openapi-t187ap05-l-2026-07-14,,,,,\n"
    )


def _write(path: Path, text: str) -> None:
    path.write_text(_HEADER + text, encoding="utf-8-sig")


def test_preview_merges_new_candidate_without_writing_target(tmp_path, capsys):
    target = tmp_path / "meta_data" / "monthly_revenue_availability.csv"
    target.parent.mkdir()
    _write(target, _legacy_row())
    candidate = tmp_path / "candidate.csv"
    _write(candidate, _formal_row())
    before = target.read_bytes()

    assert main(["--candidate", str(candidate), "--target", str(target)]) == 0

    output = capsys.readouterr().out
    assert "ready_for_apply: `true`" in output
    assert "added_count: `1`" in output
    assert target.read_bytes() == before


def test_preview_reports_conflicting_natural_key_and_fails_closed(tmp_path, capsys):
    target = tmp_path / "monthly_revenue_availability.csv"
    _write(target, _formal_row(source_hash="sha256:" + "b" * 64))
    candidate = tmp_path / "candidate.csv"
    _write(candidate, _formal_row(source_hash="sha256:" + "c" * 64))

    assert main(["--candidate", str(candidate), "--target", str(target)]) == 1

    output = capsys.readouterr().out
    assert "ready_for_apply: `false`" in output
    assert "conflict_count: `1`" in output
    assert "fundamental_availability.merge_conflict" in output


def test_apply_requires_exact_confirmation_and_does_not_write(tmp_path, capsys):
    target = tmp_path / "monthly_revenue_availability.csv"
    _write(target, _legacy_row())
    candidate = tmp_path / "candidate.csv"
    _write(candidate, _formal_row())
    before = target.read_bytes()

    assert main(["--candidate", str(candidate), "--target", str(target), "--apply"]) == 2

    assert target.read_bytes() == before
    assert "requires --confirm apply-monthly-revenue-availability" in capsys.readouterr().err


def test_apply_writes_atomic_merge_and_retains_backup(tmp_path, capsys):
    target = tmp_path / "monthly_revenue_availability.csv"
    _write(target, _legacy_row())
    candidate = tmp_path / "candidate.csv"
    _write(candidate, _formal_row())
    backup_dir = tmp_path / "backup"

    assert (
        main(
            [
                "--candidate",
                str(candidate),
                "--target",
                str(target),
                "--backup-dir",
                str(backup_dir),
                "--apply",
                "--confirm",
                "apply-monthly-revenue-availability",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "status: `applied`" in output
    assert "added_count: `1`" in output
    merged = target.read_text(encoding="utf-8-sig")
    assert "1101,2026-06" in merged
    assert "2330,2026-07" in merged
    assert list(backup_dir.glob("monthly_revenue_availability_monthly_revenue_availability_merge_*.csv"))
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_repeating_same_candidate_is_idempotent_and_does_not_create_backup(tmp_path, capsys):
    target = tmp_path / "monthly_revenue_availability.csv"
    _write(target, _legacy_row())
    candidate = tmp_path / "candidate.csv"
    _write(candidate, _formal_row())
    backup_dir = tmp_path / "backup"
    arguments = [
        "--candidate",
        str(candidate),
        "--target",
        str(target),
        "--backup-dir",
        str(backup_dir),
        "--apply",
        "--confirm",
        "apply-monthly-revenue-availability",
    ]

    assert main(arguments) == 0
    capsys.readouterr()
    backups_after_first = list(backup_dir.glob("*.csv"))
    assert main(arguments) == 0

    output = capsys.readouterr().out
    assert "added_count: `0`" in output
    assert "unchanged_count: `1`" in output
    assert list(backup_dir.glob("*.csv")) == backups_after_first


def test_revision_candidate_is_appended_without_replacing_prior_mapping_revision(
    tmp_path,
    capsys,
):
    target = tmp_path / "monthly_revenue_availability.csv"
    _write(target, _formal_row())
    candidate = tmp_path / "candidate.csv"
    _write(
        candidate,
        _formal_row()
        + _formal_row(
            announced_date="2026-08-01",
            available_date="2026-08-02",
            source_version="twse-openapi-t187ap05-l-2026-09-07",
            source_hash="sha256:" + "b" * 64,
            revision="2",
            parent_revision="1",
        ),
    )
    backup_dir = tmp_path / "backup"

    assert (
        main(
            [
                "--candidate",
                str(candidate),
                "--target",
                str(target),
                "--backup-dir",
                str(backup_dir),
                "--apply",
                "--confirm",
                "apply-monthly-revenue-availability",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "added_count: `1`" in output
    assert "unchanged_count: `1`" in output
    merged = target.read_text(encoding="utf-8-sig")
    assert ",1,\n" in merged
    assert ",2,1\n" in merged
    assert len(list(backup_dir.glob("*.csv"))) == 1


def test_apply_rejects_mapping_changed_after_plan_without_overwriting_writer(
    tmp_path,
):
    target = tmp_path / "monthly_revenue_availability.csv"
    _write(target, _legacy_row())
    candidate = tmp_path / "candidate.csv"
    _write(candidate, _formal_row())
    plan = plan_monthly_revenue_availability_merge(
        candidate_file=candidate,
        target_file=target,
    )
    concurrent_row = _formal_row(
        stock_code="2317",
        source_version="concurrent-writer-v1",
        source_hash="sha256:" + "d" * 64,
    )
    target.write_text(_HEADER + concurrent_row, encoding="utf-8-sig")

    with pytest.raises(RuntimeError, match="target changed after planning"):
        apply_monthly_revenue_availability_merge(
            plan=plan,
            backup_dir=tmp_path / "backup",
        )

    assert "2317,2026-07" in target.read_text(encoding="utf-8-sig")


def test_cli_help_reconfigures_windows_console_before_argparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chinese merge help must remain printable on cp1252 hosts."""

    payload = io.BytesIO()
    stream = io.TextIOWrapper(payload, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    stream.flush()
    assert exc_info.value.code == 0
    assert "預設" in payload.getvalue().decode("utf-8")
