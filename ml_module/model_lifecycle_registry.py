"""Append-only lifecycle events for shadow models."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3


_EVENT_TYPES = frozenset(
    {"activated_for_shadow", "disabled", "rollback_requested", "superseded", "review_required"}
)
_ALLOWED_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"activated_for_shadow", "review_required"}),
    "activated_for_shadow": frozenset({"disabled", "rollback_requested", "superseded", "review_required"}),
    "rollback_requested": frozenset({"disabled", "review_required"}),
    "review_required": frozenset({"activated_for_shadow", "disabled", "rollback_requested", "superseded"}),
    "disabled": frozenset(),
    "superseded": frozenset(),
}


@dataclass(frozen=True)
class ModelLifecycleEvent:
    event_id: str
    model_id: str
    event_type: str
    created_at: str
    reason: str

    def __post_init__(self) -> None:
        if not all((self.event_id, self.model_id, self.created_at, self.reason)):
            raise ValueError("complete lifecycle event identity is required")
        if self.event_type not in _EVENT_TYPES:
            raise ValueError(f"unsupported lifecycle event: {self.event_type}")

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


def initialize_model_lifecycle_registry(
    db_path: str | Path, *, data_root: str | Path | None = None
) -> None:
    path = _validate_shadow_db(db_path, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ml_model_lifecycle_events (
                event_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ml_lifecycle_model ON ml_model_lifecycle_events(model_id)"
        )


class ModelLifecycleRegistry:
    def __init__(self, db_path: str | Path, *, data_root: str | Path | None = None) -> None:
        self._path = _validate_shadow_db(db_path, data_root=data_root)

    def append(self, event: ModelLifecycleEvent) -> str:
        with self._connect_rw() as conn:
            existing = conn.execute(
                "SELECT payload_json FROM ml_model_lifecycle_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            payload_json = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
            if existing is not None:
                if existing[0] == payload_json:
                    return "idempotent"
                raise ValueError(f"lifecycle event conflict: {event.event_id}")
            current = self._current_status(conn, event.model_id)
            if event.event_type not in _ALLOWED_TRANSITIONS[current]:
                raise ValueError(f"invalid lifecycle transition: {current} -> {event.event_type}")
            conn.execute(
                "INSERT INTO ml_model_lifecycle_events VALUES (?, ?, ?, ?, ?)",
                (event.event_id, event.model_id, event.event_type, event.created_at, payload_json),
            )
        return "inserted"

    def list_events(self, model_id: str) -> tuple[ModelLifecycleEvent, ...]:
        with self._connect_rw() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM ml_model_lifecycle_events WHERE model_id = ? ORDER BY rowid",
                (model_id,),
            ).fetchall()
        return tuple(ModelLifecycleEvent(**json.loads(row[0])) for row in rows)

    def current_status(self, model_id: str) -> str | None:
        with self._connect_rw() as conn:
            return self._current_status(conn, model_id)

    @staticmethod
    def _current_status(conn: sqlite3.Connection, model_id: str) -> str | None:
        row = conn.execute(
            "SELECT event_type FROM ml_model_lifecycle_events WHERE model_id = ? ORDER BY rowid DESC LIMIT 1",
            (model_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def _connect_rw(self) -> sqlite3.Connection:
        if not self._path.is_file():
            raise FileNotFoundError(f"lifecycle registry is not initialized: {self._path}")
        return sqlite3.connect(f"file:{self._path.as_posix()}?mode=rw", uri=True)


def _validate_shadow_db(path: str | Path, *, data_root: str | Path | None) -> Path:
    resolved = Path(path).resolve()
    formal_root = Path(data_root or os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    if resolved == formal_root or formal_root in resolved.parents:
        raise ValueError("shadow registry cannot be DATA_ROOT or its descendant")
    return resolved
