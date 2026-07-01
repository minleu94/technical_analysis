from __future__ import annotations

from pathlib import Path


CHECKLIST = Path("docs/06_qa/POST_V1_EVIDENCE_PRODUCTION_SCHEDULER_APPROVAL_CHECKLIST_2026_07_07.md")


def test_approval_checklist_exists_and_contains_required_sections() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")

    for section in (
        "Preconditions",
        "Manual Approval Steps",
        "Production Schedule Future Design",
        "Rollback / Recovery",
        "Explicit Non-goals",
    ):
        assert section in text
    for required in (
        "latest data update completed",
        "working-copy smoke passed",
        "diagnostics report reviewed",
        "backup path verified",
        "rollback path verified",
        "no production DB writes without explicit approval",
        "source coverage check",
        "dry-run evidence pipeline",
        "manual approval",
        "archive bad events",
        "mark bad outcomes stale",
    ):
        assert required in text


def test_approval_docs_do_not_enable_scheduler_or_use_forbidden_language() -> None:
    paths = [
        CHECKLIST,
        Path("docs/superpowers/specs/2026-07-07-post-v1-production-scheduler-approval-design.md"),
        Path("docs/superpowers/plans/2026-07-07-post-v1-production-scheduler-approval.md"),
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "windows task scheduler command" not in lowered
        assert "cron entry" not in lowered
        assert "production scheduler enabled" not in lowered
        for forbidden in ("buy", "sell", "target price", "fair price", "high confidence"):
            assert forbidden not in lowered
