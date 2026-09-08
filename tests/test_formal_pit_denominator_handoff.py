from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import tests.test_pit_prospective_denominator as denominator_fixtures
import data_module.formal_pit_history_handoff as history_handoff_module
from data_module.formal_pit_history_handoff import inspect_pit_candidate_archive_history
from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.pit_prospective_denominator import build_prospective_pit_denominator
from tests.test_formal_pit_history_handoff import _AllTradingDays, _produce_with_archive


TAIPEI = ZoneInfo("Asia/Taipei")
FIXTURE_DAY = date(2026, 9, 8)
FIXTURE_CAPTURED_AT = datetime(2026, 9, 8, 6, 0, tzinfo=TAIPEI)


class _ClosedTradingCalendar(OfficialTradingCalendar):
    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        del target_date, allow_online_probe
        return False, "test_official_closed"


def _build_denominator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(denominator_fixtures, "NOW", FIXTURE_CAPTURED_AT)
    arguments = denominator_fixtures._inputs(monkeypatch)
    output = tmp_path / "denominator"
    arguments["output_dir"] = output
    build_prospective_pit_denominator(**arguments)
    return output / "denominator.json"


def _archive_and_denominator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    paths, result = _produce_with_archive(
        tmp_path,
        monkeypatch,
        captured_at=FIXTURE_CAPTURED_AT,
    )
    archive_root = paths.publication_root / "pit_candidate_archive"
    denominator_path = _build_denominator(tmp_path, monkeypatch)
    return archive_root, denominator_path


def test_verified_denominator_removes_only_objective_universe_and_license_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root, denominator_path = _archive_and_denominator(tmp_path, monkeypatch)

    report = inspect_pit_candidate_archive_history(
        archive_root,
        decision_at=datetime(2026, 9, 8, 9, 0, tzinfo=TAIPEI),
        expected_universe_path=denominator_path,
        coverage_start=date(2026, 9, 8),
        calendar=_AllTradingDays(tmp_path / "calendar.sqlite"),
    )

    universe = report["independent_universe"]
    assert isinstance(universe, dict)
    assert universe["state"] == "verified"
    assert universe["symbol_count"] == 4
    assert report["valid_archive_count"] == 1
    assert len(report["lineage"]) == 1
    blockers = report["blockers"]
    assert "pit_formal_independent_expected_universe_missing" not in blockers
    assert "pit_formal_license_scope_not_formally_accepted" not in blockers
    assert "pit_formal_license_use_scope_missing" not in blockers
    assert blockers == ["pit_formal_sidecar_publication_required"]
    assert report["license_scope"]["status"] == "machine_scope_verified"


def test_handoff_does_not_credit_current_day_before_taipei_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root, denominator_path = _archive_and_denominator(tmp_path, monkeypatch)

    report = inspect_pit_candidate_archive_history(
        archive_root,
        decision_at=datetime(2026, 9, 8, 7, 0, tzinfo=TAIPEI),
        expected_universe_path=denominator_path,
        coverage_start=date(2026, 9, 8),
        calendar=_AllTradingDays(tmp_path / "calendar.sqlite"),
    )
    coverage = report["coverage"]
    assert coverage["required_trading_dates"] == ["2026-09-08"]
    assert coverage["covered_trading_dates"] == []
    assert coverage["missing_trading_dates"] == ["2026-09-08"]
    assert "pit_formal_decision_before_current_day_cutoff:2026-09-08" in report[
        "blockers"
    ]


def test_handoff_never_accepts_empty_required_trading_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root, denominator_path = _archive_and_denominator(tmp_path, monkeypatch)

    report = inspect_pit_candidate_archive_history(
        archive_root,
        decision_at=datetime(2026, 9, 8, 9, 0, tzinfo=TAIPEI),
        expected_universe_path=denominator_path,
        coverage_start=date(2026, 9, 8),
        calendar=_ClosedTradingCalendar(tmp_path / "calendar.sqlite"),
    )
    assert report["coverage"]["required_trading_dates"] == []
    assert "pit_formal_required_trading_dates_empty" in report["blockers"]


def test_prospective_coverage_does_not_credit_archive_before_declared_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coverage_start = date(2026, 9, 8)
    prior_day = coverage_start - timedelta(days=1)
    manifest_path = (
        tmp_path / prior_day.isoformat() / "archive-1" / "archive_manifest.json"
    )
    expected_path = tmp_path / "expected-pit-universe.json"
    expected_path.write_text(json.dumps(["1101"]), encoding="utf-8")
    monkeypatch.setattr(
        history_handoff_module,
        "_discover_archive_manifests",
        lambda _root, _blockers: [manifest_path],
    )
    monkeypatch.setattr(
        history_handoff_module,
        "_read_archive_observation",
        lambda *_args, **_kwargs: {
            "archive_id": "archive-1",
            "archive_manifest_path": str(manifest_path),
            "archive_manifest_hash": "sha256:" + "a" * 64,
            "archive_file_hash": "sha256:" + "b" * 64,
            "publication_content_hash": "sha256:" + "c" * 64,
            "capture_id": "capture-1",
            "captured_at": "2026-09-07T01:00:00+00:00",
            "available_at": "2026-09-07T01:00:00+00:00",
            "archived_at": "2026-09-07T01:01:00+00:00",
            "archive_decision_at": "2026-09-07T01:01:00+00:00",
            "effective_from": prior_day.isoformat(),
            "row_count": 1,
            "source_ids": ["official:test"],
            "license_status": "declared_official_open_api_identity",
            "license_formal_acceptance_granted": False,
            "license_allowed_use_cases": ["research_shadow"],
            "universe_match": True,
            "universe_binding_reason": None,
        },
    )

    report = inspect_pit_candidate_archive_history(
        tmp_path / "pit_candidate_archive",
        decision_at=datetime(2026, 9, 8, 9, 0, tzinfo=TAIPEI),
        expected_universe_path=expected_path,
        coverage_start=coverage_start,
        calendar=_AllTradingDays(tmp_path / "calendar.sqlite"),
    )

    coverage = report["coverage"]
    assert coverage["required_trading_dates"] == [coverage_start.isoformat()]
    assert coverage["covered_trading_dates"] == []
    assert coverage["missing_trading_dates"] == [coverage_start.isoformat()]
    assert any(
        str(item).startswith("pit_formal_history_missing_natural_days:")
        for item in report["blockers"]
    )


def test_tampered_denominator_child_keeps_archive_binding_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root, denominator_path = _archive_and_denominator(tmp_path, monkeypatch)
    child = denominator_path.parent / "twse_t187ap03.csv"
    child.write_bytes(child.read_bytes() + b"\n")

    report = inspect_pit_candidate_archive_history(
        archive_root,
        decision_at=datetime(2026, 9, 8, 9, 0, tzinfo=TAIPEI),
        expected_universe_path=denominator_path,
        coverage_start=date(2026, 9, 8),
        calendar=_AllTradingDays(tmp_path / "calendar.sqlite"),
    )
    assert report["lineage"] == []
    assert any(
        str(item).startswith("pit_formal_independent_expected_universe_invalid:")
        for item in report["blockers"]
    )
    assert any(
        str(item).startswith("pit_formal_archive_universe_binding_failed:")
        for item in report["blockers"]
    )
