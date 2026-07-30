"""依機器證據建立 V4 Gate 2–7 append-only revision 批次。

本工具只產生 revision JSON，不直接改 DB。呼叫端必須再以
``manage_engineering_gate_registry.py ... append`` 原子寫入 sidecar registry。
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def build_gate_revisions(
    *,
    decision_date: str,
    pre_v2: Mapping[str, Any],
    p0_audit: Mapping[str, Any],
    pit_coverage: Mapping[str, Any],
    evidence_hashes: Mapping[str, str],
    current_revisions: Mapping[str, int] | None = None,
) -> tuple[dict[str, Any], ...]:
    pre_v2_items = {
        str(item["item_id"]): item for item in pre_v2.get("items", ())
    }
    weekly = pre_v2_items.get("weekly_history", {})
    source_rows = tuple(p0_audit.get("machine_evidence_matrix", ()))
    if len(source_rows) != 13:
        raise ValueError("P0 audit must contain exactly 13 source decisions")

    source_decisions = tuple(
        {
            "source_id": str(row["source_id"]),
            "disposition": _source_disposition(row),
            "machine_status": str(row.get("machine_status", "missing")),
            "pit_status": str(row.get("pit_status", "unavailable")),
            "remaining_blocker": str(row.get("remaining_blocker", "")),
        }
        for row in sorted(source_rows, key=lambda value: str(value["source_id"]))
    )
    accepted_count = sum(
        1 for item in source_decisions if item["disposition"] == "accepted"
    )
    research_shadow_count = sum(
        1 for item in source_decisions if item["disposition"] == "research_shadow"
    )
    blocked_count = sum(
        1 for item in source_decisions if item["disposition"] == "blocked_no_provenance"
    )

    coverage_families = {
        str(item["family_id"]): item for item in pit_coverage.get("families", ())
    }
    monthly = coverage_families.get("monthly_revenue", {})
    statements = coverage_families.get("quarterly_statement", {})
    corporate_actions = coverage_families.get("corporate_action", {})
    weekly_count = _non_negative_int(weekly.get("observed_count", 0))
    weekly_required = _positive_int(weekly.get("required_count", 3))

    shared_prohibited = (
        "不得用 fixture/replay 補真實 elapsed evidence",
        "不得把現在快照回填成歷史 PIT",
        "不得連接券商或自動送單",
    )
    revisions = (
        _gate(
            item_id="evidence:weekly-history-3",
            category="automated_evidence",
            title="以排程累積三個真實 Weekly Review",
            status=(
                "complete"
                if weekly_count >= weekly_required
                else "insufficient_evidence"
            ),
            owner="evidence-scheduler",
            decision_date=decision_date,
            progress_bp=min(10_000, weekly_count * 10_000 // weekly_required),
            required_artifacts=("pre-v2 readiness JSON", "weekly sidecar history"),
            validation_commands=(
                "python scripts/inspect_pre_v2_readiness.py --json-output",
            ),
            completion_rules=("observed weekly count >= 3",),
            prohibited_actions=shared_prohibited,
            notes=f"observed={weekly_count}; required={weekly_required}; machine-managed",
            completion_evidence=(
                (f"pre_v2_sha256={evidence_hashes['pre_v2']}",)
                if weekly_count >= weekly_required
                else ()
            ),
        ),
        _gate(
            item_id="evidence:forward-maturity",
            category="automated_evidence",
            title="依 available_at 自動重驗 forward maturity",
            status="insufficient_evidence",
            owner="evidence-scheduler",
            decision_date=decision_date,
            progress_bp=0,
            required_artifacts=("PIT coverage audit", "matured outcome registry"),
            validation_commands=(
                "python scripts/audit_pit_historical_coverage.py ...",
            ),
            completion_rules=("matured outcomes meet the configured sample floor",),
            prohibited_actions=shared_prohibited,
            notes=(
                f"monthly_eligible={monthly.get('eligible', 0)}/"
                f"{monthly.get('total', 0)}; "
                f"statement_eligible={statements.get('eligible', 0)}/"
                f"{statements.get('total', 0)}"
            ),
        ),
        _gate(
            item_id="p0:source-acceptance-13",
            category="automated_evidence",
            title="13 個 P0 來源逐來源機器處置",
            status="complete",
            owner="data-governance-policy",
            decision_date=decision_date,
            progress_bp=10_000,
            required_artifacts=("bounded official source audit",),
            validation_commands=("python scripts/run_p0_source_evidence_audit.py ...",),
            completion_rules=("all 13 sources have an explicit disposition",),
            prohibited_actions=(
                "不得批次推定 accepted",
                "未通過 license/PIT/quality 的來源不得進正式訓練",
                *shared_prohibited,
            ),
            notes=json.dumps(
                {
                    "accepted": accepted_count,
                    "research_shadow": research_shadow_count,
                    "blocked_no_provenance": blocked_count,
                    "decisions": source_decisions,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            completion_evidence=(
                f"p0_audit_sha256={evidence_hashes['p0_audit']}",
                *(f"{item['source_id']}={item['disposition']}" for item in source_decisions),
            ),
        ),
        _gate(
            item_id="paper:policy-approval",
            category="policy_decision",
            title="採用 V4 平衡型 Paper Portfolio 政策",
            status="complete",
            owner="portfolio-risk-policy",
            decision_date=decision_date,
            progress_bp=10_000,
            required_artifacts=("V4 allocation policy contract",),
            validation_commands=(
                "pytest tests/test_portfolio_allocation_service.py -q -o addopts=",
            ),
            completion_rules=("integer-bp limits and Decimal costs pass",),
            prohibited_actions=(
                "不得自動連接券商",
                "不得略過交易成本或整張限制",
            ),
            notes=(
                "cash>=2000bp; positions<=8; symbol<=1500bp; sector<=3000bp; "
                "turnover<=2000bp/week; band=300bp; min_trade=200bp; cooldown=5d; "
                "lot=1000 shares; buy_cost=25bp; sell_cost=55bp"
            ),
            completion_evidence=("user_authorized_v4_balanced_policy",),
        ),
        _gate(
            item_id="paper:elapsed-observation",
            category="automated_evidence",
            title="由 Daily Scheduler 累積 Paper Portfolio 真實觀察",
            status="insufficient_evidence",
            owner="paper-scheduler",
            decision_date=decision_date,
            progress_bp=0,
            required_artifacts=("daily paper snapshots", "cost and benchmark ledger"),
            validation_commands=("python scripts/inspect_pre_v2_readiness.py --json-output",),
            completion_rules=("at least one complete real paper week",),
            prohibited_actions=shared_prohibited,
            notes="scheduler-managed; elapsed observation is not replaced by backtest",
        ),
        _gate(
            item_id="v3:manual-pruning-review",
            category="policy_decision",
            title="保留 Rule champion 並隔離低證據 challenger",
            status="complete",
            owner="strategy-policy",
            decision_date=decision_date,
            progress_bp=10_000,
            required_artifacts=("replayable pruning decision",),
            validation_commands=("pytest tests/test_strategy_lifecycle_service.py -q",),
            completion_rules=("every challenger is retain/restrict/downweight/retire/defer",),
            prohibited_actions=("不得讓低證據 challenger 取代 Rule champion",),
            notes="Rule champion retained; all low-evidence challengers restricted to shadow",
            completion_evidence=("policy=retain_rule_restrict_low_evidence_challengers",),
        ),
        _gate(
            item_id="health:thesis-input",
            category="policy_decision",
            title="缺 thesis 自動 WATCH、invalidation 自動 EXIT",
            status="complete",
            owner="position-health-policy",
            decision_date=decision_date,
            progress_bp=10_000,
            required_artifacts=("Position Health state-machine policy",),
            validation_commands=("pytest tests/test_position_health_state_machine.py -q",),
            completion_rules=("missing thesis=>WATCH; invalidation=>EXIT_CANDIDATE",),
            prohibited_actions=("ML 不得編造 thesis 或取消 EXIT",),
            notes="human input gate replaced by deterministic fail-closed policy",
            completion_evidence=("policy=missing_thesis_watch_invalidation_exit",),
        ),
        _gate(
            item_id="health:transition-review",
            category="automated_evidence",
            title="Position Health transition 以狀態機測試簽核",
            status="complete",
            owner="position-health-policy",
            decision_date=decision_date,
            progress_bp=10_000,
            required_artifacts=("state-machine transition tests",),
            validation_commands=("pytest tests/test_position_health_state_machine.py -q",),
            completion_rules=("all legal transitions pass and illegal transitions fail closed",),
            prohibited_actions=("ML 不得直接改 recorded state",),
            notes="manual transition review replaced by deterministic transition validation",
            completion_evidence=("policy=deterministic_health_transition_validation",),
        ),
        _gate(
            item_id="exit:outcome-maturity",
            category="automated_evidence",
            title="Exit outcomes 依 horizon 自動成熟",
            status="insufficient_evidence",
            owner="evidence-scheduler",
            decision_date=decision_date,
            progress_bp=0,
            required_artifacts=("matured exit outcome registry",),
            validation_commands=("python scripts/inspect_v3_evidence_effectiveness.py ...",),
            completion_rules=("matured exit outcomes meet sample floor",),
            prohibited_actions=shared_prohibited,
            notes="no mature denominator is available at closeout",
        ),
        _gate(
            item_id="ml:shadow-days",
            category="automated_evidence",
            title="四條 alpha lane 自動累積 20 個 Shadow 交易日",
            status="insufficient_evidence",
            owner="ml-copilot-scheduler",
            decision_date=decision_date,
            progress_bp=0,
            required_artifacts=("allocation shadow replay registry",),
            validation_commands=("python scripts/run_ml_allocation_copilot.py ...",),
            completion_rules=("20 causal observed trading days with matured labels",),
            prohibited_actions=shared_prohibited,
            notes="lane execution starts now; historical replay does not count as elapsed days",
        ),
        _gate(
            item_id="ml:promotion-policy",
            category="policy_decision",
            title="採用 allocation-promotion-v4 自動 promotion/rollback",
            status="complete",
            owner="ml-promotion-policy",
            decision_date=decision_date,
            progress_bp=10_000,
            required_artifacts=("machine promotion policy tests",),
            validation_commands=("pytest tests/test_ml_allocation_validation.py -q",),
            completion_rules=("smallest passing alpha or atomic alpha=0",),
            prohibited_actions=(
                "不得手動硬改 formal_oos_allowed",
                "不得手動硬改 production blend alpha",
                "不得把 historical seen period 改稱 Formal OOS",
            ),
            notes="candidate alpha bp: 0,2000,3500,5000",
            completion_evidence=("policy=allocation-promotion-v4",),
        ),
        _gate(
            item_id="ml:revalidation",
            category="ml_revalidation",
            title="V4 全資料配置型 ML revalidation",
            status="in_progress",
            owner="ml-copilot-scheduler",
            decision_date=decision_date,
            progress_bp=2500,
            required_artifacts=(
                "dataset/feature manifests",
                "four OOS folds",
                "calibration/drift",
                "portfolio lane comparison",
                "promotion authorization",
            ),
            validation_commands=(
                "python scripts/build_ml_revalidation_runbook.py --trigger production_promotion ...",
            ),
            completion_rules=("all allocation-promotion-v4 evidence is machine-verifiable",),
            prohibited_actions=shared_prohibited,
            notes="runbook and policy are active; insufficient evidence keeps alpha=0",
        ),
        _gate(
            item_id="release:rule-operational",
            category="policy_decision",
            title="Rule-only Decision/Advice/Paper operational production",
            status="complete",
            owner="release-policy",
            decision_date=decision_date,
            progress_bp=10_000,
            required_artifacts=("Rule allocation and scheduler validation",),
            validation_commands=("pytest", "mypy ui_qt app_module data_module ..."),
            completion_rules=("Rule path passes QA with broker execution disabled",),
            prohibited_actions=("不得自動連接券商或送單",),
            notes=(
                f"corporate_action_coverage={corporate_actions.get('status', 'missing')}; "
                "affected horizons fail closed; ML influence remains machine-gated"
            ),
            completion_evidence=("scope=decision_advice_paper_allocation_no_broker",),
        ),
        _gate(
            item_id="release:formal-gates",
            category="automated_evidence",
            title="V4 ML 非零權重正式 Gate",
            status="insufficient_evidence",
            owner="release-scheduler",
            decision_date=decision_date,
            progress_bp=0,
            required_artifacts=("promotion authorization with non-zero selected alpha",),
            validation_commands=("python scripts/run_ml_allocation_copilot.py ...",),
            completion_rules=("all promotion thresholds pass for a non-zero lane",),
            prohibited_actions=shared_prohibited,
            notes=(
                "Rule operational production is enabled independently; "
                "ML remains Production Co-pilot with alpha=0 until evidence matures"
            ),
        ),
    )
    latest = current_revisions or {}
    return tuple(
        {
            **item,
            "revision": _non_negative_int(latest.get(item["item_id"], 0)) + 1,
        }
        for item in revisions
    )


def _source_disposition(row: Mapping[str, Any]) -> str:
    if (
        row.get("machine_status") == "verified"
        and row.get("pit_status") in {
            "pit_date_verified",
            "official_publication_timestamp_verified",
        }
        and not row.get("remaining_blocker")
    ):
        return "accepted"
    if row.get("machine_status") == "missing":
        return "blocked_no_provenance"
    return "research_shadow"


def _gate(
    *,
    item_id: str,
    category: str,
    title: str,
    status: str,
    owner: str,
    decision_date: str,
    progress_bp: int,
    required_artifacts: Sequence[str],
    validation_commands: Sequence[str],
    completion_rules: Sequence[str],
    prohibited_actions: Sequence[str],
    notes: str,
    completion_evidence: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "revision": 1,
        "category": category,
        "title": title,
        "status": status,
        "owner": owner,
        "earliest_validation_date": decision_date,
        "progress_bp": progress_bp,
        "required_artifacts": list(required_artifacts),
        "validation_commands": list(validation_commands),
        "completion_rules": list(completion_rules),
        "prohibited_actions": list(prohibited_actions),
        "notes": notes,
        "completion_evidence": list(completion_evidence),
    }


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _file_hash(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _current_revisions(path: Path | None) -> dict[str, int]:
    if path is None or not path.is_file():
        return {}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        table_exists = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type = 'table' AND name = 'engineering_gate_revisions'"""
        ).fetchone()
        if table_exists is None:
            return {}
        return {
            str(item_id): _non_negative_int(revision)
            for item_id, revision in connection.execute(
                """SELECT item_id, MAX(revision)
                   FROM engineering_gate_revisions
                   GROUP BY item_id"""
            ).fetchall()
        }


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected a non-negative integer")
    return value


def _positive_int(value: object) -> int:
    numeric = _non_negative_int(value)
    if numeric <= 0:
        raise ValueError("expected a positive integer")
    return numeric


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--pre-v2", type=Path, required=True)
    parser.add_argument("--p0-audit", type=Path, required=True)
    parser.add_argument("--pit-coverage", type=Path, required=True)
    parser.add_argument(
        "--registry-db",
        type=Path,
        help="Optional existing append-only registry used to assign next revisions.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    revisions = build_gate_revisions(
        decision_date=args.decision_date,
        pre_v2=_load_json(args.pre_v2),
        p0_audit=_load_json(args.p0_audit),
        pit_coverage=_load_json(args.pit_coverage),
        evidence_hashes={
            "pre_v2": _file_hash(args.pre_v2),
            "p0_audit": _file_hash(args.p0_audit),
            "pit_coverage": _file_hash(args.pit_coverage),
        },
        current_revisions=_current_revisions(args.registry_db),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(revisions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "revision_count": len(revisions),
                "complete_count": sum(
                    1 for item in revisions if item["status"] == "complete"
                ),
                "insufficient_evidence_count": sum(
                    1
                    for item in revisions
                    if item["status"] == "insufficient_evidence"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
