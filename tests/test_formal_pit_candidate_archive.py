from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

import pytest

from data_module.formal_daily_input_producer import (
    DailyFormalInputPaths,
    FormalDailyInputProducerError,
    OfficialSourceResponse,
    _archive_pit_candidate,
    _produce_pit_candidate,
    _readback_pit_candidate_archive,
)
from data_module.prospective_official_pit_source import (
    OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
)
from tests.test_formal_daily_input_producer import _pit_raw_payloads


def _responses(captured_at: datetime) -> dict[str, OfficialSourceResponse]:
    raw = _pit_raw_payloads()
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
) -> tuple[DailyFormalInputPaths, dict[str, object]]:
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY", "archive-test-key")
    monkeypatch.setenv("RULE_CHAMPION_CONTROLLED_STORE_ID", "archive-test-publisher")
    captured_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    responses = _responses(captured_at)
    paths = DailyFormalInputPaths(
        output_root=tmp_path / "pit-output",
        development_output_root=tmp_path / "technical_analysis_development_output",
        market_db=tmp_path / "unused-market.sqlite",
        publication_root=tmp_path / "publication",
    )
    paths.output_root.mkdir()
    result = _produce_pit_candidate(
        paths=paths,
        output_root=paths.output_root,
        observed=captured_at + timedelta(seconds=1),
        expected_symbols=None,
        fetch_source=lambda url: responses[url],
    )
    return paths, result


def test_pit_candidate_archive_survives_temp_cleanup_and_reads_back_official_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, result = _produce_with_archive(tmp_path, monkeypatch)

    archive = result["durable_archive"]
    assert isinstance(archive, dict)
    assert archive["archive_readback_verified"] is True
    manifest_path = Path(str(archive["archive_manifest_path"]))
    assert manifest_path.is_file()

    shutil.rmtree(paths.output_root)
    readback = _readback_pit_candidate_archive(manifest_path)

    assert readback["status"] == "durable_candidate_readback_verified"
    assert readback["consumer_verified"] is True
    assert readback["candidate_only"] is True
    assert readback["formal_consumer_compatible"] is False
    assert readback["row_count"] == 4
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["archive_independent_of_temp"] is True
    assert len(manifest["files"]) == 5


def test_pit_candidate_archive_rejects_tampered_official_raw_even_without_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, result = _produce_with_archive(tmp_path, monkeypatch)
    archive = result["durable_archive"]
    assert isinstance(archive, dict)
    manifest_path = Path(str(archive["archive_manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_entry = next(
        item for item in manifest["files"] if item["role"] == "raw:twse"
    )
    raw_path = manifest_path.parent / raw_entry["relative_path"]
    raw_path.write_bytes(raw_path.read_bytes() + b" ")
    shutil.rmtree(paths.output_root)

    with pytest.raises(
        FormalDailyInputProducerError,
        match="PIT archive file hash mismatch:raw:twse",
    ):
        _readback_pit_candidate_archive(manifest_path)


def test_pit_candidate_archive_retry_is_create_only_and_byte_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _paths, result = _produce_with_archive(tmp_path, monkeypatch)
    first_archive = result["durable_archive"]
    assert isinstance(first_archive, dict)

    second_archive = _archive_pit_candidate(
        publication_root=tmp_path / "publication",
        pit_result=result,
    )

    assert second_archive["archive_manifest_path"] == first_archive[
        "archive_manifest_path"
    ]
    assert second_archive["archive_manifest_file_hash"] == first_archive[
        "archive_manifest_file_hash"
    ]
    assert second_archive["archive_readback_verified"] is True
