"""唯讀盤點日常 Formal 三項來源的自然時間與排程可觀測性。

這個模組只讀取已持久化的 status、receipt、PIT archive 與 readiness report，
把「尚未到自然窗口」、「排程未被觀測」、「來源候選存在但仍非 Formal」分開
投影。它不會抓取 HTTP、不會修改來源 SQLite、不會建立 Formal input，也不會
啟動交易、broker 或訓練。測試可以注入 ``now``；公開 CLI 不提供 clock override。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
PACIFIC = ZoneInfo("America/Los_Angeles")
PIT_CUTOFF = time(8, 30)
RULE_SESSION_OPEN = time(9, 0)
RULE_SESSION_CLOSE = time(13, 30)
PAPER_EOD_AVAILABLE = time(15, 0)
SCHEMA_VERSION = "formal-operational-readiness.v1"
AUDITOR_VERSION = "machine:formal-operational-readiness-auditor.v1"

PIT_CAPTURE_STATUS_RELATIVE = Path(
    "scheduler/pit_preopen_capture/latest_status.json"
)
PIT_SIDECAR_STATUS_RELATIVE = Path("scheduler/pit_sidecar/latest_status.json")
FORMAL_STATUS_RELATIVE = Path("scheduler/latest_status.json")

SCHEDULE_CONTRACTS: tuple[dict[str, str], ...] = (
    {
        "key": "pit_preopen_capture",
        "task_name": "baldr-pit-sector-membership-preopen-capture-daily",
        "wrapper": "scripts/scheduled/run_pit_sector_membership_preopen_capture.cmd",
        "taipei_time": "07:00",
        "purpose": "capture current-day official PIT before Taipei 08:30",
    },
    {
        "key": "pit_postcutoff_sidecar",
        "task_name": "baldr-formal-pit-sidecar-postcutoff-daily",
        "wrapper": "scripts/scheduled/run_formal_pit_sidecar_postcutoff.cmd",
        "taipei_time": "09:00",
        "purpose": "read the preopen archive after Taipei 08:30",
    },
    {
        "key": "formal_input_producer",
        "task_name": "baldr-formal-input-producer-daily",
        "wrapper": "scripts/scheduled/run_formal_input_producer_daily.cmd",
        "taipei_time": "12:25",
        "purpose": "run the bounded Rule/ledger/PIT formal handoff",
    },
    {
        "key": "paper_eod_replay",
        "task_name": "baldr-paper-execution-eod-replay-daily",
        "wrapper": "scripts/scheduled/run_paper_execution_daily_isolated.cmd",
        "taipei_time": "15:05",
        "purpose": "consume delayed EOD Paper execution source",
    },
)

_REGISTRATION_CONDITION_KEYS = (
    "logon_mode",
    "run_only_if_user_is_logged_on",
    "stop_if_the_computer_switches_to_battery_power",
    "start_the_task_only_if_the_computer_is_on_ac_power",
    "power_management",
    "execution_time_limit",
    "multiple_instances_policy",
    "last_result",
    "last_run_time",
    "next_run_time",
)


class FormalOperationalReadinessError(ValueError):
    """輸入封套無法以唯讀方式建立可稽核報告。"""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(value: object) -> str:
    """回傳內容 hash；呼叫端應先移除既有 hash 欄位。"""

    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FormalOperationalReadinessError(
            f"{field_name} must be an aware ISO-8601 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise FormalOperationalReadinessError(
            f"{field_name} must be an aware ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FormalOperationalReadinessError(
            f"{field_name} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _read_json_mapping(path: Path) -> Mapping[str, object]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalOperationalReadinessError(
            f"JSON artifact is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise FormalOperationalReadinessError(
            f"JSON artifact must be an object: {path}"
        )
    return payload


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _unique(items: Sequence[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in result:
            result.append(value)
    return result


def _string_items(value: object) -> list[str]:
    """將 JSON 的 blocker 陣列安全收斂成字串；錯誤型別不被當成空陣列。"""

    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _lower_text(value: object) -> str:
    return value.casefold() if isinstance(value, str) else ""


def _is_unobserved_task_time(value: str) -> bool:
    return (
        not value
        or value in {"never", "n/a", "not run", "disabled"}
        or "1999" in value
    )


def _registration_operational_blockers(
    registration: Mapping[str, object],
    schedule: Sequence[Mapping[str, object]],
) -> list[str]:
    """投影登入、電源與漏跑風險；任何未觀測都保持 blocker。"""

    records_value = registration.get("tasks")
    if not isinstance(records_value, list):
        return []
    by_name: dict[str, Mapping[str, object]] = {
        str(item.get("task_name")): item
        for item in records_value
        if isinstance(item, Mapping) and isinstance(item.get("task_name"), str)
    }
    blockers: list[str] = []
    for contract in schedule:
        task_name = contract.get("task_name")
        if not isinstance(task_name, str):
            continue
        task = by_name.get(task_name)
        if task is None:
            continue
        summary_value = task.get("summary")
        summary = summary_value if isinstance(summary_value, Mapping) else {}
        logon = _lower_text(summary.get("logon_mode"))
        if "interactive" in logon and "background" not in logon:
            blockers.append(f"scheduler_task_requires_interactive_login:{task_name}")
        login_only = _lower_text(summary.get("run_only_if_user_is_logged_on"))
        if login_only in {"yes", "true", "enabled"}:
            blockers.append(f"scheduler_task_requires_logged_on_user:{task_name}")
        power = _lower_text(summary.get("power_management"))
        battery_value = _lower_text(
            summary.get("stop_if_the_computer_switches_to_battery_power")
        )
        ac_value = _lower_text(
            summary.get("start_the_task_only_if_the_computer_is_on_ac_power")
        )
        battery_restricted = (
            "battery" in power
            or battery_value in {"yes", "true", "enabled"}
            or ac_value in {"yes", "true", "enabled"}
        )
        if battery_restricted:
            blockers.append(f"scheduler_task_battery_power_restricted:{task_name}")

        last_run = _lower_text(summary.get("last_run_time"))
        if _is_unobserved_task_time(last_run):
            blockers.append(f"scheduler_task_never_successfully_run:{task_name}")

        if contract.get("due_state") != "due":
            continue
        last_result = _lower_text(summary.get("last_result"))
        if not last_result:
            blockers.append(f"scheduler_task_due_last_result_unobserved:{task_name}")
        if _is_unobserved_task_time(last_run):
            blockers.append(f"scheduler_task_due_last_run_unobserved:{task_name}")
        else:
            # schtasks 的日期格式受系統 locale 影響；未在此轉換就不把舊
            # timestamp 誤判為本日成功，保留可追查的 freshness blocker。
            blockers.append(f"scheduler_task_due_last_run_freshness_unverified:{task_name}")
    return blockers


def _phase(local_time: time) -> str:
    plain = local_time.replace(tzinfo=None)
    if plain < PIT_CUTOFF:
        return "before_pit_cutoff"
    if plain < RULE_SESSION_OPEN:
        return "pit_postcutoff_before_rule_open"
    if plain <= RULE_SESSION_CLOSE:
        return "rule_session"
    if plain < PAPER_EOD_AVAILABLE:
        return "between_rule_close_and_paper_eod"
    return "paper_eod_or_later"


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(int(hour_text), int(minute_text))


def inspect_schedule_contract(
    *,
    target_date: date,
    now: datetime,
) -> list[dict[str, object]]:
    """以台北 target date 計算排程對應的 host local time。

    這裡只驗證版本化 wrapper 的時間契約，不把契約文字當成 OS 已註冊證據；
    OS registration 必須另提供 ``inspect_scheduled_task_registration`` 的唯讀
    JSON，否則報告會明示 registration 未觀測。
    """

    result: list[dict[str, object]] = []
    for contract in SCHEDULE_CONTRACTS:
        taipei_time = _parse_hhmm(contract["taipei_time"])
        taipei_at = datetime.combine(target_date, taipei_time, tzinfo=TAIPEI)
        host_at = taipei_at.astimezone(PACIFIC)
        result.append(
            {
                **contract,
                "target_taipei_date": target_date.isoformat(),
                "expected_taipei_at": taipei_at.isoformat(),
                "expected_host_at": host_at.isoformat(),
                "due_state": "due" if now >= taipei_at.astimezone(timezone.utc) else "waiting",
                "timezone_contract": "Asia/Taipei decision windows; host trigger is DST-mapped",
            }
        )
    return result


def inspect_persisted_status(
    path: Path,
    *,
    target_date: date,
    now: datetime,
    lane: str,
) -> dict[str, object]:
    """讀取單一 status，沒有 timestamp 時保持 invalid，不猜 mtime。"""

    resolved = path.expanduser().resolve()
    base: dict[str, object] = {
        "lane": lane,
        "path": str(resolved),
        "target_taipei_date": target_date.isoformat(),
        "state": "missing",
        "status": None,
        "observed_at": None,
        "observed_taipei_date": None,
        "blockers": [],
    }
    if not resolved.is_file():
        base["blockers"] = ["persistent_status_missing"]
        return base
    try:
        payload = _read_json_mapping(resolved)
        observed = _aware_datetime(
            payload.get("observed_at") or payload.get("decision_at"),
            field_name=f"{lane}.observed_at",
        )
    except (FormalOperationalReadinessError, OSError, TypeError, ValueError) as error:
        base["state"] = "invalid"
        base["blockers"] = [
            f"persistent_status_invalid:{type(error).__name__}"
        ]
        return base
    observed_taipei = observed.astimezone(TAIPEI)
    blockers: list[str] = []
    if observed > now:
        blockers.append("persistent_status_observed_in_future")
    if observed_taipei.date() != target_date:
        blockers.append(
            "persistent_status_for_different_natural_day:"
            + observed_taipei.date().isoformat()
        )
    status_text = _text(payload.get("status"))
    if status_text is None:
        blockers.append("persistent_status_value_missing")
    reported_blockers = payload.get("blockers")
    if isinstance(reported_blockers, list):
        # Preserve producer diagnostics as data; timestamp validity remains a
        # separate concern so a current blocked run is still auditable.
        base["reported_blockers"] = [
            str(item) for item in reported_blockers if isinstance(item, str)
        ]
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        base["exit_code"] = exit_code
    base.update(
        {
            "state": "current" if not blockers else "stale_or_invalid",
            "status": status_text,
            "observed_at": observed.isoformat(),
            "observed_taipei_date": observed_taipei.date().isoformat(),
            "payload_hash": payload_hash(payload),
            "blockers": blockers,
        }
    )
    return base


def _safe_relative_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise FormalOperationalReadinessError("archive relative path is missing")
    candidate = (root / Path(relative)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise FormalOperationalReadinessError(
            "archive file escapes archive root"
        ) from error
    return candidate


def inspect_latest_pit_archive(
    archive_root: Path,
    *,
    target_date: date,
    now: datetime,
) -> dict[str, object]:
    """只接受可重算 archive file hashes 的 current-day candidate。"""

    root = archive_root.expanduser().resolve() / target_date.isoformat()
    base: dict[str, object] = {
        "root": str(root),
        "state": "missing",
        "archive_manifest_path": None,
        "archive_manifest_file_hash": None,
        "archive_id": None,
        "captured_at": None,
        "archived_at": None,
        "effective_from": None,
        "row_count": None,
        "candidate_only": None,
        "formal_consumer_compatible": None,
        "consumer_verified_at_capture": None,
        "source_ids": [],
        "blockers": [],
    }
    if not root.is_dir():
        base["blockers"] = ["pit_archive_for_current_natural_day_missing"]
        return base
    manifests = sorted(
        root.glob("*/archive_manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    failures: list[str] = []
    for manifest_path in manifests:
        try:
            payload = _read_json_mapping(manifest_path)
            captured = _aware_datetime(
                payload.get("captured_at"),
                field_name="pit_archive.captured_at",
            )
            archived = _aware_datetime(
                payload.get("archived_at"),
                field_name="pit_archive.archived_at",
            )
            if captured > now or archived > now:
                raise FormalOperationalReadinessError(
                    "pit archive timestamp is in the future"
                )
            effective_from = _text(payload.get("effective_from"))
            if effective_from != captured.astimezone(TAIPEI).date().isoformat():
                raise FormalOperationalReadinessError(
                    "pit archive effective_from does not match Taipei capture date"
                )
            if payload.get("candidate_only") is not True:
                raise FormalOperationalReadinessError(
                    "pit archive candidate_only must be true"
                )
            if payload.get("formal_consumer_compatible") is not False:
                raise FormalOperationalReadinessError(
                    "pit archive formal_consumer_compatible must be false"
                )
            if payload.get("consumer_verified_at_capture") is not True:
                raise FormalOperationalReadinessError(
                    "pit archive consumer readback is not verified"
                )
            source_ids = payload.get("source_ids")
            if not isinstance(source_ids, list) or not source_ids or any(
                not isinstance(item, str) or not item.strip() for item in source_ids
            ):
                raise FormalOperationalReadinessError(
                    "pit archive source_ids are invalid"
                )
            row_count = payload.get("row_count")
            if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count <= 0:
                raise FormalOperationalReadinessError(
                    "pit archive row_count is invalid"
                )
            files = payload.get("files")
            if not isinstance(files, list) or not files:
                raise FormalOperationalReadinessError(
                    "pit archive files are missing"
                )
            verified_roles: set[str] = set()
            for item in files:
                if not isinstance(item, Mapping):
                    raise FormalOperationalReadinessError(
                        "pit archive file entry is invalid"
                    )
                role = _text(item.get("role"))
                expected_hash = _text(item.get("archive_file_hash"))
                if role is None or expected_hash is None:
                    raise FormalOperationalReadinessError(
                        "pit archive file custody fields are missing"
                    )
                if not expected_hash.startswith("sha256:"):
                    raise FormalOperationalReadinessError(
                        "pit archive file custody hash is invalid"
                    )
                file_path = _safe_relative_file(
                    manifest_path.parent,
                    item.get("relative_path"),
                )
                if not file_path.is_file() or file_sha256(file_path) != expected_hash:
                    raise FormalOperationalReadinessError(
                        f"pit archive file hash mismatch:{role}"
                    )
                verified_roles.add(role)
            if "publication" not in verified_roles or "receipt" not in verified_roles:
                raise FormalOperationalReadinessError(
                    "pit archive publication and receipt custody are incomplete"
                )
            base.update(
                {
                    "state": "valid_candidate",
                    "archive_manifest_path": str(manifest_path.resolve()),
                    "archive_manifest_file_hash": file_sha256(manifest_path),
                    "archive_id": _text(payload.get("archive_id")),
                    "captured_at": captured.isoformat(),
                    "archived_at": archived.isoformat(),
                    "effective_from": effective_from,
                    "row_count": row_count,
                    "candidate_only": True,
                    "formal_consumer_compatible": False,
                    "consumer_verified_at_capture": True,
                    "source_ids": list(source_ids),
                    "blockers": [],
                }
            )
            return base
        except (FormalOperationalReadinessError, OSError, TypeError, ValueError) as error:
            failures.append(f"{manifest_path.parent.name}:{type(error).__name__}")
    base["state"] = "invalid" if manifests else "missing"
    base["blockers"] = (
        ["pit_archive_candidates_invalid:" + ";".join(failures[:3])]
        if failures
        else ["pit_archive_for_current_natural_day_missing"]
    )
    return base


def inspect_scheduler_registration(
    path: Path | None,
    *,
    repo_root: Path,
) -> dict[str, object]:
    """檢查外部唯讀 schtasks report；缺少時不能假稱已註冊。"""

    base: dict[str, object] = {
        "state": "not_supplied" if path is None else "missing",
        "path": str(path.expanduser().resolve()) if path is not None else None,
        "report_file_hash": None,
        "captured_at": None,
        "query_only": True,
        "required_tasks": [item["task_name"] for item in SCHEDULE_CONTRACTS],
        "tasks": [],
        "blockers": [],
        "credit_allowed": False,
    }
    if path is None:
        base["blockers"] = ["scheduler_registration_query_not_supplied"]
        return base
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        base["blockers"] = ["scheduler_registration_query_missing"]
        return base
    try:
        payload = _read_json_mapping(resolved)
        base["report_file_hash"] = file_sha256(resolved)
        base["captured_at"] = payload.get("captured_at")
    except (FormalOperationalReadinessError, OSError, TypeError, ValueError) as error:
        base["state"] = "invalid"
        base["blockers"] = [
            f"scheduler_registration_query_invalid:{type(error).__name__}"
        ]
        return base
    records = payload.get("tasks")
    if not isinstance(records, list):
        base["state"] = "invalid"
        base["blockers"] = ["scheduler_registration_tasks_missing"]
        return base
    by_name = {
        str(item.get("name")): item
        for item in records
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    observed: list[dict[str, object]] = []
    blockers: list[str] = []
    for contract in SCHEDULE_CONTRACTS:
        task_name = contract["task_name"]
        record = by_name.get(task_name)
        if record is None:
            blockers.append(f"scheduler_task_not_observed:{task_name}")
            observed.append({"task_name": task_name, "state": "missing"})
            continue
        wrapper_path = repo_root / Path(contract["wrapper"])
        summary_value = record.get("summary")
        summary = summary_value if isinstance(summary_value, Mapping) else {}
        safe_summary = {
            key: summary.get(key)
            for key in _REGISTRATION_CONDITION_KEYS
            if key in summary
        }
        task_view: dict[str, object] = {
            "task_name": task_name,
            "status": record.get("status"),
            "wrapper_status": record.get("wrapper_status"),
            "wrapper_exists": record.get("wrapper_exists"),
            "wrapper_path": contract["wrapper"],
            "action_matches_wrapper": record.get("action_matches_wrapper"),
            "summary": safe_summary,
            "condition_observed": bool(safe_summary),
            "credit_allowed": False,
        }
        observed.append(task_view)
        if record.get("status") != "available":
            blockers.append(f"scheduler_task_unavailable:{task_name}")
        if record.get("wrapper_status") != "present" or not wrapper_path.is_file():
            blockers.append(f"scheduler_wrapper_missing:{task_name}")
        if record.get("action_matches_wrapper") is not True:
            blockers.append(f"scheduler_task_action_unverified:{task_name}")
        if not safe_summary:
            blockers.append(f"scheduler_task_conditions_unobserved:{task_name}")
        last_result = _text(summary.get("last_result"))
        if last_result is not None:
            try:
                if int(last_result, 0) != 0:
                    blockers.append(
                        f"scheduler_task_last_result_nonzero:{task_name}:{last_result}"
                    )
            except ValueError:
                blockers.append(f"scheduler_task_last_result_unparsed:{task_name}")
    base.update(
        {
            "state": "verified" if not blockers else "observed_with_blockers",
            "tasks": observed,
            "blockers": _unique(blockers),
        }
    )
    return base


def inspect_formal_readiness_report(
    path: Path | None,
    *,
    target_date: date,
    now: datetime,
) -> dict[str, object]:
    """重驗 readiness report 自身 hash 與當前自然日，不改 input 狀態。"""

    base: dict[str, object] = {
        "state": "not_supplied" if path is None else "missing",
        "path": str(path.expanduser().resolve()) if path is not None else None,
        "readiness_hash": None,
        "created_at": None,
        "training_as_of": None,
        "ready_input_count": 0,
        "machine_verified_input_count": 0,
        "formal_consumer_compatible_count": 0,
        "input_count": 3,
        "inputs": [],
        "blockers": [],
        "formal_credit_allowed": False,
    }
    if path is None:
        base["blockers"] = ["formal_readiness_report_not_supplied"]
        return base
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        base["blockers"] = ["formal_readiness_report_missing"]
        return base
    try:
        payload = dict(_read_json_mapping(resolved))
        created = _aware_datetime(
            payload.get("created_at"),
            field_name="formal_readiness.created_at",
        )
        expected_hash = _text(payload.get("readiness_hash"))
        body = dict(payload)
        body.pop("readiness_hash", None)
        if expected_hash is None or expected_hash != payload_hash(body):
            raise FormalOperationalReadinessError(
                "formal readiness report hash mismatch"
            )
    except (FormalOperationalReadinessError, OSError, TypeError, ValueError) as error:
        base["state"] = "invalid"
        base["blockers"] = [
            f"formal_readiness_report_invalid:{type(error).__name__}"
        ]
        return base
    blockers: list[str] = []
    if created > now:
        blockers.append("formal_readiness_report_created_in_future")
    if created.astimezone(TAIPEI).date() != target_date:
        blockers.append(
            "formal_readiness_report_for_different_natural_day:"
            + created.astimezone(TAIPEI).date().isoformat()
        )
    if payload.get("formal_oos_allowed") is not False:
        blockers.append("formal_readiness_formal_oos_flag_invalid")
    if payload.get("broker_order_allowed") is not False:
        blockers.append("formal_readiness_broker_flag_invalid")
    inputs = payload.get("inputs")
    input_views: list[dict[str, object]] = []
    if isinstance(inputs, list):
        for item in inputs:
            if isinstance(item, Mapping):
                input_views.append(
                    {
                        "input": item.get("input"),
                        "state": item.get("state"),
                        "reason": item.get("reason"),
                        "path": item.get("path"),
                        "captured_at": item.get("captured_at"),
                        "row_count": item.get("row_count"),
                        "source_custody_verified": item.get(
                            "source_custody_verified"
                        ),
                    }
                )
    else:
        blockers.append("formal_readiness_inputs_missing")
    base.update(
        {
            "state": "current" if not blockers else "stale_or_invalid",
            "readiness_hash": expected_hash,
            "created_at": created.isoformat(),
            "training_as_of": payload.get("training_as_of"),
            "ready_input_count": payload.get("ready_input_count", 0),
            "machine_verified_input_count": payload.get(
                "machine_verified_input_count", 0
            ),
            "formal_consumer_compatible_count": payload.get(
                "formal_consumer_compatible_count", 0
            ),
            "input_count": payload.get("input_count", 3),
            "inputs": input_views,
            "blockers": blockers,
        }
    )
    return base


def inspect_paper_receipts(
    receipt_root: Path | None,
    *,
    target_date: date,
) -> dict[str, object]:
    """讀取 Paper operational receipts；不把 waiting 當成 processed。"""

    base: dict[str, object] = {
        "state": "not_supplied" if receipt_root is None else "missing",
        "root": str(receipt_root.expanduser().resolve()) if receipt_root is not None else None,
        "target_taipei_date": target_date.isoformat(),
        "receipt_count": 0,
        "terminal_receipt_count": 0,
        "statuses": [],
        "blockers": [],
        "credit_allowed": False,
    }
    if receipt_root is None:
        base["blockers"] = ["paper_receipt_root_not_supplied"]
        return base
    root = receipt_root.expanduser().resolve()
    if not root.is_dir():
        base["blockers"] = ["paper_receipt_root_missing"]
        return base
    receipts: list[dict[str, object]] = []
    blockers: list[str] = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = dict(_read_json_mapping(path))
            expected = _text(payload.get("content_sha256"))
            body = dict(payload)
            body.pop("content_sha256", None)
            if expected is None or expected != payload_hash(body):
                raise FormalOperationalReadinessError("receipt content hash mismatch")
            status = _text(payload.get("status")) or "unknown"
            receipts.append(
                {
                    "path": str(path),
                    "file_hash": file_sha256(path),
                    "content_sha256": expected,
                    "status": status,
                    "execution_date": payload.get("execution_date"),
                }
            )
        except (FormalOperationalReadinessError, OSError, TypeError, ValueError) as error:
            blockers.append(f"paper_receipt_invalid:{path.name}:{type(error).__name__}")
    terminal = [
        item
        for item in receipts
        if item.get("status") in {"processed", "failed", "superseded"}
    ]
    base.update(
        {
            "state": "current" if not blockers else "observed_with_blockers",
            "receipt_count": len(receipts),
            "terminal_receipt_count": len(terminal),
            "statuses": receipts,
            "blockers": blockers,
        }
    )
    return base


def audit_formal_operational_readiness(
    *,
    publication_root: Path,
    readiness_path: Path | None = None,
    scheduler_registration_path: Path | None = None,
    paper_receipt_root: Path | None = None,
    now: datetime | None = None,
    repo_root: Path | None = None,
) -> dict[str, object]:
    """建立目前自然日的 no-credit operational readiness report。"""

    if now is None:
        observed = datetime.now(timezone.utc)
    elif now.tzinfo is None or now.utcoffset() is None:
        raise FormalOperationalReadinessError(
            "now must be an aware ISO-8601 timestamp"
        )
    else:
        observed = now.astimezone(timezone.utc)
    local = observed.astimezone(TAIPEI)
    target_date = local.date()
    root = publication_root.expanduser().resolve()
    repository_root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    schedule = inspect_schedule_contract(target_date=target_date, now=observed)
    registration = inspect_scheduler_registration(
        scheduler_registration_path,
        repo_root=repository_root,
    )
    pit_capture_status = inspect_persisted_status(
        root / PIT_CAPTURE_STATUS_RELATIVE,
        target_date=target_date,
        now=observed,
        lane="pit_preopen_capture",
    )
    pit_sidecar_status = inspect_persisted_status(
        root / PIT_SIDECAR_STATUS_RELATIVE,
        target_date=target_date,
        now=observed,
        lane="pit_postcutoff_sidecar",
    )
    formal_status = inspect_persisted_status(
        root / FORMAL_STATUS_RELATIVE,
        target_date=target_date,
        now=observed,
        lane="formal_input_producer",
    )
    pit_archive = inspect_latest_pit_archive(
        root / "pit_candidate_archive",
        target_date=target_date,
        now=observed,
    )
    readiness = inspect_formal_readiness_report(
        readiness_path,
        target_date=target_date,
        now=observed,
    )
    paper = inspect_paper_receipts(
        paper_receipt_root,
        target_date=target_date,
    )

    phase = _phase(local.timetz().replace(tzinfo=None))
    blockers: list[str] = []
    blockers.extend(_string_items(registration.get("blockers")))
    blockers.extend(_registration_operational_blockers(registration, schedule))
    blockers.extend(_string_items(readiness.get("blockers")))

    pit_blockers: list[str] = _string_items(pit_archive.get("blockers"))
    if pit_capture_status["state"] != "current":
        pit_blockers.append("pit_preopen_capture_status_not_current")
    if phase == "before_pit_cutoff":
        pit_blockers.append("pit_formal_sidecar_waiting_for_taipei_0830_cutoff")
    elif pit_sidecar_status["state"] != "current":
        pit_blockers.append("pit_postcutoff_sidecar_receipt_not_current")
    blockers.extend(pit_blockers)

    rule_blockers: list[str] = []
    rule_blockers.extend(_string_items(formal_status.get("reported_blockers")))
    if phase in {"before_pit_cutoff", "pit_postcutoff_before_rule_open"}:
        rule_blockers.append("rule_window_not_open")
    elif formal_status["state"] != "current":
        rule_blockers.append("formal_input_producer_status_not_current")
    blockers.extend(rule_blockers)

    paper_blockers: list[str] = []
    if phase != "paper_eod_or_later":
        paper_blockers.append("paper_eod_source_window_not_reached")
    elif paper["terminal_receipt_count"] == 0:
        paper_blockers.append("paper_execution_terminal_receipt_missing")
    blockers.extend(paper_blockers)

    lanes = {
        "pit": {
            "status": "machine_candidate" if pit_archive["state"] == "valid_candidate" else "blocked",
            "capture_status": pit_capture_status,
            "sidecar_status": pit_sidecar_status,
            "archive": pit_archive,
            "blockers": _unique(pit_blockers),
            "formal_credit": False,
        },
        "rule": {
            "status": "waiting_for_natural_window" if "rule_window_not_open" in rule_blockers else "blocked",
            "status_artifact": formal_status,
            "blockers": _unique(rule_blockers),
            "formal_credit": False,
        },
        "paper": {
            "status": "waiting_for_eod_window" if "paper_eod_source_window_not_reached" in paper_blockers else "blocked",
            "receipts": paper,
            "blockers": _unique(paper_blockers),
            "formal_credit": False,
        },
    }

    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "auditor": AUDITOR_VERSION,
        "observed_at": observed.isoformat(),
        "observed_at_taipei": local.isoformat(),
        "target_taipei_date": target_date.isoformat(),
        "phase": phase,
        "windows": {
            "pit_cutoff_taipei": "08:30",
            "rule_open_taipei": "09:00",
            "rule_close_taipei": "13:30",
            "paper_eod_available_taipei": "15:00",
        },
        "schedule_contract": schedule,
        "scheduler_registration": registration,
        "lanes": lanes,
        "formal_readiness": readiness,
        "blockers": _unique(blockers),
        "status": "blocked_no_formal_credit" if blockers else "observed_no_formal_credit",
        "credit_decision": {
            "machine_identity": AUDITOR_VERSION,
            "decision": "no_credit",
            "reason": "natural_time_and_all_three_consumer_receipts_are not simultaneously proven",
            "formal_ready_input_count": readiness.get("ready_input_count", 0),
            "machine_verified_input_count": readiness.get(
                "machine_verified_input_count", 0
            ),
            "formal_consumer_compatible_count": readiness.get(
                "formal_consumer_compatible_count", 0
            ),
        },
        "safety": {
            "read_only": True,
            "network_requests": False,
            "writes_source_database": False,
            "writes_formal_controlled_paths": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
            "training_started": False,
            "historical_backfill_claimed": False,
            "secret_values_emitted": False,
        },
    }
    body["content_sha256"] = payload_hash(body)
    return body


def write_audit_report(path: Path, payload: Mapping[str, object]) -> None:
    """以 atomic replace 保存指定 QA report，不碰任何來源資料。"""

    target = path.expanduser().resolve()
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(encoded, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "AUDITOR_VERSION",
    "FormalOperationalReadinessError",
    "FORMAL_STATUS_RELATIVE",
    "PIT_CAPTURE_STATUS_RELATIVE",
    "PIT_SIDECAR_STATUS_RELATIVE",
    "SCHEMA_VERSION",
    "SCHEDULE_CONTRACTS",
    "audit_formal_operational_readiness",
    "file_sha256",
    "inspect_formal_readiness_report",
    "inspect_latest_pit_archive",
    "inspect_paper_receipts",
    "inspect_persisted_status",
    "inspect_schedule_contract",
    "inspect_scheduler_registration",
    "payload_hash",
    "write_audit_report",
]
