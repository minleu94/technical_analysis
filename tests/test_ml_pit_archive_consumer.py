from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from data_module import formal_daily_input_producer as formal
from data_module import pit_sector_membership_machine as machine
from data_module.pit_sector_membership_machine import MachinePITSourceError
from ml_module.pit_archive_consumer import (
    PITArchiveConsumerError,
    consume_pit_candidate_archive,
)
from scripts.scheduled.prepare_ml_allocation_forward_config import (
    ForwardConfigProducerError,
    _selection_projection,
)
from tests.test_formal_pit_candidate_archive import _produce_with_archive


def _archive_paths(
    result: dict[str, object],
) -> tuple[Path, Path, str]:
    archive = result["durable_archive"]
    assert isinstance(archive, dict)
    manifest = Path(str(archive["archive_manifest_path"]))
    root = Path(str(archive["archive_root"])).parents[1]
    file_hash = str(archive["archive_manifest_file_hash"])
    return root, manifest, file_hash


def test_archive_consumer_reads_current_archive_after_temp_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, result = _produce_with_archive(tmp_path, monkeypatch)
    root, manifest, file_hash = _archive_paths(result)
    shutil.rmtree(paths.output_root)

    decision_at = datetime.now(timezone.utc)
    consumed = consume_pit_candidate_archive(
        archive_root=root,
        manifest_path=manifest,
        expected_manifest_file_hash=file_hash,
        decision_at=decision_at,
    )

    assert consumed["status"] == "machine_verified_archive_candidate"
    assert consumed["current_code_hash_match"] is True
    assert consumed["source_custody_verified"] is True
    assert consumed["candidate_only"] is True
    assert consumed["formal_oos_allowed"] is False
    assert consumed["promotion_eligible"] is False
    assert consumed["row_count"] == 4
    assert len(consumed["rows"]) == 4  # type: ignore[arg-type]
    assert Path(str(consumed["publication_path"])).is_file()


def test_archive_consumer_accepts_previous_taipei_day_after_midnight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Immutable previous-day first-seen capture remains consumable after midnight."""

    _paths, result = _produce_with_archive(tmp_path, monkeypatch)
    root, manifest, file_hash = _archive_paths(result)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    captured = datetime.fromisoformat(
        str(payload["captured_at"]).replace("Z", "+00:00")
    )
    taipei = captured.astimezone(timezone(timedelta(hours=8)))
    after_midnight_base = (
        taipei.replace(hour=0, minute=5, second=0, microsecond=0)
        + timedelta(days=1)
    )

    import ml_module.pit_archive_consumer as archive_consumer

    class _ClockedDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            if tz is None:
                return cls.fromtimestamp(
                    after_midnight_base.timestamp()
                ).replace(tzinfo=None)
            return cls.fromtimestamp(  # type: ignore[arg-type]
                after_midnight_base.timestamp(),
                tz,
            )

    monkeypatch.setattr(archive_consumer, "datetime", _ClockedDateTime)
    after_midnight = _ClockedDateTime.fromtimestamp(
        after_midnight_base.timestamp(),
        timezone(timedelta(hours=8)),
    )
    consumed = archive_consumer.consume_pit_candidate_archive(
        archive_root=root,
        manifest_path=manifest,
        expected_manifest_file_hash=file_hash,
        decision_at=after_midnight,
        now=after_midnight,
    )

    assert consumed["status"] == "machine_verified_archive_candidate"
    assert datetime.fromisoformat(str(consumed["captured_at"])).astimezone(
        timezone(timedelta(hours=8))
    ).date() < after_midnight.date()
    assert consumed["consumer_now"] == after_midnight.astimezone(timezone.utc).isoformat()


def test_archive_consumer_accepts_only_audited_legacy_machine_code_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_hash = next(iter(machine._AUDITED_LEGACY_MACHINE_CODE_HASHES))
    with monkeypatch.context() as legacy:
        legacy.setattr(machine, "_producer_code_sha256", lambda: legacy_hash)
        _paths, result = _produce_with_archive(tmp_path, monkeypatch)

    root, manifest, file_hash = _archive_paths(result)
    consumed = consume_pit_candidate_archive(
        archive_root=root,
        manifest_path=manifest,
        expected_manifest_file_hash=file_hash,
        decision_at=datetime.now(timezone.utc),
    )

    assert consumed["producer_code_sha256"] == legacy_hash
    assert consumed["current_code_hash_match"] is False
    assert consumed["code_hash_compatibility"] == "audited_legacy"
    assert consumed["legacy_code_hash_compatibility_verified"] is True


def test_machine_pit_rejects_unknown_legacy_machine_code_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown_hash = "sha256:" + "1" * 64
    with monkeypatch.context() as unknown:
        unknown.setattr(machine, "_producer_code_sha256", lambda: unknown_hash)
        _paths, result = _produce_with_archive(tmp_path, monkeypatch)

    _root, manifest, _file_hash = _archive_paths(result)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert isinstance(manifest_payload, dict)
    publication_entry = next(
        item
        for item in manifest_payload["files"]
        if item["role"] == "publication"
    )
    publication_path = manifest.parent / str(publication_entry["relative_path"])
    with pytest.raises(
        MachinePITSourceError,
        match="neither current nor an audited legacy machine code hash",
    ):
        machine.validate_machine_pit_publication(publication_path)


def test_forward_config_projection_accepts_explicit_legacy_mode_only() -> None:
    common = {
        "archive_manifest_file_hash": "sha256:" + "a" * 64,
        "status": "machine_verified_archive_candidate",
    }
    legacy_projection = _selection_projection(
        Path("archive_manifest.json"),
        {
            **common,
            "current_code_hash_match": False,
            "code_hash_compatibility": "audited_legacy",
            "legacy_code_hash_compatibility_verified": True,
        },
    )
    assert legacy_projection["code_hash_compatibility"] == "audited_legacy"
    assert legacy_projection["current_code_hash_match"] is False

    with pytest.raises(
        ForwardConfigProducerError,
        match="code hash compatibility is invalid",
    ):
        _selection_projection(
            Path("archive_manifest.json"),
            {
                **common,
                "current_code_hash_match": False,
                "code_hash_compatibility": None,
                "legacy_code_hash_compatibility_verified": False,
            },
        )


def test_archive_consumer_rejects_rows_replaced_after_formal_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _paths, result = _produce_with_archive(tmp_path, monkeypatch)
    root, manifest, file_hash = _archive_paths(result)
    original = formal._readback_pit_candidate_archive

    def readback_then_replace(
        manifest_path: Path,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        readback = original(manifest_path, now=now)
        publication_path = Path(str(readback["publication_path"]))
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
        assert isinstance(publication, dict)
        rows = publication.get("rows")
        assert isinstance(rows, list)
        assert rows and isinstance(rows[0], dict)
        rows[0]["sector_id"] = "tampered-after-formal-readback"
        # Keep the old content_sha256 declaration deliberately.  The second
        # read must bind the returned rows to Formal's original file hash and
        # reject this replacement before rows reach the assembler.
        publication_path.write_text(
            json.dumps(
                publication,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return readback

    monkeypatch.setattr(
        formal,
        "_readback_pit_candidate_archive",
        readback_then_replace,
    )
    with pytest.raises(
        PITArchiveConsumerError,
        match="archived publication file hash changed during read",
    ):
        consume_pit_candidate_archive(
            archive_root=root,
            manifest_path=manifest,
            expected_manifest_file_hash=file_hash,
            decision_at=datetime.now(timezone.utc),
        )


def test_archive_consumer_requires_exact_frozen_manifest_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _paths, result = _produce_with_archive(tmp_path, monkeypatch)
    root, manifest, file_hash = _archive_paths(result)

    with pytest.raises(PITArchiveConsumerError, match="manifest file hash mismatch"):
        consume_pit_candidate_archive(
            archive_root=root,
            manifest_path=manifest,
            expected_manifest_file_hash="sha256:" + "0" * 64,
            decision_at=datetime.now(timezone.utc),
        )


def test_archive_consumer_rejects_future_consumer_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _paths, result = _produce_with_archive(tmp_path, monkeypatch)
    root, manifest, file_hash = _archive_paths(result)
    future = datetime.now(timezone.utc) + timedelta(days=1)

    with pytest.raises(PITArchiveConsumerError, match="future-dated"):
        consume_pit_candidate_archive(
            archive_root=root,
            manifest_path=manifest,
            expected_manifest_file_hash=file_hash,
            decision_at=future,
            now=future,
        )


def test_archive_consumer_rejects_archive_persisted_after_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _paths, result = _produce_with_archive(tmp_path, monkeypatch)
    root, manifest, _file_hash = _archive_paths(result)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    captured = datetime.fromisoformat(
        str(payload["captured_at"]).replace("Z", "+00:00")
    )
    decision = captured + timedelta(milliseconds=500)
    payload["archived_at"] = (captured + timedelta(seconds=1)).isoformat()
    body = dict(payload)
    body.pop("manifest_hash", None)
    payload["manifest_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    manifest.write_bytes(
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
    frozen_hash = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    observed_now = datetime.now(timezone.utc)

    with pytest.raises(
        PITArchiveConsumerError,
        match="archive was not persisted before consumer decision",
    ):
        consume_pit_candidate_archive(
            archive_root=root,
            manifest_path=manifest,
            expected_manifest_file_hash=frozen_hash,
            decision_at=decision,
            now=observed_now,
        )


def test_archive_consumer_rejects_manifest_outside_controlled_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _paths, result = _produce_with_archive(tmp_path, monkeypatch)
    root, manifest, file_hash = _archive_paths(result)
    other_root = tmp_path / "other" / "pit_candidate_archive"
    other_root.mkdir(parents=True)

    with pytest.raises(
        PITArchiveConsumerError,
        match="escapes controlled archive root",
    ):
        consume_pit_candidate_archive(
            archive_root=other_root,
            manifest_path=manifest,
            expected_manifest_file_hash=file_hash,
            decision_at=datetime.now(timezone.utc),
        )
