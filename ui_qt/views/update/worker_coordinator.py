"""UpdateView 背景 worker 的生命週期協調器。"""

from __future__ import annotations

from typing import Generic, Optional, TypeVar


WorkerT = TypeVar("WorkerT")


class WorkerCoordinator(Generic[WorkerT]):
    def __init__(self) -> None:
        self.active_workers: list[WorkerT] = []
        self.current: Optional[WorkerT] = None

    def start(self, worker: WorkerT) -> WorkerT:
        self.active_workers.append(worker)
        self.current = worker
        return worker

    def release(self, worker: WorkerT) -> Optional[WorkerT]:
        if worker in self.active_workers:
            self.active_workers.remove(worker)
        if self.current is worker:
            self.current = self.active_workers[-1] if self.active_workers else None
        return self.current
