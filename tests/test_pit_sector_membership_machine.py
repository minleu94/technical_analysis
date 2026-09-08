from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from data_module.pit_sector_membership_machine import (
    MachinePITSourceError,
    build_machine_pit_publication,
    validate_machine_pit_publication,
    validate_machine_pit_receipt,
    write_machine_pit_receipt,
)


CAPTURED_AT = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)


def _raw_payloads(*, duplicate_symbol: bool = False) -> dict[str, bytes]:
    twse_rows = [
        {"公司代號": "1101", "產業別": "01", "出表日期": "20260907"},
        {"公司代號": "1102", "產業別": "02", "出表日期": "20260907"},
    ]
    tpex_rows = [
        {
            "SecuritiesCompanyCode": "5501" if not duplicate_symbol else "1101",
            "SecuritiesIndustryCode": "03",
            "Date": "2026-09-07",
        },
        {
            "SecuritiesCompanyCode": "5502",
            "SecuritiesIndustryCode": "05",
            "Date": "2026-09-07",
        },
    ]
    return {
        "twse": _json_bytes(twse_rows),
        "tpex": _json_bytes(tpex_rows),
    }


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    )


def _build(tmp_path: Path):
    output = tmp_path / "publication"
    output.mkdir()
    return build_machine_pit_publication(
        raw_payloads=_raw_payloads(),
        output_dir=output,
        captured_at=CAPTURED_AT,
        now=datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc),
    )


def test_machine_pit_producer_rebuilds_official_raw_and_writes_receipt(
    tmp_path: Path,
) -> None:
    publication = _build(tmp_path)
    validation = validate_machine_pit_publication(
        publication.publication_path,
        now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
    )
    receipt_path = tmp_path / "receipt.json"
    receipt = write_machine_pit_receipt(
        publication.publication_path,
        receipt_path=receipt_path,
        now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
    )
    consumed = validate_machine_pit_receipt(
        receipt_path,
        now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
    )

    assert validation.row_count == 4
    assert receipt["status"] == "machine_verified"
    assert consumed["source_custody_verified"] is True
    assert consumed["rows_rebuilt_from_raw"] is True
    assert consumed["candidate_only"] is True
    assert consumed["formal_consumer_compatible"] is False
    assert consumed["formal_oos_allowed"] is False


def test_machine_pit_consumer_rejects_tampered_raw_custody(tmp_path: Path) -> None:
    publication = _build(tmp_path)
    raw_path = publication.publication_path.parent / "twse_t187ap03.raw.json"
    raw_path.write_bytes(raw_path.read_bytes() + b"\n")

    with pytest.raises(MachinePITSourceError, match="raw custody hash mismatch"):
        validate_machine_pit_publication(
            publication.publication_path,
            now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
        )


def test_machine_pit_consumer_rejects_tampered_publication_body(tmp_path: Path) -> None:
    publication = _build(tmp_path)
    payload = json.loads(publication.publication_path.read_text(encoding="utf-8"))
    payload["rows"][0]["sector_id"] = "99"
    publication.publication_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(MachinePITSourceError, match="content hash mismatch"):
        validate_machine_pit_publication(
            publication.publication_path,
            now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
        )


def test_machine_pit_receipt_accepts_equivalent_utc_offset(tmp_path: Path) -> None:
    # 09:30 UTC is 17:30 Asia/Taipei, after a 10:00 Asia/Taipei capture.  An
    # ISO string comparison would incorrectly treat "10" as later than "09".
    # The consumer must compare aware instants.
    captured = datetime(
        2026, 9, 7, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")
    )
    output = tmp_path / "publication"
    output.mkdir()
    publication = build_machine_pit_publication(
        raw_payloads=_raw_payloads(),
        output_dir=output,
        captured_at=captured,
        now=datetime(2026, 9, 7, 11, 0, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    receipt_path = tmp_path / "receipt.json"
    write_machine_pit_receipt(
        publication.publication_path,
        receipt_path=receipt_path,
        now=datetime(2026, 9, 7, 9, 30, tzinfo=timezone.utc),
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["evaluated_at"] = "2026-09-07T09:30:00+00:00"
    body = dict(receipt)
    body.pop("content_sha256")
    receipt["content_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    consumed = validate_machine_pit_receipt(
        receipt_path,
        now=datetime(2026, 9, 7, 9, 30, tzinfo=timezone.utc),
    )
    assert consumed["status"] == "machine_verified"


def test_machine_pit_rejects_future_capture_and_duplicate_market_symbol(
    tmp_path: Path,
) -> None:
    output = tmp_path / "future"
    output.mkdir()
    with pytest.raises(MachinePITSourceError, match="captured_at cannot be after now"):
        build_machine_pit_publication(
            raw_payloads=_raw_payloads(),
            output_dir=output,
            captured_at=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
            now=datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc),
        )

    duplicate_output = tmp_path / "duplicate"
    duplicate_output.mkdir()
    with pytest.raises(MachinePITSourceError, match="appears in multiple market sources"):
        build_machine_pit_publication(
            raw_payloads=_raw_payloads(duplicate_symbol=True),
            output_dir=duplicate_output,
            captured_at=CAPTURED_AT,
            now=datetime(2026, 9, 7, 11, 0, tzinfo=timezone.utc),
        )
