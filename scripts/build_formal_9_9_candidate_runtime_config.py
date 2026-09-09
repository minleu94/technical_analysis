"""建立 2026-09-09 Formal／Paper runtime candidate 設定。

這個工具只讀取已經持久化的 calendar、clock、PIT archive 與 D 槽 Rule
parent policy，並在 repository ``output/v4_next_formal`` 以 create-only
方式產生一份給 root／Ops 審核的候選設定。它不註冊或修改 Windows
Scheduler、不切換 D 槽 controlled path、不抓行情、不寫 SQLite，也不把
candidate 宣告成 Formal input。

Rule wrapper 的實際 9/9 machine bundle 須在台北 08:30 前由既有
pre-open 入口預發布；09:00--13:30 只由 daily Rule producer 消費這份
已驗證 bundle，不能在盤中首次建立同日 machine clock。因此本設定保存
的是精確 wrapper／環境契約與可驗證的輸出 pattern，而不是預先捏造
source-window hash。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_daily_input_producer import (  # noqa: E402
    _readback_pit_candidate_archive,
)
from data_module.formal_next_clock_preparation import (  # noqa: E402
    _inspect_calendar_bundle,
)
from data_module.prospective_formal_clock import (  # noqa: E402
    file_sha256,
    load_clock_manifest,
)


TAIPEI = ZoneInfo("Asia/Taipei")
ACTIVATION_DATE = date(2026, 9, 9)
DATA_ROOT = Path(r"D:\Min\Python\Project\FA_Data")
MARKET_DB = DATA_ROOT / "sqlite" / "twstock.db"
BASELINE_CLOCK = DATA_ROOT / "output" / "formal_prospective" / "clock-20260828" / "clock" / "manifest.json"
BASELINE_OWNER = BASELINE_CLOCK.parent.parent / "metadata" / "owner_acceptance.json"
BASELINE_SYMBOLS = BASELINE_CLOCK.parent.parent / "metadata" / "universe_symbols.json"
BASELINE_IDENTITY = BASELINE_CLOCK.parent.parent / "metadata" / "universe_identity.json"

PUBLICATION_ROOT = ROOT / "output" / "formal_daily_publications"
CALENDAR_ARCHIVE_ROOT = PUBLICATION_ROOT / "calendar_candidate_archive" / "2026-09-09" / "1b6227dd0464eded-aff4c96e1edab151"
CALENDAR_BUNDLE = CALENDAR_ARCHIVE_ROOT / "v4_calendar_20260909_20260908_104849140.json"
CALENDAR_ARCHIVE_MANIFEST = CALENDAR_ARCHIVE_ROOT / "archive_manifest.json"
CALENDAR_RAW_MANIFEST = CALENDAR_ARCHIVE_ROOT / "v4_calendar_20260909_20260908_104849140_raw" / "manifest.json"

CLOCK_ARCHIVE_ROOT = PUBLICATION_ROOT / "clock_candidate_archive" / "2026-09-09" / "d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1"
CLOCK_MANIFEST = CLOCK_ARCHIVE_ROOT / "clock" / "manifest.json"
CLOCK_ARCHIVE_MANIFEST = CLOCK_ARCHIVE_ROOT / "archive_manifest.json"

PIT_ARCHIVE_ROOT = PUBLICATION_ROOT / "pit_candidate_archive"
PIT_ARCHIVE_MANIFEST = PIT_ARCHIVE_ROOT / "2026-09-08" / "85f71a355f707404-284d54b9ccedbfea" / "archive_manifest.json"
PIT_PUBLICATION = PIT_ARCHIVE_MANIFEST.parent / "pit-sector-membership-machine.json"
PIT_RECEIPT = PIT_ARCHIVE_MANIFEST.parent / "receipt.json"
PIT_OPERATIONAL = PIT_ARCHIVE_MANIFEST.parent / "operational.json"

PAPER_SNAPSHOT = ROOT / "output" / "paper_execution_eod_replay" / "paper_portfolio" / "paper_portfolio.sqlite"
PAPER_LEDGER = ROOT / "output" / "paper_execution_eod_replay" / "paper_trade_ledger.sqlite"
CALENDAR_CACHE = ROOT / "output" / "paper_execution_eod_replay" / "calendar_cache"
RULE_SOURCE_ROOT = PUBLICATION_ROOT / "rule_source"
RULE_STATUS = RULE_SOURCE_ROOT / "scheduler" / "rule_source_latest_status.json"
FORMAL_STATUS_ROOT = PUBLICATION_ROOT / "scheduler"

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
RULE_WRAPPER = ROOT / "scripts" / "scheduled" / "run_formal_rule_source_preopen.cmd"
PIT_WRAPPER = ROOT / "scripts" / "scheduled" / "run_pit_sector_membership_preopen_capture.cmd"
SIDECAR_WRAPPER = ROOT / "scripts" / "scheduled" / "run_formal_pit_sidecar_postcutoff.cmd"
FORMAL_WRAPPER = ROOT / "scripts" / "scheduled" / "run_formal_input_producer_daily.cmd"
PAPER_WRAPPER = ROOT / "scripts" / "scheduled" / "run_paper_execution_daily_isolated.cmd"

SHA256_PREFIX = "sha256:"


class CandidateRuntimeConfigError(ValueError):
    """候選 runtime 設定的來源或契約無法被客觀驗證。"""


def _hash(path: Path) -> str:
    return file_sha256(path)


def _require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise CandidateRuntimeConfigError(f"{label}_missing:{resolved}")
    return resolved


def _read_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateRuntimeConfigError(f"{label}_unreadable:{path}") from error
    if not isinstance(value, dict):
        raise CandidateRuntimeConfigError(f"{label}_must_be_object:{path}")
    return {str(key): item for key, item in value.items()}


def _path_record(path: Path, *, role: str, read_only: bool = True) -> dict[str, object]:
    resolved = _require_file(path, role)
    return {
        "path": str(resolved),
        "file_hash": _hash(resolved),
        "size_bytes": resolved.stat().st_size,
        "role": role,
        "read_only": read_only,
    }


def _command(path: Path) -> str:
    return f'cmd.exe /d /c "{path.resolve()}"'


def _env_contract(*, runtime_config_path: Path) -> dict[str, object]:
    """保存兩個既有 wrapper 的有效環境，不含 secret。"""

    runtime_config = str(runtime_config_path.expanduser().resolve())
    return {
        "rule_source_wrapper": {
            "entrypoint": str(RULE_WRAPPER.resolve()),
            "command": _command(RULE_WRAPPER),
            "environment": {
                "BALDR_PYTHON": str(PYTHON.resolve()),
                "DATA_ROOT": str(DATA_ROOT),
                "FORMAL_DAILY_MARKET_DB": str(MARKET_DB),
                "FORMAL_DAILY_RULE_BASELINE_ROOT": str(BASELINE_CLOCK.parent.parent.parent),
                "FORMAL_DAILY_CALENDAR_CACHE_ROOT": str(CALENDAR_CACHE),
                "FORMAL_DAILY_RULE_SOURCE_ROOT": str(RULE_SOURCE_ROOT),
                "FORMAL_DAILY_RUNTIME_CONFIG": runtime_config,
            },
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                "FORMAL_DAILY_MARKET_DB",
                "FORMAL_DAILY_RULE_BASELINE_ROOT",
                "FORMAL_DAILY_CALENDAR_CACHE_ROOT",
                "FORMAL_DAILY_RULE_SOURCE_ROOT",
            ],
            "source_resolution": {
                "mode": "read_only_D_parent_then_machine_revalidate",
                "parent_clock_manifest": str(BASELINE_CLOCK.resolve()),
                "parent_clock_file_hash": _hash(BASELINE_CLOCK),
                "explicit_date_or_now_override": False,
                "fixture_mode": False,
                "output_root": str(RULE_SOURCE_ROOT.resolve()),
                "status_path": str(RULE_STATUS.resolve()),
                "expected_bundle_pattern": (
                    "clock-20260909-machine-v2-<source_window_hash_12>-85d50c270d9a"
                ),
            },
        },
        "pit_preopen_wrapper": {
            "entrypoint": str(PIT_WRAPPER.resolve()),
            "command": _command(PIT_WRAPPER),
            "scheduler_task": "baldr-pit-sector-membership-preopen-capture-daily",
            "scheduler_owner": "v4_schedule_ops",
            "configured_local_time": "16:00",
            "configured_timezone": "America/Los_Angeles",
            "taipei_mapping": "07:00 PDT / 08:00 PST",
            "natural_window_taipei": "07:00-08:30",
            "calls_rule_wrapper_first": True,
            "rule_producer_dependency": (
                "the existing PIT pre-open wrapper calls the Rule machine producer "
                "first; it is a prepublished source/clock step only. The daily "
                "Rule producer consumes that exact status-bound source during the "
                "Taipei 09:00-13:30 window before the 21:25 Formal consumer"
            ),
            "environment": {
                "BALDR_PYTHON": str(PYTHON.resolve()),
                "FORMAL_DAILY_PUBLICATION_ROOT": str(PUBLICATION_ROOT.resolve()),
                "FORMAL_DAILY_RUNTIME_CONFIG": runtime_config,
            },
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                "FORMAL_DAILY_PUBLICATION_ROOT",
            ],
        },
        "pit_sidecar_wrapper": {
            "entrypoint": str(SIDECAR_WRAPPER.resolve()),
            "command": _command(SIDECAR_WRAPPER),
            "scheduler_task": "baldr-formal-pit-sidecar-postcutoff-daily",
            "scheduler_owner": "v4_schedule_ops",
            "configured_local_time": "18:00",
            "configured_timezone": "America/Los_Angeles",
            "taipei_mapping": "09:00 PDT / 10:00 PST",
            "natural_window_taipei": "09:00 or later; archive read only",
            "environment": {
                "BALDR_PYTHON": str(PYTHON.resolve()),
                "FORMAL_DAILY_PUBLICATION_ROOT": str(PUBLICATION_ROOT.resolve()),
                "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT": str(PIT_ARCHIVE_ROOT.resolve()),
                "FORMAL_DAILY_RUNTIME_CONFIG": runtime_config,
            },
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                "FORMAL_DAILY_PUBLICATION_ROOT",
                "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT",
            ],
        },
        "formal_input_wrapper": {
            "entrypoint": str(FORMAL_WRAPPER.resolve()),
            "command": _command(FORMAL_WRAPPER),
            "scheduler_task": "baldr-formal-input-producer-daily",
            "scheduler_owner": "v4_schedule_ops",
            "configured_local_time": "21:25",
            "configured_timezone": "America/Los_Angeles",
            "taipei_mapping": "12:25 PDT / 13:25 PST",
            "environment": {
                "BALDR_PYTHON": str(PYTHON.resolve()),
                "DATA_ROOT": str(DATA_ROOT),
                "FORMAL_DAILY_PAPER_SNAPSHOT_DB": str(PAPER_SNAPSHOT.resolve()),
                "FORMAL_DAILY_MARKET_DB": str(MARKET_DB),
                "FORMAL_DAILY_PUBLICATION_ROOT": str(PUBLICATION_ROOT.resolve()),
                "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT": str(PIT_ARCHIVE_ROOT.resolve()),
                "FORMAL_DAILY_RULE_SOURCE_ROOT": str(RULE_SOURCE_ROOT.resolve()),
                "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB": str(PAPER_LEDGER.resolve()),
                # The durable 9/9 clock is the cumulative portfolio identity.
                # The D parent clock above remains read-only Rule lineage and
                # must never become the new Formal portfolio default.
                "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST": str(CLOCK_MANIFEST.resolve()),
                "FORMAL_DAILY_RUNTIME_CONFIG": runtime_config,
            },
            "required_environment": [
                "FORMAL_DAILY_RUNTIME_CONFIG",
                "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
                "DATA_ROOT",
                "FORMAL_DAILY_MARKET_DB",
                "FORMAL_DAILY_PUBLICATION_ROOT",
                "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT",
                "FORMAL_DAILY_RULE_SOURCE_ROOT",
                "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
                "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
            ],
            "required_rule_source_environment": {
                "FORMAL_DAILY_CLOCK_MANIFEST": "omitted; resolver binds exact verified Rule bundle",
                "FORMAL_DAILY_UNIVERSE_SYMBOLS": "omitted; resolver binds exact verified Rule bundle",
                "FORMAL_DAILY_OWNER_ACCEPTANCE": "omitted; resolver binds exact verified Rule bundle",
            },
            "legacy_BALDR_ML_paths": "omitted when FORMAL_DAILY_RULE_SOURCE_ROOT is configured",
            "status_path": str(FORMAL_STATUS_ROOT.resolve() / "latest_status.json"),
            "rule_source_predecessor": {
                # This is the real registered predecessor.  Its command invokes
                # RULE_WRAPPER before PIT capture; no unregistered post-open
                # scheduler task is invented here.
                "task": "baldr-pit-sector-membership-preopen-capture-daily",
                "wrapper": str(PIT_WRAPPER.resolve()),
                "nested_rule_wrapper": str(RULE_WRAPPER.resolve()),
                "source_root": str(RULE_SOURCE_ROOT.resolve()),
                "required_status_path": str(RULE_STATUS.resolve()),
                "same_taipei_natural_day": True,
                "prepublish_window_taipei": "07:00-08:30",
                "daily_rule_producer_window_taipei": "09:00-13:30",
                "natural_window_taipei": "07:00-08:30 prepublish; 09:00-13:30 daily Rule",
                "scheduler_owner": "v4_schedule_ops",
                "required_exit_code": 0,
                "accepted_statuses": [
                    "rule_source_bundle_created",
                    "rule_source_bundle_reused",
                ],
                "prepublish_role": (
                    "machine source and Rule clock prepublication only; no Rule "
                    "decision or Formal credit"
                ),
                "postopen_requires_existing_bundle": True,
                "new_same_day_clock_after_pit_cutoff": False,
                "daily_rule_binding": (
                    "data_module.formal_daily_input_producer consumes the exact "
                    "status-bound clock/universe/owner paths and records daily "
                    "Rule lineage separately from the fixed cumulative portfolio clock"
                ),
                "purpose": (
                    "the pre-open predecessor publishes or deterministically retries "
                    "the exact bundle; the 21:25 Pacific consumer requires those "
                    "status-bound paths and runs the daily Rule producer in the "
                    "regular Taipei Rule window"
                ),
            },
        },
        "paper_eod_wrapper": {
            "entrypoint": str(PAPER_WRAPPER.resolve()),
            "command": _command(PAPER_WRAPPER),
            "scheduler_task": "baldr-paper-execution-eod-replay-daily",
            "scheduler_owner": "v4_schedule_ops",
            "configured_local_time": "06:00",
            "configured_timezone": "America/Los_Angeles",
            "taipei_mapping": "21:00 PDT / 22:00 PST",
            "natural_source_window_taipei": "15:00 or later",
                "same_natural_day_retry": True,
            "environment": {
                "FORMAL_DAILY_RUNTIME_CONFIG": runtime_config,
            },
            "required_environment": ["FORMAL_DAILY_RUNTIME_CONFIG"],
            "source_guard": [
                "frozen pending decision identity",
                "same natural data date and version",
                "real source fill receipt required",
                "no snapshot-derived or synthetic fill",
            ],
        },
    }


def _validate_sources(observed: datetime) -> dict[str, object]:
    """驗證固定 durable inputs，並保留每個 source 的 bytes hash。"""

    for path, label in (
        (PYTHON, "python_runtime"),
        (RULE_WRAPPER, "rule_wrapper"),
        (PIT_WRAPPER, "pit_wrapper"),
        (SIDECAR_WRAPPER, "pit_sidecar_wrapper"),
        (FORMAL_WRAPPER, "formal_input_wrapper"),
        (PAPER_WRAPPER, "paper_wrapper"),
        (BASELINE_CLOCK, "baseline_clock"),
        (BASELINE_OWNER, "baseline_owner_acceptance"),
        (BASELINE_SYMBOLS, "baseline_universe_symbols"),
        (BASELINE_IDENTITY, "baseline_universe_identity"),
        (MARKET_DB, "market_db"),
    ):
        _require_file(path, label)

    clock_path = _require_file(CLOCK_MANIFEST, "durable_clock_manifest")
    clock = load_clock_manifest(clock_path, now=observed)
    if clock.activation_trading_day != ACTIVATION_DATE:
        raise CandidateRuntimeConfigError("durable_clock_activation_date_mismatch")
    if clock.payload.get("status") != "planned":
        raise CandidateRuntimeConfigError("durable_clock_status_mismatch")
    for field in ("real_money", "broker_execution", "historical_backfill_claimed"):
        if clock.payload.get(field) is not False:
            raise CandidateRuntimeConfigError(f"durable_clock_{field}_must_be_false")

    calendar_path = _require_file(CALENDAR_BUNDLE, "durable_calendar_bundle")
    calendar_projection, calendar_blockers = _inspect_calendar_bundle(
        calendar_path,
        activation_date=ACTIVATION_DATE,
    )
    if calendar_blockers:
        raise CandidateRuntimeConfigError(
            "durable_calendar_not_verified:" + ",".join(calendar_blockers)
        )

    pit_manifest = _require_file(PIT_ARCHIVE_MANIFEST, "durable_pit_archive_manifest")
    pit_readback = _readback_pit_candidate_archive(pit_manifest, now=observed)
    pit_operational_payload = _read_object(PIT_OPERATIONAL, "pit_operational")
    available_at = pit_operational_payload.get("available_at")
    if not isinstance(available_at, str) or not available_at.strip():
        raise CandidateRuntimeConfigError("prior_day_pit_available_at_missing")
    pit_readback["available_at"] = available_at
    if pit_readback.get("effective_from") != "2026-09-08":
        raise CandidateRuntimeConfigError("prior_day_pit_effective_date_mismatch")
    if pit_readback.get("candidate_only") is not True or pit_readback.get(
        "formal_consumer_compatible"
    ) is not False:
        raise CandidateRuntimeConfigError("prior_day_pit_candidate_boundary_invalid")

    archive_manifest = _read_object(CLOCK_ARCHIVE_MANIFEST, "clock_archive_manifest")
    calendar_archive_manifest = _read_object(
        CALENDAR_ARCHIVE_MANIFEST,
        "calendar_archive_manifest",
    )
    calendar_raw_manifest = _read_object(CALENDAR_RAW_MANIFEST, "calendar_raw_manifest")

    return {
        "market_db": _path_record(MARKET_DB, role="D market source"),
        "baseline_parent_policy": {
            "clock_manifest": _path_record(BASELINE_CLOCK, role="D Rule parent clock"),
            "owner_acceptance": _path_record(BASELINE_OWNER, role="D Rule parent owner acceptance"),
            "universe_symbols": _path_record(BASELINE_SYMBOLS, role="D Rule parent universe symbols"),
            "universe_identity": _path_record(BASELINE_IDENTITY, role="D Rule parent universe identity"),
            "source_role": "read_only_parent_policy; not a 2026-09-09 Formal controlled input",
        },
        "calendar": {
            "bundle": _path_record(calendar_path, role="durable official calendar bundle"),
            "bundle_hash": calendar_projection.get("bundle_hash"),
            "archive_manifest": _path_record(
                CALENDAR_ARCHIVE_MANIFEST,
                role="calendar archive manifest",
            ),
            "archive_hash": calendar_archive_manifest.get("archive_hash"),
            "raw_manifest": _path_record(CALENDAR_RAW_MANIFEST, role="calendar raw custody manifest"),
            "raw_manifest_hash": calendar_raw_manifest.get("manifest_hash"),
            "activation_day": ACTIVATION_DATE.isoformat(),
            "twse_open": calendar_projection.get("twse_open"),
            "tpex_open": calendar_projection.get("tpex_open"),
            "candidate_only": True,
            "formal_clock_created": False,
        },
        "planned_clock": {
            "manifest": _path_record(clock_path, role="durable 9/9 Rule-only clock candidate"),
            "manifest_hash": clock.manifest_hash,
            "clock_id": clock.clock_id,
            "activation_trading_day": clock.activation_trading_day.isoformat(),
            "archive_manifest": _path_record(CLOCK_ARCHIVE_MANIFEST, role="clock archive manifest"),
            "archive_hash": archive_manifest.get("archive_hash"),
            "identity_scope": "rule_only_simulation",
            "ml_identity_verified": False,
            "promotion_allowed": False,
            "controlled_clock_target": str(
                DATA_ROOT / "output" / "formal_prospective" / "clock-20260909"
            ),
            "controlled_update_applied": False,
        },
        "prior_day_pit": {
            "archive_root": str(PIT_ARCHIVE_ROOT.resolve()),
            "archive_manifest": _path_record(
                PIT_ARCHIVE_MANIFEST,
                role="durable D-1 PIT candidate archive manifest",
            ),
            "manifest_hash": pit_readback.get("manifest_hash"),
            "publication": _path_record(PIT_PUBLICATION, role="PIT archive publication"),
            "receipt": _path_record(PIT_RECEIPT, role="PIT archive receipt"),
            "operational": _path_record(PIT_OPERATIONAL, role="PIT archive operational envelope"),
            "capture_id": pit_readback.get("capture_id"),
            "captured_at": pit_readback.get("captured_at"),
            "archived_at": pit_readback.get("archived_at"),
            "available_at": pit_readback.get("available_at"),
            "effective_from": pit_readback.get("effective_from"),
            "row_count": pit_readback.get("row_count"),
            "source_ids": pit_readback.get("source_ids"),
            "source_custody_verified": pit_readback.get("consumer_verified"),
            "rows_rebuilt_from_raw": True,
            "candidate_only": True,
            "formal_consumer_compatible": False,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "reusable_for_ml_shadow": True,
            "reusable_for_formal_sidecar_directly": False,
        },
        "paper_sources": {
            "snapshot": {
                **_path_record(PAPER_SNAPSHOT, role="isolated Paper snapshot", read_only=True),
                "read_mode": "sqlite_mode_ro_query_only",
            },
            "fill_ledger": {
                "path": str(PAPER_LEDGER.resolve()),
                "exists": PAPER_LEDGER.is_file(),
                "read_only": True,
                "required_for_final_release": True,
                "source_rows_must_be_real": True,
            },
        },
        "portfolio_clock": {
            **_path_record(CLOCK_MANIFEST, role="cumulative Paper portfolio clock"),
            "scope": "cumulative_paper_portfolio_state",
            "activation_trading_day": ACTIVATION_DATE.isoformat(),
            "daily_rule_clock_is_separate": True,
            "reset_on_each_natural_day": False,
            "source_role": "durable_rule_only_clock_candidate; fixed cumulative start",
            "parent_policy_lineage": str(BASELINE_CLOCK.resolve()),
        },
    }


def _rolling_contract() -> dict[str, object]:
    """9/10 之後由自然台北交易日建立新設定與新 publication scope。"""

    publication = str(PUBLICATION_ROOT.resolve())
    return {
        "schema_version": "formal-paper-runtime-roll-forward.v1",
        "natural_date_timezone": "Asia/Taipei",
        "activation_date_source": (
            "observed Taipei date selected only after official calendar readback; "
            "never add a weekday or pass --date"
        ),
        "same_candidate_reuse_prohibited": True,
        "requires_date_scoped_config": True,
        "next_config_generation": (
            "run the same create-only builder after the next date's durable "
            "calendar/clock/PIT/Rule/Paper evidence exists; set the output path "
            "to the date-keyed runtime_config pattern"
        ),
        "config_path_pattern": str(
            ROOT / "output" / "v4_next_formal" / "formal_daily_runtime_config" / "<YYYY-MM-DD>.json"
        ),
        "date_scoped_fields": [
            "activation_trading_day",
            "source_evidence",
            "publication_paths",
            "wrapper_contract",
            "runtime_config_binding",
        ],
        "path_patterns": {
            "runtime_config": str(
                ROOT / "output" / "v4_next_formal" / "formal_daily_runtime_config" / "<YYYY-MM-DD>.json"
            ),
            "pit_archive_manifest": (
                publication
                + "/pit_candidate_archive/<YYYY-MM-DD>/<capture_hash_16>-<receipt_hash_16>/archive_manifest.json"
            ),
            "rule_source_bundle_manifest": (
                publication
                + "/rule_source/clock-<YYYYMMDD>-machine-v2-<source_window_hash_12>-<parent_clock_hash_12>/clock/manifest.json"
            ),
            "rule_history_manifest": publication + "/rule_history/<YYYY-MM-DD>/manifest.json",
            "portfolio_clock_manifest": str(CLOCK_MANIFEST.resolve()),
            "formal_pit_sidecar": (
                publication + "/pit_sector_membership_formal/<YYYY-MM-DD>/sidecar.json"
            ),
            "paper_eod_receipt_root": (
                str(ROOT / "output" / "paper_execution_eod_replay" / "receipts")
                + "/<same Taipei natural date>/"
            ),
            "causal_ledger_manifest": (
                publication
                + "/causal_ledger/<YYYY-MM-DD>-<snapshot_hash_12>-<fill_hash_12>/manifest.json"
            ),
        },
        "consumer_sequence": [
            "pit_preopen_capture -> rule_source_machine_revalidation",
            "formal_pit_sidecar reads same-day preopen archive only",
            "paper_eod replay reads frozen queue and same-day real fill source",
            "formal_input consumes exact same-day Rule/PIT/Paper paths",
            "causal_ledger closes only [snapshot_date, next_snapshot_date) intervals",
        ],
        "late_replay_policy": {
            "preserve_recorded_at": True,
            "historical_credit": False,
            "no_elapsed_credit": True,
            "same_day_pending_retry": "only same natural date and identical decision/source hashes",
            "missed_session": "explicit pending_execution_session_missed; do not replace with next recommendation",
        },
    }


def _build_config(*, observed: datetime, output_path: Path) -> dict[str, object]:
    sources = _validate_sources(observed)
    resolved_output = output_path.expanduser().resolve()
    return {
        "schema_version": "formal-paper-9-9-candidate-runtime-config.v1",
        "status": "candidate_ready_for_root_review",
        "generated_at": observed.isoformat(timespec="microseconds"),
        "activation_trading_day": ACTIVATION_DATE.isoformat(),
        "ownership": {
            "formal_paper_owner": [
                "PIT capture/publication (non-scheduled producer)",
                "formal_rule_source_producer",
                "formal_daily_input_producer",
                "Paper/fill/causal ledger consumer and common identity handoff",
            ],
            "scheduler_owner": "v4_schedule_ops",
            "ml_owner": "separate ML lane; this config never certifies ML identity",
        },
        "runtime_attestation": {
            "source": "this process runtime plus explicitly verified file hashes",
            "python_path": str(PYTHON.resolve()),
            "python_file_hash": _hash(PYTHON),
            "observed_clock_is_runtime_only": True,
            "secret_values_emitted": False,
        },
        "source_evidence": sources,
        "runtime_config_binding": {
            "environment_variable": "FORMAL_DAILY_RUNTIME_CONFIG",
            "path": str(resolved_output),
            "file_hash_semantics": (
                "computed from exact file bytes at wrapper load; omitted here to avoid self-hash recursion"
            ),
        },
        "wrapper_contract": _env_contract(runtime_config_path=resolved_output),
        "rolling_contract": _rolling_contract(),
        "publication_paths": {
            "portfolio_clock_manifest": str(CLOCK_MANIFEST.resolve()),
            "rule_source_root": str(RULE_SOURCE_ROOT.resolve()),
            "rule_source_status": str(RULE_STATUS.resolve()),
            "rule_history_manifest": str(
                PUBLICATION_ROOT / "rule_history" / "2026-09-09" / "manifest.json"
            ),
            "pit_archive_root": str(PIT_ARCHIVE_ROOT.resolve()),
            "pit_sidecar": str(
                PUBLICATION_ROOT
                / "pit_sector_membership_formal"
                / "2026-09-09"
                / "sidecar.json"
            ),
            "pit_receipt": str(
                PUBLICATION_ROOT
                / "pit_sector_membership_formal"
                / "2026-09-09"
                / "receipt.json"
            ),
            "paper_snapshot": str(PAPER_SNAPSHOT.resolve()),
            "paper_fill_ledger": str(PAPER_LEDGER.resolve()),
            "causal_ledger_run_pattern": str(
                PUBLICATION_ROOT
                / "causal_ledger"
                / "2026-09-09-<snapshot_hash_12>-<fill_hash_12>"
            ),
            "common_identity_manifest": str(
                ROOT / "output" / "v4_next_formal" / "formal_identity_20260909.json"
            ),
        },
        "pit_reuse_boundary": {
            "prior_day_archive": "2026-09-08 archive is persisted and hash/readback verified",
            "formal_sidecar": {
                "direct_consume_allowed": False,
                "reason": "archive declares candidate_only=true and formal_consumer_compatible=false",
                "lineage_candidate_only_after": [
                    "independent denominator and license scope readback",
                    "coverage_start and official calendar coverage",
                    "one distinct publication content per natural capture day",
                    "archive available_at and archived_at no later than each target 08:30 cutoff",
                    "formal sidecar publisher plus assembler readback",
                ],
                "current_root_conflict": "existing 2026-09-08 archive root has distinct captures; handoff must remain fail-closed",
            },
            "ml_shadow": {
                "exact_archive_consume_allowed": True,
                "consumer": "ml_module.pit_archive_consumer.consume_pit_candidate_archive",
                "required_manifest_file_hash": "sha256:c2b838d9d79b794bc13b934c83f5f36f18c1b5828dead20ded9112de6745178f",
                "decision_gate": "decision_at >= archived operational available_at",
                "candidate_only": True,
                "forward_credit": False,
                "promotion_allowed": False,
                "separate_ml_release_identity_required": True,
            },
        },
        "natural_execution_order": [
            {
                "step": 1,
                "when": "2026-09-09 Taipei 07:00-08:30",
                "command": _command(PIT_WRAPPER),
                "output": (
                    "one new 2026-09-09 durable PIT archive plus one machine "
                    "Rule source bundle prepublished by the nested Rule wrapper"
                ),
                "gate": (
                    "PIT effective_from=2026-09-09 and captured_at/archived_at "
                    "<= 08:30 Asia/Taipei; Rule bundle observed_at < 08:30; "
                    "no same-day retry after cutoff"
                ),
            },
            {
                "step": 2,
                "when": "2026-09-09 Taipei 09:00-13:30",
                "command": _command(FORMAL_WRAPPER),
                "scheduler_task": "baldr-formal-input-producer-daily",
                "host_trigger": "21:25 America/Los_Angeles",
                "output": (
                    "daily Rule producer consumes the exact prepublished machine "
                    "source and publishes the 2026-09-09 Rule history"
                ),
                "gate": (
                    "full clock/owner/universe/market-window readback; daily Rule "
                    "decision is inside 09:00-13:30; no date override or fixture; "
                    "missing prepublished bundle blocks"
                ),
            },
            {
                "step": 3,
                "when": "2026-09-09 Taipei 09:00 or later",
                "command": _command(SIDECAR_WRAPPER),
                "output": "pit_sector_membership_formal/2026-09-09 sidecar+receipt when independent history gate passes",
                "gate": "read archive only; no same-day post-cutoff HTTP refetch",
            },
            {
                "step": 4,
                "when": "2026-09-09 Taipei 15:00 or later",
                "command": _command(PAPER_WRAPPER),
                "output": "real source fill receipt and append-only isolated Paper ledger if a fill exists",
                "gate": "frozen pending decision/date/version; Decimal conservation; no synthetic fill",
            },
            {
                "step": 5,
                "when": "after steps 1-4 and real Paper fill source is complete",
                "command": _command(FORMAL_WRAPPER),
                "output": "causal ledger and Formal candidate after exact consumer readbacks",
                "gate": "fill is final release blocker; Rule/PIT prep may proceed independently",
            },
        ],
        "controlled_activation_gate": {
            "controlled_clock_target": str(
                DATA_ROOT / "output" / "formal_prospective" / "clock-20260909"
            ),
            "three_exact_consumer_readbacks_required": True,
            "common_identity_required": True,
            "old_controlled_paths_unchanged_until_atomic_update": True,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "fill_source_missing_is_final_gate_only": True,
        },
        "safety": {
            "read_only_sources": True,
            "writes_market_database": False,
            "writes_formal_controlled_paths": False,
            "writes_scheduler": False,
            "broker_execution": False,
            "historical_backfill_claimed": False,
            "candidate_only": True,
        },
    }


def _write_create_only(
    path: Path,
    payload: Mapping[str, object],
) -> tuple[str, str, str]:
    body = dict(payload)
    body["config_hash"] = _payload_hash(payload)
    encoded = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
    except FileExistsError as error:
        raise CandidateRuntimeConfigError(f"candidate_config_already_exists:{path}") from error
    return str(path), _hash(path), str(body["config_hash"])


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return SHA256_PREFIX + hashlib.sha256(encoded).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="新的 repository QA candidate path；已存在時拒絕覆寫",
    )
    parser.add_argument(
        "--observed-at",
        help="供隔離重驗的 aware ISO timestamp；省略時使用 process UTC clock",
    )
    return parser


def _observed(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CandidateRuntimeConfigError("observed_at_must_be_iso_timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise CandidateRuntimeConfigError("observed_at_requires_timezone")
    result = result.astimezone(timezone.utc)
    if result > datetime.now(timezone.utc):
        raise CandidateRuntimeConfigError("observed_at_cannot_be_future")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        observed = _observed(args.observed_at)
        payload = _build_config(observed=observed, output_path=args.output)
        path, file_hash, config_hash = _write_create_only(args.output, payload)
    except CandidateRuntimeConfigError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": "candidate_persisted",
                "path": path,
                "file_hash": file_hash,
                "config_hash": config_hash,
                "activation_trading_day": ACTIVATION_DATE.isoformat(),
                "safety": payload.get("safety"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
