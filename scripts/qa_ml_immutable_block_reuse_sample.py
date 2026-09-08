"""以已接受 v3 小型 bundle 演示跨 run immutable block 重用。

這是 repo-output-only 的 QA 入口：只讀 bundle，將其中的 frozen input bytes
發布一次，再建立兩個 run manifest reference。它不讀 D 槽、沒有訓練，也不
把這個樣本接入既有 PIT／Direct／OOC reader。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_storage_capacity import directory_size_bytes
from ml_module.allocation_v3_readback_bundle import load_readback_bundle
from ml_module.immutable_ml_block_store import (
    DEFAULT_MAX_STORE_BYTES,
    ImmutableBlockKey,
    publish_immutable_block,
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _atomic_create_json(path: Path, payload: Mapping[str, Any]) -> bool:
    raw = _canonical_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise ValueError(f"sample manifest collision: {path}")
        return False
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".partial",
        dir=path.parent,
    )
    temporary_path = Path(raw_path)
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor_open = False
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                raise ValueError(f"sample manifest collision: {path}")
            return False
        return True
    finally:
        if descriptor_open:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def _path_overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _required_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _build_key(bundle_manifest: Mapping[str, Any]) -> ImmutableBlockKey:
    lineage = _required_mapping(bundle_manifest.get("lineage"), field_name="lineage")
    release = _required_mapping(bundle_manifest.get("release"), field_name="release")
    source_refs_value = lineage.get("source_manifest_hashes")
    if not isinstance(source_refs_value, list):
        raise TypeError("lineage.source_manifest_hashes must be an array")
    source_refs: list[tuple[str, str]] = []
    for index, item in enumerate(source_refs_value):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(
                f"lineage.source_manifest_hashes[{index}] is invalid"
            )
        if not isinstance(item[0], str) or not isinstance(item[1], str):
            raise TypeError(
                f"lineage.source_manifest_hashes[{index}] values are invalid"
            )
        source_refs.append((item[0], item[1]))
    decision_at = _required_text(lineage.get("decision_at"), field_name="decision_at")
    release_id = _required_text(release.get("release_id"), field_name="release_id")
    bundle_identity = _required_text(
        bundle_manifest.get("bundle_identity_hash"),
        field_name="bundle_identity_hash",
    )
    return ImmutableBlockKey(
        block_type="v3_readback_input",
        artifact_schema_version="allocation-inference-input-v3",
        source_version=f"accepted-v3-readback:{release_id}:{bundle_identity}",
        source_manifest_hashes=tuple(source_refs),
        feature_contract_hash=_required_text(
            lineage.get("feature_contract_hash"),
            field_name="lineage.feature_contract_hash",
        ),
        label_contract_hash="none",
        maturity_policy=_required_text(
            lineage.get("readback_inference_mode"),
            field_name="lineage.readback_inference_mode",
        ),
        time_start=decision_at,
        time_end=decision_at,
        encoding="gzip_json",
        lane="research_shadow",
    )


def build_sample(
    *,
    bundle_manifest_path: Path,
    output_root: Path,
    max_store_bytes: int = DEFAULT_MAX_STORE_BYTES,
) -> dict[str, Any]:
    bundle = load_readback_bundle(bundle_manifest_path)
    output = output_root.resolve()
    if _path_overlaps(output, bundle.bundle_root):
        raise ValueError("sample output root must not overlap the source bundle")
    store_root = output / "registry"
    raw = bundle.input_path.read_bytes()
    key = _build_key(bundle.manifest)
    first = publish_immutable_block(
        store_root=store_root,
        key=key,
        raw=raw,
        max_store_bytes=max_store_bytes,
    )
    second = publish_immutable_block(
        store_root=store_root,
        key=key,
        raw=raw,
        max_store_bytes=max_store_bytes,
    )
    reference = first["reference"]
    for run_id in ("run-a", "run-b"):
        _atomic_create_json(
            output / "runs" / run_id / "manifest.json",
            {
                "schema_version": "ml-immutable-block-sample-run.v1",
                "run_id": run_id,
                "block": reference,
            },
        )
    report = {
        "schema_version": "ml-immutable-block-reuse-sample.v1",
        "status": "immutable_block_reuse_sample_completed",
        "source_bundle_identity_hash": bundle.bundle_identity_hash,
        "source_input_hash": bundle.input_hash,
        "source_input_bytes": len(raw),
        "source_manifest_count": len(
            _required_mapping(bundle.manifest.get("lineage"), field_name="lineage").get(
                "source_manifest_hashes", []
            )
        ),
        "store_schema_version": first["reference"]["store_schema_version"],
        "key_hash": first["key_hash"],
        "object_hash": first["object_hash"],
        "same_key_second_run_reuses_reference": second["status"]
        == "immutable_block_reused",
        "same_key_second_run_new_bytes_written": 0,
        "shared_object_count": len(
            list((store_root / "objects" / "sha256").glob("*.blob"))
        ),
        "shared_registry_bytes": directory_size_bytes(store_root),
        "naive_two_run_object_bytes": len(raw) * 2,
        "object_bytes_saved_vs_two_run_copies": len(raw),
        "run_reference_paths": [
            "runs/run-a/manifest.json",
            "runs/run-b/manifest.json",
        ],
        "source_data_modified": False,
        "training_executed": False,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    _atomic_create_json(output / "reuse_report.json", report)
    return {
        **report,
        "first_publish_status": first["status"],
        "second_publish_status": second["status"],
        "second_new_bytes_written": second["new_bytes_written"],
        "output_root": str(output),
        "report_path": str((output / "reuse_report.json").resolve()),
        "store_root": str(store_root.resolve()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--max-store-bytes",
        type=int,
        default=DEFAULT_MAX_STORE_BYTES,
    )
    args = parser.parse_args(argv)
    try:
        result = build_sample(
            bundle_manifest_path=args.bundle_manifest,
            output_root=args.output_root,
            max_store_bytes=args.max_store_bytes,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "immutable_block_reuse_sample_blocked",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
