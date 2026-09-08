"""Bounded daily producer/consumer handoff for the three Formal ML inputs.

這個模組把目前已存在的來源 producer 接到既有 consumer，並把「當天可
觀測的 machine candidate」和真正可進 Formal input 的 owner-controlled
publication 分開保存。Rule 會重用 clock-bound Rule-only producer；PIT 會
重用官方 TWSE／TPEx raw custody producer；causal non-cash ledger 沒有可
信任的 writer 時保持明確 blocker。candidate 與 Rule development 只允許
寫入作業系統 TEMP；若呼叫端明確提供合法的 repository output／隔離 TEMP
publication root，Rule／ledger 的 immutable manifest、source custody 與
receipt 會持久保存。market SQLite 只以 read-only 開啟，且不會啟動交易、
訓練或 promotion。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_EVEN
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Sequence, cast
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.pit_sector_machine_publisher import (
    consume_machine_pit_operational_candidate,
    publish_machine_pit_operational_candidate,
)
from data_module.pit_sector_membership_machine import (
    MACHINE_PIT_PRODUCER_VERSION,
    build_machine_pit_publication,
    validate_machine_pit_publication,
    write_machine_pit_receipt,
)
from data_module.prospective_formal_clock import (
    ProspectiveFormalClock,
    SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON,
    file_sha256,
    load_clock_manifest_for_capture,
)
from data_module.prospective_rule_champion_publisher import (
    JsonPersistedFormalArtifactLoader,
    ProspectiveRuleSnapshotRequest,
    publish_prospective_rule_history,
)
from data_module.rule_champion_snapshot_service import (
    FORMAL_RULE_ONLY,
    RULE_CHAMPION_HISTORY_SCHEMA_VERSION,
    PersistedFormalDecisionArtifactRepository,
    RuleChampionSnapshot,
    RuleChampionSnapshotService,
    load_verified_rule_champion_snapshot_history,
)
from scripts import continue_ml_direct_ooc_after_store as formal_store
from development_module.prospective_rule_only_decision import (
    produce_prospective_rule_only_decision,
)


TAIPEI = ZoneInfo("Asia/Taipei")
RULE_SESSION_OPEN = time(9, 0)
RULE_SESSION_CLOSE = time(13, 30)
PIT_PREOPEN_CUTOFF = time(8, 30)
PIT_SOURCE_MAX_BYTES = 8 * 1024 * 1024
PIT_SOURCE_TIMEOUT_SECONDS = 30.0
PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION = "formal-input-pit-candidate-archive.v1"
DAILY_FORMAL_INPUT_PRODUCER_SCHEMA_VERSION = (
    "formal-input-daily-producer-receipt.v1"
)
DAILY_FORMAL_INPUT_PRODUCER_VERSION = "bounded-source-handoff.v2"
DAILY_FORMAL_INPUT_SOURCE_RECEIPT_SCHEMA_VERSION = (
    "formal-input-daily-source-receipt.v1"
)
DAILY_FORMAL_INPUT_PUBLICATION_CONTEXT_SCHEMA_VERSION = (
    "formal-input-daily-publication-context.v1"
)
FORMAL_PAPER_SOURCE_CUSTODY_SCHEMA_VERSION = (
    "formal-paper-source-custody.v1"
)
RULE_HMAC_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
RULE_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
FORMAL_LEDGER_ENV = "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"
FORMAL_RULE_ENV = "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"
FORMAL_SECTOR_ENV = "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"
PAPER_SNAPSHOT_ENV = "BALDR_ML_PAPER_PORTFOLIO_SNAPSHOT_DB_PATH"
PAPER_FILL_ENV = "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH"


class FormalDailyInputProducerError(ValueError):
    """日常三項 input handoff 的 fail-closed 錯誤。"""


@dataclass(frozen=True)
class DailyFormalInputPaths:
    """由呼叫端明確指定的來源與輸出路徑。"""

    output_root: Path
    development_output_root: Path
    market_db: Path
    clock_manifest: Path | None = None
    universe_symbols: Path | None = None
    owner_acceptance: Path | None = None
    formal_ledger_path: Path | None = None
    formal_rule_history_path: Path | None = None
    formal_sector_path: Path | None = None
    paper_snapshot_db_path: Path | None = None
    paper_trade_ledger_db_path: Path | None = None
    publication_root: Path | None = None
    # PIT 的獨立 denominator 不沿用 Rule universe；缺少時 handoff 只能
    # 保存 custody candidate，不能把 current source union 當正式歷史範圍。
    pit_expected_universe_path: Path | None = None
    # 歷史 coverage 起點必須由呼叫端明確給出；不可從目前 archive 的
    # 最早日期倒推，否則缺日會被遮蔽成看似完整的 Formal history。
    pit_history_coverage_start: date | None = None
    # 日常 Formal wrapper 可要求 PIT 只重驗 08:30 前已保存的 archive；
    # 設定後不會在盤後重新抓取同一自然日的官方 source。
    pit_preopen_archive_root: Path | None = None
    # 排程可把已驗證的官方日曆／臨時休市 cache 傳入同一個 consumer；
    # cache 只讀，缺失或過期仍由 OfficialTradingCalendar 回報 unknown。
    official_calendar_cache_path: Path | None = None
    official_temporary_closure_path: Path | None = None


@dataclass(frozen=True)
class OfficialSourceResponse:
    """一個 bounded 官方 response 的 bytes 與 completion metadata。"""

    body: bytes
    metadata: Mapping[str, object]


def _build_official_calendar(paths: DailyFormalInputPaths) -> OfficialTradingCalendar:
    """建立帶 cache 設定的 calendar，並保留舊測試替身的建構契約。"""

    kwargs: dict[str, Any] = {"db_path": paths.market_db}
    if paths.official_calendar_cache_path is not None:
        kwargs["calendar_cache_path"] = paths.official_calendar_cache_path
    if paths.official_temporary_closure_path is not None:
        kwargs["temporary_closure_path"] = paths.official_temporary_closure_path
    try:
        return OfficialTradingCalendar(**kwargs)
    except TypeError as error:
        # 部分隔離測試使用只接受 db_path 的舊替身；只有明確是新增
        # keyword 不相容時才回退，不能吞掉 calendar 本身的初始化錯誤。
        if "unexpected keyword argument" not in str(error):
            raise
        return OfficialTradingCalendar(db_path=paths.market_db)


def build_daily_formal_input_preflight(
    paths: DailyFormalInputPaths,
    *,
    now: datetime | None = None,
    calendar: OfficialTradingCalendar | None = None,
) -> dict[str, object]:
    """唯讀建立日常來源 preflight。

    ``now`` 只供隔離測試注入；CLI 不提供日期覆寫。這裡不下載 PIT raw、
    不建立 artifact，也不會因 owner／reviewer 名字缺失增加 blocker。
    """

    observed_utc = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    ).astimezone(timezone.utc)
    calendar_service = calendar or _build_official_calendar(paths)
    observed_taipei = observed_utc.astimezone(TAIPEI)
    blockers: list[str] = []
    blockers.extend(_output_preflight_blockers(paths.output_root))
    blockers.extend(_output_preflight_blockers(paths.development_output_root))
    publication_projection, publication_blockers = _publication_root_projection(
        paths.publication_root
    )
    blockers.extend(publication_blockers)

    clock, clock_projection, clock_blockers = _load_clock_projection(
        paths.clock_manifest,
        now=observed_utc,
    )
    blockers.extend(clock_blockers)

    universe, universe_projection, universe_blockers = _load_universe_projection(
        paths.universe_symbols
    )
    blockers.extend(universe_blockers)

    acceptance_projection, acceptance_blockers = _acceptance_projection(
        paths.owner_acceptance,
        clock=clock,
        market_db=paths.market_db,
        observed=observed_utc,
    )
    blockers.extend(acceptance_blockers)

    market_projection, market_blockers = _market_projection(paths.market_db)
    blockers.extend(market_blockers)

    calendar_projection, calendar_blockers = _calendar_projection(
        paths.market_db,
        target_date=observed_taipei.date(),
        calendar=calendar_service,
    )
    blockers.extend(calendar_blockers)

    rule_blockers: list[str] = []
    if clock is None:
        rule_blockers.append("rule_clock_source_missing_or_invalid")
    else:
        if observed_taipei.date() < clock.activation_trading_day:
            rule_blockers.append(
                "clock_activation_day_in_future:"
                f"{clock.activation_trading_day.isoformat()}"
                f">{observed_taipei.date().isoformat()}"
            )
        decision_time = _clock_decision_time(clock)
        if decision_time is None:
            rule_blockers.append("clock_decision_time_invalid")
        elif observed_taipei.timetz().replace(tzinfo=None) < decision_time:
            rule_blockers.append("rule_before_clock_decision_boundary")
    if not RULE_SESSION_OPEN <= observed_taipei.timetz().replace(
        tzinfo=None
    ) <= RULE_SESSION_CLOSE:
        rule_blockers.append("rule_capture_outside_taiwan_regular_session")
    if paths.owner_acceptance is None:
        rule_blockers.append("rule_owner_acceptance_source_missing")
    if paths.universe_symbols is None:
        rule_blockers.append("rule_universe_source_missing")
    if not _env_configured(RULE_HMAC_KEY_ENV):
        rule_blockers.append("rule_controlled_hmac_runtime_missing")
    if not _env_configured(RULE_STORE_ID_ENV):
        rule_blockers.append("rule_controlled_store_identity_missing")
    if market_projection.get("state") != "ready":
        rule_blockers.append("rule_market_db_not_readable")
    if calendar_projection.get("is_trading_day") is not True:
        rule_blockers.append("rule_official_trading_day_not_proven")
    blockers.extend(rule_blockers)

    # 公司基本資料的現況 capture 可以在休市日或收盤後取得；其
    # response completion timestamp 才是 source availability。是否能被
    # 下一個 trading decision 消費，交由正式 consumer 以 decision_at、
    # official calendar 與 cutoff 另外判定，不能在 capture preflight 先
    # 用市場交易時段製造 blocker。
    pit_capture_blockers: list[str] = []
    if not _env_configured(RULE_HMAC_KEY_ENV):
        pit_capture_blockers.append("pit_controlled_publisher_hmac_runtime_missing")
    if not _env_configured(RULE_STORE_ID_ENV):
        pit_capture_blockers.append("pit_controlled_publisher_identity_missing")
    pit_trading_decision_blockers: list[str] = []
    if calendar_projection.get("is_trading_day") is not True:
        pit_trading_decision_blockers.append("pit_official_trading_day_not_proven")
    blockers.extend(pit_capture_blockers)

    explicit = _explicit_formal_source_projections(paths)
    for projection in explicit.values():
        if projection.get("state") == "missing":
            blockers.append(str(projection["reason"]))

    paper_sources, paper_source_blockers = _paper_source_projections(paths)
    durable_ledger_projection = _durable_ledger_publication_projection(
        paths,
        observed=observed_utc,
        paper_sources=paper_sources,
    )
    paper_sources["durable_causal_ledger"] = durable_ledger_projection
    # An explicit, already published formal ledger is self-contained.  When it
    # is absent, the only admissible daily writer input is the real Paper
    # snapshot boundary plus the append-only Paper fill ledger; either missing
    # source remains a concrete machine blocker.
    if paths.formal_ledger_path is None:
        if durable_ledger_projection.get("state") != "ready":
            blockers.extend(paper_source_blockers)
            if durable_ledger_projection.get("state") in {"invalid", "unavailable"}:
                blockers.append(str(durable_ledger_projection["reason"]))

    identities: dict[str, object] = {}
    if clock_projection:
        identities["accepted_rule_clock"] = clock_projection
    if acceptance_projection:
        identities["owner_acceptance"] = acceptance_projection
    if universe_projection:
        identities["rule_universe"] = universe_projection

    body: dict[str, object] = {
        "schema_version": DAILY_FORMAL_INPUT_PRODUCER_SCHEMA_VERSION,
        "producer": "data_module.formal_daily_input_producer",
        "producer_version": DAILY_FORMAL_INPUT_PRODUCER_VERSION,
        "observed_at": observed_utc.isoformat(),
        "decision_at": observed_utc.isoformat(),
        "decision_timezone": "Asia/Taipei",
        "identities": identities,
        "market_source": market_projection,
        "official_calendar": calendar_projection,
        "publication": publication_projection,
        "formal_sources": explicit,
        "paper_sources": paper_sources,
        "rule_capture": {
            "eligible": not rule_blockers,
            "source": "development_module.prospective_rule_only_decision",
            "publisher": "data_module.prospective_rule_champion_publisher",
            "consumer": "data_module.rule_champion_snapshot_service.RuleChampionSnapshotService",
            "blockers": sorted(set(rule_blockers)),
            "candidate_only": True,
        },
        "pit_capture": {
            # ``eligible`` is retained as a compatibility alias for callers
            # that only understand the old capture field.
            "eligible": not pit_capture_blockers,
            "capture_eligible": not pit_capture_blockers,
            "capture_blockers": sorted(set(pit_capture_blockers)),
            "trading_decision_eligible": not pit_trading_decision_blockers,
            "trading_decision_blockers": sorted(
                set(pit_trading_decision_blockers)
            ),
            "source": "official TWSE/TPEx OpenAPI",
            "producer": "data_module.pit_sector_membership_machine",
            "publisher": "data_module.pit_sector_machine_publisher",
            "consumer": "data_module.pit_sector_machine_publisher.consume_machine_pit_operational_candidate",
            "blockers": sorted(set(pit_capture_blockers)),
            "candidate_only": True,
        },
        "blockers": sorted(set(blockers)),
        "human_review_required": False,
        "owner_reviewer_required": False,
        "formal_ready_input_count": 0,
        "formal_consumer_compatible_count": 0,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_market_database": False,
        "writes_formal_controlled_paths": False,
        "training_started": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
        "secret_values_emitted": False,
    }
    return {**body, "preflight_hash": _payload_hash(body)}


def run_daily_formal_input_producer(
    paths: DailyFormalInputPaths,
    *,
    now: datetime | None = None,
    calendar: OfficialTradingCalendar | None = None,
    fetch_source: Callable[[str], OfficialSourceResponse] | None = None,
) -> dict[str, object]:
    """執行一輪 bounded source→producer→consumer handoff。

    只有 current natural-day PIT candidate 與 current clock Rule candidate
    會由本函式建立 TEMP artifact。正式三項 input 則只接受呼叫端明確給的
    path 並以既有 production consumer readback；缺少 formal ledger writer
    時絕不由 Paper／simulated state 推造 causal ledger。
    """

    observed_utc = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    ).astimezone(timezone.utc)
    # Build one calendar service for this invocation and reuse it for both the
    # preflight projection and the PIT history handoff.  The preflight already
    # proves the official schedule; dropping that service at the handoff
    # boundary would turn a valid calendar observation into the unrelated
    # ``official_calendar_required`` blocker and could trigger a second HTTP
    # lookup.  A caller supplied test/service remains authoritative.
    calendar_service = calendar or _build_official_calendar(paths)
    preflight = build_daily_formal_input_preflight(
        paths,
        now=observed_utc,
        calendar=calendar_service,
    )
    output_root = _prepare_output_root(paths.output_root)
    development_root = _prepare_development_root(paths.development_output_root)
    # The development producer requires this exact basename; create it only
    # after the TEMP boundary has been checked.
    if development_root != paths.development_output_root.expanduser().resolve():
        raise FormalDailyInputProducerError(
            "development output root was normalized unexpectedly"
        )

    result_inputs: dict[str, object] = {}
    blockers = [str(item) for item in cast(list[object], preflight["blockers"])]
    preflight_rule = _mapping(preflight["rule_capture"], "rule_capture")
    preflight_pit = _mapping(preflight["pit_capture"], "pit_capture")
    clock = _load_clock_from_preflight(paths.clock_manifest, observed_utc)
    universe = _read_symbols(paths.universe_symbols) if paths.universe_symbols else None

    if preflight_rule.get("eligible") is True and clock is not None and universe:
        try:
            rule_result = _produce_rule_candidate(
                paths=paths,
                output_root=output_root,
                clock=clock,
                now=observed_utc.astimezone(TAIPEI),
                publication_root=paths.publication_root,
            )
            result_inputs["rule_candidate"] = rule_result
        except Exception as error:  # noqa: BLE001 - persist a bounded blocker
            detail = _safe_error(error)
            reason = f"rule_source_production_failed:{detail}"
            blockers.append(reason)
            result_inputs["rule_candidate"] = {
                "status": "blocked",
                "formal_consumer_compatible": False,
                "candidate_only": True,
                "reason": reason,
            }
    else:
        result_inputs["rule_candidate"] = {
            "status": "blocked",
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "reason": "rule_capture_not_eligible",
            "blockers": _text_list(preflight_rule.get("blockers")),
        }

    if (
        preflight_pit.get("capture_eligible") is True
        or preflight_pit.get("eligible") is True
    ):
        try:
            expected_pit_symbols = (
                universe
                if _clock_is_current(clock, observed_utc.astimezone(TAIPEI))
                else None
            )
            if paths.pit_preopen_archive_root is not None:
                # 盤後的日常 wrapper 只能消費盤前已完成的 archive；不再
                # 以新的 response completion timestamp 重抓同一自然日。
                pit_result = _load_preopen_pit_candidate(
                    archive_root=paths.pit_preopen_archive_root,
                    observed=observed_utc,
                )
            else:
                pit_result = _produce_pit_candidate(
                    paths=paths,
                    output_root=output_root,
                    observed=observed_utc,
                    expected_symbols=expected_pit_symbols,
                    fetch_source=fetch_source,
                )
            result_inputs["pit_candidate"] = pit_result
            pit_result["trading_decision_eligible"] = (
                preflight_pit.get("trading_decision_eligible") is True
            )
            pit_result["trading_decision_blockers"] = _text_list(
                preflight_pit.get("trading_decision_blockers")
            )
            if paths.publication_root is not None:
                try:
                    from data_module.formal_pit_history_handoff import (  # noqa: PLC0415
                        persist_pit_candidate_history_handoff,
                    )

                    # The handoff has its own real persistence decision time.
                    # ``now`` injection remains a test seam for the source
                    # producer; production history must never inherit a
                    # caller-supplied historical clock.
                    history_handoff = persist_pit_candidate_history_handoff(
                        archive_root=paths.publication_root / "pit_candidate_archive",
                        publication_root=paths.publication_root,
                        decision_at=datetime.now(timezone.utc),
                        expected_universe_path=paths.pit_expected_universe_path,
                        coverage_start=paths.pit_history_coverage_start,
                        calendar=calendar_service,
                    )
                except Exception as error:  # noqa: BLE001 - retain candidate, expose blocker
                    handoff_reason = (
                        "pit_formal_history_handoff_failed:" + _safe_error(error)
                    )
                    pit_result["formal_history_handoff"] = {
                        "status": "blocked",
                        "candidate_only": True,
                        "formal_ready": False,
                        "formal_consumer_compatible": False,
                        "blockers": [handoff_reason],
                    }
                    blockers.append(handoff_reason)
                else:
                    pit_result["formal_history_handoff"] = history_handoff
                    # Keep the handoff's source blockers at the public receipt
                    # boundary as well as inside the PIT result.  A scheduled
                    # consumer must not require a human to inspect nested JSON
                    # to discover that the archive is still candidate-only.
                    blockers.extend(_text_list(history_handoff.get("blockers")))
        except Exception as error:  # noqa: BLE001 - persist a bounded blocker
            detail = _safe_error(error)
            reason = f"pit_source_production_failed:{detail}"
            blockers.append(reason)
            result_inputs["pit_candidate"] = {
                "status": "blocked",
                "formal_consumer_compatible": False,
                "candidate_only": True,
                "reason": reason,
            }
    else:
        result_inputs["pit_candidate"] = {
            "status": "blocked",
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "reason": "pit_capture_not_eligible",
            "blockers": _text_list(preflight_pit.get("blockers")),
        }

    paper_sources = _mapping(preflight.get("paper_sources"), "paper_sources")
    if paths.formal_ledger_path is None:
        paper_ready = all(
            _mapping(paper_sources.get(name), name).get("state") == "ready"
            for name in ("paper_snapshot", "paper_trade_ledger")
        )
        durable_ledger_ready = (
            _mapping(
                paper_sources.get("durable_causal_ledger"),
                "durable_causal_ledger",
            ).get("state")
            == "ready"
        )
        paper_ready = paper_ready or durable_ledger_ready
        if paper_ready:
            try:
                result_inputs["formal_ledger_candidate"] = (
                    _produce_formal_ledger_candidate(
                        paths=paths,
                        output_root=output_root,
                        observed=observed_utc,
                        calendar=calendar_service,
                        publication_root=paths.publication_root,
                    )
                )
            except Exception as error:  # noqa: BLE001 - bounded source blocker
                detail = _safe_error(error)
                reason = f"formal_ledger_source_rejected:{detail}"
                blockers.append(reason)
                result_inputs["formal_ledger_candidate"] = {
                    "status": "blocked",
                    "formal_consumer_compatible": False,
                    "candidate_only": True,
                    "reason": reason,
                }
        else:
            result_inputs["formal_ledger_candidate"] = {
                "status": "blocked",
                "formal_consumer_compatible": False,
                "candidate_only": True,
                "reason": "formal_ledger_real_paper_sources_not_ready",
                "blockers": [
                    str(
                        _mapping(item, "paper source").get(
                            "reason", "paper_source_not_ready"
                        )
                    )
                    for item in paper_sources.values()
                    if _mapping(item, "paper source").get("state") != "ready"
                ],
            }

    formal_results, formal_blockers = _readback_explicit_formal_sources(
        paths,
        training_as_of=observed_utc.isoformat(),
    )
    result_inputs.update(formal_results)
    blockers.extend(formal_blockers)

    formal_ready_count = sum(
        _mapping(value, "formal input result").get("formal_ready") is True
        for value in formal_results.values()
    )
    compatible_count = sum(
        _mapping(value, "formal input result").get("formal_consumer_compatible")
        is True
        for value in formal_results.values()
    )
    candidate_count = sum(
        _mapping(value, "produced input result").get("candidate_only") is True
        and _mapping(value, "produced input result").get("status")
        in {"machine_verified", "machine_verified_candidate", "published_candidate"}
        for value in result_inputs.values()
    )
    if formal_ready_count == 3:
        status = "formal_inputs_machine_verified"
    elif candidate_count:
        status = "candidate_only"
    else:
        status = "blocked"

    body: dict[str, object] = {
        "schema_version": DAILY_FORMAL_INPUT_PRODUCER_SCHEMA_VERSION,
        "producer": "data_module.formal_daily_input_producer",
        "producer_version": DAILY_FORMAL_INPUT_PRODUCER_VERSION,
        "status": status,
        "observed_at": observed_utc.isoformat(),
        "decision_at": observed_utc.isoformat(),
        "preflight": preflight,
        "inputs": result_inputs,
        "blockers": sorted(set(blockers)),
        "formal_ready_input_count": formal_ready_count,
        "formal_consumer_compatible_count": compatible_count,
        "machine_candidate_input_count": candidate_count,
        "human_review_required": False,
        "owner_reviewer_required": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_market_database": False,
        "writes_formal_controlled_paths": False,
        "training_started": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
        "secret_values_emitted": False,
    }
    receipt = {**body, "receipt_hash": _payload_hash(body)}
    _write_immutable_json(output_root / "formal_input_producer_receipt.json", receipt)
    return receipt


def _produce_rule_candidate(
    *,
    paths: DailyFormalInputPaths,
    output_root: Path,
    clock: ProspectiveFormalClock,
    now: datetime,
    publication_root: Path | None = None,
) -> dict[str, object]:
    if paths.universe_symbols is None or paths.owner_acceptance is None:
        raise FormalDailyInputProducerError("Rule source inputs are incomplete")
    _validate_rule_capture_window(clock, now)
    publication_run_dir: Path | None = None
    if publication_root is not None:
        durable_root = _prepare_publication_root(publication_root)
        publication_run_dir = (
            durable_root
            / "rule_history"
            / _aware_datetime(now, "now").astimezone(TAIPEI).date().isoformat()
        )
        if publication_run_dir.exists():
            return _load_rule_publication_retry(
                publication_run_dir,
                observed=now,
            )
    source = produce_prospective_rule_only_decision(
        development_output_root=paths.development_output_root,
        market_db=paths.market_db,
        clock_manifest_path=paths.clock_manifest or Path(""),
        universe_symbols_json=paths.universe_symbols,
        owner_acceptance_json=paths.owner_acceptance,
        now=now,
        allow_post_activation=True,
    )
    requests = _read_rule_requests(Path(str(source["requests_json"])))
    artifacts = JsonPersistedFormalArtifactLoader(
        Path(str(source["artifacts_json"]))
    )
    repository = PersistedFormalDecisionArtifactRepository(artifacts)
    snapshot = RuleChampionSnapshotService().build(
        strategy_version=str(source["strategy_version"]),
        policy_version=str(source["policy_version"]),
        score_configuration_hash=str(source["score_configuration_hash"]),
        universe_hash=str(source["universe_hash"]),
        selection_capacity=1,
        repository=repository,
        decision_snapshot_ids=requests[0].decision_snapshot_ids,
    )
    rule_dir = output_root / "rule_candidate"
    rule_dir.mkdir(parents=True, exist_ok=True)
    published = publish_prospective_rule_history(
        clock=clock,
        output_path=rule_dir / "prospective_rule_history.json",
        now=now,
        strategy_version=str(source["strategy_version"]),
        policy_version=str(source["policy_version"]),
        score_configuration_hash=str(source["score_configuration_hash"]),
        universe_hash=str(source["universe_hash"]),
        selection_capacity=1,
        repository=repository,
        requests=requests,
    )
    from data_module.prospective_capture_readiness import (  # noqa: PLC0415
        _read_canonical_object,
        _validate_rule_history_manifest,
    )

    consumed_history = _read_canonical_object(
        published.manifest_path,
        "prospective Rule history manifest",
    )
    _validate_rule_history_manifest(
        consumed_history,
        clock=clock,
        decision=now,
        now=now,
    )
    candidate_formal_manifest_path = rule_dir / "formal_rule_history.json"
    candidate_formal_history = _publish_formal_rule_history(
        snapshot=snapshot,
        output_path=candidate_formal_manifest_path,
        observed=now,
    )
    formal_manifest_path = candidate_formal_manifest_path
    formal_history = candidate_formal_history
    if publication_run_dir is not None:
        try:
            publication_run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise FormalDailyInputProducerError(
                "Rule publication run appeared during capture"
            ) from error
        formal_manifest_path = publication_run_dir / "manifest.json"
        formal_history = _publish_formal_rule_history(
            snapshot=snapshot,
            output_path=formal_manifest_path,
            observed=now,
        )
    result: dict[str, object] = {
        "status": "machine_verified_candidate",
        "source_lane": "prospective_formal_simulation",
        "producer": "development_module.prospective_rule_only_decision",
        "producer_version": "prospective-rule-only-source.v1",
        "source_run_id": source.get("run_id"),
        "source_lineage_hash": source.get("source_lineage_hash"),
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "strategy_version": snapshot.strategy_version,
        "policy_version": snapshot.policy_version,
        "universe_hash": snapshot.universe_hash,
        "decision_timestamp": snapshot.decision_timestamp,
        "snapshot_content_hash": snapshot.content_hash,
        "publisher": "data_module.prospective_rule_champion_publisher",
        "publisher_manifest_path": str(published.manifest_path),
        "publisher_manifest_hash": published.manifest_hash,
        "publisher_file_hash": published.manifest_file_hash,
        "consumer": "data_module.rule_champion_snapshot_service.RuleChampionSnapshotService",
        "consumer_readback": (
            "data_module.prospective_capture_readiness."
            "_validate_rule_history_manifest"
        ),
        "consumer_manifest_hash": consumed_history["manifest_hash"],
        "consumer_verified": consumed_history["manifest_hash"] == published.manifest_hash,
        "prospective_consumer": (
            "data_module.prospective_capture_readiness._validate_rule_history_manifest"
        ),
        "prospective_consumer_verified": consumed_history["manifest_hash"]
        == published.manifest_hash,
        "candidate_formal_manifest_path": str(candidate_formal_manifest_path),
        "formal_manifest_path": str(formal_manifest_path),
        "formal_manifest_hash": formal_history.manifest_hash,
        "formal_manifest_file_hash": formal_history.manifest_file_hash,
        "formal_consumer": (
            "data_module.rule_champion_snapshot_service."
            "load_verified_rule_champion_snapshot_history"
        ),
        "formal_consumer_verified": True,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }
    receipt_path, receipt_hash, receipt_file_hash = _write_input_receipt(
        output_path=rule_dir / "receipt.json",
        input_name="formal_rule_champion_snapshot_history",
        result=result,
        observed=now,
    )
    result.update(
        {
            "receipt_path": str(receipt_path),
            "receipt_hash": receipt_hash,
            "receipt_file_hash": receipt_file_hash,
        }
    )
    if publication_run_dir is not None:
        publication_receipt_path = publication_run_dir / "receipt.json"
        publication_result = dict(result)
        publication_result.update(
            {
                "publication_run_id": publication_run_dir.name,
                "publication_receipt_path": str(publication_receipt_path.resolve()),
                "publication_natural_date": now.astimezone(TAIPEI)
                .date()
                .isoformat(),
                "publication_status": "published",
            }
        )
        _write_publication_context(
            run_dir=publication_run_dir,
            input_name="formal_rule_champion_snapshot_history",
            result=publication_result,
            observed=now,
        )
        (
            publication_receipt_path,
            publication_receipt_hash,
            publication_receipt_file_hash,
        ) = _write_input_receipt(
            output_path=publication_receipt_path,
            input_name="formal_rule_champion_snapshot_history",
            result=publication_result,
            observed=now,
        )
        result.update(
            {
                "publication_run_id": publication_run_dir.name,
                "publication_receipt_path": str(publication_receipt_path),
                "publication_receipt_hash": publication_receipt_hash,
                "publication_receipt_file_hash": publication_receipt_file_hash,
                "publication_natural_date": now.astimezone(TAIPEI)
                .date()
                .isoformat(),
                "publication_status": "published",
            }
        )
    return result


def _publish_formal_rule_history(
    *,
    snapshot: RuleChampionSnapshot,
    output_path: Path,
    observed: datetime,
) -> Any:
    """將已驗證的 Rule snapshot 封裝成正式 loader 可讀的 immutable manifest。

    prospective publisher 的 clock-bound schema 與正式 Rule consumer 的
    history schema 是兩個不同契約；這裡只把同一個受控 HMAC snapshot 轉成
    正式 loader 所需的最小 manifest，clock／來源 completion／candidate-only
    語意由外層 daily receipt 綁定，絕不把未驗證 JSON 升格。
    """

    if not isinstance(snapshot, RuleChampionSnapshot):
        raise FormalDailyInputProducerError(
            "formal Rule history requires a verified RuleChampionSnapshot"
        )
    rows = snapshot.decision_rows
    if not rows:
        raise FormalDailyInputProducerError(
            "formal Rule history requires at least one verified decision row"
        )
    registered_store_ids = {
        _required_nonempty_text(
            row.registered_store_id,
            "formal Rule decision registered_store_id",
        )
        for row in rows
    }
    if len(registered_store_ids) != 1:
        raise FormalDailyInputProducerError(
            "formal Rule history decision rows use different controlled stores"
        )
    decision_timestamp = _required_nonempty_text(
        snapshot.decision_timestamp,
        "formal Rule snapshot decision_timestamp",
    )
    decision_at = _aware_datetime(
        decision_timestamp,
        "formal Rule snapshot decision_timestamp",
    ).astimezone(TAIPEI)
    observed_taipei = _aware_datetime(observed, "observed").astimezone(TAIPEI)
    if decision_at > observed_taipei:
        raise FormalDailyInputProducerError(
            "formal Rule snapshot decision timestamp is after capture time"
        )
    body: dict[str, object] = {
        "schema_version": RULE_CHAMPION_HISTORY_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "rule_only_proof": FORMAL_RULE_ONLY,
        "registered_store_id": next(iter(registered_store_ids)),
        "decision_dates": [decision_at.date().isoformat()],
        "snapshot_count": 1,
        "snapshots": [snapshot.to_manifest()],
    }
    manifest = {**body, "manifest_hash": _payload_hash(body)}
    _write_immutable_json(output_path, manifest)
    return load_verified_rule_champion_snapshot_history(
        output_path,
        decision_dates=(decision_at.date().isoformat(),),
        training_as_of=observed_taipei.isoformat(),
    )


def _write_input_receipt(
    *,
    output_path: Path,
    input_name: str,
    result: Mapping[str, object],
    observed: datetime,
) -> tuple[Path, str, str]:
    """保存一份綁定 producer 結果與 consumer readback 的 immutable receipt。"""

    body: dict[str, object] = {
        "schema_version": DAILY_FORMAL_INPUT_SOURCE_RECEIPT_SCHEMA_VERSION,
        "input": input_name,
        "producer": "data_module.formal_daily_input_producer",
        "observed_at": _aware_datetime(observed, "observed").astimezone(timezone.utc).isoformat(),
        "result": dict(result),
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_formal_controlled_paths": False,
        "historical_backfill_claimed": False,
    }
    receipt = {**body, "receipt_hash": _payload_hash(body)}
    _write_immutable_json(output_path, receipt)
    file_hash = _file_hash_or_none(output_path)
    if file_hash is None:
        raise FormalDailyInputProducerError(
            f"{input_name} receipt hash is unavailable"
        )
    return output_path, str(receipt["receipt_hash"]), file_hash


def _write_publication_context(
    *,
    run_dir: Path,
    input_name: str,
    result: Mapping[str, object],
    observed: datetime,
) -> Path:
    """在 receipt 前保存可恢復的 publication context。

    manifest 已落盤而 receipt 寫入失敗時，下一次 retry 必須能用這份
    immutable context 完成補寫；context 只保存已驗證結果與安全旗標，不能
    用來把未完成的 publication 宣稱成正式 input。
    """

    body: dict[str, object] = {
        "schema_version": DAILY_FORMAL_INPUT_PUBLICATION_CONTEXT_SCHEMA_VERSION,
        "input": input_name,
        "producer": "data_module.formal_daily_input_producer",
        "publication_run_id": run_dir.name,
        "observed_at": _aware_datetime(observed, "observed")
        .astimezone(timezone.utc)
        .isoformat(),
        "result": dict(result),
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_formal_controlled_paths": False,
        "historical_backfill_claimed": False,
    }
    payload = {**body, "context_hash": _payload_hash(body)}
    path = run_dir / "publication_context.json"
    _write_immutable_json(path, payload)
    return path


def _read_publication_context(
    path: Path,
    *,
    input_name: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """讀取並驗證 receipt 遺失時使用的 immutable recovery context。"""

    payload = _read_json_object(path)
    if payload.get("schema_version") != (
        DAILY_FORMAL_INPUT_PUBLICATION_CONTEXT_SCHEMA_VERSION
    ):
        raise FormalDailyInputProducerError(
            f"{input_name} publication context schema is invalid"
        )
    if payload.get("input") != input_name:
        raise FormalDailyInputProducerError(
            f"{input_name} publication context input is invalid"
        )
    supplied = payload.get("context_hash")
    body = dict(payload)
    body.pop("context_hash", None)
    if _payload_hash(body) != supplied:
        raise FormalDailyInputProducerError(
            f"{input_name} publication context hash mismatch"
        )
    result = _mapping(
        payload.get("result"),
        f"{input_name} publication context result",
    )
    if payload.get("publication_run_id") != result.get("publication_run_id"):
        raise FormalDailyInputProducerError(
            f"{input_name} publication context run identity mismatch"
        )
    return payload, result


def _write_paper_source_custody(
    *,
    run_dir: Path,
    snapshots: Sequence[Mapping[str, object]],
    fills: Sequence[Mapping[str, object]],
    snapshot_source_hash: str,
    fill_source_hash: str,
    snapshot_source_path: Path,
    fill_source_path: Path,
) -> dict[str, object]:
    """把已驗證 SQLite read transaction 的列保存到 durable publication。

    retry 不應依賴可能位於 TEMP 的原始 SQLite。這兩份 canonical custody
    artifact 只保存已通過 schema、Decimal、append-only 與安全旗標驗證的
    rows，並以 row-level hash 與 aggregate hash 綁定來源；不會把來源寫回
    原始資料庫。
    """

    snapshot_rows = [_snapshot_custody_payload(item) for item in snapshots]
    fill_rows = [_fill_custody_payload(item) for item in fills]
    snapshot_body: dict[str, object] = {
        "schema_version": FORMAL_PAPER_SOURCE_CUSTODY_SCHEMA_VERSION,
        "kind": "paper_snapshots",
        "source_path": str(snapshot_source_path.expanduser().resolve()),
        "source_content_hash": snapshot_source_hash,
        "row_count": len(snapshot_rows),
        "rows": snapshot_rows,
    }
    fill_body: dict[str, object] = {
        "schema_version": FORMAL_PAPER_SOURCE_CUSTODY_SCHEMA_VERSION,
        "kind": "paper_fills",
        "source_path": str(fill_source_path.expanduser().resolve()),
        "source_content_hash": fill_source_hash,
        "row_count": len(fill_rows),
        "rows": fill_rows,
    }
    snapshot_payload = {
        **snapshot_body,
        "custody_hash": _payload_hash(snapshot_body),
    }
    fill_payload = {**fill_body, "custody_hash": _payload_hash(fill_body)}
    snapshot_path = run_dir / "snapshot_source_custody.json"
    fill_path = run_dir / "fill_source_custody.json"
    _write_immutable_json(snapshot_path, snapshot_payload)
    _write_immutable_json(fill_path, fill_payload)
    snapshot_file_hash = _file_hash_or_none(snapshot_path)
    fill_file_hash = _file_hash_or_none(fill_path)
    if snapshot_file_hash is None or fill_file_hash is None:
        raise FormalDailyInputProducerError(
            "paper source custody artifact hash is unavailable"
        )
    return {
        "snapshot_source_custody_path": str(snapshot_path),
        "snapshot_source_custody_file_hash": snapshot_file_hash,
        "snapshot_source_custody_hash": snapshot_payload["custody_hash"],
        "fill_source_custody_path": str(fill_path),
        "fill_source_custody_file_hash": fill_file_hash,
        "fill_source_custody_hash": fill_payload["custody_hash"],
        "source_custody_schema_version": FORMAL_PAPER_SOURCE_CUSTODY_SCHEMA_VERSION,
        "source_custody_read_consistency": "sqlite_read_transaction_rows_copied_before_manifest",
    }


def _snapshot_custody_payload(row: Mapping[str, object]) -> dict[str, object]:
    """取出已驗證 snapshot row 的 JSON canonical payload。"""

    payload: dict[str, object] = {
        "schema_version": _required_nonempty_text(
            row.get("schema_version"), "paper snapshot schema_version"
        ),
        "snapshot_id": _required_nonempty_text(
            row.get("snapshot_id"), "paper snapshot snapshot_id"
        ),
        "portfolio_id": _required_nonempty_text(
            row.get("portfolio_id"), "paper snapshot portfolio_id"
        ),
        "decision_date": _record_date(
            row, "decision_date", "paper snapshot"
        ).isoformat(),
        "source_result_id": _required_nonempty_text(
            row.get("source_result_id"), "paper snapshot source_result_id"
        ),
        "cash": _required_nonempty_text(row.get("cash"), "paper snapshot cash"),
        "total_value": _required_nonempty_text(
            row.get("total_value"), "paper snapshot total_value"
        ),
        "positions": [
            dict(_mapping(item, "paper snapshot custody position"))
            for item in _mapping_sequence(row.get("positions"), "paper snapshot positions")
        ],
    }
    expected = _payload_hash(payload)
    if expected != row.get("content_hash"):
        raise FormalDailyInputProducerError(
            "paper snapshot custody row hash does not match validated source"
        )
    payload["content_hash"] = expected
    return payload


def _fill_custody_payload(row: Mapping[str, object]) -> dict[str, object]:
    """取出已驗證 PaperTradeFill 的 canonical payload。"""

    fill = row.get("fill")
    to_dict = getattr(fill, "to_dict", None)
    if not callable(to_dict):
        raise FormalDailyInputProducerError(
            "paper fill custody row lacks validated PaperTradeFill"
        )
    raw_payload = to_dict()
    if not isinstance(raw_payload, Mapping):
        raise FormalDailyInputProducerError("paper fill custody payload is invalid")
    payload = {str(key): value for key, value in raw_payload.items()}
    expected = _payload_hash(payload)
    if expected != row.get("content_hash"):
        raise FormalDailyInputProducerError(
            "paper fill custody row hash does not match validated source"
        )
    payload["content_hash"] = expected
    return payload


def _read_paper_source_custody(
    *,
    run_dir: Path,
    result: Mapping[str, object],
) -> tuple[str, str]:
    """重驗 durable Paper source custody，回傳兩個 aggregate hash。"""

    snapshot_path = Path(str(result.get("snapshot_source_custody_path")))
    fill_path = Path(str(result.get("fill_source_custody_path")))
    snapshot = _read_json_object(snapshot_path)
    fill = _read_json_object(fill_path)
    snapshot_hash = _validate_paper_source_custody_payload(
        snapshot,
        expected_kind="paper_snapshots",
        input_name="paper snapshot source custody",
    )
    fill_hash = _validate_paper_source_custody_payload(
        fill,
        expected_kind="paper_fills",
        input_name="paper fill source custody",
    )
    if snapshot_path.parent.resolve() != run_dir.resolve() or fill_path.parent.resolve() != run_dir.resolve():
        raise FormalDailyInputProducerError(
            "paper source custody path escapes publication run"
        )
    expected_snapshot_hash = result.get("snapshot_source_content_hash")
    expected_fill_hash = result.get("fill_source_content_hash")
    if snapshot_hash != expected_snapshot_hash:
        raise FormalDailyInputProducerError(
            "paper snapshot source custody aggregate hash mismatch"
        )
    if fill_hash != expected_fill_hash:
        raise FormalDailyInputProducerError(
            "paper fill source custody aggregate hash mismatch"
        )
    return snapshot_hash, fill_hash


def _validate_paper_source_custody_payload(
    payload: Mapping[str, object],
    *,
    expected_kind: str,
    input_name: str,
) -> str:
    if payload.get("schema_version") != FORMAL_PAPER_SOURCE_CUSTODY_SCHEMA_VERSION:
        raise FormalDailyInputProducerError(f"{input_name} schema is invalid")
    if payload.get("kind") != expected_kind:
        raise FormalDailyInputProducerError(f"{input_name} kind is invalid")
    body = dict(payload)
    supplied_custody_hash = body.pop("custody_hash", None)
    if _payload_hash(body) != supplied_custody_hash:
        raise FormalDailyInputProducerError(f"{input_name} custody hash mismatch")
    rows_value = payload.get("rows")
    if not isinstance(rows_value, list):
        raise FormalDailyInputProducerError(f"{input_name} rows are invalid")
    if payload.get("row_count") != len(rows_value):
        raise FormalDailyInputProducerError(f"{input_name} row count mismatch")
    normalized: list[Mapping[str, object]] = []
    for value in rows_value:
        row = _mapping(value, f"{input_name} row")
        content_hash = row.get("content_hash")
        row_body = dict(row)
        row_body.pop("content_hash", None)
        if _payload_hash(row_body) != content_hash:
            raise FormalDailyInputProducerError(
                f"{input_name} row content hash mismatch"
            )
        normalized.append(row)
    schema_version = (
        "paper-snapshot-source-custody.v1"
        if expected_kind == "paper_snapshots"
        else "paper-fill-source-custody.v1"
    )
    return _paper_rows_content_hash(normalized, schema_version=schema_version)


def _read_input_receipt(
    path: Path,
    *,
    input_name: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """讀取並重算單一 input receipt；不接受自行改寫的 retry 狀態。"""

    payload = _read_json_object(path)
    if payload.get("schema_version") != DAILY_FORMAL_INPUT_SOURCE_RECEIPT_SCHEMA_VERSION:
        raise FormalDailyInputProducerError(
            f"{input_name} receipt schema is invalid"
        )
    if payload.get("input") != input_name:
        raise FormalDailyInputProducerError(f"{input_name} receipt input is invalid")
    supplied = payload.get("receipt_hash")
    body = dict(payload)
    body.pop("receipt_hash", None)
    if _payload_hash(body) != supplied:
        raise FormalDailyInputProducerError(f"{input_name} receipt hash mismatch")
    result = _mapping(payload.get("result"), f"{input_name} receipt result")
    return payload, result


def _validate_rule_capture_window(
    clock: ProspectiveFormalClock,
    now: datetime,
) -> None:
    """確認 Rule 來源是在當日決策窗口內被實際捕捉。"""

    observed = _aware_datetime(now, "now").astimezone(TAIPEI)
    if observed.date() < clock.activation_trading_day:
        raise FormalDailyInputProducerError(
            "Rule capture natural date precedes clock activation"
        )
    if not RULE_SESSION_OPEN <= observed.timetz().replace(tzinfo=None) <= RULE_SESSION_CLOSE:
        raise FormalDailyInputProducerError(
            "Rule capture is outside Taiwan regular session"
        )
    decision_time = _clock_decision_time(clock)
    if decision_time is None:
        raise FormalDailyInputProducerError("Rule clock decision_time is invalid")
    if observed.timetz().replace(tzinfo=None) < decision_time:
        raise FormalDailyInputProducerError(
            "Rule capture is before clock decision boundary"
        )


def _load_rule_publication_retry(
    run_dir: Path,
    *,
    observed: datetime,
) -> dict[str, object]:
    """重驗既有 Rule publication，確認 retry 不會另建或覆寫同日輸出。"""

    if not run_dir.is_dir():
        raise FormalDailyInputProducerError("Rule publication run is not a directory")
    receipt_path = run_dir / "receipt.json"
    manifest_path = run_dir / "manifest.json"
    receipt_missing = not receipt_path.is_file()
    if receipt_missing:
        context_path = run_dir / "publication_context.json"
        _context, result = _read_publication_context(
            context_path,
            input_name="formal_rule_champion_snapshot_history",
        )
    else:
        _receipt, result = _read_input_receipt(
            receipt_path,
            input_name="formal_rule_champion_snapshot_history",
        )
    if Path(str(result.get("formal_manifest_path"))).resolve() != manifest_path.resolve():
        raise FormalDailyInputProducerError(
            "Rule publication receipt does not bind its manifest path"
        )
    decision_timestamp = _aware_datetime(
        result.get("decision_timestamp"),
        "published Rule decision_timestamp",
    ).astimezone(TAIPEI)
    observed_taipei = _aware_datetime(observed, "observed").astimezone(TAIPEI)
    if decision_timestamp > observed_taipei:
        raise FormalDailyInputProducerError(
            "published Rule decision timestamp is after retry time"
        )
    history = load_verified_rule_champion_snapshot_history(
        manifest_path,
        decision_dates=(decision_timestamp.date().isoformat(),),
        training_as_of=observed_taipei.isoformat(),
    )
    if history.manifest_hash != result.get("formal_manifest_hash"):
        raise FormalDailyInputProducerError(
            "Rule publication manifest hash changed during retry"
        )
    if history.manifest_file_hash != result.get("formal_manifest_file_hash"):
        raise FormalDailyInputProducerError(
            "Rule publication manifest file hash changed during retry"
        )
    result = dict(result)
    if receipt_missing:
        recovery_result = dict(result)
        recovery_result.update(
            {
                "publication_run_id": run_dir.name,
                "publication_receipt_path": str(receipt_path.resolve()),
                "publication_status": "recovered_after_receipt_failure",
                "idempotent_retry": True,
            }
        )
        (
            _recovered_path,
            recovered_hash,
            recovered_file_hash,
        ) = _write_input_receipt(
            output_path=receipt_path,
            input_name="formal_rule_champion_snapshot_history",
            result=recovery_result,
            observed=observed,
        )
        result = recovery_result
        result.update(
            {
                "publication_receipt_hash": recovered_hash,
                "publication_receipt_file_hash": recovered_file_hash,
            }
        )
        return result
    result.update(
        {
            "publication_run_id": run_dir.name,
            "publication_receipt_path": str(receipt_path.resolve()),
            "publication_receipt_file_hash": _file_hash_or_none(receipt_path),
            "publication_status": "idempotent_retry",
            "idempotent_retry": True,
        }
    )
    return result


def _load_ledger_publication_retry(
    run_dir: Path,
    *,
    observed: datetime,
    snapshot_source_hash: str | None = None,
    fill_source_hash: str | None = None,
    recover_missing_receipt: bool = True,
) -> dict[str, object]:
    """重驗既有 causal ledger publication，避免 retry 產生第二條 chain。"""

    if not run_dir.is_dir():
        raise FormalDailyInputProducerError(
            "causal ledger publication run is not a directory"
        )
    receipt_path = run_dir / "receipt.json"
    manifest_path = run_dir / "manifest.json"
    receipt_missing = not receipt_path.is_file()
    if receipt_missing:
        _context, result = _read_publication_context(
            run_dir / "publication_context.json",
            input_name="causal_non_cash_portfolio_ledger",
        )
    else:
        _receipt, result = _read_input_receipt(
            receipt_path,
            input_name="causal_non_cash_portfolio_ledger",
        )
    if Path(str(result.get("manifest_path"))).resolve() != manifest_path.resolve():
        raise FormalDailyInputProducerError(
            "causal ledger receipt does not bind its manifest path"
        )
    stored_snapshot_hash = result.get("snapshot_source_content_hash")
    stored_fill_hash = result.get("fill_source_content_hash")
    if snapshot_source_hash is not None and stored_snapshot_hash != snapshot_source_hash:
        raise FormalDailyInputProducerError(
            "causal ledger snapshot source changed during retry"
        )
    if fill_source_hash is not None and stored_fill_hash != fill_source_hash:
        raise FormalDailyInputProducerError(
            "causal ledger fill source changed during retry"
        )
    if not _is_sha256(stored_snapshot_hash) or not _is_sha256(stored_fill_hash):
        raise FormalDailyInputProducerError(
            "causal ledger source custody hashes are invalid"
        )
    if not receipt_missing:
        custody_snapshot_hash, custody_fill_hash = _read_paper_source_custody(
            run_dir=run_dir,
            result=result,
        )
        if custody_snapshot_hash != stored_snapshot_hash:
            raise FormalDailyInputProducerError(
                "causal ledger snapshot source custody changed during retry"
            )
        if custody_fill_hash != stored_fill_hash:
            raise FormalDailyInputProducerError(
                "causal ledger fill source custody changed during retry"
            )
    else:
        custody_snapshot_hash, custody_fill_hash = _read_paper_source_custody(
            run_dir=run_dir,
            result=result,
        )
        if custody_snapshot_hash != stored_snapshot_hash:
            raise FormalDailyInputProducerError(
                "causal ledger snapshot source custody changed during recovery"
            )
        if custody_fill_hash != stored_fill_hash:
            raise FormalDailyInputProducerError(
                "causal ledger fill source custody changed during recovery"
            )
    replay = _readback_formal_ledger(manifest_path, observed.isoformat())
    if replay.get("manifest_hash") != result.get("manifest_hash"):
        raise FormalDailyInputProducerError(
            "causal ledger publication manifest hash changed during retry"
        )
    if replay.get("ledger_file_hash") != result.get("sqlite_file_hash"):
        raise FormalDailyInputProducerError(
            "causal ledger publication sqlite hash changed during retry"
        )
    result = dict(result)
    if receipt_missing and recover_missing_receipt:
        recovery_result = dict(result)
        recovery_result.update(
            {
                "publication_run_id": run_dir.name,
                "publication_receipt_path": str(receipt_path.resolve()),
                "publication_status": "recovered_after_receipt_failure",
                "idempotent_retry": True,
            }
        )
        (
            _recovered_path,
            recovered_hash,
            recovered_file_hash,
        ) = _write_input_receipt(
            output_path=receipt_path,
            input_name="causal_non_cash_portfolio_ledger",
            result=recovery_result,
            observed=observed,
        )
        result = recovery_result
        result.update(
            {
                "publication_receipt_hash": recovered_hash,
                "publication_receipt_file_hash": recovered_file_hash,
            }
        )
        return result
    if receipt_missing:
        result.update(
            {
                "publication_run_id": run_dir.name,
                "publication_receipt_path": str(receipt_path.resolve()),
                "publication_status": "receipt_recovery_pending",
                "idempotent_retry": False,
            }
        )
        return result
    result.update(
        {
            "publication_run_id": run_dir.name,
            "publication_receipt_path": str(receipt_path.resolve()),
            "publication_receipt_file_hash": _file_hash_or_none(receipt_path),
            "publication_status": "idempotent_retry",
            "idempotent_retry": True,
        }
    )
    return result


def _find_ledger_publication_for_missing_sources(
    *,
    publication_root: Path,
    snapshot_source_path: Path,
    fill_source_path: Path,
    observed: datetime,
) -> Path | None:
    """找出可由 durable custody 完成 retry 的既有 ledger run。

    原始 Paper SQLite 可能位於 TEMP，成功 publication 後可以被清理；此
    掃描只讀 publication metadata，並以原始 source path 與 Taipei 自然日
    綁定，真正內容完整性仍由 ``_load_ledger_publication_retry`` 的 receipt、
    custody、manifest 與 SQLite readback 再驗證。
    """

    root = publication_root.expanduser().resolve() / "causal_ledger"
    if not root.is_dir():
        return None
    expected_snapshot_path = str(snapshot_source_path.expanduser().resolve())
    expected_fill_path = str(fill_source_path.expanduser().resolve())
    expected_date = _aware_datetime(observed, "observed").astimezone(TAIPEI).date().isoformat()
    matches: list[Path] = []
    for candidate in sorted(root.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir():
            continue
        metadata_paths = (
            candidate / "receipt.json",
            candidate / "publication_context.json",
        )
        for metadata_path in metadata_paths:
            if not metadata_path.is_file():
                continue
            try:
                if metadata_path.name == "receipt.json":
                    _metadata, result = _read_input_receipt(
                        metadata_path,
                        input_name="causal_non_cash_portfolio_ledger",
                    )
                else:
                    _metadata, result = _read_publication_context(
                        metadata_path,
                        input_name="causal_non_cash_portfolio_ledger",
                    )
            except FormalDailyInputProducerError:
                continue
            if str(result.get("snapshot_source_path")) != expected_snapshot_path:
                continue
            if str(result.get("fill_source_path")) != expected_fill_path:
                continue
            if result.get("publication_natural_date") != expected_date:
                continue
            matches.append(candidate)
            break
    unique_matches = sorted(set(matches), key=lambda item: item.name)
    if len(unique_matches) > 1:
        raise FormalDailyInputProducerError(
            "multiple causal ledger publications match missing Paper sources"
        )
    return unique_matches[0] if unique_matches else None


def _durable_ledger_publication_projection(
    paths: DailyFormalInputPaths,
    *,
    observed: datetime,
    paper_sources: Mapping[str, object],
) -> dict[str, object]:
    """唯讀驗證缺少原始 TEMP source 時可否由 durable custody retry。"""

    if paths.publication_root is None:
        return {
            "state": "not_configured",
            "reason": "durable_ledger_publication_root_not_configured",
        }
    if (
        paths.paper_snapshot_db_path is None
        or paths.paper_trade_ledger_db_path is None
    ):
        return {
            "state": "unavailable",
            "reason": "durable_ledger_paper_source_paths_missing",
        }
    source_states = {
        name: _mapping(paper_sources.get(name), name).get("state")
        for name in ("paper_snapshot", "paper_trade_ledger")
    }
    if all(value == "ready" for value in source_states.values()):
        return {
            "state": "not_needed",
            "reason": "live_paper_sources_available",
        }
    try:
        run_dir = _find_ledger_publication_for_missing_sources(
            publication_root=paths.publication_root,
            snapshot_source_path=paths.paper_snapshot_db_path,
            fill_source_path=paths.paper_trade_ledger_db_path,
            observed=observed,
        )
    except FormalDailyInputProducerError as error:
        return {
            "state": "invalid",
            "reason": f"durable_ledger_publication_lookup_failed:{_safe_error(error)}",
        }
    if run_dir is None:
        return {
            "state": "unavailable",
            "reason": "durable_ledger_publication_for_missing_source_not_found",
        }
    try:
        result = _load_ledger_publication_retry(
            run_dir,
            observed=observed,
            recover_missing_receipt=False,
        )
    except Exception as error:  # noqa: BLE001 - preflight remains fail-closed
        return {
            "state": "invalid",
            "run_path": str(run_dir),
            "reason": f"durable_ledger_publication_validation_failed:{_safe_error(error)}",
        }
    return {
        "state": "ready",
        "run_path": str(run_dir),
        "reason": "durable_causal_ledger_custody_verified",
        "publication_status": result.get("publication_status"),
        "manifest_hash": result.get("manifest_hash"),
        "sqlite_file_hash": result.get("sqlite_file_hash"),
        "snapshot_source_content_hash": result.get("snapshot_source_content_hash"),
        "fill_source_content_hash": result.get("fill_source_content_hash"),
        "consumer_verified": result.get("consumer_verified") is True,
    }


def _produce_pit_candidate(
    *,
    paths: DailyFormalInputPaths,
    output_root: Path,
    observed: datetime,
    expected_symbols: tuple[str, ...] | None,
    fetch_source: Callable[[str], OfficialSourceResponse] | None,
    capture_cutoff: datetime | None = None,
) -> dict[str, object]:
    from data_module.prospective_official_pit_source import (  # noqa: PLC0415
        OFFICIAL_COMPANY_SOURCE_DEFINITIONS,
    )

    if capture_cutoff is not None:
        cutoff = _aware_datetime(capture_cutoff, "capture_cutoff")
        if observed >= cutoff:
            raise FormalDailyInputProducerError(
                "PIT preopen capture must start before Taipei 08:30 cutoff"
            )
    else:
        cutoff = None
    fetch = fetch_source or _fetch_official_source
    raw_payloads: dict[str, bytes] = {}
    metadata: dict[str, Mapping[str, object]] = {}
    for market in ("twse", "tpex"):
        response = fetch(OFFICIAL_COMPANY_SOURCE_DEFINITIONS[market].endpoint)
        if not isinstance(response, OfficialSourceResponse):
            raise FormalDailyInputProducerError(
                "official source fetcher must return OfficialSourceResponse"
            )
        raw_payloads[market] = response.body
        metadata[market] = response.metadata
    captured_at = max(
        _aware_datetime(item.get("captured_at"), f"{market}.captured_at")
        for market, item in metadata.items()
    )
    # response completion metadata is untrusted input until compared with the
    # real wall clock.  ``max(observed, captured_at)`` would make a future
    # 2099 timestamp appear valid; use the actual validation instant instead.
    actual_now = datetime.now(timezone.utc)
    # 測試 caller 可以提供一個稍後的決策 instant，但來源 completion
    # timestamp 仍必須先與真正的 wall clock 比較；不能讓 caller 提供的
    # future ``observed`` 把 2099 的偽造來源時間洗成有效。
    if captured_at > actual_now:
        raise FormalDailyInputProducerError(
            "pit source captured_at cannot be after current wall clock"
        )
    if cutoff is not None:
        if captured_at >= cutoff:
            raise FormalDailyInputProducerError(
                "PIT source completion must be before Taipei 08:30 cutoff"
            )
        if captured_at.astimezone(TAIPEI).date() != cutoff.astimezone(TAIPEI).date():
            raise FormalDailyInputProducerError(
                "PIT preopen capture source date does not match cutoff date"
            )
    # The producer's domain validation uses the caller's decision instant so a
    # replayed, already-captured fixture remains bound to its original
    # natural date.  ``actual_now`` above is still the independent wall-clock
    # guard against future-dated response metadata; production callers pass
    # the current clock, while tests may pass an earlier observed instant.
    # A live HTTP capture normally completes after the producer was invoked.
    # Use the later of the caller's decision instant and this real wall-clock
    # observation for validation; never move the clock forward to an
    # advertised source timestamp.
    # Keep deterministic historical test/replay seams intact, while allowing
    # a live invocation's response to complete a few seconds after its start.
    # A caller-supplied clock far from the host wall clock is not allowed to
    # rebase an artifact onto today's date.
    live_observation = abs(actual_now - observed) <= timedelta(minutes=5)
    validation_now = actual_now if live_observation else observed
    captured_taipei_date = captured_at.astimezone(TAIPEI).date()
    observed_taipei_date = observed.astimezone(TAIPEI).date()
    if captured_taipei_date != observed_taipei_date:
        raise FormalDailyInputProducerError(
            "pit capture natural date does not match observed natural date"
        )
    pit_dir = output_root / "pit_candidate"
    pit_dir.mkdir(parents=True, exist_ok=True)
    publication = build_machine_pit_publication(
        raw_payloads=raw_payloads,
        output_dir=pit_dir,
        captured_at=captured_at,
        now=validation_now,
        expected_symbols=expected_symbols,
        http_metadata=metadata,
    )
    receipt_path = pit_dir / "receipt.json"
    receipt = write_machine_pit_receipt(
        publication.publication_path,
        receipt_path=receipt_path,
        now=validation_now,
    )
    evaluated = _aware_datetime(receipt.get("evaluated_at"), "receipt.evaluated_at")
    decision_at = max(observed, captured_at, evaluated)
    operational = publish_machine_pit_operational_candidate(
        receipt_path,
        output_path=pit_dir / "operational.json",
        decision_at=decision_at,
        now=decision_at,
    )
    consumed = consume_machine_pit_operational_candidate(
        pit_dir / "operational.json",
        decision_at=decision_at,
        now=decision_at,
    )
    result: dict[str, object] = {
        "status": "machine_verified_candidate",
        "source_lane": "current_natural_day_machine_capture",
        "producer": "data_module.pit_sector_membership_machine",
        "producer_version": MACHINE_PIT_PRODUCER_VERSION,
        "producer_code_sha256": publication.producer_code_sha256,
        "publication_path": str(publication.publication_path),
        "publication_file_hash": publication.publication_file_hash,
        "publication_content_hash": publication.publication_content_hash,
        "receipt_path": str(receipt_path),
        "receipt_file_hash": receipt.get("receipt_file_hash"),
        "operational_path": str(pit_dir / "operational.json"),
        "operational_file_hash": operational.get("operational_file_hash"),
        "consumer": "data_module.pit_sector_machine_publisher.consume_machine_pit_operational_candidate",
        "consumer_verified": consumed.get("status") == "machine_verified",
        "captured_at": publication.captured_at,
        "decision_at": decision_at.isoformat(),
        "effective_from": publication.effective_from,
        "row_count": publication.row_count,
        "source_ids": list(publication.source_ids),
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "historical_backfill_claimed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }
    if paths.publication_root is not None:
        archive = _archive_pit_candidate(
            publication_root=paths.publication_root,
            pit_result=result,
            archive_cutoff=cutoff,
        )
        result.update(
            {
                "durable_archive": archive,
                "durable_archive_verified": archive.get(
                    "archive_readback_verified"
                )
                is True,
            }
        )
    return result


def capture_pit_candidate_before_cutoff(
    *,
    publication_root: Path,
    candidate_root: Path | None = None,
    now: datetime | None = None,
    expected_symbols: tuple[str, ...] | None = None,
    fetch_source: Callable[[str], OfficialSourceResponse] | None = None,
) -> dict[str, object]:
    """在台北 08:30 前抓取並保存當日 PIT candidate archive。

    這是日常 PIT capture 排程的唯一 live capture 入口。它先以真實
    ``now`` 驗證仍在 cutoff 前，再把每個官方 response 的 completion
    timestamp 傳入 ``_produce_pit_candidate``；任何一個 response 越過
    cutoff 都在 archive 寫入前 fail closed。盤後流程應改讀
    :func:`_load_preopen_pit_candidate`，不重新抓取同一自然日。
    """

    observed = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    ).astimezone(timezone.utc)
    observed_taipei = observed.astimezone(TAIPEI)
    cutoff = datetime.combine(
        observed_taipei.date(),
        PIT_PREOPEN_CUTOFF,
        tzinfo=TAIPEI,
    )
    if observed >= cutoff:
        raise FormalDailyInputProducerError(
            "PIT preopen capture is only allowed before Taipei 08:30 cutoff"
        )
    if candidate_root is None:
        output_root = Path(
            tempfile.mkdtemp(prefix="baldr_pit_preopen_candidate_")
        )
    else:
        output_root = candidate_root.expanduser().resolve()
        _require_temp_path(output_root, "PIT preopen candidate root")
        if output_root.exists():
            if not output_root.is_dir() or any(output_root.iterdir()):
                raise FormalDailyInputProducerError(
                    "PIT preopen candidate root must be a new empty TEMP directory"
                )
        else:
            output_root.mkdir(parents=True, exist_ok=False)
    result = _produce_pit_candidate(
        paths=DailyFormalInputPaths(
            output_root=output_root,
            development_output_root=output_root / "development",
            market_db=output_root / "unused-market.sqlite",
            publication_root=publication_root,
        ),
        output_root=output_root,
        observed=observed,
        expected_symbols=expected_symbols,
        fetch_source=fetch_source,
        capture_cutoff=cutoff,
    )
    result["source_lane"] = "preopen_cutoff_machine_capture"
    result["capture_cutoff"] = cutoff.isoformat()
    result["captured_before_cutoff"] = True
    result["post_cutoff_refetch_forbidden"] = True
    return result


def reuse_pit_candidate_archive_before_cutoff(
    *,
    publication_root: Path,
    now: datetime | None = None,
) -> dict[str, object]:
    """在盤前重用同日已驗證 archive，避免排程重抓造成多重 capture。

    盤前排程可能因電腦喚醒、retry 或另一個受控 task 而執行多次；同一
    Taipei 自然日應持有一份已完成 custody 的 PIT archive，而不是每次再
    產生一個帶不同 capture timestamp 的候選。此入口只讀既有 durable
    archive，並要求 archive 的 source completion 與 persistence 都早於
    08:30。若當日沒有 archive，呼叫端可以再進入唯一 live capture；若有
    archive 但重驗失敗，則 fail closed，不能用新的抓取掩蓋竄改或不完整
    custody。
    """

    observed = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "now",
    ).astimezone(timezone.utc)
    observed_taipei = observed.astimezone(TAIPEI)
    cutoff = datetime.combine(
        observed_taipei.date(),
        PIT_PREOPEN_CUTOFF,
        tzinfo=TAIPEI,
    )
    if observed >= cutoff:
        raise FormalDailyInputProducerError(
            "PIT preopen archive reuse is only allowed before Taipei 08:30 cutoff"
        )

    day_root = (
        publication_root.expanduser().resolve()
        / "pit_candidate_archive"
        / observed_taipei.date().isoformat()
    )
    try:
        manifests = sorted(day_root.glob("*/archive_manifest.json"))
    except OSError as error:
        raise FormalDailyInputProducerError(
            "PIT preopen archive directory cannot be listed"
        ) from error
    if not manifests:
        try:
            has_partial_archive = any(day_root.iterdir()) if day_root.is_dir() else False
        except OSError as error:
            raise FormalDailyInputProducerError(
                "PIT preopen archive directory cannot be inspected"
            ) from error
        if has_partial_archive:
            raise FormalDailyInputProducerError(
                "PIT preopen archive directory contains an incomplete archive"
            )
        raise FormalDailyInputProducerError(
            "PIT preopen archive is missing for "
            + observed_taipei.date().isoformat()
        )

    valid: list[tuple[datetime, str, dict[str, object], dict[str, object]]] = []
    invalid_reasons: list[str] = []
    for manifest_path in manifests:
        try:
            manifest = _pit_candidate_json_file(
                manifest_path,
                "PIT preopen archive manifest",
            )
            if manifest.get("effective_from") != observed_taipei.date().isoformat():
                raise FormalDailyInputProducerError(
                    "archive effective_from does not match consumer date"
                )
            captured = _aware_datetime(
                manifest.get("captured_at"),
                "PIT preopen archive captured_at",
            )
            archived = _aware_datetime(
                manifest.get("archived_at"),
                "PIT preopen archive archived_at",
            )
            if captured >= cutoff:
                raise FormalDailyInputProducerError(
                    "archive source completion is not before Taipei 08:30 cutoff"
                )
            if archived >= cutoff:
                raise FormalDailyInputProducerError(
                    "archive persistence is not before Taipei 08:30 cutoff"
                )
            readback = _readback_pit_candidate_archive(
                manifest_path,
                now=observed,
            )
            if readback.get("captured_at") != captured.isoformat():
                raise FormalDailyInputProducerError(
                    "archive captured_at changed during readback"
                )
            valid.append(
                (
                    captured,
                    str(manifest.get("archive_id")),
                    manifest,
                    readback,
                )
            )
        except Exception as error:  # noqa: BLE001 - each archive must pass custody
            invalid_reasons.append(f"{manifest_path.name}:{_safe_error(error)}")

    if not valid:
        detail = ";".join(invalid_reasons[:3])
        raise FormalDailyInputProducerError(
            "PIT preopen archive has no valid before-cutoff capture"
            + (":" + detail if detail else "")
        )

    captured, archive_id, manifest, readback = max(
        valid,
        key=lambda item: (item[0], item[1]),
    )
    manifest_path = Path(str(readback.get("manifest_path"))).expanduser().resolve()
    archive = {
        "schema_version": PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION,
        "archive_manifest_path": str(manifest_path),
        "archive_manifest_file_hash": _file_hash_or_none(manifest_path),
        "archive_root": str(manifest_path.parent),
        "archive_readback_verified": True,
        "archive_id": archive_id,
        "publication_content_hash": readback.get("publication_content_hash"),
        "row_count": readback.get("row_count"),
        "candidate_only": True,
        "formal_consumer_compatible": False,
    }
    return {
        "status": "machine_verified_candidate",
        "source_lane": "preopen_archive_reuse",
        "producer": manifest.get("producer"),
        "producer_version": manifest.get("producer_version"),
        "producer_code_sha256": manifest.get("producer_code_sha256"),
        "publication_path": readback.get("publication_path"),
        "publication_file_hash": readback.get("publication_file_hash"),
        "publication_content_hash": readback.get("publication_content_hash"),
        "receipt_path": readback.get("receipt_path"),
        "receipt_file_hash": readback.get("receipt_file_hash"),
        "operational_path": readback.get("operational_path"),
        "operational_file_hash": readback.get("operational_file_hash"),
        "consumer": manifest.get("consumer"),
        "consumer_verified": readback.get("consumer_verified") is True,
        "captured_at": captured.astimezone(timezone.utc).isoformat(),
        "decision_at": observed.isoformat(),
        "effective_from": readback.get("effective_from"),
        "row_count": readback.get("row_count"),
        "source_ids": readback.get("source_ids"),
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "historical_backfill_claimed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "durable_archive": archive,
        "durable_archive_verified": True,
        "capture_cutoff": cutoff.isoformat(),
        "captured_before_cutoff": True,
        "post_cutoff_refetch_forbidden": True,
        "archive_selection_reason": (
            "reused latest valid immutable archive captured and persisted before "
            "Taipei 08:30; live source refetch was skipped"
        ),
        "archive_manifest_hash": readback.get("manifest_hash"),
        "archive_manifest_status": manifest.get("status"),
    }


def _load_preopen_pit_candidate(
    *,
    archive_root: Path,
    observed: datetime,
) -> dict[str, object]:
    """盤後只讀當日 08:30 前 archive，禁止同日重新抓取 source。"""

    decision = _aware_datetime(observed, "observed").astimezone(timezone.utc)
    local = decision.astimezone(TAIPEI)
    cutoff = datetime.combine(local.date(), PIT_PREOPEN_CUTOFF, tzinfo=TAIPEI)
    if local < cutoff:
        raise FormalDailyInputProducerError(
            "preopen PIT archive consumer cannot run before Taipei 08:30 cutoff"
        )
    root = archive_root.expanduser().resolve()
    day_root = root / local.date().isoformat()
    try:
        manifests = sorted(day_root.glob("*/archive_manifest.json"))
    except OSError as error:
        raise FormalDailyInputProducerError(
            "PIT preopen archive directory cannot be listed"
        ) from error
    if not manifests:
        raise FormalDailyInputProducerError(
            "PIT preopen archive is missing for " + local.date().isoformat()
        )
    valid: list[tuple[datetime, str, dict[str, object]]] = []
    invalid_reasons: list[str] = []
    for manifest_path in manifests:
        try:
            manifest = _pit_candidate_json_file(
                manifest_path,
                "PIT preopen archive manifest",
            )
            if manifest.get("effective_from") != local.date().isoformat():
                raise FormalDailyInputProducerError(
                    "archive effective_from does not match consumer date"
                )
            captured = _aware_datetime(
                manifest.get("captured_at"),
                "PIT preopen archive captured_at",
            )
            archived = _aware_datetime(
                manifest.get("archived_at"),
                "PIT preopen archive archived_at",
            )
            if captured >= cutoff:
                raise FormalDailyInputProducerError(
                    "archive source completion is not before Taipei 08:30 cutoff"
                )
            if archived >= cutoff:
                raise FormalDailyInputProducerError(
                    "archive persistence is not before Taipei 08:30 cutoff"
                )
            if archived > decision:
                raise FormalDailyInputProducerError(
                    "archive was written after consumer decision"
                )
            readback = _readback_pit_candidate_archive(
                manifest_path,
                now=decision,
            )
            if readback.get("captured_at") != captured.isoformat():
                raise FormalDailyInputProducerError(
                    "archive captured_at changed during readback"
                )
            valid.append(
                (
                    captured,
                    str(manifest.get("archive_id")),
                    {**readback, "archive_manifest": manifest},
                )
            )
        except Exception as error:  # noqa: BLE001 - one bad archive must not pass
            invalid_reasons.append(
                f"{manifest_path.name}:{_safe_error(error)}"
            )
    if not valid:
        detail = ";".join(invalid_reasons[:3])
        raise FormalDailyInputProducerError(
            "PIT preopen archive has no valid before-cutoff capture"
            + (":" + detail if detail else "")
        )
    captured, archive_id, readback = max(
        valid,
        key=lambda item: (item[0], item[1]),
    )
    selected_manifest_value = readback.get("archive_manifest")
    if not isinstance(selected_manifest_value, Mapping):  # pragma: no cover - readback guard
        raise FormalDailyInputProducerError("PIT preopen archive manifest projection is invalid")
    selected_manifest = {
        str(key): value for key, value in selected_manifest_value.items()
    }
    return {
        "status": "machine_verified_candidate",
        "source_lane": "preopen_archive_readback",
        "producer": selected_manifest.get("producer"),
        "producer_version": selected_manifest.get("producer_version"),
        "producer_code_sha256": selected_manifest.get("producer_code_sha256"),
        "publication_path": readback.get("publication_path"),
        "publication_file_hash": readback.get("publication_file_hash"),
        "publication_content_hash": readback.get("publication_content_hash"),
        "receipt_path": readback.get("receipt_path"),
        "receipt_file_hash": readback.get("receipt_file_hash"),
        "operational_path": readback.get("operational_path"),
        "operational_file_hash": readback.get("operational_file_hash"),
        "consumer": selected_manifest.get("consumer"),
        "consumer_verified": readback.get("consumer_verified") is True,
        "captured_at": captured.isoformat(),
        "decision_at": decision.isoformat(),
        "effective_from": readback.get("effective_from"),
        "row_count": readback.get("row_count"),
        "source_ids": readback.get("source_ids"),
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "historical_backfill_claimed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "durable_archive": {
            "schema_version": PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION,
            "archive_id": archive_id,
            "archive_manifest_path": readback.get("manifest_path"),
            "archive_manifest_file_hash": _file_hash_or_none(
                Path(str(readback.get("manifest_path")))
            ),
            "archive_root": str(Path(str(readback.get("manifest_path"))).parent),
            "archive_readback_verified": True,
            "publication_content_hash": readback.get("publication_content_hash"),
            "row_count": readback.get("row_count"),
            "candidate_only": True,
            "formal_consumer_compatible": False,
        },
        "durable_archive_verified": True,
        "capture_cutoff": cutoff.isoformat(),
        "captured_before_cutoff": True,
        "post_cutoff_refetch_forbidden": True,
        "archive_selection_reason": (
            "selected latest valid immutable archive captured before Taipei 08:30;"
            " no same-day post-cutoff source fetch"
        ),
        "archive_manifest_hash": readback.get("manifest_hash"),
        "archive_manifest_status": selected_manifest.get("status"),
    }


def _archive_pit_candidate(
    *,
    publication_root: Path,
    pit_result: Mapping[str, object],
    archive_cutoff: datetime | None = None,
) -> dict[str, object]:
    """保存已由 machine consumer 驗證的 PIT candidate 完整 byte custody。

    machine operational publisher 仍只接受 TEMP，避免把候選誤當正式來源。
    這裡另外把 publication、receipt、operational 及 publication 參照的兩份
    official raw bytes 以 create-only 方式保存到 durable publication root；
    archive readback 會直接在 archive 內重驗 raw 與 rows，因此不依賴已結束
    的 TEMP process。這個 archive 仍永遠是 candidate-only，不提升 Formal credit。
    """

    cutoff = (
        _aware_datetime(archive_cutoff, "archive_cutoff")
        if archive_cutoff is not None
        else None
    )
    if cutoff is not None and datetime.now(timezone.utc) >= cutoff:
        raise FormalDailyInputProducerError(
            "PIT durable archive must start before Taipei 08:30 cutoff"
        )
    durable_root = _prepare_publication_root(publication_root)
    publication_path = _pit_candidate_source_path(
        pit_result.get("publication_path"),
        "PIT publication",
    )
    receipt_path = _pit_candidate_source_path(
        pit_result.get("receipt_path"),
        "PIT receipt",
    )
    operational_path = _pit_candidate_source_path(
        pit_result.get("operational_path"),
        "PIT operational publication",
    )
    expected_publication_hash = _pit_candidate_hash(
        pit_result.get("publication_file_hash"),
        "publication_file_hash",
    )
    expected_receipt_hash = _pit_candidate_hash(
        pit_result.get("receipt_file_hash"),
        "receipt_file_hash",
    )
    expected_operational_hash = _pit_candidate_hash(
        pit_result.get("operational_file_hash"),
        "operational_file_hash",
    )
    publication_bytes = _pit_candidate_read_bytes(
        publication_path,
        "PIT publication",
        expected_publication_hash,
    )
    receipt_bytes = _pit_candidate_read_bytes(
        receipt_path,
        "PIT receipt",
        expected_receipt_hash,
    )
    operational_bytes = _pit_candidate_read_bytes(
        operational_path,
        "PIT operational publication",
        expected_operational_hash,
    )
    publication_payload = _pit_candidate_json_bytes(
        publication_bytes,
        "PIT publication",
    )
    publication_content_hash = _pit_candidate_hash(
        publication_payload.get("content_sha256"),
        "publication.content_sha256",
    )
    publication_body = dict(publication_payload)
    publication_body.pop("content_sha256", None)
    if _payload_hash(publication_body) != publication_content_hash:
        raise FormalDailyInputProducerError(
            "PIT publication content hash changed before durable archive"
        )
    if publication_content_hash != _pit_candidate_hash(
        pit_result.get("publication_content_hash"),
        "publication_content_hash",
    ):
        raise FormalDailyInputProducerError(
            "PIT publication content hash does not match producer result"
        )

    effective_from = publication_payload.get("effective_from")
    if not isinstance(effective_from, str) or not effective_from:
        raise FormalDailyInputProducerError(
            "PIT publication effective_from is missing for archive"
        )
    captured_at = _aware_datetime(
        publication_payload.get("captured_at"),
        "PIT publication captured_at",
    )
    if effective_from != captured_at.astimezone(TAIPEI).date().isoformat():
        raise FormalDailyInputProducerError(
            "PIT publication effective_from does not match Taipei capture date"
        )

    # Keep the Windows path bounded; the manifest still records and verifies
    # the complete hashes, so a truncated directory key cannot silently merge
    # two different byte sets.
    archive_key = (
        publication_content_hash[7:23]
        + "-"
        + expected_receipt_hash[7:23]
    )
    archive_dir = durable_root / "pit_candidate_archive" / effective_from / archive_key
    file_specs: list[tuple[str, Path, str, str, bytes]] = [
        (
            "publication",
            publication_path,
            "pit-sector-membership-machine.json",
            expected_publication_hash,
            publication_bytes,
        ),
        ("receipt", receipt_path, "receipt.json", expected_receipt_hash, receipt_bytes),
        (
            "operational",
            operational_path,
            "operational.json",
            expected_operational_hash,
            operational_bytes,
        ),
    ]
    raw_inputs = _mapping_sequence(
        publication_payload.get("raw_inputs"),
        "PIT publication raw_inputs",
    )
    seen_relative_paths = {item[2] for item in file_specs}
    for item in raw_inputs:
        relative_value = item.get("path")
        if not isinstance(relative_value, str) or not relative_value.strip():
            raise FormalDailyInputProducerError(
                "PIT publication raw input path is invalid"
            )
        relative = Path(relative_value)
        if relative.is_absolute() or str(relative) in {"", "."}:
            raise FormalDailyInputProducerError(
                "PIT publication raw input path must be relative"
            )
        source = _pit_candidate_child(publication_path.parent, relative)
        expected_hash = _pit_candidate_hash(
            item.get("content_sha256"),
            "PIT raw input content_sha256",
        )
        raw_bytes = _pit_candidate_read_bytes(
            source,
            "PIT raw input",
            expected_hash,
        )
        archive_relative = relative.as_posix()
        if archive_relative in seen_relative_paths:
            raise FormalDailyInputProducerError(
                "PIT archive contains duplicate relative file paths"
            )
        seen_relative_paths.add(archive_relative)
        market = item.get("market")
        role = (
            "raw:" + market
            if isinstance(market, str) and market.strip()
            else "raw"
        )
        file_specs.append((role, source, archive_relative, expected_hash, raw_bytes))

    file_entries: list[dict[str, object]] = []
    for role, source, relative_path, expected_hash, raw_bytes in file_specs:
        target = _pit_candidate_child(archive_dir, Path(relative_path))
        archive_hash = _sha256_bytes(raw_bytes)
        if archive_hash != expected_hash:
            raise FormalDailyInputProducerError(
                f"PIT archive source hash is invalid:{role}"
            )
        _write_immutable_bytes_or_match(target, raw_bytes, role)
        observed_archive_hash = _file_hash_or_none(target)
        if observed_archive_hash != expected_hash:
            raise FormalDailyInputProducerError(
                f"PIT archive file hash is unavailable:{role}"
            )
        file_entries.append(
            {
                "role": role,
                "relative_path": relative_path,
                "source_path": str(source.resolve()),
                "source_file_hash": expected_hash,
                "archive_file_hash": observed_archive_hash,
                "byte_count": len(raw_bytes),
            }
        )

    manifest_path = archive_dir / "archive_manifest.json"
    if manifest_path.is_file():
        readback = _readback_pit_candidate_archive(manifest_path)
        if readback.get("publication_content_hash") != publication_content_hash:
            raise FormalDailyInputProducerError(
                "existing PIT archive manifest content hash does not match candidate"
            )
        if cutoff is not None and _aware_datetime(
            readback.get("archived_at"), "archive.archived_at"
        ) >= cutoff:
            raise FormalDailyInputProducerError(
                "existing PIT durable archive was persisted at or after Taipei 08:30 cutoff"
            )
        return {
            "schema_version": PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION,
            "archive_manifest_path": str(manifest_path.resolve()),
            "archive_manifest_file_hash": _file_hash_or_none(manifest_path),
            "archive_root": str(archive_dir.resolve()),
            "archive_readback_verified": True,
            "archive_id": readback.get("archive_id"),
            "publication_content_hash": publication_content_hash,
            "row_count": readback.get("row_count"),
            "candidate_only": True,
            "formal_consumer_compatible": False,
        }

    archived_at = datetime.now(timezone.utc)
    if cutoff is not None and archived_at >= cutoff:
        raise FormalDailyInputProducerError(
            "PIT durable archive persistence did not complete before Taipei 08:30 cutoff"
        )
    archive_body: dict[str, object] = {
        "schema_version": PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION,
        "status": "archived_candidate",
        "input": "pit_sector_membership",
        "archive_id": (
            "pit-candidate:"
            + publication_content_hash[7:]
            + ":"
            + expected_receipt_hash[7:]
        ),
        "archived_at": archived_at.isoformat(),
        "captured_at": publication_payload.get("captured_at"),
        "decision_at": pit_result.get("decision_at"),
        "effective_from": effective_from,
        "capture_id": publication_payload.get("capture_id"),
        "publication_content_hash": publication_content_hash,
        "row_count": publication_payload.get("row_count"),
        "source_ids": [],
        "producer": pit_result.get("producer"),
        "producer_version": pit_result.get("producer_version"),
        "producer_code_sha256": pit_result.get("producer_code_sha256"),
        "consumer": pit_result.get("consumer"),
        "consumer_verified_at_capture": pit_result.get("consumer_verified") is True,
        "archive_independent_of_temp": True,
        "candidate_only": True,
        "formal_consumer_compatible": False,
        "historical_backfill_claimed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "archive_reason": (
            "exact publication, receipt, operational and official raw bytes were "
            "copied after machine consumer readback; archive readback revalidates "
            "official raw custody and rows without TEMP paths"
        ),
        "files": file_entries,
    }
    # Keep the manifest small and stable: source IDs are already represented by
    # each raw input entry, while the full source registry stays in the exact
    # archived publication bytes.
    archive_body["source_ids"] = sorted(
        str(item.get("source_id"))
        for item in raw_inputs
        if isinstance(item.get("source_id"), str)
    )
    manifest = {**archive_body, "manifest_hash": _payload_hash(archive_body)}
    try:
        _write_immutable_json(manifest_path, manifest)
    except FormalDailyInputProducerError:
        if not manifest_path.is_file():
            raise
        readback = _readback_pit_candidate_archive(manifest_path)
        if readback.get("publication_content_hash") != publication_content_hash:
            raise
    readback = _readback_pit_candidate_archive(manifest_path)
    if cutoff is not None and _aware_datetime(
        readback.get("archived_at"), "archive.archived_at"
    ) >= cutoff:
        raise FormalDailyInputProducerError(
            "PIT durable archive persistence crossed Taipei 08:30 cutoff"
        )
    return {
        "schema_version": PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION,
        "archive_manifest_path": str(manifest_path.resolve()),
        "archive_manifest_file_hash": _file_hash_or_none(manifest_path),
        "archive_root": str(archive_dir.resolve()),
        "archive_readback_verified": readback.get("status")
        == "durable_candidate_readback_verified",
        "archive_id": readback.get("archive_id"),
        "publication_content_hash": publication_content_hash,
        "row_count": readback.get("row_count"),
        "candidate_only": True,
        "formal_consumer_compatible": False,
    }


def _readback_pit_candidate_archive(
    manifest_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """從 durable archive 重新驗證 official raw、rows 與三份 envelope。"""

    manifest_file = manifest_path.expanduser().resolve()
    manifest = _pit_candidate_json_file(manifest_file, "PIT archive manifest")
    expected_manifest_hash = _pit_candidate_hash(
        manifest.get("manifest_hash"),
        "PIT archive manifest_hash",
    )
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_hash", None)
    if _payload_hash(manifest_body) != expected_manifest_hash:
        raise FormalDailyInputProducerError("PIT archive manifest hash mismatch")
    expected_fields = {
        "schema_version",
        "status",
        "input",
        "archive_id",
        "archived_at",
        "captured_at",
        "decision_at",
        "effective_from",
        "capture_id",
        "publication_content_hash",
        "row_count",
        "source_ids",
        "producer",
        "producer_version",
        "producer_code_sha256",
        "consumer",
        "consumer_verified_at_capture",
        "archive_independent_of_temp",
        "candidate_only",
        "formal_consumer_compatible",
        "historical_backfill_claimed",
        "formal_oos_allowed",
        "promotion_eligible",
        "broker_order_allowed",
        "archive_reason",
        "files",
        "manifest_hash",
    }
    if set(manifest) != expected_fields:
        raise FormalDailyInputProducerError("PIT archive manifest fields are invalid")
    for field_name, expected in (
        ("schema_version", PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION),
        ("status", "archived_candidate"),
        ("input", "pit_sector_membership"),
        ("candidate_only", True),
        ("formal_consumer_compatible", False),
        ("historical_backfill_claimed", False),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
        ("consumer_verified_at_capture", True),
        ("archive_independent_of_temp", True),
    ):
        if manifest.get(field_name) is not expected if isinstance(expected, bool) else manifest.get(field_name) != expected:
            raise FormalDailyInputProducerError(
                f"PIT archive manifest {field_name} is invalid"
            )
    archive_root = manifest_file.parent
    files = _mapping_sequence(manifest.get("files"), "PIT archive files")
    file_by_role: dict[str, tuple[Path, Mapping[str, object]]] = {}
    for item in files:
        role = item.get("role")
        relative_value = item.get("relative_path")
        if not isinstance(role, str) or not role.strip():
            raise FormalDailyInputProducerError("PIT archive file role is invalid")
        if role in file_by_role:
            raise FormalDailyInputProducerError("PIT archive file roles are duplicated")
        if not isinstance(relative_value, str) or not relative_value.strip():
            raise FormalDailyInputProducerError("PIT archive relative path is invalid")
        target = _pit_candidate_child(archive_root, Path(relative_value))
        try:
            raw = target.read_bytes()
        except OSError as error:
            raise FormalDailyInputProducerError(
                f"PIT archive file is unreadable:{role}"
            ) from error
        expected_hash = _pit_candidate_hash(
            item.get("archive_file_hash"),
            f"PIT archive {role} archive_file_hash",
        )
        source_hash = _pit_candidate_hash(
            item.get("source_file_hash"),
            f"PIT archive {role} source_file_hash",
        )
        if expected_hash != source_hash or _sha256_bytes(raw) != expected_hash:
            raise FormalDailyInputProducerError(
                f"PIT archive file hash mismatch:{role}"
            )
        if item.get("byte_count") != len(raw):
            raise FormalDailyInputProducerError(
                f"PIT archive file byte count mismatch:{role}"
            )
        file_by_role[role] = (target, item)
    required_roles = {"publication", "receipt", "operational"}
    if not required_roles.issubset(file_by_role):
        raise FormalDailyInputProducerError("PIT archive envelope files are incomplete")
    raw_roles = [role for role in file_by_role if role.startswith("raw:")]
    if len(raw_roles) != 2:
        raise FormalDailyInputProducerError("PIT archive official raw files are incomplete")

    publication_path = file_by_role["publication"][0]
    observed_now = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc),
        "PIT archive readback now",
    )
    validation = validate_machine_pit_publication(
        publication_path,
        now=observed_now,
    )
    if validation.publication_content_hash != manifest.get("publication_content_hash"):
        raise FormalDailyInputProducerError(
            "PIT archive publication content hash mismatch"
        )
    if validation.capture_id != manifest.get("capture_id"):
        raise FormalDailyInputProducerError("PIT archive capture_id mismatch")
    if validation.effective_from != manifest.get("effective_from"):
        raise FormalDailyInputProducerError("PIT archive effective_from mismatch")
    if validation.row_count != manifest.get("row_count"):
        raise FormalDailyInputProducerError("PIT archive row_count mismatch")
    if list(validation.source_ids) != manifest.get("source_ids"):
        raise FormalDailyInputProducerError("PIT archive source_ids mismatch")

    receipt_path = file_by_role["receipt"][0]
    receipt = _pit_candidate_json_file(receipt_path, "PIT archive receipt")
    receipt_content_hash = _pit_candidate_hash(
        receipt.get("content_sha256"),
        "PIT archive receipt content_sha256",
    )
    receipt_body = dict(receipt)
    receipt_body.pop("content_sha256", None)
    if _payload_hash(receipt_body) != receipt_content_hash:
        raise FormalDailyInputProducerError("PIT archive receipt content hash mismatch")
    for key, expected_value in (
        ("publication_file_hash", validation.publication_file_hash),
        ("publication_content_hash", validation.publication_content_hash),
        ("capture_id", validation.capture_id),
        ("captured_at", validation.captured_at),
        ("effective_from", validation.effective_from),
        ("row_count", validation.row_count),
        ("source_ids", list(validation.source_ids)),
    ):
        if receipt.get(key) != expected_value:
            raise FormalDailyInputProducerError(
                f"PIT archive receipt {key} mismatch"
            )
    evaluated = _aware_datetime(receipt.get("evaluated_at"), "PIT archive evaluated_at")
    captured = _aware_datetime(receipt.get("captured_at"), "PIT archive captured_at")
    if captured > evaluated or evaluated > observed_now:
        raise FormalDailyInputProducerError("PIT archive receipt time ordering is invalid")
    for key, expected in (
        ("source_custody_verified", True),
        ("rows_rebuilt_from_raw", True),
        ("candidate_only", True),
        ("formal_consumer_compatible", False),
    ):
        if receipt.get(key) is not expected:
            raise FormalDailyInputProducerError(
                f"PIT archive receipt {key} is invalid"
            )

    operational_path = file_by_role["operational"][0]
    operational = _pit_candidate_json_file(
        operational_path,
        "PIT archive operational publication",
    )
    operational_content_hash = _pit_candidate_hash(
        operational.get("content_sha256"),
        "PIT archive operational content_sha256",
    )
    operational_body = dict(operational)
    operational_body.pop("content_sha256", None)
    if _payload_hash(operational_body) != operational_content_hash:
        raise FormalDailyInputProducerError(
            "PIT archive operational content hash mismatch"
        )
    receipt_file_hash = _file_hash_or_none(receipt_path)
    if receipt_file_hash is None:
        raise FormalDailyInputProducerError(
            "PIT archive receipt file hash is unavailable"
        )
    for key, expected_value in (
        ("receipt_file_hash", receipt_file_hash),
        ("receipt_content_hash", receipt_content_hash),
        ("publication_file_hash", validation.publication_file_hash),
        ("publication_content_hash", validation.publication_content_hash),
        ("capture_id", validation.capture_id),
        ("effective_from", validation.effective_from),
        ("row_count", validation.row_count),
        ("source_ids", list(validation.source_ids)),
    ):
        if operational.get(key) != expected_value:
            raise FormalDailyInputProducerError(
                f"PIT archive operational {key} mismatch"
            )
    operational_decision = _aware_datetime(
        operational.get("decision_at"),
        "PIT archive operational decision_at",
    )
    if operational_decision < evaluated or operational_decision < captured:
        raise FormalDailyInputProducerError(
            "PIT archive operational decision precedes source custody"
        )
    return {
        "status": "durable_candidate_readback_verified",
        "schema_version": PIT_CANDIDATE_ARCHIVE_SCHEMA_VERSION,
        "archive_id": manifest.get("archive_id"),
        "manifest_path": str(manifest_file),
        "manifest_hash": expected_manifest_hash,
        "archived_at": _aware_datetime(
            manifest.get("archived_at"), "PIT archive archived_at"
        ).astimezone(timezone.utc).isoformat(),
        "publication_path": str(publication_path),
        "publication_file_hash": validation.publication_file_hash,
        "publication_content_hash": validation.publication_content_hash,
        "receipt_path": str(receipt_path),
        "receipt_file_hash": _file_hash_or_none(receipt_path),
        "operational_path": str(operational_path),
        "operational_file_hash": _file_hash_or_none(operational_path),
        "capture_id": validation.capture_id,
        "captured_at": validation.captured_at,
        "effective_from": validation.effective_from,
        "row_count": validation.row_count,
        "source_ids": list(validation.source_ids),
        "consumer_verified": True,
        "candidate_only": True,
        "formal_consumer_compatible": False,
    }


def _pit_candidate_source_path(value: object, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise FormalDailyInputProducerError(f"{field_name} path is missing")
    path = Path(value).expanduser().resolve()
    _require_temp_path(path, field_name)
    if not path.is_file():
        raise FormalDailyInputProducerError(f"{field_name} source file is missing")
    return path


def _pit_candidate_hash(value: object, field_name: str) -> str:
    if not _is_sha256(value):
        raise FormalDailyInputProducerError(f"{field_name} must be sha256")
    return str(value)


def _pit_candidate_read_bytes(
    path: Path,
    field_name: str,
    expected_hash: str,
) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise FormalDailyInputProducerError(
            f"{field_name} source cannot be read"
        ) from error
    if _sha256_bytes(raw) != expected_hash:
        raise FormalDailyInputProducerError(f"{field_name} source hash mismatch")
    return raw


def _pit_candidate_json_bytes(raw: bytes, field_name: str) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FormalDailyInputProducerError(f"{field_name} JSON is invalid") from error
    if not isinstance(value, dict):
        raise FormalDailyInputProducerError(f"{field_name} JSON must be an object")
    if raw != (_canonical_json(value) + "\n").encode("utf-8"):
        raise FormalDailyInputProducerError(f"{field_name} JSON is not canonical")
    return {str(key): item for key, item in value.items()}


def _pit_candidate_json_file(path: Path, field_name: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise FormalDailyInputProducerError(f"{field_name} is unreadable") from error
    return _pit_candidate_json_bytes(raw, field_name)


def _pit_candidate_child(root: Path, relative: Path) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise FormalDailyInputProducerError(
            "PIT archive custody path escapes its root"
        ) from error
    if candidate == root.resolve():
        raise FormalDailyInputProducerError("PIT archive custody path must name a file")
    return candidate


def _write_immutable_bytes_or_match(path: Path, raw: bytes, role: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise FormalDailyInputProducerError(
                f"PIT archive existing file cannot be read:{role}"
            ) from error
        if existing != raw:
            raise FormalDailyInputProducerError(
                f"PIT archive existing file differs:{role}"
            )
        return
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        _write_immutable_bytes_or_match(path, raw, role)
    except OSError as error:
        raise FormalDailyInputProducerError(
            f"PIT archive file is not writable:{role}"
        ) from error


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _paper_source_projections(
    paths: DailyFormalInputPaths,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    """檢查真正 Paper state／fill source 的 schema，不建立任何資料庫。"""

    definitions = (
        (
            "paper_snapshot",
            paths.paper_snapshot_db_path,
            "paper_portfolio_snapshots",
            frozenset(
                {
                    "snapshot_id",
                    "portfolio_id",
                    "decision_date",
                    "source_result_id",
                    "cash",
                    "total_value",
                }
            ),
            "formal_ledger_paper_snapshot_source_missing",
        ),
        (
            "paper_trade_ledger",
            paths.paper_trade_ledger_db_path,
            "paper_trade_ledger",
            frozenset(
                {
                    "schema_version",
                    "fill_id",
                    "order_id",
                    "portfolio_id",
                    "event_date",
                    "stock_code",
                    "side",
                    "requested_quantity",
                    "filled_quantity",
                    "reference_price",
                    "fill_price",
                    "commission",
                    "tax",
                    "slippage_cost",
                    "turnover_bp",
                    "execution_gap_bp",
                    "status",
                    "source_event_id",
                    "override_reason",
                    "source_type",
                    "research_only",
                    "broker_order_allowed",
                    "auto_rebalance_allowed",
                }
            ),
            "formal_ledger_paper_fill_source_missing",
        ),
    )
    projections: dict[str, dict[str, object]] = {}
    blockers: list[str] = []
    for name, path, table, required, missing_reason in definitions:
        if path is None:
            projections[name] = {
                "state": "missing",
                "mode": "ro/query_only",
                "file_hash": None,
                "file_hash_semantics": "main_db_bytes_observation_only",
                "row_count": 0,
                "reason": missing_reason,
            }
            blockers.append(missing_reason)
            continue
        resolved = path.expanduser().resolve()
        projection: dict[str, object] = {
            "state": "missing",
            "mode": "ro/query_only",
            "path": str(resolved),
            "file_hash": _file_hash_or_none(resolved),
            "file_hash_semantics": "main_db_bytes_observation_only",
            "row_count": 0,
        }
        if not resolved.is_file():
            projection["reason"] = missing_reason.replace(
                "_source_missing", "_source_file_missing"
            )
            projections[name] = projection
            blockers.append(str(projection["reason"]))
            continue
        connection: sqlite3.Connection | None = None
        try:
            connection = _open_read_only_sqlite(resolved)
            columns = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            if not required.issubset(columns):
                projection["reason"] = (
                    f"{name}_source_schema_missing_columns"
                )
                projections[name] = projection
                blockers.append(str(projection["reason"]))
                continue
            row_count = int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            projection["row_count"] = row_count
            if row_count <= 0:
                projection["state"] = "empty"
                projection["reason"] = f"{name}_source_empty"
                blockers.append(str(projection["reason"]))
            else:
                projection["state"] = "ready"
                projection["reason"] = "paper_source_schema_and_rows_available"
        except Exception as error:  # noqa: BLE001 - preflight is fail closed
            projection["reason"] = (
                f"{name}_source_read_failed:{_safe_error(error)}"
            )
            blockers.append(str(projection["reason"]))
        finally:
            if connection is not None:
                connection.close()
        projections[name] = projection
    return projections, blockers


def _produce_formal_ledger_candidate(
    *,
    paths: DailyFormalInputPaths,
    output_root: Path,
    observed: datetime,
    calendar: OfficialTradingCalendar | None,
    publication_root: Path | None = None,
) -> dict[str, object]:
    """由已存在的 Paper snapshots + 真實 fills 建立一份 TEMP candidate。

    這條路徑不接受 snapshots 反推成交，也不接受 simulated／research
    ledger。每個 snapshot 邊界都必須有官方交易日證據，quantity 與 Decimal
    cash 必須和 append-only Paper fill rows 完整對帳；任一缺件直接拒絕。
    """

    if paths.paper_snapshot_db_path is None:
        raise FormalDailyInputProducerError(
            "paper snapshot source is required for formal ledger candidate"
        )
    if paths.paper_trade_ledger_db_path is None:
        raise FormalDailyInputProducerError(
            "paper fill source is required for formal ledger candidate"
        )
    clock = _load_clock_from_preflight(paths.clock_manifest, observed)
    if clock is None:
        raise FormalDailyInputProducerError(
            "formal ledger candidate requires a validated Rule clock policy"
        )
    if publication_root is not None and (
        not paths.paper_snapshot_db_path.expanduser().resolve().is_file()
        or not paths.paper_trade_ledger_db_path.expanduser().resolve().is_file()
    ):
        existing_run = _find_ledger_publication_for_missing_sources(
            publication_root=publication_root,
            snapshot_source_path=paths.paper_snapshot_db_path,
            fill_source_path=paths.paper_trade_ledger_db_path,
            observed=observed,
        )
        if existing_run is not None:
            return _load_ledger_publication_retry(
                existing_run,
                observed=observed,
            )
    source_snapshots = _read_paper_snapshots(paths.paper_snapshot_db_path)
    source_fills = _read_paper_fills(paths.paper_trade_ledger_db_path)
    if len(source_snapshots) < 2:
        raise FormalDailyInputProducerError(
            "paper snapshots require at least two causal boundaries"
        )
    observed_taipei = observed.astimezone(TAIPEI)
    preopen_boundary = time(8, 30)
    for item in source_snapshots:
        snapshot_day = _record_date(item, "decision_date", "paper snapshot")
        if snapshot_day > observed_taipei.date():
            raise FormalDailyInputProducerError(
                "paper snapshots contain future decision dates"
            )
        if (
            snapshot_day == observed_taipei.date()
            and observed_taipei.timetz().replace(tzinfo=None) < preopen_boundary
        ):
            raise FormalDailyInputProducerError(
                "current paper preopen snapshot is not yet available"
            )
    if any(
        _record_date(item, "event_date", "paper fill") >= observed_taipei.date()
        for item in source_fills
    ):
        raise FormalDailyInputProducerError(
            "paper fills contain current or future event dates"
        )
    activation_day = clock.activation_trading_day
    # The current day's preopen boundary may already exist when this producer
    # runs, but the date-only formal loader can only consume transitions whose
    # decision date is strictly before ``observed``.  Keep that boundary in
    # source custody while excluding it from the published transition set;
    # the next natural run can then validate the preceding day's transition.
    snapshots = [
        item
        for item in source_snapshots
        if activation_day
        <= _record_date(item, "decision_date", "paper snapshot")
        < observed_taipei.date()
    ]
    fills = [
        item
        for item in source_fills
        if _record_date(item, "event_date", "paper fill") >= activation_day
    ]
    if len(snapshots) < 2:
        raise FormalDailyInputProducerError(
            "paper snapshots do not contain two post-activation boundaries"
        )
    first_date = _record_date(snapshots[0], "decision_date", "paper snapshot")
    last_date = _record_date(snapshots[-1], "decision_date", "paper snapshot")
    if any(
        _record_date(item, "event_date", "paper fill") < first_date
        or _record_date(item, "event_date", "paper fill") >= last_date
        for item in fills
    ):
        raise FormalDailyInputProducerError(
            "paper fills do not fit the [start, end) snapshot intervals"
        )
    service = calendar or OfficialTradingCalendar(db_path=paths.market_db)
    _validate_snapshot_calendar_adjacency(snapshots, service)
    _validate_paper_fill_calendar_days(fills, service)

    from data_module.formal_portfolio_ledger import (  # noqa: PLC0415
        FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        _ZERO_SHA256,
    )
    from ml_module.allocation_contracts import (  # noqa: PLC0415
        AllocationWeightContract,
        CausalPortfolioState,
    )

    policy_hash = clock.payload.get("policy_hash")
    if not _is_sha256(policy_hash):
        raise FormalDailyInputProducerError(
            "formal ledger candidate Rule policy hash is invalid"
        )
    source_snapshot_hash = _paper_rows_content_hash(
        source_snapshots,
        schema_version="paper-snapshot-source-custody.v1",
    )
    source_fill_hash = _paper_rows_content_hash(
        source_fills,
        schema_version="paper-fill-source-custody.v1",
    )

    transition_rows: list[dict[str, object]] = []
    previous_chain_hash = _ZERO_SHA256
    non_cash_state_day_count = 0
    for start, end in zip(snapshots, snapshots[1:]):
        start_date = _record_date(start, "decision_date", "paper snapshot")
        end_date = _record_date(end, "decision_date", "paper snapshot")
        interval_fills = tuple(
            item
            for item in fills
            if start_date
            <= _record_date(item, "event_date", "paper fill")
            < end_date
        )
        _validate_paper_boundary_reconciliation(
            start=start,
            end=end,
            fills=interval_fills,
        )
        input_turnover = _turnover_before_date(fills, start_date)
        output_turnover = _turnover_before_date(fills, end_date)
        input_weights = _ml_weights_from_snapshot(start)
        output_weights = _ml_weights_from_snapshot(end)
        input_state = CausalPortfolioState.create(
            as_of_date=start_date.isoformat(),
            weights=input_weights,
            weekly_turnover_used_bp=input_turnover,
        )
        output_state = CausalPortfolioState.create(
            as_of_date=end_date.isoformat(),
            weights=output_weights,
            weekly_turnover_used_bp=output_turnover,
        )
        desired_weights = output_weights
        buy_turnover = sum(
            _record_int(item, "turnover_bp", "paper fill")
            for item in interval_fills
            if _record_text(item, "side", "paper fill") == "buy"
        )
        sell_turnover = sum(
            _record_int(item, "turnover_bp", "paper fill")
            for item in interval_fills
            if _record_text(item, "side", "paper fill") == "sell"
        )
        canonical_turnover = buy_turnover + sell_turnover
        cost = sum(
            (
                _record_decimal(item, "total_cost", "paper fill")
                for item in interval_fills
            ),
            Decimal("0.00"),
        )
        estimated_cost = int(
            (
                cost
                * Decimal(10_000)
                / _record_decimal(start, "total_value_decimal", "paper snapshot")
            ).to_integral_value(
                rounding=ROUND_HALF_EVEN
            )
        )
        current_quantities = {
            _record_text(item, "stock_code", "paper position"): _record_int(
                item, "quantity", "paper position"
            )
            for item in _record_sequence(start, "positions", "paper snapshot")
        }
        next_quantities = {
            _record_text(item, "stock_code", "paper position"): _record_int(
                item, "quantity", "paper position"
            )
            for item in _record_sequence(end, "positions", "paper snapshot")
        }
        symbols = sorted(set(current_quantities) | set(next_quantities))
        add_count = sum(
            next_quantities.get(symbol, 0) > current_quantities.get(symbol, 0)
            for symbol in symbols
        )
        reduce_count = sum(
            next_quantities.get(symbol, 0) < current_quantities.get(symbol, 0)
            for symbol in symbols
        )
        feature_input_hash = _payload_hash(
            {
                "schema_version": "paper-fill-bound-formal-ledger-input.v1",
                "start_snapshot_id": _record_text(
                    start, "snapshot_id", "paper snapshot"
                ),
                "start_snapshot_hash": _record_text(
                    start, "content_hash", "paper snapshot"
                ),
                "end_snapshot_id": _record_text(end, "snapshot_id", "paper snapshot"),
                "end_snapshot_hash": _record_text(
                    end, "content_hash", "paper snapshot"
                ),
                "paper_snapshot_source_content_hash": source_snapshot_hash,
                "paper_fill_source_content_hash": source_fill_hash,
                "fill_ids": [
                    _record_text(item, "fill_id", "paper fill")
                    for item in interval_fills
                ],
                "fill_content_hashes": [
                    _record_text(item, "content_hash", "paper fill")
                    for item in interval_fills
                ],
            }
        )
        transition_payload = {
            "schema_version": FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
            "decision_date": end_date.isoformat(),
            "input_state_hash": input_state.state_hash,
            "feature_input_hash": feature_input_hash,
            "desired_weights": _ml_weight_payload(desired_weights),
            "output_state_hash": output_state.state_hash,
            "buy_turnover_bp": buy_turnover,
            "sell_turnover_bp": sell_turnover,
            "canonical_turnover_bp": canonical_turnover,
            "estimated_cost_bp": estimated_cost,
            "add_count": add_count,
            "reduce_count": reduce_count,
            "future_teacher_target_used": False,
            "same_day_advice_used": False,
        }
        transition_hash = _payload_hash(transition_payload)
        chain_hash = _payload_hash(
            {
                "previous_chain_hash": previous_chain_hash,
                "transition_hash": transition_hash,
            }
        )
        transition_rows.append(
            {
                "decision_date": end_date.isoformat(),
                "input_state_json": _canonical_json(_ml_state_payload(input_state)),
                "desired_weights_json": _canonical_json(
                    _ml_weight_payload(desired_weights)
                ),
                "output_state_json": _canonical_json(
                    _ml_state_payload(output_state)
                ),
                "feature_input_hash": feature_input_hash,
                "buy_turnover_bp": buy_turnover,
                "sell_turnover_bp": sell_turnover,
                "canonical_turnover_bp": canonical_turnover,
                "estimated_cost_bp": estimated_cost,
                "add_count": add_count,
                "reduce_count": reduce_count,
                "transition_hash": transition_hash,
                "chain_hash": chain_hash,
            }
        )
        non_cash_state_day_count += int(input_weights.invested_bp > 0)
        previous_chain_hash = chain_hash

    if non_cash_state_day_count <= 0:
        raise FormalDailyInputProducerError(
            "paper fill bound ledger has no non-cash input state"
        )
    publication_run_dir: Path | None = None
    if publication_root is None:
        candidate_dir = output_root / "formal_ledger_candidate"
        candidate_dir.mkdir(parents=True, exist_ok=False)
    else:
        durable_root = _prepare_publication_root(publication_root)
        if not transition_rows:
            raise FormalDailyInputProducerError(
                "formal ledger publication has no transition rows"
            )
        latest_decision_date = str(transition_rows[-1]["decision_date"])
        run_id = (
            f"{latest_decision_date}-"
            f"{source_snapshot_hash[7:19]}-"
            f"{source_fill_hash[7:19]}"
        )
        publication_run_dir = durable_root / "causal_ledger" / run_id
        if publication_run_dir.exists():
            return _load_ledger_publication_retry(
                publication_run_dir,
                observed=observed,
                snapshot_source_hash=source_snapshot_hash,
                fill_source_hash=source_fill_hash,
            )
        try:
            publication_run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise FormalDailyInputProducerError(
                "causal ledger publication run appeared during capture"
            ) from error
        candidate_dir = publication_run_dir
    source_custody: dict[str, object] = {}
    if publication_run_dir is not None:
        source_custody = _write_paper_source_custody(
            run_dir=publication_run_dir,
            snapshots=source_snapshots,
            fills=source_fills,
            snapshot_source_hash=source_snapshot_hash,
            fill_source_hash=source_fill_hash,
            snapshot_source_path=paths.paper_snapshot_db_path,
            fill_source_path=paths.paper_trade_ledger_db_path,
        )
    sqlite_path = candidate_dir / "portfolio_ledger.sqlite"
    _write_formal_ledger_sqlite(sqlite_path, transition_rows)
    sqlite_file_hash = _file_hash_or_none(sqlite_path)
    if sqlite_file_hash is None:
        raise FormalDailyInputProducerError(
            "formal ledger candidate sqlite hash is unavailable"
        )
    decision_dates = [str(item["decision_date"]) for item in transition_rows]
    identity = {
        "schema_version": FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        "transition_schema_version": FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        "sqlite_file_hash": sqlite_file_hash,
        "policy_hash": policy_hash,
        "decision_dates": decision_dates,
        "decision_date_count": len(decision_dates),
        "non_cash_state_day_count": non_cash_state_day_count,
        "transition_chain_hash": previous_chain_hash,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
    }
    manifest_body: dict[str, object] = {
        "schema_version": FORMAL_PORTFOLIO_LEDGER_SCHEMA_VERSION,
        "status": "complete",
        "formal_source_only": True,
        "research_only": False,
        "formal_consumer_compatible": True,
        "promotion_eligible": False,
        "transition_schema_version": FORMAL_PORTFOLIO_LEDGER_TRANSITION_SCHEMA_VERSION,
        "sqlite_path": sqlite_path.name,
        "sqlite_file_hash": sqlite_file_hash,
        "policy_hash": policy_hash,
        "decision_dates": decision_dates,
        "decision_date_count": len(decision_dates),
        "non_cash_state_day_count": non_cash_state_day_count,
        "transition_chain_hash": previous_chain_hash,
        "future_teacher_target_used": False,
        "same_day_advice_used": False,
        "ledger_manifest_hash": _payload_hash(identity),
    }
    manifest_body["manifest_hash"] = _payload_hash(manifest_body)
    manifest_path = candidate_dir / "manifest.json"
    _write_immutable_json(manifest_path, manifest_body)
    formal_replay = _readback_formal_ledger(manifest_path, observed.isoformat())
    result: dict[str, object] = {
        "status": "machine_verified_candidate",
        "source_lane": "paper_fill_bound_causal_transition",
        "producer": "data_module.formal_daily_input_producer._produce_formal_ledger_candidate",
        "producer_version": "paper-fill-bound-formal-ledger.v2",
        "snapshot_source_path": str(paths.paper_snapshot_db_path.expanduser().resolve()),
        "snapshot_source_content_hash": source_snapshot_hash,
        "snapshot_source_hash": source_snapshot_hash,
        "snapshot_source_hash_semantics": "validated_rows_in_sqlite_read_transaction",
        "snapshot_rows_read": len(source_snapshots),
        "snapshot_rows_used": len(snapshots),
        "pre_activation_snapshot_rows_excluded": (
            len(source_snapshots) - len(snapshots)
        ),
        "fill_source_path": str(paths.paper_trade_ledger_db_path.expanduser().resolve()),
        "fill_source_content_hash": source_fill_hash,
        "fill_source_hash": source_fill_hash,
        "fill_source_hash_semantics": "validated_rows_in_sqlite_read_transaction",
        "fill_rows_read": len(source_fills),
        "fill_rows_used": len(fills),
        "pre_activation_fill_rows_excluded": len(source_fills) - len(fills),
        "activation_filter": "post_activation_sources_only",
        "source_read_consistency": "sqlite_read_transaction",
        "manifest_path": str(manifest_path),
        "manifest_file_hash": _file_hash_or_none(manifest_path),
        "manifest_hash": formal_replay["manifest_hash"],
        "sqlite_path": str(sqlite_path),
        "sqlite_file_hash": sqlite_file_hash,
        "transition_chain_hash": formal_replay["transition_chain_hash"],
        "decision_dates": list(
            _text_list(formal_replay["decision_dates"])
        ),
        "non_cash_state_day_count": formal_replay["non_cash_state_day_count"],
        "consumer": "data_module.formal_portfolio_ledger.load_formal_portfolio_state_ledger",
        "consumer_verified": True,
        "formal_source_only": True,
        "formal_consumer_compatible": True,
        "formal_ready": False,
        "candidate_only": True,
        "historical_backfill_claimed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        **source_custody,
    }
    if publication_run_dir is None:
        receipt_path, receipt_hash, receipt_file_hash = _write_input_receipt(
            output_path=candidate_dir / "receipt.json",
            input_name="causal_non_cash_portfolio_ledger",
            result=result,
            observed=observed,
        )
        result.update(
            {
                "receipt_path": str(receipt_path),
                "receipt_hash": receipt_hash,
                "receipt_file_hash": receipt_file_hash,
            }
        )
    else:
        publication_receipt_path = publication_run_dir / "receipt.json"
        publication_result = dict(result)
        publication_result.update(
            {
                "publication_run_id": publication_run_dir.name,
                "publication_receipt_path": str(publication_receipt_path.resolve()),
                "publication_natural_date": observed.astimezone(TAIPEI)
                .date()
                .isoformat(),
                "publication_status": "published",
            }
        )
        _write_publication_context(
            run_dir=publication_run_dir,
            input_name="causal_non_cash_portfolio_ledger",
            result=publication_result,
            observed=observed,
        )
        (
            publication_receipt_path,
            publication_receipt_hash,
            publication_receipt_file_hash,
        ) = _write_input_receipt(
            output_path=publication_receipt_path,
            input_name="causal_non_cash_portfolio_ledger",
            result=publication_result,
            observed=observed,
        )
        result.update(
            {
                "publication_run_id": publication_run_dir.name,
                "publication_receipt_path": str(publication_receipt_path),
                "publication_receipt_hash": publication_receipt_hash,
                "publication_receipt_file_hash": publication_receipt_file_hash,
                "publication_status": "published",
                "publication_natural_date": observed.astimezone(TAIPEI)
                .date()
                .isoformat(),
            }
        )
    return result


def _open_read_only_sqlite(path: Path) -> sqlite3.Connection:
    """以 SQLite URI 唯讀開啟，避免任何 source schema side effect。"""

    connection = sqlite3.connect(
        f"file:{path.expanduser().resolve().as_posix()}?mode=ro",
        uri=True,
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA query_only").fetchone() != (1,):
            raise FormalDailyInputProducerError(
                "source sqlite query_only could not be enabled"
            )
    except Exception:
        connection.close()
        raise
    return connection


def _read_paper_snapshots(path: Path) -> list[dict[str, object]]:
    from decimal import Decimal  # noqa: PLC0415 - local source boundary

    connection = _open_read_only_sqlite(path)
    connection.row_factory = sqlite3.Row
    try:
        # schema 檢查與所有列讀取固定在同一個 SQLite snapshot。main 檔案的
        # 路徑級 hash 不涵蓋並行更新的 WAL，因此下方已驗證的列內容才是
        # candidate 使用的 custody identity。
        connection.execute("BEGIN")
        snapshot_columns = {
            str(row[1])
            for row in connection.execute(
                'PRAGMA table_info("paper_portfolio_snapshots")'
            )
        }
        position_columns = {
            str(row[1])
            for row in connection.execute(
                'PRAGMA table_info("paper_portfolio_positions")'
            )
        }
        required_snapshots = {
            "snapshot_id",
            "portfolio_id",
            "decision_date",
            "source_result_id",
            "cash",
            "total_value",
        }
        required_positions = {
            "snapshot_id",
            "stock_code",
            "quantity",
            "mark_price",
            "market_value",
            "weight_bp",
        }
        if not required_snapshots.issubset(snapshot_columns):
            raise FormalDailyInputProducerError(
                "paper snapshot schema is missing required columns"
            )
        if not required_positions.issubset(position_columns):
            raise FormalDailyInputProducerError(
                "paper snapshot position schema is missing required columns"
            )
        rows = connection.execute(
            """
            SELECT snapshot_id, portfolio_id, decision_date, source_result_id,
                   cash, total_value
            FROM paper_portfolio_snapshots
            ORDER BY decision_date, snapshot_id
            """
        ).fetchall()
        result: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        portfolio_ids: set[str] = set()
        seen_dates: set[date] = set()
        for row in rows:
            snapshot_id = _required_nonempty_text(
                row["snapshot_id"], "paper snapshot_id"
            )
            if snapshot_id in seen_ids:
                raise FormalDailyInputProducerError(
                    "paper snapshots contain duplicate snapshot_id"
                )
            seen_ids.add(snapshot_id)
            portfolio_id = _required_nonempty_text(
                row["portfolio_id"], "paper portfolio_id"
            )
            portfolio_ids.add(portfolio_id)
            decision_text = _canonical_date_text(
                row["decision_date"], "paper snapshot decision_date"
            )
            decision_day = date.fromisoformat(decision_text)
            if decision_day in seen_dates:
                raise FormalDailyInputProducerError(
                    "paper snapshots require one boundary per decision date"
                )
            seen_dates.add(decision_day)
            cash = _finite_decimal(row["cash"], "paper snapshot cash")
            total_value = _finite_decimal(
                row["total_value"], "paper snapshot total_value"
            )
            if cash < 0 or total_value <= 0:
                raise FormalDailyInputProducerError(
                    "paper snapshot cash/total_value is outside its valid domain"
                )
            position_rows = connection.execute(
                """
                SELECT stock_code, quantity, mark_price, market_value, weight_bp
                FROM paper_portfolio_positions
                WHERE snapshot_id = ?
                ORDER BY stock_code
                """,
                (snapshot_id,),
            ).fetchall()
            positions: list[dict[str, object]] = []
            position_codes: set[str] = set()
            position_total = Decimal("0.00")
            for position in position_rows:
                stock_code = _required_nonempty_text(
                    position["stock_code"], "paper position stock_code"
                )
                if stock_code in position_codes:
                    raise FormalDailyInputProducerError(
                        "paper snapshot contains duplicate stock_code"
                    )
                position_codes.add(stock_code)
                quantity = _required_nonnegative_int(
                    position["quantity"], "paper position quantity"
                )
                mark_price = _finite_decimal(
                    position["mark_price"], "paper position mark_price"
                )
                market_value = _finite_decimal(
                    position["market_value"], "paper position market_value"
                )
                stored_weight = _required_nonnegative_int(
                    position["weight_bp"], "paper position weight_bp"
                )
                if stored_weight > 10_000:
                    raise FormalDailyInputProducerError(
                        "paper position weight_bp exceeds 10000"
                    )
                expected_value = (mark_price * quantity).quantize(Decimal("0.01"))
                if mark_price < 0 or market_value < 0 or market_value != expected_value:
                    raise FormalDailyInputProducerError(
                        "paper position market value does not match Decimal mark"
                    )
                if quantity > 0 and mark_price <= 0:
                    raise FormalDailyInputProducerError(
                        "paper position with quantity requires positive mark price"
                    )
                if quantity == 0 and market_value != Decimal("0.00"):
                    raise FormalDailyInputProducerError(
                        "zero-quantity paper position has non-zero market value"
                    )
                position_total += market_value
                positions.append(
                    {
                        "stock_code": stock_code,
                        "quantity": quantity,
                        "mark_price": str(mark_price),
                        "market_value": str(market_value),
                        "stored_weight_bp": stored_weight,
                    }
                )
            if (cash + position_total).quantize(Decimal("0.01")) != total_value:
                raise FormalDailyInputProducerError(
                    "paper snapshot cash plus positions does not equal total_value"
                )
            payload = {
                "schema_version": "paper-snapshot-boundary.v1",
                "snapshot_id": snapshot_id,
                "portfolio_id": portfolio_id,
                "decision_date": decision_text,
                "source_result_id": _required_nonempty_text(
                    row["source_result_id"], "paper snapshot source_result_id"
                ),
                "cash": str(cash),
                "total_value": str(total_value),
                "positions": positions,
            }
            result.append(
                {
                    **payload,
                    "decision_date": decision_day,
                    "cash_decimal": cash,
                    "total_value_decimal": total_value,
                    "content_hash": _payload_hash(payload),
                }
            )
        if len(portfolio_ids) != 1:
            raise FormalDailyInputProducerError(
                "paper snapshot source must contain exactly one portfolio"
            )
        if len(result) < 2:
            raise FormalDailyInputProducerError(
                "paper snapshot source requires at least two rows"
            )
        return result
    finally:
        connection.close()


def _read_paper_fills(path: Path) -> list[dict[str, object]]:
    from app_module.paper_trade_ledger import (  # noqa: PLC0415
        PAPER_TRADE_LEDGER_SCHEMA_VERSION,
        PaperTradeFill,
    )

    connection = _open_read_only_sqlite(path)
    connection.row_factory = sqlite3.Row
    try:
        # 同 _read_paper_snapshots：source identity 由此一致 read transaction
        # 的列計算，絕不使用無關的 main-db bytes hash。
        connection.execute("BEGIN")
        columns = {
            str(row[1])
            for row in connection.execute(
                'PRAGMA table_info("paper_trade_ledger")'
            )
        }
        required = {
            "schema_version",
            "fill_id",
            "order_id",
            "portfolio_id",
            "event_date",
            "stock_code",
            "side",
            "requested_quantity",
            "filled_quantity",
            "reference_price",
            "fill_price",
            "commission",
            "tax",
            "slippage_cost",
            "turnover_bp",
            "execution_gap_bp",
            "status",
            "source_event_id",
            "override_reason",
            "source_type",
            "research_only",
            "broker_order_allowed",
            "auto_rebalance_allowed",
        }
        if not required.issubset(columns):
            raise FormalDailyInputProducerError(
                "paper trade ledger schema is missing required columns"
            )
        rows = connection.execute(
            """
            SELECT schema_version, fill_id, order_id, portfolio_id, event_date,
                   stock_code, side, requested_quantity, filled_quantity,
                   reference_price, fill_price, commission, tax, slippage_cost,
                   turnover_bp, execution_gap_bp, status, source_event_id,
                   override_reason, source_type, research_only,
                   broker_order_allowed, auto_rebalance_allowed
            FROM paper_trade_ledger
            ORDER BY event_date, fill_id
            """
        ).fetchall()
        result: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        seen_events: set[str] = set()
        portfolio_ids: set[str] = set()
        for row in rows:
            if row["schema_version"] != PAPER_TRADE_LEDGER_SCHEMA_VERSION:
                raise FormalDailyInputProducerError(
                    "paper trade ledger schema_version is not the governed version"
                )
            fill_id = _required_nonempty_text(row["fill_id"], "paper fill_id")
            if fill_id in seen_ids:
                raise FormalDailyInputProducerError(
                    "paper trade ledger contains duplicate fill_id"
                )
            seen_ids.add(fill_id)
            source_event_id = _required_nonempty_text(
                row["source_event_id"], "paper source_event_id"
            )
            if source_event_id in seen_events:
                raise FormalDailyInputProducerError(
                    "paper trade ledger contains duplicate source_event_id"
                )
            seen_events.add(source_event_id)
            portfolio_id = _required_nonempty_text(
                row["portfolio_id"], "paper fill portfolio_id"
            )
            portfolio_ids.add(portfolio_id)
            event_date = _canonical_date_text(row["event_date"], "paper fill event_date")
            turnover = _required_nonnegative_int(
                row["turnover_bp"], "paper fill turnover_bp"
            )
            execution_gap = _required_integer(row["execution_gap_bp"], "paper fill execution_gap_bp")
            research_only = _strict_sqlite_bool(
                row["research_only"], "paper fill research_only"
            )
            broker_allowed = _strict_sqlite_bool(
                row["broker_order_allowed"], "paper fill broker_order_allowed"
            )
            rebalance_allowed = _strict_sqlite_bool(
                row["auto_rebalance_allowed"], "paper fill auto_rebalance_allowed"
            )
            if not research_only or broker_allowed or rebalance_allowed:
                raise FormalDailyInputProducerError(
                    "paper fill safety flags are not research-only"
                )
            try:
                fill = PaperTradeFill(
                    fill_id=fill_id,
                    order_id=_required_nonempty_text(row["order_id"], "paper fill order_id"),
                    portfolio_id=portfolio_id,
                    event_date=event_date,
                    stock_code=_required_nonempty_text(
                        row["stock_code"], "paper fill stock_code"
                    ),
                    side=str(row["side"]),
                    requested_quantity=_required_nonnegative_int(
                        row["requested_quantity"], "paper fill requested_quantity"
                    ),
                    filled_quantity=_required_nonnegative_int(
                        row["filled_quantity"], "paper fill filled_quantity"
                    ),
                    reference_price=_finite_decimal(
                        row["reference_price"], "paper fill reference_price"
                    ),
                    fill_price=(
                        None
                        if row["fill_price"] is None
                        else _finite_decimal(row["fill_price"], "paper fill fill_price")
                    ),
                    commission=_finite_decimal(
                        row["commission"], "paper fill commission"
                    ),
                    tax=_finite_decimal(row["tax"], "paper fill tax"),
                    slippage_cost=_finite_decimal(
                        row["slippage_cost"], "paper fill slippage_cost"
                    ),
                    turnover_bp=turnover,
                    execution_gap_bp=execution_gap,
                    status=str(row["status"]),
                    source_event_id=source_event_id,
                    override_reason=(
                        None
                        if row["override_reason"] is None
                        else str(row["override_reason"])
                    ),
                    source_type=_required_nonempty_text(
                        row["source_type"], "paper fill source_type"
                    ),
                    research_only=research_only,
                    broker_order_allowed=broker_allowed,
                    auto_rebalance_allowed=rebalance_allowed,
                )
            except (TypeError, ValueError, InvalidOperation) as error:
                raise FormalDailyInputProducerError(
                    f"paper fill row is invalid: {_safe_error(error)}"
                ) from error
            payload = fill.to_dict()
            result.append(
                {
                    "fill_id": fill.fill_id,
                    "event_date": date.fromisoformat(event_date),
                    "stock_code": fill.stock_code,
                    "side": fill.side,
                    "filled_quantity": fill.filled_quantity,
                    "turnover_bp": turnover,
                    "commission": fill.commission,
                    "tax": fill.tax,
                    "total_cost": fill.total_cost,
                    "gross_amount": fill.gross_amount,
                    "content_hash": _payload_hash(payload),
                    "fill": fill,
                }
            )
        if len(portfolio_ids) != 1:
            raise FormalDailyInputProducerError(
                "paper fill source must contain exactly one portfolio"
            )
        if not result:
            raise FormalDailyInputProducerError("paper fill source is empty")
        return result
    finally:
        connection.close()


def _validate_snapshot_calendar_adjacency(
    snapshots: Sequence[Mapping[str, object]],
    calendar: OfficialTradingCalendar,
) -> None:
    """證明每個 output boundary 的 input 是前一個官方交易日。"""

    get_range = getattr(calendar, "get_trading_days_in_range", None)
    if not callable(get_range):
        raise FormalDailyInputProducerError(
            "official trading calendar range evidence is unavailable"
        )
    for start, end in zip(snapshots, snapshots[1:]):
        start_day = _required_date_object(start.get("decision_date"), "snapshot start date")
        end_day = _required_date_object(end.get("decision_date"), "snapshot end date")
        if end_day <= start_day:
            raise FormalDailyInputProducerError(
                "paper snapshot decision dates are not increasing"
            )
        try:
            rows = get_range(start_day, end_day, allow_online_probe=True)
        except Exception as error:  # noqa: BLE001
            raise FormalDailyInputProducerError(
                f"official calendar range evidence failed:{_safe_error(error)}"
            ) from error
        open_dates: list[str] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise FormalDailyInputProducerError(
                    "official calendar range row is invalid"
                )
            if row.get("is_trading_day") is None:
                raise FormalDailyInputProducerError(
                    "official calendar range contains unknown trading day"
                )
            if row.get("is_trading_day") is True:
                open_dates.append(
                    _canonical_date_text(row.get("date_str"), "calendar date")
                )
        if tuple(open_dates[-2:]) != (start_day.isoformat(), end_day.isoformat()):
            raise FormalDailyInputProducerError(
                "paper snapshots skip an official trading-day boundary"
            )


def _validate_paper_fill_calendar_days(
    fills: Sequence[Mapping[str, object]],
    calendar: OfficialTradingCalendar,
) -> None:
    """確認每筆成交日都有獨立的官方開市證據。"""

    for item in fills:
        event_day = _record_date(item, "event_date", "paper fill")
        try:
            is_trading_day, reason = calendar.is_official_trading_day(
                event_day,
                allow_online_probe=True,
            )
        except Exception as error:  # noqa: BLE001 - unknown source is unsafe
            raise FormalDailyInputProducerError(
                f"paper fill official calendar evidence failed:{_safe_error(error)}"
            ) from error
        if is_trading_day is not True:
            raise FormalDailyInputProducerError(
                "paper fill event date is not an officially proven trading day:"
                f"{event_day.isoformat()}:{reason}"
            )


def _validate_paper_boundary_reconciliation(
    *,
    start: Mapping[str, object],
    end: Mapping[str, object],
    fills: Sequence[Mapping[str, object]],
) -> None:
    start_quantities = {
        _record_text(item, "stock_code", "start position"): _record_int(
            item, "quantity", "start position"
        )
        for item in _record_sequence(start, "positions", "start snapshot")
    }
    end_quantities = {
        _record_text(item, "stock_code", "end position"): _record_int(
            item, "quantity", "end position"
        )
        for item in _record_sequence(end, "positions", "end snapshot")
    }
    deltas: dict[str, int] = {}
    for item in fills:
        symbol = _record_text(item, "stock_code", "paper fill")
        value = _record_int(item, "filled_quantity", "paper fill")
        signed = (
            value
            if _record_text(item, "side", "paper fill") == "buy"
            else -value
        )
        deltas[symbol] = deltas.get(symbol, 0) + signed
    symbols = sorted(set(start_quantities) | set(end_quantities) | set(deltas))
    for symbol in symbols:
        expected = end_quantities.get(symbol, 0) - start_quantities.get(symbol, 0)
        observed = deltas.get(symbol, 0)
        if expected != observed:
            raise FormalDailyInputProducerError(
                f"paper fill quantity reconciliation mismatch:{symbol}"
            )
    start_cash = _decimal_object(start.get("cash_decimal"), "start cash")
    end_cash = _decimal_object(end.get("cash_decimal"), "end cash")
    cash_delta = Decimal("0.00")
    for item in fills:
        gross = _record_decimal(item, "gross_amount", "paper fill")
        # fill_price 已含 slippage；正式現金守恆只結算 commission + tax。
        # total_cost 仍保留完整執行成本歸因，不在此重扣。
        commission = _record_decimal(item, "commission", "paper fill")
        tax = _record_decimal(item, "tax", "paper fill")
        settlement_cost = (commission + tax).quantize(Decimal("0.01"))
        cash_delta += (
            gross - settlement_cost
            if _record_text(item, "side", "paper fill") == "sell"
            else -gross - settlement_cost
        )
    expected_cash = (start_cash + cash_delta).quantize(Decimal("0.01"))
    if end_cash.quantize(Decimal("0.01")) != expected_cash:
        raise FormalDailyInputProducerError(
            "paper fill cash reconciliation mismatch"
        )


def _turnover_before_date(
    fills: Sequence[Mapping[str, object]],
    boundary: date,
) -> int:
    lower = boundary - timedelta(days=7)
    return sum(
        _record_int(item, "turnover_bp", "paper fill")
        for item in fills
        if lower <= _record_date(item, "event_date", "paper fill") < boundary
    )


def _ml_weights_from_snapshot(
    snapshot: Mapping[str, object],
) -> Any:
    from ml_module.allocation_contracts import AllocationWeightContract  # noqa: PLC0415

    total = _decimal_object(snapshot.get("total_value_decimal"), "snapshot total_value")
    amounts: dict[str, Decimal] = {
        "CASH": _decimal_object(snapshot.get("cash_decimal"), "snapshot cash")
    }
    for item in _mapping_sequence(snapshot.get("positions"), "snapshot.positions"):
        symbol = _required_nonempty_text(item.get("stock_code"), "snapshot stock_code")
        quantity = _required_nonnegative_int(item.get("quantity"), "snapshot quantity")
        market_value = _finite_decimal(item.get("market_value"), "snapshot market_value")
        if quantity > 0 and market_value > 0:
            amounts[symbol] = market_value
    floors: dict[str, int] = {}
    remainders: dict[str, Decimal] = {}
    for symbol, amount in amounts.items():
        exact = amount * Decimal(10_000) / total
        floor = int(exact.to_integral_value(rounding=ROUND_DOWN))
        floors[symbol] = floor
        remainders[symbol] = exact - Decimal(floor)
    missing = 10_000 - sum(floors.values())
    for symbol in sorted(amounts, key=lambda key: (-remainders[key], key))[:missing]:
        floors[symbol] += 1
    positions = tuple(
        (symbol, floors[symbol])
        for symbol in sorted(floors)
        if symbol != "CASH" and floors[symbol] > 0
    )
    return AllocationWeightContract(
        positions_bp=positions,
        cash_bp=floors.get("CASH", 0),
    )


def _ml_weight_payload(weights: Any) -> dict[str, object]:
    return {
        "positions_bp": [[symbol, value] for symbol, value in weights.positions_bp],
        "cash_bp": weights.cash_bp,
    }


def _ml_state_payload(state: Any) -> dict[str, object]:
    return {
        "as_of_date": state.as_of_date,
        "weights": _ml_weight_payload(state.weights),
        "weekly_turnover_used_bp": state.weekly_turnover_used_bp,
        "state_hash": state.state_hash,
    }


def _write_formal_ledger_sqlite(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE transitions (
                decision_date TEXT PRIMARY KEY,
                input_state_json TEXT NOT NULL,
                desired_weights_json TEXT NOT NULL,
                output_state_json TEXT NOT NULL,
                feature_input_hash TEXT NOT NULL,
                buy_turnover_bp INTEGER NOT NULL,
                sell_turnover_bp INTEGER NOT NULL,
                canonical_turnover_bp INTEGER NOT NULL,
                estimated_cost_bp INTEGER NOT NULL,
                add_count INTEGER NOT NULL,
                reduce_count INTEGER NOT NULL,
                transition_hash TEXT NOT NULL UNIQUE,
                chain_hash TEXT NOT NULL UNIQUE
            );
            CREATE TRIGGER transitions_no_update
            BEFORE UPDATE ON transitions
            BEGIN
                SELECT RAISE(ABORT, 'append-only formal ledger');
            END;
            CREATE TRIGGER transitions_no_delete
            BEFORE DELETE ON transitions
            BEGIN
                SELECT RAISE(ABORT, 'append-only formal ledger');
            END;
            """
        )
        connection.executemany(
            """
            INSERT INTO transitions(
                decision_date, input_state_json, desired_weights_json,
                output_state_json, feature_input_hash, buy_turnover_bp,
                sell_turnover_bp, canonical_turnover_bp, estimated_cost_bp,
                add_count, reduce_count, transition_hash, chain_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(
                (
                    row["decision_date"],
                    row["input_state_json"],
                    row["desired_weights_json"],
                    row["output_state_json"],
                    row["feature_input_hash"],
                    row["buy_turnover_bp"],
                    row["sell_turnover_bp"],
                    row["canonical_turnover_bp"],
                    row["estimated_cost_bp"],
                    row["add_count"],
                    row["reduce_count"],
                    row["transition_hash"],
                    row["chain_hash"],
                )
                for row in rows
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _mapping_sequence(value: object, field_name: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        raise FormalDailyInputProducerError(f"{field_name} must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise FormalDailyInputProducerError(f"{field_name} row must be an object")
        result.append(item)
    return tuple(result)


def _record_value(
    record: Mapping[str, object],
    key: str,
    record_name: str,
) -> object:
    if key not in record:
        raise FormalDailyInputProducerError(
            f"{record_name} is missing required field: {key}"
        )
    return record[key]


def _record_text(
    record: Mapping[str, object],
    key: str,
    record_name: str,
) -> str:
    return _required_nonempty_text(
        _record_value(record, key, record_name),
        f"{record_name}.{key}",
    )


def _record_date(
    record: Mapping[str, object],
    key: str,
    record_name: str,
) -> date:
    return _required_date_object(
        _record_value(record, key, record_name),
        f"{record_name}.{key}",
    )


def _record_int(
    record: Mapping[str, object],
    key: str,
    record_name: str,
) -> int:
    return _required_nonnegative_int(
        _record_value(record, key, record_name),
        f"{record_name}.{key}",
    )


def _record_decimal(
    record: Mapping[str, object],
    key: str,
    record_name: str,
) -> Decimal:
    return _decimal_object(
        _record_value(record, key, record_name),
        f"{record_name}.{key}",
    )


def _record_sequence(
    record: Mapping[str, object],
    key: str,
    record_name: str,
) -> tuple[Mapping[str, object], ...]:
    return _mapping_sequence(
        _record_value(record, key, record_name),
        f"{record_name}.{key}",
    )


def _paper_rows_content_hash(
    rows: Sequence[Mapping[str, object]],
    *,
    schema_version: str,
) -> str:
    """Hash validated row identities from one SQLite read transaction.

    Each source row's ``content_hash`` is calculated only after its complete
    Decimal/domain/custody validation.  The aggregate therefore changes when
    any source payload changes, including a change that is only present in a
    WAL frame.  It intentionally does not claim that the SQLite main file is
    the complete source artifact.
    """

    normalized: list[dict[str, str]] = []
    for row in rows:
        if "snapshot_id" in row:
            normalized.append(
                {
                    "kind": "snapshot",
                    "id": _record_text(row, "snapshot_id", "paper snapshot"),
                    "date": _record_date(
                        row, "decision_date", "paper snapshot"
                    ).isoformat(),
                    "content_hash": _record_text(
                        row, "content_hash", "paper snapshot"
                    ),
                }
            )
        else:
            normalized.append(
                {
                    "kind": "fill",
                    "id": _record_text(row, "fill_id", "paper fill"),
                    "date": _record_date(row, "event_date", "paper fill").isoformat(),
                    "content_hash": _record_text(
                        row, "content_hash", "paper fill"
                    ),
                }
            )
    return _payload_hash(
        {
            "schema_version": schema_version,
            "row_count": len(normalized),
            "rows": normalized,
        }
    )


def _required_nonempty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalDailyInputProducerError(f"{field_name} must be non-empty text")
    return value.strip()


def _canonical_date_text(value: object, field_name: str) -> str:
    text = _required_nonempty_text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise FormalDailyInputProducerError(f"{field_name} must be YYYY-MM-DD") from error
    if parsed.isoformat() != text:
        raise FormalDailyInputProducerError(f"{field_name} must be YYYY-MM-DD")
    return text


def _required_date_object(value: object, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(_canonical_date_text(value, field_name))


def _required_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise FormalDailyInputProducerError(f"{field_name} must be a non-negative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise FormalDailyInputProducerError(f"{field_name} must be a non-negative integer")
    if parsed < 0:
        raise FormalDailyInputProducerError(f"{field_name} must be a non-negative integer")
    return parsed


def _required_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise FormalDailyInputProducerError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as error:
            raise FormalDailyInputProducerError(f"{field_name} must be an integer") from error
    raise FormalDailyInputProducerError(f"{field_name} must be an integer")


def _strict_sqlite_bool(value: object, field_name: str) -> bool:
    parsed = _required_nonnegative_int(value, field_name)
    if parsed not in (0, 1):
        raise FormalDailyInputProducerError(f"{field_name} must be 0 or 1")
    return bool(parsed)


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise FormalDailyInputProducerError(f"{field_name} must be an exact Decimal value")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise FormalDailyInputProducerError(f"{field_name} must be an exact Decimal value") from error
    if not parsed.is_finite():
        raise FormalDailyInputProducerError(f"{field_name} must be finite")
    return parsed


def _decimal_object(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise FormalDailyInputProducerError(f"{field_name} must be Decimal")
    return value


def _readback_explicit_formal_sources(
    paths: DailyFormalInputPaths,
    *,
    training_as_of: str,
) -> tuple[dict[str, dict[str, object]], list[str]]:
    results: dict[str, dict[str, object]] = {}
    blockers: list[str] = []
    configured = (
        (
            "causal_non_cash_portfolio_ledger",
            paths.formal_ledger_path,
            FORMAL_LEDGER_ENV,
        ),
        (
            "formal_rule_champion_snapshot_history",
            paths.formal_rule_history_path,
            FORMAL_RULE_ENV,
        ),
        ("pit_sector_membership", paths.formal_sector_path, FORMAL_SECTOR_ENV),
    )
    for input_name, path, environment_name in configured:
        if path is None:
            results[input_name] = {
                "input": input_name,
                "state": "missing",
                "formal_ready": False,
                "formal_consumer_compatible": False,
                "candidate_only": True,
                "environment_variable": environment_name,
                "reason": f"formal_{_input_slug(input_name)}_source_missing",
            }
            blockers.append(str(results[input_name]["reason"]))
            continue
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            reason = f"formal_{_input_slug(input_name)}_source_file_missing"
            results[input_name] = {
                "input": input_name,
                "state": "missing",
                "formal_ready": False,
                "formal_consumer_compatible": False,
                "candidate_only": True,
                "path": str(resolved),
                "environment_variable": environment_name,
                "reason": reason,
            }
            blockers.append(reason)
            continue
        try:
            if input_name == "causal_non_cash_portfolio_ledger":
                results[input_name] = _readback_formal_ledger(resolved, training_as_of)
            elif input_name == "formal_rule_champion_snapshot_history":
                results[input_name] = _readback_formal_rule(resolved, training_as_of)
            else:
                results[input_name] = _readback_formal_sector(resolved, training_as_of)
        except Exception as error:  # noqa: BLE001 - preserve exact machine blocker
            reason = f"formal_{_input_slug(input_name)}_consumer_rejected:{_safe_error(error)}"
            results[input_name] = {
                "input": input_name,
                "state": "invalid",
                "formal_ready": False,
                "formal_consumer_compatible": False,
                "candidate_only": True,
                "path": str(resolved),
                "file_hash": _file_hash_or_none(resolved),
                "environment_variable": environment_name,
                "reason": reason,
            }
            blockers.append(reason)
    return results, blockers


def _readback_formal_ledger(path: Path, training_as_of: str) -> dict[str, object]:
    from data_module.formal_portfolio_ledger import (  # noqa: PLC0415
        load_formal_portfolio_state_ledger,
    )

    cutoff = _aware_datetime(training_as_of, "training_as_of").astimezone(TAIPEI).date()
    replay = load_formal_portfolio_state_ledger(path)
    if any(date.fromisoformat(item) >= cutoff for item in replay.decision_dates):
        raise FormalDailyInputProducerError(
            "date-only formal ledger transition is not strictly before cutoff"
        )
    return {
        "input": "causal_non_cash_portfolio_ledger",
        "state": "ready",
        "formal_ready": True,
        "formal_consumer_compatible": True,
        "candidate_only": False,
        "path": str(path),
        "file_hash": _file_hash_or_none(path),
        "manifest_hash": replay.ledger_manifest_hash,
        "ledger_file_hash": replay.ledger_file_hash,
        "transition_chain_hash": replay.transition_chain_hash,
        "decision_dates": list(replay.decision_dates),
        "decision_date_count": len(replay.decision_dates),
        "non_cash_state_day_count": replay.non_cash_state_day_count,
        "consumer": "data_module.formal_portfolio_ledger.load_formal_portfolio_state_ledger",
        "cutoff_semantics": "taipei_calendar_date_after_date_only_transition",
    }


def _readback_formal_rule(path: Path, training_as_of: str) -> dict[str, object]:
    history = load_verified_rule_champion_snapshot_history(
        path,
        training_as_of=training_as_of,
    )
    return {
        "input": "formal_rule_champion_snapshot_history",
        "state": "ready",
        "formal_ready": True,
        "formal_consumer_compatible": True,
        "candidate_only": False,
        "path": str(path),
        "file_hash": _file_hash_or_none(path),
        "manifest_hash": history.manifest_hash,
        "decision_dates": list(history.decision_dates),
        "snapshot_count": len(history.snapshots),
        "registered_store_id": history.registered_store_id,
        "consumer": "data_module.rule_champion_snapshot_service.load_verified_rule_champion_snapshot_history",
        "cutoff_semantics": "timezone_aware_decision_timestamp_at_or_before_training_as_of",
    }


def _readback_formal_sector(path: Path, training_as_of: str) -> dict[str, object]:
    # Reuse the exact explicit-path validator used by the owner packet.  It
    # performs canonical manifest, row, source, license and cutoff checks.
    formal_store._validate_sector_sidecar(path, training_as_of=training_as_of)
    # _validate_sector_sidecar returns None on success; the row count is
    # obtained through the same in-memory assembler spool for the receipt.
    import sqlite3 as _sqlite3  # noqa: PLC0415
    from data_module import portfolio_ml_dataset_assembler as assembler  # noqa: PLC0415

    connection = _sqlite3.connect(":memory:")
    try:
        assembler._initialize_spool(connection)
        manifest_hash, row_count = assembler._spool_sector_memberships(
            connection,
            path,
            training_as_of=_aware_datetime(training_as_of, "training_as_of"),
        )
    finally:
        connection.close()
    return {
        "input": "pit_sector_membership",
        "state": "ready",
        "formal_ready": True,
        "formal_consumer_compatible": True,
        "candidate_only": False,
        "path": str(path),
        "file_hash": _file_hash_or_none(path),
        "manifest_hash": manifest_hash,
        "row_count": row_count,
        "consumer": "data_module.portfolio_ml_dataset_assembler._spool_sector_memberships",
        "cutoff_semantics": "available_at_at_or_before_training_as_of",
    }


def _load_clock_projection(
    path: Path | None,
    *,
    now: datetime,
) -> tuple[
    ProspectiveFormalClock | None,
    dict[str, object],
    list[str],
]:
    if path is None:
        return None, {}, ["rule_clock_source_missing"]
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return None, {"path": str(resolved)}, ["rule_clock_source_file_missing"]
    try:
        clock = load_clock_manifest_for_capture(resolved, now=now)
    except Exception as error:  # noqa: BLE001 - preflight must stay structured
        return (
            None,
            {
                "path": str(resolved),
                "file_hash": _file_hash_or_none(resolved),
            },
            [f"rule_clock_invalid:{_safe_error(error)}"],
        )
    payload = clock.payload
    projection: dict[str, object] = {
        "path": str(resolved),
        "file_hash": _file_hash_or_none(resolved),
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "activation_trading_day": clock.activation_trading_day.isoformat(),
        "strategy_version": payload.get("strategy_version"),
        "policy_version": payload.get("policy_version"),
        "policy_hash": payload.get("policy_hash"),
        "universe_hash": payload.get("universe_hash"),
        "source_policy_hash": payload.get("source_policy_hash"),
        "candidate_model_hash": payload.get("candidate_model_hash"),
        "candidate_feature_manifest_hash": payload.get(
            "candidate_feature_manifest_hash"
        ),
        "decision_time": payload.get("decision_time"),
        "pit_decision_time": payload.get("pit_decision_time"),
        "historical_backfill_claimed": payload.get("historical_backfill_claimed"),
        "real_money": payload.get("real_money"),
        "broker_execution": payload.get("broker_execution"),
    }
    return clock, projection, []


def _load_clock_from_preflight(
    path: Path | None,
    now: datetime,
) -> ProspectiveFormalClock | None:
    if path is None or not path.expanduser().resolve().is_file():
        return None
    try:
        return load_clock_manifest_for_capture(path.expanduser().resolve(), now=now)
    except Exception:
        return None


def _load_universe_projection(
    path: Path | None,
) -> tuple[tuple[str, ...] | None, dict[str, object], list[str]]:
    if path is None:
        return None, {}, ["rule_universe_source_missing"]
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return None, {"path": str(resolved)}, ["rule_universe_source_file_missing"]
    try:
        symbols = _read_symbols(resolved)
    except Exception as error:  # noqa: BLE001
        return (
            None,
            {"path": str(resolved), "file_hash": _file_hash_or_none(resolved)},
            [f"rule_universe_source_invalid:{_safe_error(error)}"],
        )
    return (
        symbols,
        {
            "path": str(resolved),
            "file_hash": _file_hash_or_none(resolved),
            "symbol_count": len(symbols),
            "symbols_hash": _payload_hash(list(symbols)),
        },
        [],
    )


def _acceptance_projection(
    path: Path | None,
    *,
    clock: ProspectiveFormalClock | None,
    market_db: Path | None = None,
    observed: datetime | None = None,
) -> tuple[dict[str, object], list[str]]:
    if path is None:
        return {}, ["rule_owner_acceptance_source_missing"]
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return {"path": str(resolved)}, ["rule_owner_acceptance_source_file_missing"]
    try:
        payload = _read_json_object(resolved)
    except Exception as error:  # noqa: BLE001
        return {"path": str(resolved)}, [f"rule_owner_acceptance_invalid:{_safe_error(error)}"]
    projection: dict[str, object] = {
        "path": str(resolved),
        "file_hash": _file_hash_or_none(resolved),
        "decision_id": payload.get("decision_id"),
        "accepted_strategy_version": payload.get("accepted_strategy_version"),
        "accepted_policy_version": payload.get("accepted_policy_version"),
        "policy_hash": payload.get("policy_hash"),
        "universe_hash": payload.get("universe_hash"),
        "score_configuration_hash": payload.get("score_configuration_hash"),
        "formal_oos_allowed": payload.get("formal_oos_allowed"),
        "promotion_eligible": payload.get("promotion_eligible"),
        "broker_order_allowed": payload.get("broker_order_allowed"),
        "acceptance_source": payload.get("acceptance_source"),
        "machine_review_identity": payload.get("machine_review_identity"),
        "machine_review_version": payload.get("machine_review_version"),
    }
    if clock is None:
        return projection, ["rule_owner_acceptance_clock_binding_unproven"]
    expected: dict[str, object] = {
        "decision_id": clock.payload.get("owner_decision_id"),
        "accepted_strategy_version": clock.payload.get("strategy_version"),
        "accepted_policy_version": clock.payload.get("policy_version"),
        "policy_hash": clock.payload.get("policy_hash"),
        "universe_hash": clock.payload.get("universe_hash"),
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
    }
    mismatches = [
        field
        for field, expected_value in expected.items()
        if payload.get(field) != expected_value
    ]
    if mismatches:
        return projection, [
            "rule_owner_acceptance_identity_mismatch:" + ",".join(sorted(mismatches))
        ]
    score_hash = payload.get("score_configuration_hash")
    if not _is_sha256(score_hash):
        return projection, ["rule_owner_acceptance_score_hash_invalid"]
    timing_override = clock.payload.get("activation_timing_override")
    clock_is_machine_revalidated = (
        isinstance(timing_override, Mapping)
        and timing_override.get("reason_code")
        == SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON
    )
    owner_is_machine_revalidated = payload.get("acceptance_source") == (
        "machine_revalidated_existing_owner_policy"
    )
    if clock_is_machine_revalidated != owner_is_machine_revalidated:
        return projection, ["machine_revalidation_clock_owner_identity_mismatch"]
    if clock_is_machine_revalidated:
        if market_db is None:
            return projection, ["machine_revalidation_market_db_not_supplied"]
        from data_module.formal_rule_source_producer import (  # noqa: PLC0415
            validate_machine_revalidation_bundle,
        )

        try:
            machine_validation = validate_machine_revalidation_bundle(
                resolved.parent.parent,
                market_db=market_db,
                observed=observed,
            )
        except Exception as error:  # noqa: BLE001 - retain exact machine blocker
            return projection, [
                "machine_revalidation_consumer_rejected:" + _safe_error(error)
            ]
        projection["machine_revalidation"] = machine_validation
    projection["identity_verified"] = True
    return projection, []


def _market_projection(path: Path) -> tuple[dict[str, object], list[str]]:
    resolved = path.expanduser().resolve()
    projection: dict[str, object] = {
        "path": str(resolved),
        "mode": "ro/query_only",
        "state": "missing",
        "file_hash": None,
        "daily_prices_present": False,
    }
    if not resolved.is_file():
        return projection, ["rule_market_db_source_file_missing"]
    projection["file_hash"] = _file_hash_or_none(resolved)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        columns = {
            str(item[1])
            for item in connection.execute("PRAGMA table_info(daily_prices)")
        }
        required = {"日期", "證券代號", "收盤價"}
        if not required.issubset(columns):
            raise FormalDailyInputProducerError("daily_prices_required_columns_missing")
        projection["daily_prices_present"] = True
        projection["state"] = "ready"
    except Exception as error:  # noqa: BLE001
        return projection, [f"rule_market_db_read_failed:{_safe_error(error)}"]
    finally:
        if connection is not None:
            connection.close()
    return projection, []


def _calendar_projection(
    market_db: Path,
    *,
    target_date: date,
    calendar: OfficialTradingCalendar | None,
) -> tuple[dict[str, object], list[str]]:
    service = calendar or OfficialTradingCalendar(db_path=market_db)
    try:
        is_trading_day, reason = service.is_official_trading_day(target_date)
    except Exception as error:  # noqa: BLE001
        is_trading_day, reason = None, f"calendar_exception:{_safe_error(error)}"
    projection: dict[str, object] = {
        "target_date": target_date.isoformat(),
        "is_trading_day": is_trading_day,
        "reason_code": reason,
        "provider": "data_module.official_trading_calendar.OfficialTradingCalendar",
        "official_source_required": True,
        "online_probe_reason_code": reason,
        "fallback_evidence": None,
    }
    # 年度 holidaySchedule 暫時不可達時，沿既有 Calendar 的明確唯讀
    # market_indices 日期列重試；這不是以星期幾推定開市。缺少該列時仍
    # 保持 unknown，並將線上失敗原因留在 receipt 供排程與 QA 追蹤。
    if is_trading_day is None:
        try:
            offline_day, offline_reason = service.is_official_trading_day(
                target_date,
                allow_online_probe=False,
            )
        except TypeError:
            # 舊的隔離／外掛 calendar 可能只有單一參數；不能因 fallback
            # 介面不存在而改變其原本判定。
            offline_day, offline_reason = None, "offline_probe_unsupported"
        except Exception as error:  # noqa: BLE001 - calendar remains fail closed
            offline_day, offline_reason = None, f"offline_probe_exception:{_safe_error(error)}"
        projection["fallback_evidence"] = {
            "is_trading_day": offline_day,
            "reason_code": offline_reason,
            "mode": "read_only_market_indices_date_evidence",
        }
        if offline_day is True:
            is_trading_day = True
            reason = str(offline_reason)
            projection["is_trading_day"] = True
            projection["reason_code"] = str(offline_reason)
    if is_trading_day is not True:
        return projection, [
            "official_calendar_not_proven:" + str(projection["reason_code"])
        ]
    return projection, []


def _explicit_formal_source_projections(
    paths: DailyFormalInputPaths,
) -> dict[str, dict[str, object]]:
    values = (
        (
            "causal_non_cash_portfolio_ledger",
            paths.formal_ledger_path,
            FORMAL_LEDGER_ENV,
        ),
        (
            "formal_rule_champion_snapshot_history",
            paths.formal_rule_history_path,
            FORMAL_RULE_ENV,
        ),
        ("pit_sector_membership", paths.formal_sector_path, FORMAL_SECTOR_ENV),
    )
    result: dict[str, dict[str, object]] = {}
    for input_name, path, environment_name in values:
        if path is None:
            result[input_name] = {
                "state": "missing",
                "formal_ready": False,
                "formal_consumer_compatible": False,
                "candidate_only": True,
                "environment_variable": environment_name,
                "reason": f"formal_{_input_slug(input_name)}_source_missing",
            }
            continue
        resolved = path.expanduser().resolve()
        result[input_name] = {
            "state": "configured" if resolved.is_file() else "missing",
            "formal_ready": False,
            "formal_consumer_compatible": False,
            "candidate_only": True,
            "environment_variable": environment_name,
            "path": str(resolved),
            "file_hash": _file_hash_or_none(resolved),
            "reason": (
                "explicit_formal_source_configured"
                if resolved.is_file()
                else f"formal_{_input_slug(input_name)}_source_file_missing"
            ),
        }
    return result


def _fetch_official_source(url: str) -> OfficialSourceResponse:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "technical-analysis-formal-input-producer/1.0",
        },
        method="GET",
    )
    with urlopen(request, timeout=PIT_SOURCE_TIMEOUT_SECONDS) as response:
        body = response.read(PIT_SOURCE_MAX_BYTES + 1)
        completed_at = datetime.now(timezone.utc)
        final_url = response.geturl()
        status = getattr(response, "status", None)
        headers = response.headers
    if len(body) > PIT_SOURCE_MAX_BYTES:
        raise FormalDailyInputProducerError("official PIT response exceeds bounded size")
    if not body:
        raise FormalDailyInputProducerError("official PIT response is empty")
    if final_url != url:
        raise FormalDailyInputProducerError("official PIT response final URL mismatch")
    if isinstance(status, bool) or not isinstance(status, int) or status != 200:
        raise FormalDailyInputProducerError("official PIT response HTTP status is not 200")
    metadata: dict[str, object] = {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": str(headers.get("Content-Type") or "application/json"),
        "http_date": headers.get("Date"),
        "http_last_modified": headers.get("Last-Modified"),
        "captured_at": completed_at.isoformat(),
    }
    return OfficialSourceResponse(body=body, metadata=metadata)


def _prepare_output_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    _require_temp_path(resolved, "daily producer output")
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise FormalDailyInputProducerError(
                "daily producer output root must be a new empty TEMP directory"
            )
    else:
        resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _prepare_development_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    _require_temp_path(resolved, "Rule development output")
    if resolved.name != "technical_analysis_development_output":
        raise FormalDailyInputProducerError(
            "development output root name must be technical_analysis_development_output"
        )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise FormalDailyInputProducerError(
                "Rule development output root must be a new empty TEMP directory"
            )
    else:
        resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _output_preflight_blockers(path: Path) -> list[str]:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError:
        return ["output_path_must_be_under_os_temp"]
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        return ["output_path_must_be_new_empty_temp_directory"]
    return []


def _publication_root_projection(
    path: Path | None,
) -> tuple[dict[str, object], list[str]]:
    """檢查 durable publication root；不建立目錄或讀取來源資料。"""

    if path is None:
        return {
            "configured": False,
            "path": None,
            "mode": "candidate_only_temp_output",
        }, []
    resolved = path.expanduser().resolve()
    repository_output = Path(__file__).resolve().parents[1] / "output"
    temp_root = Path(tempfile.gettempdir()).resolve()
    allowed = False
    persistence = ""
    try:
        resolved.relative_to(repository_output.resolve())
        allowed = True
        persistence = "repository_output_append_only_runs"
    except ValueError:
        try:
            resolved.relative_to(temp_root)
            allowed = True
            persistence = "isolated_temp_append_only_runs"
        except ValueError:
            pass
    blockers: list[str] = []
    if not allowed:
        blockers.append("publication_root_must_be_repo_output_or_os_temp")
    if resolved.exists() and not resolved.is_dir():
        blockers.append("publication_root_is_not_directory")
    if path.expanduser().resolve() == Path.cwd().resolve():
        blockers.append("publication_root_must_not_be_repository_root")
    return {
        "configured": True,
        "path": str(resolved),
        "mode": "immutable_run_directory",
        "persistence": persistence or "rejected",
    }, blockers


def _prepare_publication_root(path: Path) -> Path:
    projection, blockers = _publication_root_projection(path)
    if blockers:
        raise FormalDailyInputProducerError(
            "publication root rejected:" + ",".join(blockers)
        )
    raw_path = projection.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise FormalDailyInputProducerError("publication root path is invalid")
    resolved = Path(raw_path)
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FormalDailyInputProducerError(
            f"publication root cannot be created:{type(error).__name__}"
        ) from error
    if not resolved.is_dir():
        raise FormalDailyInputProducerError("publication root is not a directory")
    return resolved


def _require_temp_path(path: Path, field_name: str) -> None:
    try:
        path.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as error:
        raise FormalDailyInputProducerError(
            f"{field_name} must be under operating-system TEMP"
        ) from error


def _clock_is_current(
    clock: ProspectiveFormalClock | None,
    now_taipei: datetime,
) -> bool:
    return clock is not None and clock.activation_trading_day == now_taipei.date()


def _clock_decision_time(clock: ProspectiveFormalClock) -> time | None:
    value = clock.payload.get("decision_time")
    if not isinstance(value, str):
        return None
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else None


def _read_rule_requests(path: Path) -> tuple[ProspectiveRuleSnapshotRequest, ...]:
    payload = _read_json_value(path)
    if not isinstance(payload, list) or not payload:
        raise FormalDailyInputProducerError("Rule requests are invalid")
    requests: list[ProspectiveRuleSnapshotRequest] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise FormalDailyInputProducerError("Rule request row is invalid")
        decision_date = item.get("decision_date")
        ids = item.get("decision_snapshot_ids")
        if not isinstance(decision_date, str) or not isinstance(ids, list):
            raise FormalDailyInputProducerError("Rule request fields are invalid")
        if any(not isinstance(value, str) or not value.strip() for value in ids):
            raise FormalDailyInputProducerError("Rule request snapshot ids are invalid")
        requests.append(
            ProspectiveRuleSnapshotRequest(
                decision_date=decision_date,
                decision_snapshot_ids=tuple(ids),
            )
        )
    return tuple(requests)


def _read_symbols(path: Path) -> tuple[str, ...]:
    value = _read_json_value(path)
    if not isinstance(value, list) or not value:
        raise FormalDailyInputProducerError("universe symbols must be a non-empty array")
    symbols = tuple(item.strip() for item in value if isinstance(item, str))
    if len(symbols) != len(value) or any(not item for item in symbols):
        raise FormalDailyInputProducerError("universe symbols must be non-empty text")
    if symbols != tuple(sorted(set(symbols))):
        raise FormalDailyInputProducerError("universe symbols must be sorted and unique")
    return symbols


def _read_json_object(path: Path) -> dict[str, object]:
    value = _read_json_value(path)
    if not isinstance(value, dict):
        raise FormalDailyInputProducerError("JSON object expected")
    return {str(key): value_item for key, value_item in value.items()}


def _read_json_value(path: Path) -> Any:
    try:
        return json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalDailyInputProducerError(f"JSON unreadable: {path}") from error


def _write_immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise FormalDailyInputProducerError("daily producer receipt already exists") from error


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_hash_or_none(path: Path) -> str | None:
    try:
        return file_sha256(path) if path.is_file() else None
    except OSError:
        return None


def _env_configured(name: str) -> bool:
    value = os.environ.get(name)
    return isinstance(value, str) and bool(value.strip())


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise FormalDailyInputProducerError(f"{field_name} must be ISO datetime") from error
    else:
        raise FormalDailyInputProducerError(f"{field_name} must be timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FormalDailyInputProducerError(f"{field_name} must include timezone")
    return parsed


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FormalDailyInputProducerError(f"{field_name} must be an object")
    return {str(key): item for key, item in value.items()}


def _text_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise FormalDailyInputProducerError("blockers must be an array")
    return [str(item) for item in value]


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _input_slug(input_name: str) -> str:
    return {
        "causal_non_cash_portfolio_ledger": "ledger",
        "formal_rule_champion_snapshot_history": "rule_history",
        "pit_sector_membership": "sector",
    }[input_name]


def _safe_error(error: Exception) -> str:
    detail = str(error).splitlines()[0].strip() or type(error).__name__
    if len(detail) > 220:
        detail = detail[:217] + "..."
    # Error text from dependencies should never become a secret sink.
    return detail.replace("\x00", "?")


__all__ = [
    "DAILY_FORMAL_INPUT_PRODUCER_SCHEMA_VERSION",
    "DAILY_FORMAL_INPUT_PRODUCER_VERSION",
    "DailyFormalInputPaths",
    "FormalDailyInputProducerError",
    "OfficialSourceResponse",
    "build_daily_formal_input_preflight",
    "capture_pit_candidate_before_cutoff",
    "reuse_pit_candidate_archive_before_cutoff",
    "run_daily_formal_input_producer",
]
