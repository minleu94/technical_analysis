"""Fixture-only CLI for clock-bound prospective Rule Champion history.

必須提供 ``--fixture-only``。CLI 只讀 clock、requests 與受控 artifact fixture，
由既有 repository verifier 取用 Windows controlled runtime HMAC；輸出只寫呼叫端
指定的 immutable manifest，不啟動 watcher、不讀取或輸出 HMAC secret。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.prospective_formal_clock import (  # noqa: E402
    ProspectiveFormalClockError,
    load_clock_manifest_for_capture,
)
from data_module.prospective_rule_champion_publisher import (  # noqa: E402
    JsonPersistedFormalArtifactLoader,
    ProspectiveRuleChampionPublisherError,
    PROSPECTIVE_RULE_HISTORY_RESULT_SCHEMA_VERSION,
    ProspectiveRuleSnapshotRequest,
    publish_prospective_rule_history,
)
from data_module.rule_champion_snapshot_service import (  # noqa: E402
    PersistedFormalDecisionArtifactRepository,
)


def _parse_now(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("--now must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include timezone")
    return parsed


def _read_requests(path: Path) -> tuple[ProspectiveRuleSnapshotRequest, ...]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("requests JSON is unreadable") from error
    if not isinstance(value, list) or not value:
        raise ValueError("requests JSON must be a non-empty array")
    requests: list[ProspectiveRuleSnapshotRequest] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("request row must be an object")
        if set(item) != {"decision_date", "decision_snapshot_ids"}:
            raise ValueError("request row fields are invalid")
        decision_date = item.get("decision_date")
        ids = item.get("decision_snapshot_ids")
        if not isinstance(decision_date, str) or not decision_date.strip():
            raise ValueError("request decision_date is required")
        if not isinstance(ids, list) or not ids:
            raise ValueError("request decision_snapshot_ids must be a non-empty array")
        if any(not isinstance(snapshot_id, str) or not snapshot_id.strip() for snapshot_id in ids):
            raise ValueError("request decision_snapshot_ids must contain text")
        requests.append(
            ProspectiveRuleSnapshotRequest(
                decision_date=decision_date,
                decision_snapshot_ids=tuple(ids),
            )
        )
    return tuple(requests)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixture-only publish of prospective clock-bound Rule Champion history。"
    )
    parser.add_argument("--fixture-only", action="store_true", required=True)
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requests-json", type=Path, required=True)
    parser.add_argument("--artifacts-json", type=Path, required=True)
    parser.add_argument("--strategy-version", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--score-configuration-hash", required=True)
    parser.add_argument("--universe-hash", required=True)
    parser.add_argument("--selection-capacity", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        now = _parse_now(args.now)
        clock = load_clock_manifest_for_capture(args.clock_manifest, now=now)
        loader = JsonPersistedFormalArtifactLoader(args.artifacts_json)
        repository = PersistedFormalDecisionArtifactRepository(loader)
        result = publish_prospective_rule_history(
            clock=clock,
            output_path=args.output,
            now=now,
            strategy_version=args.strategy_version,
            policy_version=args.policy_version,
            score_configuration_hash=args.score_configuration_hash,
            universe_hash=args.universe_hash,
            selection_capacity=args.selection_capacity,
            repository=repository,
            requests=_read_requests(args.requests_json),
        )
        payload = result.to_dict()
        payload["fixture_only"] = True
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ProspectiveFormalClockError,
        ProspectiveRuleChampionPublisherError,
    ) as error:
        print(
            json.dumps(
                {
                    "schema_version": PROSPECTIVE_RULE_HISTORY_RESULT_SCHEMA_VERSION,
                    "status": "blocked",
                    "fixture_only": True,
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                    "secret_values_emitted": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
