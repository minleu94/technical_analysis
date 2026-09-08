"""以 frozen 模型 artifact 對單一決策時點執行配置型 ML 推論。

輸入只能是顯式 ``allocation-inference-input-v2`` JSON／JSON.GZ；每列都必須
是沒有 teacher targets 的 ``PortfolioMLDatasetRow``。模型 artifact 會先以呼叫端
提供的 SHA-256 驗證，通過後才允許 joblib 反序列化。若提供 ``--release-root``，
則由 ``AllocationReleaseAdapter`` 一次驗證 release manifest、前處理、校準器、
feature order、missing policy 與 lineage，再執行相同的唯讀推論。

本入口只產生不可執行的 ML proposal 與 replay audit。輸出固定
``formal_oos_allowed=false``、``production_action_allowed=false``、
``production_blend_alpha_bp=0`` 與 ``broker_order_allowed=false``；不會執行
Rule 混合、投組限制投影、Advice 或券商送單。
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.ml_allocation_inference_service import (  # noqa: E402
    MLAllocationInferenceService,
)
from app_module.allocation_release_adapter import (  # noqa: E402
    AllocationReleaseAdapter,
)
from ml_module.allocation_contracts import (  # noqa: E402
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
)


INPUT_SCHEMA_VERSION = "allocation-inference-input-v2"
PROPOSAL_SCHEMA_VERSION = "ml-allocation-proposal-output-v3"
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "rows"})
_ROW_FIELDS = frozenset(
    {
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
    }
)
_FEATURE_FIELDS = frozenset(
    {
        "feature_id",
        "family_id",
        "source_id",
        "value_int",
        "scale",
        "event_at",
        "available_at",
        "revision_id",
        "quality",
        "content_hash",
        "observed",
        "event_time_semantics",
    }
)
_STATE_FIELDS = frozenset(
    {
        "as_of_date",
        "weights",
        "weekly_turnover_used_bp",
        "state_hash",
    }
)
_WEIGHT_FIELDS = frozenset({"positions_bp", "cash_bp"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        required=False,
        help="由受控訓練流程產生的 immutable joblib artifact；使用 --release-root 時可省略",
    )
    parser.add_argument(
        "--artifact-hash",
        required=False,
        help="受控 training manifest 中的 sha256:<64 hex>",
    )
    parser.add_argument(
        "--dataset-id",
        required=False,
        help="受控 training manifest 中的 frozen dataset id",
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        help=(
            "選用的 immutable allocation release root；會由 "
            "AllocationReleaseAdapter 驗證 manifest、artifact、前處理與校準器"
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="單一決策時間的 allocation-inference-input-v2 JSON／JSON.GZ",
    )
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--universe-id", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--policy-hash", required=True)
    parser.add_argument("--expected-universe-hash", required=True)
    parser.add_argument("--proposal-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = _parser().parse_args(argv)
    if args.release_root is None and (
        args.artifact is None
        or args.artifact_hash is None
        or args.dataset_id is None
    ):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "message": "請提供 --release-root，或同時提供 --artifact、--artifact-hash、--dataset-id",
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
    try:
        summary = _run(
            artifact_path=args.artifact,
            expected_artifact_hash=args.artifact_hash,
            expected_dataset_id=args.dataset_id,
            release_root=args.release_root,
            input_path=args.input,
            model_id=args.model_id,
            universe_id=args.universe_id,
            policy_id=args.policy_id,
            policy_hash=args.policy_hash,
            expected_universe_hash=args.expected_universe_hash,
            proposal_output=args.proposal_output,
            audit_output=args.audit_output,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
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


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _required_text(value: str | None, *, field_name: str) -> str:
    """把 optional CLI contract 收窄成 service 所需的非空字串。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 必須提供")
    return value


def _run(
    *,
    artifact_path: Path | None,
    expected_artifact_hash: str | None,
    expected_dataset_id: str | None,
    release_root: Path | None = None,
    input_path: Path,
    model_id: str,
    universe_id: str,
    policy_id: str,
    policy_hash: str,
    expected_universe_hash: str,
    proposal_output: Path,
    audit_output: Path,
) -> dict[str, Any]:
    if release_root is not None:
        release = AllocationReleaseAdapter().load(release_root)
        artifact_for_paths = release_root / release.manifest.artifact_file
    else:
        if artifact_path is None:
            raise ValueError(
                "artifact_path、expected_artifact_hash 與 expected_dataset_id 必須同時提供"
            )
        expected_artifact_hash_value = _required_text(
            expected_artifact_hash,
            field_name="expected_artifact_hash",
        )
        expected_dataset_id_value = _required_text(
            expected_dataset_id,
            field_name="expected_dataset_id",
        )
        artifact_for_paths = artifact_path
        release = None
    _validate_distinct_paths(
        artifact_path=artifact_for_paths,
        input_path=input_path,
        proposal_output=proposal_output,
        audit_output=audit_output,
    )
    rows = _load_rows(input_path)
    if release is not None:
        result = release.infer(
            rows=rows,
            model_id=model_id,
            universe_id=universe_id,
            policy_id=policy_id,
            policy_hash=policy_hash,
            expected_universe_hash=expected_universe_hash,
        )
    else:
        service = MLAllocationInferenceService.from_artifact_path(
            artifact_for_paths,
            expected_artifact_hash=expected_artifact_hash_value,
            expected_dataset_id=expected_dataset_id_value,
        )
        result = service.infer(
            rows=rows,
            model_id=model_id,
            universe_id=universe_id,
            policy_id=policy_id,
            policy_hash=policy_hash,
            expected_universe_hash=expected_universe_hash,
        )
    proposal_payload = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "status": "inference_completed",
        "proposal_hash": result.proposal_hash,
        "replay_hash": result.replay_hash,
        "proposal": result.proposal.to_dict(),
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "not_performed": [
            "promotion_authorization",
            "rule_weight_blend",
            "portfolio_risk_projection",
            "advice_composition",
            "broker_order_routing",
        ],
    }
    proposal_bytes = (
        json.dumps(
            proposal_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    audit_bytes = (result.audit_json + "\n").encode("utf-8")
    _atomic_commit_outputs(
        (
            (proposal_output, proposal_bytes),
            # audit 最後 replace，作為同一推論批次的 commit marker。
            (audit_output, audit_bytes),
        )
    )
    requested = result.proposal.requested_weights
    return {
        "status": "inference_completed",
        "dataset_id": result.proposal.dataset_id,
        "decision_date": result.proposal.decision_date,
        "proposal_hash": result.proposal_hash,
        "replay_hash": result.replay_hash,
        "coverage_bp": result.proposal.coverage_bp,
        "fallback_reason": result.proposal.fallback_reason,
        "requested_position_count": len(requested.symbol_weights_bp),
        "requested_cash_bp": requested.cash_weight_bp,
        "proposal_output": str(proposal_output),
        "audit_output": str(audit_output),
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _load_rows(path: Path) -> tuple[PortfolioMLDatasetRow, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"inference input is missing: {path}")
    raw_bytes = path.read_bytes()
    if path.name.lower().endswith(".gz"):
        try:
            json_bytes = gzip.decompress(raw_bytes)
        except (OSError, EOFError) as exc:
            raise ValueError(f"invalid gzip inference input: {path}") from exc
    else:
        json_bytes = raw_bytes
    try:
        raw_payload = json.loads(json_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON inference input: {path}") from exc
    payload = _mapping(raw_payload, field_name="input")
    _reject_unknown(
        payload,
        allowed=_TOP_LEVEL_FIELDS,
        field_name="input",
    )
    if payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must equal {INPUT_SCHEMA_VERSION}"
        )
    row_payloads = _mapping_sequence(payload.get("rows"), field_name="rows")
    if not row_payloads:
        raise ValueError("rows must not be empty")
    return tuple(_parse_row(row) for row in row_payloads)


def _parse_row(payload: Mapping[str, Any]) -> PortfolioMLDatasetRow:
    _reject_unknown(payload, allowed=_ROW_FIELDS, field_name="row")
    if payload.get("targets") is not None:
        raise ValueError("inference row targets must be absent or null")

    feature_payloads = _mapping_sequence(
        payload.get("features"),
        field_name="features",
    )
    features: list[PITFeatureValue] = []
    for feature_payload in feature_payloads:
        _reject_unknown(
            feature_payload,
            allowed=_FEATURE_FIELDS,
            field_name="feature",
        )
        features.append(PITFeatureValue(**dict(feature_payload)))

    state_payload = _mapping(
        payload.get("portfolio_state"),
        field_name="portfolio_state",
    )
    _reject_unknown(
        state_payload,
        allowed=_STATE_FIELDS,
        field_name="portfolio_state",
    )
    weights_payload = _mapping(
        state_payload.get("weights"),
        field_name="portfolio_state.weights",
    )
    _reject_unknown(
        weights_payload,
        allowed=_WEIGHT_FIELDS,
        field_name="portfolio_state.weights",
    )
    portfolio_state = CausalPortfolioState(
        as_of_date=state_payload["as_of_date"],
        weights=AllocationWeightContract(
            positions_bp=_pair_tuple(
                weights_payload.get("positions_bp"),
                field_name="positions_bp",
            ),
            cash_bp=weights_payload["cash_bp"],
        ),
        weekly_turnover_used_bp=state_payload["weekly_turnover_used_bp"],
        state_hash=state_payload["state_hash"],
    )
    return PortfolioMLDatasetRow(
        row_id=payload["row_id"],
        decision_at=payload["decision_at"],
        symbol=payload["symbol"],
        features=tuple(features),
        missing_family_ids=_text_tuple(
            payload.get("missing_family_ids", ()),
            field_name="missing_family_ids",
            allow_empty=True,
        ),
        portfolio_state=portfolio_state,
        dataset_identity_hash=payload["dataset_identity_hash"],
        feature_registry_hash=payload["feature_registry_hash"],
        source_manifest_hashes=_pair_tuple(
            payload.get("source_manifest_hashes"),
            field_name="source_manifest_hashes",
            text_values=True,
        ),
        targets=None,
    )


def _validate_distinct_paths(
    *,
    artifact_path: Path,
    input_path: Path,
    proposal_output: Path,
    audit_output: Path,
) -> None:
    read_paths = {artifact_path.resolve(), input_path.resolve()}
    output_paths = {proposal_output.resolve(), audit_output.resolve()}
    if len(output_paths) != 2:
        raise ValueError("proposal and audit outputs must be distinct")
    if read_paths & output_paths:
        raise ValueError("outputs must not overwrite artifact or inference input")


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
        _mapping(item, field_name=f"{field_name}[]") for item in value
    )


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
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


def _reject_unknown(
    payload: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    field_name: str,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            f"unsupported {field_name} field: {sorted(unknown)[0]}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
