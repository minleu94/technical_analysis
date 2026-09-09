"""執行一輪日常 Formal input producer，並保存可重驗的排程狀態。

這個入口只從 Windows 使用者環境讀取來源路徑，並可由 wrapper 指定唯讀的
Rule source bundle 根目錄；使用當下 UTC／台北時間，不提供日期覆寫或人工
確認參數。candidate 與 Rule development 會放在新的
TEMP 目錄；Rule／causal ledger／PIT history handoff 的 immutable publication
則寫到合法的 repository output publication root。缺少來源時仍寫入具體
blocker，排程以非零狀態結束，不把 candidate-only 當成 Formal 3/3 成功。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
from typing import Sequence
import uuid
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_daily_input_producer import (  # noqa: E402
DAILY_FORMAL_INPUT_PRODUCER_SCHEMA_VERSION,
    DailyFormalInputPaths,
    run_daily_formal_input_producer,
)
from data_module.formal_runtime_config import (  # noqa: E402
    FORMAL_RUNTIME_CONFIG_ENV,
    FormalRuntimeConfigError,
    load_optional_formal_runtime_config,
)
from data_module.prospective_formal_clock import (  # noqa: E402
    file_sha256,
    load_clock_manifest_for_capture,
)
from data_module.formal_pit_sector_publisher import (  # noqa: E402
    read_formal_pit_sector_receipt,
)
from data_module.pit_prospective_denominator import (  # noqa: E402
    validate_prospective_pit_denominator,
)


_DEFAULT_DATA_ROOT = Path(r"D:\Min\Python\Project\FA_Data")
TAIPEI = ZoneInfo("Asia/Taipei")
_REQUIRED_SOURCE_ENV = (
    "FORMAL_DAILY_CLOCK_MANIFEST",
    "FORMAL_DAILY_UNIVERSE_SYMBOLS",
    "FORMAL_DAILY_OWNER_ACCEPTANCE",
)
_RULE_SOURCE_ROOT_ENV = "FORMAL_DAILY_RULE_SOURCE_ROOT"
_LEGACY_FORMAL_SOURCE_ENV = (
    "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
    "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
    "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
    "BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH",
)
_SCHEDULED_ATTEMPT_LOG_SCHEMA_VERSION = "formal-input-scheduled-attempt.v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publication-root",
        type=Path,
        help="覆寫 FORMAL_DAILY_PUBLICATION_ROOT；仍須是 repo output 或 TEMP",
    )
    parser.add_argument(
        "--status-root",
        type=Path,
        help="覆寫 FORMAL_DAILY_STATUS_ROOT；必須位於 publication root",
    )
    return parser


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip()).expanduser()


def _env_path_or_fallback(name: str, fallback_name: str) -> Path | None:
    return _env_path(name) or _env_path(fallback_name)


def _env_date(name: str) -> date | None:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{name} must be YYYY-MM-DD") from error
    if parsed.isoformat() != text:
        raise ValueError(f"{name} must be YYYY-MM-DD")
    return parsed


def _data_root() -> Path:
    return _env_path("DATA_ROOT") or _DEFAULT_DATA_ROOT


def _output_root(data_root: Path) -> Path:
    return _env_path("OUTPUT_ROOT") or data_root / "output"


def _publication_root(override: Path | None) -> Path:
    return (
        override
        or _env_path("FORMAL_DAILY_PUBLICATION_ROOT")
        or ROOT / "output" / "formal_daily_publications"
    ).expanduser().resolve()


def _status_root(publication_root: Path, override: Path | None) -> Path:
    configured = override or _env_path("FORMAL_DAILY_STATUS_ROOT")
    if configured is None:
        return publication_root / "scheduler"
    resolved = configured.expanduser().resolve()
    try:
        resolved.relative_to(publication_root)
    except ValueError as error:
        raise ValueError(
            "FORMAL_DAILY_STATUS_ROOT must be under FORMAL_DAILY_PUBLICATION_ROOT"
        ) from error
    return resolved


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _rule_source_error_detail(error: BaseException) -> str:
    """把 source bundle 驗證例外壓成可觀測、有限長度的單行原因。"""

    detail = " ".join(str(error).split())
    if not detail:
        return type(error).__name__
    return f"{type(error).__name__}:{detail[:220]}"


def _validate_exact_rule_source_bundle(
    bundle_path: Path,
    *,
    market_db: Path,
    observed: datetime,
) -> dict[str, object]:
    """重跑 machine Rule consumer，避免把 scheduler status 當成來源證明。"""

    from data_module.formal_rule_source_producer import (  # noqa: PLC0415
        validate_machine_revalidation_bundle,
    )

    return validate_machine_revalidation_bundle(
        bundle_path,
        market_db=market_db,
        observed=observed,
    )


def _validate_rule_universe_against_market_db(
    *,
    identity_payload: dict[str, object],
    symbols: list[str],
    market_db: Path | None,
    bundle_root: Path | None = None,
) -> None:
    """用 exact bundle source 重算 frozen universe 的 score hash。

    v3 的 source rows 已經是 immutable custody；只有 legacy v2 才從
    SQLite 重讀 T-1。這個分流避免 auto-discovery 的驗證再次把 mutated
    live rows 偷渡進正式決策。
    """

    if market_db is None:
        raise ValueError("rule market database is not configured")
    db_path = market_db.expanduser().resolve()
    if not db_path.is_file():
        raise ValueError("rule market database is missing")
    data_as_of_raw = identity_payload.get("data_as_of_date")
    session_dates = identity_payload.get("session_dates")
    expected_hash = identity_payload.get("universe_hash")
    if not isinstance(data_as_of_raw, str) or not isinstance(session_dates, list):
        raise ValueError("universe identity lacks revalidation window")
    if not isinstance(expected_hash, str):
        raise ValueError("universe identity lacks universe hash")
    try:
        data_as_of = date.fromisoformat(data_as_of_raw)
    except ValueError as error:
        raise ValueError("universe identity data_as_of_date is invalid") from error
    # 持久 identity 記錄的是最後來源交易日，不是 decision clock。使用
    # 該日期的隔日交給既有 loader，即可取到不晚於來源日的完整 window，
    # 也涵蓋來源日後接續週末或休市日的情形。
    from development_module.manual_rule_only_decision import (  # noqa: PLC0415
        _universe_hash,
        load_read_only_daily_price_window,
        rank_rule_only_candidates,
    )

    if identity_payload.get("source_window_persisted") is True:
        if bundle_root is None:
            raise ValueError("persisted rule source bundle path is missing")
        from data_module.formal_rule_source_producer import (  # noqa: PLC0415
            load_verified_rule_source_window,
        )

        window = load_verified_rule_source_window(
            bundle_root,
            market_db=db_path,
            observed=datetime.now(timezone.utc),
        )
    else:
        window = load_read_only_daily_price_window(
            db_path,
            decision_session=data_as_of + timedelta(days=1),
        )
    if list(window.session_dates) != session_dates:
        raise ValueError("rule source window sessions do not match universe identity")
    source_window_hash = identity_payload.get("source_window_hash")
    if window.source_hash != source_window_hash:
        raise ValueError("rule source window hash does not match universe identity")
    candidates = rank_rule_only_candidates(window, eligible_symbols=symbols)
    if _universe_hash(candidates) != expected_hash:
        raise ValueError("rule score universe hash does not match clock identity")


def _discover_latest_rule_source_paths(
    *,
    source_root: Path | None,
    observed: datetime | None = None,
    market_db: Path | None = None,
) -> tuple[dict[str, Path], str]:
    """找出最近一個完整且可重新驗證的 Rule source bundle。

    這裡只解析既有的 clock、universe 與 owner acceptance 檔案，沒有任何
    寫入或授權動作。clock 仍交由正式 ``load_clock_manifest_for_capture``
    重驗；owner acceptance 的欄位只作完整性篩選，Rule producer 會再次做
    完整 binding。找不到完整 bundle 時回傳空結果，讓正式 preflight 保留
    具體缺件，而不是將不完整資料拼成可用來源。
    """

    if source_root is None:
        return {}, "rule_source_root_not_configured"
    if market_db is None:
        return {}, "rule_source_discovery_market_db_not_configured"
    root = source_root.expanduser().resolve()
    if not root.is_dir():
        return {}, "rule_source_root_missing_or_not_directory"
    observed_value = observed or datetime.now(timezone.utc)
    if observed_value.tzinfo is None or observed_value.utcoffset() is None:
        return {}, "rule_source_discovery_requires_timezone"
    try:
        from data_module.prospective_formal_clock import (  # noqa: PLC0415
            SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON,
            load_clock_manifest_for_capture,
        )
    except ImportError:
        return {}, "rule_source_discovery_clock_loader_unavailable"

    candidates: list[
        tuple[date, str, dict[str, Path], dict[str, object], list[str]]
    ] = []
    failures: list[str] = []
    try:
        clock_paths = list(root.glob("clock-*/clock/manifest.json"))
    except OSError as error:
        return {}, f"rule_source_root_unreadable:{type(error).__name__}"
    for clock_path in clock_paths:
        bundle_root = clock_path.parent.parent
        owner_path = bundle_root / "metadata" / "owner_acceptance.json"
        universe_path = bundle_root / "metadata" / "universe_symbols.json"
        validation_stage = "metadata"
        try:
            clock_payload = _read_json(clock_path)
            owner_payload = _read_json(owner_path)
            universe_payload = _read_json(universe_path)
            if not isinstance(clock_payload, dict):
                raise ValueError("clock manifest must be an object")
            if not isinstance(owner_payload, dict):
                raise ValueError("owner acceptance must be an object")
            if not isinstance(universe_payload, list) or not universe_payload:
                raise ValueError("universe symbols must be a non-empty array")
            if any(not isinstance(item, str) or not item.strip() for item in universe_payload):
                raise ValueError("universe symbols contain invalid values")
            symbols = [item.strip() for item in universe_payload]
            if symbols != sorted(set(symbols)):
                raise ValueError("universe symbols are not sorted and unique")
            activation_raw = clock_payload.get("activation_trading_day")
            if not isinstance(activation_raw, str):
                raise ValueError("clock activation date is missing")
            activation_day = date.fromisoformat(activation_raw)
            validation_stage = "clock_revalidation"
            clock = load_clock_manifest_for_capture(
                clock_path,
                now=observed_value,
            )
            if clock.activation_trading_day != activation_day:
                raise ValueError("clock activation date changed during discovery")
            # 既有 Rule producer 的 universe hash 綁定候選分數與 symbols，
            # 不是純 symbols JSON 的 hash；resolver 不能用錯誤的列表 hash
            # 拒絕合法 bundle。這裡使用 producer 保存的 identity 作外部
            # binding evidence，並逐欄驗證其完整性；後續正式 producer 仍
            # 會重新讀取 market DB、重算 source window 與候選分數。
            identity_path = bundle_root / "metadata" / "universe_identity.json"
            validation_stage = "universe_identity"
            identity_payload = _read_json(identity_path)
            if not isinstance(identity_payload, dict):
                raise ValueError("universe identity must be an object")
            if identity_payload.get("schema_version") != "manual-rule-only-universe.v1":
                raise ValueError("universe identity schema is invalid")
            if identity_payload.get("symbols") != symbols:
                raise ValueError("universe identity symbols do not match symbols file")
            expected_universe_hash = clock_payload.get("universe_hash")
            if identity_payload.get("universe_hash") != expected_universe_hash:
                raise ValueError("universe identity hash does not bind clock")
            if identity_payload.get("candidate_count") != len(symbols):
                raise ValueError("universe identity candidate count does not bind symbols")
            data_as_of_raw = identity_payload.get("data_as_of_date")
            decision_session_raw = identity_payload.get("decision_session")
            session_dates = identity_payload.get("session_dates")
            if not isinstance(data_as_of_raw, str) or not isinstance(
                decision_session_raw, str
            ):
                raise ValueError("universe identity dates are missing")
            data_as_of = date.fromisoformat(data_as_of_raw)
            decision_session = date.fromisoformat(decision_session_raw)
            if data_as_of >= decision_session:
                raise ValueError("universe identity data is not before decision session")
            if not isinstance(session_dates, list) or not session_dates:
                raise ValueError("universe identity session dates are invalid")
            if any(not isinstance(item, str) for item in session_dates):
                raise ValueError("universe identity session dates are invalid")
            try:
                parsed_session_dates = [date.fromisoformat(item) for item in session_dates]
            except ValueError as error:
                raise ValueError("universe identity session dates are invalid") from error
            if (
                [item.isoformat() for item in parsed_session_dates] != session_dates
                or parsed_session_dates != sorted(set(parsed_session_dates))
                or parsed_session_dates[-1] != data_as_of
                or any(item > data_as_of for item in parsed_session_dates)
            ):
                raise ValueError("universe identity session dates are invalid")
            source_window_hash = identity_payload.get("source_window_hash")
            if (
                not isinstance(source_window_hash, str)
                or not source_window_hash.startswith("sha256:")
                or len(source_window_hash) != 71
            ):
                raise ValueError("universe identity source window hash is invalid")
            # machine-derived acceptance 不能只靠 caller 自填布林欄位；其
            # receipt 必須把 child hash、parent policy、當前 market DB bytes
            # 與可用時間綁在同一 bundle。舊的 owner-produced bundle 沒有此
            # sidecar，仍沿既有 owner binding 相容處理。
            machine_receipt_path = bundle_root / "metadata" / "machine_revalidation_receipt.json"
            timing_override = clock_payload.get("activation_timing_override")
            clock_is_machine_revalidated = (
                isinstance(timing_override, Mapping)
                and timing_override.get("reason_code")
                == SAME_DAY_PREOPEN_MACHINE_REVALIDATION_REASON
            )
            owner_is_machine_revalidated = owner_payload.get("acceptance_source") == (
                "machine_revalidated_existing_owner_policy"
            )
            if clock_is_machine_revalidated != owner_is_machine_revalidated:
                raise ValueError(
                    "machine_revalidation_clock_owner_identity_mismatch"
                )
            if clock_is_machine_revalidated:
                validation_stage = "machine_receipt"
                if not machine_receipt_path.is_file():
                    raise ValueError("machine_revalidation_receipt_missing")
                from data_module.formal_rule_source_producer import (  # noqa: PLC0415
                    validate_machine_revalidation_bundle,
                )

                validate_machine_revalidation_bundle(
                    bundle_root,
                    market_db=market_db,
                    observed=observed_value,
                )
            for field_name, expected in (
                ("source_id", "daily_prices"),
                ("formal_oos_allowed", False),
                ("historical_backfill_claimed", False),
                ("production_blend_alpha_bp", 0),
                ("promotion_eligible", False),
                ("broker_order_allowed", False),
            ):
                if identity_payload.get(field_name) != expected:
                    raise ValueError(f"universe identity {field_name} is invalid")
            expected_owner = {
                "decision_id": clock_payload.get("owner_decision_id"),
                "accepted_strategy_version": clock_payload.get("strategy_version"),
                "accepted_policy_version": clock_payload.get("policy_version"),
                "policy_hash": clock_payload.get("policy_hash"),
                "universe_hash": clock_payload.get("universe_hash"),
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "promotion_eligible": False,
                "broker_order_allowed": False,
            }
            validation_stage = "owner_acceptance"
            if any(owner_payload.get(field) != value for field, value in expected_owner.items()):
                raise ValueError("owner acceptance does not bind clock")
            score_hash = owner_payload.get("score_configuration_hash")
            if (
                not isinstance(score_hash, str)
                or not score_hash.startswith("sha256:")
                or len(score_hash) != 71
            ):
                raise ValueError("owner acceptance score hash is invalid")
            candidates.append(
                (
                    activation_day,
                    str(clock_path),
                    {
                        "FORMAL_DAILY_CLOCK_MANIFEST": clock_path.resolve(),
                        "FORMAL_DAILY_UNIVERSE_SYMBOLS": universe_path.resolve(),
                        "FORMAL_DAILY_OWNER_ACCEPTANCE": owner_path.resolve(),
                    },
                    identity_payload,
                    symbols,
                )
            )
        except Exception as error:  # noqa: BLE001 - 單一壞 bundle 不得放行
            failures.append(
                f"{clock_path.parent.parent.name}:{validation_stage}_"
                f"{_rule_source_error_detail(error)}"
            )
    if not candidates:
        detail = ",".join(failures[:3])
        return {}, "rule_source_bundle_not_verified" + (":" + detail if detail else "")
    # metadata 驗證成本低，score／source-window hash 重驗則會讀取有界的
    # 歷史 market window。依最新 activation 反向嘗試，第一個完整通過的
    # bundle 才可使用；較新的 malformed bundle 不得遮蔽較舊的合法 bundle。
    failed_revalidation_keys: set[tuple[str, tuple[str, ...], str]] = set()
    for activation_day, path_text, selected, identity, symbols in sorted(
        candidates,
        key=lambda item: (item[0], item[1]),
        reverse=True,
    ):
        identity_hash = identity.get("source_window_hash")
        session_values = identity.get("session_dates")
        universe_hash = identity.get("universe_hash")
        if (
            not isinstance(identity_hash, str)
            or not isinstance(session_values, list)
            or any(not isinstance(item, str) for item in session_values)
            or not isinstance(universe_hash, str)
        ):
            failures.append(
                f"{Path(path_text).parent.parent.name}:market_revalidation_identity_invalid"
            )
            continue
        revalidation_key = (identity_hash, tuple(session_values), universe_hash)
        if revalidation_key in failed_revalidation_keys:
            failures.append(
                f"{Path(path_text).parent.parent.name}:market_revalidation_same_identity_failed"
            )
            continue
        try:
            _validate_rule_universe_against_market_db(
                identity_payload=identity,
                symbols=symbols,
                market_db=market_db,
                bundle_root=Path(path_text).parent.parent,
            )
        except Exception as error:  # noqa: BLE001 - 繼續嘗試下一個 immutable bundle
            failed_revalidation_keys.add(revalidation_key)
            failures.append(
                f"{Path(path_text).parent.parent.name}:market_revalidation_"
                f"{_rule_source_error_detail(error)}"
            )
            continue
        return selected, "auto_discovered_latest_verified_bundle"
    detail = ",".join(failures[:3])
    return {}, "rule_source_bundle_not_verified" + (":" + detail if detail else "")


def _resolve_required_source_paths(
    *,
    observed: datetime | None = None,
) -> tuple[dict[str, Path], list[str], str | None]:
    paths: dict[str, Path] = {}
    missing: list[str] = []
    for name in _REQUIRED_SOURCE_ENV:
        path = _env_path(name)
        if path is None:
            missing.append(name)
        else:
            paths[name] = path
    if not missing:
        return paths, missing, None
    # 部分明確設定保留原狀，讓 status 指出確切缺少的 environment input。
    # 只有 wrapper 提供 source root 且沒有任何明確 Rule source path 時，
    # 才進行自動解析。
    if paths or _env_path(_RULE_SOURCE_ROOT_ENV) is None:
        return paths, missing, None
    discovered, discovery_reason = _discover_latest_rule_source_paths(
        source_root=_env_path(_RULE_SOURCE_ROOT_ENV),
        observed=observed,
        market_db=(
            _env_path("FORMAL_DAILY_MARKET_DB")
            or _data_root() / "sqlite" / "twstock.db"
        ),
    )
    if discovered:
        return discovered, [], discovery_reason
    return paths, missing, discovery_reason


def _required_source_paths(
    *,
    observed: datetime | None = None,
) -> tuple[dict[str, Path], list[str]]:
    """保留既有 caller 的二元回傳；排程入口另保存 resolver 原因。"""

    paths, missing, _ = _resolve_required_source_paths(observed=observed)
    return paths, missing


def _rule_source_configuration(
    source_paths: dict[str, Path],
    missing: list[str],
    discovery_reason: str | None = None,
) -> dict[str, object]:
    explicit = [name for name in _REQUIRED_SOURCE_ENV if _env_path(name) is not None]
    configured_root = _env_path(_RULE_SOURCE_ROOT_ENV)
    if discovery_reason == "predecessor_exact_status_paths" and not missing:
        mode = "predecessor_exact_status_paths"
    elif not missing and len(explicit) == len(_REQUIRED_SOURCE_ENV):
        mode = "explicit_environment_paths"
    elif not missing and configured_root is not None:
        mode = "auto_discovered_latest_verified_bundle"
    elif configured_root is not None:
        mode = "auto_discovery_failed"
    else:
        mode = "incomplete_source_configuration"
    return {
        "mode": mode,
        "source_root": (
            str(configured_root.expanduser().resolve())
            if configured_root is not None
            else None
        ),
        "paths": {name: str(path.expanduser().resolve()) for name, path in source_paths.items()},
        "missing_environment": list(missing),
        "discovery_reason": discovery_reason,
        "source_paths_are_read_only": True,
        "legacy_environment_policy": (
            "ignored_when_formal_daily_rule_source_root_is_configured"
        ),
        "legacy_environment_present": [
            name for name in _LEGACY_FORMAL_SOURCE_ENV if _env_path(name) is not None
        ],
    }


def _candidate_roots() -> tuple[Path, Path]:
    configured_candidate_parent = _env_path("FORMAL_DAILY_OUTPUT_ROOT")
    if configured_candidate_parent is None:
        candidate_root = Path(
            tempfile.mkdtemp(prefix="baldr_formal_daily_candidate_")
        )
    else:
        candidate_parent = configured_candidate_parent.expanduser().resolve()
        candidate_parent.mkdir(parents=True, exist_ok=True)
        candidate_root = candidate_parent / (
            f"run_{uuid.uuid4().hex[:16]}"
        )
        candidate_root.mkdir(parents=False, exist_ok=False)

    configured_development_parent = _env_path(
        "FORMAL_DAILY_DEVELOPMENT_OUTPUT_ROOT"
    )
    if configured_development_parent is None:
        development_parent = Path(
            tempfile.mkdtemp(prefix="baldr_formal_daily_development_")
        )
    else:
        development_parent = configured_development_parent.expanduser().resolve()
        development_parent.mkdir(parents=True, exist_ok=True)
        development_parent = development_parent / (
            f"run_{uuid.uuid4().hex[:16]}"
        )
        development_parent.mkdir(parents=False, exist_ok=False)
    development_root = development_parent / "technical_analysis_development_output"
    return candidate_root, development_root


def _formal_source_path(primary: str, fallback: str) -> Path | None:
    """解析 Formal source path；啟用新 root 時不沿用舊 activation 環境。"""

    configured = _env_path(primary)
    if configured is not None:
        return configured
    # scheduled wrapper 已提供可掃描、可重新驗證的 FORMAL_DAILY_RULE_SOURCE_ROOT。
    # 此時 legacy BALDR_ML_* 可能仍殘留指向舊 clock；即使舊檔尚存在，也必須
    # 交給新 resolver 按目前 source window／consumer 驗證，不可被路徑優先序偷渡。
    if _env_path(_RULE_SOURCE_ROOT_ENV) is not None:
        return None
    return _legacy_formal_path(fallback)


def _legacy_formal_path(fallback: str) -> Path | None:
    """在未啟用新 source root 的相容模式下讀取 legacy path。"""

    # 舊 activation 可能留下 BALDR_* 變數。已不存在的 legacy fallback 不得
    # 壓過目前 repo publication，也不得把隔離 Paper source 指回 D；明確
    # 設定的 FORMAL_DAILY_* 仍原樣交給 consumer，之後若無效則由 consumer
    # 拒絕。
    legacy = _env_path(fallback)
    if legacy is None:
        return None
    try:
        return legacy if legacy.expanduser().resolve().is_file() else None
    except OSError:
        return None


def _formal_path(primary: str, fallback: str) -> Path | None:
    """解析一般 Formal path；新 source bundle 的四項輸入另用隔離解析器。"""

    configured = _env_path(primary)
    if configured is not None:
        return configured
    return _legacy_formal_path(fallback)


def _default_isolated_paper_trade_ledger_path() -> Path:
    """回傳 Paper EOD replay 的 repo 隔離 ledger；不預設指向 D。"""

    return (
        ROOT
        / "output"
        / "paper_execution_eod_replay"
        / "paper_trade_ledger.sqlite"
    ).resolve()


def _default_paper_snapshot_path() -> Path:
    """回傳 preopen writer 建立、Formal consumer 唯讀的 Paper snapshot。"""

    return (
        _output_root(_data_root()).expanduser().resolve()
        / "paper_portfolio"
        / "paper_portfolio.sqlite"
    ).resolve()


def _default_official_calendar_cache_root() -> Path:
    """回傳 isolated Paper task 產出的官方日曆 cache 根目錄。"""

    return (
        ROOT
        / "output"
        / "paper_execution_eod_replay"
        / "calendar_cache"
    ).resolve()


def _default_portfolio_clock_manifest_path() -> Path:
    """9/9 durable cumulative Paper clock; daily Rule clock is separate."""

    return (ROOT / "output" / "formal_daily_publications" / "clock_candidate_archive"
            / "2026-09-09"
            / "d9852b1985ef89f60479110c1ef7974d7a06ea718c7ceddaf777d5284af571e1"
            / "clock" / "manifest.json").resolve()


def _find_current_verified_pit_denominator(
    publication_root: Path,
    *,
    observed: datetime | None,
) -> tuple[Path | None, str]:
    """找當日獨立分母；無法驗證時回傳具體原因而不猜測。"""

    if observed is None:
        return None, "not_attempted_without_runtime_clock"
    target_date = observed.astimezone(timezone.utc).astimezone(TAIPEI).date()
    root = publication_root.expanduser().resolve() / "pit_denominator"
    try:
        candidates = sorted(
            root.glob(target_date.isoformat() + "*/denominator.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError as error:
        return None, f"directory_unavailable:{type(error).__name__}"
    failures: list[str] = []
    for candidate in candidates:
        try:
            payload = validate_prospective_pit_denominator(
                candidate,
                now=observed,
            )
            if payload.get("coverage_start") != target_date.isoformat():
                failures.append(f"{candidate.name}:coverage_start_mismatch")
                continue
            return candidate.resolve(), "verified_current_natural_day"
        except Exception as error:  # noqa: BLE001 - 繼續嘗試下一個 immutable run
            failures.append(f"{candidate.name}:{type(error).__name__}")
    detail = ";".join(failures[:3])
    return None, "missing_verified_current_denominator" + (
        ":" + detail if detail else ""
    )


def _find_current_verified_pit_sidecar(
    publication_root: Path,
    *,
    observed: datetime | None,
) -> tuple[Path | None, str]:
    """找當日已發布且已由 assembler 讀回的 PIT sidecar。"""

    if observed is None:
        return None, "not_attempted_without_runtime_clock"
    target_date = observed.astimezone(timezone.utc).astimezone(TAIPEI).date()
    directory = (
        publication_root.expanduser().resolve()
        / "pit_sector_membership_formal"
        / target_date.isoformat()
    )
    sidecar = directory / "sidecar.json"
    receipt = directory / "receipt.json"
    if not sidecar.is_file() or not receipt.is_file():
        return None, "current_formal_pit_sidecar_or_receipt_missing"
    try:
        read_formal_pit_sector_receipt(
            receipt,
            sidecar_path=sidecar,
            decision_at=observed,
        )
    except Exception as error:  # noqa: BLE001 - consumer remains fail closed
        return None, f"current_formal_pit_sidecar_unverified:{type(error).__name__}"
    return sidecar.resolve(), "verified_current_formal_pit_sidecar"


def _find_current_verified_formal_rule_history(
    publication_root: Path,
    *,
    observed: datetime | None,
) -> tuple[Path | None, str]:
    """找當日 durable Rule manifest，並以正式 loader 讀回驗證。"""

    if observed is None:
        return None, "not_attempted_without_runtime_clock"
    target_date = observed.astimezone(timezone.utc).astimezone(TAIPEI).date()
    manifest = (
        publication_root.expanduser().resolve()
        / "rule_history"
        / target_date.isoformat()
        / "manifest.json"
    )
    if not manifest.is_file():
        return None, "current_formal_rule_history_manifest_missing"
    try:
        from data_module.formal_daily_input_producer import (  # noqa: PLC0415
            _readback_formal_rule,
        )

        result = _readback_formal_rule(manifest, observed.isoformat())
    except Exception as error:  # noqa: BLE001 - current source remains blocked
        return None, f"current_formal_rule_history_unverified:{type(error).__name__}"
    if result.get("formal_ready") is not True:
        return None, "current_formal_rule_history_not_formal_ready"
    return manifest.resolve(), "verified_current_formal_rule_history"


def _find_latest_verified_formal_ledger(
    publication_root: Path,
    *,
    observed: datetime | None,
) -> tuple[Path | None, str]:
    """找最新 immutable causal ledger，並以正式 consumer 讀回。"""

    if observed is None:
        return None, "not_attempted_without_runtime_clock"
    root = publication_root.expanduser().resolve() / "causal_ledger"
    try:
        candidates = list(root.glob("*/manifest.json"))
    except OSError as error:
        return None, f"causal_ledger_publication_root_unreadable:{type(error).__name__}"
    if not candidates:
        return None, "current_formal_ledger_manifest_missing"
    failures: list[str] = []
    validated: list[tuple[date, str, Path]] = []
    cutoff = observed.astimezone(timezone.utc).astimezone(TAIPEI).date()
    for candidate in candidates:
        try:
            from data_module.formal_portfolio_ledger import (  # noqa: PLC0415
                load_formal_portfolio_state_ledger,
            )

            replay = load_formal_portfolio_state_ledger(candidate)
            dates = tuple(date.fromisoformat(item) for item in replay.decision_dates)
            if not dates:
                raise ValueError("ledger has no decision dates")
            if any(item >= cutoff for item in dates):
                raise ValueError("ledger contains a transition at or after cutoff")
            validated.append((max(dates), str(candidate), candidate.resolve()))
        except Exception as error:  # noqa: BLE001 - try the next immutable run
            failures.append(f"{candidate.parent.name}:{type(error).__name__}")
    if not validated:
        detail = ",".join(failures[:3])
        return None, "current_formal_ledger_unverified" + (
            ":" + detail if detail else ""
        )
    _, _, selected = max(validated, key=lambda item: (item[0], item[1]))
    return selected, "verified_current_formal_ledger"


def _build_paths(
    *,
    source_paths: dict[str, Path],
    publication_root: Path,
    observed: datetime | None = None,
    runtime_config: Mapping[str, object] | None = None,
    daily_rule_lineage: Mapping[str, object] | None = None,
) -> DailyFormalInputPaths:
    data_root = _data_root().expanduser().resolve()
    output_root = _output_root(data_root).expanduser().resolve()
    candidate_root, development_root = _candidate_roots()
    formal_sector_path = _formal_source_path(
        "FORMAL_DAILY_FORMAL_SECTOR_PATH",
        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
    )
    formal_rule_history_path = _formal_source_path(
        "FORMAL_DAILY_FORMAL_RULE_HISTORY_PATH",
        "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
    )
    formal_ledger_path = _formal_source_path(
        "FORMAL_DAILY_FORMAL_LEDGER_PATH",
        "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
    )
    runtime_publications = (
        runtime_config.get("publication_paths")
        if isinstance(runtime_config, Mapping)
        else None
    )
    runtime_publications = (
        runtime_publications if isinstance(runtime_publications, Mapping) else {}
    )
    # The active date-scoped config carries exact Rule/PIT publication targets.
    # They are allowed to be absent before the producer runs, but they must not
    # be replaced by a latest-file search.  The causal ledger is intentionally
    # left unset until this invocation emits its hash-scoped run directory.
    if runtime_config is not None:
        if formal_rule_history_path is None:
            value = runtime_publications.get("rule_history_manifest")
            if isinstance(value, str) and value.strip():
                formal_rule_history_path = Path(value).expanduser().resolve()
        if formal_sector_path is None:
            value = runtime_publications.get("pit_sidecar")
            if isinstance(value, str) and value.strip():
                formal_sector_path = Path(value).expanduser().resolve()
    pit_expected_universe_path = _formal_source_path(
        "FORMAL_DAILY_PIT_EXPECTED_UNIVERSE",
        "BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH",
    )
    if observed is not None and runtime_config is None:
        if pit_expected_universe_path is None:
            pit_expected_universe_path, _ = _find_current_verified_pit_denominator(
                publication_root,
                observed=observed,
            )
        if formal_sector_path is None:
            formal_sector_path, _ = _find_current_verified_pit_sidecar(
                publication_root,
                observed=observed,
            )
        if formal_rule_history_path is None:
            formal_rule_history_path, _ = _find_current_verified_formal_rule_history(
                publication_root,
                observed=observed,
            )
        if formal_ledger_path is None:
            formal_ledger_path, _ = _find_latest_verified_formal_ledger(
                publication_root,
                observed=observed,
            )
    configured_paper_trade_ledger = _formal_path(
        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
        "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH",
    )
    paper_trade_ledger = (
        configured_paper_trade_ledger
        or _default_isolated_paper_trade_ledger_path()
    )
    paper_execution_receipt_root = _env_path("FORMAL_DAILY_PAPER_RECEIPT_ROOT")
    if paper_execution_receipt_root is None:
        receipt_root_value = runtime_publications.get("paper_eod_receipt_root")
        if isinstance(receipt_root_value, str) and receipt_root_value.strip():
            paper_execution_receipt_root = Path(receipt_root_value).expanduser().resolve()
    common_identity_path: Path | None = None
    identity_value = runtime_publications.get("common_identity_manifest")
    if isinstance(identity_value, str) and identity_value.strip():
        common_identity_path = Path(identity_value).expanduser().resolve()
    receipt_paths: dict[str, Path] = {}
    for environment_name, explicit_name in (
        (
            "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
            "FORMAL_DAILY_FORMAL_LEDGER_RECEIPT_PATH",
        ),
        (
            "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
            "FORMAL_DAILY_FORMAL_RULE_HISTORY_RECEIPT_PATH",
        ),
        (
            "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
            "FORMAL_DAILY_FORMAL_SECTOR_RECEIPT_PATH",
        ),
    ):
        explicit_receipt = _env_path(explicit_name)
        if explicit_receipt is not None:
            receipt_paths[environment_name] = explicit_receipt.expanduser().resolve()
    # Rule/PIT publishers use a deterministic sibling receipt next to the
    # exact configured manifest.  This is a contract path from runtime config,
    # not a directory scan; if the file is not there the identity producer
    # remains blocked until the publisher has completed.
    if formal_rule_history_path is not None and "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH" not in receipt_paths:
        receipt_paths[
            "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"
        ] = formal_rule_history_path.parent / "receipt.json"
    if formal_sector_path is not None and "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH" not in receipt_paths:
        receipt_paths[
            "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"
        ] = formal_sector_path.parent / "receipt.json"
    return DailyFormalInputPaths(
        output_root=candidate_root,
        development_output_root=development_root,
        market_db=(
            _env_path("FORMAL_DAILY_MARKET_DB")
            or data_root / "sqlite" / "twstock.db"
        ),
        clock_manifest=source_paths.get("FORMAL_DAILY_CLOCK_MANIFEST"),
        portfolio_clock_manifest=(
            _env_path("FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST")
            or _default_portfolio_clock_manifest_path()
        ),
        universe_symbols=source_paths.get("FORMAL_DAILY_UNIVERSE_SYMBOLS"),
        owner_acceptance=source_paths.get("FORMAL_DAILY_OWNER_ACCEPTANCE"),
        formal_ledger_path=formal_ledger_path,
        formal_rule_history_path=formal_rule_history_path,
        formal_sector_path=formal_sector_path,
        paper_snapshot_db_path=_formal_path(
            "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
            "BALDR_ML_PAPER_PORTFOLIO_SNAPSHOT_DB_PATH",
        )
        or _default_paper_snapshot_path(),
        paper_trade_ledger_db_path=paper_trade_ledger,
        paper_execution_receipt_root=paper_execution_receipt_root,
        publication_root=publication_root,
        pit_expected_universe_path=pit_expected_universe_path,
        pit_history_coverage_start=_env_date(
            "FORMAL_DAILY_PIT_HISTORY_COVERAGE_START"
        ),
        pit_preopen_archive_root=_env_path(
            "FORMAL_DAILY_PIT_PREOPEN_ARCHIVE_ROOT"
        ),
        official_calendar_cache_path=_env_path(
            "FORMAL_DAILY_CALENDAR_CACHE_ROOT"
        )
        or _default_official_calendar_cache_root(),
        official_temporary_closure_path=_env_path(
            "FORMAL_DAILY_CALENDAR_CACHE_ROOT"
        )
        or _default_official_calendar_cache_root(),
        common_identity_manifest_path=common_identity_path,
        formal_source_receipt_paths=receipt_paths or None,
        daily_rule_lineage=daily_rule_lineage,
    )


def _common_status(*, observed_at: str, publication_root: Path) -> dict[str, object]:
    return {
        "schema_version": DAILY_FORMAL_INPUT_PRODUCER_SCHEMA_VERSION,
        "producer": "scripts.scheduled.run_formal_input_producer_daily",
        "producer_version": "scheduled-formal-input-wrapper.v1",
        "observed_at": observed_at,
        "publication_root": str(publication_root),
        "formal_ready_input_count": 0,
        "formal_consumer_compatible_count": 0,
        "machine_candidate_input_count": 0,
        "human_review_required": False,
        "owner_reviewer_required": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "writes_market_database": False,
        "writes_formal_controlled_paths": False,
        "training_started": False,
        "broker_execution": False,
        "historical_backfill_claimed": False,
        "secret_values_emitted": False,
    }


def _write_status(path: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(encoded, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _runtime_projection() -> dict[str, object]:
    """保存可重驗的 process invocation；不保存 secret 或完整環境。"""

    entrypoint = Path(__file__).resolve()
    python_executable = Path(sys.executable).expanduser().resolve()
    working_directory = Path.cwd().resolve()
    arguments = [str(value) for value in sys.argv[1:]]
    return {
        "entrypoint": str(entrypoint),
        "python_executable": str(python_executable),
        "working_directory": str(working_directory),
        "arguments": arguments,
        "command": [str(python_executable), str(entrypoint), *arguments],
        "wrapper_command": [
            "cmd.exe",
            "/d",
            "/c",
            str(ROOT / "scripts" / "scheduled" / "run_formal_input_producer_daily.cmd"),
        ],
    }


def _validate_rule_source_predecessor(
    runtime_config: Mapping[str, object] | None,
    *,
    observed: datetime,
) -> dict[str, object] | None:
    """確認 21:25 consumer 確實接到同日 Rule producer predecessor。"""

    if runtime_config is None:
        return None
    role_contract = runtime_config.get("role_contract")
    if not isinstance(role_contract, Mapping):
        raise FormalRuntimeConfigError("formal_input_role_contract_missing")
    dependency = role_contract.get("rule_source_predecessor")
    if not isinstance(dependency, Mapping):
        raise FormalRuntimeConfigError("rule_source_predecessor_contract_missing")
    status_path_value = dependency.get("required_status_path")
    if not isinstance(status_path_value, str) or not status_path_value.strip():
        raise FormalRuntimeConfigError("rule_source_predecessor_status_path_missing")
    status_path = Path(status_path_value).expanduser().resolve()
    try:
        # Parse and hash the exact same immutable byte snapshot.  Reading text
        # and then hashing the path separately could accept a status payload
        # from one scheduler attempt while reporting the hash of a later one.
        status_bytes = status_path.read_bytes()
        payload = json.loads(status_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalRuntimeConfigError(
            f"rule_source_predecessor_status_unreadable:{type(error).__name__}"
        ) from error
    if not isinstance(payload, Mapping):
        raise FormalRuntimeConfigError("rule_source_predecessor_status_invalid")
    local_date = observed.astimezone(TAIPEI).date().isoformat()
    if payload.get("taipei_date") != local_date:
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_status_natural_day_mismatch"
        )
    raw_exit_code = payload.get("exit_code")
    if isinstance(raw_exit_code, bool):
        raise FormalRuntimeConfigError("rule_source_predecessor_exit_code_invalid")
    if isinstance(raw_exit_code, int):
        exit_code = raw_exit_code
    elif isinstance(raw_exit_code, str):
        try:
            exit_code = int(raw_exit_code)
        except ValueError as error:
            raise FormalRuntimeConfigError(
                "rule_source_predecessor_exit_code_invalid"
            ) from error
    else:
        raise FormalRuntimeConfigError("rule_source_predecessor_exit_code_invalid")
    if exit_code != dependency.get("required_exit_code", 0):
        raise FormalRuntimeConfigError("rule_source_predecessor_exit_code_not_zero")
    accepted = dependency.get("accepted_statuses")
    if not isinstance(accepted, list) or payload.get("status") not in accepted:
        raise FormalRuntimeConfigError("rule_source_predecessor_status_not_accepted")
    bundle_root = payload.get("bundle_root")
    if not isinstance(bundle_root, str) or not bundle_root.strip():
        raise FormalRuntimeConfigError("rule_source_predecessor_bundle_missing")
    bundle_path = Path(bundle_root).expanduser().resolve()
    configured_root_value = dependency.get("source_root")
    configured_root = (
        Path(configured_root_value).expanduser().resolve()
        if isinstance(configured_root_value, str) and configured_root_value.strip()
        else _env_path(_RULE_SOURCE_ROOT_ENV)
    )
    if configured_root is not None:
        try:
            bundle_path.relative_to(configured_root)
        except ValueError as error:
            raise FormalRuntimeConfigError(
                "rule_source_predecessor_bundle_outside_configured_root"
            ) from error
    source_paths: dict[str, str] = {}
    for name, field in (
        ("FORMAL_DAILY_CLOCK_MANIFEST", "clock_manifest"),
        ("FORMAL_DAILY_UNIVERSE_SYMBOLS", "universe_symbols"),
        ("FORMAL_DAILY_OWNER_ACCEPTANCE", "owner_acceptance"),
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise FormalRuntimeConfigError(
                f"rule_source_predecessor_{field}_missing"
            )
        path = Path(value).expanduser().resolve()
        try:
            path.relative_to(bundle_path)
        except ValueError as error:
            raise FormalRuntimeConfigError(
                f"rule_source_predecessor_{field}_outside_bundle"
            ) from error
        if not path.is_file():
            raise FormalRuntimeConfigError(
                f"rule_source_predecessor_{field}_file_missing"
            )
        source_paths[name] = str(path)
    market_db = _env_path("FORMAL_DAILY_MARKET_DB")
    if market_db is None:
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_market_db_environment_missing"
        )
    try:
        consumer_validation = _validate_exact_rule_source_bundle(
            bundle_path,
            market_db=market_db,
            observed=observed,
        )
    except Exception as error:  # noqa: BLE001 - scheduler boundary is fail closed
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_consumer_rejected:"
            f"{_rule_source_error_detail(error)}"
        ) from error
    consumer_source_hash = consumer_validation.get("source_window_hash")
    status_source_hash = payload.get("source_window_hash")
    if not isinstance(consumer_source_hash, str):
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_consumer_source_window_hash_missing"
        )
    if status_source_hash != consumer_source_hash:
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_source_window_hash_mismatch"
        )
    return {
        "task": dependency.get("task"),
        "status_path": str(status_path),
        "status_file_hash": "sha256:" + hashlib.sha256(status_bytes).hexdigest(),
        "status": payload.get("status"),
        "exit_code": exit_code,
        "taipei_date": payload.get("taipei_date"),
        "bundle_root": str(bundle_path),
        "source_paths": source_paths,
        "source_window_hash": consumer_source_hash,
        "source_window_hash_verified_against_market_db": True,
        "source_window_persisted": consumer_validation.get(
            "source_window_persisted"
        )
        is True,
        "source_window_path": consumer_validation.get("source_window_path"),
        "consumer_validation_status": consumer_validation.get("status"),
    }


def _daily_rule_lineage_from_predecessor(
    predecessor: Mapping[str, object] | None,
    *,
    observed: datetime,
) -> dict[str, object] | None:
    """由已驗證 predecessor 的 exact clock／window 建立 daily Rule lineage。"""

    if predecessor is None:
        return None
    source_paths = predecessor.get("source_paths")
    if not isinstance(source_paths, Mapping):
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_lineage_paths_missing"
        )
    clock_value = source_paths.get("FORMAL_DAILY_CLOCK_MANIFEST")
    if not isinstance(clock_value, str) or not clock_value.strip():
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_lineage_clock_missing"
        )
    clock_path = Path(clock_value).expanduser().resolve()
    try:
        clock = load_clock_manifest_for_capture(clock_path, now=observed)
    except Exception as error:  # noqa: BLE001 - wrapper remains fail closed
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_lineage_clock_rejected:"
            + _rule_source_error_detail(error)
        ) from error
    source_window_hash = predecessor.get("source_window_hash")
    if not isinstance(source_window_hash, str) or not source_window_hash.strip():
        raise FormalRuntimeConfigError(
            "rule_source_predecessor_lineage_source_window_missing"
        )
    return {
        "clock_id": clock.clock_id,
        "clock_manifest_hash": clock.manifest_hash,
        "activation_trading_day": clock.activation_trading_day.isoformat(),
        "universe_hash": clock.payload.get("universe_hash"),
        "source_window_hash": source_window_hash,
        "policy_hash": clock.payload.get("policy_hash"),
        "source_bundle_path": predecessor.get("bundle_root"),
        "source_bundle_status_file_hash": predecessor.get("status_file_hash"),
        "source_window_verified_against_market_db": predecessor.get(
            "source_window_hash_verified_against_market_db"
        )
        is True,
        "source_window_persisted": predecessor.get("source_window_persisted")
        is True,
        "source_window_path": predecessor.get("source_window_path"),
    }


def _append_attempt_log(path: Path, payload: dict[str, object]) -> None:
    """以 append-only JSONL 保存每次排程結果與 exit code。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def run_from_environment(
    *,
    publication_root: Path,
    status_root: Path,
) -> tuple[dict[str, object], int]:
    observed = datetime.now(timezone.utc)
    observed_at = observed.isoformat()
    runtime_config: dict[str, object] | None = None
    runtime_config_error: str | None = None
    try:
        runtime_config = load_optional_formal_runtime_config(
            role="formal_input_wrapper",
            observed=observed,
        )
    except FormalRuntimeConfigError as error:
        runtime_config_error = str(error)
    source_paths: dict[str, Path] = {}
    missing: list[str] = list(_REQUIRED_SOURCE_ENV)
    discovery_reason: str | None = "not_attempted"
    status_path = status_root / "latest_status.json"
    attempt_log_path = status_root / "attempts.jsonl"
    runtime = _runtime_projection()
    runtime["formal_runtime_config"] = (
        runtime_config
        if runtime_config is not None
        else {
            "status": "absent" if runtime_config_error is None else "invalid",
            "environment_variable": FORMAL_RUNTIME_CONFIG_ENV,
            "error": runtime_config_error,
        }
    )
    rule_source_predecessor: dict[str, object] | None = None
    try:
        if runtime_config_error is not None:
            raise FormalRuntimeConfigError(runtime_config_error)
        if (
            runtime_config is not None
            and runtime_config.get("activation_status") != "active"
        ):
            raise FormalRuntimeConfigError(
                "runtime_config_waiting_for_activation:"
                f"{runtime_config.get('activation_trading_day')}"
            )
        rule_source_predecessor = _validate_rule_source_predecessor(
            runtime_config,
            observed=observed,
        )
        if rule_source_predecessor is not None:
            raw_source_paths = rule_source_predecessor.get("source_paths")
            if not isinstance(raw_source_paths, Mapping):
                raise FormalRuntimeConfigError(
                    "rule_source_predecessor_source_paths_missing"
                )
            source_paths = {
                name: Path(value).expanduser().resolve()
                for name, value in raw_source_paths.items()
                if name in _REQUIRED_SOURCE_ENV and isinstance(value, str)
            }
            missing = [
                name for name in _REQUIRED_SOURCE_ENV if name not in source_paths
            ]
            if missing:
                raise FormalRuntimeConfigError(
                    "rule_source_predecessor_source_paths_partial"
                )
            discovery_reason = "predecessor_exact_status_paths"
        else:
            source_paths, missing, discovery_reason = _resolve_required_source_paths(
                observed=observed
            )
        daily_rule_lineage = _daily_rule_lineage_from_predecessor(
            rule_source_predecessor,
            observed=observed,
        )
        paths = _build_paths(
            source_paths=source_paths,
            publication_root=publication_root,
            observed=observed,
            runtime_config=runtime_config,
            daily_rule_lineage=daily_rule_lineage,
        )
        result = run_daily_formal_input_producer(paths)
        status = {
            **_common_status(
                observed_at=observed_at,
                publication_root=publication_root,
            ),
            **result,
            "scheduled_entrypoint": "scripts.scheduled.run_formal_input_producer_daily",
            "status_path": str(status_path),
            "candidate_output_root": str(paths.output_root.expanduser().resolve()),
            "development_output_root": str(
                paths.development_output_root.expanduser().resolve()
            ),
            "publication_root": str(publication_root),
            "scheduled_source_configuration": {
                "rule_source_resolution": _rule_source_configuration(
                    source_paths, missing, discovery_reason
                ),
                "missing_rule_source_environment": list(missing),
                "missing_rule_sources_do_not_block_pit_capture": True,
                "paper_trade_ledger_resolution": (
                    "environment"
                    if _formal_path(
                        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
                        "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH",
                    )
                    is not None
                    else "isolated_repository_default"
                ),
                "paper_trade_ledger_path": str(
                    paths.paper_trade_ledger_db_path
                    if paths.paper_trade_ledger_db_path is not None
                    else _default_isolated_paper_trade_ledger_path()
                ),
                "paper_snapshot_resolution": (
                    "environment"
                    if _formal_path(
                        "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
                        "BALDR_ML_PAPER_PORTFOLIO_SNAPSHOT_DB_PATH",
                    )
                    is not None
                    else "data_root_output_default"
                ),
                "paper_snapshot_db_path": str(
                    paths.paper_snapshot_db_path
                    if paths.paper_snapshot_db_path is not None
                    else _default_paper_snapshot_path()
                ),
                "paper_snapshot_read_mode": "sqlite_mode_ro_query_only",
                "official_calendar_cache_path": str(
                    paths.official_calendar_cache_path
                    if paths.official_calendar_cache_path is not None
                    else _default_official_calendar_cache_root()
                ),
                "pit_expected_universe_resolution": (
                    "environment"
                    if _formal_path(
                        "FORMAL_DAILY_PIT_EXPECTED_UNIVERSE",
                        "BALDR_ML_PIT_EXPECTED_UNIVERSE_PATH",
                    )
                    is not None
                    else (
                        "publication_root_current_day_auto_discovery"
                        if paths.pit_expected_universe_path is not None
                        else "missing_current_day_verified_denominator"
                    )
                ),
            "formal_pit_sidecar_resolution": (
                    "environment"
                    if _formal_path(
                        "FORMAL_DAILY_FORMAL_SECTOR_PATH",
                        "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
                    )
                    is not None
                    else (
                        "publication_root_current_day_auto_discovery"
                        if paths.formal_sector_path is not None
                        else "missing_current_day_verified_sidecar"
                    )
                ),
                "rule_source_predecessor": rule_source_predecessor,
            },
            "schedule_exit_policy": (
                "zero_only_for_formal_inputs_machine_verified;"
                "candidate_only_or_blocked_returns_2"
            ),
            **runtime,
            "attempt_log_path": str(attempt_log_path),
        }
    except Exception as error:  # noqa: BLE001 - scheduled boundary emits a blocker
        status = {
            **_common_status(
                observed_at=observed_at,
                publication_root=publication_root,
            ),
            "status": "blocked",
            "blockers": [
                f"scheduled_formal_input_producer_failed:{type(error).__name__}:{str(error).splitlines()[0][:220]}"
            ],
            "inputs": {},
            "status_path": str(status_path),
            "scheduled_source_configuration": {
                "rule_source_resolution": _rule_source_configuration(
                    source_paths, missing, discovery_reason
                ),
                "missing_rule_source_environment": list(missing),
                "missing_rule_sources_do_not_block_pit_capture": True,
                "paper_trade_ledger_resolution": (
                    "environment"
                    if _formal_path(
                        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
                        "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH",
                    )
                    is not None
                    else "isolated_repository_default"
                ),
                "paper_trade_ledger_path": str(
                    _formal_path(
                        "FORMAL_DAILY_PAPER_TRADE_LEDGER_DB",
                        "BALDR_ML_PAPER_TRADE_LEDGER_DB_PATH",
                    )
                    or _default_isolated_paper_trade_ledger_path()
                ),
                "paper_snapshot_resolution": (
                    "environment"
                    if _formal_path(
                        "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
                        "BALDR_ML_PAPER_PORTFOLIO_SNAPSHOT_DB_PATH",
                    )
                    is not None
                    else "data_root_output_default"
                ),
                "paper_snapshot_db_path": str(
                    _formal_path(
                        "FORMAL_DAILY_PAPER_SNAPSHOT_DB",
                        "BALDR_ML_PAPER_PORTFOLIO_SNAPSHOT_DB_PATH",
                    )
                    or _default_paper_snapshot_path()
                ),
                "paper_snapshot_read_mode": "sqlite_mode_ro_query_only",
                "official_calendar_cache_path": str(
                    _env_path("FORMAL_DAILY_CALENDAR_CACHE_ROOT")
                    or _default_official_calendar_cache_root()
                ),
                "pit_expected_universe_resolution": "unavailable_due_to_runner_error",
                "formal_pit_sidecar_resolution": "unavailable_due_to_runner_error",
                "rule_source_predecessor": rule_source_predecessor,
            },
            "schedule_exit_policy": (
                "zero_only_for_formal_inputs_machine_verified;"
                "candidate_only_or_blocked_returns_2"
            ),
            **runtime,
            "attempt_log_path": str(attempt_log_path),
        }
    exit_code = 0 if status.get("status") == "formal_inputs_machine_verified" else 2
    status["exit_code"] = exit_code
    _write_status(status_path, status)
    status_observed_at = status.get("observed_at")
    if not isinstance(status_observed_at, str) or not status_observed_at:
        status_observed_at = observed_at
    attempt = {
        "schema_version": _SCHEDULED_ATTEMPT_LOG_SCHEMA_VERSION,
        "observed_at": status_observed_at,
        "wrapper_started_at": observed_at,
        "status_path": str(status_path),
        "attempt_log_path": str(attempt_log_path),
        "status": status.get("status"),
        "exit_code": exit_code,
        "blockers": status.get("blockers", []),
        "formal_ready_input_count": status.get("formal_ready_input_count", 0),
        "formal_consumer_compatible_count": status.get(
            "formal_consumer_compatible_count", 0
        ),
        "machine_candidate_input_count": status.get(
            "machine_candidate_input_count", 0
        ),
        **runtime,
    }
    try:
        _append_attempt_log(attempt_log_path, attempt)
    except OSError as error:
        # status／receipt 仍可供排錯，但無法驗證的 scheduler run 不得表示為
        # 成功的 operational attempt。
        status["observability_blocker"] = (
            f"scheduled_attempt_log_write_failed:{type(error).__name__}:{error}"
        )
        status["exit_code"] = 2
        _write_status(status_path, status)
        exit_code = 2
    return status, exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    publication_root = _publication_root(args.publication_root)
    try:
        status_root = _status_root(publication_root, args.status_root)
    except ValueError as error:
        observed_at = datetime.now(timezone.utc).isoformat()
        status_root = ROOT / "output" / "formal_daily_publications" / "scheduler"
        status = _common_status(
            observed_at=observed_at,
            publication_root=publication_root,
        )
        status.update(
            {
                "status": "blocked",
                "blockers": [f"scheduled_status_path_rejected:{error}"],
                "inputs": {},
            }
        )
        _write_status(status_root / "latest_status.json", status)
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    status, exit_code = run_from_environment(
        publication_root=publication_root,
        status_root=status_root,
    )
    print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
