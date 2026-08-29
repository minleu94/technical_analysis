from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from app_module.evidence_weekly_approval_input import (
    APPROVAL_STATUS,
    build_weekly_approval_input,
    render_markdown,
    validate_output_path,
)


def _create_sidecar(path: Path, source_path: Path) -> None:
    source_path.write_bytes(b"source")
    source_hash = "sha256:" + ("a" * 64)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE evidence_weekly_collections (
                collection_id TEXT PRIMARY KEY,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                error_type TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO evidence_weekly_collections (
                collection_id, period_start, period_end, source_path,
                source_hash, status, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "ewc-1",
                    "2026-08-03",
                    "2026-08-09",
                    str(source_path),
                    source_hash,
                    "pending_human_review",
                    json.dumps(
                        {
                            "last_trading_date": "2026-08-07",
                            "human_approval_required": True,
                        }
                    ),
                    "2026-08-10 01:00:00",
                ),
                (
                    "ewc-2",
                    "2026-08-10",
                    "2026-08-16",
                    str(source_path),
                    source_hash,
                    "collection_failed",
                    json.dumps({"last_trading_date": ""}),
                    "2026-08-17 01:00:00",
                ),
            ],
        )


def test_build_packet_is_read_only_and_excludes_failed_by_default(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "sidecar.sqlite"
    source_path = tmp_path / "source.db"
    _create_sidecar(sidecar_path, source_path)
    before = sidecar_path.read_bytes()

    packet = build_weekly_approval_input(sidecar_path)

    assert packet["packet_status"] == "needs_named_owner_reviewer"
    assert packet["record_count"] == 1
    assert packet["pending_human_review_count"] == 1
    assert packet["collection_failed_count"] == 0
    assert packet["formal_credit_authorized"] is False
    assert packet["write_performed"] is False
    assert packet["records"][0]["review"]["approval_status"] == APPROVAL_STATUS
    assert sidecar_path.read_bytes() == before


def test_build_packet_can_include_failed_and_named_roles(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "sidecar.sqlite"
    source_path = tmp_path / "source.db"
    _create_sidecar(sidecar_path, source_path)

    packet = build_weekly_approval_input(
        sidecar_path,
        owner_role="evidence_owner",
        reviewer_role="independent_reviewer",
        include_failed=True,
    )

    assert packet["packet_status"] == "ready_for_human_review"
    assert packet["record_count"] == 2
    assert packet["pending_human_review_count"] == 1
    assert packet["collection_failed_count"] == 1
    assert packet["owner_role"] == "evidence_owner"
    assert packet["reviewer_role"] == "independent_reviewer"
    assert "pending" in render_markdown(packet)


def test_packet_fails_closed_on_invalid_source_hash(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "sidecar.sqlite"
    source_path = tmp_path / "source.db"
    _create_sidecar(sidecar_path, source_path)
    with sqlite3.connect(sidecar_path) as connection:
        connection.execute(
            "UPDATE evidence_weekly_collections SET source_hash = 'not-hashed'"
        )

    with pytest.raises(ValueError, match="immutable"):
        build_weekly_approval_input(sidecar_path)


def test_output_path_cannot_overwrite_sidecar_or_missing_parent(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "sidecar.sqlite"
    with pytest.raises(ValueError, match="overwrite"):
        validate_output_path(sidecar_path, sidecar_path=sidecar_path)
    with pytest.raises(ValueError, match="parent"):
        validate_output_path(
            tmp_path / "missing" / "packet.json",
            sidecar_path=sidecar_path,
        )

