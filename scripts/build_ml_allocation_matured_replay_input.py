"""從 immutable training publication 建立非 live 的 ML matured replay 輸入。

本工具只重播已存在於 ``portfolio-ml-training-shards.v2`` publication 的成熟
歷史列。它會驗證外部提供的 publication manifest hash、manifest 自身 hash、
全部註冊 shard 的壓縮／JSONL content hash、row count、日期範圍與 header
custody，然後選取指定或最新成熟 decision date 的全部股票列。

輸出固定為 ``allocation-inference-input-v2`` JSON.GZ，且完全移除
``targets`` 與 ``horizon_labels``。這不是 current/live inference，也不是
Formal OOS 證據，不具 production alpha、投組執行或券商送單權限。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
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

from ml_module.allocation_training_service import (  # noqa: E402
    AllocationTrainingSample,
)
from scripts.train_ml_allocation_copilot import (  # noqa: E402
    _load_jsonl_shard,
    _merge_shards,
)


INPUT_SCHEMA_VERSION = "allocation-inference-input-v2"
AUDIT_SCHEMA_VERSION = "allocation-inference-matured-replay-audit-v1"
PUBLICATION_SCHEMA_VERSION = "portfolio-ml-training-shards.v2"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publication-manifest",
        type=Path,
        required=True,
        help="immutable portfolio-ml-training-shards publication 的 manifest.json",
    )
    parser.add_argument(
        "--expected-publication-manifest-hash",
        required=True,
        help="外部 custody 保存的 sha256:<64 hex>，不可只信任 manifest 自簽值",
    )
    parser.add_argument(
        "--decision-date",
        help="指定成熟決策日 YYYY-MM-DD；省略時選 publication 中最新成熟日",
    )
    parser.add_argument(
        "--matured-replay-output",
        type=Path,
        required=True,
        help="檔名必須包含 matured_replay 且副檔名為 .json.gz",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        required=True,
        help="檔名必須包含 matured_replay 且副檔名為 .json",
    )
    parser.add_argument("--compression-level", type=int, default=6)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = _parser().parse_args(argv)
    try:
        summary = _run(
            publication_manifest=args.publication_manifest,
            expected_publication_manifest_hash=(
                args.expected_publication_manifest_hash
            ),
            requested_decision_date=args.decision_date,
            matured_replay_output=args.matured_replay_output,
            audit_output=args.audit_output,
            compression_level=args.compression_level,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "mode": "matured_replay",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "live_data": False,
                    "formal_oos_allowed": False,
                    "production_action_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _run(
    *,
    publication_manifest: Path,
    expected_publication_manifest_hash: str,
    requested_decision_date: str | None,
    matured_replay_output: Path,
    audit_output: Path,
    compression_level: int,
) -> dict[str, Any]:
    if (
        isinstance(compression_level, bool)
        or not isinstance(compression_level, int)
        or not 0 <= compression_level <= 9
    ):
        raise ValueError("compression_level must be an integer within 0..9")
    _require_sha256(
        expected_publication_manifest_hash,
        field_name="expected_publication_manifest_hash",
    )
    _validate_output_paths(
        publication_manifest=publication_manifest,
        matured_replay_output=matured_replay_output,
        audit_output=audit_output,
    )
    manifest, shard_paths = _load_publication_manifest(
        publication_manifest,
        expected_manifest_hash=expected_publication_manifest_hash,
    )
    output_paths = {
        matured_replay_output.resolve(),
        audit_output.resolve(),
    }
    if output_paths & set(shard_paths):
        raise ValueError("outputs must not overwrite publication shards")
    shards = tuple(_load_jsonl_shard(path) for path in shard_paths)
    merged = _merge_shards(shards)
    if any(
        shard.publication_manifest_hash
        != expected_publication_manifest_hash
        for shard in shards
    ):
        raise ValueError("verified shard custody manifest hash mismatch")
    if merged.dataset_id != manifest.get("dataset_id"):
        raise ValueError("merged dataset_id does not match publication manifest")

    cutoff = _aware_datetime(
        merged.training_as_of,
        field_name="training_as_of",
    )
    decision_date, selected_samples, selection_policy = _select_samples(
        samples=merged.samples,
        horizons=merged.horizons,
        cutoff=cutoff,
        requested_decision_date=requested_decision_date,
    )
    input_payload = _build_replay_input_payload(
        samples=selected_samples,
        decision_date=decision_date,
    )
    input_bytes = (
        _canonical_json(input_payload) + "\n"
    ).encode("utf-8")
    compressed_bytes = gzip.compress(
        input_bytes,
        compresslevel=compression_level,
        mtime=0,
    )
    input_hash = _sha256(input_bytes)
    compressed_hash = _sha256(compressed_bytes)

    maturity_rows = [
        _maturity_payload(sample)
        for sample in sorted(
            selected_samples,
            key=lambda item: (item.row.symbol, item.row.row_id),
        )
    ]
    source_shard_custody = [
        {
            "year": entry.get("year"),
            "path": entry.get("path"),
            "compressed_sha256": entry.get("compressed_sha256"),
            "content_sha256": entry.get("content_sha256"),
            "sample_count": entry.get("sample_count"),
            "min_decision_date": entry.get("min_decision_date"),
            "max_decision_date": entry.get("max_decision_date"),
        }
        for entry in _mapping_sequence(
            manifest.get("shards"),
            field_name="publication.shards",
        )
    ]
    audit_without_hash = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "mode": "matured_replay",
        "selection_policy": selection_policy,
        "decision_date": decision_date,
        "training_as_of": merged.training_as_of,
        "publication_id": manifest.get("publication_id"),
        "publication_manifest_hash": expected_publication_manifest_hash,
        "dataset_id": merged.dataset_id,
        "dataset_identity_hash": manifest.get("dataset_identity_hash"),
        "feature_registry_hash": manifest.get("feature_registry_hash"),
        "source_manifest_hashes": manifest.get("source_manifest_hashes"),
        "source_shard_custody": source_shard_custody,
        "selected_row_count": len(selected_samples),
        "all_publication_rows_for_decision_date_selected": True,
        "selected_symbols": sorted(
            sample.row.symbol for sample in selected_samples
        ),
        "selected_row_payload_hashes": [
            {
                "row_id": row_payload["row_id"],
                "row_payload_hash": _sha256_json(row_payload),
            }
            for row_payload in input_payload["rows"]
        ],
        "maturity_evidence_hash": _sha256_json(maturity_rows),
        "inference_input_schema_version": INPUT_SCHEMA_VERSION,
        "inference_input_uncompressed_hash": input_hash,
        "inference_input_compressed_hash": compressed_hash,
        "supervised_fields_removed": ["targets", "horizon_labels"],
        "supervised_field_occurrence_count": 0,
        "live_data": False,
        "current_snapshot_claimed": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "not_performed": [
            "live_data_fetch",
            "current_snapshot_assembly",
            "model_inference",
            "formal_oos_authorization",
            "rule_weight_blend",
            "portfolio_risk_projection",
            "broker_order_routing",
        ],
    }
    audit_hash = _sha256_json(audit_without_hash)
    audit_payload = {
        **audit_without_hash,
        "audit_hash": audit_hash,
    }
    audit_bytes = (
        json.dumps(
            audit_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_commit_outputs(
        (
            (matured_replay_output, compressed_bytes),
            # audit 最後 replace，作為同一 matured replay 批次的 commit marker。
            (audit_output, audit_bytes),
        )
    )
    return {
        "status": "matured_replay_input_built",
        "mode": "matured_replay",
        "decision_date": decision_date,
        "selected_row_count": len(selected_samples),
        "publication_manifest_hash": expected_publication_manifest_hash,
        "inference_input_uncompressed_hash": input_hash,
        "inference_input_compressed_hash": compressed_hash,
        "audit_hash": audit_hash,
        "matured_replay_output": str(matured_replay_output),
        "audit_output": str(audit_output),
        "live_data": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _load_publication_manifest(
    path: Path,
    *,
    expected_manifest_hash: str,
) -> tuple[Mapping[str, Any], tuple[Path, ...]]:
    resolved = path.resolve()
    if resolved.name != "manifest.json" or not resolved.is_file():
        raise ValueError(
            "publication_manifest must reference an existing manifest.json"
        )
    try:
        decoded = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid publication manifest JSON") from exc
    manifest = _mapping(decoded, field_name="publication manifest")
    if manifest.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise ValueError("unsupported publication manifest schema")
    declared_hash = _text(
        manifest.get("manifest_hash"),
        field_name="manifest_hash",
    )
    _require_sha256(declared_hash, field_name="manifest_hash")
    body = dict(manifest)
    body.pop("manifest_hash", None)
    actual_hash = _sha256_json(body)
    if declared_hash != actual_hash:
        raise ValueError("publication manifest self-hash mismatch")
    if declared_hash != expected_manifest_hash:
        raise ValueError("publication manifest external custody hash mismatch")
    if manifest.get("direct_training_input") is not True:
        raise ValueError("publication is not an immutable direct training input")
    if manifest.get("formal_oos_allowed") is not False:
        raise ValueError("training publication cannot authorize Formal OOS")
    if manifest.get("production_action_allowed") is not False:
        raise ValueError("training publication cannot authorize production action")
    if manifest.get("production_alpha_bp") != 0:
        raise ValueError("training publication cannot authorize non-zero alpha")

    manifest_root = resolved.parent
    entries = _mapping_sequence(
        manifest.get("shards"),
        field_name="publication.shards",
    )
    if not entries:
        raise ValueError("publication manifest contains no shards")
    shard_paths: list[Path] = []
    for entry in entries:
        relative = _text(entry.get("path"), field_name="shard.path")
        shard_path = (manifest_root / relative).resolve()
        if not shard_path.is_relative_to(manifest_root):
            raise ValueError("publication shard path escapes manifest root")
        if not shard_path.is_file():
            raise FileNotFoundError(f"publication shard is missing: {relative}")
        shard_paths.append(shard_path)
    if len(shard_paths) != len(set(shard_paths)):
        raise ValueError("publication shard paths must be unique")
    return manifest, tuple(shard_paths)


def _select_samples(
    *,
    samples: tuple[AllocationTrainingSample, ...],
    horizons: tuple[int, ...],
    cutoff: datetime,
    requested_decision_date: str | None,
) -> tuple[str, tuple[AllocationTrainingSample, ...], str]:
    by_date: dict[str, list[AllocationTrainingSample]] = {}
    for sample in samples:
        decision_date = sample.row.decision_at[:10]
        by_date.setdefault(decision_date, []).append(sample)
    mature_dates = tuple(
        sorted(
            decision_date
            for decision_date, rows in by_date.items()
            if rows
            and all(
                _sample_is_mature(
                    sample,
                    horizons=horizons,
                    cutoff=cutoff,
                )
                for sample in rows
            )
        )
    )
    if requested_decision_date is None:
        if not mature_dates:
            raise ValueError("publication contains no fully mature decision date")
        selected_date = mature_dates[-1]
        selection_policy = "latest_fully_matured_publication_decision_date"
    else:
        try:
            selected_date = date.fromisoformat(
                requested_decision_date
            ).isoformat()
        except ValueError as exc:
            raise ValueError("decision_date must be YYYY-MM-DD") from exc
        if selected_date not in by_date:
            raise ValueError("requested decision_date is absent from publication")
        if selected_date not in mature_dates:
            raise ValueError(
                "requested decision_date is not fully mature by training_as_of"
            )
        selection_policy = "explicit_fully_matured_publication_decision_date"
    selected = tuple(
        sorted(
            by_date[selected_date],
            key=lambda item: (item.row.symbol, item.row.row_id),
        )
    )
    return selected_date, selected, selection_policy


def _sample_is_mature(
    sample: AllocationTrainingSample,
    *,
    horizons: tuple[int, ...],
    cutoff: datetime,
) -> bool:
    targets = sample.row.targets
    if targets is None:
        raise ValueError("source training sample is missing AllocationTargets")
    observed_horizons = tuple(
        sorted(label.horizon_trading_days for label in sample.horizon_labels)
    )
    if observed_horizons != tuple(sorted(horizons)):
        raise ValueError("source sample lacks the complete horizon label set")
    decision_at = _aware_datetime(
        sample.row.decision_at,
        field_name="row.decision_at",
    )
    availability = [
        _aware_datetime(
            targets.available_at,
            field_name="targets.available_at",
        ),
        *(
            _aware_datetime(
                label.available_at,
                field_name="horizon_label.available_at",
            )
            for label in sample.horizon_labels
        ),
    ]
    return decision_at <= cutoff and max(availability) <= cutoff


def _build_replay_input_payload(
    *,
    samples: tuple[AllocationTrainingSample, ...],
    decision_date: str,
) -> dict[str, Any]:
    if not samples:
        raise ValueError("matured replay requires at least one row")
    observed_dates = {
        sample.row.decision_at[:10] for sample in samples
    }
    if observed_dates != {decision_date}:
        raise ValueError("matured replay rows must contain exactly one decision date")
    symbols = tuple(sample.row.symbol for sample in samples)
    if len(symbols) != len(set(symbols)):
        raise ValueError("matured replay symbols must be unique")

    row_payloads: list[dict[str, Any]] = []
    for sample in sorted(
        samples,
        key=lambda item: (item.row.symbol, item.row.row_id),
    ):
        if sample.row.targets is None or not sample.horizon_labels:
            raise ValueError(
                "source replay row requires mature supervised evidence"
            )
        row_payload = asdict(sample.row)
        removed_targets = row_payload.pop("targets", None)
        if removed_targets is None:
            raise ValueError("source replay row targets could not be stripped")
        if _contains_supervised_field(row_payload):
            raise ValueError("supervised field remains in replay row")
        row_payloads.append(row_payload)
    payload = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "rows": row_payloads,
    }
    if _contains_supervised_field(payload):
        raise ValueError("supervised field remains in inference input")
    return payload


def _maturity_payload(sample: AllocationTrainingSample) -> dict[str, Any]:
    targets = sample.row.targets
    if targets is None:
        raise ValueError("source training sample is missing AllocationTargets")
    return {
        "row_id": sample.row.row_id,
        "decision_date": sample.row.decision_at[:10],
        "targets_available_at": targets.available_at,
        "horizon_availability": [
            [
                label.horizon_trading_days,
                label.horizon_end_date,
                label.available_at,
            ]
            for label in sorted(
                sample.horizon_labels,
                key=lambda item: item.horizon_trading_days,
            )
        ],
    }


def _contains_supervised_field(value: object) -> bool:
    if isinstance(value, dict):
        if {"targets", "horizon_labels"} & set(value):
            return True
        return any(
            _contains_supervised_field(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_supervised_field(item) for item in value)
    return False


def _validate_output_paths(
    *,
    publication_manifest: Path,
    matured_replay_output: Path,
    audit_output: Path,
) -> None:
    replay_name = matured_replay_output.name.lower()
    audit_name = audit_output.name.lower()
    if (
        "matured_replay" not in replay_name
        or not replay_name.endswith(".json.gz")
    ):
        raise ValueError(
            "matured replay output name must contain matured_replay and end .json.gz"
        )
    if (
        "matured_replay" not in audit_name
        or not audit_name.endswith(".json")
    ):
        raise ValueError(
            "audit output name must contain matured_replay and end .json"
        )
    resolved_outputs = {
        matured_replay_output.resolve(),
        audit_output.resolve(),
    }
    if len(resolved_outputs) != 2:
        raise ValueError("matured replay and audit outputs must be distinct")
    if publication_manifest.resolve() in resolved_outputs:
        raise ValueError("outputs must not overwrite publication manifest")


def _atomic_commit_outputs(
    outputs: tuple[tuple[Path, bytes], ...],
) -> None:
    staged: list[tuple[Path, Path]] = []
    for target, payload in outputs:
        if target.exists() and target.read_bytes() != payload:
            raise ValueError(
                f"refusing to overwrite different immutable output: {target}"
            )
    try:
        for target, payload in outputs:
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
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


def _mapping_sequence(
    value: object,
    *,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    return tuple(
        _mapping(item, field_name=f"{field_name}[]") for item in value
    )


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _aware_datetime(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return _sha256(_canonical_json(value).encode("utf-8"))


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
