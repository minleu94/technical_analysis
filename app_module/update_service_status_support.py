from __future__ import annotations

from typing import Any, Mapping


def compose_sqlite_status_read_model(
    statuses: Mapping[str, Mapping[str, Any]],
    *,
    is_overview: bool = False,
) -> dict[str, dict[str, Any]]:
    """以既有 SQLite status payload 組裝唯讀回傳模型。"""
    result = {source: dict(payload) for source, payload in statuses.items()}
    if is_overview:
        for payload in result.values():
            payload["is_overview"] = True
    return result
