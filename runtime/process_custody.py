"""Read-only process custody grouping for CPU and duplicate-runtime diagnosis.

This module deliberately exposes only safe process metadata.  Command lines are
used internally to classify a process, but are never returned in the report;
that prevents an accidental HMAC, token, or path argument from becoming a
status artifact.  No function in this module can terminate or mutate a process.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
from pathlib import Path
import os
import time
from typing import Any, Callable, TypedDict


PROCESS_CUSTODY_SCHEMA_VERSION = "runtime-process-custody.v1"


class _NormalizedSample(TypedDict):
    pid: int
    ppid: int | None
    role: str
    scope: str
    cpu_seconds: float
    memory_bytes: int
    thread_count: int
    status: str


class _ProcessCandidate(TypedDict):
    process: Any
    pid: int
    ppid: int | None
    name: str
    executable: str
    cmdline: tuple[str, ...]
    cwd: str
    before_cpu_seconds: float
    before_monotonic: float
    memory_bytes: int
    thread_count: int
    status: str


class ProcessCustodyError(ValueError):
    """Process custody input or output is invalid."""


def build_process_custody_report(
    samples: Sequence[Mapping[str, object]],
    *,
    sample_seconds: float,
    skipped_process_count: int = 0,
) -> dict[str, object]:
    """Group safe process samples without exposing command lines or secrets.

    ``cpu_seconds`` is the delta measured during ``sample_seconds``.  The
    resulting ``cpu_percent_of_one_core`` is intentionally an operational
    diagnostic, not a financial metric, so a float is appropriate here.
    """

    if isinstance(sample_seconds, bool) or not isinstance(sample_seconds, (int, float)):
        raise ProcessCustodyError("sample_seconds must be numeric")
    if sample_seconds <= 0:
        raise ProcessCustodyError("sample_seconds must be positive")
    if isinstance(skipped_process_count, bool) or not isinstance(skipped_process_count, int):
        raise ProcessCustodyError("skipped_process_count must be an integer")
    if skipped_process_count < 0:
        raise ProcessCustodyError("skipped_process_count cannot be negative")

    normalized = [_normalize_sample(value) for value in samples]
    groups: dict[tuple[str, str], list[_NormalizedSample]] = {}
    for sample in normalized:
        key = (str(sample["scope"]), str(sample["role"]))
        groups.setdefault(key, []).append(sample)

    group_rows: list[dict[str, object]] = []
    duplicate_mcp_groups: list[dict[str, object]] = []
    mcp_members: dict[str, list[tuple[str, _NormalizedSample]]] = {}
    for (scope, role), members in sorted(groups.items()):
        cpu_seconds = sum(float(item["cpu_seconds"]) for item in members)
        row: dict[str, object] = {
            "scope": scope,
            "role": role,
            "instance_count": len(members),
            "pids": sorted(int(item["pid"]) for item in members),
            "parent_pids": sorted({int(item["ppid"]) for item in members if item["ppid"] is not None}),
            "cpu_seconds": round(cpu_seconds, 6),
            "cpu_percent_of_one_core": round(cpu_seconds / float(sample_seconds) * 100.0, 3),
            "memory_bytes": sum(int(item["memory_bytes"]) for item in members),
            "max_threads": max(int(item["thread_count"]) for item in members),
        }
        group_rows.append(row)
        if role.startswith("mcp:"):
            mcp_members.setdefault(role, []).extend(
                (scope, member) for member in members
            )

    for role, mcp_group_members in sorted(mcp_members.items()):
        if len(mcp_group_members) <= 1:
            continue
        duplicate_mcp_groups.append(
            {
                "role": role,
                "scopes": sorted({scope for scope, _ in mcp_group_members}),
                "instance_count": len(mcp_group_members),
                "pids": sorted(int(sample["pid"]) for _, sample in mcp_group_members),
                "memory_bytes": sum(
                    int(sample["memory_bytes"]) for _, sample in mcp_group_members
                ),
            }
        )

    busy_single_core: list[dict[str, object]] = []
    for sample in normalized:
        cpu_percent = float(sample["cpu_seconds"]) / float(sample_seconds) * 100.0
        if cpu_percent >= 80.0 and int(sample["thread_count"]) <= 2:
            busy_single_core.append(
                {
                    "pid": int(sample["pid"]),
                    "ppid": sample["ppid"],
                    "scope": sample["scope"],
                    "role": sample["role"],
                    "cpu_percent_of_one_core": round(cpu_percent, 3),
                    "thread_count": int(sample["thread_count"]),
                    "memory_bytes": int(sample["memory_bytes"]),
                    "status": sample["status"],
                }
            )

    warnings: list[str] = []
    if skipped_process_count:
        warnings.append(f"process_access_denied_or_exited:{skipped_process_count}")
    for item in duplicate_mcp_groups:
        warnings.append(
            f"duplicate_mcp_runtime:{item['role']}:{item['instance_count']}"
        )
    for item in busy_single_core:
        warnings.append(f"busy_single_core_process:{item['pid']}:{item['role']}")

    return {
        "schema_version": PROCESS_CUSTODY_SCHEMA_VERSION,
        "status": "attention_required" if warnings else "clean",
        "read_only": True,
        "termination_requested": False,
        "sample_seconds": float(sample_seconds),
        "process_count": len(normalized),
        "skipped_process_count": skipped_process_count,
        "groups": group_rows,
        "duplicate_mcp_groups": duplicate_mcp_groups,
        "busy_single_core_processes": busy_single_core,
        "warnings": warnings,
        "secret_values_emitted": False,
    }


def collect_process_samples(
    *,
    sample_seconds: float,
    process_iter: Callable[..., Iterable[Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    python_only: bool = True,
) -> tuple[list[dict[str, object]], int]:
    """Collect a bounded CPU delta using psutil, without mutating processes.

    The default only inspects Python processes because the operational question
    is duplicate MCP／ML custody; ``python_only=False`` is available for a
    broader diagnostic when explicitly requested.
    """

    if isinstance(sample_seconds, bool) or not isinstance(sample_seconds, (int, float)):
        raise ProcessCustodyError("sample_seconds must be numeric")
    if sample_seconds <= 0:
        raise ProcessCustodyError("sample_seconds must be positive")
    try:
        import psutil
    except ImportError as error:  # pragma: no cover - deployment guard
        raise ProcessCustodyError("psutil is required for process custody") from error

    iterator = psutil.process_iter if process_iter is None else process_iter
    candidates: list[_ProcessCandidate] = []
    skipped = 0
    for process in iterator():
        try:
            with process.oneshot():
                if not isinstance(process.pid, int) or process.pid <= 0:
                    skipped += 1
                    continue
                process_name = _safe_process_value(process.name)
                if python_only and "python" not in process_name.casefold():
                    continue
                before_monotonic = time.monotonic()
                before = process.cpu_times()
                candidates.append(
                    {
                        "process": process,
                        "pid": process.pid,
                        "ppid": process.ppid(),
                        "name": process_name,
                        "executable": _safe_process_value(process.exe),
                        "cmdline": tuple(_safe_process_value(item) for item in process.cmdline()),
                        "cwd": _safe_process_value(process.cwd),
                        "before_cpu_seconds": float(before.user + before.system),
                        "before_monotonic": before_monotonic,
                        "memory_bytes": int(process.memory_info().rss),
                        "thread_count": int(process.num_threads()),
                        "status": _safe_process_value(process.status),
                    }
                )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            skipped += 1
    sleep(float(sample_seconds))

    samples: list[dict[str, object]] = []
    for candidate in candidates:
        process = candidate["process"]
        try:
            after = process.cpu_times()
            raw_delta = max(
                0.0,
                float(after.user + after.system) - float(candidate["before_cpu_seconds"]),
            )
            elapsed = max(
                time.monotonic() - float(candidate["before_monotonic"]),
                0.001,
            )
            delta = raw_delta * float(sample_seconds) / elapsed
            samples.append(
                {
                    "pid": candidate["pid"],
                    "ppid": candidate["ppid"],
                    "name": candidate["name"],
                    "executable": candidate["executable"],
                    "cmdline": candidate["cmdline"],
                    "cwd": candidate["cwd"],
                    "cpu_seconds": delta,
                    "memory_bytes": candidate["memory_bytes"],
                    "thread_count": candidate["thread_count"],
                    "status": candidate["status"],
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            skipped += 1
    return samples, skipped


def write_process_custody_report(output_path: Path, report: Mapping[str, object]) -> str:
    """Write a canonical, create-only report and return its file hash."""

    if report.get("schema_version") != PROCESS_CUSTODY_SCHEMA_VERSION:
        raise ProcessCustodyError("process custody schema_version is invalid")
    body = dict(report)
    body.pop("report_hash", None)
    report_with_hash = {**body, "report_hash": _payload_hash(body)}
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProcessCustodyError("process custody output parent must exist")
    try:
        with output.open("xb") as stream:
            stream.write(_canonical_json(report_with_hash).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProcessCustodyError("process custody output already exists") from error
    return _file_sha256(output)


def _normalize_sample(value: Mapping[str, object]) -> _NormalizedSample:
    if not isinstance(value, Mapping):
        raise ProcessCustodyError("process sample must be an object")
    required = {
        "pid", "ppid", "name", "executable", "cmdline", "cwd", "cpu_seconds",
        "memory_bytes", "thread_count", "status",
    }
    if set(value) != required:
        raise ProcessCustodyError("process sample fields are invalid")
    pid = value["pid"]
    ppid = value["ppid"]
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ProcessCustodyError("process sample pid is invalid")
    if ppid is not None and (isinstance(ppid, bool) or not isinstance(ppid, int) or ppid < 0):
        raise ProcessCustodyError("process sample ppid is invalid")
    for field_name in ("name", "executable", "cwd", "status"):
        if not isinstance(value[field_name], str):
            raise ProcessCustodyError(f"process sample {field_name} is invalid")
    cmdline = value["cmdline"]
    if not isinstance(cmdline, (list, tuple)) or any(not isinstance(item, str) for item in cmdline):
        raise ProcessCustodyError("process sample cmdline is invalid")
    cpu_seconds = value["cpu_seconds"]
    if isinstance(cpu_seconds, bool) or not isinstance(cpu_seconds, (int, float)) or cpu_seconds < 0:
        raise ProcessCustodyError("process sample cpu_seconds is invalid")
    memory_bytes = value["memory_bytes"]
    thread_count = value["thread_count"]
    if isinstance(memory_bytes, bool) or not isinstance(memory_bytes, int) or memory_bytes < 0:
        raise ProcessCustodyError("process sample memory_bytes is invalid")
    if isinstance(thread_count, bool) or not isinstance(thread_count, int) or thread_count < 0:
        raise ProcessCustodyError("process sample thread_count is invalid")
    status = value["status"]
    if not isinstance(status, str):  # pragma: no cover - guarded above
        raise ProcessCustodyError("process sample status is invalid")
    role, scope = classify_process(
        name=str(value["name"]),
        executable=str(value["executable"]),
        cmdline=tuple(cmdline),
        cwd=str(value["cwd"]),
    )
    return {
        "pid": pid,
        "ppid": ppid,
        "role": role,
        "scope": scope,
        "cpu_seconds": float(cpu_seconds),
        "memory_bytes": memory_bytes,
        "thread_count": thread_count,
        "status": status,
    }


def classify_process(
    *,
    name: str,
    executable: str,
    cmdline: Sequence[str],
    cwd: str,
) -> tuple[str, str]:
    """Classify without returning the original command line or path."""

    text = " ".join((name, executable, cwd, *cmdline)).casefold().replace("\\", "/")
    technical = "technical_analysis" in text
    codex = ".codex" in text or "codex" in text
    if "inkscope_probe_" in text:
        return "external:inkscope_probe", "external"
    for marker, role in (
        ("mcp_server_yfinance", "mcp:yfinance"),
        ("evidence_access_server.py", "mcp:evidence_access"),
        ("sqlite_server.py", "mcp:sqlite"),
        ("project_context_server.py", "mcp:project_context"),
        ("git_server.py", "mcp:git"),
    ):
        if marker in text:
            return role, "technical_analysis" if technical else "runtime"
    if any(marker in text for marker in ("maintain_ml", "build_ml", "train_ml", "ooc", "direct_v3")):
        return "ml_or_data_pipeline", "technical_analysis" if technical else "external"
    if "ui_qt/main.py" in text:
        return "technical_analysis_ui", "technical_analysis"
    if codex:
        return "codex_runtime", "codex"
    if technical:
        return "technical_analysis_other", "technical_analysis"
    return "other", "external"


def _safe_process_value(value: Any) -> str:
    if callable(value):
        try:
            value = value()
        except Exception:
            return ""
    return value if isinstance(value, str) else ""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: object) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
