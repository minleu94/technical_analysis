"""獨立核對 v3 線性 shadow release 的載入、推論與校準接線。

本檔只讀 release、v3 frozen input 與其 bytes；不訓練、不修改 D:
source，也不把 shadow 結果提升為 formal OOS 或 promotion 證據。
v3 input 可由 immutable content-addressed readback bundle 提供；bundle 只含
frozen input 與 lineage metadata，不依賴原始 TEMP 路徑。
校準核對會從 release sidecar 重新讀取 mapping，再逐 expert 比對
``uncalibrated_downside_probability_bp`` 到 calibrated bp，避免只把
consumer 自己產生的 audit 當成 expected。
"""

from __future__ import annotations

import argparse
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

from app_module.allocation_release_adapter import load_allocation_release  # noqa: E402
from ml_module.allocation_release_contract import (  # noqa: E402
    IntegerProbabilityCalibrator,
    payload_hash,
)
from ml_module.allocation_v3_linear_release import (  # noqa: E402
    _infer_release_readback,
    _load_v3_input,
    _readback_inference_mode,
)
from ml_module.allocation_v3_readback_bundle import (  # noqa: E402
    ReadbackBundle,
    load_readback_bundle,
)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _same_existing_file(first: Path, second: Path) -> bool:
    """判斷兩個已存在路徑是否指向同一個 inode/file。"""

    if not first.exists() or not second.exists():
        return False
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _validate_external_output_path(
    path: Path,
    *,
    release_root: Path,
    input_path: Path,
    field_name: str,
    protected_roots: Sequence[Path] = (),
) -> Path:
    """拒絕輸出覆蓋 release/input/bundle，包含 existing samefile alias。"""

    target = path.resolve()
    resolved_input_path = input_path.resolve()
    if target == resolved_input_path or _same_existing_file(
        target,
        resolved_input_path,
    ):
        raise ValueError(f"{field_name} must not overwrite the v3 input")
    protected = [
        (
            release_root.resolve(),
            "immutable release root",
            "immutable release file",
        )
    ]
    protected.extend(
        (
            root.resolve(),
            "immutable readback bundle root",
            "immutable readback bundle file",
        )
        for root in protected_roots
    )
    for protected_root, root_description, file_description in protected:
        if target == protected_root or protected_root in target.parents:
            raise ValueError(
                f"{field_name} must be outside the {root_description}"
            )
        if protected_root.exists():
            for protected_file in protected_root.rglob("*"):
                if protected_file.is_file() and _same_existing_file(
                    target,
                    protected_file,
                ):
                    raise ValueError(
                        f"{field_name} must not overwrite an {file_description}"
                    )
    return target


def _validate_distinct_output_paths(first: Path, second: Path) -> None:
    """避免摘要與完整 readback 共用同一個 output path。"""

    if first == second or _same_existing_file(first, second):
        raise ValueError("audit output and readback output must be distinct")


def audit_v3_release(
    *,
    release_root: Path,
    v3_input_path: Path | None = None,
    readback_bundle_path: Path | None = None,
    readback_output: Path | None = None,
) -> dict[str, Any]:
    """以 release adapter 加載並用 sidecar mapping 做獨立逐輸出核對。"""

    root = release_root.resolve()
    if (v3_input_path is None) == (readback_bundle_path is None):
        raise ValueError("provide exactly one of v3_input_path or readback_bundle_path")
    bundle: ReadbackBundle | None = None
    if readback_bundle_path is not None:
        bundle = load_readback_bundle(readback_bundle_path)
        input_path = bundle.input_path
    else:
        assert v3_input_path is not None
        input_path = v3_input_path.resolve()
    input_payload, rows = _load_v3_input(input_path)
    loaded = load_allocation_release(root)
    manifest = loaded.manifest
    if bundle is not None:
        bundle_release = bundle.manifest.get("release")
        if not isinstance(bundle_release, Mapping):
            raise ValueError("readback bundle release binding is missing")
        if manifest.release_id != bundle_release.get("release_id"):
            raise ValueError("readback bundle release id differs")
        if manifest.release_identity_hash != bundle_release.get(
            "release_identity_hash"
        ):
            raise ValueError("readback bundle release identity differs")
        if loaded.release_manifest_file_hash != bundle_release.get(
            "release_manifest_file_hash"
        ):
            raise ValueError("readback bundle release manifest differs")
        if manifest.training_manifest_hash != bundle.training_lineage.get(
            "manifest_hash"
        ):
            raise ValueError("readback bundle training lineage differs")
    if (
        manifest.formal_oos_allowed is not False
        or manifest.production_alpha_bp != 0
        or manifest.production_action_allowed is not False
        or manifest.broker_order_allowed is not False
        or manifest.promotion_eligible is not False
    ):
        raise ValueError("v3 release safety flags authorize an unavailable action")
    if input_payload.get("feature_contract_hash") != manifest.feature_registry_hash:
        raise ValueError("v3 input and release feature contract differ")
    artifact_contract = getattr(loaded.service, "_artifact", None)
    if artifact_contract is None:
        raise ValueError("loaded release artifact contract is unavailable")
    meta_probability_input = getattr(artifact_contract, "meta_probability_input", None)
    if meta_probability_input != "calibrated":
        raise ValueError("v3 artifact must declare calibrated meta input")

    calibrator_path = root / manifest.calibration.artifact_file
    calibrator_payload = _read_object(calibrator_path)
    calibrator = IntegerProbabilityCalibrator.from_dict(calibrator_payload)
    if (
        calibrator.calibration_id != manifest.calibration.calibration_id
        or calibrator.model_id != manifest.model_id
        or calibrator.feature_order_hash != manifest.feature_order_hash
        or calibrator.fit_fold_ids != manifest.calibration.fit_fold_ids
    ):
        raise ValueError("release calibrator identity differs from manifest")

    inference_result = _infer_release_readback(
        loaded=loaded,
        rows=rows,
        policy_id=manifest.missing_policy.policy_id,
        policy_hash=manifest.missing_policy.policy_hash,
    )
    if (
        inference_result.formal_oos_allowed is not False
        or inference_result.production_action_allowed is not False
        or inference_result.production_blend_alpha_bp != 0
    ):
        raise ValueError("v3 inference result safety flags changed")
    audit = inference_result.audit_payload()
    row_audits = audit.get("row_audits")
    if not isinstance(row_audits, list) or not row_audits:
        raise ValueError("v3 inference audit has no row_audits")

    expert_rows_checked = 0
    for row_index, row_audit in enumerate(row_audits):
        if not isinstance(row_audit, Mapping):
            raise TypeError(f"row_audits[{row_index}] must be an object")
        expert_outputs = row_audit.get("base_expert_outputs")
        if not isinstance(expert_outputs, Mapping) or not expert_outputs:
            raise ValueError(f"row_audits[{row_index}] has no expert outputs")
        for expert_key, expert_output in expert_outputs.items():
            if not isinstance(expert_output, Mapping):
                raise TypeError(f"{expert_key} output must be an object")
            raw = _required_int(
                expert_output.get("uncalibrated_downside_probability_bp"),
                f"{expert_key}.uncalibrated_downside_probability_bp",
            )
            calibrated = _required_int(
                expert_output.get("downside_probability_bp"),
                f"{expert_key}.downside_probability_bp",
            )
            expected = calibrator.calibrate_bp(raw)
            if calibrated != expected:
                raise ValueError(
                    f"{expert_key} calibrated probability mismatch: "
                    f"{calibrated} != {expected}"
                )
            expert_rows_checked += 1

    file_hashes = {
        "release_manifest": _file_hash(root / "release_manifest.json"),
        "model_artifact": _file_hash(root / manifest.artifact_file),
        "calibrator": _file_hash(calibrator_path),
        "preprocessor": _file_hash(root / manifest.preprocessor.artifact_file),
        "training_manifest": _file_hash(root / "training_manifest.json"),
        "v3_input": _file_hash(input_path),
    }
    if file_hashes["model_artifact"] != manifest.artifact_hash:
        raise ValueError("model artifact hash differs from manifest")
    if file_hashes["calibrator"] != manifest.calibration.artifact_hash:
        raise ValueError("calibrator hash differs from manifest")
    training_payload = _read_object(root / "training_manifest.json")
    if training_payload.get("manifest_hash") != manifest.training_manifest_hash:
        raise ValueError("training manifest identity differs from release")
    if training_payload.get("v3_input_hash") != file_hashes["v3_input"]:
        raise ValueError("training manifest v3 input hash differs")
    expected_readback_mode = _readback_inference_mode(rows)
    if training_payload.get("readback_inference_mode") != expected_readback_mode:
        raise ValueError("training manifest readback mode differs")
    if training_payload.get("inference_readback_status") != (
        "planned_before_publish"
    ):
        raise ValueError(
            "training manifest readback status must remain planned_before_publish"
        )
    readback_payload = training_payload.get("inference_readback")
    if not isinstance(readback_payload, Mapping):
        raise ValueError("training manifest inference_readback is missing")
    if readback_payload.get("mode") != expected_readback_mode:
        raise ValueError("training manifest inference_readback mode differs")
    if readback_payload.get("decision_at") != rows[0].decision_at:
        raise ValueError("training manifest inference_readback decision differs")
    if readback_payload.get("status") != "planned_before_publish":
        raise ValueError(
            "training manifest inference_readback status must remain planned"
        )
    result: dict[str, Any] = {
        "schema_version": "allocation-v3-linear-shadow-release-audit.v1",
        "status": "independent_v3_release_audit_passed",
        "release_root": str(root),
        "release_id": manifest.release_id,
        "release_identity_hash": manifest.release_identity_hash,
        "release_manifest_file_hash": loaded.release_manifest_file_hash,
        "file_hashes": file_hashes,
        "inference_row_count": len(rows),
        "inference_readback_mode": expected_readback_mode,
        "inference_readback_status": "verified_after_publish",
        "audit_row_count": len(row_audits),
        "expert_outputs_checked": expert_rows_checked,
        "inference_audit_hash": payload_hash(audit),
        "calibration_id": calibrator.calibration_id,
        "calibration_contract_hash": calibrator.contract_hash,
        "calibration_mapping_hash": payload_hash(list(calibrator.mapping_bp)),
        "calibration_fit_fold_ids": list(calibrator.fit_fold_ids),
        "meta_probability_input": meta_probability_input,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
        "promotion_eligible": False,
    }
    if readback_output is not None:
        # 保留 adapter 實際產生的完整 audit，讓外部可用同一 canonical
        # payload_hash 重算 inference_audit_hash，而非只相信摘要欄位。
        safe_readback_output = _validate_external_output_path(
            readback_output,
            release_root=root,
            input_path=input_path,
            field_name="readback_output",
            protected_roots=(bundle.bundle_root,) if bundle is not None else (),
        )
        _atomic_write_json(safe_readback_output, audit)
        result["readback_output"] = str(safe_readback_output)
        result["readback_file_hash"] = _file_hash(safe_readback_output)
    if bundle is not None:
        result["readback_bundle"] = {
            "manifest": str(bundle.manifest_path),
            "bundle_identity_hash": bundle.bundle_identity_hash,
            "bundle_manifest_file_hash": _file_hash(bundle.manifest_path),
            "input_object_hash": bundle.input_hash,
        }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--v3-input", type=Path)
    input_group.add_argument("--readback-bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--readback-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    release_root = args.release_root.resolve()
    bundle: ReadbackBundle | None = None
    if args.readback_bundle is not None:
        bundle = load_readback_bundle(args.readback_bundle)
        input_path = bundle.input_path
    else:
        assert args.v3_input is not None
        input_path = args.v3_input.resolve()
    protected_roots = (bundle.bundle_root,) if bundle is not None else ()
    output_path = _validate_external_output_path(
        args.output,
        release_root=release_root,
        input_path=input_path,
        field_name="output",
        protected_roots=protected_roots,
    )
    readback_path: Path | None = None
    if args.readback_output is not None:
        readback_path = _validate_external_output_path(
            args.readback_output,
            release_root=release_root,
            input_path=input_path,
            field_name="readback_output",
            protected_roots=protected_roots,
        )
        _validate_distinct_output_paths(output_path, readback_path)
    result = audit_v3_release(
        release_root=release_root,
        v3_input_path=input_path if bundle is None else None,
        readback_bundle_path=args.readback_bundle,
        readback_output=readback_path,
    )
    _atomic_write_json(output_path, result)
    print(json.dumps({"status": result["status"], "output": str(output_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
