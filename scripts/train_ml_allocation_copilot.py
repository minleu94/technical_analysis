"""從 frozen 顯式 JSON/JSON.GZ shards 訓練配置型 ML Co-pilot。

此入口不掃描 SQLite、不自動發現欄位，也不接受 wildcard feature pack。
年度 shard 可透過重複 ``--input`` 合併；每個 shard 都必須聲明相同的 frozen
dataset id、training cutoff、horizons 與 feature packs。輸出固定
``production_alpha_bp=0``、``production_action_allowed=false``，promotion
必須由獨立的機器證據 artifact 決定。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.allocation_contracts import (  # noqa: E402
    AllocationTargets,
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
)
from ml_module.allocation_training_service import (  # noqa: E402
    AllocationHorizonLabel,
    AllocationTrainingSample,
    AllocationTrainingService,
    EXPERT_HEAD_IDS,
    EXPERT_VECTOR_WIDTH,
    FeaturePackDefinition,
)
from ml_module.purged_walk_forward import (  # noqa: E402
    MLTimeWindowRow,
    PurgedWalkForwardFold,
)


INPUT_SCHEMA_VERSION = "allocation-training-input-v2"
JSONL_INPUT_SCHEMA_VERSION = "allocation-training-jsonl-v2"
MANIFEST_SCHEMA_VERSION = "allocation-training-output-manifest-v2"
_UNVERIFIED_DATASET_MANIFEST_FILE_HASH = "sha256:" + ("0" * 64)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "dataset_id",
        "training_as_of",
        "horizons",
        "feature_packs",
        "samples",
        "folds",
        "assembly_blockers",
    }
)


@dataclass(frozen=True)
class _FrozenShard:
    path: Path
    content_hash: str
    dataset_id: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    training_as_of: str
    horizons: tuple[int, ...]
    feature_packs: tuple[FeaturePackDefinition, ...]
    samples: tuple[AllocationTrainingSample, ...]
    fold_payloads: tuple[Mapping[str, Any], ...]
    assembly_blockers: tuple[str, ...]
    fold_mode: str = "row_ids"
    direct_training_input: bool = False
    publication_manifest_hash: str | None = None
    publication_shard_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class _MergedInput:
    dataset_id: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    training_as_of: str
    horizons: tuple[int, ...]
    feature_packs: tuple[FeaturePackDefinition, ...]
    samples: tuple[AllocationTrainingSample, ...]
    folds: tuple[PurgedWalkForwardFold, ...]
    assembly_blockers: tuple[str, ...]
    shards: tuple[_FrozenShard, ...]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        type=Path,
        required=True,
        help="frozen JSON 或 JSON.GZ；可重複指定年度 shards",
    )
    parser.add_argument("--artifact-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--hgb-max-iter", type=int, default=60)
    parser.add_argument("--ridge-alpha", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = _parser().parse_args(argv)
    try:
        summary = _run(
            input_paths=tuple(args.input),
            artifact_output=args.artifact_output,
            audit_output=args.audit_output,
            manifest_output=args.manifest_output,
            random_state=args.random_state,
            hgb_max_iter=args.hgb_max_iter,
            ridge_alpha=args.ridge_alpha,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "production_alpha_bp": 0,
                    "production_action_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _run(
    *,
    input_paths: tuple[Path, ...],
    artifact_output: Path,
    audit_output: Path,
    manifest_output: Path,
    random_state: int,
    hgb_max_iter: int,
    ridge_alpha: int,
) -> dict[str, Any]:
    if not input_paths:
        raise ValueError("at least one frozen input shard is required")
    output_paths = (artifact_output, audit_output, manifest_output)
    resolved_outputs = tuple(path.resolve() for path in output_paths)
    if len(resolved_outputs) != len(set(resolved_outputs)):
        raise ValueError("artifact, audit, and manifest outputs must be distinct")

    shards = tuple(_load_frozen_shard(path) for path in input_paths)
    merged = _merge_shards(shards)
    result = AllocationTrainingService(
        random_state=random_state,
        hgb_max_iter=hgb_max_iter,
        ridge_alpha=ridge_alpha,
    ).fit(
        dataset_id=merged.dataset_id,
        samples=merged.samples,
        feature_packs=merged.feature_packs,
        folds=merged.folds,
        training_as_of=merged.training_as_of,
        dataset_manifest_file_hash=merged.dataset_manifest_file_hash,
        horizons=merged.horizons,
    )

    audit_bytes = (result.audit_json + "\n").encode("utf-8")
    blocker_values = {
        *merged.assembly_blockers,
        "production_alpha_locked_pending_automated_promotion_evidence",
    }
    if not all(shard.direct_training_input for shard in shards):
        blocker_values.add(
            "actual_db_dataset_assembly_not_performed_requires_"
            "eligibility_governed_frozen_shards"
        )
        blocker_values.add(
            "dataset_manifest_file_hash_unverified_non_direct_input"
        )
    blockers = tuple(sorted(blocker_values))
    manifest_payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "training_completed",
        "dataset_id": result.dataset_id,
        "dataset_identity_hash": result.dataset_identity_hash,
        "dataset_manifest_file_hash": result.dataset_manifest_file_hash,
        "feature_registry_hash": result.feature_registry_hash,
        "source_manifest_hashes": [
            [source_id, source_hash]
            for source_id, source_hash in result.source_manifest_hashes
        ],
        "training_as_of": result.training_as_of,
        "horizons": list(result.horizons),
        "expert_head_ids": list(EXPERT_HEAD_IDS),
        "expert_vector_width": EXPERT_VECTOR_WIDTH,
        "feature_packs": [
            {
                "pack_id": pack.pack_id,
                "feature_ids": list(pack.feature_ids),
            }
            for pack in merged.feature_packs
        ],
        "outer_fold_ids": list(result.outer_fold_ids),
        "training_row_count": len(merged.samples),
        "base_oof_prediction_count": len(result.base_oof_predictions),
        "meta_oof_prediction_count": len(result.meta_oof_predictions),
        "feature_family_weights_bp": [
            [family_id, weight_bp]
            for family_id, weight_bp in result.feature_family_weights_bp
        ],
        "input_shards": [
            {
                "file_name": shard.path.name,
                "content_hash": shard.content_hash,
                "row_count": len(shard.samples),
                "direct_training_input": shard.direct_training_input,
                "publication_manifest_hash": shard.publication_manifest_hash,
                "dataset_manifest_file_hash": (
                    shard.dataset_manifest_file_hash
                ),
            }
            for shard in shards
        ],
        "artifact_file": artifact_output.name,
        "artifact_hash": result.artifact_hash,
        "audit_file": audit_output.name,
        "audit_file_hash": _sha256(audit_bytes),
        "replay_hash": result.replay_hash,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "formal_oos_allowed": False,
        "blockers": list(blockers),
        "not_performed": [
            "sqlite_schema_discovery",
            "unreviewed_feature_wildcard_training",
            "production_promotion",
            "broker_order_routing",
        ],
    }
    manifest_bytes = (
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_commit_outputs(
        (
            (artifact_output, result.artifact_bytes),
            (audit_output, audit_bytes),
            # manifest 最後 replace，作為同一批輸出的 commit marker。
            (manifest_output, manifest_bytes),
        )
    )
    return {
        "status": "training_completed",
        "dataset_id": result.dataset_id,
        "training_row_count": len(merged.samples),
        "artifact_hash": result.artifact_hash,
        "replay_hash": result.replay_hash,
        "manifest_output": str(manifest_output),
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "blockers": list(blockers),
    }


def _load_frozen_shard(path: Path) -> _FrozenShard:
    if path.name.lower().endswith((".jsonl", ".jsonl.gz")):
        return _load_jsonl_shard(path)
    raw_bytes = path.read_bytes()
    if path.suffix.lower() == ".gz":
        try:
            json_bytes = gzip.decompress(raw_bytes)
        except (OSError, EOFError) as exc:
            raise ValueError(f"invalid gzip input: {path}") from exc
    else:
        json_bytes = raw_bytes
    try:
        payload = json.loads(json_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON input: {path}") from exc
    mapping = _as_mapping(payload, field_name="input")
    unknown = set(mapping) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ValueError(f"unsupported top-level input field: {sorted(unknown)[0]}")
    if mapping.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must equal {INPUT_SCHEMA_VERSION}"
        )
    dataset_id = _text(mapping.get("dataset_id"), field_name="dataset_id")
    training_as_of = _text(
        mapping.get("training_as_of"), field_name="training_as_of"
    )
    horizons = _integer_tuple(mapping.get("horizons"), field_name="horizons")
    feature_packs = tuple(
        FeaturePackDefinition(
            pack_id=_text(item.get("pack_id"), field_name="pack_id"),
            feature_ids=_explicit_feature_ids(
                item.get("feature_ids"), field_name="feature_ids"
            ),
        )
        for item in _mapping_sequence(
            mapping.get("feature_packs"), field_name="feature_packs"
        )
    )
    if not feature_packs:
        raise ValueError("feature_packs must contain explicit registered fields")
    samples = tuple(
        _parse_sample(item)
        for item in _mapping_sequence(
            mapping.get("samples"), field_name="samples"
        )
    )
    if not samples:
        raise ValueError("each frozen shard requires samples")
    dataset_identity_hashes = {
        sample.row.dataset_identity_hash for sample in samples
    }
    if len(dataset_identity_hashes) != 1:
        raise ValueError("legacy training shard must share one dataset identity hash")
    folds_raw = mapping.get("folds", ())
    fold_payloads = tuple(
        _mapping_sequence(folds_raw, field_name="folds")
    )
    blockers = _text_tuple(
        mapping.get("assembly_blockers", ()),
        field_name="assembly_blockers",
        allow_empty=True,
    )
    return _FrozenShard(
        path=path,
        content_hash=_sha256(raw_bytes),
        dataset_id=dataset_id,
        dataset_identity_hash=next(iter(dataset_identity_hashes)),
        dataset_manifest_file_hash=(
            _UNVERIFIED_DATASET_MANIFEST_FILE_HASH
        ),
        training_as_of=training_as_of,
        horizons=horizons,
        feature_packs=feature_packs,
        samples=samples,
        fold_payloads=fold_payloads,
        assembly_blockers=blockers,
        fold_mode="row_ids",
        direct_training_input=False,
    )


def _load_jsonl_shard(path: Path) -> _FrozenShard:
    """逐行讀取 assembler 發佈的 gzip JSONL，不解壓整檔到記憶體。"""

    opener = gzip.open if path.name.lower().endswith(".gz") else open
    header: Mapping[str, Any] | None = None
    samples: list[AllocationTrainingSample] = []
    content_digest = hashlib.sha256()
    with opener(path, "rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                continue
            content_digest.update(raw_line)
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid JSONL input at {path}:{line_number}"
                ) from exc
            mapping = _as_mapping(payload, field_name="jsonl record")
            record_type = mapping.get("record_type")
            if record_type == "header":
                if header is not None or samples:
                    raise ValueError("JSONL header must be the first record")
                header = mapping
                continue
            if record_type != "sample":
                raise ValueError("JSONL record_type must be header or sample")
            if header is None:
                raise ValueError("JSONL sample precedes header")
            _reject_unknown(
                mapping,
                allowed={"record_type", "sample"},
                field_name="jsonl sample record",
            )
            samples.append(
                _parse_sample(
                    _as_mapping(mapping.get("sample"), field_name="sample")
                )
            )
    if header is None:
        raise ValueError("JSONL input requires a header")
    _reject_unknown(
        header,
        allowed={
            "record_type",
            "schema_version",
            "direct_training_input",
            "research_only",
            "formal_consumer_compatible",
            "promotion_eligible",
            "research_shadow_included",
            "formal_source_only",
            "dataset_id",
            "dataset_identity_hash",
            "training_as_of",
            "horizons",
            "feature_packs",
            "folds",
            "assembly_blockers",
            "feature_registry_hash",
            "source_manifest_hashes",
            "price_availability",
            "source_quality",
            "portfolio_state_policy",
            "corporate_action_custody",
            "label_policy",
            "year",
        },
        field_name="jsonl header",
    )
    source_quality = header.get("source_quality")
    if source_quality is not None:
        source_quality_mapping = _as_mapping(
            source_quality, field_name="source_quality"
        )
        research_only = _required_json_bool(
            source_quality_mapping.get("research_only"),
            field_name="source_quality.research_only",
        )
        formal_training_allowed = _required_json_bool(
            source_quality_mapping.get("formal_training_allowed"),
            field_name="source_quality.formal_training_allowed",
        )
        if research_only or not formal_training_allowed:
            raise ValueError(
                "JSONL source quality is research-only and cannot be trained"
            )
    if header.get("schema_version") != JSONL_INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"JSONL schema_version must equal {JSONL_INPUT_SCHEMA_VERSION}"
        )
    if header.get("direct_training_input") is not True:
        raise ValueError("JSONL header must declare direct_training_input=true")
    if not samples:
        raise ValueError("each frozen JSONL shard requires samples")
    feature_packs = tuple(
        FeaturePackDefinition(
            pack_id=_text(item.get("pack_id"), field_name="pack_id"),
            feature_ids=_explicit_feature_ids(
                item.get("feature_ids"), field_name="feature_ids"
            ),
        )
        for item in _mapping_sequence(
            header.get("feature_packs"), field_name="feature_packs"
        )
    )
    if not feature_packs:
        raise ValueError("feature_packs must contain explicit registered fields")
    dataset_identity_hash = _text(
        header.get("dataset_identity_hash"),
        field_name="dataset_identity_hash",
    )
    feature_registry_hash = _text(
        header.get("feature_registry_hash"),
        field_name="feature_registry_hash",
    )
    source_manifest_hashes = _pair_tuple(
        header.get("source_manifest_hashes"),
        field_name="source_manifest_hashes",
        text_values=True,
    )
    shard_year = _integer(header.get("year"), field_name="year")
    for sample in samples:
        if sample.row.dataset_identity_hash != dataset_identity_hash:
            raise ValueError(
                "sample dataset_identity_hash does not match JSONL header"
            )
        if sample.row.feature_registry_hash != feature_registry_hash:
            raise ValueError(
                "sample feature_registry_hash does not match JSONL header"
            )
        if sample.row.source_manifest_hashes != source_manifest_hashes:
            raise ValueError(
                "sample source_manifest_hashes do not match JSONL header"
            )
        if date.fromisoformat(sample.row.decision_at[:10]).year != shard_year:
            raise ValueError("sample decision_at year does not match JSONL header")
    compressed_hash = _file_sha256(path)
    (
        publication_manifest_hash,
        dataset_manifest_file_hash,
        publication_shard_paths,
    ) = (
        _validate_direct_publication_shard(
            path=path,
            header=header,
            samples=tuple(samples),
            compressed_hash=compressed_hash,
            content_hash=f"sha256:{content_digest.hexdigest()}",
        )
    )
    return _FrozenShard(
        path=path,
        content_hash=compressed_hash,
        dataset_id=_text(header.get("dataset_id"), field_name="dataset_id"),
        dataset_identity_hash=dataset_identity_hash,
        dataset_manifest_file_hash=dataset_manifest_file_hash,
        training_as_of=_text(
            header.get("training_as_of"), field_name="training_as_of"
        ),
        horizons=_integer_tuple(
            header.get("horizons"), field_name="horizons"
        ),
        feature_packs=feature_packs,
        samples=tuple(samples),
        fold_payloads=_mapping_sequence(
            header.get("folds"), field_name="folds"
        ),
        assembly_blockers=_text_tuple(
            header.get("assembly_blockers", ()),
            field_name="assembly_blockers",
            allow_empty=True,
        ),
        fold_mode="date_windows",
        direct_training_input=True,
        publication_manifest_hash=publication_manifest_hash,
        publication_shard_paths=publication_shard_paths,
    )


def _validate_direct_publication_shard(
    *,
    path: Path,
    header: Mapping[str, Any],
    samples: tuple[AllocationTrainingSample, ...],
    compressed_hash: str,
    content_hash: str,
) -> tuple[str, str, tuple[str, ...]]:
    """重新計算 assembler publication 與 shard custody，不信任 header 宣稱。"""

    manifest_path = path.resolve().parent / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(
            "direct training shard requires sibling publication manifest"
        )
    try:
        decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid direct publication manifest") from exc
    manifest = _as_mapping(decoded, field_name="publication manifest")
    if manifest.get("schema_version") != "portfolio-ml-training-shards.v2":
        raise ValueError("unsupported direct publication manifest schema")
    expected_manifest_hash = _text(
        manifest.get("manifest_hash"),
        field_name="manifest_hash",
    )
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_hash", None)
    actual_manifest_hash = _sha256(
        _canonical_json(manifest_body).encode("utf-8")
    )
    if actual_manifest_hash != expected_manifest_hash:
        raise ValueError("direct publication manifest hash mismatch")
    if manifest.get("direct_training_input") is not True:
        raise ValueError("publication manifest does not authorize direct input")

    manifest_root = manifest_path.parent.resolve()
    shard_entries = _mapping_sequence(
        manifest.get("shards"),
        field_name="publication shards",
    )
    resolved_entries: list[tuple[Path, Mapping[str, Any]]] = []
    for entry in shard_entries:
        relative = _text(entry.get("path"), field_name="shard.path")
        resolved = (manifest_root / relative).resolve()
        if not resolved.is_relative_to(manifest_root):
            raise ValueError("publication shard path escapes manifest root")
        resolved_entries.append((resolved, entry))
    matches = [
        entry
        for resolved, entry in resolved_entries
        if resolved == path.resolve()
    ]
    if len(matches) != 1:
        raise ValueError("input shard is not uniquely registered in manifest")
    entry = matches[0]
    if entry.get("compressed_sha256") != compressed_hash:
        raise ValueError("direct publication compressed shard hash mismatch")
    if entry.get("content_sha256") != content_hash:
        raise ValueError("direct publication JSONL content hash mismatch")
    if _integer(entry.get("sample_count"), field_name="sample_count") != len(
        samples
    ):
        raise ValueError("direct publication shard row count mismatch")

    decision_dates = tuple(
        sample.row.decision_at[:10] for sample in samples
    )
    if entry.get("min_decision_date") != min(decision_dates):
        raise ValueError("direct publication shard minimum date mismatch")
    if entry.get("max_decision_date") != max(decision_dates):
        raise ValueError("direct publication shard maximum date mismatch")
    if entry.get("year") != header.get("year"):
        raise ValueError("direct publication shard year mismatch")

    header_manifest_pairs = (
        ("dataset_id", "dataset_id"),
        ("dataset_identity_hash", "dataset_identity_hash"),
        ("feature_registry_hash", "feature_registry_hash"),
        ("training_as_of", "training_as_of"),
        ("horizons", "horizons"),
        ("feature_packs", "feature_packs"),
        ("folds", "folds"),
        ("source_manifest_hashes", "source_manifest_hashes"),
        ("corporate_action_custody", "corporate_action_custody"),
    )
    for header_field, manifest_field in header_manifest_pairs:
        if _canonical_json(header.get(header_field)) != _canonical_json(
            manifest.get(manifest_field)
        ):
            raise ValueError(
                f"JSONL header {header_field} does not match publication manifest"
            )
    declared_total = sum(
        _integer(item.get("sample_count"), field_name="sample_count")
        for item in shard_entries
    )
    if _integer(
        manifest.get("sample_count"),
        field_name="manifest.sample_count",
    ) != declared_total:
        raise ValueError("publication manifest aggregate row count mismatch")
    return (
        expected_manifest_hash,
        _file_sha256(manifest_path),
        tuple(str(resolved) for resolved, _ in resolved_entries),
    )


def _merge_shards(shards: tuple[_FrozenShard, ...]) -> _MergedInput:
    if not shards:
        raise ValueError("frozen shards are required")
    first = shards[0]
    expected_packs = _canonical_pack_shape(first.feature_packs)
    fold_payloads: tuple[Mapping[str, Any], ...] | None = None
    fold_mode: str | None = None
    all_samples: list[AllocationTrainingSample] = []
    blockers: set[str] = set()
    for shard in shards:
        if shard.dataset_id != first.dataset_id:
            raise ValueError("all shards must share one dataset_id")
        if shard.dataset_identity_hash != first.dataset_identity_hash:
            raise ValueError("all shards must share one dataset identity hash")
        if (
            shard.dataset_manifest_file_hash
            != first.dataset_manifest_file_hash
        ):
            raise ValueError(
                "all shards must share one dataset manifest file hash"
            )
        if shard.training_as_of != first.training_as_of:
            raise ValueError("all shards must share one training_as_of")
        if shard.horizons != first.horizons:
            raise ValueError("all shards must share identical horizons")
        if _canonical_pack_shape(shard.feature_packs) != expected_packs:
            raise ValueError("all shards must share identical explicit feature packs")
        if fold_mode is None:
            fold_mode = shard.fold_mode
        elif fold_mode != shard.fold_mode:
            raise ValueError("cannot mix row-id and date-window fold definitions")
        if shard.fold_payloads:
            if fold_payloads is None:
                fold_payloads = shard.fold_payloads
            elif _canonical_json(shard.fold_payloads) != _canonical_json(
                fold_payloads
            ):
                raise ValueError("shards contain conflicting fold definitions")
        all_samples.extend(shard.samples)
        blockers.update(shard.assembly_blockers)
    direct_manifest_hashes = {
        shard.publication_manifest_hash
        for shard in shards
        if shard.direct_training_input
    }
    if direct_manifest_hashes and (
        None in direct_manifest_hashes or len(direct_manifest_hashes) != 1
    ):
        raise ValueError(
            "direct training shards must share one verified publication manifest"
        )
    if direct_manifest_hashes:
        supplied_paths = {
            str(shard.path.resolve())
            for shard in shards
            if shard.direct_training_input
        }
        expected_paths = set(first.publication_shard_paths)
        if supplied_paths != expected_paths:
            raise ValueError(
                "all registered direct publication shards must be supplied"
            )
    if fold_payloads is None:
        raise ValueError("at least one shard must provide fold definitions")
    sample_by_id = {sample.row.row_id: sample for sample in all_samples}
    if len(sample_by_id) != len(all_samples):
        raise ValueError("row ids must be unique across frozen shards")
    if fold_mode == "date_windows":
        folds = tuple(
            _parse_window_fold(payload, sample_by_id=sample_by_id)
            for payload in fold_payloads
        )
    else:
        folds = tuple(
            _parse_fold(payload, sample_by_id=sample_by_id)
            for payload in fold_payloads
        )
    return _MergedInput(
        dataset_id=first.dataset_id,
        dataset_identity_hash=first.dataset_identity_hash,
        dataset_manifest_file_hash=first.dataset_manifest_file_hash,
        training_as_of=first.training_as_of,
        horizons=first.horizons,
        feature_packs=tuple(
            sorted(first.feature_packs, key=lambda pack: pack.pack_id)
        ),
        samples=tuple(all_samples),
        folds=folds,
        assembly_blockers=tuple(sorted(blockers)),
        shards=shards,
    )


def _parse_sample(payload: Mapping[str, Any]) -> AllocationTrainingSample:
    _reject_unknown(
        payload,
        allowed={"row", "horizon_labels"},
        field_name="sample",
    )
    row_payload = _as_mapping(payload.get("row"), field_name="row")
    _reject_unknown(
        row_payload,
        allowed={
            "row_id",
            "decision_at",
            "symbol",
            "features",
            "missing_family_ids",
            "portfolio_state",
            "dataset_identity_hash",
            "feature_registry_hash",
            "source_manifest_hashes",
            "targets",
        },
        field_name="row",
    )
    features = tuple(
        PITFeatureValue(**dict(item))
        for item in _mapping_sequence(
            row_payload.get("features"), field_name="features"
        )
    )
    state_payload = _as_mapping(
        row_payload.get("portfolio_state"), field_name="portfolio_state"
    )
    _reject_unknown(
        state_payload,
        allowed={
            "as_of_date",
            "weights",
            "weekly_turnover_used_bp",
            "state_hash",
        },
        field_name="portfolio_state",
    )
    portfolio_state = CausalPortfolioState(
        as_of_date=state_payload["as_of_date"],
        weights=_parse_weights(
            _as_mapping(state_payload.get("weights"), field_name="weights")
        ),
        weekly_turnover_used_bp=state_payload["weekly_turnover_used_bp"],
        state_hash=state_payload["state_hash"],
    )
    targets_payload = _as_mapping(
        row_payload.get("targets"), field_name="targets"
    )
    _reject_unknown(
        targets_payload,
        allowed={
            "decision_date",
            "horizon_end_date",
            "available_at",
            "target_weights",
            "delta_weights_bp",
            "risk_contributions_bp",
            "risky_budget_bp",
            "cash_bp",
            "rebalance_worthwhile",
        },
        field_name="targets",
    )
    targets = AllocationTargets(
        decision_date=targets_payload["decision_date"],
        horizon_end_date=targets_payload["horizon_end_date"],
        available_at=targets_payload["available_at"],
        target_weights=_parse_weights(
            _as_mapping(
                targets_payload.get("target_weights"),
                field_name="target_weights",
            )
        ),
        delta_weights_bp=_pair_tuple(
            targets_payload.get("delta_weights_bp"),
            field_name="delta_weights_bp",
        ),
        risk_contributions_bp=_pair_tuple(
            targets_payload.get("risk_contributions_bp"),
            field_name="risk_contributions_bp",
        ),
        risky_budget_bp=targets_payload["risky_budget_bp"],
        cash_bp=targets_payload["cash_bp"],
        rebalance_worthwhile=targets_payload["rebalance_worthwhile"],
    )
    row = PortfolioMLDatasetRow(
        row_id=row_payload["row_id"],
        decision_at=row_payload["decision_at"],
        symbol=row_payload["symbol"],
        features=features,
        missing_family_ids=_text_tuple(
            row_payload.get("missing_family_ids", ()),
            field_name="missing_family_ids",
            allow_empty=True,
        ),
        portfolio_state=portfolio_state,
        dataset_identity_hash=row_payload["dataset_identity_hash"],
        feature_registry_hash=row_payload["feature_registry_hash"],
        source_manifest_hashes=_pair_tuple(
            row_payload.get("source_manifest_hashes"),
            field_name="source_manifest_hashes",
            text_values=True,
        ),
        targets=targets,
    )
    labels = tuple(
        AllocationHorizonLabel(**dict(item))
        for item in _mapping_sequence(
            payload.get("horizon_labels"), field_name="horizon_labels"
        )
    )
    return AllocationTrainingSample(row=row, horizon_labels=labels)


def _parse_weights(payload: Mapping[str, Any]) -> AllocationWeightContract:
    _reject_unknown(
        payload,
        allowed={"positions_bp", "cash_bp"},
        field_name="weights",
    )
    return AllocationWeightContract(
        positions_bp=_pair_tuple(
            payload.get("positions_bp"), field_name="positions_bp"
        ),
        cash_bp=payload["cash_bp"],
    )


def _parse_fold(
    payload: Mapping[str, Any],
    *,
    sample_by_id: Mapping[str, AllocationTrainingSample],
) -> PurgedWalkForwardFold:
    _reject_unknown(
        payload,
        allowed={
            "fold_id",
            "train_row_ids",
            "test_row_ids",
            "test_start",
            "test_end",
            "purge_trading_days",
            "embargo_trading_days",
        },
        field_name="fold",
    )
    train_ids = _text_tuple(
        payload.get("train_row_ids"), field_name="train_row_ids"
    )
    test_ids = _text_tuple(
        payload.get("test_row_ids"), field_name="test_row_ids"
    )
    return PurgedWalkForwardFold(
        fold_id=_text(payload.get("fold_id"), field_name="fold_id"),
        train_rows=tuple(
            _window_row(sample_by_id, row_id=row_id) for row_id in train_ids
        ),
        test_rows=tuple(
            _window_row(sample_by_id, row_id=row_id) for row_id in test_ids
        ),
        test_start=_text(payload.get("test_start"), field_name="test_start"),
        test_end=_text(payload.get("test_end"), field_name="test_end"),
        purge_days=_integer(
            payload.get("purge_trading_days"),
            field_name="purge_trading_days",
        ),
        embargo_days=_integer(
            payload.get("embargo_trading_days"),
            field_name="embargo_trading_days",
        ),
    )


def _parse_window_fold(
    payload: Mapping[str, Any],
    *,
    sample_by_id: Mapping[str, AllocationTrainingSample],
) -> PurgedWalkForwardFold:
    _reject_unknown(
        payload,
        allowed={
            "fold_id",
            "train_end_date",
            "test_start",
            "test_end",
            "purge_trading_days",
            "embargo_trading_days",
        },
        field_name="date-window fold",
    )
    train_end = _text(
        payload.get("train_end_date"), field_name="train_end_date"
    )
    test_start = _text(payload.get("test_start"), field_name="test_start")
    test_end = _text(payload.get("test_end"), field_name="test_end")
    ordered_samples = tuple(
        sorted(
            sample_by_id.values(),
            key=lambda sample: (
                sample.row.decision_at,
                sample.row.row_id,
            ),
        )
    )
    train_rows = tuple(
        _window_row(sample_by_id, row_id=sample.row.row_id)
        for sample in ordered_samples
        if sample.row.decision_at[:10] <= train_end
        and max(
            label.horizon_end_date for label in sample.horizon_labels
        )
        < test_start
    )
    test_rows = tuple(
        _window_row(sample_by_id, row_id=sample.row.row_id)
        for sample in ordered_samples
        if test_start <= sample.row.decision_at[:10] <= test_end
    )
    return PurgedWalkForwardFold(
        fold_id=_text(payload.get("fold_id"), field_name="fold_id"),
        train_rows=train_rows,
        test_rows=test_rows,
        test_start=test_start,
        test_end=test_end,
        purge_days=_integer(
            payload.get("purge_trading_days"),
            field_name="purge_trading_days",
        ),
        embargo_days=_integer(
            payload.get("embargo_trading_days"),
            field_name="embargo_trading_days",
        ),
    )


def _window_row(
    sample_by_id: Mapping[str, AllocationTrainingSample],
    *,
    row_id: str,
) -> MLTimeWindowRow:
    try:
        sample = sample_by_id[row_id]
    except KeyError as exc:
        raise ValueError(f"fold references unknown row: {row_id}") from exc
    label_end = max(
        (
            date.fromisoformat(label.horizon_end_date[:10])
            for label in sample.horizon_labels
        )
    ).isoformat()
    return MLTimeWindowRow(
        row_id=row_id,
        decision_date=sample.row.decision_at[:10],
        label_end_date=label_end,
    )


def _atomic_commit_outputs(
    outputs: tuple[tuple[Path, bytes], ...],
) -> None:
    staged: list[tuple[Path, Path]] = []
    try:
        for target, payload in outputs:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                existing = target.read_bytes()
                if existing != payload:
                    raise ValueError(
                        f"refusing to overwrite different frozen output: {target}"
                    )
                continue
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".staged",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            if temporary.read_bytes() != payload:
                raise OSError(f"staged output verification failed: {target}")
            staged.append((temporary, target))
        for temporary, target in staged:
            os.replace(temporary, target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def _pair_tuple(
    value: Any,
    *,
    field_name: str,
    text_values: bool = False,
) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    result: list[tuple[str, Any]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be two-item arrays")
        key = _text(item[0], field_name=f"{field_name}.key")
        second = (
            _text(item[1], field_name=f"{field_name}.value")
            if text_values
            else item[1]
        )
        result.append((key, second))
    return tuple(result)


def _mapping_sequence(
    value: Any,
    *,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    return tuple(
        _as_mapping(item, field_name=f"{field_name}[]") for item in value
    )


def _as_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _required_json_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a JSON boolean")
    return value


def _text_tuple(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    result = tuple(_text(item, field_name=field_name) for item in value)
    if not allow_empty and not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _explicit_feature_ids(value: Any, *, field_name: str) -> tuple[str, ...]:
    feature_ids = _text_tuple(value, field_name=field_name)
    for feature_id in feature_ids:
        if any(character in feature_id for character in ("*", "?", "[", "]")):
            raise ValueError(
                "feature_ids must be explicit registry ids; wildcard is forbidden"
            )
    return feature_ids


def _integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    return value


def _integer_tuple(value: Any, *, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError(f"{field_name} must be a non-empty integer array")
    return tuple(_integer(item, field_name=field_name) for item in value)


def _reject_unknown(
    payload: Mapping[str, Any],
    *,
    allowed: set[str],
    field_name: str,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unsupported {field_name} field: {sorted(unknown)[0]}")


def _canonical_pack_shape(
    packs: tuple[FeaturePackDefinition, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        sorted(
            ((pack.pack_id, pack.feature_ids) for pack in packs),
            key=lambda item: item[0],
        )
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())
