import json
import os
from typing import List, Dict, Any
from runtime.interfaces.store_interface import (
    IRuntimeStore,
    RuntimeEventCursor,
    RuntimeEventReadBatch,
    RuntimeEventReadResult,
)

class LocalFileStore(IRuntimeStore):
    """
    Concrete implementation of IRuntimeStore using local JSON and JSONL files.
    This class handles the pure I/O mechanics and shields the Orchestration layer.
    """
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.events_file = os.path.join(self.base_dir, "events", "runtime_events.jsonl")
        self.task_file = os.path.join(self.base_dir, "state", "current_task.json")
        self.context_file = os.path.join(self.base_dir, "state", "runtime_context.json")
        
    def append_event(self, event_data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.events_file), exist_ok=True)
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_data, ensure_ascii=False) + "\n")
            
    def read_latest_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self.read_latest_events_result(limit).events)

    def read_latest_events_result(self, limit: int = 100) -> RuntimeEventReadResult:
        if not os.path.exists(self.events_file):
            return RuntimeEventReadResult((), "missing")

        try:
            events: list[Dict[str, Any]] = []
            invalid_line_count = 0
            for line in self._read_tail_lines(limit):
                if line.strip():
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        invalid_line_count += 1
                        continue
                    if isinstance(payload, dict):
                        events.append(payload)
                    else:
                        invalid_line_count += 1
            diagnostic = (
                f"runtime_event_invalid_lines:{invalid_line_count}"
                if invalid_line_count
                else ""
            )
            return RuntimeEventReadResult(
                tuple(events),
                "degraded" if invalid_line_count else "observed",
                diagnostic=diagnostic,
                invalid_line_count=invalid_line_count,
            )
        except OSError as exc:
            return RuntimeEventReadResult(
                (),
                "unavailable",
                diagnostic=f"runtime_event_read_failed:{type(exc).__name__}",
            )

    def read_events_after(
        self,
        cursor: RuntimeEventCursor | None,
        limit: int = 50,
    ) -> RuntimeEventReadBatch:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not os.path.exists(self.events_file):
            # Keep the initial ``-1`` sentinel until a stream exists.  If an
            # external workflow creates the stream later, the controller will
            # still attach at its tail instead of replaying old fixture events.
            return RuntimeEventReadBatch(
                (),
                cursor or RuntimeEventCursor(-1),
                False,
                read_state="missing",
            )

        try:
            file_size = os.path.getsize(self.events_file)
            requested_position = 0 if cursor is None else cursor.position
            if requested_position < 0:
                return RuntimeEventReadBatch((), RuntimeEventCursor(file_size), False)

            cursor_reset = requested_position > file_size
            position = 0 if cursor_reset else requested_position
            events: list[Dict[str, Any]] = []
            invalid_line_count = 0
            next_position = position
            scanned_line_count = 0
            max_scanned_lines = max(limit * 4, 100)
            with open(self.events_file, "rb") as handle:
                handle.seek(position)
                while len(events) < limit and scanned_line_count < max_scanned_lines:
                    line_start = handle.tell()
                    raw_line = handle.readline()
                    if not raw_line:
                        break
                    scanned_line_count += 1
                    line_end = handle.tell()
                    if not raw_line.endswith(b"\n"):
                        next_position = line_start
                        break
                    next_position = line_end
                    if not raw_line.strip():
                        continue
                    try:
                        decoded = raw_line.decode("utf-8")
                        payload = json.loads(decoded)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        invalid_line_count += 1
                        continue
                    if isinstance(payload, dict):
                        events.append(payload)
                    else:
                        invalid_line_count += 1
            has_more = next_position < file_size
            return RuntimeEventReadBatch(
                tuple(events),
                RuntimeEventCursor(next_position),
                has_more,
                cursor_reset=cursor_reset,
                invalid_line_count=invalid_line_count,
                read_state="degraded" if invalid_line_count else "observed",
                diagnostic=(
                    f"runtime_event_invalid_lines:{invalid_line_count}"
                    if invalid_line_count
                    else ""
                ),
            )
        except OSError as exc:
            fallback = cursor or RuntimeEventCursor(-1)
            return RuntimeEventReadBatch(
                (),
                fallback,
                False,
                read_state="unavailable",
                diagnostic=f"runtime_event_read_failed:{type(exc).__name__}",
            )
        
    def _read_json_file(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def read_current_task(self) -> Dict[str, Any]:
        return self._read_json_file(self.task_file)
        
    def read_runtime_context(self) -> Dict[str, Any]:
        return self._read_json_file(self.context_file)
        
    def update_current_task(self, task_data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.task_file), exist_ok=True)
        with open(self.task_file, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)

    def _read_tail_lines(self, limit: int) -> list[str]:
        if limit <= 0:
            return []
        block_size = 8192
        with open(self.events_file, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            remaining = handle.tell()
            chunks: list[bytes] = []
            newline_count = 0
            while remaining > 0 and newline_count <= limit:
                read_size = min(block_size, remaining)
                remaining -= read_size
                handle.seek(remaining)
                chunk = handle.read(read_size)
                chunks.insert(0, chunk)
                newline_count += chunk.count(b"\n")
        content = b"".join(chunks)
        if content and not content.endswith(b"\n"):
            content = content.rsplit(b"\n", 1)[0]
        return [
            line.decode("utf-8", errors="replace")
            for line in content.splitlines()[-limit:]
        ]
