from __future__ import annotations

from datetime import datetime
import gzip
import json
from pathlib import Path

import pytest

from data_module.prospective_formal_clock import (
    build_clock_manifest,
    canonical_json,
    load_clock_manifest_for_capture,
    payload_hash,
)
from data_module.prospective_pit_sector_membership import (
    PIT_SECTOR_MEMBERSHIP_PROSPECTIVE_MANIFEST_SCHEMA_VERSION,
    ProspectivePitSectorMembershipError,
    capture_prospective_pit_sector_membership,
    validate_prospective_pit_sector_membership,
)


_NOW = datetime.fromisoformat("2026-08-17T09:00:00+08:00")


def _clock(
    tmp_path: Path,
    *,
    decision_time: str = "08:30:00",
    pit_decision_time: str | None = None,
):
    seed = {"kind": "cash", "cash_bp": 10_000, "position_count": 0}
    seed["state_hash"] = payload_hash(seed)
    calendar = {
        "schema_version": "official-trading-calendar-evidence.v1",
        "date": "2026-08-17",
        "is_trading_day": True,
        "reason_code": "twse_holiday_schedule_open",
        "source": "TWSE holidaySchedule",
        "source_hash": "sha256:" + "1" * 64,
    }
    body: dict[str, object] = {
        "schema_version": "prospective-formal-simulated-portfolio-clock.v1",
        "status": "planned",
        "clock_id": "clock:prospective:pfs04:r1",
        "mode": "prospective_formal_simulation",
        "owner_decision_id": "owner-decision:pfs04-test",
        "owner_decision_timestamp": "2026-08-14T08:45:00+08:00",
        "activation_trading_day": "2026-08-17",
        "decision_timezone": "Asia/Taipei",
        "decision_time": decision_time,
        "activation_calendar_evidence": calendar,
        "seed_state": seed,
        "virtual_notional_minor_units": 1_000_000,
        "strategy_version": "rule-v1",
        "policy_version": "policy-v1",
        "policy_hash": "sha256:" + "2" * 64,
        "universe_hash": "sha256:" + "5" * 64,
        "source_policy_hash": "sha256:" + "6" * 64,
        "candidate_model_hash": "sha256:" + "7" * 64,
        "candidate_feature_manifest_hash": "sha256:" + "8" * 64,
        "candidate_training_cutoff": "2026-08-13T08:30:00+08:00",
        "calibration_policy_hash": "sha256:" + "9" * 64,
        "evaluation_policy_hash": "sha256:" + "a" * 64,
        "real_money": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
    }
    if pit_decision_time is not None:
        body["pit_decision_time"] = pit_decision_time
    path = tmp_path / "clock.json"
    path.write_text(json.dumps(build_clock_manifest(body)), encoding="utf-8")
    return load_clock_manifest_for_capture(path, now=_NOW)


def _source_registry() -> list[dict[str, object]]:
    return [
        {
            "source_id": "twse-t97-prospective",
            "license_id": "license:owner-authorized-test",
            "source_hash": "sha256:" + "b" * 64,
            "source_version": "t97:test:v1",
            "publication_at": "2026-08-16T22:00:00+08:00",
            "allowed_use": ["prospective_pit_sector_membership"],
        }
    ]


def _rows() -> list[dict[str, object]]:
    return [
        {
            "symbol": "2317",
            "sector_id": "semiconductor",
            "available_at": "2026-08-17T08:00:00+08:00",
            "effective_from": "2026-08-17",
            "effective_to": None,
            "status": "accepted",
            "source_id": "twse-t97-prospective",
            "license_id": "license:owner-authorized-test",
            "source_hash": "sha256:" + "b" * 64,
        },
        {
            "symbol": "2330",
            "sector_id": "semiconductor",
            "available_at": "2026-08-17T08:00:00+08:00",
            "effective_from": "2026-08-17",
            "effective_to": None,
            "status": "accepted",
            "source_id": "twse-t97-prospective",
            "license_id": "license:owner-authorized-test",
            "source_hash": "sha256:" + "b" * 64,
        },
    ]


def _capture_kwargs(tmp_path: Path, clock, output: Path):
    return {
        "clock": clock,
        "output_path": output,
        "decision_timestamp": "2026-08-17T08:30:00+08:00",
        "now": _NOW,
        "rows": _rows(),
        "source_registry": _source_registry(),
        "expected_symbols": ("2317", "2330"),
    }


@pytest.mark.parametrize("suffix", (".json", ".jsonl", ".jsonl.gz"))
def test_capture_and_validate_supported_sidecar_formats(
    tmp_path: Path,
    suffix: str,
) -> None:
    clock = _clock(tmp_path)
    path = tmp_path / f"pit_membership{suffix}"
    result = capture_prospective_pit_sector_membership(
        **_capture_kwargs(tmp_path, clock, path)
    )
    validated = validate_prospective_pit_sector_membership(
        sidecar_path=path,
        clock=clock,
        decision_timestamp="2026-08-17T08:30:00+08:00",
        now=_NOW,
        expected_symbols=("2317", "2330"),
    )
    assert result.row_count == 2
    assert validated.canonical_hash == result.canonical_hash
    assert validated.rows_hash == result.rows_hash
    assert validated.source_ids == ("twse-t97-prospective",)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = path.read_bytes()
        if suffix.endswith(".gz"):
            raw = gzip.decompress(raw)
        payload = json.loads(raw.decode("utf-8").splitlines()[0])
    assert payload["manifest"]["schema_version"] == (
        PIT_SECTOR_MEMBERSHIP_PROSPECTIVE_MANIFEST_SCHEMA_VERSION
    )
    assert payload["manifest"]["historical_backfill_claimed"] is False


def test_pit_capture_uses_separate_pit_boundary(tmp_path: Path) -> None:
    clock = _clock(
        tmp_path,
        decision_time="09:00:00",
        pit_decision_time="08:30:00",
    )
    result = capture_prospective_pit_sector_membership(
        **_capture_kwargs(tmp_path, clock, tmp_path / "pit_separate_boundary.json")
    )

    assert result.coverage_end == "2026-08-17"


def test_source_license_and_status_lineage_are_required(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    rows = _rows()
    rows[0]["status"] = "research"
    with pytest.raises(ProspectivePitSectorMembershipError, match="status"):
        capture_prospective_pit_sector_membership(
            **{
                **_capture_kwargs(tmp_path, clock, tmp_path / "blocked.json"),
                "rows": rows,
            }
        )

    sources = _source_registry()
    sources[0]["license_id"] = "unknown"
    with pytest.raises(ProspectivePitSectorMembershipError, match="license"):
        capture_prospective_pit_sector_membership(
            **{
                **_capture_kwargs(tmp_path, clock, tmp_path / "blocked2.json"),
                "source_registry": sources,
            }
        )

    sources = _source_registry()
    sources[0]["source_id"] = "companies.csv"
    rows = _rows()
    rows[0]["source_id"] = "companies.csv"
    with pytest.raises(ProspectivePitSectorMembershipError, match="current company"):
        capture_prospective_pit_sector_membership(
            **{
                **_capture_kwargs(tmp_path, clock, tmp_path / "blocked3.json"),
                "source_registry": sources,
                "rows": rows,
            }
        )


def test_future_available_at_and_incomplete_universe_fail_closed(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    rows = _rows()
    rows[0]["available_at"] = "2026-08-17T09:00:01+08:00"
    with pytest.raises(ProspectivePitSectorMembershipError, match="available_at"):
        capture_prospective_pit_sector_membership(
            **{
                **_capture_kwargs(tmp_path, clock, tmp_path / "blocked.json"),
                "rows": rows,
            }
        )
    with pytest.raises(ProspectivePitSectorMembershipError, match="symbol universe"):
        capture_prospective_pit_sector_membership(
            **{
                **_capture_kwargs(tmp_path, clock, tmp_path / "blocked2.json"),
                "expected_symbols": ("2317", "2330", "6505"),
            }
        )


def test_historical_or_preactivation_effective_from_is_rejected(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    rows = _rows()
    rows[0]["effective_from"] = "2014-01-03"
    with pytest.raises(
        ProspectivePitSectorMembershipError,
        match="outside prospective coverage",
    ):
        capture_prospective_pit_sector_membership(
            **{
                **_capture_kwargs(tmp_path, clock, tmp_path / "historical.json"),
                "rows": rows,
            }
        )


def test_manifest_tamper_and_output_immutability_are_rejected(tmp_path: Path) -> None:
    clock = _clock(tmp_path)
    path = tmp_path / "pit_membership.json"
    capture_prospective_pit_sector_membership(
        **_capture_kwargs(tmp_path, clock, path)
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"][0]["sector_id"] = "forged"
    path.write_text(canonical_json(payload), encoding="utf-8")
    with pytest.raises(ProspectivePitSectorMembershipError, match="rows_hash"):
        validate_prospective_pit_sector_membership(
            sidecar_path=path,
            clock=clock,
            decision_timestamp="2026-08-17T08:30:00+08:00",
            now=_NOW,
            expected_symbols=("2317", "2330"),
        )

    valid_path = tmp_path / "valid.json"
    capture_prospective_pit_sector_membership(
        **_capture_kwargs(tmp_path, clock, valid_path)
    )
    with pytest.raises(ProspectivePitSectorMembershipError, match="already exists"):
        capture_prospective_pit_sector_membership(
            **_capture_kwargs(tmp_path, clock, valid_path)
        )


def test_fixture_cli_requires_explicit_inputs_and_writes_no_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.capture_prospective_pit_sector_membership import main

    clock_path = tmp_path / "clock.json"
    clock = _clock(tmp_path)
    clock_payload = json.loads(clock_path.read_text(encoding="utf-8"))
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps(_rows()), encoding="utf-8")
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps(_source_registry()), encoding="utf-8")
    symbols_path = tmp_path / "symbols.json"
    symbols_path.write_text(json.dumps(["2317", "2330"]), encoding="utf-8")
    output_path = tmp_path / "captured.jsonl.gz"

    exit_code = main(
        [
            "--fixture-only",
            "--clock-manifest",
            str(clock_path),
            "--now",
            _NOW.isoformat(),
            "--decision-timestamp",
            "2026-08-17T08:30:00+08:00",
            "--rows-json",
            str(rows_path),
            "--source-registry-json",
            str(sources_path),
            "--symbols-json",
            str(symbols_path),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output_path.is_file()
    assert '"status": "accepted"' in captured.out
    assert captured.err == ""
    assert clock_payload["clock_id"] == clock.clock_id
