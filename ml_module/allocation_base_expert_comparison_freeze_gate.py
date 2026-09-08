"""在讀取 confirmatory fold source 前驗證已發布 comparison freeze。

這個 gate 只讀已發布的 comparison receipt、parent/store manifest 與四個
owner 程式檔的 bytes；它不開啟任何 future fold 的 price、label 或 result。
future reader 必須先取得 :class:`ConfirmatoryScopeGate`，再把 token 傳給
自己的 source reader，避免只依 receipt 內的 ``requires_frozen_method_hash``
字串就繼續讀取資料。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ml_module import allocation_base_expert_comparison as comparison
from ml_module import allocation_oos_portfolio_replay as replay
from ml_module import allocation_oos_replay_input_builder as replay_input_builder
from ml_module import allocation_replay_causal_volume_sidecar as causal_volume_sidecar


_SHA256_PREFIX = "sha256:"
_CONFIRMATORY_FOLD_ID = "fold-005"
_EXPLORATORY_FOLD_ID = "fold-004"
_EXPECTED_BATCH_SIZE = 8_192
_EXPECTED_MEMORY_BUDGET_MB = 4_096


class ConfirmatoryFreezeGateError(ValueError):
    """published receipt 未滿足 confirmatory read 的 frozen method 條件。"""


@dataclass(frozen=True)
class ConfirmatoryScopeGate:
    """由 gate 驗證後才可交給 future source reader 的 immutable token。"""

    receipt_path: Path
    comparison_hash: str
    method_freeze_hash: str
    fold_id: str
    request_hash: str
    method_freeze_version: str
    policy_hash: str
    parent_training_manifest_hash: str
    parent_store_manifest_hash: str
    parent_store_manifest_file_hash: str
    parent_training_manifest_path: Path
    parent_store_manifest_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": (
                "allocation-base-expert-confirmatory-gate.v1"
            ),
            "status": "validated_before_confirmatory_read",
            "receipt_path": str(self.receipt_path),
            "comparison_hash": self.comparison_hash,
            "method_freeze_hash": self.method_freeze_hash,
            "fold_id": self.fold_id,
            "request_hash": self.request_hash,
            "method_freeze_version": self.method_freeze_version,
            "policy_hash": self.policy_hash,
            "parent_training_manifest_hash": (
                self.parent_training_manifest_hash
            ),
            "parent_store_manifest_hash": self.parent_store_manifest_hash,
            "parent_store_manifest_file_hash": (
                self.parent_store_manifest_file_hash
            ),
            "parent_training_manifest_path": str(
                self.parent_training_manifest_path
            ),
            "parent_store_manifest_path": str(
                self.parent_store_manifest_path
            ),
            "price_data_read": False,
            "label_data_read": False,
            "result_data_read": False,
        }


def authorize_confirmatory_scope(
    receipt_path: Path,
    *,
    fold_id: str = _CONFIRMATORY_FOLD_ID,
) -> ConfirmatoryScopeGate:
    """驗證 published v6 receipt，且在任何 future source read 前失敗關閉。

    ``fold_id`` 會先檢查，之後才讀 receipt。receipt 的靜態 hashes、policy、
    parent lineage 與獨立 fold-005 request 全部通過後，才會回傳 gate token。
    此函式不接受 source path，也不會讀取 fold-005 的任何資料。
    """

    if fold_id != _CONFIRMATORY_FOLD_ID:
        raise ConfirmatoryFreezeGateError(
            "confirmatory gate only accepts pre-registered fold-005"
        )
    if not isinstance(receipt_path, Path):
        raise TypeError("receipt_path must be a Path")
    receipt = _read_json(receipt_path.resolve())
    _validate_receipt_hash(receipt)
    if receipt.get("status") != "complete_research":
        raise ConfirmatoryFreezeGateError("published receipt is not complete")
    if receipt.get("fold_id") != _EXPLORATORY_FOLD_ID:
        raise ConfirmatoryFreezeGateError(
            "published receipt must be the frozen exploratory fold-004 receipt"
        )
    if receipt.get("formal_oos_allowed") is not False:
        raise ConfirmatoryFreezeGateError("formal_oos_allowed must remain false")
    if receipt.get("production_alpha_bp") != 0:
        raise ConfirmatoryFreezeGateError("production_alpha_bp must remain zero")
    if receipt.get("broker_order_allowed") is not False:
        raise ConfirmatoryFreezeGateError("broker_order_allowed must remain false")

    parent_hash = _required_sha256(
        receipt.get("parent_training_manifest_hash"),
        "parent_training_manifest_hash",
    )
    store_hash = _required_sha256(
        receipt.get("parent_store_manifest_hash"),
        "parent_store_manifest_hash",
    )
    method = _required_mapping(receipt.get("method_freeze"), "method_freeze")
    _validate_method_freeze_static(
        receipt,
        method=method,
        parent_hash=parent_hash,
        store_hash=store_hash,
    )
    future_scope = _validate_future_scope(receipt, method)

    # 靜態 freeze 驗證全部先完成；以下只讀 immutable parent/store manifest，
    # 不會觸碰 future fold 的 row、price、label 或 result sidecar。
    parent_path = _required_path(
        receipt.get("parent_training_manifest_path"),
        "parent_training_manifest_path",
    )
    parent = _read_json(parent_path)
    if _logical_hash(parent, "manifest_hash") != parent_hash:
        raise ConfirmatoryFreezeGateError(
            "parent training manifest hash no longer matches published receipt"
        )
    store_path = _resolve_store_path(parent_path, parent)
    store = _read_json(store_path)
    if _logical_hash(store, "manifest_hash") != store_hash:
        raise ConfirmatoryFreezeGateError(
            "parent store manifest hash no longer matches published receipt"
        )
    if parent.get("store_manifest_hash") != store_hash:
        raise ConfirmatoryFreezeGateError(
            "parent store_manifest_hash does not match published receipt"
        )
    store_file_hash = _file_sha256(store_path)
    if receipt.get("parent_store_manifest_file_hash") != store_file_hash:
        raise ConfirmatoryFreezeGateError(
            "parent store manifest file hash no longer matches receipt"
        )

    return ConfirmatoryScopeGate(
        receipt_path=receipt_path.resolve(),
        comparison_hash=_required_sha256(
            receipt.get("comparison_hash"), "comparison_hash"
        ),
        method_freeze_hash=_required_sha256(
            method.get("method_freeze_hash"), "method_freeze_hash"
        ),
        fold_id=fold_id,
        request_hash=_required_sha256(
            future_scope.get("request_hash"), "future.request_hash"
        ),
        method_freeze_version=str(method["method_freeze_version"]),
        policy_hash=_required_sha256(method.get("policy_hash"), "policy_hash"),
        parent_training_manifest_hash=parent_hash,
        parent_store_manifest_hash=store_hash,
        parent_store_manifest_file_hash=_required_sha256(
            receipt.get("parent_store_manifest_file_hash"),
            "parent_store_manifest_file_hash",
        ),
        parent_training_manifest_path=parent_path,
        parent_store_manifest_path=store_path,
    )


def _validate_receipt_hash(receipt: Mapping[str, Any]) -> None:
    expected = _required_sha256(receipt.get("comparison_hash"), "comparison_hash")
    body = dict(receipt)
    body.pop("comparison_hash", None)
    if _payload_hash(body) != expected:
        raise ConfirmatoryFreezeGateError("published comparison hash mismatch")


def _validate_method_freeze_static(
    receipt: Mapping[str, Any],
    *,
    method: Mapping[str, Any],
    parent_hash: str,
    store_hash: str,
) -> None:
    if method.get("method_freeze_version") != comparison.METHOD_FREEZE_VERSION:
        raise ConfirmatoryFreezeGateError("method freeze version is not current")
    parent_input_hashes = _required_mapping(
        method.get("parent_input_hashes"), "method.parent_input_hashes"
    )
    if parent_input_hashes != {
        "parent_training_manifest_hash": parent_hash,
        "parent_store_manifest_hash": store_hash,
    }:
        raise ConfirmatoryFreezeGateError("method parent input hashes mismatch")

    expected_code_hashes = {
        "comparison_file_hash": _file_sha256(
            Path(str(comparison.__file__)).resolve()
        ),
        "replay_input_builder_file_hash": _file_sha256(
            Path(str(replay_input_builder.__file__)).resolve()
        ),
        "replay_policy_owner_file_hash": _file_sha256(
            Path(str(replay.__file__)).resolve()
        ),
        "causal_volume_sidecar_file_hash": _file_sha256(
            Path(str(causal_volume_sidecar.__file__)).resolve()
        ),
    }
    code_hashes = _required_mapping(
        method.get("code_file_hashes"), "method.code_file_hashes"
    )
    if dict(code_hashes) != expected_code_hashes:
        raise ConfirmatoryFreezeGateError(
            "frozen comparison/replay owner code hash changed"
        )

    expected_future_hash = _future_request_hash(
        method_version=comparison.METHOD_FREEZE_VERSION,
        pool_policy_version=comparison.LIQUIDITY_POOL_POLICY_VERSION,
        lot_policy_version=comparison.LOT_EXECUTION_POLICY_VERSION,
        volume_sidecar_policy_version=(
            comparison.CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
        ),
    )
    if method.get("future_confirmatory_request_hashes") != [
        expected_future_hash
    ]:
        raise ConfirmatoryFreezeGateError(
            "future confirmatory request registration hash mismatch"
        )

    expected_policy = _policy_body(expected_future_hash)
    expected_policy_hash = _payload_hash(expected_policy)
    if method.get("policy_hash") != expected_policy_hash:
        raise ConfirmatoryFreezeGateError("frozen comparison policy hash mismatch")

    expected_request = _request_body(receipt, parent_hash, store_hash)
    expected_request_hash = _payload_hash(expected_request)
    if method.get("request_hash") != expected_request_hash:
        raise ConfirmatoryFreezeGateError(
            "frozen exploratory request hash mismatch"
        )

    expected_method_hash = _payload_hash(
        {
            "method_freeze_version": comparison.METHOD_FREEZE_VERSION,
            "request_hash": expected_request_hash,
            "policy_hash": expected_policy_hash,
            "code_file_hashes": expected_code_hashes,
            "parent_input_hashes": {
                "parent_training_manifest_hash": parent_hash,
                "parent_store_manifest_hash": store_hash,
            },
            "future_confirmatory_request_hashes": [expected_future_hash],
        }
    )
    if method.get("method_freeze_hash") != expected_method_hash:
        raise ConfirmatoryFreezeGateError("method freeze hash mismatch")
    if method.get("outcome_tuning") is not False:
        raise ConfirmatoryFreezeGateError("outcome_tuning must be false")


def _validate_future_scope(
    receipt: Mapping[str, Any],
    method: Mapping[str, Any],
) -> Mapping[str, Any]:
    raw = receipt.get("future_confirmatory_scopes")
    if not isinstance(raw, list) or len(raw) != 1:
        raise ConfirmatoryFreezeGateError(
            "receipt must contain exactly one pre-registered future scope"
        )
    scope = _required_mapping(raw[0], "future_confirmatory_scopes[0]")
    if scope.get("fold_id") != _CONFIRMATORY_FOLD_ID:
        raise ConfirmatoryFreezeGateError("future scope fold id mismatch")
    if scope.get("classification") != "confirmatory_oos_pre_registered":
        raise ConfirmatoryFreezeGateError("future scope classification mismatch")
    if scope.get("status") != "registered_not_read":
        raise ConfirmatoryFreezeGateError("future scope is already marked read")
    for key in ("price_data_read", "label_data_read", "result_data_read"):
        if scope.get(key) is not False:
            raise ConfirmatoryFreezeGateError(
                f"future scope {key} must be false before source read"
            )
    if scope.get("requires_frozen_method_hash") is not True:
        raise ConfirmatoryFreezeGateError(
            "future scope must require the complete frozen method hash"
        )
    request_hash = _required_sha256(scope.get("request_hash"), "future.request_hash")
    expected_request_hash = _future_request_hash(
        method_version=comparison.METHOD_FREEZE_VERSION,
        pool_policy_version=comparison.LIQUIDITY_POOL_POLICY_VERSION,
        lot_policy_version=comparison.LOT_EXECUTION_POLICY_VERSION,
        volume_sidecar_policy_version=(
            comparison.CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
        ),
    )
    if request_hash != expected_request_hash:
        raise ConfirmatoryFreezeGateError(
            "future fold request does not match the pre-registered specification"
        )
    if request_hash == method.get("request_hash"):
        raise ConfirmatoryFreezeGateError(
            "future request must be distinct from exploratory request"
        )
    return scope


def _request_body(
    receipt: Mapping[str, Any],
    parent_hash: str,
    store_hash: str,
) -> dict[str, Any]:
    return {
        "request_role": "exploratory_oos_comparison",
        "fold_id": receipt.get("fold_id"),
        "horizon": receipt.get("horizon"),
        "algorithms": receipt.get("algorithms"),
        "pack_ids": receipt.get("pack_ids"),
        "batch_size": _EXPECTED_BATCH_SIZE,
        "memory_budget_mb": _EXPECTED_MEMORY_BUDGET_MB,
        "persistent_new_bytes_budget": 256 * 1024 * 1024,
        "temporary_peak_bytes_budget": 256 * 1024 * 1024,
        "safety_reserve_bytes": 200 * 1024 * 1024 * 1024,
        "acquire_heavy_lock": True,
        "parent_training_manifest_hash": parent_hash,
        "parent_store_manifest_hash": store_hash,
    }


def _future_request_hash(
    *,
    method_version: str,
    pool_policy_version: str,
    lot_policy_version: str,
    volume_sidecar_policy_version: str,
) -> str:
    return _payload_hash(
        _future_request_body(
            method_version=method_version,
            pool_policy_version=pool_policy_version,
            lot_policy_version=lot_policy_version,
            volume_sidecar_policy_version=volume_sidecar_policy_version,
        )
    )


def _future_request_body(
    *,
    method_version: str,
    pool_policy_version: str,
    lot_policy_version: str,
    volume_sidecar_policy_version: str,
) -> dict[str, Any]:
    """回傳唯一的 fold-005 預登記規格，供 hash 與 reader 共用。"""

    return {
        "request_role": "future_confirmatory_registration",
        "fold_id": _CONFIRMATORY_FOLD_ID,
        "horizon": 5,
        "algorithms": ["ridge_logistic"],
        "pack_ids": "parent_declared_complete",
        "liquidity_pool_policy_version": pool_policy_version,
        "lot_execution_policy_version": lot_policy_version,
        "causal_volume_sidecar_policy_version": volume_sidecar_policy_version,
        "method_freeze_version": method_version,
        "status": "registered_not_read",
    }


def _policy_body(future_request_hash: str) -> dict[str, Any]:
    return {
        "comparison_method_version": comparison.METHOD_FREEZE_VERSION,
        "liquidity_pool_policy_version": comparison.LIQUIDITY_POOL_POLICY_VERSION,
        "lot_execution_policy_version": comparison.LOT_EXECUTION_POLICY_VERSION,
        "causal_volume_sidecar_policy_version": (
            comparison.CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
        ),
        "replay_policy": dict(replay._REPLAY_POLICY),
        "maximum_signal_symbols": 8,
        "lane_selection_policies": {
            "base": "positive_expected_excess_return_bp_top8_capped",
            "base_mean": "integer_half_even_mean_positive_score_top8_capped",
            "rule": "persisted_t_minus_one_rule_score_top8_capped",
            "equal_weight": "t_minus_one_liquidity_pool_equal_weight",
        },
        "future_confirmatory_fold_ids": [_CONFIRMATORY_FOLD_ID],
        "future_confirmatory_request_hashes": [future_request_hash],
        "outcome_tuning": False,
    }


def _resolve_store_path(parent_path: Path, parent: Mapping[str, Any]) -> Path:
    value = parent.get("store_manifest_path")
    if not isinstance(value, str) or not value.strip():
        raise ConfirmatoryFreezeGateError("parent store_manifest_path is missing")
    path = Path(value)
    return (path if path.is_absolute() else parent_path.parent / path).resolve()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfirmatoryFreezeGateError(f"required immutable receipt is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfirmatoryFreezeGateError(
            f"cannot read immutable receipt: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise ConfirmatoryFreezeGateError(f"JSON object required: {path}")
    return value


def _required_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfirmatoryFreezeGateError(f"{field_name} must be an object")
    return value


def _required_path(value: object, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfirmatoryFreezeGateError(f"{field_name} is missing")
    return Path(value).resolve()


def _required_sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
    ):
        raise ConfirmatoryFreezeGateError(f"{field_name} must be a sha256 value")
    return value


def _logical_hash(payload: Mapping[str, Any], field_name: str) -> str:
    value = _required_sha256(payload.get(field_name), field_name)
    body = dict(payload)
    body.pop(field_name, None)
    if _payload_hash(body) != value:
        raise ConfirmatoryFreezeGateError(f"{field_name} logical hash mismatch")
    return value


def _payload_hash(payload: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ConfirmatoryFreezeGateError(
            f"cannot read frozen owner file: {path}"
        ) from exc
    return _SHA256_PREFIX + digest.hexdigest()


__all__ = [
    "ConfirmatoryFreezeGateError",
    "ConfirmatoryScopeGate",
    "authorize_confirmatory_scope",
]
