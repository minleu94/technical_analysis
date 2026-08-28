"""TaskWorker 取消契約的精準單元測試。"""

import pytest

from ui_qt.workers.task_worker import (
    ProgressTaskWorker,
    TaskWorker,
    request_cooperative_task_worker_shutdown,
)


class _InspectableTaskWorker(TaskWorker):
    """記錄取消期間的 QThread 方法呼叫，不啟動實際執行緒。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.terminate_calls = 0
        self.wait_calls = []

    def terminate(self):
        self.terminate_calls += 1

    def wait(self, *args):
        self.wait_calls.append(args)
        return True


class _InspectableProgressTaskWorker(ProgressTaskWorker):
    """記錄取消期間的 QThread 方法呼叫，不啟動實際執行緒。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.terminate_calls = 0
        self.wait_calls = []

    def terminate(self):
        self.terminate_calls += 1

    def wait(self, *args):
        self.wait_calls.append(args)
        return True


@pytest.mark.parametrize(
    "worker_class",
    [_InspectableTaskWorker, _InspectableProgressTaskWorker],
)
def test_cancel_defaults_to_nonblocking_cooperative_without_terminating(worker_class):
    worker = worker_class(lambda **_kwargs: None)

    worker.cancel()

    assert worker._is_cancelled is True
    assert worker.terminate_calls == 0
    assert worker.wait_calls == []


@pytest.mark.parametrize(
    "worker_class",
    [_InspectableTaskWorker, _InspectableProgressTaskWorker],
)
def test_cancel_can_explicitly_wait_without_terminating(worker_class):
    worker = worker_class(lambda **_kwargs: None)

    worker.cancel(wait=True)

    assert worker._is_cancelled is True
    assert worker.terminate_calls == 0
    assert worker.wait_calls == [()]


@pytest.mark.parametrize(
    "worker_class",
    [_InspectableTaskWorker, _InspectableProgressTaskWorker],
)
def test_cancel_keeps_legacy_parameter_but_never_terminates(worker_class):
    worker = worker_class(lambda **_kwargs: None)

    worker.cancel(cooperative=False, wait=False)

    assert worker._is_cancelled is True
    assert worker.terminate_calls == 0
    assert worker.wait_calls == []


@pytest.mark.parametrize("worker_class", [TaskWorker, ProgressTaskWorker])
def test_pre_cancelled_worker_emits_cancelled_without_running_task(worker_class):
    task_calls = []
    cancelled_calls = []
    worker = worker_class(lambda **_kwargs: task_calls.append("ran"))
    worker.cancelled.connect(lambda: cancelled_calls.append("cancelled"))

    worker.cancel(wait=False)
    worker.run()

    assert task_calls == []
    assert cancelled_calls == ["cancelled"]


def test_progress_worker_injects_thread_safe_cancel_callback_only_when_supported():
    observed: list[bool] = []
    finished_calls: list[object] = []

    def task(progress_callback=None, cancel_callback=None):
        assert progress_callback is not None
        assert cancel_callback is not None
        observed.append(cancel_callback())
        return "done"

    worker = ProgressTaskWorker(task)
    worker.finished.connect(finished_calls.append)
    worker.run()

    assert observed == [False]
    assert finished_calls == ["done"]

    worker.cancel()
    assert worker.is_cancel_requested() is True


def test_task_worker_does_not_inject_cancel_callback_into_legacy_callable():
    calls: list[str] = []
    worker = TaskWorker(lambda: calls.append("ran"))

    worker.run()

    assert calls == ["ran"]


def test_shutdown_request_is_nonblocking_and_never_terminates():
    class _RunningWorker(_InspectableTaskWorker):
        def isRunning(self):
            return True

    worker = _RunningWorker(lambda **_kwargs: None)

    remaining = request_cooperative_task_worker_shutdown()

    assert worker in remaining
    assert worker._is_cancelled is True
    assert worker.terminate_calls == 0
    assert worker.wait_calls == []


def test_native_thread_cleanup_is_deferred_while_worker_is_running():
    class _RunningWorker(TaskWorker):
        running = True

        def isRunning(self):
            return self.running

    worker = _RunningWorker(lambda **_kwargs: None)

    worker.deleteLater()

    assert worker._delete_later_requested is True

    worker.running = False
    worker._on_native_thread_finished()

    assert worker._delete_later_requested is False


def test_native_finished_signal_is_available_separately_from_task_result():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    task_results = []
    native_finished = []
    worker = TaskWorker(lambda: "ok")
    worker.finished.connect(task_results.append)
    worker.native_thread_finished.connect(lambda: native_finished.append(True))

    worker.start()
    assert worker.wait(5_000) is True
    app.processEvents()

    assert task_results == ["ok"]
    assert native_finished == [True]
    worker.deleteLater()
    app.processEvents()
