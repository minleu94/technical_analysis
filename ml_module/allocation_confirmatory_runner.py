"""在同一程序內執行 confirmatory freeze gate 與受控 source reader。

這個入口把已驗證的 exploratory receipt、parent/store lineage、policy 與
fold-005 預登記 request 綁成 immutable request，只有完成全部驗證後才呼叫
source reader。reader 不會收到未綁定的 source path；未來的資料開啟必須在
callback 內使用本模組提供的 token/request，避免先讀資料再補做 gate。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    StorageCapacityError,
    acquire_heavy_chain_reservation,
    heavy_chain_lock_path,
    release_heavy_chain_reservation,
)
from ml_module import allocation_base_expert_comparison as comparison
from ml_module.allocation_base_expert_comparison_freeze_gate import (
    ConfirmatoryFreezeGateError,
    ConfirmatoryScopeGate,
    _future_request_body,
    _payload_hash,
    authorize_confirmatory_scope,
)


_T = TypeVar("_T")
_CONFIRMATORY_BATCH_SIZE = 8_192
_CONFIRMATORY_MEMORY_BUDGET_MB = 4_096
_CONFIRMATORY_PERSISTENT_BUDGET = 256 * 1024 * 1024
_CONFIRMATORY_TEMPORARY_BUDGET = 256 * 1024 * 1024
_CONFIRMATORY_SAFETY_RESERVE = 200 * BYTES_PER_GIB


def _shared_heavy_lock_path(parent_path: Path) -> Path:
    """解析與 raw/Direct/OOC 相同的 release_v4 共用 reservation lock。"""

    resolved = parent_path.resolve()
    candidates = (resolved, *resolved.parents)
    release_root = next(
        (
            candidate
            for candidate in candidates
            if candidate.name.casefold() == "release_v4"
        ),
        None,
    )
    if release_root is None:
        raise ConfirmatoryFreezeGateError(
            "parent manifest is not under the shared release_v4 root"
        )
    return heavy_chain_lock_path(release_root)


@dataclass(frozen=True)
class ConfirmatoryBoundRequest:
    """由 gate token 建立、不可由 source reader 修改的 fold request。"""

    fold_id: str
    horizon: int
    algorithms: tuple[str, ...]
    pack_ids: str
    liquidity_pool_policy_version: str
    lot_execution_policy_version: str
    causal_volume_sidecar_policy_version: str
    method_freeze_version: str
    status: str
    request_hash: str
    comparison_hash: str
    method_freeze_hash: str
    policy_hash: str
    parent_training_manifest_hash: str
    parent_store_manifest_hash: str
    parent_store_manifest_file_hash: str
    parent_training_manifest_path: Path
    parent_store_manifest_path: Path
    runner_file_hash: str
    batch_size: int
    memory_budget_mb: int
    persistent_new_bytes_budget: int
    temporary_peak_bytes_budget: int
    safety_reserve_bytes: int
    heavy_lock_path: Path
    binding_hash: str

    def as_dict(self) -> dict[str, Any]:
        """輸出可寫入 audit 的完整 request binding。"""

        return {
            "request_role": "future_confirmatory_reader",
            "fold_id": self.fold_id,
            "horizon": self.horizon,
            "algorithms": list(self.algorithms),
            "pack_ids": self.pack_ids,
            "liquidity_pool_policy_version": (
                self.liquidity_pool_policy_version
            ),
            "lot_execution_policy_version": (
                self.lot_execution_policy_version
            ),
            "causal_volume_sidecar_policy_version": (
                self.causal_volume_sidecar_policy_version
            ),
            "method_freeze_version": self.method_freeze_version,
            "status": self.status,
            "request_hash": self.request_hash,
            "comparison_hash": self.comparison_hash,
            "method_freeze_hash": self.method_freeze_hash,
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
            "runner_file_hash": self.runner_file_hash,
            "batch_size": self.batch_size,
            "memory_budget_mb": self.memory_budget_mb,
            "persistent_new_bytes_budget": self.persistent_new_bytes_budget,
            "temporary_peak_bytes_budget": self.temporary_peak_bytes_budget,
            "safety_reserve_bytes": self.safety_reserve_bytes,
            "heavy_lock_path": str(self.heavy_lock_path),
            "binding_hash": self.binding_hash,
        }


def build_confirmatory_bound_request(
    gate: ConfirmatoryScopeGate,
) -> ConfirmatoryBoundRequest:
    """從已授權 token 建立完整、可稽核的 future request。"""

    specification = _future_request_body(
        method_version=gate.method_freeze_version,
        pool_policy_version=comparison.LIQUIDITY_POOL_POLICY_VERSION,
        lot_policy_version=comparison.LOT_EXECUTION_POLICY_VERSION,
        volume_sidecar_policy_version=(
            comparison.CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
        ),
    )
    request_hash = _payload_hash(specification)
    if request_hash != gate.request_hash:
        raise ConfirmatoryFreezeGateError(
            "authorized future request specification changed"
        )
    binding_body = {
        **specification,
        "comparison_hash": gate.comparison_hash,
        "method_freeze_hash": gate.method_freeze_hash,
        "policy_hash": gate.policy_hash,
        "parent_training_manifest_hash": (
            gate.parent_training_manifest_hash
        ),
        "parent_store_manifest_hash": gate.parent_store_manifest_hash,
        "parent_store_manifest_file_hash": (
            gate.parent_store_manifest_file_hash
        ),
        "parent_training_manifest_path": str(
            gate.parent_training_manifest_path
        ),
        "parent_store_manifest_path": str(gate.parent_store_manifest_path),
        "runner_file_hash": comparison._file_sha256(Path(__file__).resolve()),
        "batch_size": _CONFIRMATORY_BATCH_SIZE,
        "memory_budget_mb": _CONFIRMATORY_MEMORY_BUDGET_MB,
        "persistent_new_bytes_budget": _CONFIRMATORY_PERSISTENT_BUDGET,
        "temporary_peak_bytes_budget": _CONFIRMATORY_TEMPORARY_BUDGET,
        "safety_reserve_bytes": _CONFIRMATORY_SAFETY_RESERVE,
        "heavy_lock_path": str(
            _shared_heavy_lock_path(gate.parent_training_manifest_path)
        ),
        "request_hash": request_hash,
    }
    return ConfirmatoryBoundRequest(
        fold_id=str(specification["fold_id"]),
        horizon=int(specification["horizon"]),
        algorithms=tuple(str(item) for item in specification["algorithms"]),
        pack_ids=str(specification["pack_ids"]),
        liquidity_pool_policy_version=str(
            specification["liquidity_pool_policy_version"]
        ),
        lot_execution_policy_version=str(
            specification["lot_execution_policy_version"]
        ),
        causal_volume_sidecar_policy_version=str(
            specification["causal_volume_sidecar_policy_version"]
        ),
        method_freeze_version=str(specification["method_freeze_version"]),
        status=str(specification["status"]),
        request_hash=request_hash,
        comparison_hash=gate.comparison_hash,
        method_freeze_hash=gate.method_freeze_hash,
        policy_hash=gate.policy_hash,
        parent_training_manifest_hash=gate.parent_training_manifest_hash,
        parent_store_manifest_hash=gate.parent_store_manifest_hash,
        parent_store_manifest_file_hash=(
            gate.parent_store_manifest_file_hash
        ),
        parent_training_manifest_path=gate.parent_training_manifest_path,
        parent_store_manifest_path=gate.parent_store_manifest_path,
        runner_file_hash=comparison._file_sha256(Path(__file__).resolve()),
        batch_size=_CONFIRMATORY_BATCH_SIZE,
        memory_budget_mb=_CONFIRMATORY_MEMORY_BUDGET_MB,
        persistent_new_bytes_budget=_CONFIRMATORY_PERSISTENT_BUDGET,
        temporary_peak_bytes_budget=_CONFIRMATORY_TEMPORARY_BUDGET,
        safety_reserve_bytes=_CONFIRMATORY_SAFETY_RESERVE,
        heavy_lock_path=_shared_heavy_lock_path(
            gate.parent_training_manifest_path
        ),
        binding_hash=_payload_hash(binding_body),
    )


@dataclass(frozen=True)
class ConfirmatoryComparisonRequest:
    """fold-005 比較的固定執行參數；資料路徑由 gate 綁定。"""

    output_root: Path
    fold_id: str = "fold-005"
    horizon: int = 5
    algorithms: tuple[str, ...] = ("ridge_logistic",)
    pack_ids: tuple[str, ...] = ()
    batch_size: int = _CONFIRMATORY_BATCH_SIZE
    memory_budget_mb: int = _CONFIRMATORY_MEMORY_BUDGET_MB
    persistent_new_bytes_budget: int = _CONFIRMATORY_PERSISTENT_BUDGET
    temporary_peak_bytes_budget: int = _CONFIRMATORY_TEMPORARY_BUDGET
    safety_reserve_bytes: int = _CONFIRMATORY_SAFETY_RESERVE
    acquire_heavy_lock: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.output_root, Path):
            raise TypeError("output_root must be a Path")
        if self.fold_id != "fold-005":
            raise ValueError("confirmatory runner only accepts fold-005")
        if self.horizon != 5:
            raise ValueError("confirmatory runner requires h5")
        if self.algorithms != ("ridge_logistic",):
            raise ValueError("confirmatory runner requires ridge_logistic")
        if self.pack_ids:
            raise ValueError(
                "confirmatory request uses the parent-declared complete pack scope"
            )
        for field_name in (
            "batch_size",
            "memory_budget_mb",
            "persistent_new_bytes_budget",
            "temporary_peak_bytes_budget",
            "safety_reserve_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.batch_size > 65_536:
            raise ValueError("batch_size must not exceed 65536")
        if self.memory_budget_mb > 4_096:
            raise ValueError("memory budget must not exceed 4096 MB")
        if self.persistent_new_bytes_budget > 256 * 1024 * 1024:
            raise ValueError("persistent comparison budget exceeds 256 MiB")
        if self.temporary_peak_bytes_budget > 256 * 1024 * 1024:
            raise ValueError("temporary comparison budget exceeds 256 MiB")
        if self.acquire_heavy_lock is not True:
            raise ValueError("confirmatory runner must acquire the heavy lock")


class ConfirmatoryComparisonExecutionError(ConfirmatoryFreezeGateError):
    """比較在已開始 future source read 後失敗，附帶 exposure receipt。"""

    def __init__(
        self,
        message: str,
        *,
        exposure: Mapping[str, Any],
        exposure_receipt_path: Path,
    ) -> None:
        super().__init__(message)
        self.exposure = dict(exposure)
        self.exposure_receipt_path = exposure_receipt_path


def _confirmatory_exposure_receipt(
    *,
    output_root: Path,
    run_id: str,
    gate: ConfirmatoryScopeGate,
    bound: ConfirmatoryBoundRequest,
    source_read_completed: bool,
    phase: str,
    error: BaseException | None,
    status: str | None = None,
) -> tuple[dict[str, Any], Path]:
    """保存 source phase outcome；不把未知狀態誤標成未讀。"""

    observed = True if source_read_completed else None
    body: dict[str, Any] = {
        "schema_version": "allocation-base-expert-confirmatory-exposure.v1",
        "status": status
        or (
            "source_read_completed_publish_failed"
            if source_read_completed
            else "source_read_started_failed"
        ),
        "phase": phase,
        "run_id": run_id,
        "fold_id": bound.fold_id,
        "output_root": str(output_root.resolve()),
        "stable_exposure_receipt_path": str(
            _stable_exposure_outcome_receipt_path(gate)
        ),
        "comparison_hash": bound.comparison_hash,
        "method_freeze_hash": bound.method_freeze_hash,
        "request_hash": bound.request_hash,
        "request_binding_hash": bound.binding_hash,
        "runner_file_hash": bound.runner_file_hash,
        "source_read_attempted": True,
        "source_read_completed": source_read_completed,
        "price_data_read": observed,
        "label_data_read": observed,
        "result_data_read": observed,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "research_only": True,
        "source_readonly": True,
        "gate_status": gate.as_dict()["status"],
        "error_type": type(error).__name__ if error is not None else None,
        "error": str(error) if error is not None else None,
    }
    receipt_path = _local_exposure_outcome_path(output_root, run_id)
    # outcome 是 started receipt 之後的獨立 append-only 檔案；若 process 在
    # source read 中斷，started receipt 仍會留下而不會被誤認為 fresh run。
    stable_receipt_path = _stable_exposure_outcome_receipt_path(gate)
    original_error = error or RuntimeError("confirmatory source phase completed")
    _write_exposure_receipt_consistently(
        stable_receipt_path,
        body,
        original_error,
    )
    _write_exposure_receipt_consistently(receipt_path, body, original_error)
    return body, receipt_path


def _confirmatory_exposure_started_receipt(
    *,
    output_root: Path,
    run_id: str,
    gate: ConfirmatoryScopeGate,
    bound: ConfirmatoryBoundRequest,
) -> Path:
    """在 lock 內 durable exclusive 建立 source read started receipt。"""

    body: dict[str, Any] = {
        "schema_version": "allocation-base-expert-confirmatory-exposure.v1",
        "status": "source_read_started",
        "phase": "confirmatory_source_read",
        "run_id": run_id,
        "fold_id": bound.fold_id,
        "output_root": str(output_root.resolve()),
        "stable_exposure_receipt_path": str(
            _stable_exposure_started_receipt_path(gate)
        ),
        "comparison_hash": bound.comparison_hash,
        "method_freeze_hash": bound.method_freeze_hash,
        "request_hash": bound.request_hash,
        "request_binding_hash": bound.binding_hash,
        "runner_file_hash": bound.runner_file_hash,
        "source_read_attempted": True,
        "source_read_completed": False,
        "price_data_read": None,
        "label_data_read": None,
        "result_data_read": None,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "research_only": True,
        "source_readonly": True,
        "gate_status": gate.as_dict()["status"],
        "error_type": None,
        "error": None,
    }
    started_path = _local_exposure_started_path(output_root, run_id)
    original_error = RuntimeError("confirmatory source phase started")
    _write_exposure_receipt_consistently(
        _stable_exposure_started_receipt_path(gate),
        body,
        original_error,
    )
    _write_exposure_receipt_consistently(
        started_path,
        body,
        original_error,
    )
    return started_path


def _stable_exposure_outcome_receipt_path(
    gate: ConfirmatoryScopeGate,
) -> Path:
    """以 exploratory receipt 為根保存跨 output root 的 outcome identity。"""

    return (
        gate.receipt_path.parent.parent
        / ".confirmatory-exposures"
        / f"{gate.comparison_hash.removeprefix('sha256:')}.outcome.json"
    )


def _stable_exposure_started_receipt_path(
    gate: ConfirmatoryScopeGate,
) -> Path:
    return (
        gate.receipt_path.parent.parent
        / ".confirmatory-exposures"
        / f"{gate.comparison_hash.removeprefix('sha256:')}.started.json"
    )


def _local_exposure_started_path(output_root: Path, run_id: str) -> Path:
    return output_root.resolve() / "runs" / run_id / "confirmatory_exposure.json"


def _local_exposure_outcome_path(output_root: Path, run_id: str) -> Path:
    return (
        output_root.resolve()
        / "runs"
        / run_id
        / "confirmatory_exposure_outcome.json"
    )


def _write_exposure_receipt_consistently(
    path: Path,
    body: Mapping[str, Any],
    original_error: BaseException,
) -> None:
    try:
        comparison._write_json_exclusive(path, body)
    except FileExistsError:
        existing = comparison._read_json_mapping(path)
        if existing != dict(body):
            raise ConfirmatoryFreezeGateError(
                "confirmatory exposure receipt collision"
            ) from original_error


def _load_existing_exposure(
    *,
    gate: ConfirmatoryScopeGate,
    bound: ConfirmatoryBoundRequest,
    output_root: Path,
    run_id: str,
) -> tuple[Mapping[str, Any], Path] | None:
    """在任何 future source read 前恢復既有 exposure identity。"""

    local_path = (
        _local_exposure_outcome_path(output_root, run_id)
    )
    stable_path = _stable_exposure_outcome_receipt_path(gate)
    candidate_paths = (
        stable_path,
        local_path,
        _stable_exposure_started_receipt_path(gate),
        _local_exposure_started_path(output_root, run_id),
    )
    for path in candidate_paths:
        if not path.is_file():
            continue
        body = comparison._read_json_mapping(path)
        expected = {
            "schema_version": "allocation-base-expert-confirmatory-exposure.v1",
            "run_id": run_id,
            "fold_id": bound.fold_id,
            "comparison_hash": bound.comparison_hash,
            "method_freeze_hash": bound.method_freeze_hash,
            "request_hash": bound.request_hash,
            "request_binding_hash": bound.binding_hash,
            "runner_file_hash": bound.runner_file_hash,
            "source_read_attempted": True,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
            "research_only": True,
            "source_readonly": True,
        }
        for field_name, expected_value in expected.items():
            if body.get(field_name) != expected_value:
                raise ConfirmatoryFreezeGateError(
                    "existing confirmatory exposure identity mismatch: "
                    f"{field_name}"
                )
        saved_output_root = body.get("output_root")
        if not isinstance(saved_output_root, str) or not saved_output_root:
            raise ConfirmatoryFreezeGateError(
                "existing confirmatory exposure output root is missing"
            )
        for field_name in (
            "price_data_read",
            "label_data_read",
            "result_data_read",
        ):
            if body.get(field_name) not in (True, None):
                raise ConfirmatoryFreezeGateError(
                    f"existing confirmatory exposure {field_name} is invalid"
                )
        status = body.get("status")
        if status not in {
            "source_read_started",
            "source_read_started_failed",
            "source_read_completed_publish_failed",
            "source_read_completed_published",
        }:
            raise ConfirmatoryFreezeGateError(
                "existing confirmatory exposure status is invalid"
            )
        expected_stable_path = (
            _stable_exposure_started_receipt_path(gate)
            if status == "source_read_started"
            else _stable_exposure_outcome_receipt_path(gate)
        )
        if body.get("stable_exposure_receipt_path") != str(
            expected_stable_path
        ):
            raise ConfirmatoryFreezeGateError(
                "existing confirmatory exposure stable path is invalid"
            )
        completed = status in {
            "source_read_completed_publish_failed",
            "source_read_completed_published",
        }
        if body.get("source_read_completed") is not completed:
            raise ConfirmatoryFreezeGateError(
                "existing confirmatory exposure completion state is invalid"
            )
        expected_observed = True if completed else None
        if any(
            body.get(field_name) is not expected_observed
            for field_name in (
                "price_data_read",
                "label_data_read",
                "result_data_read",
            )
        ):
            raise ConfirmatoryFreezeGateError(
                "existing confirmatory exposure read state is invalid"
            )
        return body, path
    return None


@dataclass(frozen=True)
class _EngineConfirmatoryComparisonRequest(
    comparison.AllocationBaseExpertComparisonRequest
):
    """給既有 read-only engine 的 fold-005 request 型別。

    engine 的公開 request 為了避免誤用只接受 fold-004；此 private subclass
    只在 gate 已通過後建立，沿用相同欄位與預算，允許唯一預先登記的 fold-005。
    """

    def __post_init__(self) -> None:
        if self.fold_id != "fold-005":
            raise ValueError("confirmatory engine request requires fold-005")
        if self.horizon != 5:
            raise ValueError("confirmatory engine request requires h5")
        if self.algorithms != ("ridge_logistic",):
            raise ValueError("confirmatory engine request requires ridge_logistic")
        if self.pack_ids:
            raise ValueError("confirmatory engine request requires all packs")


@dataclass(frozen=True)
class ConfirmatoryComparisonPublication:
    """confirmatory comparison output 的 immutable 路徑與容量證據。"""

    comparison_path: Path
    comparison_hash: str
    latest_pointer_path: Path
    run_id: str
    output_size_bytes: int
    capacity_preflight: Mapping[str, Any]
    idempotent: bool = False


def run_authorized_confirmatory_read(
    receipt_path: Path,
    *,
    source_reader: Callable[[ConfirmatoryScopeGate, ConfirmatoryBoundRequest], _T],
    request: ConfirmatoryBoundRequest | None = None,
    fold_id: str = "fold-005",
) -> _T:
    """先 authorize、再建 request，最後才呼叫 future source reader。

    ``request`` 若由呼叫端提供，必須與本次 gate 依 receipt 建立的完整
    binding 逐欄相同；任何 request、parent、policy 或 hash 改變都會在
    ``source_reader`` 被呼叫前失敗。函式本身不接受或開啟 fold-005 path。
    """

    if not callable(source_reader):
        raise TypeError("source_reader must be callable")
    gate = authorize_confirmatory_scope(receipt_path, fold_id=fold_id)
    bound_request = build_confirmatory_bound_request(gate)
    if request is not None and request != bound_request:
        raise ConfirmatoryFreezeGateError(
            "confirmatory bound request does not match frozen registration"
        )
    # 只有這一行之後才允許 source reader 開啟任何 fold-005 source。
    return source_reader(gate, bound_request)


def preflight_confirmatory_comparison(
    receipt_path: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    """只驗證 freeze 與 output 參數，不開啟 fold-005 source。"""

    request = ConfirmatoryComparisonRequest(output_root=output_root)
    gate = authorize_confirmatory_scope(receipt_path)
    bound = build_confirmatory_bound_request(gate)
    return {
        "schema_version": "allocation-base-expert-confirmatory-runner.v1",
        "status": "preflight_passed_before_confirmatory_read",
        "output_root": str(request.output_root.resolve()),
        "bound_request": bound.as_dict(),
        "price_data_read": False,
        "label_data_read": False,
        "result_data_read": False,
    }


def run_confirmatory_comparison(
    receipt_path: Path,
    *,
    output_root: Path,
    request: ConfirmatoryComparisonRequest | None = None,
) -> ConfirmatoryComparisonPublication:
    """執行 gate 後的真實 fold-005 comparison source/read/publish 路徑。

    這是唯一允許 future comparison 開啟 parent fold source 的入口。gate
    完成後才會呼叫既有 comparison engine 的 read-only payload builder；
    engine 不重訓 Meta、不讀 Direct targets，輸出另建 immutable output root。
    本輪只做 preflight 與負例測試，沒有呼叫此函式讀取 fold-005。
    """

    effective_request = request or ConfirmatoryComparisonRequest(
        output_root=output_root
    )
    if effective_request.output_root.resolve() != output_root.resolve():
        raise ValueError("confirmatory request output_root mismatch")

    def _read_after_gate(
        gate: ConfirmatoryScopeGate,
        bound: ConfirmatoryBoundRequest,
    ) -> ConfirmatoryComparisonPublication:
        return _execute_confirmatory_comparison(
            gate=gate,
            bound=bound,
            request=effective_request,
        )

    return run_authorized_confirmatory_read(
        receipt_path,
        source_reader=_read_after_gate,
    )


def _execute_confirmatory_comparison(
    *,
    gate: ConfirmatoryScopeGate,
    bound: ConfirmatoryBoundRequest,
    request: ConfirmatoryComparisonRequest,
) -> ConfirmatoryComparisonPublication:
    """gate 後執行 fold-005 read-only comparison；不接受未綁定 source path。"""

    parent_path = bound.parent_training_manifest_path
    store_path = bound.parent_store_manifest_path
    parent = comparison._read_json_mapping(parent_path)
    if comparison._verify_logical_hash(parent, "manifest_hash") != (
        bound.parent_training_manifest_hash
    ):
        raise ConfirmatoryFreezeGateError(
            "parent training manifest changed after confirmatory authorization"
        )
    store_manifest = comparison._read_json_mapping(store_path)
    if comparison._verify_logical_hash(store_manifest, "manifest_hash") != (
        bound.parent_store_manifest_hash
    ):
        raise ConfirmatoryFreezeGateError(
            "parent store manifest changed after confirmatory authorization"
        )
    if parent.get("store_manifest_hash") != bound.parent_store_manifest_hash:
        raise ConfirmatoryFreezeGateError(
            "parent store lineage changed after confirmatory authorization"
        )
    if comparison._file_sha256(store_path) != (
        bound.parent_store_manifest_file_hash
    ):
        raise ConfirmatoryFreezeGateError(
            "parent store manifest file changed after confirmatory authorization"
        )
    if gate.parent_training_manifest_path != parent_path:
        raise ConfirmatoryFreezeGateError(
            "authorized parent path does not match bound request"
        )
    comparison._reject_source_output_overlap(
        parent_path,
        store_path,
        request.output_root.resolve(),
    )
    engine_request = _engine_request(bound, request)
    capacity = comparison._capacity_preflight(
        engine_request,
        source_path=store_path,
        output_root=request.output_root.resolve(),
        stage="confirmatory_comparison_preflight",
    )
    run_id = _confirmatory_run_id(bound, request)
    comparison_path = (
        request.output_root.resolve() / "runs" / run_id / "comparison.json"
    )
    latest_pointer_path = (
        request.output_root.resolve() / "latest_comparison.json"
    )
    lock_path = bound.heavy_lock_path
    reservation = acquire_heavy_chain_reservation(lock_path)
    if reservation is None:
        raise StorageCapacityError(
            "confirmatory comparison heavy-chain reservation unavailable",
            preflight={
                "stage": "confirmatory_comparison_lock",
                "lock_path": str(lock_path.resolve()),
                "blockers": ["heavy_chain_reservation_unavailable"],
            },
    )
    try:
        # 先在 shared heavy lock 內重檢既有 exposure/出版物，避免兩個
        # process 同時看見「尚無 receipt」後各自打開 fold-005 source。
        try:
            existing = _load_existing_confirmatory(
                comparison_path,
                latest_pointer_path,
                bound=bound,
            )
        except ValueError:
            # 失敗 publish 可能只留下半個 comparison；若有 outcome，
            # 優先回報既有 exposure，而不是把它當成新的 source attempt。
            existing_exposure = _load_existing_exposure(
                gate=gate,
                bound=bound,
                output_root=request.output_root,
                run_id=run_id,
            )
            if existing_exposure is None:
                raise
            exposure, exposure_path = existing_exposure
            saved_root = exposure.get("output_root")
            root_note = (
                " output_root cannot be changed for this frozen request."
                if saved_root != str(request.output_root.resolve())
                else ""
            )
            raise ConfirmatoryComparisonExecutionError(
                "confirmatory exposure already exists; source read is blocked."
                + root_note,
                exposure=exposure,
                exposure_receipt_path=exposure_path,
            )
        if existing is not None:
            return ConfirmatoryComparisonPublication(
                comparison_path=comparison_path,
                comparison_hash=comparison._required_sha256(
                    existing.get("comparison_hash"),
                    "comparison_hash",
                ),
                latest_pointer_path=latest_pointer_path,
                run_id=run_id,
                output_size_bytes=comparison.directory_size_bytes(
                    request.output_root.resolve()
                ),
                capacity_preflight=capacity,
                idempotent=True,
            )
        existing_exposure = _load_existing_exposure(
            gate=gate,
            bound=bound,
            output_root=request.output_root,
            run_id=run_id,
        )
        if existing_exposure is not None:
            exposure, exposure_path = existing_exposure
            saved_root = exposure.get("output_root")
            root_note = (
                " output_root cannot be changed for this frozen request."
                if saved_root != str(request.output_root.resolve())
                else ""
            )
            raise ConfirmatoryComparisonExecutionError(
                "confirmatory exposure already exists; source read is blocked."
                + root_note,
                exposure=exposure,
                exposure_receipt_path=exposure_path,
            )
        capacity = comparison._capacity_preflight(
            engine_request,
            source_path=store_path,
            output_root=request.output_root.resolve(),
            stage="confirmatory_comparison_locked_recheck",
        )
        _confirmatory_exposure_started_receipt(
            output_root=request.output_root,
            run_id=run_id,
            gate=gate,
            bound=bound,
        )
        source_read_completed = False
        outcome_written = False
        # 這個 phase 之後既可能部分讀取 future source，也可能已完成讀取；
        # 失敗時必須保存 unknown/true exposure，不能一律回報 false。
        try:
            payload = comparison._build_comparison_payload(
                request=engine_request,
                parent=parent,
                parent_path=parent_path,
                parent_hash=bound.parent_training_manifest_hash,
                store_path=store_path,
                store_manifest=store_manifest,
                store_hash=bound.parent_store_manifest_hash,
                run_id=run_id,
                capacity=capacity,
            )
            source_read_completed = True
            payload = _confirmatory_payload(
                payload,
                gate=gate,
                bound=bound,
            )
            published = comparison._publish_comparison(
                payload,
                comparison_path=comparison_path,
                latest_pointer_path=latest_pointer_path,
                output_root=request.output_root.resolve(),
                capacity=capacity,
                request=engine_request,
            )
            _confirmatory_exposure_receipt(
                output_root=request.output_root,
                run_id=run_id,
                gate=gate,
                bound=bound,
                source_read_completed=True,
                phase="published_after_confirmatory_source_read",
                error=None,
                status="source_read_completed_published",
            )
            outcome_written = True
            return ConfirmatoryComparisonPublication(
                comparison_path=published.comparison_path,
                comparison_hash=published.comparison_hash,
                latest_pointer_path=published.latest_pointer_path,
                run_id=published.run_id,
                output_size_bytes=published.output_size_bytes,
                capacity_preflight=published.capacity_preflight,
                idempotent=published.idempotent,
            )
        except Exception as exc:
            if outcome_written:
                raise
            exposure, exposure_receipt_path = _confirmatory_exposure_receipt(
                output_root=request.output_root,
                run_id=run_id,
                gate=gate,
                bound=bound,
                source_read_completed=source_read_completed,
                phase=(
                    "publish_after_source_read"
                    if source_read_completed
                    else "confirmatory_source_read"
                ),
                error=exc,
            )
            raise ConfirmatoryComparisonExecutionError(
                "confirmatory comparison failed after source phase; "
                f"exposure receipt={exposure_receipt_path}",
                exposure=exposure,
                exposure_receipt_path=exposure_receipt_path,
            ) from exc
    finally:
        release_heavy_chain_reservation(reservation)


def _engine_request(
    bound: ConfirmatoryBoundRequest,
    request: ConfirmatoryComparisonRequest,
) -> _EngineConfirmatoryComparisonRequest:
    """把 user options 與 gate 綁定的 immutable parent path 合成 engine request。"""

    for field_name in (
        "batch_size",
        "memory_budget_mb",
        "persistent_new_bytes_budget",
        "temporary_peak_bytes_budget",
        "safety_reserve_bytes",
    ):
        if getattr(request, field_name) != getattr(bound, field_name):
            raise ConfirmatoryFreezeGateError(
                "confirmatory execution request does not match frozen registration"
            )
    return _EngineConfirmatoryComparisonRequest(
        parent_training_manifest_path=bound.parent_training_manifest_path,
        output_root=request.output_root.resolve(),
        fold_id=request.fold_id,
        horizon=request.horizon,
        algorithms=request.algorithms,
        pack_ids=request.pack_ids,
        batch_size=request.batch_size,
        memory_budget_mb=request.memory_budget_mb,
        persistent_new_bytes_budget=request.persistent_new_bytes_budget,
        temporary_peak_bytes_budget=request.temporary_peak_bytes_budget,
        safety_reserve_bytes=request.safety_reserve_bytes,
        heavy_lock_path=bound.heavy_lock_path,
        acquire_heavy_lock=request.acquire_heavy_lock,
    )


def _confirmatory_payload(
    payload: Mapping[str, Any],
    *,
    gate: ConfirmatoryScopeGate,
    bound: ConfirmatoryBoundRequest,
) -> dict[str, Any]:
    result = dict(payload)
    result.pop("comparison_hash", None)
    result["schema_version"] = (
        "allocation-base-expert-confirmatory-comparison.v1"
    )
    result["status"] = "complete_confirmatory_research"
    result["confirmatory_binding"] = bound.as_dict()
    result["confirmatory_scope"] = {
        "fold_id": bound.fold_id,
        "classification": "confirmatory_oos_read_after_frozen_gate",
        "status": "read_research_only",
        "price_data_read": True,
        "label_data_read": True,
        "result_data_read": True,
        "source_readonly": True,
        "gate_status": gate.as_dict()["status"],
    }
    result["method_freeze"] = {
        "method_freeze_version": bound.method_freeze_version,
        "method_freeze_hash": bound.method_freeze_hash,
        "policy_hash": bound.policy_hash,
        "exploratory_comparison_hash": bound.comparison_hash,
        "future_request_hash": bound.request_hash,
        "parent_input_hashes": {
            "parent_training_manifest_hash": (
                bound.parent_training_manifest_hash
            ),
            "parent_store_manifest_hash": bound.parent_store_manifest_hash,
        },
        "request_binding_hash": bound.binding_hash,
    }
    result["future_confirmatory_scopes"] = []
    result["formal_oos_allowed"] = False
    result["production_alpha_bp"] = 0
    result["broker_order_allowed"] = False
    result["research_only"] = True
    result["source_readonly"] = True
    result["comparison_hash"] = comparison._payload_hash(result)
    return result


def _confirmatory_run_id(
    bound: ConfirmatoryBoundRequest,
    request: ConfirmatoryComparisonRequest,
) -> str:
    return "confirmatory-compare-" + comparison._payload_hash(
        {
            "schema_version": "allocation-base-expert-confirmatory-comparison.v1",
            "binding_hash": bound.binding_hash,
            "fold_id": request.fold_id,
            "horizon": request.horizon,
            "algorithms": list(request.algorithms),
            "batch_size": request.batch_size,
            "memory_budget_mb": request.memory_budget_mb,
        }
    )[7:31]


def _load_existing_confirmatory(
    comparison_path: Path,
    latest_pointer_path: Path,
    *,
    bound: ConfirmatoryBoundRequest,
) -> Mapping[str, Any] | None:
    if not comparison_path.exists():
        if latest_pointer_path.exists():
            raise ValueError(
                "latest confirmatory comparison pointer exists without run"
            )
        return None
    existing = comparison._read_json_mapping(comparison_path)
    if existing.get("confirmatory_binding") != bound.as_dict():
        raise ValueError("existing confirmatory binding mismatch")
    comparison._verify_logical_hash(existing, "comparison_hash")
    if existing.get("fold_id") != bound.fold_id:
        raise ValueError("existing confirmatory fold mismatch")
    if not latest_pointer_path.exists():
        raise ValueError("existing confirmatory run is missing latest pointer")
    pointer = comparison._read_json_mapping(latest_pointer_path)
    if pointer.get("comparison_hash") != existing.get("comparison_hash"):
        raise ValueError("existing confirmatory pointer mismatch")
    return existing


__all__ = [
    "ConfirmatoryBoundRequest",
    "ConfirmatoryComparisonPublication",
    "ConfirmatoryComparisonRequest",
    "ConfirmatoryComparisonExecutionError",
    "build_confirmatory_bound_request",
    "preflight_confirmatory_comparison",
    "run_confirmatory_comparison",
    "run_authorized_confirmatory_read",
]
