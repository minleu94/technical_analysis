from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil

import pytest

from data_module.ml_storage_capacity import StorageCapacityError, directory_size_bytes
from ml_module import immutable_ml_block_store as block_store_module
from ml_module.immutable_ml_block_store import (
    ImmutableBlockKey,
    immutable_block_store_lock_path,
    load_immutable_block,
    publish_immutable_block,
    publish_immutable_block_file,
)


def _digest(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _key(
    *,
    source_version: str = "pit-publication-v1",
    artifact_schema_version: str = "ml-pit-year-shard-dataset.v1",
    feature_contract: str = "feature-contract-v1",
) -> ImmutableBlockKey:
    return ImmutableBlockKey(
        block_type="pit_shard",
        artifact_schema_version=artifact_schema_version,
        source_version=source_version,
        source_manifest_hashes=(
            ("pit.publication", _digest("pit-publication")),
            ("pit.eligibility", _digest("pit-eligibility")),
        ),
        feature_contract_hash=_digest(feature_contract),
        label_contract_hash="none",
        maturity_policy="raw_observed_only.v1",
        time_start="2026-01-01",
        time_end="2026-01-31",
        encoding="gzip_jsonl",
        lane="research_shadow",
    )


def test_two_run_references_share_content_and_move_with_registry(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "shared-blocks"
    raw = b"accepted-small-artifact\n" * 128
    key = _key()

    first = publish_immutable_block(
        store_root=store_root,
        key=key,
        raw=raw,
    )
    second = publish_immutable_block(
        store_root=store_root,
        key=key,
        raw=raw,
    )

    assert first["status"] == "immutable_block_created"
    assert second["status"] == "immutable_block_reused"
    assert second["new_bytes_written"] == 0
    assert first["object_hash"] == second["object_hash"]
    assert first["reference"] == second["reference"]
    assert len(list((store_root / "objects" / "sha256").glob("*.blob"))) == 1

    reference = first["reference"]
    run_a = tmp_path / "run-a"
    run_b = tmp_path / "run-b"
    run_a.mkdir()
    run_b.mkdir()
    (run_a / "manifest.json").write_text(
        json.dumps({"run_id": "a", "block": reference}, sort_keys=True),
        encoding="utf-8",
    )
    (run_b / "manifest.json").write_text(
        json.dumps({"run_id": "b", "block": reference}, sort_keys=True),
        encoding="utf-8",
    )

    moved_root = tmp_path / "moved-registry"
    shutil.copytree(store_root, moved_root)
    loaded = load_immutable_block(
        store_root=moved_root,
        reference=reference,
    )
    assert loaded.read_bytes() == raw
    assert str(store_root) not in json.dumps(reference, ensure_ascii=False)

    # 兩個 run 若各自保存 bytes 會重複這段內容；共享 object 只發布一次。
    assert first["object_bytes"] * 2 - first["object_bytes"] == len(raw)


def test_semantic_key_change_reuses_bytes_but_not_old_reference(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "shared-blocks"
    raw = b"same-bytes-different-source-version"
    original = publish_immutable_block(
        store_root=store_root,
        key=_key(),
        raw=raw,
    )
    changed_key = replace(_key(), source_version="pit-publication-v2")
    changed = publish_immutable_block(
        store_root=store_root,
        key=changed_key,
        raw=raw,
    )

    assert changed["key_hash"] != original["key_hash"]
    assert changed["object_hash"] == original["object_hash"]
    assert changed["object_created"] is False
    assert changed["reference_created"] is True
    assert len(list((store_root / "objects" / "sha256").glob("*.blob"))) == 1
    assert len(list((store_root / "keys").glob("*.json"))) == 2
    load_immutable_block(store_root=store_root, reference=changed["reference"])

    invalid_reference = json.loads(
        json.dumps(original["reference"], ensure_ascii=False)
    )
    invalid_reference["key"]["source_version"] = "pit-publication-v2"
    with pytest.raises(ValueError, match="key hash"):
        load_immutable_block(
            store_root=store_root,
            reference=invalid_reference,
        )


def test_contract_maturity_schema_and_time_changes_invalidate_key(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "shared-blocks"
    raw = b"same-bytes-with-different-contract"
    base = _key()
    base_result = publish_immutable_block(
        store_root=store_root,
        key=base,
        raw=raw,
    )
    variants = (
        replace(base, artifact_schema_version="ml-pit-year-shard-dataset.v2"),
        replace(base, feature_contract_hash=_digest("feature-contract-v2")),
        replace(base, label_contract_hash=_digest("label-contract-v1")),
        replace(base, maturity_policy="matured_labels.v1"),
        replace(base, time_start="2026-01-02"),
        replace(base, time_end="2026-02-01"),
    )
    results = [
        publish_immutable_block(
            store_root=store_root,
            key=variant,
            raw=raw,
        )
        for variant in variants
    ]
    assert len({result["key_hash"] for result in results}) == len(variants)
    assert all(result["key_hash"] != base_result["key_hash"] for result in results)
    assert all(result["object_hash"] == base_result["object_hash"] for result in results)
    assert all(result["object_created"] is False for result in results)
    assert len(list((store_root / "objects" / "sha256").glob("*.blob"))) == 1


def test_schema_and_object_byte_tampering_fail_closed(tmp_path: Path) -> None:
    store_root = tmp_path / "shared-blocks"
    result = publish_immutable_block(
        store_root=store_root,
        key=_key(),
        raw=b"immutable-payload",
    )
    reference = result["reference"]

    bad_schema = json.loads(json.dumps(reference, ensure_ascii=False))
    bad_schema["key"]["schema_version"] = "ml-immutable-block-key.v0"
    with pytest.raises(ValueError, match="key schema_version"):
        load_immutable_block(store_root=store_root, reference=bad_schema)

    object_path = store_root / reference["object"]["path"]
    object_path.write_bytes(b"modified-bytes")
    with pytest.raises(ValueError, match="bytes/hash mismatch"):
        load_immutable_block(store_root=store_root, reference=reference)


def test_interrupted_publish_retries_without_final_partial_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_root = tmp_path / "shared-blocks"
    raw = b"interruptible"
    key = _key()

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", interrupt)
    with pytest.raises(KeyboardInterrupt):
        publish_immutable_block(store_root=store_root, key=key, raw=raw)
    assert not list((store_root / "objects" / "sha256").glob("*.blob"))
    assert not list((store_root / "objects" / "sha256").glob("*.partial"))

    monkeypatch.undo()
    retried = publish_immutable_block(
        store_root=store_root,
        key=key,
        raw=raw,
    )
    assert retried["status"] == "immutable_block_created"
    load_immutable_block(store_root=store_root, reference=retried["reference"])


def test_concurrent_same_content_is_create_only_and_partial_counts_in_capacity(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "shared-blocks"
    raw = b"concurrent-payload" * 32
    key = _key()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: publish_immutable_block(
                    store_root=store_root,
                    key=key,
                    raw=raw,
                ),
                (0, 1),
            )
        )
    assert sorted(result["status"] for result in results) == [
        "immutable_block_created",
        "immutable_block_reused",
    ]
    assert len(list((store_root / "objects" / "sha256").glob("*.blob"))) == 1

    partial_path = store_root / "objects" / "sha256" / "orphan.partial"
    partial_path.write_bytes(b"orphan-partial")
    observed = directory_size_bytes(store_root)
    assert observed >= len(b"orphan-partial")
    with pytest.raises(ValueError, match="persistent budget"):
        publish_immutable_block(
            store_root=store_root,
            key=_key(source_version="pit-publication-v3"),
            raw=b"another-payload",
            max_store_bytes=observed,
        )


def _publish_from_process(
    store_root: str,
    source_version: str,
    raw: bytes,
    max_store_bytes: int,
    start_event: object,
    ready_queue: object,
    result_queue: object,
) -> None:
    """跨 process worker，驗證 registry lock 不是 thread-only protection。"""

    try:
        ready_queue.put("ready")  # type: ignore[attr-defined]
        start_event.wait(10)  # type: ignore[attr-defined]
        result = publish_immutable_block(
            store_root=Path(store_root),
            key=_key(source_version=source_version),
            raw=raw,
            max_store_bytes=max_store_bytes,
        )
        result_queue.put(("ok", result["status"]))  # type: ignore[attr-defined]
    except Exception as exc:
        result_queue.put(  # type: ignore[attr-defined]
            ("error", type(exc).__name__, str(exc))
        )


def test_different_objects_reserve_capacity_under_shared_os_lock(
    tmp_path: Path,
) -> None:
    """兩個不同 object 競爭時，一方必須在寫入前被容量政策拒絕。"""

    probe = publish_immutable_block(
        store_root=tmp_path / "probe",
        key=_key(source_version="capacity-race-a"),
        raw=b"A" * 192,
    )
    probe_b = publish_immutable_block(
        store_root=tmp_path / "probe-b",
        key=_key(source_version="capacity-race-b"),
        raw=b"B" * 192,
    )
    max_store_bytes = max(int(probe["store_bytes"]), int(probe_b["store_bytes"]))
    assert int(probe["store_bytes"]) <= max_store_bytes
    assert int(probe_b["store_bytes"]) <= max_store_bytes
    store_root = tmp_path / "shared-blocks"
    assert immutable_block_store_lock_path(store_root) == (
        tmp_path / ".ml_immutable_block_store.lock"
    )
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    processes = [
        context.Process(
                target=_publish_from_process,
                args=(
                    str(store_root),
                    "capacity-race-a",
                    b"A" * 192,
                    max_store_bytes,
                    start_event,
                    ready_queue,
                    result_queue,
                ),
        ),
        context.Process(
                target=_publish_from_process,
                args=(
                    str(store_root),
                    "capacity-race-b",
                    b"B" * 192,
                    max_store_bytes,
                    start_event,
                    ready_queue,
                    result_queue,
                ),
        ),
    ]
    for process in processes:
        process.start()
    assert [ready_queue.get(timeout=10) for _process in processes] == [
        "ready",
        "ready",
    ]
    start_event.set()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    results = [result_queue.get(timeout=2) for _process in processes]

    assert sum(result[0] == "ok" for result in results) == 1
    assert sum(result[0] == "error" for result in results) == 1
    error = next(result for result in results if result[0] == "error")
    assert error[1] in {"ImmutableBlockCapacityError", "StorageCapacityError"}
    assert "persistent budget" in error[2]
    assert directory_size_bytes(store_root) <= max_store_bytes
    assert len(list((store_root / "objects" / "sha256").glob("*.blob"))) == 1
    assert len(list((store_root / "keys").glob("*.json"))) == 1


def test_noncanonical_lock_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical lock"):
        publish_immutable_block(
            store_root=tmp_path / "shared-blocks",
            key=_key(source_version="noncanonical-lock"),
            raw=b"small-object",
            lock_path=tmp_path / "different.lock",
        )
    assert not (tmp_path / "different.lock").exists()


def test_temporary_peak_is_measured_before_publish_and_reported(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "shared-blocks"
    temporary_root = tmp_path / "temporary"
    temporary_root.mkdir()
    partial_path = temporary_root / "job.partial"
    partial_path.write_bytes(b"temporary-peak")

    with pytest.raises(StorageCapacityError) as error:
        publish_immutable_block(
            store_root=store_root,
            key=_key(source_version="temporary-capacity"),
            raw=b"small-object",
            temporary_roots=(temporary_root,),
            temporary_budget_bytes=partial_path.stat().st_size - 1,
        )
    assert error.value.preflight["blocker"] == "temporary_peak_bytes_budget_exceeded"
    assert not (store_root / "objects").exists()

    result = publish_immutable_block(
        store_root=store_root,
        key=_key(source_version="temporary-capacity"),
        raw=b"small-object",
        temporary_roots=(temporary_root,),
        temporary_budget_bytes=partial_path.stat().st_size,
    )
    assert result["temporary_peak_bytes_observed"] == partial_path.stat().st_size
    assert result["temporary_budget_bytes"] == partial_path.stat().st_size


def test_file_publication_streams_source_without_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_root = tmp_path / "shared-blocks"
    source = tmp_path / "source-shard.gz"
    source.write_bytes(b"streamed-source\n" * 4096)
    original_read_bytes = Path.read_bytes

    def reject_source_read_bytes(path: Path) -> bytes:
        if path.resolve() == source.resolve():
            raise AssertionError("file publication must stream the source path")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_source_read_bytes)
    key = _key(source_version="streamed-file")
    first = publish_immutable_block_file(
        store_root=store_root,
        key=key,
        source_path=source,
    )
    second = publish_immutable_block_file(
        store_root=store_root,
        key=key,
        source_path=source,
    )
    assert first["status"] == "immutable_block_created"
    assert second["status"] == "immutable_block_reused"
    loaded = load_immutable_block(
        store_root=store_root,
        reference=first["reference"],
    )
    assert loaded.object_bytes == source.stat().st_size


def test_file_publication_rejects_source_growth_before_partial_overrun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_root = tmp_path / "shared-blocks"
    source = tmp_path / "source-shard.gz"
    source.write_bytes(b"bounded-source")
    original_reference = block_store_module._object_reference_from_file

    def grow_after_hash(path: Path) -> dict[str, object]:
        reference = original_reference(path)
        with path.open("ab") as handle:
            handle.write(b"-grew-after-hash")
        return reference

    monkeypatch.setattr(
        block_store_module,
        "_object_reference_from_file",
        grow_after_hash,
    )
    with pytest.raises(ValueError, match="source changed while publishing"):
        publish_immutable_block_file(
            store_root=store_root,
            key=_key(source_version="source-grew"),
            source_path=source,
        )
    assert not tuple(store_root.rglob("*.blob"))
    assert not tuple(store_root.rglob("*.partial"))
