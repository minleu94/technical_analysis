"""ML 全鏈的唯讀容量預算與 fail-closed preflight。

本模組只讀取檔案系統使用量與受控輸出目錄大小，不建立、刪除或修改任何
資料檔案。容量政策把一個長時間 ML chain 拆成三個可審核的整數 bytes
預算：本次持久新增上限、暫存峰值上限，以及執行後必須保留的安全空間。

    ``None`` 表示呼叫端尚未提供該項上限；為了維持舊 API，未設定的上限不會
自行猜一個持久／暫存限制，但仍會依已知估算檢查安全保留與可用空間。
核心計算只使用整數 bytes。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import tempfile
import threading
import time
from typing import Any, BinaryIO, Mapping, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - 僅 POSIX 提供
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - 僅 Windows 提供
    msvcrt = None  # type: ignore[assignment]


BYTES_PER_GIB = 1024**3

# 所有會建立長時間 ML 產物的入口都必須在同一磁碟保留至少 200 GiB。
# 這是執行後仍要存在的 safety reserve，不等同本次作業的 persistent/temp
# 新增上限；小型 fake filesystem 測試仍可直接使用 MLStorageCapacityBudget。
CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES = 200 * BYTES_PER_GIB
DEFAULT_HEAVY_PERSISTENT_NEW_BYTES_BUDGET = BYTES_PER_GIB
DEFAULT_HEAVY_TEMPORARY_PEAK_BYTES_BUDGET = BYTES_PER_GIB
DEFAULT_SAFETY_RESERVE_BYTES = CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES

# Scheduled raw 與 Direct/OOC chain 共用這組有界政策。scheduled wrapper
# 仍可使用較大的單次 persistent/temp 預算，但 safety reserve 不得降到
# 200 GiB 以下，避免舊的 125 GiB 參數形成安全漏洞。
SCHEDULED_SAFETY_RESERVE_BYTES = CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES
SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET = 35 * BYTES_PER_GIB
SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET = 40 * BYTES_PER_GIB
SCHEDULED_REQUIRED_FREE_BYTES = (
    SCHEDULED_SAFETY_RESERVE_BYTES
    + SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET
    + SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET
)
HEAVY_CHAIN_LOCK_FILENAME = ".ml_heavy_chain.lock"
HEAVY_CHAIN_RESERVATION_HELD_ENV = (
    "BALDR_ML_HEAVY_CHAIN_RESERVATION_HELD"
)
HEAVY_CHAIN_OWNER_METADATA_SUFFIX = ".owner.json"
HEAVY_CHAIN_OWNER_METADATA_SCHEMA = "ml-heavy-chain-reservation-owner.v1"
HEAVY_CHAIN_HANDOFF_SCHEMA = "ml-heavy-chain-reservation-handoff.v1"
HEAVY_CHAIN_HANDOFF_LOST_RETURN_CODE = 75
HEAVY_CHAIN_HANDOFF_GATE_PREFIX = ".handoff."
HEAVY_CHAIN_HANDOFF_GATE_SUFFIX = ".lock"
_HANDOFF_WATCHDOG_INTERVAL_SECONDS = 0.25
_HANDOFF_AUTHORIZATION_WAIT_SECONDS = 5.0


class StorageCapacityError(RuntimeError):
    """容量政策不允許繼續執行；呼叫端應保留 checkpoint 後停止。"""

    def __init__(self, message: str, *, preflight: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.preflight = dict(preflight)


class StorageCapacityPreflightError(StorageCapacityError):
    """唯讀容量 preflight 未通過。"""


class StorageCapacityExceededError(StorageCapacityError):
    """執行中的已觀測使用量超過容量預算。"""


def _owner_metadata_path(lock_path: Path) -> Path:
    return Path(f"{lock_path}{HEAVY_CHAIN_OWNER_METADATA_SUFFIX}")


def _normalised_path(path: Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` on Windows can continue to report a joined
        # multiprocessing PID as alive for a short interval.  psutil asks
        # the process table directly and avoids reopening a released owner
        # reservation during that interval.
        try:
            import psutil
        except ImportError:  # pragma: no cover - dependency fallback
            psutil = None  # type: ignore[assignment]
        if psutil is not None:
            try:
                process = psutil.Process(pid)
                return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
            except psutil.AccessDenied:
                return True
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        # 權限不足不代表程序已死亡；這裡只做 custody liveness check。
        return True
    except (ProcessLookupError, OSError):
        return False
    return True


def _atomic_write_owner_metadata(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    temporary_path: Path | None = None
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _read_owner_metadata(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _new_handoff_gate_path(
    lock_path: Path,
    *,
    owner_nonce: str,
    parent_pid: int,
) -> Path:
    """建立本次 handoff 專用的 OS gate 路徑。

    gate 是實際由 child 持有的 advisory lock；每一層使用獨立檔案，讓
    continuation 可以在上一層仍持有 gate 時先取得下一層 gate。競爭者
    會掃描同一 canonical lock 旁的 gate 檔，因此不依賴 sidecar 是否仍
    能被讀到。
    """

    token = secrets.token_hex(16)
    return lock_path.with_name(
        f"{lock_path.name}{HEAVY_CHAIN_HANDOFF_GATE_PREFIX}"
        f"{owner_nonce}.{parent_pid}.{token}{HEAVY_CHAIN_HANDOFF_GATE_SUFFIX}"
    )


def _normalised_handoff_gate_path(lock_path: Path, raw_path: object) -> str:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise _handoff_error(
            lock_path,
            "invalid_reservation_handoff_gate",
            "ML heavy-chain handoff gate path is missing",
        )
    gate_path = Path(raw_path).resolve()
    expected_prefix = f"{lock_path.name}{HEAVY_CHAIN_HANDOFF_GATE_PREFIX}"
    if (
        gate_path.parent != lock_path.parent
        or not gate_path.name.startswith(expected_prefix)
        or not gate_path.name.endswith(HEAVY_CHAIN_HANDOFF_GATE_SUFFIX)
    ):
        raise _handoff_error(
            lock_path,
            "invalid_reservation_handoff_gate",
            "ML heavy-chain handoff gate must be beside the canonical lock",
        )
    return _normalised_path(gate_path)


def _open_locked_file(path: Path) -> BinaryIO | None:
    """以 process-safe advisory lock 開啟檔案；失敗時不留下 handle。"""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
    except OSError:
        return None
    try:
        _lock_handle(handle)
        if not _try_lock_handle(handle):
            handle.close()
            return None
    except OSError:
        try:
            handle.close()
        except OSError:
            pass
        return None
    return handle


def _probe_locked_file(path: Path) -> bool:
    """回傳 path 是否被另一 process 持有；probe 本身不保留 lock。"""

    try:
        handle = path.open("a+b")
    except OSError:
        # 無法判斷時採 fail-closed，避免把不可讀的 gate 當成空閒。
        return True
    try:
        if not _try_lock_handle(handle):
            return True
        _unlock_handle(handle)
        return False
    except OSError:
        return True
    finally:
        try:
            handle.close()
        except OSError:
            pass


def _handoff_gate_paths(lock_path: Path) -> tuple[Path, ...] | None:
    pattern = f"{lock_path.name}{HEAVY_CHAIN_HANDOFF_GATE_PREFIX}*{HEAVY_CHAIN_HANDOFF_GATE_SUFFIX}"
    try:
        return tuple(sorted(lock_path.parent.glob(pattern)))
    except OSError:
        return None


def _child_record_parent(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        # 相容早期只保存 parent PID 的 owner sidecar；新 handoff 不會
        # 再產生這種 record，但讀取舊 metadata 時仍須 fail closed。
        return value
    if not isinstance(value, Mapping):
        return None
    parent_pid = value.get("parent_pid")
    if isinstance(parent_pid, int) and not isinstance(parent_pid, bool) and parent_pid > 0:
        return parent_pid
    return None


def _child_record_gate_path(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    gate_path = value.get("gate_path")
    return gate_path if isinstance(gate_path, str) and gate_path else None


def _live_child_pids(metadata: Mapping[str, Any]) -> tuple[int, ...]:
    authorized_pids = metadata.get("authorized_child_pids")
    if not isinstance(authorized_pids, list):
        return ()
    return tuple(
        value
        for value in authorized_pids
        if isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
        and _process_is_alive(value)
    )


def _register_authorized_child(
    *,
    lock_path: Path,
    owner_pid: int,
    owner_nonce: str,
    child_pid: int,
    parent_pid: int,
    gate_path: str,
) -> None:
    """在 owner sidecar 內登記一個由已驗證 parent 建立的 child。

    登記與 owner metadata 的驗證集中在這個小 helper，讓 reservation owner
    與已 handoff 的 continuation 共用同一個 custody 規則。這不是 PID
    marker：child 只有在 nonce、canonical lock、owner liveness 與這個
    parent→child mapping 都吻合時才可消費 reservation。
    """

    metadata_path = _owner_metadata_path(lock_path)
    metadata = _read_owner_metadata(metadata_path)
    expected_lock = _normalised_path(lock_path)
    if (
        metadata is None
        or metadata.get("schema_version") != HEAVY_CHAIN_OWNER_METADATA_SCHEMA
        or metadata.get("lock_path") != expected_lock
        or metadata.get("owner_pid") != owner_pid
        or metadata.get("owner_nonce") != owner_nonce
    ):
        raise _handoff_error(
            lock_path,
            "reservation_owner_metadata_missing",
            "cannot authorize child without the active ML heavy-chain owner",
        )
    existing = metadata.get("authorized_child_pids", [])
    authorized_children = metadata.get("authorized_children", {})
    if not isinstance(existing, list) or not isinstance(authorized_children, dict):
        raise _handoff_error(
            lock_path,
            "invalid_reservation_child_custody",
            "ML heavy-chain owner metadata has invalid child custody",
        )
    children = [
        value
        for value in existing
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    if child_pid not in children:
        children.append(child_pid)
    child_records: dict[str, Any] = {}
    for key, value in authorized_children.items():
        if not isinstance(key, str):
            continue
        record_parent = _child_record_parent(value)
        if record_parent is None:
            continue
        if isinstance(value, Mapping):
            record = dict(value)
        else:
            record = {"parent_pid": record_parent}
        child_records[key] = record
    child_records[str(child_pid)] = {
        "parent_pid": parent_pid,
        "gate_path": gate_path,
        "state": "pending",
        "registered_at_ns": time.time_ns(),
    }
    updated = dict(metadata)
    updated["authorized_child_pids"] = sorted(children)
    updated["authorized_children"] = child_records
    _atomic_write_owner_metadata(metadata_path, updated)


def _reservation_owner_payload(
    *,
    lock_path: Path,
    owner_pid: int,
    owner_nonce: str,
) -> dict[str, Any]:
    return {
        "schema_version": HEAVY_CHAIN_OWNER_METADATA_SCHEMA,
        "lock_path": _normalised_path(lock_path),
        "owner_pid": owner_pid,
        "owner_nonce": owner_nonce,
        "created_at_ns": time.time_ns(),
        "owner_released": False,
        "authorized_child_pids": [],
        "authorized_children": {},
    }


class MLStorageChainReservation:
    """一條 scheduled ML heavy chain 的 process-safe reservation。

    Reservation 使用同一 filesystem 上的 OS advisory lock。lock file 本身
    固定保留，不依賴 PID 存活判定，也不做 stale rename；程序 crash 時由
    作業系統在 handle 關閉時自動釋放。Windows 使用 ``msvcrt.locking``，
    POSIX 使用 ``fcntl.flock``。
    """

    def __init__(self, path: Path, handle: BinaryIO, owner_nonce: str) -> None:
        self.path = path
        self._handle = handle
        self._owner_nonce = owner_nonce
        self._pending_handoff_gate_paths: list[str] = []
        self._released = False

    @property
    def owner_pid(self) -> int:
        return os.getpid()

    @property
    def owner_nonce(self) -> str:
        return self._owner_nonce

    @property
    def owner_metadata_path(self) -> Path:
        return _owner_metadata_path(self.path)

    def handoff_payload(self, *, parent_pid: int | None = None) -> dict[str, Any]:
        """建立只可由目前 reservation owner 傳出的 child custody payload。"""

        if self._released:
            raise StorageCapacityError(
                "cannot hand off a released ML heavy-chain reservation",
                preflight={
                    "lock_path": str(self.path),
                    "blocker": "reservation_released",
                },
            )
        effective_parent_pid = os.getpid() if parent_pid is None else parent_pid
        gate_path = _new_handoff_gate_path(
            self.path,
            owner_nonce=self.owner_nonce,
            parent_pid=effective_parent_pid,
        )
        gate_path_value = _normalised_path(gate_path)
        pending = getattr(self, "_pending_handoff_gate_paths", None)
        if pending is None:
            pending = []
            self._pending_handoff_gate_paths = pending
        pending.append(gate_path_value)
        return {
            "schema_version": HEAVY_CHAIN_HANDOFF_SCHEMA,
            "lock_path": _normalised_path(self.path),
            "owner_pid": self.owner_pid,
            "parent_pid": effective_parent_pid,
            "custody_parent_pid": effective_parent_pid,
            "owner_nonce": self.owner_nonce,
            "gate_path": gate_path_value,
        }

    def authorize_child(
        self,
        child_pid: int,
        *,
        gate_path: str | Path | None = None,
    ) -> None:
        """將已由本 reservation 建立的 child PID 綁入 owner sidecar。"""

        if isinstance(child_pid, bool) or not isinstance(child_pid, int) or child_pid <= 0:
            raise ValueError("child_pid must be a positive integer")
        pending = getattr(self, "_pending_handoff_gate_paths", [])
        if gate_path is None:
            if not pending:
                raise _handoff_error(
                    self.path,
                    "reservation_handoff_gate_missing",
                    "cannot authorize child without a generated handoff gate",
                )
            gate_path_value = str(pending.pop(0))
        else:
            gate_path_value = _normalised_handoff_gate_path(self.path, gate_path)
            try:
                pending.remove(gate_path_value)
            except ValueError:
                pass
        # Parent creates the gate path before Popen; this validation also
        # prevents an accidental gate on another volume from weakening the
        # canonical lock's custody.
        gate_path_value = _normalised_handoff_gate_path(
            self.path,
            gate_path_value,
        )
        _register_authorized_child(
            lock_path=self.path,
            owner_pid=self.owner_pid,
            owner_nonce=self.owner_nonce,
            child_pid=child_pid,
            parent_pid=os.getpid(),
            gate_path=gate_path_value,
        )

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            metadata = _read_owner_metadata(self.owner_metadata_path)
            if (
                metadata is not None
                and metadata.get("schema_version")
                == HEAVY_CHAIN_OWNER_METADATA_SCHEMA
                and metadata.get("lock_path") == _normalised_path(self.path)
                and metadata.get("owner_pid") == self.owner_pid
                and metadata.get("owner_nonce") == self.owner_nonce
            ):
                live_children = _live_child_pids(metadata)
                if live_children:
                    # 正常 owner release 也不能刪除仍在寫入的 child
                    # custody；canonical lock 釋放後由 child gate 與
                    # acquisition probe 持續阻擋其他 chain。
                    updated = dict(metadata)
                    updated["owner_released"] = True
                    _atomic_write_owner_metadata(
                        self.owner_metadata_path,
                        updated,
                    )
                else:
                    try:
                        self.owner_metadata_path.unlink()
                    except FileNotFoundError:
                        pass
            _unlock_handle(self._handle)
        finally:
            try:
                self._handle.close()
            except OSError:
                pass

    def __enter__(self) -> "MLStorageChainReservation":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.release()


# 名稱較短的相容別名，供 wrapper 與測試使用。
StorageCapacityReservation = MLStorageChainReservation


def _lock_handle(handle: BinaryIO) -> None:
    """在 lock file 尚無內容時寫入固定 marker，不寫 owner identity。"""

    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"ml_heavy_chain_lock.v1\r\n")
        handle.flush()
    handle.seek(0)


def _try_lock_handle(handle: BinaryIO) -> bool:
    if os.name == "nt":
        if msvcrt is None:  # pragma: no cover - 平台防禦分支
            return False
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    if fcntl is None:  # pragma: no cover - 平台防禦分支
        return False
    flock = getattr(fcntl, "flock", None)
    lock_ex = getattr(fcntl, "LOCK_EX", None)
    lock_nb = getattr(fcntl, "LOCK_NB", None)
    if not callable(flock) or not isinstance(lock_ex, int) or not isinstance(
        lock_nb, int
    ):
        return False
    try:
        flock(handle.fileno(), lock_ex | lock_nb)
    except OSError:
        return False
    return True


def _unlock_handle(handle: BinaryIO) -> None:
    if os.name == "nt":
        if msvcrt is None:  # pragma: no cover - 平台防禦分支
            return
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    if fcntl is None:  # pragma: no cover - 平台防禦分支
        return
    flock = getattr(fcntl, "flock", None)
    lock_un = getattr(fcntl, "LOCK_UN", None)
    if not callable(flock) or not isinstance(lock_un, int):
        return
    try:
        flock(handle.fileno(), lock_un)
    except OSError:
        pass


def acquire_heavy_chain_reservation(
    lock_path: Path,
) -> MLStorageChainReservation | None:
    """嘗試取得跨 raw／Direct/OOC 的 process-safe heavy-chain lock。

    這個函式只能在 execution path 呼叫，preflight-only 不應呼叫。lock
    檔案會穩定保留，競爭中的 caller 由 OS lock 回傳 ``None``；不讀 PID、
    不刪除 lock、也不嘗試自行回收 stale lock。
    """

    path = Path(lock_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageCapacityError(
            f"cannot prepare ML heavy-chain lock directory: {path.parent}",
            preflight={"lock_path": str(path), "error_type": type(exc).__name__},
        ) from exc

    try:
        handle = path.open("a+b")
    except OSError as exc:
        raise StorageCapacityError(
            f"cannot open ML heavy-chain lock: {path}",
            preflight={"lock_path": str(path), "error_type": type(exc).__name__},
        ) from exc
    owner_nonce = secrets.token_urlsafe(32)
    try:
        _lock_handle(handle)
        if not _try_lock_handle(handle):
            handle.close()
            return None
        if not _cleanup_handoff_state_before_new_owner(path):
            # A previous child may still hold its handoff gate after the
            # parent process released the canonical OS lock.  Never hand the
            # canonical lock to a new writer during that transition.
            _unlock_handle(handle)
            handle.close()
            return None
        _atomic_write_owner_metadata(
            _owner_metadata_path(path),
            _reservation_owner_payload(
                lock_path=path,
                owner_pid=os.getpid(),
                owner_nonce=owner_nonce,
            ),
        )
    except OSError as exc:
        try:
            _unlock_handle(handle)
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass
        raise StorageCapacityError(
            f"cannot prepare ML heavy-chain lock: {path}",
            preflight={"lock_path": str(path), "error_type": type(exc).__name__},
        ) from exc
    return MLStorageChainReservation(path, handle, owner_nonce)


def release_heavy_chain_reservation(
    reservation: MLStorageChainReservation | None,
) -> None:
    """釋放 reservation；``None`` 是未取得 lock 的相容 no-op。"""

    if reservation is not None:
        reservation.release()


def heavy_chain_lock_path(release_root: Path) -> Path:
    """由 release root 統一產生 raw／Direct/OOC 共用 lock 路徑。"""

    return Path(release_root).resolve() / HEAVY_CHAIN_LOCK_FILENAME


def resolve_heavy_chain_lock_path(
    output_path: Path,
    *,
    explicit_path: Path | None = None,
) -> Path | None:
    """解析 production output 對應的 canonical heavy-chain lock。

    正式輸出必須位於名為 ``release_v4`` 的 release root 之下；若 caller
    另外傳入 lock path，必須與該 root 推導出的路徑完全一致，避免不同
    caller 各自建立互斥檔。純 fixture 若沒有 release root 可回傳 ``None``，
    讓單元測試不需建立 production custody 目錄。
    """

    resolved_output = Path(output_path).resolve()
    release_root: Path | None = None
    for candidate in (resolved_output, *resolved_output.parents):
        if candidate.name.casefold() == "release_v4":
            release_root = candidate
            break
    canonical = (
        None if release_root is None else heavy_chain_lock_path(release_root)
    )
    if explicit_path is not None:
        explicit = Path(explicit_path).resolve()
        if canonical is not None and explicit != canonical:
            raise ValueError(
                "explicit heavy-chain lock must match the canonical "
                f"release_v4 lock: {canonical}"
            )
        return explicit
    return canonical


def _handoff_error(lock_path: Path, blocker: str, message: str) -> StorageCapacityError:
    return StorageCapacityError(
        message,
        preflight={
            "lock_path": str(lock_path),
            "blocker": blocker,
            "handoff_verified": False,
        },
    )


def _matching_owner_metadata(
    lock_path: Path,
    metadata: Mapping[str, Any] | None,
    *,
    owner_pid: int,
    owner_nonce: str,
) -> bool:
    return bool(
        metadata is not None
        and metadata.get("schema_version") == HEAVY_CHAIN_OWNER_METADATA_SCHEMA
        and metadata.get("lock_path") == _normalised_path(lock_path)
        and metadata.get("owner_pid") == owner_pid
        and metadata.get("owner_nonce") == owner_nonce
    )


def _iter_child_records(
    metadata: Mapping[str, Any],
) -> tuple[tuple[int, Mapping[str, Any] | int], ...]:
    authorized_pids = metadata.get("authorized_child_pids")
    authorized_children = metadata.get("authorized_children")
    if not isinstance(authorized_pids, list) or not isinstance(
        authorized_children, Mapping
    ):
        return ()
    records: list[tuple[int, Mapping[str, Any] | int]] = []
    for value in authorized_pids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            continue
        record = authorized_children.get(str(value))
        if isinstance(record, Mapping):
            records.append((value, dict(record)))
        elif isinstance(record, int) and not isinstance(record, bool) and record > 0:
            records.append((value, record))
    return tuple(records)


def _handoff_registered_child_pid(
    metadata: Mapping[str, Any],
    *,
    parent_pid: int,
    current_pid: int | None = None,
) -> int | None:
    current = os.getpid() if current_pid is None else current_pid
    immediate_parent = os.getppid()
    for child_pid, record in _iter_child_records(metadata):
        if _child_record_parent(record) != parent_pid:
            continue
        if child_pid == current or (
            immediate_parent != current and child_pid == immediate_parent
        ):
            return child_pid
    return None


def _mark_handoff_gate_active(
    *,
    lock_path: Path,
    owner_pid: int,
    owner_nonce: str,
    child_pid: int,
    gate_path: str,
    expected_parent_pid: int,
) -> None:
    metadata_path = _owner_metadata_path(lock_path)
    metadata = _read_owner_metadata(metadata_path)
    if not _matching_owner_metadata(
        lock_path,
        metadata,
        owner_pid=owner_pid,
        owner_nonce=owner_nonce,
    ):
        raise _handoff_error(
            lock_path,
            "reservation_handoff_owner_metadata_mismatch",
            "cannot activate a handoff without the active owner metadata",
        )
    if metadata is None:
        raise _handoff_error(
            lock_path,
            "reservation_handoff_owner_metadata_mismatch",
            "cannot activate a handoff without the active owner metadata",
        )
    records = metadata.get("authorized_children")
    if not isinstance(records, dict):
        raise _handoff_error(
            lock_path,
            "invalid_reservation_child_custody",
            "ML heavy-chain owner metadata has invalid child custody",
        )
    record = records.get(str(child_pid))
    if (
        not isinstance(record, Mapping)
        or _child_record_parent(record) != expected_parent_pid
    ):
        # The registered PID can be a Windows launcher while this process is
        # its interpreter.  ``expected_parent_pid`` is the handoff custody
        # parent, while the interpreter's immediate parent can be the
        # launcher PID.
        raise _handoff_error(
            lock_path,
            "invalid_reservation_child_custody",
            "ML heavy-chain child custody changed before gate activation",
        )
    updated_record = dict(record)
    updated_record["gate_path"] = gate_path
    updated_record["state"] = "active"
    updated_record["gate_owner_pid"] = os.getpid()
    updated_record["activated_at_ns"] = time.time_ns()
    updated_metadata = dict(metadata)
    updated_records = dict(records)
    updated_records[str(child_pid)] = updated_record
    updated_metadata["authorized_children"] = updated_records
    _atomic_write_owner_metadata(metadata_path, updated_metadata)


def _remove_handoff_child(
    *,
    lock_path: Path,
    owner_pid: int,
    owner_nonce: str,
    child_pid: int,
) -> None:
    metadata_path = _owner_metadata_path(lock_path)
    metadata = _read_owner_metadata(metadata_path)
    if not _matching_owner_metadata(
        lock_path,
        metadata,
        owner_pid=owner_pid,
        owner_nonce=owner_nonce,
    ) or metadata is None:
        return
    records = metadata.get("authorized_children")
    if not isinstance(records, dict):
        return
    updated_records = dict(records)
    updated_records.pop(str(child_pid), None)
    updated = dict(metadata)
    updated["authorized_children"] = updated_records
    updated["authorized_child_pids"] = sorted(
        value
        for value in metadata.get("authorized_child_pids", [])
        if isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
        and value != child_pid
    )
    owner_released = bool(metadata.get("owner_released", False))
    if not updated["authorized_child_pids"] and (
        owner_released or not _process_is_alive(owner_pid)
    ):
        try:
            metadata_path.unlink()
        except FileNotFoundError:
            pass
        return
    _atomic_write_owner_metadata(metadata_path, updated)


def _cleanup_handoff_state_before_new_owner(lock_path: Path) -> bool:
    """canonical lock 取得後檢查上一層 child custody 與實際 gate。

    回傳 False 時 caller 必須立即釋放 canonical lock。sidecar 只用來
    覆蓋 child 尚未完成 gate activation 的 transition；已啟動 writer 的
    互斥由同目錄 gate 的 OS advisory lock 再次保護。
    """

    metadata_path = _owner_metadata_path(lock_path)
    metadata = _read_owner_metadata(metadata_path)
    if metadata is not None:
        if (
            metadata.get("schema_version") != HEAVY_CHAIN_OWNER_METADATA_SCHEMA
            or metadata.get("lock_path") != _normalised_path(lock_path)
        ):
            # 不可解讀的 owner metadata 不可被新 owner 覆寫。
            return False
        live_children = _live_child_pids(metadata)
        if live_children:
            return False
        owner_pid = metadata.get("owner_pid")
        owner_released = bool(metadata.get("owner_released", False))
        if (
            isinstance(owner_pid, int)
            and not isinstance(owner_pid, bool)
            and owner_pid > 0
            and _process_is_alive(owner_pid)
            and not owner_released
        ):
            # canonical OS lock 已可取得但 sidecar 仍宣稱 owner active；
            # fail closed，避免雙 writer。
            return False
        try:
            metadata_path.unlink()
        except FileNotFoundError:
            pass

    gate_paths = _handoff_gate_paths(lock_path)
    if gate_paths is None:
        return False
    # 這個掃描是 sidecar 之外的實際互斥證據；即使 metadata 被刪除，
    # 仍不能在 child 持有 gate 時取得新的 chain。
    return not any(_probe_locked_file(path) for path in gate_paths)


def _handoff_child_is_authorized(
    metadata: Mapping[str, Any],
    *,
    parent_pid: int,
    current_pid: int | None = None,
) -> bool:
    """判斷 current process 是否由 sidecar 登記的 parent 建立。

    Windows 的 Python launcher 可能讓 ``Popen.pid`` 成為中介 process，
    而實際 Python interpreter 的 ``os.getppid()`` 是該中介 PID。sidecar
    仍登記 parent 取得的 Popen PID；因此同時接受「自身 PID」及「立即
    parent PID」兩種已登記形式。兩者都必須綁定同一個 handoff parent，
    不接受任意祖先或只有環境變數的 PID。
    """

    authorized_children = metadata.get("authorized_children")
    authorized_pids = metadata.get("authorized_child_pids")
    if not isinstance(authorized_children, Mapping) or not isinstance(
        authorized_pids, list
    ):
        return False
    current = os.getpid() if current_pid is None else current_pid
    allowed = {
        value
        for value in authorized_pids
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }

    def _matches(pid: int) -> bool:
        return (
            pid in allowed
            and _child_record_parent(authorized_children.get(str(pid)))
            == parent_pid
        )

    if _matches(current):
        return True
    # Windows launcher bridge: the interpreter's immediate parent is the
    # registered Popen process. On POSIX this falls back to the normal direct
    # child path above and is harmless.
    immediate_parent = os.getppid()
    return immediate_parent != current and _matches(immediate_parent)


def _validate_handoff_payload(
    *,
    lock_path: Path,
    payload: Mapping[str, Any],
    require_immediate_parent: bool = False,
    require_child_authorized: bool = True,
) -> dict[str, Any]:
    expected_lock = _normalised_path(lock_path)
    if payload.get("schema_version") != HEAVY_CHAIN_HANDOFF_SCHEMA:
        raise _handoff_error(
            lock_path,
            "invalid_reservation_handoff_schema",
            "ML heavy-chain handoff schema is missing or unsupported",
        )
    if payload.get("lock_path") != expected_lock:
        raise _handoff_error(
            lock_path,
            "reservation_handoff_lock_mismatch",
            "ML heavy-chain handoff does not bind the canonical lock path",
        )
    for field_name in ("owner_pid", "parent_pid"):
        value = payload.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _handoff_error(
                lock_path,
                "invalid_reservation_handoff_owner",
                f"ML heavy-chain handoff {field_name} is invalid",
            )
    owner_nonce = payload.get("owner_nonce")
    if not isinstance(owner_nonce, str) or len(owner_nonce) < 32:
        raise _handoff_error(
            lock_path,
            "invalid_reservation_handoff_nonce",
            "ML heavy-chain handoff owner nonce is invalid",
        )
    gate_path = _normalised_handoff_gate_path(
        lock_path,
        payload.get("gate_path"),
    )
    if require_immediate_parent and payload["parent_pid"] != os.getppid():
        raise _handoff_error(
            lock_path,
            "reservation_handoff_parent_mismatch",
            "ML heavy-chain handoff parent is not the spawning process",
        )
    owner_pid = int(payload["owner_pid"])
    parent_pid = int(payload["parent_pid"])
    custody_parent_pid_value = payload.get("custody_parent_pid", parent_pid)
    if (
        isinstance(custody_parent_pid_value, bool)
        or not isinstance(custody_parent_pid_value, int)
        or custody_parent_pid_value <= 0
    ):
        raise _handoff_error(
            lock_path,
            "invalid_reservation_handoff_owner",
            "ML heavy-chain handoff custody parent is invalid",
        )
    custody_parent_pid = int(custody_parent_pid_value)
    if not _process_is_alive(owner_pid) or not _process_is_alive(parent_pid):
        raise _handoff_error(
            lock_path,
            "reservation_handoff_owner_not_alive",
            "ML heavy-chain handoff owner is not alive",
        )
    metadata = _read_owner_metadata(_owner_metadata_path(lock_path))
    if (
        metadata is None
        or metadata.get("schema_version") != HEAVY_CHAIN_OWNER_METADATA_SCHEMA
        or metadata.get("lock_path") != expected_lock
        or metadata.get("owner_pid") != owner_pid
        or metadata.get("owner_nonce") != owner_nonce
    ):
        raise _handoff_error(
            lock_path,
            "reservation_handoff_owner_metadata_mismatch",
            "ML heavy-chain handoff has no matching active reservation owner",
        )
    authorized_children = metadata.get("authorized_children")
    authorized_pids = metadata.get("authorized_child_pids")
    if not isinstance(authorized_children, dict) or not isinstance(
        authorized_pids, list
    ):
        raise _handoff_error(
            lock_path,
            "invalid_reservation_child_custody",
            "ML heavy-chain owner metadata has no child custody map",
        )
    if require_child_authorized:
        if not _handoff_child_is_authorized(
            metadata,
            parent_pid=custody_parent_pid,
        ):
            raise _handoff_error(
                lock_path,
                "reservation_handoff_child_not_authorized",
                "ML heavy-chain handoff child was not registered by its parent",
            )
        registered_child_pid = _handoff_registered_child_pid(
            metadata,
            parent_pid=custody_parent_pid,
        )
        if registered_child_pid is None:
            raise _handoff_error(
                lock_path,
                "reservation_handoff_child_not_authorized",
                "ML heavy-chain handoff child was not registered by its parent",
            )
        record = metadata.get("authorized_children", {}).get(
            str(registered_child_pid),
        )
        registered_gate_path = _child_record_gate_path(record)
        if registered_gate_path != gate_path:
            raise _handoff_error(
                lock_path,
                "reservation_handoff_gate_mismatch",
                "ML heavy-chain handoff gate does not match owner custody",
            )
    validated = dict(payload)
    validated["gate_path"] = gate_path
    validated["custody_parent_pid"] = custody_parent_pid
    return validated


class MLStorageChainReservationHandoff:
    """已驗證的 parent→child reservation lease。

    child 不以可偽造的環境變數作為鎖證據；它會驗證 owner sidecar、
    canonical path、實際 spawning parent 與 owner liveness。watchdog 在
    owner 或 immediate parent 消失、或 sidecar 被撤銷時終止 child，避免
    child 在 reservation 失效後繼續寫入。
    """

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)
        self.lock_path = Path(str(self.payload["lock_path"])).resolve()
        self.owner_pid = int(self.payload["owner_pid"])
        self.parent_pid = int(self.payload["parent_pid"])
        self.gate_path = Path(str(self.payload["gate_path"])).resolve()
        self.custody_parent_pid = int(
            self.payload.get("custody_parent_pid", self.parent_pid)
        )
        gate_handle = _open_locked_file(self.gate_path)
        if gate_handle is None:
            raise _handoff_error(
                self.lock_path,
                "reservation_handoff_gate_unavailable",
                "ML heavy-chain handoff child could not acquire its OS gate",
            )
        metadata = _read_owner_metadata(_owner_metadata_path(self.lock_path))
        registered_child_pid = (
            None
            if metadata is None
            else _handoff_registered_child_pid(
                metadata,
                parent_pid=self.custody_parent_pid,
            )
        )
        if registered_child_pid is None:
            _unlock_handle(gate_handle)
            gate_handle.close()
            raise _handoff_error(
                self.lock_path,
                "reservation_handoff_child_not_authorized",
                "ML heavy-chain handoff child was not registered by its parent",
            )
        try:
            _mark_handoff_gate_active(
                lock_path=self.lock_path,
                owner_pid=self.owner_pid,
                owner_nonce=str(self.payload["owner_nonce"]),
                child_pid=registered_child_pid,
                gate_path=_normalised_path(self.gate_path),
                expected_parent_pid=self.custody_parent_pid,
            )
        except Exception:
            _unlock_handle(gate_handle)
            gate_handle.close()
            raise
        self._gate_handle = gate_handle
        self._registered_child_pid = registered_child_pid
        self._stop_event = threading.Event()
        self._watchdog = threading.Thread(
            target=self._watch_owner,
            name="ml-heavy-chain-handoff-watchdog",
            daemon=True,
        )
        self._watchdog.start()

    def _watch_owner(self) -> None:
        while not self._stop_event.wait(_HANDOFF_WATCHDOG_INTERVAL_SECONDS):
            if not _process_is_alive(self.owner_pid) or not _process_is_alive(
                self.parent_pid
            ):
                os._exit(HEAVY_CHAIN_HANDOFF_LOST_RETURN_CODE)
            metadata = _read_owner_metadata(
                _owner_metadata_path(self.lock_path)
            )
            if (
                metadata is None
                or metadata.get("schema_version")
                != HEAVY_CHAIN_OWNER_METADATA_SCHEMA
                or metadata.get("lock_path") != _normalised_path(self.lock_path)
                or metadata.get("owner_pid") != self.owner_pid
                or metadata.get("owner_nonce")
                != self.payload.get("owner_nonce")
            ):
                os._exit(HEAVY_CHAIN_HANDOFF_LOST_RETURN_CODE)
            if not _handoff_child_is_authorized(
                metadata,
                parent_pid=self.parent_pid,
            ):
                os._exit(HEAVY_CHAIN_HANDOFF_LOST_RETURN_CODE)

    def close(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        try:
            _remove_handoff_child(
                lock_path=self.lock_path,
                owner_pid=self.owner_pid,
                owner_nonce=str(self.payload["owner_nonce"]),
                child_pid=self._registered_child_pid,
            )
        finally:
            _unlock_handle(self._gate_handle)
            try:
                self._gate_handle.close()
            except OSError:
                pass
            try:
                self.gate_path.unlink()
            except OSError:
                # On Windows a concurrent probe may briefly retain its file
                # handle; the unlocked stable gate is harmless and can be
                # reused/cleaned by a later acquisition.
                pass


def validate_heavy_chain_reservation_handoff(
    lock_path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> MLStorageChainReservationHandoff | None:
    """驗證 child 收到的 reservation handoff；舊 marker 一律拒絕。

    沒有該環境變數表示 caller 是獨立 execution boundary，回傳 ``None``
    由 caller 自行取得 lock。若存在但不是完整 handoff，則 fail closed。
    """

    env = os.environ if environment is None else environment
    raw = env.get(HEAVY_CHAIN_RESERVATION_HELD_ENV)
    if raw is None:
        return None
    if raw.strip() == "1":
        raise _handoff_error(
            lock_path,
            "legacy_reservation_marker_rejected",
            "legacy ML heavy-chain reservation marker cannot bypass the lock",
        )
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise _handoff_error(
            lock_path,
            "invalid_reservation_handoff_payload",
            "ML heavy-chain reservation handoff is not valid JSON",
        ) from exc
    if not isinstance(decoded, Mapping):
        raise _handoff_error(
            lock_path,
            "invalid_reservation_handoff_payload",
            "ML heavy-chain reservation handoff must be an object",
        )
    deadline = time.monotonic() + _HANDOFF_AUTHORIZATION_WAIT_SECONDS
    while True:
        try:
            payload = _validate_handoff_payload(lock_path=lock_path, payload=decoded)
            return MLStorageChainReservationHandoff(payload)
        except StorageCapacityError as exc:
            # Popen 回傳 child PID 後，parent 才能把 PID 寫入 owner sidecar；
            # child 可能先於該 atomic update 啟動。只對「尚未登記 child」
            # 做短暫重試，其他 custody/schema 錯誤仍立即 fail closed。
            blocker = exc.preflight.get("blocker")
            if (
                blocker
                not in {
                    "reservation_handoff_child_not_authorized",
                    "reservation_handoff_gate_unavailable",
                }
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(0.01)


def authorize_heavy_chain_reservation_handoff_child(
    child_pid: int,
    *,
    environment: Mapping[str, str] | None = None,
) -> None:
    """由已驗證 continuation parent 登記下一層 child PID。

    這個 API 必須在 ``Popen`` 之後、child 進入重型 builder 前呼叫。它
    重新驗證目前 process 的 handoff custody，再以 owner nonce 與 canonical
    lock path 更新 sidecar；裸 marker、偽造 payload、未被上一層登記的
    parent 都無法註冊 child。
    """

    if isinstance(child_pid, bool) or not isinstance(child_pid, int) or child_pid <= 0:
        raise ValueError("child_pid must be a positive integer")
    env = os.environ if environment is None else environment
    raw = env.get(HEAVY_CHAIN_RESERVATION_HELD_ENV)
    if raw is None:
        raise _handoff_error(
            Path("."),
            "reservation_handoff_missing",
            "cannot authorize child without an ML heavy-chain handoff",
        )
    if raw.strip() == "1":
        raise _handoff_error(
            Path("."),
            "legacy_reservation_marker_rejected",
            "legacy ML heavy-chain reservation marker cannot authorize a child",
        )
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise _handoff_error(
            Path("."),
            "invalid_reservation_handoff_payload",
            "ML heavy-chain handoff is not valid JSON",
        ) from exc
    if not isinstance(decoded, Mapping):
        raise _handoff_error(
            Path("."),
            "invalid_reservation_handoff_payload",
            "ML heavy-chain handoff must be an object",
        )
    raw_lock_path = decoded.get("lock_path")
    if not isinstance(raw_lock_path, str) or not raw_lock_path.strip():
        raise _handoff_error(
            Path("."),
            "reservation_handoff_lock_mismatch",
            "ML heavy-chain handoff does not contain a lock path",
        )
    lock_path = Path(raw_lock_path).resolve()
    source_custody_parent = decoded.get("source_custody_parent_pid")
    source_gate_path = decoded.get("source_gate_path")
    if source_custody_parent is not None or source_gate_path is not None:
        if (
            isinstance(source_custody_parent, bool)
            or not isinstance(source_custody_parent, int)
            or source_custody_parent <= 0
            or not isinstance(source_gate_path, str)
        ):
            raise _handoff_error(
                lock_path,
                "invalid_reservation_handoff_source",
                "ML heavy-chain child handoff source custody is invalid",
            )
        current_payload = dict(decoded)
        current_payload["custody_parent_pid"] = source_custody_parent
        current_payload["gate_path"] = source_gate_path
        _validate_handoff_payload(
            lock_path=lock_path,
            payload=current_payload,
        )
        payload = _validate_handoff_payload(
            lock_path=lock_path,
            payload=decoded,
            require_child_authorized=False,
        )
    else:
        payload = _validate_handoff_payload(
            lock_path=lock_path,
            payload=decoded,
            require_child_authorized=False,
        )
    target_gate_path = _normalised_handoff_gate_path(
        lock_path,
        payload.get("gate_path"),
    )
    if payload.get("custody_parent_pid") != os.getpid():
        raise _handoff_error(
            lock_path,
            "reservation_handoff_parent_mismatch",
            "ML heavy-chain next child custody parent is not this process",
        )
    _register_authorized_child(
        lock_path=lock_path,
        owner_pid=int(payload["owner_pid"]),
        owner_nonce=str(payload["owner_nonce"]),
        child_pid=child_pid,
        parent_pid=os.getpid(),
        gate_path=target_gate_path,
    )


def build_heavy_chain_reservation_handoff_environment(
    reservation: MLStorageChainReservation,
    *,
    environment: Mapping[str, str] | None = None,
    parent_pid: int | None = None,
) -> dict[str, str]:
    """由真正持有 reservation 的 parent 建立 child 環境。"""

    output = dict(os.environ if environment is None else environment)
    payload = reservation.handoff_payload(parent_pid=parent_pid)
    output[HEAVY_CHAIN_RESERVATION_HELD_ENV] = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return output


def forward_heavy_chain_reservation_handoff_environment(
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """已驗證 child 將同一 lease 傳給自己的受控 child。

    forwarding 前重新核對 owner sidecar 與目前 parent 關係；因此單純
    複製環境變數、殘留 marker 或改寫 parent PID 都不能繞過 reservation。
    """

    output = dict(os.environ if environment is None else environment)
    raw = output.get(HEAVY_CHAIN_RESERVATION_HELD_ENV)
    if raw is None:
        return output
    if raw.strip() == "1":
        raise _handoff_error(
            Path("."),
            "legacy_reservation_marker_rejected",
            "legacy ML heavy-chain reservation marker cannot be forwarded",
        )
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise StorageCapacityError(
            "ML heavy-chain reservation handoff is not valid JSON",
            preflight={
                "blocker": "invalid_reservation_handoff_payload",
                "handoff_verified": False,
            },
        ) from exc
    if not isinstance(decoded, Mapping):
        raise StorageCapacityError(
            "ML heavy-chain reservation handoff must be an object",
            preflight={
                "blocker": "invalid_reservation_handoff_payload",
                "handoff_verified": False,
            },
        )
    payload = _validate_handoff_payload(
        lock_path=Path(str(decoded.get("lock_path", "."))),
        payload=decoded,
    )
    source_custody_parent_pid = int(
        payload.get("custody_parent_pid", payload.get("parent_pid", os.getppid()))
    )
    source_gate_path = str(payload["gate_path"])
    payload["parent_pid"] = os.getpid()
    payload["custody_parent_pid"] = os.getpid()
    payload["source_custody_parent_pid"] = source_custody_parent_pid
    payload["source_gate_path"] = source_gate_path
    payload["gate_path"] = _normalised_path(
        _new_handoff_gate_path(
            Path(str(payload["lock_path"])),
            owner_nonce=str(payload["owner_nonce"]),
            parent_pid=os.getpid(),
        )
    )
    output[HEAVY_CHAIN_RESERVATION_HELD_ENV] = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return output


def scheduled_default_capacity_budget() -> "MLStorageCapacityBudget":
    """回傳正式 scheduled raw／Direct/OOC 的 bounded 預設政策。"""

    return MLStorageCapacityBudget(
        persistent_new_bytes_budget=SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET,
        temporary_peak_bytes_budget=SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET,
        safety_reserve_bytes=SCHEDULED_SAFETY_RESERVE_BYTES,
    )


@dataclass(frozen=True)
class MLStorageCapacityBudget:
    """一條 ML chain 的三段式容量政策。

    ``persistent_new_bytes_budget`` 與 ``temporary_peak_bytes_budget`` 是
    上限；``safety_reserve_bytes`` 是執行後仍須留在檔案系統上的空間。
    所有值均為 bytes。為相容舊的 only-headroom 呼叫，兩個上限可為
    ``None``。
    """

    persistent_new_bytes_budget: int | None = None
    temporary_peak_bytes_budget: int | None = None
    safety_reserve_bytes: int = DEFAULT_SAFETY_RESERVE_BYTES

    def __post_init__(self) -> None:
        for field_name in (
            "persistent_new_bytes_budget",
            "temporary_peak_bytes_budget",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer or None")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        value = self.safety_reserve_bytes
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("safety_reserve_bytes must be integer")
        if value <= 0:
            raise ValueError("safety_reserve_bytes must be positive")

    @property
    def persistent_storage_budget_bytes(self) -> int | None:
        """相容性別名：持久新增 bytes 上限。"""

        return self.persistent_new_bytes_budget

    @property
    def temporary_storage_budget_bytes(self) -> int | None:
        """相容性別名：暫存峰值 bytes 上限。"""

        return self.temporary_peak_bytes_budget

    def as_dict(self) -> dict[str, int | None]:
        payload = asdict(self)
        # 寫入 manifest/status 時同時提供易讀的舊命名，讓 operator 不必
        # 依賴 DTO 的 Python 類別才能解讀容量政策。
        payload["persistent_storage_budget_bytes"] = (
            self.persistent_new_bytes_budget
        )
        payload["temporary_storage_budget_bytes"] = (
            self.temporary_peak_bytes_budget
        )
        return payload


def resolve_heavy_chain_safety_reserve(
    value: int | None,
    *,
    field_name: str = "safety_reserve_bytes",
) -> int:
    """解析 heavy chain safety reserve，拒絕低於中央政策的值。

    ``None`` 只代表採用中央 200 GiB 政策；它不再代表可以沿用舊的
    20/125 GiB wrapper 預設。一般容量純計算測試仍可直接建立較小的
    ``MLStorageCapacityBudget``，但正式 heavy caller 必須經過本入口。
    """

    resolved = (
        CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES
        if value is None
        else value
    )
    if isinstance(resolved, bool) or not isinstance(resolved, int):
        raise TypeError(f"{field_name} must be integer or None")
    if resolved < CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES:
        raise ValueError(
            f"{field_name} must be at least "
            f"{CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES} bytes "
            "for a heavy ML chain"
        )
    return resolved


def heavy_chain_capacity_budget(
    *,
    persistent_new_bytes_budget: int | None = None,
    temporary_peak_bytes_budget: int | None = None,
    safety_reserve_bytes: int | None = None,
) -> MLStorageCapacityBudget:
    """建立所有正式 heavy caller 共用的 bounded 容量預算。

    未提供的 persistent/temp 上限各採 1 GiB；safety reserve 採中央
    200 GiB 並拒絕更小的顯式值。這個解析層與可接受小數值的純計算
    ``MLStorageCapacityBudget`` 分離，保留測試和舊 read-only API 相容性。
    """

    persistent = (
        DEFAULT_HEAVY_PERSISTENT_NEW_BYTES_BUDGET
        if persistent_new_bytes_budget is None
        else persistent_new_bytes_budget
    )
    temporary = (
        DEFAULT_HEAVY_TEMPORARY_PEAK_BYTES_BUDGET
        if temporary_peak_bytes_budget is None
        else temporary_peak_bytes_budget
    )
    for field_name, candidate in (
        ("persistent_new_bytes_budget", persistent),
        ("temporary_peak_bytes_budget", temporary),
    ):
        if isinstance(candidate, bool) or not isinstance(candidate, int):
            raise TypeError(f"{field_name} must be integer or None")
        if candidate <= 0:
            raise ValueError(f"{field_name} must be positive")
    return MLStorageCapacityBudget(
        persistent_new_bytes_budget=persistent,
        temporary_peak_bytes_budget=temporary,
        safety_reserve_bytes=resolve_heavy_chain_safety_reserve(
            safety_reserve_bytes
        ),
    )


# 簡短別名供 wrapper 與外部 read-only 工具使用；canonical class 仍保留
# ``ML`` 前綴以免和其他檔案處理容量政策混淆。
StorageCapacityBudget = MLStorageCapacityBudget


@dataclass(frozen=True)
class StorageCapacityPreflight:
    """一次容量檢查的可序列化結果。"""

    stage: str
    probe_path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    persistent_existing_bytes: int
    persistent_new_bytes_estimate: int | None
    persistent_new_bytes_budget: int | None
    temporary_peak_bytes_observed: int | None
    temporary_peak_bytes_budget: int | None
    safety_reserve_bytes: int
    required_free_bytes: int
    within_persistent_budget: bool
    within_temporary_budget: bool
    within_safety_reserve: bool
    within_headroom: bool
    within_budget: bool
    blockers: tuple[str, ...]
    # 同一條 chain 可能把輸出與暫存放在不同磁碟；保留每個 filesystem
    # 的唯讀檢查結果，避免只以 probe_path 所在磁碟代表全部用量。
    filesystem_checks: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["filesystem_checks"] = [
            dict(item) for item in self.filesystem_checks
        ]
        return payload


def _capacity_inspection_error(path: Path, exc: OSError) -> StorageCapacityPreflightError:
    return StorageCapacityPreflightError(
        f"cannot inspect capacity path: {path}",
        preflight={"path": str(path), "error_type": type(exc).__name__},
    )


def _stat_is_reparse_point(stat_result: os.stat_result) -> bool:
    """以 Windows lstat attributes 辨識 junction／其他 reparse point。"""

    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    attributes = int(getattr(stat_result, "st_file_attributes", 0))
    return bool(attributes & reparse_flag)


def _path_is_junction(path: Path, stat_result: os.stat_result | None = None) -> bool:
    """檢查 Windows junction；無新 API 的 Python 版本也以 lstat 辨識。"""

    checker = getattr(path, "is_junction", None)
    if callable(checker):
        try:
            if bool(checker()):
                return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _capacity_inspection_error(path, exc) from exc
    checker = getattr(os.path, "isjunction", None)
    if callable(checker):
        try:
            if bool(checker(path)):
                return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _capacity_inspection_error(path, exc) from exc
    if stat_result is None:
        try:
            stat_result = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _capacity_inspection_error(path, exc) from exc
    # Windows Python 3.11 已提供 st_file_attributes/st_reparse_tag，但
    # Path.is_junction 要到 Python 3.12 才加入；跳過所有 reparse point
    # 是保守作法，可避免跟隨未知 mount。
    return _stat_is_reparse_point(stat_result)


def _directory_size_from_scandir(directory: Path) -> int:
    total = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                child = Path(entry.path)
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(entry_stat.st_mode) or _path_is_junction(
                        child, entry_stat
                    ):
                        continue
                    if stat.S_ISDIR(entry_stat.st_mode):
                        total += _directory_size_from_scandir(child)
                    elif stat.S_ISREG(entry_stat.st_mode):
                        total += int(entry_stat.st_size)
                except FileNotFoundError:
                    # atomic replace 或 cleanup 可能在 scandir 與 stat 之間
                    # 移除 child；下次 checkpoint 會重新量測。
                    continue
                except OSError as exc:
                    raise _capacity_inspection_error(child, exc) from exc
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise _capacity_inspection_error(directory, exc) from exc
    return total


def directory_size_bytes(path: Path) -> int:
    """以唯讀方式計算目錄內一般檔案大小。

    不追蹤 symlink 或 Windows junction 目標，避免容量估算因輸出目錄外部
    的檔案而失真；找不到的路徑視為 0 bytes，因為 wrapper 在正式建立前
    常只收到尚未存在的 output path。任何目錄列舉／metadata 權限錯誤都
    轉成 ``StorageCapacityPreflightError``，不可靜默當成 0 bytes。
    """

    resolved = Path(path)
    try:
        root_stat = os.lstat(resolved)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise _capacity_inspection_error(resolved, exc) from exc
    if stat.S_ISLNK(root_stat.st_mode) or _path_is_junction(
        resolved, root_stat
    ):
        return 0
    if stat.S_ISREG(root_stat.st_mode):
        return int(root_stat.st_size)
    if not stat.S_ISDIR(root_stat.st_mode):
        return 0
    return _directory_size_from_scandir(resolved)


def _nearest_existing_path(path: Path) -> Path:
    """找出可供 disk_usage/stat 使用的最近既存祖先。"""

    candidate = Path(path)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return candidate


def _filesystem_identity(path: Path) -> str:
    """取得穩定的 filesystem 群組鍵，不能因目錄尚未建立而失敗。"""

    existing = _nearest_existing_path(path)
    try:
        device = int(existing.stat().st_dev)
    except OSError as exc:
        raise _capacity_inspection_error(existing, exc) from exc
    # Windows 的 drive 可避免不同 mount 在 st_dev 表示上被合併；POSIX
    # 沒有 drive 時仍以 st_dev 分組。
    drive = existing.drive.casefold()
    return f"{drive}:{device}"


def filesystem_usage(path: Path) -> dict[str, int | str]:
    """讀取 path 所在 filesystem 使用量，不產生任何檔案。"""

    probe_path = _nearest_existing_path(path)
    try:
        usage = shutil.disk_usage(probe_path)
    except OSError as exc:
        raise StorageCapacityPreflightError(
            f"cannot read filesystem usage: {probe_path}",
            preflight={"probe_path": str(probe_path), "error_type": type(exc).__name__},
        ) from exc
    return {
        "probe_path": str(probe_path),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": int(usage.free),
    }


def normalise_capacity_usage(
    usage: Mapping[str, Any],
) -> dict[str, int | str]:
    """補齊舊 wrapper 回傳的 usage 欄位並完成整數驗證。"""

    free_bytes = _required_usage_int(usage, "free_bytes")
    used_value = usage.get("used_bytes", 0)
    if isinstance(used_value, bool) or not isinstance(used_value, int):
        raise TypeError("usage.used_bytes must be integer")
    used_bytes = used_value
    total_value = usage.get("total_bytes", free_bytes + used_bytes)
    if isinstance(total_value, bool) or not isinstance(total_value, int):
        raise TypeError("usage.total_bytes must be integer")
    if free_bytes < 0 or used_bytes < 0 or total_value < 0:
        raise ValueError("filesystem usage values must be non-negative")
    return {
        "probe_path": str(usage.get("probe_path", "")),
        "total_bytes": total_value,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
    }


def evaluate_capacity(
    *,
    budget: MLStorageCapacityBudget,
    usage: Mapping[str, Any],
    stage: str = "preflight",
    persistent_existing_bytes: int = 0,
    persistent_new_bytes_estimate: int | None = 0,
    temporary_peak_bytes_observed: int | None = 0,
) -> StorageCapacityPreflight:
    """依已取得的 filesystem usage 計算容量政策結果。

    這個純計算入口讓測試與 scheduled wrapper 可以重用同一套 contract，
    也避免測試為了模擬低容量而建立或刪除大量檔案。
    """

    for field_name in (
        "persistent_existing_bytes",
        "persistent_new_bytes_estimate",
        "temporary_peak_bytes_observed",
    ):
        value = locals()[field_name]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be non-negative integer")
    total_bytes = _required_usage_int(usage, "total_bytes")
    used_bytes = _required_usage_int(usage, "used_bytes")
    free_bytes = _required_usage_int(usage, "free_bytes")
    probe_path = str(usage.get("probe_path", ""))
    if total_bytes < 0 or used_bytes < 0 or free_bytes < 0:
        raise ValueError("filesystem usage values must be non-negative")

    persistent_budget = budget.persistent_new_bytes_budget
    temporary_budget = budget.temporary_peak_bytes_budget
    within_persistent = (
        persistent_new_bytes_estimate is not None
        and (
            persistent_budget is None
            or persistent_new_bytes_estimate <= persistent_budget
        )
    )
    within_temporary = (
        temporary_peak_bytes_observed is not None
        and (
            temporary_budget is None
            or temporary_peak_bytes_observed <= temporary_budget
        )
    )
    # 若呼叫端沒有設定上限，已知估算仍要納入執行前所需 headroom；有
    # 上限時則以整個上限預留，避免「估算剛好但實際峰值超過」耗盡安全空間。
    persistent_headroom = (
        persistent_budget
        if persistent_budget is not None
        else (
            0
            if persistent_new_bytes_estimate is None
            else persistent_new_bytes_estimate
        )
    )
    temporary_headroom = (
        temporary_budget
        if temporary_budget is not None
        else (
            0
            if temporary_peak_bytes_observed is None
            else temporary_peak_bytes_observed
        )
    )
    required_free = (
        budget.safety_reserve_bytes
        + persistent_headroom
        + temporary_headroom
    )
    within_safety = free_bytes >= budget.safety_reserve_bytes
    within_headroom = free_bytes >= required_free
    blockers: list[str] = []
    if not within_persistent:
        blockers.append(
            "persistent_new_bytes_estimate_unknown"
            if persistent_new_bytes_estimate is None
            else "persistent_new_bytes_budget_exceeded"
        )
    if not within_temporary:
        blockers.append(
            "temporary_peak_bytes_estimate_unknown"
            if temporary_peak_bytes_observed is None
            else "temporary_peak_bytes_budget_exceeded"
        )
    if not within_safety:
        blockers.append("safety_reserve_unavailable")
    if not within_headroom:
        blockers.append("required_free_headroom_unavailable")
    return StorageCapacityPreflight(
        stage=str(stage),
        probe_path=probe_path,
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        free_bytes=free_bytes,
        persistent_existing_bytes=persistent_existing_bytes,
        persistent_new_bytes_estimate=persistent_new_bytes_estimate,
        persistent_new_bytes_budget=persistent_budget,
        temporary_peak_bytes_observed=temporary_peak_bytes_observed,
        temporary_peak_bytes_budget=temporary_budget,
        safety_reserve_bytes=budget.safety_reserve_bytes,
        required_free_bytes=required_free,
        within_persistent_budget=within_persistent,
        within_temporary_budget=within_temporary,
        within_safety_reserve=within_safety,
        within_headroom=within_headroom,
        within_budget=(
            within_persistent
            and within_temporary
            and within_safety
            and within_headroom
        ),
        blockers=tuple(blockers),
    )


def preflight_capacity(
    *,
    probe_path: Path,
    budget: MLStorageCapacityBudget,
    stage: str = "preflight",
    persistent_roots: Sequence[Path] = (),
    persistent_new_bytes_estimate: int | None = 0,
    temporary_roots: Sequence[Path] = (),
    temporary_peak_bytes_observed: int | None = 0,
) -> StorageCapacityPreflight:
    """執行一次唯讀 filesystem preflight，失敗時 fail-closed。

    輸出、持久新增與暫存根目錄若位於不同 filesystem，會分組逐一檢查；
    每組都必須保留 safety reserve，且對應的新增／暫存上限會在寫入前
    預留。這避免只檢查 output probe 所在磁碟而漏算異磁碟 TEMP。
    """

    persistent_paths = tuple(Path(root) for root in persistent_roots)
    temporary_paths = tuple(Path(root) for root in temporary_roots)
    group_paths: dict[str, dict[str, Any]] = {}

    def add_path(path: Path, kind: str) -> None:
        key = _filesystem_identity(path)
        group = group_paths.setdefault(
            key,
            {"representative": _nearest_existing_path(path), "persistent": [], "temporary": []},
        )
        group[kind].append(path)

    probe_path_obj = Path(probe_path)
    probe_key = _filesystem_identity(probe_path_obj)
    group_paths.setdefault(
        probe_key,
        {
            "representative": _nearest_existing_path(probe_path_obj),
            "persistent": [],
            "temporary": [],
        },
    )["is_probe"] = True
    for root in persistent_paths:
        add_path(root, "persistent")
    for root in temporary_paths:
        add_path(root, "temporary")

    if temporary_peak_bytes_observed is not None and (
        isinstance(temporary_peak_bytes_observed, bool)
        or not isinstance(temporary_peak_bytes_observed, int)
        or temporary_peak_bytes_observed < 0
    ):
        raise ValueError(
            "temporary_peak_bytes_observed must be non-negative integer"
        )

    # 先以全 chain 的估算檢查 global persistent/temp quota。分盤檢查若
    # 只把 estimate 分攤到各盤，會讓兩個各 0.6 GiB 的暫存根目錄錯誤地
    # 通過 1 GiB 上限，因此 aggregate 檢查不可省略。
    persistent_existing_total = sum(
        directory_size_bytes(root) for root in persistent_paths
    )
    temporary_existing_total = sum(
        directory_size_bytes(root) for root in temporary_paths
    )
    aggregate_temporary_observed = temporary_peak_bytes_observed
    if aggregate_temporary_observed is not None:
        aggregate_temporary_observed = max(
            aggregate_temporary_observed,
            temporary_existing_total,
        )
    probe_usage = filesystem_usage(probe_path_obj)
    aggregate = evaluate_capacity(
        budget=budget,
        usage=probe_usage,
        stage=stage,
        persistent_existing_bytes=persistent_existing_total,
        persistent_new_bytes_estimate=persistent_new_bytes_estimate,
        temporary_peak_bytes_observed=aggregate_temporary_observed,
    )

    checked: list[dict[str, Any]] = []
    results: dict[str, StorageCapacityPreflight] = {}
    for key, group in group_paths.items():
        group_persistent = list(group["persistent"])
        group_temporary = list(group["temporary"])
        persistent_assigned = bool(group_persistent) if persistent_paths else (
            key == probe_key
        )
        temporary_assigned = bool(group_temporary) if temporary_paths else (
            key == probe_key
        )
        persistent_existing = sum(
            directory_size_bytes(root) for root in group_persistent
        )
        temporary_size = sum(
            directory_size_bytes(root) for root in group_temporary
        )
        if persistent_paths:
            # ``persistent_new_bytes_estimate`` is a chain-level upper bound,
            # not an estimate for the probe filesystem.  Once the actual
            # persistent root is known, charge the bound to every filesystem
            # that can receive a persistent root.  Charging the full bound
            # per destination is intentionally conservative when a chain has
            # multiple persistent filesystems: without a per-root allocation
            # contract, allowing either destination to spend the estimate
            # would let the post-run safety reserve be breached.
            group_persistent_estimate = (
                persistent_new_bytes_estimate
                if group_persistent
                else 0
            )
        else:
            group_persistent_estimate = (
                persistent_new_bytes_estimate
                if key == probe_key
                else 0
            )
        if temporary_paths:
            group_temporary_observed: int | None = temporary_size
        elif key == probe_key:
            group_temporary_observed = aggregate_temporary_observed
        else:
            group_temporary_observed = 0
        group_budget = MLStorageCapacityBudget(
            persistent_new_bytes_budget=(
                budget.persistent_new_bytes_budget
                if persistent_assigned
                else 0
            ),
            temporary_peak_bytes_budget=(
                budget.temporary_peak_bytes_budget
                if temporary_assigned
                else 0
            ),
            safety_reserve_bytes=budget.safety_reserve_bytes,
        )
        usage = (
            probe_usage
            if key == probe_key
            else filesystem_usage(Path(group["representative"]))
        )
        result = evaluate_capacity(
            budget=group_budget,
            usage=usage,
            stage=stage,
            persistent_existing_bytes=persistent_existing,
            persistent_new_bytes_estimate=group_persistent_estimate,
            temporary_peak_bytes_observed=group_temporary_observed,
        )
        results[key] = result
        checked.append(
            {
                "filesystem_key": key,
                "is_probe_filesystem": key == probe_key,
                "representative_path": str(group["representative"]),
                "persistent_roots": [str(root) for root in group_persistent],
                "temporary_roots": [str(root) for root in group_temporary],
                **result.as_dict(),
            }
        )

    primary = results[probe_key]
    # aggregate 的 quota 結果負責全 chain 總量；每盤結果負責 safety 和
    # 依該盤實際 root 配置的 headroom。兩者都通過才可繼續。
    aggregate_blockers = tuple(
        blocker
        for blocker in aggregate.blockers
        if blocker
        in {
            "persistent_new_bytes_estimate_unknown",
            "persistent_new_bytes_budget_exceeded",
            "temporary_peak_bytes_estimate_unknown",
            "temporary_peak_bytes_budget_exceeded",
        }
    )
    group_safety_ok = all(item.within_safety_reserve for item in results.values())
    group_headroom_ok = all(item.within_headroom for item in results.values())
    all_within_budget = (
        aggregate.within_persistent_budget
        and aggregate.within_temporary_budget
        and group_safety_ok
        and group_headroom_ok
        and all(item.within_budget for item in results.values())
    )
    blockers: list[str] = []
    for blocker in aggregate_blockers:
        if blocker not in blockers:
            blockers.append(blocker)
    for key, item in results.items():
        for blocker in item.blockers:
            if blocker in {
                "persistent_new_bytes_estimate_unknown",
                "persistent_new_bytes_budget_exceeded",
                "temporary_peak_bytes_estimate_unknown",
                "temporary_peak_bytes_budget_exceeded",
            }:
                continue
            decorated = (
                blocker if key == probe_key else f"filesystem:{key}:{blocker}"
            )
            if decorated not in blockers:
                blockers.append(decorated)
    result = replace(
        primary,
        persistent_existing_bytes=persistent_existing_total,
        persistent_new_bytes_estimate=persistent_new_bytes_estimate,
        persistent_new_bytes_budget=budget.persistent_new_bytes_budget,
        temporary_peak_bytes_observed=aggregate_temporary_observed,
        temporary_peak_bytes_budget=budget.temporary_peak_bytes_budget,
        within_persistent_budget=aggregate.within_persistent_budget,
        within_temporary_budget=aggregate.within_temporary_budget,
        within_safety_reserve=group_safety_ok,
        within_headroom=group_headroom_ok,
        within_budget=all_within_budget,
        blockers=tuple(blockers),
        filesystem_checks=tuple(checked),
    )
    if not result.within_budget:
        raise StorageCapacityExceededError(
            "ML storage capacity preflight failed at "
            f"{stage}: {', '.join(result.blockers)}; "
            f"free={result.free_bytes}, required={result.required_free_bytes}",
            preflight=result.as_dict(),
        )
    return result


# 讓呼叫端以語意名稱取用同一個入口。
run_capacity_preflight = preflight_capacity


def _required_usage_int(usage: Mapping[str, Any], field_name: str) -> int:
    value = usage.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"usage.{field_name} must be integer")
    return value


__all__ = [
    "BYTES_PER_GIB",
    "CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES",
    "DEFAULT_HEAVY_PERSISTENT_NEW_BYTES_BUDGET",
    "DEFAULT_HEAVY_TEMPORARY_PEAK_BYTES_BUDGET",
    "DEFAULT_SAFETY_RESERVE_BYTES",
    "HEAVY_CHAIN_HANDOFF_GATE_PREFIX",
    "HEAVY_CHAIN_HANDOFF_GATE_SUFFIX",
    "HEAVY_CHAIN_LOCK_FILENAME",
    "HEAVY_CHAIN_HANDOFF_LOST_RETURN_CODE",
    "HEAVY_CHAIN_HANDOFF_SCHEMA",
    "HEAVY_CHAIN_OWNER_METADATA_SCHEMA",
    "HEAVY_CHAIN_OWNER_METADATA_SUFFIX",
    "HEAVY_CHAIN_RESERVATION_HELD_ENV",
    "MLStorageCapacityBudget",
    "MLStorageChainReservation",
    "MLStorageChainReservationHandoff",
    "SCHEDULED_PERSISTENT_NEW_BYTES_BUDGET",
    "SCHEDULED_REQUIRED_FREE_BYTES",
    "SCHEDULED_SAFETY_RESERVE_BYTES",
    "SCHEDULED_TEMPORARY_PEAK_BYTES_BUDGET",
    "StorageCapacityBudget",
    "StorageCapacityError",
    "StorageCapacityExceededError",
    "StorageCapacityPreflight",
    "StorageCapacityPreflightError",
    "StorageCapacityReservation",
    "acquire_heavy_chain_reservation",
    "authorize_heavy_chain_reservation_handoff_child",
    "build_heavy_chain_reservation_handoff_environment",
    "directory_size_bytes",
    "evaluate_capacity",
    "filesystem_usage",
    "forward_heavy_chain_reservation_handoff_environment",
    "heavy_chain_capacity_budget",
    "heavy_chain_lock_path",
    "resolve_heavy_chain_lock_path",
    "normalise_capacity_usage",
    "preflight_capacity",
    "release_heavy_chain_reservation",
    "resolve_heavy_chain_safety_reserve",
    "validate_heavy_chain_reservation_handoff",
    "run_capacity_preflight",
    "scheduled_default_capacity_budget",
]
