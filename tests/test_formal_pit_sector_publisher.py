from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

import pytest

import data_module.formal_pit_sector_publisher as publisher_module
from data_module.formal_pit_history_handoff import (
    persist_pit_candidate_history_handoff,
)
from data_module.formal_pit_sector_publisher import (
    FormalPITSectorPublisherError,
    consume_formal_pit_sector_sidecar,
    publish_formal_pit_sector_sidecar,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from tests.test_formal_pit_denominator_handoff import (
    FIXTURE_CAPTURED_AT,
    FIXTURE_DAY,
    _build_denominator,
)
from tests.test_formal_pit_history_handoff import _AllTradingDays, _produce_with_archive


TAIPEI = ZoneInfo("Asia/Taipei")


class _ClosedTradingCalendar(OfficialTradingCalendar):
    def is_official_trading_day(
        self,
        target_date: date,
        allow_online_probe: bool = True,
    ) -> tuple[bool | None, str]:
        del target_date, allow_online_probe
        return False, "test_official_closed"


def _ready_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision_hour: int,
    calendar: OfficialTradingCalendar | None = None,
) -> tuple[Path, Path, Path, datetime, Path]:
    paths, _result = _produce_with_archive(
        tmp_path,
        monkeypatch,
        captured_at=FIXTURE_CAPTURED_AT,
    )
    denominator_path = _build_denominator(tmp_path, monkeypatch)
    natural_day = FIXTURE_DAY
    decision = datetime.combine(
        natural_day,
        time(decision_hour, 0),
        tzinfo=TAIPEI,
    )
    handoff = persist_pit_candidate_history_handoff(
        archive_root=paths.publication_root / "pit_candidate_archive",
        publication_root=paths.publication_root,
        decision_at=decision,
        expected_universe_path=denominator_path,
        coverage_start=natural_day,
        calendar=calendar or _AllTradingDays(tmp_path / "calendar.sqlite"),
    )
    return (
        paths.publication_root / "pit_candidate_archive",
        Path(str(handoff["handoff_path"])),
        denominator_path,
        decision,
        paths.output_root,
    )


def test_formal_sidecar_publishes_and_reads_through_existing_assembler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root, handoff_path, denominator_path, decision, candidate_root = _ready_handoff(
        tmp_path,
        monkeypatch,
        decision_hour=9,
    )
    del archive_root
    # The formal path must be able to use the durable archive after the
    # producer's bounded working directory has been removed.
    shutil.rmtree(candidate_root)

    result = publish_formal_pit_sector_sidecar(
        handoff_path=handoff_path,
        denominator_path=denominator_path,
        publication_root=tmp_path / "formal-publication",
        decision_at=decision,
        now=decision,
    )

    assert result["status"] == "formal_source_publication"
    assert result["formal_ready"] is True
    assert result["formal_consumer_compatible"] is True
    assert result["candidate_only"] is False
    assert result["formal_oos_allowed"] is False
    assert result["promotion_eligible"] is False
    assert result["production_action_allowed"] is False
    assert result["consumer_verified"] is True
    assert result["row_count"] == 4

    sidecar_path = Path(str(result["sidecar_path"]))
    receipt_path = Path(str(result["receipt_path"]))
    assert sidecar_path.is_file()
    assert receipt_path.is_file()
    consumed = consume_formal_pit_sector_sidecar(
        sidecar_path,
        receipt_path=receipt_path,
        decision_at=decision,
        now=decision,
    )
    assert consumed["consumer_readback"]["consumer_verified"] is True
    assert consumed["consumer_readback"]["spooled_row_count"] == 4

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["scope"] == "prospective_pit_sector_membership"
    assert receipt["historical_backfill_claimed"] is False
    assert receipt["formal_ready"] is True
    assert receipt["candidate_only"] is False


def test_formal_sidecar_keeps_current_day_before_taipei_cutoff_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _archive_root, handoff_path, denominator_path, decision, _candidate_root = _ready_handoff(
        tmp_path,
        monkeypatch,
        decision_hour=7,
    )

    result = publish_formal_pit_sector_sidecar(
        handoff_path=handoff_path,
        denominator_path=denominator_path,
        publication_root=tmp_path / "formal-publication",
        decision_at=decision,
        now=decision,
    )

    assert result["status"] == "blocked"
    blockers = result["blockers"]
    assert "pit_formal_decision_before_current_day_cutoff:" + decision.date().isoformat() in blockers
    assert result["formal_ready"] is False
    assert result["candidate_only"] is True
    assert not Path(str(result["sidecar_path"])).exists()
    assert Path(str(result["blocked_receipt_path"])).is_file()


def test_formal_sidecar_rejects_empty_official_required_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _archive_root, handoff_path, denominator_path, decision, _candidate_root = _ready_handoff(
        tmp_path,
        monkeypatch,
        decision_hour=9,
        calendar=_ClosedTradingCalendar(tmp_path / "calendar.sqlite"),
    )

    result = publish_formal_pit_sector_sidecar(
        handoff_path=handoff_path,
        denominator_path=denominator_path,
        publication_root=tmp_path / "formal-publication",
        decision_at=decision,
        now=decision,
    )

    assert result["status"] == "blocked"
    assert "pit_formal_required_trading_dates_empty" in result["blockers"]
    assert not Path(str(result["sidecar_path"])).exists()


def test_formal_sidecar_receipt_write_interruption_recovers_without_mutating_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _archive_root, handoff_path, denominator_path, decision, _candidate_root = _ready_handoff(
        tmp_path,
        monkeypatch,
        decision_hour=9,
    )
    publication_root = tmp_path / "formal-publication"
    original_writer = publisher_module._write_create_only_json
    state = {"failed": False}

    def fail_once(path: Path, payload: dict[str, object]) -> None:
        if path.name == "receipt.json" and not state["failed"]:
            state["failed"] = True
            raise FormalPITSectorPublisherError("simulated receipt interruption")
        original_writer(path, payload)

    monkeypatch.setattr(publisher_module, "_write_create_only_json", fail_once)
    first = publish_formal_pit_sector_sidecar(
        handoff_path=handoff_path,
        denominator_path=denominator_path,
        publication_root=publication_root,
        decision_at=decision,
        now=decision,
    )

    assert first["status"] == "blocked"
    assert "pit_formal_sidecar_publication_failed:simulated receipt interruption" in first[
        "blockers"
    ]
    sidecar_path = Path(str(first["sidecar_path"]))
    assert sidecar_path.is_file()
    sidecar_bytes = sidecar_path.read_bytes()

    monkeypatch.setattr(publisher_module, "_write_create_only_json", original_writer)
    second = publish_formal_pit_sector_sidecar(
        handoff_path=handoff_path,
        denominator_path=denominator_path,
        publication_root=publication_root,
        decision_at=decision,
        now=decision,
    )

    assert second["status"] == "formal_source_publication"
    assert sidecar_path.read_bytes() == sidecar_bytes
    assert Path(str(second["receipt_path"])).is_file()


def test_formal_consumer_rejects_sidecar_bytes_changed_after_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _archive_root, handoff_path, denominator_path, decision, _candidate_root = _ready_handoff(
        tmp_path,
        monkeypatch,
        decision_hour=9,
    )
    result = publish_formal_pit_sector_sidecar(
        handoff_path=handoff_path,
        denominator_path=denominator_path,
        publication_root=tmp_path / "formal-publication",
        decision_at=decision,
        now=decision,
    )
    sidecar_path = Path(str(result["sidecar_path"]))
    receipt_path = Path(str(result["receipt_path"]))
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload["rows"][0]["sector_id"] = "tampered"
    sidecar_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(FormalPITSectorPublisherError, match="sidecar file hash mismatch"):
        consume_formal_pit_sector_sidecar(
            sidecar_path,
            receipt_path=receipt_path,
            decision_at=decision,
            now=decision,
        )
