from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

from ui_qt import crash_diagnostics
from ui_qt import main as app_main


def test_main_configures_non_utf8_console_streams_fail_softly(monkeypatch) -> None:
    class FakeStream:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, **kwargs: str) -> None:
            self.calls.append(kwargs)

    stdout = FakeStream()
    stderr = FakeStream()
    monkeypatch.setattr(app_main.sys, "stdout", stdout)
    monkeypatch.setattr(app_main.sys, "stderr", stderr)

    app_main._configure_console_streams()

    expected = [{"encoding": "utf-8", "errors": "backslashreplace"}]
    assert stdout.calls == expected
    assert stderr.calls == expected


def test_main_console_reconfigure_failure_is_ignored(monkeypatch) -> None:
    class FailingStream:
        def reconfigure(self, **_kwargs: str) -> None:
            raise ValueError("captured stream is immutable")

    monkeypatch.setattr(app_main.sys, "stdout", FailingStream())
    monkeypatch.setattr(app_main.sys, "stderr", FailingStream())

    app_main._configure_console_streams()


def test_crash_diagnostics_persists_main_thread_and_worker_exceptions(
    tmp_path,
    monkeypatch,
) -> None:
    native_calls: list[tuple[str, object]] = []
    original_calls: list[str] = []

    monkeypatch.setattr(crash_diagnostics.faulthandler, "is_enabled", lambda: False)
    monkeypatch.setattr(
        crash_diagnostics.faulthandler,
        "enable",
        lambda **kwargs: native_calls.append(("enable", kwargs)),
    )
    monkeypatch.setattr(
        crash_diagnostics.faulthandler,
        "disable",
        lambda: native_calls.append(("disable", None)),
    )
    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda *_args: original_calls.append("sys"),
    )
    monkeypatch.setattr(
        threading,
        "excepthook",
        lambda _args: original_calls.append("thread"),
    )

    log_path = crash_diagnostics.install_crash_diagnostics(tmp_path)
    try:
        main_error = RuntimeError("main-boom")
        sys.excepthook(type(main_error), main_error, None)

        thread_error = ValueError("worker-boom")
        threading.excepthook(
            SimpleNamespace(
                exc_type=type(thread_error),
                exc_value=thread_error,
                exc_traceback=None,
                thread=SimpleNamespace(name="candidate-updater"),
            )
        )
        crash_diagnostics.record_exception(
            "handled_startup_boundary",
            OSError("startup-boom"),
        )
    finally:
        crash_diagnostics.close_crash_diagnostics()

    log_text = log_path.read_text(encoding="utf-8")
    assert "SESSION_START" in log_text
    assert "executable=" in log_text
    assert "argv0=" in log_text
    assert "cwd=" in log_text
    assert "data_root=" in log_text
    assert "NATIVE_FAULTHANDLER enabled=true" in log_text
    assert "EXCEPTION context=main_thread_unhandled" in log_text
    assert "RuntimeError: main-boom" in log_text
    assert "EXCEPTION context=thread_unhandled:candidate-updater" in log_text
    assert "ValueError: worker-boom" in log_text
    assert "EXCEPTION context=handled_startup_boundary" in log_text
    assert "OSError: startup-boom" in log_text
    assert "SESSION_END clean_shutdown=false exception_observed=true" in log_text
    assert original_calls == ["sys", "thread"]
    assert [call[0] for call in native_calls] == ["enable", "disable"]


def test_crash_diagnostics_install_is_idempotent(tmp_path, monkeypatch) -> None:
    enable_calls: list[object] = []
    monkeypatch.setattr(crash_diagnostics.faulthandler, "is_enabled", lambda: False)
    monkeypatch.setattr(
        crash_diagnostics.faulthandler,
        "enable",
        lambda **kwargs: enable_calls.append(kwargs),
    )
    monkeypatch.setattr(crash_diagnostics.faulthandler, "disable", lambda: None)

    first_path = crash_diagnostics.install_crash_diagnostics(tmp_path)
    second_path = crash_diagnostics.install_crash_diagnostics(tmp_path / "other")
    crash_diagnostics.close_crash_diagnostics()

    assert first_path == second_path
    assert len(enable_calls) == 1
    assert "SESSION_END clean_shutdown=true exception_observed=false" in first_path.read_text(
        encoding="utf-8"
    )
