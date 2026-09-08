"""ML release 的中立載入器註冊契約。

ML producer 只能依賴這個窄契約，不能反向 import ``app_module``。實際的
hash 驗證與 inference service 仍由 application release adapter 提供；adapter
在載入時註冊自己的 callable。若 application boundary 尚未啟動，這裡會
fail-closed，而不是猜測或略過 artifact readback。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class AllocationReleaseLoader(Protocol):
    """application release adapter 必須實作的唯讀 loader 形狀。"""

    def __call__(
        self,
        release_root: str | Path,
        *,
        expected_release_identity_hash: str | None = None,
        manifest_name: str = "release_manifest.json",
    ) -> Any: ...


_registered_loader: AllocationReleaseLoader | None = None


def register_release_loader(loader: AllocationReleaseLoader) -> None:
    """註冊 application adapter；重複註冊同一 callable 具冪等性。"""

    if not callable(loader):
        raise TypeError("allocation release loader must be callable")
    global _registered_loader
    if _registered_loader is not None and _registered_loader is not loader:
        raise RuntimeError("allocation release loader is already registered")
    _registered_loader = loader


def load_allocation_release(
    release_root: str | Path,
    *,
    expected_release_identity_hash: str | None = None,
    manifest_name: str = "release_manifest.json",
) -> Any:
    """以中立 contract 轉送至已註冊的 application release loader。

    沒有註冊 loader 時拒絕繼續，確保 producer 不會在缺少 artifact
    readback parity 的情況下發布結果。
    """

    loader = _registered_loader
    if loader is None:
        raise RuntimeError(
            "allocation release loader is not registered; "
            "bootstrap the application release adapter before readback"
        )
    return loader(
        release_root,
        expected_release_identity_hash=expected_release_identity_hash,
        manifest_name=manifest_name,
    )


__all__ = [
    "AllocationReleaseLoader",
    "load_allocation_release",
    "register_release_loader",
]
