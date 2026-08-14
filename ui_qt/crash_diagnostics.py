"""桌面 App 的持久化 crash diagnostics。

此模組只負責記錄診斷證據，不改變 Qt 事件處理或投資決策流程。
"""

from __future__ import annotations

import atexit
from datetime import datetime, timezone
import faulthandler
import os
from pathlib import Path
import sys
import threading
import traceback
from types import TracebackType
from typing import Callable, TextIO


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CrashDiagnosticsSession:
    """保留 log stream 與原始 exception hooks，直到程序安全結束。"""

    def __init__(self, log_path: Path, stream: TextIO) -> None:
        self.log_path = log_path
        self._stream = stream
        self._lock = threading.RLock()
        self._closed = False
        self._exception_observed = False
        self._original_sys_hook = sys.excepthook
        self._original_thread_hook = threading.excepthook
        self._enabled_native_handler = False
        self._sys_hook: Callable[..., object] | None = None
        self._thread_hook: Callable[..., object] | None = None

    def _flush(self) -> None:
        try:
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except (OSError, ValueError):
            pass

    def write_line(self, message: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._stream.write(message.rstrip() + "\n")
            self._flush()

    def write_exception(
        self,
        context: str,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        with self._lock:
            if self._closed:
                return
            self._exception_observed = True
            self._stream.write(f"EXCEPTION context={context} at={_utc_now()}\n")
            traceback.print_exception(
                exc_type,
                exc_value,
                exc_traceback,
                file=self._stream,
            )
            self._flush()

    def install(self) -> None:
        executable = repr(sys.executable)
        argv0 = repr(sys.argv[0] if sys.argv else "")
        working_directory = repr(str(Path.cwd()))
        data_root = repr(os.environ.get("DATA_ROOT", ""))
        self.write_line(
            "SESSION_START "
            f"at={_utc_now()} pid={os.getpid()} "
            f"ppid={getattr(os, 'getppid', lambda: 0)()} "
            f"python={sys.version.split()[0]} executable={executable} "
            f"argv0={argv0} cwd={working_directory} data_root={data_root}"
        )

        if not faulthandler.is_enabled():
            faulthandler.enable(file=self._stream, all_threads=True)
            self._enabled_native_handler = True
            self.write_line("NATIVE_FAULTHANDLER enabled=true all_threads=true")
        else:
            self.write_line("NATIVE_FAULTHANDLER enabled=external")

        def sys_hook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            exc_traceback: TracebackType | None,
        ) -> object:
            self.write_exception(
                "main_thread_unhandled",
                exc_type,
                exc_value,
                exc_traceback,
            )
            return self._original_sys_hook(exc_type, exc_value, exc_traceback)

        def thread_hook(args: threading.ExceptHookArgs) -> object:
            thread_name = getattr(getattr(args, "thread", None), "name", "unknown")
            self.write_exception(
                f"thread_unhandled:{thread_name}",
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            )
            return self._original_thread_hook(args)

        self._sys_hook = sys_hook
        self._thread_hook = thread_hook
        sys.excepthook = sys_hook
        threading.excepthook = thread_hook

    def close(self) -> None:
        if self._closed:
            return
        clean_shutdown = str(not self._exception_observed).lower()
        exception_observed = str(self._exception_observed).lower()
        self.write_line(
            "SESSION_END "
            f"clean_shutdown={clean_shutdown} "
            f"exception_observed={exception_observed} at={_utc_now()}"
        )
        if self._sys_hook is not None and sys.excepthook is self._sys_hook:
            sys.excepthook = self._original_sys_hook
        if (
            self._thread_hook is not None
            and threading.excepthook is self._thread_hook
        ):
            threading.excepthook = self._original_thread_hook
        if self._enabled_native_handler:
            faulthandler.disable()
        self._closed = True
        self._stream.close()


_ACTIVE_SESSION: CrashDiagnosticsSession | None = None


def install_crash_diagnostics(
    data_root: str | Path | None = None,
) -> Path:
    """安裝一次 crash hooks，並回傳持久化 log 路徑。"""

    global _ACTIVE_SESSION
    if _ACTIVE_SESSION is not None and not _ACTIVE_SESSION._closed:
        return _ACTIVE_SESSION.log_path

    resolved_root = Path(
        data_root
        or os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")
    ).expanduser()
    log_path = resolved_root / "logs" / "ui_qt_crash.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("a", encoding="utf-8", buffering=1)
    session = CrashDiagnosticsSession(log_path, stream)
    session.install()
    _ACTIVE_SESSION = session
    atexit.register(close_crash_diagnostics)
    return log_path


def record_exception(context: str, error: BaseException) -> None:
    """將已被 UI 邊界攔下的例外也寫入同一份持久化證據。"""

    if _ACTIVE_SESSION is None:
        return
    _ACTIVE_SESSION.write_exception(
        context,
        type(error),
        error,
        error.__traceback__,
    )


def close_crash_diagnostics() -> None:
    """還原 hooks 並關閉 log；可重複呼叫。"""

    global _ACTIVE_SESSION
    if _ACTIVE_SESSION is None:
        return
    _ACTIVE_SESSION.close()
    _ACTIVE_SESSION = None
