"""Append-only human, time, evidence and ML revalidation gate registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any


GATE_CATEGORIES = frozenset(
    {
        "human_input",
        "human_approval",
        "waiting_for_time",
        "data_license",
        "evidence_maturity",
        "ml_revalidation",
        "automated_evidence",
        "policy_decision",
    }
)
GATE_STATUSES = frozenset(
    {
        "open",
        "in_progress",
        "waiting",
        "insufficient_evidence",
        "complete",
        "rejected",
    }
)


@dataclass(frozen=True)
class EngineeringGateItem:
    item_id: str
    revision: int
    category: str
    title: str
    status: str
    owner: str
    earliest_validation_date: str
    progress_bp: int
    required_artifacts: tuple[str, ...]
    validation_commands: tuple[str, ...]
    completion_rules: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    notes: str = ""
    completion_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.item_id or not self.title or not self.owner:
            raise ValueError("item_id, title and owner are required")
        if self.revision <= 0:
            raise ValueError("revision must be positive")
        if self.category not in GATE_CATEGORIES:
            raise ValueError("unsupported gate category")
        if self.status not in GATE_STATUSES:
            raise ValueError("unsupported gate status")
        if isinstance(self.progress_bp, bool) or not isinstance(self.progress_bp, int) or not 0 <= self.progress_bp <= 10000:
            raise ValueError("progress_bp must be integer within 0..10000")
        for name in (
            "required_artifacts",
            "validation_commands",
            "completion_rules",
            "prohibited_actions",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        if self.status == "complete" and (
            self.progress_bp != 10000 or not self.completion_evidence
        ):
            raise ValueError("complete gate requires 10000bp progress and completion evidence")

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        for name in (
            "required_artifacts",
            "validation_commands",
            "completion_rules",
            "prohibited_actions",
            "completion_evidence",
        ):
            payload[name] = list(payload[name])
        return payload


class EngineeringGateRegistry:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS engineering_gate_revisions (
                    item_id TEXT NOT NULL, revision INTEGER NOT NULL, category TEXT NOT NULL,
                    status TEXT NOT NULL, payload_json TEXT NOT NULL,
                    PRIMARY KEY (item_id, revision)
                )"""
            )

    def append(self, item: EngineeringGateItem) -> None:
        self.append_many((item,))

    def append_many(self, items: tuple[EngineeringGateItem, ...]) -> None:
        if not items:
            raise ValueError("at least one gate revision is required")
        identities = tuple((item.item_id, item.revision) for item in items)
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate gate revision in append batch")
        try:
            with sqlite3.connect(self._path) as conn:
                current_revisions = {
                    str(row[0]): int(row[1])
                    for row in conn.execute(
                        """SELECT item_id, MAX(revision)
                           FROM engineering_gate_revisions
                           GROUP BY item_id"""
                    ).fetchall()
                }
                batch_revisions: dict[str, int] = {}
                for item in items:
                    latest_revision = max(
                        current_revisions.get(item.item_id, 0),
                        batch_revisions.get(item.item_id, 0),
                    )
                    expected_revision = latest_revision + 1
                    if item.revision != expected_revision:
                        raise ValueError(
                            "gate revision must be contiguous: "
                            f"{item.item_id}:expected={expected_revision}:"
                            f"actual={item.revision}"
                        )
                    batch_revisions[item.item_id] = item.revision
                conn.executemany(
                    "INSERT INTO engineering_gate_revisions VALUES (?, ?, ?, ?, ?)",
                    tuple(
                        (
                            item.item_id,
                            item.revision,
                            item.category,
                            item.status,
                            json.dumps(item.to_dict()),
                        )
                        for item in items
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("gate revision already exists in append batch") from exc

    def latest(self, item_id: str) -> EngineeringGateItem | None:
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM engineering_gate_revisions WHERE item_id = ? ORDER BY revision DESC LIMIT 1",
                (item_id,),
            ).fetchone()
        return _hydrate(row[0]) if row else None

    def history(self, item_id: str) -> tuple[EngineeringGateItem, ...]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM engineering_gate_revisions WHERE item_id = ? ORDER BY revision",
                (item_id,),
            ).fetchall()
        return tuple(_hydrate(row[0]) for row in rows)

    def list_latest(self) -> tuple[EngineeringGateItem, ...]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                """SELECT r.payload_json FROM engineering_gate_revisions r
                   JOIN (SELECT item_id, MAX(revision) revision FROM engineering_gate_revisions GROUP BY item_id) latest
                   ON r.item_id = latest.item_id AND r.revision = latest.revision
                   ORDER BY r.item_id"""
            ).fetchall()
        return tuple(_hydrate(row[0]) for row in rows)


def _hydrate(payload_json: str) -> EngineeringGateItem:
    payload = json.loads(payload_json)
    for name in (
        "required_artifacts",
        "validation_commands",
        "completion_rules",
        "prohibited_actions",
        "completion_evidence",
    ):
        payload[name] = tuple(payload[name])
    return EngineeringGateItem(**payload)
