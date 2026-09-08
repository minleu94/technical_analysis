from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import data_module.formal_daily_input_producer as producer_module
from data_module.formal_daily_input_producer import (
    DailyFormalInputPaths,
    OfficialSourceResponse,
    _produce_pit_candidate,
    run_daily_formal_input_producer,
)
import data_module.formal_pit_history_handoff as history_handoff_module
from data_module.formal_pit_history_handoff import (
    FormalPITHistoryHandoffError,
    inspect_pit_candidate_archive_history,
    persist_pit_candidate_history_handoff,
    read_pit_candidate_history_handoff,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.prospective_official_pit_source import (
    OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
)
from scripts.scheduled import run_formal_input_producer_daily as scheduled_runner
from tests.test_formal_daily_input_producer import (
    _CaptureCalendar,
    _market_db,
    _pit_raw_payloads,
)


TAIPEI = ZoneInfo("Asia/Taipei")


class _FixtureDateTime(datetime):
    frozen_utc = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz: object = None) -> _FixtureDateTime:
        if tz is None:
            return cls.fromtimestamp(cls.frozen_utc.timestamp())
        return cls.fromtimestamp(cls.frozen_utc.timestamp(), tz)


class _AllTradingDays(OfficialTradingCalendar):
    """隔離測試日曆；不以週末推定交易日。"""

    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        return True, "test_official_calendar_evidence"


def _responses(
    captured_at: datetime,
    raw_payloads: dict[str, bytes] | None = None,
) -> dict[str, OfficialSourceResponse]:
    raw = raw_payloads or _pit_raw_payloads()
    return {
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint: OfficialSourceResponse(
            body=raw[market],
            metadata={
                "requested_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint,
                "final_url": OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint,
                "http_status": 200,
                "content_type": "application/json",
                "http_date": None,
                "http_last_modified": None,
                "captured_at": captured_at.isoformat(),
            },
        )
        for market in ("twse", "tpex")
    }


def _produce_with_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    captured_at: datetime | None = None,
    raw_payloads: dict[str, bytes] | None = None,
) -> tuple[DailyFormalInputPaths, dict[str, object]]:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "history-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "history-producer")
    captured = captured_at or datetime.now(timezone.utc) - timedelta(seconds=2)
    _FixtureDateTime.frozen_utc = captured.astimezone(timezone.utc) + timedelta(seconds=1)
    responses = _responses(captured, raw_payloads)
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "pit-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unused-market.sqlite",
        publication_root=tmp_path / "publication",
    )
    paths.output_root.mkdir()
    with monkeypatch.context() as clock_patch:
        clock_patch.setattr(producer_module, "datetime", _FixtureDateTime)
        result = _produce_pit_candidate(
            paths=paths,
            output_root=paths.output_root,
            observed=captured + timedelta(seconds=1),
            expected_symbols=None,
            fetch_source=lambda url: responses[url],
        )
    return paths, result


def _expected_universe_for_archive(archive_manifest: Path, output: Path) -> Path:
    manifest = json.loads(archive_manifest.read_text(encoding="utf-8"))
    publication_entry = next(
        item for item in manifest["files"] if item["role"] == "publication"
    )
    publication = json.loads(
        (archive_manifest.parent / publication_entry["relative_path"]).read_text(
            encoding="utf-8"
        )
    )
    symbols = publication["universe"]["symbols"]
    output.write_text(json.dumps(symbols, ensure_ascii=False), encoding="utf-8")
    return output


def test_archive_custody_stays_visible_when_universe_is_not_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, result = _produce_with_archive(tmp_path, monkeypatch)
    archive = result["durable_archive"]
    assert isinstance(archive, dict)

    report = inspect_pit_candidate_archive_history(
        paths.publication_root / "pit_candidate_archive",
        decision_at=datetime.now(timezone.utc),
        expected_universe_path=None,
        coverage_start=None,
        calendar=None,
    )

    assert report["status"] == "candidate_history_verified"
    assert report["valid_archive_count"] == 1
    assert report["invalid_archive_count"] == 0
    assert report["lineage"] == []
    blockers = report["blockers"]
    assert isinstance(blockers, list)
    assert "pit_formal_independent_expected_universe_missing" in blockers
    assert any(
        str(item).startswith("pit_formal_archive_universe_binding_failed:")
        for item in blockers
    )
    assert "pit_formal_license_scope_not_formally_accepted" in blockers
    assert "pit_formal_sidecar_publication_required" in blockers


def test_expected_universe_binding_is_checked_against_publication_rows_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, result = _produce_with_archive(tmp_path, monkeypatch)
    archive = result["durable_archive"]
    assert isinstance(archive, dict)
    manifest_path = Path(str(archive["archive_manifest_path"]))
    expected_path = _expected_universe_for_archive(
        manifest_path,
        tmp_path / "expected-pit-universe.json",
    )

    report = inspect_pit_candidate_archive_history(
        paths.publication_root / "pit_candidate_archive",
        decision_at=datetime.now(timezone.utc),
        expected_universe_path=expected_path,
        coverage_start=None,
        calendar=None,
    )
    assert report["valid_archive_count"] == 1
    lineage = report["lineage"]
    assert isinstance(lineage, list) and len(lineage) == 1
    assert lineage[0]["universe_match"] is True
    assert not any(
        str(item).startswith("pit_formal_archive_universe_binding_failed:")
        for item in report["blockers"]
    )

    expected_path.write_text(
        json.dumps(["0000", "1101", "1102", "5501"], ensure_ascii=False),
        encoding="utf-8",
    )
    mismatch = inspect_pit_candidate_archive_history(
        paths.publication_root / "pit_candidate_archive",
        decision_at=datetime.now(timezone.utc),
        expected_universe_path=expected_path,
        coverage_start=None,
        calendar=None,
    )
    assert mismatch["valid_archive_count"] == 1
    assert mismatch["lineage"] == []
    assert any(
        str(item).startswith("pit_formal_archive_universe_binding_failed:")
        for item in mismatch["blockers"]
    )

    copied_into_archive = manifest_path.parent / "copied-expected-universe.json"
    copied_into_archive.write_text(
        expected_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    copied_report = inspect_pit_candidate_archive_history(
        paths.publication_root / "pit_candidate_archive",
        decision_at=datetime.now(timezone.utc),
        expected_universe_path=copied_into_archive,
        coverage_start=None,
        calendar=None,
    )
    assert copied_report["lineage"] == []
    assert "pit_formal_independent_expected_universe_must_be_external" in copied_report[
        "blockers"
    ]


def test_taipei_cutoff_keeps_after_cutoff_capture_for_next_trading_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the cutoff calculation with a custody record whose timestamps
    # were already validated by the producer.  The full official archive
    # readback is covered by the tests above and by the producer integration
    # test below; this case isolates the natural-day boundary without creating
    # a historical source capture in the test process.
    capture_day = datetime(2026, 9, 7).date()
    next_day = capture_day + timedelta(days=1)
    manifest_path = (
        tmp_path / capture_day.isoformat() / "archive-1" / "archive_manifest.json"
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
            # 10:00 Taipei = 02:00 UTC, after the 08:30 Taipei cutoff.
            "captured_at": "2026-09-07T02:00:00+00:00",
            "available_at": "2026-09-07T02:00:00+00:00",
            "archived_at": "2026-09-07T02:01:00+00:00",
            "archive_decision_at": "2026-09-07T02:01:00+00:00",
            "effective_from": capture_day.isoformat(),
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
        decision_at=datetime.combine(next_day, time(9), tzinfo=TAIPEI),
        expected_universe_path=expected_path,
        coverage_start=capture_day,
        calendar=_AllTradingDays(tmp_path / "unused-market.sqlite"),
    )

    coverage = report["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["required_trading_dates"] == [
        capture_day.isoformat(),
        next_day.isoformat(),
    ]
    assert coverage["missing_trading_dates"] == [capture_day.isoformat()]
    assert coverage["covered_trading_dates"] == [next_day.isoformat()]
    assert any(
        str(item).startswith("pit_formal_history_missing_natural_days:")
        for item in report["blockers"]
    )


def test_handoff_retry_is_byte_idempotent_and_tamper_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _result = _produce_with_archive(tmp_path, monkeypatch)
    decision = datetime.now(timezone.utc) + timedelta(seconds=2)
    first = persist_pit_candidate_history_handoff(
        archive_root=paths.publication_root / "pit_candidate_archive",
        publication_root=paths.publication_root,
        decision_at=decision,
        expected_universe_path=None,
        coverage_start=None,
        calendar=None,
    )
    second = persist_pit_candidate_history_handoff(
        archive_root=paths.publication_root / "pit_candidate_archive",
        publication_root=paths.publication_root,
        decision_at=decision,
        expected_universe_path=None,
        coverage_start=None,
        calendar=None,
    )
    assert first["handoff_path"] == second["handoff_path"]
    assert first["handoff_file_hash"] == second["handoff_file_hash"]
    handoff_path = Path(str(first["handoff_path"]))
    payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    payload["projection"]["decision_at"] = "2099-01-01T00:00:00+00:00"
    handoff_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        FormalPITHistoryHandoffError,
        match="projection hash mismatch",
    ):
        read_pit_candidate_history_handoff(handoff_path)

    semantic_path = handoff_path.with_name("semantic-tamper.json")
    original = json.loads(
        (Path(str(first["handoff_path"]))).read_text(encoding="utf-8")
    )
    semantic_payload = dict(original)
    semantic_projection = dict(original["projection"])
    semantic_projection["formal_ready"] = True
    semantic_projection["handoff_content_hash"] = history_handoff_module._payload_hash(
        {
            key: value
            for key, value in semantic_projection.items()
            if key != "handoff_content_hash"
        }
    )
    semantic_payload["projection"] = semantic_projection
    semantic_body = dict(semantic_payload)
    semantic_body.pop("handoff_hash", None)
    semantic_payload["handoff_hash"] = history_handoff_module._payload_hash(
        semantic_body
    )
    semantic_path.write_text(
        json.dumps(semantic_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        FormalPITHistoryHandoffError,
        match="formal flags are invalid",
    ):
        read_pit_candidate_history_handoff(semantic_path)


def test_public_daily_runner_persists_candidate_history_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "runner-history-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "runner-history")
    captured_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    responses = _responses(captured_at)
    market_db = _market_db(tmp_path)
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "candidate",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=market_db,
        publication_root=tmp_path / "publication",
    )
    paths.output_root.mkdir()
    receipt = run_daily_formal_input_producer(
        paths,
        now=captured_at + timedelta(seconds=1),
        calendar=_CaptureCalendar(
            market_db,
            result=None,
            reason="history_handoff_calendar_unknown",
        ),
        fetch_source=lambda url: responses[url],
    )

    inputs = receipt["inputs"]
    assert isinstance(inputs, dict)
    pit = inputs["pit_candidate"]
    assert isinstance(pit, dict)
    handoff = pit["formal_history_handoff"]
    assert isinstance(handoff, dict)
    assert handoff["status"] == "candidate_history_verified"
    assert handoff["formal_ready"] is False
    assert handoff["candidate_only"] is True
    assert handoff["handoff_readback_verified"] is True
    assert Path(str(handoff["handoff_path"])).is_file()
    assert "pit_formal_sidecar_publication_required" in handoff["blockers"]
    assert "pit_formal_sidecar_publication_required" in receipt["blockers"]


def test_scheduled_paths_forward_optional_pit_history_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_path = tmp_path / "pit-expected-universe.json"
    expected_path.write_text(json.dumps(["1101"]), encoding="utf-8")
    monkeypatch.setenv("FORMAL_DAILY_PIT_EXPECTED_UNIVERSE", str(expected_path))
    monkeypatch.setenv("FORMAL_DAILY_PIT_HISTORY_COVERAGE_START", "2026-09-07")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_ROOT", str(tmp_path / "output"))

    paths = scheduled_runner._build_paths(
        source_paths={},
        publication_root=tmp_path / "publication",
    )

    assert paths.pit_expected_universe_path == expected_path.resolve()
    assert paths.pit_history_coverage_start == datetime(2026, 9, 7).date()
