from ui_qt.views.update.worker_coordinator import WorkerCoordinator


def test_worker_coordinator_preserves_all_workers_and_falls_back_to_latest() -> None:
    coordinator = WorkerCoordinator[object]()
    first = object()
    second = object()

    assert coordinator.start(first) is first
    assert coordinator.start(second) is second
    assert coordinator.active_workers == [first, second]
    assert coordinator.current is second

    assert coordinator.release(second) is first
    assert coordinator.active_workers == [first]
    assert coordinator.release(first) is None
    assert coordinator.active_workers == []


def test_worker_coordinator_release_is_idempotent() -> None:
    coordinator = WorkerCoordinator[object]()
    worker = object()
    coordinator.start(worker)

    coordinator.release(worker)

    assert coordinator.release(worker) is None
