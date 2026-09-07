"""ML 全鏈的唯讀容量預算與 fail-closed preflight。

本模組只讀取檔案系統使用量與受控輸出目錄大小，不建立、刪除或修改任何
資料檔案。容量政策把一個長時間 ML chain 拆成三個可審核的整數 bytes
預算：本次持久新增上限、暫存峰值上限，以及執行後必須保留的安全空間。

    ``None`` 表示呼叫端尚未提供該項上限；為了維持舊 API，未設定的上限不會
自行猜一個持久／暫存限制，但仍會依已知估算檢查安全保留與可用空間。
核心計算只使用整數 bytes。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence


BYTES_PER_GIB = 1024**3
DEFAULT_SAFETY_RESERVE_BYTES = 20 * BYTES_PER_GIB


class StorageCapacityError(RuntimeError):
    """容量政策不允許繼續執行；呼叫端應保留 checkpoint 後停止。"""

    def __init__(self, message: str, *, preflight: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.preflight = dict(preflight)


class StorageCapacityPreflightError(StorageCapacityError):
    """唯讀容量 preflight 未通過。"""


class StorageCapacityExceededError(StorageCapacityError):
    """執行中的已觀測使用量超過容量預算。"""


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
    persistent_new_bytes_estimate: int
    persistent_new_bytes_budget: int | None
    temporary_peak_bytes_observed: int
    temporary_peak_bytes_budget: int | None
    safety_reserve_bytes: int
    required_free_bytes: int
    within_persistent_budget: bool
    within_temporary_budget: bool
    within_safety_reserve: bool
    within_headroom: bool
    within_budget: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


def directory_size_bytes(path: Path) -> int:
    """以唯讀方式計算目錄內一般檔案大小。

    不追蹤 symlink 目標，避免容量估算因輸出目錄外部的檔案而失真；找不
    到的路徑視為 0 bytes，因為 wrapper 在正式建立前常只收到尚未存在的
    output path。
    """

    resolved = Path(path)
    if resolved.is_symlink():
        return 0
    if not resolved.exists():
        return 0
    if resolved.is_file():
        try:
            return int(resolved.stat().st_size)
        except OSError as exc:
            raise StorageCapacityPreflightError(
                f"cannot stat capacity path: {resolved}",
                preflight={"path": str(resolved), "error_type": type(exc).__name__},
            ) from exc
    total = 0
    try:
        for root, directories, files in os.walk(
            resolved,
            topdown=True,
            followlinks=False,
        ):
            directories[:] = [
                name
                for name in directories
                if not (Path(root) / name).is_symlink()
            ]
            for name in files:
                file_path = Path(root) / name
                if file_path.is_symlink():
                    continue
                try:
                    total += int(file_path.stat().st_size)
                except FileNotFoundError:
                    # A concurrent atomic replace can remove a file between
                    # walk and stat. The next checkpoint measures it again.
                    continue
                except OSError as exc:
                    raise StorageCapacityPreflightError(
                        f"cannot stat capacity path: {file_path}",
                        preflight={
                            "path": str(file_path),
                            "error_type": type(exc).__name__,
                        },
                    ) from exc
    except OSError as exc:
        raise StorageCapacityPreflightError(
            f"cannot inspect capacity path: {resolved}",
            preflight={"path": str(resolved), "error_type": type(exc).__name__},
        ) from exc
    return total


def filesystem_usage(path: Path) -> dict[str, int | str]:
    """讀取 path 所在 filesystem 使用量，不產生任何檔案。"""

    probe_path = path if path.exists() else path.parent
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


def evaluate_capacity(
    *,
    budget: MLStorageCapacityBudget,
    usage: Mapping[str, Any],
    stage: str = "preflight",
    persistent_existing_bytes: int = 0,
    persistent_new_bytes_estimate: int = 0,
    temporary_peak_bytes_observed: int = 0,
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
        persistent_budget is None
        or persistent_new_bytes_estimate <= persistent_budget
    )
    within_temporary = (
        temporary_budget is None
        or temporary_peak_bytes_observed <= temporary_budget
    )
    # 若呼叫端沒有設定上限，已知估算仍要納入執行前所需 headroom；有
    # 上限時則以整個上限預留，避免「估算剛好但實際峰值超過」耗盡安全空間。
    persistent_headroom = (
        persistent_budget
        if persistent_budget is not None
        else persistent_new_bytes_estimate
    )
    temporary_headroom = (
        temporary_budget
        if temporary_budget is not None
        else temporary_peak_bytes_observed
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
        blockers.append("persistent_new_bytes_budget_exceeded")
    if not within_temporary:
        blockers.append("temporary_peak_bytes_budget_exceeded")
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
    persistent_new_bytes_estimate: int = 0,
    temporary_roots: Sequence[Path] = (),
    temporary_peak_bytes_observed: int = 0,
) -> StorageCapacityPreflight:
    """執行一次唯讀 filesystem preflight，失敗時 fail-closed。"""

    usage = filesystem_usage(probe_path)
    persistent_existing = sum(
        directory_size_bytes(Path(root)) for root in persistent_roots
    )
    if (
        isinstance(temporary_peak_bytes_observed, bool)
        or not isinstance(temporary_peak_bytes_observed, int)
        or temporary_peak_bytes_observed < 0
    ):
        raise ValueError(
            "temporary_peak_bytes_observed must be non-negative integer"
        )
    observed_temporary = max(
        temporary_peak_bytes_observed,
        sum(directory_size_bytes(Path(root)) for root in temporary_roots),
    )
    result = evaluate_capacity(
        budget=budget,
        usage=usage,
        stage=stage,
        persistent_existing_bytes=persistent_existing,
        persistent_new_bytes_estimate=persistent_new_bytes_estimate,
        temporary_peak_bytes_observed=observed_temporary,
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
    "DEFAULT_SAFETY_RESERVE_BYTES",
    "MLStorageCapacityBudget",
    "StorageCapacityBudget",
    "StorageCapacityError",
    "StorageCapacityExceededError",
    "StorageCapacityPreflight",
    "StorageCapacityPreflightError",
    "directory_size_bytes",
    "evaluate_capacity",
    "filesystem_usage",
    "preflight_capacity",
    "run_capacity_preflight",
]
