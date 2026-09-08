from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from data_module.pit_sector_machine_publisher import (
    MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION,
    MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV,
    MACHINE_PIT_PUBLISHER_ID_ENV,
    MachinePITSourceError,
    consume_machine_pit_operational_candidate,
    publish_machine_pit_operational_candidate,
    validate_machine_pit_operational_candidate,
)
from data_module import portfolio_ml_dataset_assembler as dataset_assembler
from data_module.pit_sector_membership_machine import (
    build_machine_pit_publication,
    write_machine_pit_receipt,
)


CAPTURED_AT = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
DECISION_AT = datetime(2026, 9, 7, 13, 0, tzinfo=timezone.utc)


def _raw_payloads(publication_date: str = "20260907") -> dict[str, bytes]:
    iso_date = (
        f"{publication_date[:4]}-{publication_date[4:6]}-"
        f"{publication_date[6:]}"
    )
    return {
        "twse": json.dumps(
            [
                {"公司代號": "1101", "產業別": "01", "出表日期": publication_date},
                {"公司代號": "1102", "產業別": "02", "出表日期": publication_date},
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        "tpex": json.dumps(
            [
                {
                    "SecuritiesCompanyCode": "5501",
                    "SecuritiesIndustryCode": "03",
                    "Date": iso_date,
                },
                {
                    "SecuritiesCompanyCode": "5502",
                    "SecuritiesIndustryCode": "05",
                    "Date": iso_date,
                },
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    }


def _receipt(
    tmp_path: Path,
    *,
    raw_date: str = "20260907",
    captured_at: datetime = CAPTURED_AT,
    build_now: datetime = datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc),
    receipt_now: datetime = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
) -> Path:
    publication_dir = tmp_path / "machine"
    publication_dir.mkdir()
    publication = build_machine_pit_publication(
        raw_payloads=_raw_payloads(raw_date),
        output_dir=publication_dir,
        captured_at=captured_at,
        now=build_now,
    )
    receipt_path = tmp_path / "receipt.json"
    write_machine_pit_receipt(
        publication.publication_path,
        receipt_path=receipt_path,
        now=receipt_now,
    )
    return receipt_path


def test_controlled_machine_publisher_and_timestamp_gated_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, "test-controlled-key")
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_ID_ENV, "machine-pit-test-store")
    receipt_path = _receipt(tmp_path)
    operational_path = tmp_path / "operational.json"

    published = publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=operational_path,
        decision_at=DECISION_AT,
        now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    )
    validated = validate_machine_pit_operational_candidate(
        operational_path,
        decision_at=DECISION_AT,
        now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    )
    consumed = consume_machine_pit_operational_candidate(
        operational_path,
        decision_at=DECISION_AT,
        now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    )

    assert published["publisher_version"] == MACHINE_PIT_OPERATIONAL_PUBLISHER_VERSION
    assert str(published["attestation_signature"]).startswith("hmac-sha256:")
    assert validated["publisher_id"] == "machine-pit-test-store"
    assert consumed["status"] == "machine_verified"
    assert consumed["consumer_decision_at"] == "2026-09-07T13:00:00+00:00"
    assert consumed["row_count"] == 4
    assert len(consumed["rows"]) == 4
    assert consumed["source_custody_verified"] is True
    assert consumed["rows_rebuilt_from_raw"] is True
    assert consumed["formal_consumer_compatible"] is False
    assert consumed["candidate_only"] is True


def test_operational_publication_uses_taipei_date_across_utc_midnight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UTC 23:30 的完成時間應屬台北次日，不能用 UTC 日期回填。"""

    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, "test-controlled-key")
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_ID_ENV, "machine-pit-test-store")
    captured_at = datetime(2026, 8, 1, 23, 30, tzinfo=timezone.utc)
    receipt_path = _receipt(
        tmp_path,
        raw_date="20260801",
        captured_at=captured_at,
        build_now=datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc),
        receipt_now=datetime(2026, 8, 2, 0, 10, tzinfo=timezone.utc),
    )
    decision_at = datetime(2026, 8, 2, 0, 30, tzinfo=timezone.utc)
    operational_path = tmp_path / "operational.json"
    publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=operational_path,
        decision_at=decision_at,
        now=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
    )

    validated = validate_machine_pit_operational_candidate(
        operational_path,
        decision_at=decision_at,
        now=datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc),
    )

    assert validated["available_at"] == "2026-08-01T23:30:00+00:00"
    assert validated["available_date"] == "2026-08-02"
    assert validated["effective_from"] == "2026-08-02"


def test_operational_consumer_rejects_tampered_signature_and_future_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, "test-controlled-key")
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_ID_ENV, "machine-pit-test-store")
    receipt_path = _receipt(tmp_path)
    operational_path = tmp_path / "operational.json"
    publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=operational_path,
        decision_at=DECISION_AT,
        now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    )
    payload = json.loads(operational_path.read_text(encoding="utf-8"))
    payload["publisher_id"] = "tampered"
    payload["content_sha256"] = "sha256:" + "0" * 64
    operational_path.write_bytes(
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    with pytest.raises(MachinePITSourceError, match="identity does not match runtime"):
        validate_machine_pit_operational_candidate(
            operational_path,
            decision_at=DECISION_AT,
            now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
        )

    operational_path.unlink()
    publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=operational_path,
        decision_at=DECISION_AT,
        now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(MachinePITSourceError, match="before published decision"):
        consume_machine_pit_operational_candidate(
            operational_path,
            decision_at=datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc),
            now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
        )


def test_operational_publisher_requires_controlled_runtime_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, raising=False)
    monkeypatch.delenv(MACHINE_PIT_PUBLISHER_ID_ENV, raising=False)
    receipt_path = _receipt(tmp_path)
    with pytest.raises(MachinePITSourceError, match="RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"):
        publish_machine_pit_operational_candidate(
            receipt_path,
            output_path=tmp_path / "operational.json",
            decision_at=DECISION_AT,
            now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
        )


def test_assembler_spools_verified_machine_candidate_only_in_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_HMAC_KEY_ENV, "test-controlled-key")
    monkeypatch.setenv(MACHINE_PIT_PUBLISHER_ID_ENV, "machine-pit-test-store")
    receipt_path = _receipt(tmp_path)
    operational_path = tmp_path / "operational.json"
    publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=operational_path,
        decision_at=DECISION_AT,
        now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
    )

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        dataset_assembler._initialize_spool(connection)
        manifest_hash, row_count = dataset_assembler._spool_sector_memberships(
            connection,
            None,
            training_as_of=DECISION_AT,
            machine_operational_path=operational_path,
            machine_now=datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc),
        )
        persisted_count = int(
            connection.execute("SELECT COUNT(*) FROM sector_memberships").fetchone()[0]
        )
    finally:
        connection.close()

    assert manifest_hash == dataset_assembler._file_sha256(operational_path)
    assert row_count == 4
    assert persisted_count == 4
