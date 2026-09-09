"""建立下一個 Formal clock 的明確 producer preparation plan。

本模組只讀取明確傳入的來源路徑，產生一份 hash-bound、create-only 的
準備計畫。它不選最新檔案、不建立 clock、不抓取行情、不寫 D 槽資料，也
不更新 Windows controlled environment。activation date、clock identity 和
所有輸出根目錄都必須由呼叫端明確傳入，避免把候選 artifact 誤當成正式
input。
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from data_module.prospective_formal_clock import canonical_json, file_sha256, payload_hash


FORMAL_NEXT_CLOCK_PREPARATION_SCHEMA_VERSION = (
    "formal-next-clock-preparation-plan.v1"
)
PIT_CAPTURE_START = time(7, 0)
PIT_CAPTURE_CUTOFF = time(8, 30)
PIT_SIDECAR_START = time(9, 0)
RULE_SESSION_START = time(9, 0)
RULE_SESSION_END = time(13, 30)
PAPER_EOD_SOURCE_START = time(15, 0)


class FormalNextClockPreparationError(ValueError):
    """下一個 Formal clock preparation plan 無法形成。"""


def build_formal_next_clock_preparation_plan(
    *,
    observed: datetime,
    activation_date: date,
    planned_clock_id: str,
    controlled_clock_root: Path,
    clock_candidate_manifest: Path,
    official_calendar_bundle: Path,
    twse_calendar_cache: Path | None,
    market_db: Path,
    publication_root: Path,
    paper_snapshot_db: Path,
    paper_fill_db: Path,
    identity_manifest: Path,
    clock_planning_report: Path | None = None,
    prior_day_pit_operational: Path | None = None,
    prior_day_pit_receipt: Path | None = None,
    paper_schedule_evidence: Mapping[str, object] | None = None,
    owner_decision_id: str | None = None,
    owner_decision_timestamp: str | None = None,
    existing_calendar_capture_root: Path | None = None,
) -> dict[str, object]:
    """建立具體的下一日 producer chain 計畫。

    ``official_calendar_bundle`` 與 ``clock_candidate_manifest`` 即使尚未
    產生也必須傳入精確目標路徑；缺件會成為 blocker，絕不以 output 掃描或
    目錄排序猜選。計畫的 consumer target 則固定由明確的
    ``controlled_clock_root`` 展開，供 root 審核後再交給 handoff builder。
    """

    observed_at = _aware_datetime(observed, "observed")
    if type(activation_date) is not date:
        raise FormalNextClockPreparationError("activation_date must be a date")
    planned_id = _required_text(planned_clock_id, "planned_clock_id")
    controlled_root = _absolute_path(controlled_clock_root, "controlled_clock_root")
    clock_candidate = _absolute_path(
        clock_candidate_manifest, "clock_candidate_manifest"
    )
    clock_plan_report = (
        _absolute_path(clock_planning_report, "clock_planning_report")
        if clock_planning_report is not None
        else None
    )
    calendar_bundle = _absolute_path(
        official_calendar_bundle, "official_calendar_bundle"
    )
    market_path = _absolute_path(market_db, "market_db")
    publication_path = _absolute_path(publication_root, "publication_root")
    snapshot_path = _absolute_path(paper_snapshot_db, "paper_snapshot_db")
    fill_path = _absolute_path(paper_fill_db, "paper_fill_db")
    identity_path = _absolute_path(identity_manifest, "identity_manifest")
    prior_operational_path = (
        _absolute_path(prior_day_pit_operational, "prior_day_pit_operational")
        if prior_day_pit_operational is not None
        else None
    )
    prior_receipt_path = (
        _absolute_path(prior_day_pit_receipt, "prior_day_pit_receipt")
        if prior_day_pit_receipt is not None
        else None
    )
    cache_path = (
        _absolute_path(twse_calendar_cache, "twse_calendar_cache")
        if twse_calendar_cache is not None
        else None
    )
    archive_root = (
        _absolute_path(existing_calendar_capture_root, "existing_calendar_capture_root")
        if existing_calendar_capture_root is not None
        else publication_path / "pit_candidate_archive"
    )

    observed_taipei = observed_at.astimezone(_taipei_zone())
    activation_text = activation_date.isoformat()
    date_token = activation_date.strftime("%Y%m%d")
    blockers: list[str] = []
    if activation_date <= observed_taipei.date():
        blockers.append("activation_date_must_be_after_observed_taipei_date")
    if date_token not in planned_id:
        blockers.append("planned_clock_id_must_bind_activation_date")
    if owner_decision_timestamp is not None and owner_decision_timestamp.strip():
        parsed_owner_decision = _parse_aware_timestamp(
            owner_decision_timestamp,
            "owner_decision_timestamp",
        )
        if parsed_owner_decision is None:
            blockers.append("owner_decision_timestamp_invalid")
        elif parsed_owner_decision > observed_at:
            blockers.append("owner_decision_timestamp_after_observed")
    schedule_evidence = _normalize_schedule_evidence(paper_schedule_evidence)

    calendar_projection, calendar_blockers = _inspect_calendar_bundle(
        calendar_bundle,
        activation_date=activation_date,
    )
    blockers.extend(calendar_blockers)
    market_projection = _inspect_file(market_path, role="D market source")
    if market_projection["exists"] is not True:
        blockers.append("market_db_missing")
    cache_projection = (
        _inspect_file(cache_path, role="TWSE calendar cache")
        if cache_path is not None
        else {
            "path": None,
            "exists": False,
            "role": "TWSE calendar cache",
            "read_only": True,
        }
    )
    if cache_path is None or cache_projection["exists"] is not True:
        blockers.append("twse_calendar_cache_missing")

    snapshot_projection = _inspect_file(snapshot_path, role="Paper snapshot source")
    fill_projection = _inspect_file(fill_path, role="Paper fill source")
    if snapshot_projection["exists"] is not True:
        blockers.append("paper_snapshot_source_missing")
    # The fill is a final release gate.  Its absence must not stop the
    # independent calendar/PIT/Rule preparation that can be completed now.

    publication_projection = _inspect_directory(
        publication_path, role="durable publication root"
    )
    if publication_projection["exists"] is not True:
        blockers.append("publication_root_missing")

    current_capture_projection = _inspect_pit_capture_day(
        archive_root, activation_date=activation_date
    )
    if current_capture_projection["distinct_capture_count"] != 0:
        blockers.append("activation_day_already_has_pit_captures_review_required")
    prior_day_pit_projection, prior_day_pit_blockers = _inspect_prior_day_pit(
        prior_operational_path,
        prior_receipt_path,
        activation_date=activation_date,
        observed=observed_at,
    )
    blockers.extend(prior_day_pit_blockers)

    target_paths = {
        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH": str(
            controlled_root / "portfolio_ledger" / "manifest.json"
        ),
        "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH": str(
            controlled_root / "rule_champion_history" / "manifest.json"
        ),
        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH": str(
            controlled_root / "pit_sector_membership" / "manifest.json"
        ),
    }
    publication_paths = {
        "rule_history_manifest": str(
            publication_path / "rule_history" / activation_text / "manifest.json"
        ),
        "pit_sidecar": str(
            publication_path
            / "pit_sector_membership_formal"
            / activation_text
            / "sidecar.json"
        ),
        "pit_receipt": str(
            publication_path
            / "pit_sector_membership_formal"
            / activation_text
            / "receipt.json"
        ),
        "causal_ledger_run_directory": str(
            publication_path
            / "causal_ledger"
            / f"{activation_text}-<snapshot_hash_12>-<fill_hash_12>"
        ),
        "paper_snapshot_source": str(snapshot_path),
        "paper_fill_source": str(fill_path),
        "identity_manifest": str(identity_path),
    }

    producer_artifacts = _producer_artifacts(
        activation_date=activation_date,
        planned_clock_id=planned_id,
        calendar_bundle=calendar_bundle,
        clock_candidate=clock_candidate,
        clock_planning_report=clock_plan_report,
        publication_root=publication_path,
        target_paths=target_paths,
        publication_paths=publication_paths,
        snapshot_path=snapshot_path,
        fill_path=fill_path,
        identity_path=identity_path,
        prior_day_pit_operational=prior_operational_path,
        prior_day_pit_receipt=prior_receipt_path,
        paper_schedule_evidence=schedule_evidence,
    )
    commands = _root_commands(
        activation_date=activation_date,
        planned_clock_id=planned_id,
        calendar_bundle=calendar_bundle,
        clock_candidate=clock_candidate,
        market_path=market_path,
        publication_path=publication_path,
        snapshot_path=snapshot_path,
        fill_path=fill_path,
        identity_path=identity_path,
        target_paths=target_paths,
        paper_schedule_evidence=schedule_evidence,
        prior_day_pit_operational=prior_operational_path,
        prior_day_pit_receipt=prior_receipt_path,
        clock_planning_report=clock_plan_report,
        observed_at=observed_at,
        owner_decision_timestamp=owner_decision_timestamp,
    )

    body: dict[str, object] = {
        "schema_version": FORMAL_NEXT_CLOCK_PREPARATION_SCHEMA_VERSION,
        "observed_at": observed_at.isoformat(),
        "observed_taipei_date": observed_taipei.date().isoformat(),
        "activation_trading_day": activation_text,
        "earliest_legal_activation_candidate": activation_text,
        "minimum_preparation_days": 1,
        "planned_clock": {
            "clock_id": planned_id,
            "clock_candidate_manifest": str(clock_candidate),
            "clock_planning_report": (
                str(clock_plan_report) if clock_plan_report is not None else None
            ),
            "controlled_clock_root": str(controlled_root),
            "formal_clock_created": False,
            "owner_decision_id": owner_decision_id,
            "owner_decision_timestamp": owner_decision_timestamp,
        },
        "legal_windows_taipei": {
            "pit_capture": "07:00-08:30",
            "pit_postcutoff_sidecar": "09:00 or later; read archive only",
            "rule_source": "09:00-13:30",
            "paper_eod_source": "15:00 or later",
            "paper_eod_wrapper": schedule_evidence,
        },
        "calendar_evidence": calendar_projection,
        "preliminary_twse_cache": cache_projection,
        "paper_schedule_evidence": schedule_evidence,
        "source_evidence": {
            "market_db": market_projection,
            "paper_snapshot_db": snapshot_projection,
            "paper_fill_db": fill_projection,
            "publication_root": publication_projection,
            "pit_capture_day": current_capture_projection,
            "prior_day_pit_operational": prior_day_pit_projection,
        },
        "target_paths": target_paths,
        "publication_paths": publication_paths,
        "producer_artifacts": producer_artifacts,
        "root_auditable_commands": commands,
        "source_to_formal_order": [
            "official calendar bundle -> explicit prospective clock candidate",
            "D-1 PIT capture -> timestamp-gated operational candidate for D pre-cutoff -> one archive/sidecar",
            "Rule natural session -> durable Rule history manifest and receipt",
            "Paper EOD source -> frozen recommendation -> real fill receipt -> atomic Paper ledger",
            "Paper snapshot + Paper fills -> hash-bound causal ledger publication",
            "three exact Formal consumers -> common identity manifest -> handoff plan",
        ],
        "gates": {
            "candidate_clock_only_until_owner_decision": True,
            "pit_single_capture_required": True,
            "d_minus_one_pit_may_supply_pre_cutoff_decision": True,
            "d_minus_one_effective_from_must_remain_capture_date": True,
            "paper_fill_requires_real_source_rows": True,
            "causal_ledger_requires_snapshot_and_fill_custody": True,
            "all_three_consumer_readbacks_required": True,
            "controlled_update_is_one_atomic_owner_operation": True,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "historical_backfill_claimed": False,
        },
        "blockers": sorted(set(blockers)),
        "final_release_blockers": sorted(
            set(
                ["paper_fill_source_missing"]
                if fill_projection["exists"] is not True
                else []
            )
        ),
        "status": "blocked" if blockers else "ready_for_root_review",
        "read_only": True,
        "writes_formal_controlled_paths": False,
        "writes_market_database": False,
        "secret_values_emitted": False,
        "rollback": {
            "old_paths_remain_unchanged": True,
            "new_paths_are_not_applied_by_this_plan": True,
            "on_post_update_mismatch": "restore all three saved old values as one operation; retain candidate receipts; keep formal_oos_allowed=false",
            "rollback_target_is_current_runtime_attestation": True,
        },
    }
    return {**body, "plan_hash": payload_hash(body)}


def write_immutable_formal_next_clock_preparation_plan(
    output_path: Path,
    plan: Mapping[str, object],
) -> str:
    """以 create-only、fsync 的 canonical JSON 保存準備計畫。"""

    _validate_plan_hash(plan)
    output = output_path.expanduser().resolve()
    if not output.parent.is_dir():
        raise FormalNextClockPreparationError(
            "preparation plan output parent must already exist"
        )
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(plan)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise FormalNextClockPreparationError(
            "preparation plan output already exists"
        ) from error
    return file_sha256(output)


def _producer_artifacts(
    *,
    activation_date: date,
    planned_clock_id: str,
    calendar_bundle: Path,
    clock_candidate: Path,
    clock_planning_report: Path | None,
    publication_root: Path,
    target_paths: Mapping[str, str],
    publication_paths: Mapping[str, str],
    snapshot_path: Path,
    fill_path: Path,
    identity_path: Path,
    prior_day_pit_operational: Path | None,
    prior_day_pit_receipt: Path | None,
    paper_schedule_evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    day = activation_date.isoformat()
    planning_artifact: dict[str, object] = {
        "name": "prospective_clock_planning_report",
        "owner": "formal_paper",
        "output_path": str(clock_planning_report) if clock_planning_report is not None else None,
        "natural_window": "after durable calendar raw-custody readback",
        "depends_on": [str(calendar_bundle), planned_clock_id],
        "consumer": "data_module.prospective_clock_planner.plan_next_prospective_clock",
        "candidate_only": True,
        "current_state": (
            "produced_and_verified"
            if clock_planning_report is not None and clock_planning_report.is_file()
            else "not_created"
        ),
    }
    return [
        {
            "name": "official_calendar_bundle",
            "owner": "formal_paper",
            "output_path": str(calendar_bundle),
            "natural_window": "bounded official capture before clock planning",
            "depends_on": ["TWSE annual response", "TPEX monthly response"],
            "consumer": "data_module.prospective_clock_planner.plan_next_prospective_clock",
            "candidate_only": True,
            "current_state": (
                "durable_candidate_supplied"
                if calendar_bundle.is_file()
                else "missing_until_explicit_official_capture"
            ),
        },
        planning_artifact,
        {
            "name": "prospective_clock_candidate",
            "owner": "formal_paper",
            "output_path": str(clock_candidate),
            "natural_window": "after owner decision and official bundle verification",
            "depends_on": [str(calendar_bundle), planned_clock_id],
            "consumer": "data_module.prospective_formal_clock.load_clock_manifest_for_capture",
            "candidate_only": True,
            "current_state": (
                "produced_candidate"
                if _is_formal_clock_candidate(clock_candidate)
                else "not_created"
            ),
        },
        {
            "name": "pit_preopen_archive",
            "owner": "formal_paper",
            "output_path": str(
                publication_root / "pit_candidate_archive" / day / "<capture_hash>-<receipt_hash>"
            ),
            "natural_window": "Taipei 07:00-08:30; one capture only",
            "depends_on": ["official TWSE/TPEX PIT source", "independent denominator"],
            "consumer": "data_module.formal_pit_history_handoff",
            "candidate_only": True,
            "current_state": "not_created_for_activation_day",
        },
        {
            "name": "pit_d_minus_one_operational_candidate",
            "owner": "formal_paper",
            "output_path": (
                str(prior_day_pit_operational)
                if prior_day_pit_operational is not None
                else None
            ),
            "receipt_path": (
                str(prior_day_pit_receipt)
                if prior_day_pit_receipt is not None
                else None
            ),
            "natural_window": "D-1 after official response and receipt evaluation; D decision may consume after available_at",
            "depends_on": ["current code official raw capture", "real receipt evaluation timestamp"],
            "consumer": "data_module.pit_sector_machine_publisher.consume_machine_pit_operational_candidate",
            "candidate_only": True,
            "effective_from_policy": "must remain the capture Taipei natural date",
            "current_state": "provided_explicitly" if prior_day_pit_operational is not None else "not_supplied",
        },
        {
            "name": "pit_formal_sidecar",
            "owner": "formal_paper",
            "output_path": publication_paths["pit_sidecar"],
            "receipt_path": publication_paths["pit_receipt"],
            "natural_window": "Taipei 09:00 or later; archive readback only",
            "depends_on": ["single preopen archive", "coverage start", "denominator", "formal store/HMAC"],
            "consumer": "data_module.formal_pit_sector_publisher.read_formal_pit_sector_receipt",
            "candidate_only": True,
            "current_state": "blocked_until_archive_and_coverage",
        },
        {
            "name": "rule_history_publication",
            "owner": "formal_paper",
            "output_path": publication_paths["rule_history_manifest"],
            "natural_window": "Taipei 09:00-13:30",
            "depends_on": ["validated clock", "owner acceptance", "universe symbols", "read-only market source"],
            "consumer": "data_module.rule_champion_snapshot_service.load_verified_rule_champion_snapshot_history",
            "candidate_only": True,
            "current_state": "must_be_produced_on_activation_day",
        },
        {
            "name": "paper_fill_and_ledger",
            "owner": "formal_paper",
            "output_path": str(fill_path),
            "paper_snapshot_source": str(snapshot_path),
            "natural_window": {
                "source_available_taipei": "15:00 or later",
                "scheduler": dict(paper_schedule_evidence),
            },
            "depends_on": ["official daily_prices rows", "frozen pending recommendation", "real fill receipt"],
            "consumer": "app_module.paper_trade_ledger.PaperTradeLedgerRepository.append_many",
            "candidate_only": False,
            "current_state": "fill_source_missing; no fill may be fabricated",
        },
        {
            "name": "causal_ledger_publication",
            "owner": "formal_paper",
            "output_path": publication_paths["causal_ledger_run_directory"],
            "natural_window": "after Paper snapshot and real fill commit readback",
            "depends_on": [str(snapshot_path), str(fill_path), "Decimal cash/fee/tax reconciliation"],
            "consumer": "data_module.formal_portfolio_ledger.load_formal_portfolio_state_ledger",
            "candidate_only": True,
            "current_state": "blocked_until_real_fill_source_and_two boundaries",
        },
        {
            "name": "common_identity_manifest",
            "owner": "formal_paper",
            "output_path": str(identity_path),
            "natural_window": "after all three exact consumer readbacks",
            "depends_on": [target_paths[name] for name in target_paths],
            "consumer": "data_module.formal_controlled_handoff.build_formal_controlled_handoff_plan",
            "candidate_only": True,
            "current_state": "not_created",
        },
    ]


def _root_commands(
    *,
    activation_date: date,
    planned_clock_id: str,
    calendar_bundle: Path,
    clock_candidate: Path,
    market_path: Path,
    publication_path: Path,
    snapshot_path: Path,
    fill_path: Path,
    identity_path: Path,
    target_paths: Mapping[str, str],
    paper_schedule_evidence: Mapping[str, object],
    prior_day_pit_operational: Path | None,
    prior_day_pit_receipt: Path | None,
    clock_planning_report: Path | None,
    observed_at: datetime,
    owner_decision_timestamp: str | None,
) -> list[dict[str, object]]:
    day = activation_date.isoformat()
    repo = Path.cwd().resolve()
    python = ".\\.venv\\Scripts\\python.exe"
    if prior_day_pit_operational is not None and prior_day_pit_receipt is not None:
        prior_pit_command = (
            f'{python} -c "from datetime import datetime, timezone; from pathlib import Path; '
            f'from data_module.pit_sector_machine_publisher import consume_machine_pit_operational_candidate; '
            f'r=consume_machine_pit_operational_candidate(Path(r\'{prior_day_pit_operational}\'), '
            'decision_at=datetime.now(timezone.utc)); '
            'print({k:r[k] for k in ("status","available_at","effective_from","capture_id","row_count","source_custody_verified","rows_rebuilt_from_raw")})"'
        )
        prior_pit_purpose = (
            "沿用明確 D-1 operational candidate 供 D 08:30 前 consumer；"
            "不等待同日 capture，也不產生歷史補記"
        )
        prior_pit_readback = (
            f"{prior_day_pit_operational} + {prior_day_pit_receipt} exact readback; "
            f"effective_from={activation_date - __import__('datetime').timedelta(days=1)}; "
            "available_at <= D 08:30 Asia/Taipei; D decision_at >= available_at"
        )
    else:
        prior_pit_command = "provide explicit D-1 operational candidate and receipt; do not fetch same-day as a substitute"
        prior_pit_purpose = "D-1 PIT candidate 未提供，pre-cutoff consumer 必須 fail closed"
        prior_pit_readback = "operational candidate + receipt are required before D 08:30"

    calendar_readback_command = (
        f'{python} -c "import json; from datetime import date; from pathlib import Path; '
        f'from data_module.formal_next_clock_preparation import _inspect_calendar_bundle; '
        f'p=Path(r\'{calendar_bundle}\'); projection,blockers=_inspect_calendar_bundle('
        f'p, activation_date=date.fromisoformat(\'{day}\')); '
        "print(json.dumps({'projection': projection, 'blockers': blockers}, "
        "ensure_ascii=False, sort_keys=True))\""
    )
    if clock_planning_report is not None and clock_planning_report.is_file():
        planning_readback_command = (
            f'{python} -c "import json; from pathlib import Path; '
            f'p=Path(r\'{clock_planning_report}\'); d=json.loads(p.read_text(encoding=\'utf-8\')); '
            "print({k:d.get(k) for k in ('schema_version','status','clock_id',"
            "'activation_trading_day','plan_hash')})\""
        )
        planning_purpose = (
            "讀回已完成的 planner report；它是 prospective planning evidence，"
            "不把 report 當 immutable clock，也不重跑 network/寫入既有檔"
        )
        planning_readback = (
            f"{clock_planning_report} exact readback; schema=prospective-formal-clock-planning.v1; "
            f"status=candidate_ready; clock_id={planned_clock_id}; activation={day}"
        )
    else:
        owner_arg = (
            f" --owner-decision-timestamp {owner_decision_timestamp}"
            if owner_decision_timestamp is not None and owner_decision_timestamp.strip()
            else ""
        )
        planning_output = (
            repo
            / "output"
            / "v4_next_formal"
            / f"formal_clock_planning_{activation_date.strftime('%Y%m%d')}.json"
        )
        planning_readback_command = (
            f'{python} scripts\\plan_prospective_formal_clock.py --now {observed_at.isoformat()}'
            f'{owner_arg} --calendar-evidence "{calendar_bundle}" --minimum-preparation-days 1 '
            f'--lookahead-days 31 --clock-id-prefix clock:prospective: --output "{planning_output}"'
        )
        planning_purpose = (
            "在已具 owner decision 且 calendar custody 通過時建立 create-only planning report；"
            "不能把缺 owner 的狀態偽裝成完成"
        )
        planning_readback = "planner must return status=candidate_ready with explicit plan_hash"
    clock_readback_command = (
        f'{python} -c "from datetime import datetime; from pathlib import Path; '
        f'from data_module.prospective_formal_clock import load_clock_manifest; '
        f'c=load_clock_manifest(Path(r\'{clock_candidate}\'), '
        f'now=datetime.fromisoformat(\'{observed_at.isoformat()}\')); '
        "print({'clock_id': c.clock_id, 'activation_trading_day': "
        "c.activation_trading_day.isoformat(), 'manifest_hash': c.manifest_hash})\""
    )
    development_output = (
        Path(os.environ.get("TEMP", str(repo / "temp"))).resolve()
        / "baldr_formal_rule_development"
    )
    handoff_output = (
        repo
        / "output"
        / "v4_next_formal"
        / f"formal_controlled_handoff_{activation_date.strftime('%Y%m%d')}.json"
    )
    return [
        {
            "step": 1,
            "when": "now/read-only",
            "purpose": "以當下 process clock 驗證 D market 與 TWSE cache，不改來源",
            "command": f'{python} -c "from data_module.official_trading_calendar import OfficialTradingCalendar; from pathlib import Path; c=OfficialTradingCalendar(db_path=r\'{market_path}\', calendar_cache_path=r\'output\\paper_execution_eod_replay\\calendar_cache\\twse_holiday_schedule_2026_20260907_capture1.json\'); print(c.is_official_trading_day(__import__(\'datetime\').date.fromisoformat(\'{day}\'), allow_online_probe=False))"',
        },
        {
            "step": 2,
            "when": "now/read-only",
            "purpose": "讀回已持久化的 exact calendar bundle/raw custody；不重抓、不覆寫 durable 或 TEMP 來源",
            "command": calendar_readback_command,
            "required_readback": f"{calendar_bundle} exact bundle + raw/metadata sidecars verified; activation={day} TWSE/TPEX=true; candidate_only=true; formal_clock_created=false",
        },
        {
            "step": 3,
            "when": "now/read-only if report exists; otherwise after explicit owner decision",
            "purpose": planning_purpose,
            "command": planning_readback_command,
            "required_readback": planning_readback,
        },
        {
            "step": 4,
            "when": "now/read-only before activation",
            "purpose": "讀回 immutable clock manifest；與 planner report 分離，並以實際 observed timestamp 驗 hash/日期/安全旗標",
            "command": clock_readback_command,
            "required_readback": f"{clock_candidate} exact manifest loads; clock_id={planned_clock_id}; activation={day}; status=planned; formal_oos_allowed=false; no controlled write",
        },
        {
            "step": 5,
            "when": f"before Taipei {PIT_CAPTURE_CUTOFF.strftime('%H:%M')} on {day}",
            "purpose": prior_pit_purpose,
            "command": prior_pit_command,
            "required_readback": prior_pit_readback,
        },
        {
            "step": 6,
            "when": f"Taipei {PIT_CAPTURE_START.strftime('%H:%M')}-{PIT_CAPTURE_CUTOFF.strftime('%H:%M')} on {day}; only if D current-day archive is required",
            "purpose": "若 coverage contract 要求 D natural-day archive，建立單一官方 capture；D-1 reuse 不因等待這份 archive 而阻擋 pre-cutoff consumer",
            "command": "cmd /c scripts\\scheduled\\run_pit_sector_membership_preopen_capture.cmd",
            "required_readback": f"if run: archive effective_from={day}; captured_at and archived_at < {day}T08:30:00+08:00; one archive only; multiple distinct captures fail closed",
        },
        {
            "step": 7,
            "when": f"Taipei {PIT_SIDECAR_START.strftime('%H:%M')} or later on {day}",
            "purpose": "從 preopen archive 建立 PIT history/sidecar；不重新抓同日官方來源",
            "command": "cmd /c scripts\\scheduled\\run_formal_pit_sidecar_postcutoff.cmd",
            "required_readback": f"{publication_path / 'pit_sector_membership_formal' / day / 'sidecar.json'} and receipt.json are exact-consumer verified",
        },
        {
            "step": 8,
            "when": f"Taipei {RULE_SESSION_START.strftime('%H:%M')}-{RULE_SESSION_END.strftime('%H:%M')} on {day}",
            "purpose": "同一 proposed clock 建立 Rule history durable publication",
            "command": "cmd /c scripts\\scheduled\\run_formal_rule_source_preopen.cmd",
            "required_readback": f"{publication_path / 'rule_history' / day / 'manifest.json'} loads with formal_ready=true and exact clock hash",
        },
        {
            "step": 9,
            "when": {
                "paper_source_available_taipei": PAPER_EOD_SOURCE_START.strftime("%H:%M") + " or later",
                "scheduler": dict(paper_schedule_evidence),
                "activation_date": day,
            },
            "purpose": "先完成同日 frozen Paper pending 的真實 source->fill->ledger retry",
            "command": "cmd /c scripts\\scheduled\\run_paper_execution_daily_isolated.cmd",
            "required_readback": f"source rows/date/version guard, real fill receipt, then {fill_path} append/readback; no snapshot-derived fill",
        },
        {
            "step": 10,
            "when": "after steps 5-9 and Paper snapshot boundary exists",
            "purpose": "執行 repo publication 的 formal daily producer，建立 causal ledger",
            "command": "cmd /c scripts\\scheduled\\run_formal_input_producer_daily.cmd",
            "required_readback": f"{publication_path / 'causal_ledger'}\\<run_id>\\manifest.json + receipt.json + portfolio_ledger.sqlite pass exact consumer",
        },
        {
            "step": 11,
            "when": "after all three durable publications exist",
            "purpose": "以 exact paths 建立 common identity 並形成 root review plan",
            "command": f'{python} scripts\\qa_formal_controlled_handoff_plan.py --market-db "{market_path}" --training-as-of {observed_at.isoformat()} --output-root "{repo / "output" / "formal_daily_publications"}" --development-output-root "{development_output}" --proposed-portfolio-ledger "{target_paths["BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"]}" --proposed-rule-history "{target_paths["BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"]}" --proposed-pit-sector "{target_paths["BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"]}" --proposed-clock-manifest "{clock_candidate}" --proposed-identity-manifest "{identity_path}" --output "{handoff_output}"',
            "required_readback": "status=ready_for_root_review only when all three supplied paths exist and exact consumer readbacks plus common identity pass",
        },
    ]


def _inspect_calendar_bundle(
    path: Path,
    *,
    activation_date: date,
) -> tuple[dict[str, object], list[str]]:
    projection: dict[str, object] = {
        "path": str(path),
        "exists": path.is_file(),
        "schema_version": None,
        "bundle_hash": None,
        "file_hash": None,
        "activation_day": activation_date.isoformat(),
        "twse_open": None,
        "tpex_open": None,
        "candidate_only": None,
        "formal_clock_created": None,
        "raw_custody": None,
        "read_only": True,
    }
    blockers: list[str] = []
    if not path.is_file():
        blockers.append("official_calendar_bundle_missing")
        return projection, blockers
    projection["file_hash"] = file_sha256(path)
    try:
        raw: object = __import__("json").loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        blockers.append("official_calendar_bundle_unreadable")
        return projection, blockers
    if not isinstance(raw, Mapping):
        blockers.append("official_calendar_bundle_root_invalid")
        return projection, blockers
    projection["schema_version"] = raw.get("schema_version")
    projection["bundle_hash"] = raw.get("bundle_hash")
    projection["candidate_only"] = raw.get("candidate_only")
    projection["formal_clock_created"] = raw.get("formal_clock_created")
    if raw.get("schema_version") != "official-trading-calendar-bundle.v1":
        blockers.append("official_calendar_bundle_schema_invalid")
    body = dict(raw)
    body.pop("bundle_hash", None)
    if raw.get("bundle_hash") != payload_hash(body):
        blockers.append("official_calendar_bundle_hash_invalid")
    raw_projection, raw_blockers = _inspect_calendar_raw_custody(path, raw)
    projection["raw_custody"] = raw_projection
    blockers.extend(raw_blockers)
    days = raw.get("days")
    row = next(
        (item for item in days if isinstance(item, Mapping) and item.get("date") == activation_date.isoformat()),
        None,
    ) if isinstance(days, list) else None
    if row is None:
        blockers.append("official_calendar_bundle_activation_day_missing")
    else:
        twse = row.get("twse")
        tpex = row.get("tpex")
        projection["twse_open"] = isinstance(twse, Mapping) and twse.get("is_trading_day") is True
        projection["tpex_open"] = isinstance(tpex, Mapping) and tpex.get("is_trading_day") is True
        if projection["twse_open"] is not True:
            blockers.append("official_calendar_bundle_twse_activation_day_not_open")
        if projection["tpex_open"] is not True:
            blockers.append("official_calendar_bundle_tpex_activation_day_not_open")
    if raw.get("candidate_only") is not True:
        blockers.append("official_calendar_bundle_must_remain_candidate_only")
    if raw.get("formal_clock_created") is not False:
        blockers.append("official_calendar_bundle_must_not_create_clock")
    return projection, blockers


def _is_formal_clock_candidate(path: Path) -> bool:
    """辨識 immutable prospective clock candidate，不宣稱 ML lineage 有效。"""

    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(raw, Mapping)
        and raw.get("schema_version") == "prospective-formal-simulated-portfolio-clock.v1"
        and raw.get("status") == "planned"
        and raw.get("mode") == "prospective_formal_simulation"
        and raw.get("real_money") is False
        and raw.get("broker_execution") is False
        and raw.get("historical_backfill_claimed") is False
        and isinstance(raw.get("manifest_hash"), str)
    )


def _inspect_calendar_raw_custody(
    bundle_path: Path,
    bundle: Mapping[str, object],
) -> tuple[dict[str, object], list[str]]:
    """Verify that a candidate's source hashes resolve to captured bytes.

    The old calendar bundle only carried endpoint URLs and hashes.  A new
    bounded capture must carry an exact base64 copy plus a create-only raw
    sidecar manifest so an independent reviewer can recompute both hashes.
    """

    projection: dict[str, object] = {
        "manifest_path": None,
        "manifest_file_hash": None,
        "manifest_hash": None,
        "entry_count": None,
        "inline_source_count": 0,
        "verified": False,
        "read_only": True,
    }
    blockers: list[str] = []
    evidence = bundle.get("raw_evidence")
    if not isinstance(evidence, Mapping):
        blockers.append("official_calendar_bundle_raw_evidence_missing")
        return projection, blockers
    manifest_ref = evidence.get("manifest_path")
    if not isinstance(manifest_ref, str) or not manifest_ref.strip():
        blockers.append("official_calendar_bundle_raw_evidence_manifest_path_missing")
        return projection, blockers
    manifest_candidate = Path(manifest_ref)
    if manifest_candidate.is_absolute():
        blockers.append("official_calendar_bundle_raw_evidence_manifest_path_must_be_relative")
        return projection, blockers
    manifest_path = (bundle_path.parent / manifest_candidate).resolve()
    try:
        manifest_path.relative_to(bundle_path.parent.resolve())
    except ValueError:
        blockers.append("official_calendar_bundle_raw_evidence_manifest_path_outside_bundle_root")
        return projection, blockers
    projection["manifest_path"] = str(manifest_path)
    if not manifest_path.is_file():
        blockers.append("official_calendar_bundle_raw_evidence_manifest_missing")
        return projection, blockers
    manifest_file_hash = file_sha256(manifest_path)
    projection["manifest_file_hash"] = manifest_file_hash
    expected_manifest_file_hash = evidence.get("manifest_file_hash")
    if expected_manifest_file_hash != manifest_file_hash:
        blockers.append("official_calendar_bundle_raw_evidence_manifest_file_hash_invalid")
    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        blockers.append("official_calendar_bundle_raw_evidence_manifest_unreadable")
        return projection, blockers
    if not isinstance(manifest_raw, Mapping):
        blockers.append("official_calendar_bundle_raw_evidence_manifest_root_invalid")
        return projection, blockers
    projection["manifest_hash"] = manifest_raw.get("manifest_hash")
    if manifest_raw.get("schema_version") != "official-calendar-raw-evidence-manifest.v1":
        blockers.append("official_calendar_bundle_raw_evidence_manifest_schema_invalid")
    manifest_body = dict(manifest_raw)
    supplied_manifest_hash = manifest_body.pop("manifest_hash", None)
    if supplied_manifest_hash != payload_hash(manifest_body):
        blockers.append("official_calendar_bundle_raw_evidence_manifest_hash_invalid")
    if evidence.get("manifest_hash") != supplied_manifest_hash:
        blockers.append("official_calendar_bundle_raw_evidence_manifest_binding_invalid")
    entries = manifest_raw.get("entries")
    if not isinstance(entries, list):
        blockers.append("official_calendar_bundle_raw_evidence_entries_invalid")
        return projection, blockers
    projection["entry_count"] = len(entries)
    if evidence.get("entry_count") != len(entries):
        blockers.append("official_calendar_bundle_raw_evidence_entry_count_invalid")

    manifest_by_identity: dict[tuple[str, str], Mapping[str, object]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_invalid")
            continue
        kind = str(entry.get("kind", ""))
        key = str(entry.get("key", ""))
        identity = (kind, key)
        if kind not in {"twse", "tpex"} or not key or identity in manifest_by_identity:
            blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_identity_invalid")
            continue
        manifest_by_identity[identity] = entry
        raw_name = entry.get("raw_file")
        metadata_name = entry.get("metadata_file")
        raw_path = _resolve_manifest_child(manifest_path, raw_name)
        metadata_path = _resolve_manifest_child(manifest_path, metadata_name)
        if raw_path is None:
            blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_raw_path_invalid")
        elif not raw_path.is_file():
            blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_raw_missing")
        else:
            actual_hash = file_sha256(raw_path)
            if actual_hash != entry.get("raw_file_hash") or actual_hash != entry.get("source_hash"):
                blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_raw_hash_invalid")
            try:
                raw_size = raw_path.stat().st_size
            except OSError:
                raw_size = None
            if raw_size != entry.get("raw_size_bytes"):
                blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_raw_size_invalid")
        if metadata_path is None:
            blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_metadata_path_invalid")
        elif not metadata_path.is_file():
            blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_metadata_missing")
        else:
            if file_sha256(metadata_path) != entry.get("metadata_file_hash"):
                blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_metadata_hash_invalid")
            try:
                metadata_raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                metadata_raw = None
            if not isinstance(metadata_raw, Mapping):
                blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_metadata_invalid")
            else:
                if metadata_raw.get("source_hash") != entry.get("source_hash"):
                    blockers.append(f"official_calendar_bundle_raw_evidence_entry_{index}_metadata_source_hash_invalid")

    source_responses = bundle.get("source_responses")
    if not isinstance(source_responses, Mapping):
        blockers.append("official_calendar_bundle_source_responses_invalid")
        return projection, blockers
    for market in ("twse", "tpex"):
        records = source_responses.get(market)
        if not isinstance(records, list) or not records:
            blockers.append(f"official_calendar_bundle_{market}_source_responses_invalid")
            continue
        identity_field = "year" if market == "twse" else "month"
        for record in records:
            if not isinstance(record, Mapping):
                blockers.append(f"official_calendar_bundle_{market}_source_record_invalid")
                continue
            key = str(record.get(identity_field, ""))
            raw_response = record.get("raw_response")
            if not isinstance(raw_response, Mapping):
                blockers.append(f"official_calendar_bundle_{market}_{key}_inline_raw_missing")
                continue
            encoded = raw_response.get("content_base64")
            if not isinstance(encoded, str):
                blockers.append(f"official_calendar_bundle_{market}_{key}_inline_raw_invalid")
                continue
            try:
                raw_bytes = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                blockers.append(f"official_calendar_bundle_{market}_{key}_inline_raw_invalid")
                continue
            digest = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
            if digest != record.get("source_hash") or digest != raw_response.get("sha256"):
                blockers.append(f"official_calendar_bundle_{market}_{key}_inline_raw_hash_invalid")
            if raw_response.get("size_bytes") != len(raw_bytes):
                blockers.append(f"official_calendar_bundle_{market}_{key}_inline_raw_size_invalid")
            if (market, key) not in manifest_by_identity:
                blockers.append(f"official_calendar_bundle_{market}_{key}_raw_manifest_entry_missing")
            else:
                entry = manifest_by_identity[(market, key)]
                if entry.get("source_hash") != record.get("source_hash"):
                    blockers.append(f"official_calendar_bundle_{market}_{key}_raw_manifest_binding_invalid")
            current_count = projection["inline_source_count"]
            projection["inline_source_count"] = (
                current_count + 1 if isinstance(current_count, int) else 1
            )

    projection["verified"] = not blockers
    return projection, blockers


def _resolve_manifest_child(manifest_path: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = (manifest_path.parent / value).resolve()
    try:
        candidate.relative_to(manifest_path.parent.resolve())
    except ValueError:
        return None
    return candidate


def _inspect_file(path: Path | None, *, role: str) -> dict[str, object]:
    projection: dict[str, object] = {
        "path": str(path) if path is not None else None,
        "role": role,
        "exists": bool(path is not None and path.is_file()),
        "read_only": True,
    }
    if path is not None and path.is_file():
        try:
            stat = path.stat()
            projection.update({"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        except OSError as error:
            projection["stat_error"] = type(error).__name__
    return projection


def _inspect_directory(path: Path, *, role: str) -> dict[str, object]:
    return {
        "path": str(path),
        "role": role,
        "exists": path.is_dir(),
        "read_only": True,
    }


def _normalize_schedule_evidence(
    value: Mapping[str, object] | None,
) -> dict[str, object]:
    """保留 scheduler owner 傳入的證據，不在本模組另造時間 SSOT。"""

    if value is None:
        return {
            "source": "not_supplied",
            "configured_time": None,
            "configured_timezone": None,
            "taipei_equivalent": None,
            "same_natural_day_retry": True,
        }
    if not isinstance(value, Mapping):  # pragma: no cover - typing guard
        raise FormalNextClockPreparationError("paper_schedule_evidence must be an object")
    result = {str(key): item for key, item in value.items()}
    result.setdefault("source", "explicit_schedule_evidence")
    result.setdefault("same_natural_day_retry", True)
    return result


def _inspect_pit_capture_day(root: Path, *, activation_date: date) -> dict[str, object]:
    day_root = root / activation_date.isoformat()
    manifests: list[str] = []
    if day_root.is_dir():
        manifests = sorted(str(item.resolve()) for item in day_root.glob("*/archive_manifest.json"))
    return {
        "archive_root": str(root),
        "activation_date": activation_date.isoformat(),
        "distinct_capture_count": len(manifests),
        "archive_manifests": manifests,
        "multiple_distinct_captures_block": len(manifests) > 1,
        "read_only": True,
    }


def _inspect_prior_day_pit(
    operational_path: Path | None,
    receipt_path: Path | None,
    *,
    activation_date: date,
    observed: datetime,
) -> tuple[dict[str, object], list[str]]:
    """驗證 D-1 machine PIT candidate 是否可供 D pre-cutoff 重驗。"""

    projection: dict[str, object] = {
        "operational_path": str(operational_path) if operational_path is not None else None,
        "receipt_path": str(receipt_path) if receipt_path is not None else None,
        "operational_file_hash": None,
        "receipt_file_hash": None,
        "effective_from": None,
        "available_at": None,
        "decision_at": None,
        "capture_id": None,
        "row_count": None,
        "source_ids": None,
        "candidate_only": None,
        "formal_consumer_compatible": None,
        "usable_for_activation_pre_cutoff": False,
        "read_only": True,
    }
    blockers: list[str] = []
    if operational_path is None or receipt_path is None:
        blockers.append("pit_d_minus_one_operational_candidate_not_supplied")
        return projection, blockers
    if not operational_path.is_file():
        blockers.append("pit_d_minus_one_operational_candidate_missing")
        return projection, blockers
    if not receipt_path.is_file():
        blockers.append("pit_d_minus_one_receipt_missing")
        return projection, blockers
    projection["operational_file_hash"] = file_sha256(operational_path)
    projection["receipt_file_hash"] = file_sha256(receipt_path)
    try:
        operational = json.loads(operational_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        blockers.append("pit_d_minus_one_operational_json_unreadable")
        return projection, blockers
    if not isinstance(operational, Mapping) or not isinstance(receipt, Mapping):
        blockers.append("pit_d_minus_one_operational_json_root_invalid")
        return projection, blockers
    for key in (
        "effective_from",
        "available_at",
        "decision_at",
        "capture_id",
        "row_count",
        "source_ids",
        "candidate_only",
        "formal_consumer_compatible",
    ):
        projection[key] = operational.get(key)
    if operational.get("status") != "published_candidate":
        blockers.append("pit_d_minus_one_operational_status_invalid")
    if operational.get("candidate_only") is not True:
        blockers.append("pit_d_minus_one_operational_must_remain_candidate_only")
    if operational.get("formal_consumer_compatible") is not False:
        blockers.append("pit_d_minus_one_operational_must_not_claim_formal_compatibility")
    if operational.get("source_custody_verified") is not True:
        blockers.append("pit_d_minus_one_operational_source_custody_unverified")
    if operational.get("rows_rebuilt_from_raw") is not True:
        blockers.append("pit_d_minus_one_operational_rows_not_rebuilt_from_raw")
    effective_text = operational.get("effective_from")
    try:
        effective = date.fromisoformat(str(effective_text))
    except ValueError:
        effective = None
    if effective is None:
        blockers.append("pit_d_minus_one_operational_effective_from_invalid")
    elif effective >= activation_date:
        blockers.append("pit_d_minus_one_operational_must_be_d_minus_one")
    available = _parse_aware_timestamp(operational.get("available_at"), "available_at")
    decision = _parse_aware_timestamp(operational.get("decision_at"), "decision_at")
    if available is None:
        blockers.append("pit_d_minus_one_operational_available_at_invalid")
    elif available > _activation_cutoff(activation_date):
        blockers.append("pit_d_minus_one_operational_available_after_activation_cutoff")
    if decision is None:
        blockers.append("pit_d_minus_one_operational_decision_at_invalid")
    elif decision > observed:
        blockers.append("pit_d_minus_one_operational_decision_at_in_future")
    receipt_content_hash = receipt.get("content_sha256")
    if operational.get("receipt_content_hash") != receipt_content_hash:
        blockers.append("pit_d_minus_one_operational_receipt_hash_mismatch")
    if operational.get("capture_id") != receipt.get("capture_id"):
        blockers.append("pit_d_minus_one_operational_capture_id_mismatch")
    if operational.get("effective_from") != receipt.get("effective_from"):
        blockers.append("pit_d_minus_one_operational_effective_from_mismatch")
    if not blockers:
        projection["usable_for_activation_pre_cutoff"] = True
        projection["consumption_rule"] = (
            "D decision_at must be at or after available_at; effective_from remains D-1 capture date; no historical backfill"
        )
    return projection, blockers


def _activation_cutoff(activation_date: date) -> datetime:
    return datetime.combine(
        activation_date,
        PIT_CAPTURE_CUTOFF,
        tzinfo=_taipei_zone(),
    ).astimezone(timezone.utc)


def _absolute_path(path: Path, field_name: str) -> Path:
    if not isinstance(path, Path):
        raise FormalNextClockPreparationError(f"{field_name} must be a Path")
    resolved = path.expanduser().resolve()
    if not resolved.is_absolute():  # pragma: no cover - resolve normally absolute
        raise FormalNextClockPreparationError(f"{field_name} must be absolute")
    return resolved


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalNextClockPreparationError(f"{field_name} must be non-empty")
    return value.strip()


def _aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FormalNextClockPreparationError(f"{field_name} must include timezone")
    return value.astimezone(timezone.utc)


def _parse_aware_timestamp(value: object, field_name: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    try:
        return _aware_datetime(parsed, field_name)
    except FormalNextClockPreparationError:
        return None


def _taipei_zone() -> Any:
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Taipei")


def _validate_plan_hash(plan: Mapping[str, object]) -> None:
    supplied = plan.get("plan_hash")
    body = dict(plan)
    body.pop("plan_hash", None)
    if supplied != payload_hash(body):
        raise FormalNextClockPreparationError("preparation plan hash mismatch")


__all__ = [
    "FORMAL_NEXT_CLOCK_PREPARATION_SCHEMA_VERSION",
    "FormalNextClockPreparationError",
    "build_formal_next_clock_preparation_plan",
    "write_immutable_formal_next_clock_preparation_plan",
]
