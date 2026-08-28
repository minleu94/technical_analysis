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


def test_worker_coordinator_exclusive_write_rejects_overlap_but_allows_read() -> None:
    coordinator = WorkerCoordinator[object]()
    write_worker = object()
    read_worker = object()

    assert coordinator.start(write_worker, kind="write", exclusive=True) is write_worker
    assert coordinator.has_active("write") is True

    # 唯讀狀態檢查可在寫入期間並行，避免 UI 卡在無法觀測的狀態。
    assert coordinator.start(read_worker, kind="read") is read_worker
    assert coordinator.has_active("read") is True

    try:
        coordinator.start(object(), kind="write", exclusive=True)
    except RuntimeError as exc:
        assert "write" in str(exc)
    else:
        raise AssertionError("第二個 exclusive write worker 不應被接受")
