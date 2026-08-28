"""正式 App 路徑與持久化邊界的唯讀 readiness 檢查。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Callable

from app_module.dtos.runtime_dtos import (
    EnvironmentPathReadinessDTO,
    EnvironmentReadinessSnapshotDTO,
    EnvironmentWriteProbeDTO,
)


@dataclass(frozen=True)
class _PathSpec:
    key: str
    label: str
    path: Path
    kind: str
    requires_write: bool
    write_probe_path: Path | None = None


class EnvironmentReadinessService:
    """檢查路徑能力但不嘗試修復；不建立目錄、檔案或資料庫。"""

    def __init__(
        self,
        data_root: Path,
        output_root: Path,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._data_root = _safe_resolve(Path(data_root))
        self._output_root = _safe_resolve(Path(output_root))
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def get_snapshot(self) -> EnvironmentReadinessSnapshotDTO:
        specs = (
            _PathSpec(
                key="data_root",
                label="DATA_ROOT",
                path=self._data_root,
                kind="directory",
                requires_write=False,
            ),
            _PathSpec(
                key="output_root",
                label="OUTPUT_ROOT",
                path=self._output_root,
                kind="directory",
                requires_write=True,
            ),
            _PathSpec(
                key="log_root",
                label="Logs",
                path=self._data_root / "logs",
                kind="directory",
                requires_write=True,
                write_probe_path=self._data_root / "logs" / "config.log",
            ),
            _PathSpec(
                key="research_registry",
                label="Research Run Registry",
                path=self._output_root / "research_runs" / "research_runs.db",
                kind="file",
                requires_write=True,
                write_probe_path=self._output_root / "research_runs" / "research_runs.db",
            ),
        )
        statuses = tuple(_inspect_spec(spec) for spec in specs)
        diagnostics = tuple(
            status.diagnostic
            for status in statuses
            if status.diagnostic
        )
        if any(
            status.status == "unavailable"
            for status in statuses
            if status.key == "data_root" or status.requires_write
        ):
            overall_state = "unavailable"
        elif any(status.status == "attention" for status in statuses):
            overall_state = "attention"
        else:
            overall_state = "ready"

        return EnvironmentReadinessSnapshotDTO(
            overall_state=overall_state,
            observed_at=_as_utc(self._now_provider()),
            data_root=str(self._data_root),
            output_root=str(self._output_root),
            log_root=str(self._data_root / "logs"),
            research_registry=str(self._output_root / "research_runs" / "research_runs.db"),
            paths=statuses,
            diagnostics=diagnostics,
            write_probe="os.access_plus_existing_handle",
        )

    def run_write_probe(
        self,
        probe_root: Path,
        *,
        confirm: bool = False,
    ) -> EnvironmentWriteProbeDTO:
        """在明確指定的非正式目錄執行可清理的實際寫入驗證。

        預設不執行任何寫入。即使帶有 ``confirm``，也禁止將正式
        ``DATA_ROOT`` 或 ``OUTPUT_ROOT``（含其子路徑）當成 probe 目標，
        避免把環境檢查變成正式資料／registry 變更。
        """

        target = _safe_resolve(Path(probe_root))
        observed_at = _as_utc(self._now_provider())
        if confirm is not True:
            return EnvironmentWriteProbeDTO(
                status="confirmation_required",
                probe_root=str(target),
                observed_at=observed_at,
                side_effect_free=True,
                write_probe="not_run",
                diagnostic="需要明確傳入 confirm 才會執行 ephemeral write probe",
            )

        if _is_within(target, self._data_root) or _is_within(target, self._output_root):
            return EnvironmentWriteProbeDTO(
                status="blocked",
                probe_root=str(target),
                observed_at=observed_at,
                side_effect_free=True,
                write_probe="not_run",
                diagnostic="probe_root 不得位於正式 DATA_ROOT 或 OUTPUT_ROOT",
            )

        if not _is_dir(target):
            return EnvironmentWriteProbeDTO(
                status="blocked",
                probe_root=str(target),
                observed_at=observed_at,
                side_effect_free=True,
                write_probe="not_run",
                diagnostic="probe_root 必須是已存在的非正式目錄；不會由檢查自動建立",
            )

        file_write_succeeded = False
        sqlite_write_succeeded = False
        cleanup_succeeded = False
        diagnostic = ""
        temporary_path: Path | None = None
        try:
            with tempfile.TemporaryDirectory(
                prefix=".runtime-write-probe-",
                dir=str(target),
            ) as temporary_name:
                temporary_path = Path(temporary_name)
                marker_path = temporary_path / "file_probe.txt"
                marker_path.write_text("baldr-runtime-write-probe-v1\n", encoding="utf-8")
                file_write_succeeded = (
                    marker_path.read_text(encoding="utf-8")
                    == "baldr-runtime-write-probe-v1\n"
                )

                database_path = temporary_path / "sqlite_probe.sqlite"
                with closing(sqlite3.connect(database_path)) as connection:
                    with connection:
                        connection.execute(
                            "CREATE TABLE runtime_write_probe (probe_id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
                        )
                        connection.execute(
                            "INSERT INTO runtime_write_probe(value) VALUES (?)",
                            ("ok",),
                        )
                        row = connection.execute(
                            "SELECT value FROM runtime_write_probe WHERE probe_id = 1"
                        ).fetchone()
                        sqlite_write_succeeded = row == ("ok",)
            cleanup_succeeded = temporary_path is not None and not temporary_path.exists()
        except (OSError, sqlite3.Error, UnicodeError) as exc:
            diagnostic = f"{type(exc).__name__}: {exc}"
            if temporary_path is not None:
                cleanup_succeeded = not temporary_path.exists()

        status = (
            "passed"
            if file_write_succeeded and sqlite_write_succeeded and cleanup_succeeded
            else "failed"
        )
        if not diagnostic and status != "passed":
            diagnostic = "ephemeral file／SQLite write 或 cleanup 未完整通過"
        return EnvironmentWriteProbeDTO(
            status=status,
            probe_root=str(target),
            observed_at=observed_at,
            file_write_succeeded=file_write_succeeded,
            sqlite_write_succeeded=sqlite_write_succeeded,
            cleanup_succeeded=cleanup_succeeded,
            side_effect_free=False,
            write_probe="actual_ephemeral",
            diagnostic=diagnostic,
        )


def _inspect_spec(spec: _PathSpec) -> EnvironmentPathReadinessDTO:
    path = spec.path
    parent = path.parent
    parent_exists = _is_dir(parent)
    exists = _is_dir(path) if spec.kind == "directory" else _is_file(path)
    readable = _access(path, os.R_OK) if exists else False

    if exists:
        writable: bool | None = _access(path, os.W_OK)
    elif parent_exists:
        writable = _access(parent, os.W_OK) if spec.requires_write else None
    else:
        writable = False if spec.requires_write else None

    if spec.key == "data_root" and not exists:
        status = "unavailable"
        diagnostic = "data_root_not_created"
    elif not parent_exists and not exists:
        status = "unavailable"
        diagnostic = f"{spec.key}_parent_missing"
    elif not exists:
        status = "ready_to_create" if (not spec.requires_write or writable is True) else "attention"
        diagnostic = f"{spec.key}_not_created"
    elif not readable:
        status = "unavailable"
        diagnostic = f"{spec.key}_not_readable"
    elif spec.requires_write and writable is False:
        status = "attention"
        diagnostic = f"{spec.key}_not_writable"
    else:
        status = "ready"
        diagnostic = ""

    # ``os.access`` may report a writable path even when the current Windows
    # token cannot open an existing file for write (ACL, share mode, or an
    # external lock).  Probe only an already-existing representative file;
    # never create, truncate, or write a formal file from this read-only
    # readiness path.
    if (
        status == "ready"
        and spec.requires_write
        and spec.write_probe_path is not None
        and _is_file(spec.write_probe_path)
    ):
        handle_ok, handle_diagnostic = _probe_existing_write_handle(
            spec.write_probe_path
        )
        if handle_ok is False:
            status = "attention"
            diagnostic = handle_diagnostic or f"{spec.key}_write_handle_denied"

    return EnvironmentPathReadinessDTO(
        key=spec.key,
        label=spec.label,
        path=str(path),
        kind=spec.kind,
        exists=exists,
        parent_exists=parent_exists,
        readable=readable,
        writable=writable,
        requires_write=spec.requires_write,
        status=status,
        diagnostic=diagnostic,
    )


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _access(path: Path, mode: int) -> bool:
    try:
        return bool(os.access(path, mode))
    except OSError:
        return False


def _probe_existing_write_handle(path: Path) -> tuple[bool | None, str]:
    """Open an existing file for write without changing its contents.

    ``None`` is reserved for a path that cannot be probed; callers already
    guard existence, but keeping this outcome explicit prevents an inspection
    failure from being mistaken for a successful write capability.  The
    handle is closed immediately and no bytes are written.
    """

    try:
        with path.open("r+b"):
            return True, ""
    except (OSError, PermissionError) as exc:
        return False, f"{path.name}_write_handle_denied:{type(exc).__name__}"


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return path.expanduser().absolute()


def _is_within(path: Path, root: Path) -> bool:
    """判定 path 是否等於或位於 root 下方；兩者均已 canonicalize。"""

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
