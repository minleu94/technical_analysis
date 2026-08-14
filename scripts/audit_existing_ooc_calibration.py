"""唯讀重驗既有 OOC base OOF 的 cross-fitted calibration。

這個工具只消費已發布的 training/store/artifact custody，重新驗證 hash
後重算 shadow calibration diagnostic。它不重訓、不改寫 training manifest、
不寫入正式 SQLite，也不會建立 promotion-compatible pointer。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml_module.allocation_out_of_core_training_service import (  # noqa: E402
    _NumericStore,
    _calibration_summary,
    _file_sha256,
    _read_and_validate_artifact,
    _read_json,
    _validate_training_manifest,
)


AUDIT_SCHEMA_VERSION = "allocation-ooc-calibration-audit.v1"
_ATOMIC_REPLACE_RETRY_COUNT = 120
_ATOMIC_REPLACE_RETRY_DELAY_SECONDS = 0.5


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value.strip()


def _required_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _required_sequence(
    value: object,
    *,
    field_name: str,
) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise TypeError(f"{field_name} must be a list of mappings")
    return value


def _resolve_store_manifest(
    *,
    training_manifest_path: Path,
    training_manifest: Mapping[str, Any],
) -> Path:
    release_root = training_manifest_path.parent.parents[2].resolve()
    store_value = _required_text(
        training_manifest.get("store_manifest_path"),
        field_name="store_manifest_path",
    )
    store_path = (training_manifest_path.parent / store_value).resolve()
    if not store_path.is_relative_to(release_root):
        raise ValueError("store_manifest_path escapes the release custody root")
    if not store_path.is_file():
        raise FileNotFoundError(store_path)
    return store_path


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                    raise
                time.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_calibration_audit_report(
    *,
    training_manifest_path: Path,
    batch_size: int = 65_536,
) -> dict[str, Any]:
    """重新驗證 OOC custody 並建立不可升級的 calibration report。"""

    if batch_size <= 0 or batch_size > 65_536:
        raise ValueError("batch_size must be between 1 and 65536")
    training_manifest_path = training_manifest_path.resolve()
    if not training_manifest_path.is_file():
        raise FileNotFoundError(training_manifest_path)
    training_run_directory = training_manifest_path.parent
    training_manifest = _read_json(training_manifest_path)
    run_identity = _required_mapping(
        training_manifest.get("run_identity"),
        field_name="run_identity",
    )
    _validate_training_manifest(
        manifest=training_manifest,
        run_directory=training_run_directory,
        expected_identity=run_identity,
    )

    store_manifest_path = _resolve_store_manifest(
        training_manifest_path=training_manifest_path,
        training_manifest=training_manifest,
    )
    store = _NumericStore(store_manifest_path)
    training_manifest_hash = _required_text(
        training_manifest.get("manifest_hash"),
        field_name="training_manifest.manifest_hash",
    )
    store_manifest_hash = _required_text(
        store.manifest.get("manifest_hash"),
        field_name="store_manifest.manifest_hash",
    )
    if training_manifest.get("store_manifest_hash") != store_manifest_hash:
        raise ValueError("training/store logical hash binding mismatch")
    store_file_hash = _file_sha256(store_manifest_path)
    if training_manifest.get("store_manifest_file_hash") != store_file_hash:
        raise ValueError("training/store physical hash binding mismatch")

    base_entries = _required_sequence(
        training_manifest.get("base_experts"),
        field_name="base_experts",
    )
    artifacts = [
        _read_and_validate_artifact(
            training_run_directory
            / _required_text(
                entry.get("artifact_path"),
                field_name="base_expert.artifact_path",
            )
        )
        for entry in base_entries
    ]
    expected_base_count = training_manifest.get("base_expert_count")
    if expected_base_count != len(artifacts):
        raise ValueError("training/base expert count mismatch")
    artifact_store_hashes = {
        _required_text(
            artifact.get("store_manifest_hash"),
            field_name="base_expert.store_manifest_hash",
        )
        for artifact in artifacts
    }
    if artifact_store_hashes != {store_manifest_hash}:
        raise ValueError("base expert/store logical hash binding mismatch")

    started_ns = time.monotonic_ns()
    calibration = _calibration_summary(
        store=store,
        artifacts=artifacts,
        batch_size=batch_size,
    )
    elapsed_ms = (time.monotonic_ns() - started_ns) // 1_000_000
    horizon_reports = calibration.get("horizons")
    quality_pass = bool(
        isinstance(horizon_reports, list)
        and horizon_reports
        and all(
            isinstance(report, Mapping)
            and report.get("quality_pass") is True
            for report in horizon_reports
        )
    )
    blockers: list[str] = [
        "calibration_diagnostic_only_not_attached_to_ooc_model",
    ]
    if calibration.get("cross_fitted_calibration") is not True:
        blockers.append("calibration_not_cross_fitted")
    if not quality_pass:
        blockers.append("calibration_quality_threshold_failed")

    body: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "complete_shadow_diagnostic",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "formal_oos_allowed": False,
        "production_eligible": False,
        "broker_order_allowed": False,
        "promotion_pass": False,
        "quality_pass": quality_pass,
        "blockers": sorted(set(blockers)),
        "custody": {
            "training_manifest_path": str(training_manifest_path),
            "training_manifest_hash": training_manifest_hash,
            "training_manifest_file_hash": _file_sha256(
                training_manifest_path
            ),
            "store_manifest_path": str(store_manifest_path),
            "store_manifest_hash": store_manifest_hash,
            "store_manifest_file_hash": store_file_hash,
            "training_run_id": _required_text(
                training_manifest.get("run_id"),
                field_name="training_manifest.run_id",
            ),
            "base_expert_count": len(artifacts),
            "row_count": store.manifest.get("row_count"),
            "feature_count": len(store.feature_ids),
            "outer_fold_count": len(store.folds),
        },
        "calibration": calibration,
        "elapsed_calibration_ms": elapsed_ms,
    }
    body["audit_hash"] = _payload_hash(body)
    return body


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="唯讀重算既有 OOC OOF 的 cross-fitted calibration。"
    )
    parser.add_argument(
        "--training-manifest",
        type=Path,
        required=True,
        help="已完成的 allocation-ooc-training.v5 manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="獨立 shadow audit JSON 輸出路徑",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=65_536,
        help="OOF 唯讀掃描 batch size（上限 65536）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = build_calibration_audit_report(
            training_manifest_path=args.training_manifest,
            batch_size=args.batch_size,
        )
        _atomic_write_json(args.output.resolve(), report)
    except Exception as exc:  # pragma: no cover - CLI fail-closed boundary
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "read_only": True,
                    "promotion_pass": False,
                    "production_eligible": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "audit_hash": report["audit_hash"],
                "quality_pass": report["quality_pass"],
                "cross_fitted_calibration": report["calibration"].get(
                    "cross_fitted_calibration"
                ),
                "promotion_pass": report["promotion_pass"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
