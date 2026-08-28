"""UpdateView 背景 worker 的生命週期協調器。"""

from __future__ import annotations

from typing import Generic, Optional, TypeVar


WorkerT = TypeVar("WorkerT")


class WorkerCoordinator(Generic[WorkerT]):
    def __init__(self) -> None:
        self.active_workers: list[WorkerT] = []
        self.current: Optional[WorkerT] = None
        # 以 id 保存 kind，避免對自訂 worker 的 hashability 做額外假設。
        self._worker_kinds: dict[int, str] = {}

    def start(
        self,
        worker: WorkerT,
        *,
        kind: str = "read",
        exclusive: bool = False,
    ) -> WorkerT:
        """註冊 worker；可選擇阻擋同類型的重疊工作。"""
        if exclusive and self.has_active(kind):
            raise RuntimeError(f"已有進行中的 {kind} 背景工作")
        self.active_workers.append(worker)
        self._worker_kinds[id(worker)] = kind
        self.current = worker
        return worker

    def active_workers_for(self, kind: str) -> list[WorkerT]:
        """取得指定 kind 的活動 worker。"""
        return [
            worker
            for worker in self.active_workers
            if self._worker_kinds.get(id(worker), "read") == kind
        ]

    def has_active(self, kind: Optional[str] = None) -> bool:
        """檢查是否有活動 worker；kind 為 None 時檢查全部。"""
        if kind is None:
            return bool(self.active_workers)
        return bool(self.active_workers_for(kind))

    def release(self, worker: WorkerT) -> Optional[WorkerT]:
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        self._worker_kinds.pop(id(worker), None)
        if self.current is worker:
            self.current = self.active_workers[-1] if self.active_workers else None
        return self.current
