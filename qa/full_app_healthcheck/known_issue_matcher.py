from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence


@dataclass(frozen=True)
class KnownIssueMatch:
    issue_id: str
    title: str
    category: str
    likely_owner: str
    recommendation: str
    confidence: str


def match_known_issues(text: str) -> Sequence[KnownIssueMatch]:
    normalized = text.lower()
    matches: list[KnownIssueMatch] = []

    if any(token in normalized for token in ("sqlite", "daily_prices", "available_date", "schema")):
        matches.append(
            KnownIssueMatch(
                issue_id="DATA-AUDIT-001",
                title="資料或 SQLite schema 相關錯誤",
                category="data_audit",
                likely_owner="data_audit",
                recommendation="交接給 Data Audit Agent 檢查資料新鮮度、SQLite schema 與 available_date。",
                confidence="medium",
            )
        )

    has_ui_signal = any(
        token in normalized for token in ("widget", "layout", "visible", "hidden", "button")
    ) or re.search(r"\btab\b", normalized) is not None
    if has_ui_signal:
        matches.append(
            KnownIssueMatch(
                issue_id="UI-EXECUTION-001",
                title="UI 元件可見性或排版錯誤",
                category="ui_execution",
                likely_owner="execution",
                recommendation="交接給 Execution Agent 檢查 UI layout、widget binding 與可見性。",
                confidence="medium",
            )
        )

    if any(token in normalized for token in ("known manual gap", "manual gap", "manual-only")):
        matches.append(
            KnownIssueMatch(
                issue_id="KNOWN-MANUAL-GAP-001",
                title="已知手動測試缺口",
                category="known_manual_gap",
                likely_owner="testing_qa",
                recommendation="保留為 manual gap，由 Testing / QA Agent 彙整缺口，不可自動標記為通過。",
                confidence="high",
            )
        )

    if "unmatched suite id" in normalized:
        matches.append(
            KnownIssueMatch(
                issue_id="RUNNER-ROUTING-001",
                title="Runner bridge 或 feature route 未註冊測試套件",
                category="runner_routing",
                likely_owner="testing_qa",
                recommendation="檢查 test_suite_bridge.py、feature_router.py 與 TEST_INVENTORY 分類是否一致。",
                confidence="high",
            )
        )

    return tuple(matches)
