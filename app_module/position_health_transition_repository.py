"""Append-only repository for proposed and human-approved health transitions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from app_module.position_health_service import PositionHealthState


@dataclass(frozen=True)
class PositionHealthTransitionRecord:
    event_id: str
    position_id: str
    decision_date: str
    previous_state: PositionHealthState
    proposed_state: PositionHealthState
    recorded_state: PositionHealthState
    decision_kind: str
    reasons: tuple[str, ...]
    reviewer: str | None = None
    auto_action_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.event_id or not self.position_id or not self.decision_date:
            raise ValueError("event_id, position_id and decision_date are required")
        if self.decision_kind not in {"proposal", "human_approved"}:
            raise ValueError("unsupported decision_kind")
        if self.decision_kind == "proposal" and self.recorded_state is not self.previous_state:
            raise ValueError("proposal cannot change recorded_state")
        if self.decision_kind == "human_approved" and not (self.reviewer or "").strip():
            raise ValueError("human-approved transition requires reviewer")
        if self.auto_action_allowed:
            raise ValueError("health transition cannot enable auto action")

    @classmethod
    def proposal(
        cls,
        *,
        event_id: str,
        position_id: str,
        decision_date: str,
        previous_state: PositionHealthState,
        proposed_state: PositionHealthState,
        reasons: tuple[str, ...],
    ) -> "PositionHealthTransitionRecord":
        return cls(
            event_id,
            position_id,
            decision_date,
            previous_state,
            proposed_state,
            previous_state,
            "proposal",
            reasons,
        )

    @classmethod
    def human_approved(
        cls,
        *,
        event_id: str,
        position_id: str,
        decision_date: str,
        previous_state: PositionHealthState,
        approved_state: PositionHealthState,
        reasons: tuple[str, ...],
        reviewer: str,
    ) -> "PositionHealthTransitionRecord":
        return cls(
            event_id,
            position_id,
            decision_date,
            previous_state,
            approved_state,
            approved_state,
            "human_approved",
            reasons,
            reviewer,
        )


class PositionHealthTransitionRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS position_health_transitions (
                    event_id TEXT PRIMARY KEY,
                    position_id TEXT NOT NULL,
                    decision_date TEXT NOT NULL,
                    previous_state TEXT NOT NULL,
                    proposed_state TEXT NOT NULL,
                    recorded_state TEXT NOT NULL,
                    decision_kind TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    reviewer TEXT,
                    auto_action_allowed INTEGER NOT NULL
                )"""
            )

    def append(self, record: PositionHealthTransitionRecord) -> None:
        try:
            with sqlite3.connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO position_health_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.event_id,
                        record.position_id,
                        record.decision_date,
                        record.previous_state.value,
                        record.proposed_state.value,
                        record.recorded_state.value,
                        record.decision_kind,
                        json.dumps(record.reasons),
                        record.reviewer,
                        int(record.auto_action_allowed),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"transition event already exists: {record.event_id}") from exc

    def append_proposal_idempotent(
        self,
        record: PositionHealthTransitionRecord,
    ) -> str:
        """Atomically append one proposal or return its idempotent result.

        The evaluator uses ``position_id + decision_date`` as the identity
        boundary. ``BEGIN IMMEDIATE`` serializes two scheduled writers so a
        list-then-insert race cannot allow contradictory proposals for the same
        position and date.
        """

        if record.decision_kind != "proposal":
            raise ValueError("idempotent append only accepts proposals")
        with sqlite3.connect(self._path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT event_id, previous_state, proposed_state, recorded_state,
                       decision_kind, reasons_json
                FROM position_health_transitions
                WHERE position_id = ? AND decision_date = ?
                """,
                (record.position_id, record.decision_date),
            ).fetchone()
            if existing is not None:
                same_payload = (
                    str(existing["event_id"]) == record.event_id
                    and str(existing["previous_state"]) == record.previous_state.value
                    and str(existing["proposed_state"]) == record.proposed_state.value
                    and str(existing["recorded_state"]) == record.recorded_state.value
                    and str(existing["decision_kind"]) == "proposal"
                    and tuple(json.loads(str(existing["reasons_json"]))) == record.reasons
                )
                if same_payload:
                    return "idempotent"
                raise ValueError("conflicting health proposal for position/date")
            try:
                conn.execute(
                    "INSERT INTO position_health_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.event_id,
                        record.position_id,
                        record.decision_date,
                        record.previous_state.value,
                        record.proposed_state.value,
                        record.recorded_state.value,
                        record.decision_kind,
                        json.dumps(record.reasons),
                        record.reviewer,
                        int(record.auto_action_allowed),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"transition event already exists: {record.event_id}") from exc
        return "written"

    def list_for_position(self, position_id: str) -> tuple[PositionHealthTransitionRecord, ...]:
        with sqlite3.connect(self._path) as conn:
            rows = conn.execute(
                "SELECT * FROM position_health_transitions WHERE position_id = ? ORDER BY decision_date, event_id",
                (position_id,),
            ).fetchall()
        return tuple(
            PositionHealthTransitionRecord(
                event_id=str(row[0]),
                position_id=str(row[1]),
                decision_date=str(row[2]),
                previous_state=PositionHealthState(row[3]),
                proposed_state=PositionHealthState(row[4]),
                recorded_state=PositionHealthState(row[5]),
                decision_kind=str(row[6]),
                reasons=tuple(json.loads(row[7])),
                reviewer=row[8],
                auto_action_allowed=bool(row[9]),
            )
            for row in rows
        )
