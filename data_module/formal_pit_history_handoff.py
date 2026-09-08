"""將官方 PIT current-day archive 接到正式歷史來源的保守 handoff。

``pit_sector_membership_machine`` 產生的是可重驗的 current-natural-day
candidate。這個模組只把已驗證的 candidate archive 彙整成 immutable handoff
inventory，並以台北 08:30 的自然日 cutoff 檢查歷史覆蓋。它不把 archive
改名成正式 sidecar，也不把來源 ``formal_acceptance_granted=false`` 改成
true；正式 consumer 仍只會讀明確發布的 ``pit-sector-membership-sidecar-v1``。

handoff 的目的，是讓下一個自然日的 source capture 能沿著同一條 custody
鏈累積，而不是以當日 current snapshot 補回過去。每一個 archive 都必須
保留 capture／archive 時間、source／publication hash 與獨立 expected
universe；缺少任一項時回傳具體 blocker。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from data_module.official_trading_calendar import OfficialTradingCalendar


FORMAL_PIT_HISTORY_HANDOFF_SCHEMA_VERSION = (
    "formal-pit-sector-history-handoff.v1"
)
FORMAL_PIT_HISTORY_CANDIDATE_SCHEMA_VERSION = (
    "formal-pit-sector-history-candidate.v1"
)
TAIPEI = ZoneInfo("Asia/Taipei")
PIT_DECISION_TIME = time(8, 30)
MAX_ARCHIVE_MANIFESTS = 10_000
MAX_COVERAGE_DAYS = 20_000


class FormalPITHistoryHandoffError(ValueError):
    """PIT history handoff 不符合 fail-closed 契約。"""


def inspect_pit_candidate_archive_history(
    archive_root: Path,
    *,
    decision_at: datetime,
    expected_universe_path: Path | None,
    coverage_start: date | None,
    calendar: OfficialTradingCalendar | None = None,
) -> dict[str, object]:
    """唯讀檢查 archive 是否足以交給下一層正式 PIT publisher。

    ``decision_at`` 是實際 consumer decision instant，不能以日期代替。歷史
    覆蓋的每日 cutoff 固定為台北 08:30，與既有 assembler 的 PIT decision
    語意一致；在 cutoff 後完成的 current capture 只能服務下一個可用日。
    """

    decision = _aware_datetime(decision_at, "decision_at")
    archive_dir = archive_root.expanduser().resolve()
    report: dict[str, object] = {
        "schema_version": FORMAL_PIT_HISTORY_CANDIDATE_SCHEMA_VERSION,
        "input": "pit_sector_membership",
        "status": "blocked",
        "decision_at": decision.astimezone(timezone.utc).isoformat(),
        "decision_timezone": "Asia/Taipei",
        "archive_root": str(archive_dir),
        "candidate_only": True,
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "historical_backfill_claimed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "archive_count": 0,
        "valid_archive_count": 0,
        "future_archive_count": 0,
        "invalid_archive_count": 0,
        "lineage": [],
        "coverage": {
            "coverage_start": (
                coverage_start.isoformat() if coverage_start is not None else None
            ),
            "coverage_end": decision.astimezone(TAIPEI).date().isoformat(),
            "decision_cutoff": PIT_DECISION_TIME.isoformat(),
            "required_trading_dates": [],
            "covered_trading_dates": [],
            "missing_trading_dates": [],
            "calendar_evidence": [],
        },
        "independent_universe": _empty_universe_projection(
            expected_universe_path
        ),
        "license_scope": {
            "status": "unknown",
            "formal_acceptance_granted": False,
            "allowed_use_cases": [],
        },
        "blockers": [],
        "required_conditions": [
            "每個正式決策日須有在台北08:30前已可得的官方PIT觀察；盤後捕捉只能服務下一個決策日",
            "archive effective_from 必須等於 capture timestamp 的台北自然日，且 archive 在該 cutoff 前已持久化",
            "expected universe 必須來自 archive 以外的已驗證輸入，並逐次與 publication universe hash 對齊",
            "官方來源 license scope 必須由獨立、可重驗的正式政策封套核對；current candidate 的 declared identity 不足",
            "只有明確發布並由正式 sidecar consumer readback 的歷史封套才可計入 formal input",
        ],
    }
    blockers = _text_list(report["blockers"])

    manifests = _discover_archive_manifests(archive_dir, blockers)
    report["archive_count"] = len(manifests)
    if not manifests:
        blockers.append("pit_formal_candidate_archive_missing")
    elif len(manifests) > MAX_ARCHIVE_MANIFESTS:
        blockers.append("pit_formal_candidate_archive_inventory_too_large")

    expected_symbols, universe_projection = _load_expected_universe(
        expected_universe_path,
        blockers,
        now=decision,
    )
    if expected_universe_path is not None and expected_symbols is not None:
        expected_path = expected_universe_path.expanduser().resolve()
        try:
            expected_path.relative_to(archive_dir)
        except ValueError:
            pass
        else:
            # A file copied into the archive is not an independent denominator
            # even when its JSON and hash happen to match the publication.
            expected_symbols = None
            universe_projection["state"] = "invalid"
            blockers.append(
                "pit_formal_independent_expected_universe_must_be_external"
            )
    report["independent_universe"] = universe_projection

    valid: list[dict[str, object]] = []
    future_count = 0
    invalid_count = 0
    for manifest_path in manifests[:MAX_ARCHIVE_MANIFESTS]:
        try:
            item = _read_archive_observation(
                manifest_path,
                decision=decision,
                expected_symbols=expected_symbols,
                expected_universe_hash=universe_projection.get("content_hash"),
            )
        except Exception as error:  # noqa: BLE001 - preserve per-archive blocker
            invalid_count += 1
            blockers.append(
                "pit_formal_candidate_archive_invalid:"
                f"{manifest_path.parent.name}:{_safe_error(error)}"
            )
            continue
        if _aware_datetime(item["available_at"], "archive.available_at") > decision:
            future_count += 1
            blockers.append(
                "pit_formal_candidate_archive_after_decision:"
                + str(item["archive_id"])
            )
            continue
        if item.get("universe_match") is not True:
            blockers.append(
                "pit_formal_archive_universe_binding_failed:"
                f"{item['archive_id']}:{item.get('universe_binding_reason', 'unknown')}"
            )
        valid.append(item)

    report["future_archive_count"] = future_count
    report["invalid_archive_count"] = invalid_count
    report["valid_archive_count"] = len(valid)
    if not valid:
        blockers.append("pit_formal_candidate_archive_has_no_decision_available_observation")

    natural_day_groups: dict[str, dict[str, object]] = {}
    for item in valid:
        # Only an archive whose rows and universe are bound to the independent
        # denominator can contribute to natural-day coverage.  Its custody and
        # license observations remain in ``valid`` for diagnostics.
        if item.get("universe_match") is not True:
            continue
        effective_from = str(item["effective_from"])
        previous = natural_day_groups.get(effective_from)
        if previous is not None and previous.get("publication_content_hash") != item.get(
            "publication_content_hash"
        ):
            blockers.append(
                "pit_formal_multiple_distinct_captures_for_natural_day:"
                + effective_from
            )
            continue
        # Same publication content may have a second receipt/archive after a
        # retry. Keep one lineage entry; the content identity remains the
        # publication hash rather than an arbitrary latest file.
        natural_day_groups.setdefault(effective_from, item)

    lineage = [
        natural_day_groups[key]
        for key in sorted(natural_day_groups)
    ]
    report["lineage"] = lineage
    independent_license = universe_projection.get("license_scope")
    if valid:
        _validate_license_scope(
            valid,
            blockers,
            report,
            independent_license=(
                independent_license
                if isinstance(independent_license, Mapping)
                else None
            ),
        )
    else:
        blockers.append("pit_formal_license_scope_unobserved")

    coverage = report["coverage"]
    if not isinstance(coverage, dict):  # pragma: no cover - local literal guard
        raise AssertionError("coverage projection must be a dict")
    covered_dates: list[str] = []
    missing_dates: list[str] = []
    required_dates: list[str] = []
    calendar_evidence: list[dict[str, object]] = []
    decision_day = decision.astimezone(TAIPEI).date()
    if coverage_start is None:
        blockers.append("pit_formal_history_coverage_start_missing")
    elif coverage_start > decision_day:
        blockers.append("pit_formal_history_coverage_start_after_decision")
    else:
        span_days = (decision_day - coverage_start).days + 1
        if span_days > MAX_COVERAGE_DAYS:
            blockers.append("pit_formal_history_coverage_range_too_large")
        elif calendar is None:
            blockers.append("pit_formal_official_calendar_required")
        else:
            current = coverage_start
            while current <= decision_day:
                try:
                    is_trading, reason = calendar.is_official_trading_day(current)
                except Exception as error:  # noqa: BLE001 - unknown stays blocked
                    is_trading, reason = None, f"calendar_exception:{_safe_error(error)}"
                evidence: dict[str, object] = {
                    "date": current.isoformat(),
                    "is_trading_day": is_trading,
                    "reason_code": str(reason),
                }
                calendar_evidence.append(evidence)
                if is_trading is None:
                    blockers.append(
                        "pit_formal_calendar_unknown:" + current.isoformat()
                    )
                elif is_trading is True:
                    required_dates.append(current.isoformat())
                    cutoff = datetime.combine(
                        current,
                        PIT_DECISION_TIME,
                        tzinfo=TAIPEI,
                    ).astimezone(timezone.utc)
                    # A consumer decision before today's 08:30 Taipei cutoff
                    # cannot grant today's coverage credit.  The cutoff is the
                    # source-availability boundary, not a target timestamp a
                    # caller may look into from an earlier decision instant.
                    if current == decision_day and decision < cutoff:
                        blockers.append(
                            "pit_formal_decision_before_current_day_cutoff:"
                            + current.isoformat()
                        )
                        missing_dates.append(current.isoformat())
                        current += _one_day()
                        continue
                    eligible = [
                        item
                        for item in lineage
                        if coverage_start is not None
                        and str(item["effective_from"]) >= coverage_start.isoformat()
                        and str(item["effective_from"]) <= current.isoformat()
                        and _aware_datetime(
                            item["available_at"], "archive.available_at"
                        )
                        <= cutoff
                        and _aware_datetime(
                            item["archived_at"], "archive.archived_at"
                        )
                        <= cutoff
                    ]
                    if eligible:
                        covered_dates.append(current.isoformat())
                    else:
                        missing_dates.append(current.isoformat())
                current += _one_day()
    coverage["required_trading_dates"] = required_dates
    coverage["covered_trading_dates"] = covered_dates
    coverage["missing_trading_dates"] = missing_dates
    coverage["calendar_evidence"] = calendar_evidence
    if missing_dates:
        blockers.append(
            "pit_formal_history_missing_natural_days:"
            + ",".join(missing_dates[:32])
        )
    if coverage_start is not None and calendar is not None and not required_dates:
        blockers.append("pit_formal_required_trading_dates_empty")

    # A current candidate archive deliberately cannot self-promote.  This is
    # a permanent boundary for this handoff schema; a separate formal sidecar
    # publisher must prove license scope and invoke its production consumer.
    blockers.append("pit_formal_sidecar_publication_required")
    report["blockers"] = sorted(set(blockers))
    report["status"] = (
        "candidate_history_verified"
        if valid
        else "blocked"
    )
    report["handoff_content_hash"] = _payload_hash(
        {key: value for key, value in report.items() if key != "handoff_content_hash"}
    )
    return report


def persist_pit_candidate_history_handoff(
    *,
    archive_root: Path,
    publication_root: Path,
    decision_at: datetime,
    expected_universe_path: Path | None,
    coverage_start: date | None,
    calendar: OfficialTradingCalendar | None = None,
) -> dict[str, object]:
    """以 create-only bytes 保存 handoff projection，並立即讀回 hash。"""

    projection = inspect_pit_candidate_archive_history(
        archive_root,
        decision_at=decision_at,
        expected_universe_path=expected_universe_path,
        coverage_start=coverage_start,
        calendar=calendar,
    )
    root = publication_root.expanduser().resolve()
    _require_publication_root(root)
    decision_date = _aware_datetime(decision_at, "decision_at").astimezone(TAIPEI).date()
    lineage_hash = str(projection["handoff_content_hash"])[7:23]
    output = root / "pit_history_candidate" / decision_date.isoformat() / (
        f"handoff-{lineage_hash}.json"
    )
    if output.is_file():
        # A retry keeps the first real persistence timestamp.  Rebuilding the
        # envelope with a fresh ``created_at`` would make a create-only retry
        # look like a conflicting mutation even when the projection is the
        # same; readback verifies that the existing bytes are the same
        # content-addressed handoff before returning them.
        readback = read_pit_candidate_history_handoff(output)
        existing_projection = readback.get("projection")
        if not isinstance(existing_projection, Mapping) or existing_projection.get(
            "handoff_content_hash"
        ) != projection.get("handoff_content_hash"):
            raise FormalPITHistoryHandoffError(
                "existing PIT history handoff projection differs on retry"
            )
    else:
        body = {
            "schema_version": FORMAL_PIT_HISTORY_HANDOFF_SCHEMA_VERSION,
            "status": "candidate_only",
            "input": "pit_sector_membership",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "projection": projection,
            "candidate_only": True,
            "formal_ready": False,
            "formal_consumer_compatible": False,
            "historical_backfill_claimed": False,
            "formal_oos_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
        }
        # ``created_at`` records actual persistence time and is intentionally
        # excluded from the content-addressed filename.  A retry reads and
        # verifies the original immutable bytes above.
        payload = {**body, "handoff_hash": _payload_hash(body)}
        try:
            _write_create_only_json(output, payload)
        except FormalPITHistoryHandoffError:
            # Another process may have won the create-only race.  Accept only
            # if its already-persisted projection is the exact same one.
            if not output.is_file():
                raise
            readback = read_pit_candidate_history_handoff(output)
            existing_projection = readback.get("projection")
            if not isinstance(existing_projection, Mapping) or existing_projection.get(
                "handoff_content_hash"
            ) != projection.get("handoff_content_hash"):
                raise
    readback = read_pit_candidate_history_handoff(output)
    result = dict(projection)
    result.update(
        {
            "handoff_path": str(output.resolve()),
            "handoff_file_hash": _file_sha256(output),
            "handoff_hash": readback["handoff_hash"],
            "handoff_readback_verified": True,
        }
    )
    return result


def read_pit_candidate_history_handoff(path: Path) -> dict[str, object]:
    """驗證 handoff manifest，確認 retry 不會讀到竄改的 projection。"""

    resolved = path.expanduser().resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormalPITHistoryHandoffError("PIT history handoff is unreadable") from error
    if not isinstance(payload, dict):
        raise FormalPITHistoryHandoffError("PIT history handoff must be an object")
    expected_fields = {
        "schema_version",
        "status",
        "input",
        "created_at",
        "projection",
        "candidate_only",
        "formal_ready",
        "formal_consumer_compatible",
        "historical_backfill_claimed",
        "formal_oos_allowed",
        "promotion_eligible",
        "broker_order_allowed",
        "handoff_hash",
    }
    if set(payload) != expected_fields:
        raise FormalPITHistoryHandoffError("PIT history handoff fields are invalid")
    for field_name, expected in (
        ("schema_version", FORMAL_PIT_HISTORY_HANDOFF_SCHEMA_VERSION),
        ("status", "candidate_only"),
        ("input", "pit_sector_membership"),
        ("candidate_only", True),
        ("formal_ready", False),
        ("formal_consumer_compatible", False),
        ("historical_backfill_claimed", False),
        ("formal_oos_allowed", False),
        ("promotion_eligible", False),
        ("broker_order_allowed", False),
    ):
        if payload.get(field_name) is not expected if isinstance(expected, bool) else payload.get(field_name) != expected:
            raise FormalPITHistoryHandoffError(
                f"PIT history handoff {field_name} is invalid"
            )
    _aware_datetime(payload.get("created_at"), "handoff.created_at")
    projection = payload.get("projection")
    if not isinstance(projection, Mapping):
        raise FormalPITHistoryHandoffError("PIT history handoff projection is invalid")
    projection_dict = dict(projection)
    if projection_dict.get("schema_version") != FORMAL_PIT_HISTORY_CANDIDATE_SCHEMA_VERSION:
        raise FormalPITHistoryHandoffError(
            "PIT history handoff projection schema is invalid"
        )
    if projection_dict.get("input") != "pit_sector_membership":
        raise FormalPITHistoryHandoffError(
            "PIT history handoff projection input is invalid"
        )
    _aware_datetime(
        projection_dict.get("decision_at"),
        "handoff.projection.decision_at",
    )
    if projection_dict.get("status") not in {"blocked", "candidate_history_verified"}:
        raise FormalPITHistoryHandoffError(
            "PIT history handoff projection status is invalid"
        )
    for field_name in (
        "formal_oos_allowed",
        "promotion_eligible",
        "broker_order_allowed",
        "historical_backfill_claimed",
        "formal_consumer_compatible",
    ):
        if projection_dict.get(field_name) is not False and field_name != "candidate_only":
            raise FormalPITHistoryHandoffError(
                f"PIT history handoff projection {field_name} is invalid"
            )
    if projection_dict.get("candidate_only") is not True or projection_dict.get(
        "formal_ready"
    ) is not False:
        raise FormalPITHistoryHandoffError(
            "PIT history handoff projection formal flags are invalid"
        )
    projection_blockers = projection_dict.get("blockers")
    if not isinstance(projection_blockers, list) or (
        "pit_formal_sidecar_publication_required" not in projection_blockers
    ):
        raise FormalPITHistoryHandoffError(
            "PIT history handoff projection blockers are invalid"
        )
    declared_projection_hash = projection_dict.get("handoff_content_hash")
    if declared_projection_hash != _payload_hash(
        {key: value for key, value in projection_dict.items() if key != "handoff_content_hash"}
    ):
        raise FormalPITHistoryHandoffError("PIT history handoff projection hash mismatch")
    declared_hash = payload.get("handoff_hash")
    body = dict(payload)
    body.pop("handoff_hash", None)
    if declared_hash != _payload_hash(body):
        raise FormalPITHistoryHandoffError("PIT history handoff hash mismatch")
    return dict(payload)


def _discover_archive_manifests(
    root: Path,
    blockers: list[str],
) -> list[Path]:
    if not root.exists():
        return []
    if not root.is_dir():
        blockers.append("pit_formal_candidate_archive_root_not_directory")
        return []
    candidates: list[Path] = []
    for natural_day in sorted(root.iterdir(), key=lambda item: item.name):
        if not natural_day.is_dir():
            continue
        for archive in sorted(natural_day.iterdir(), key=lambda item: item.name):
            manifest = archive / "archive_manifest.json"
            if manifest.is_file():
                resolved_manifest = manifest.resolve()
                try:
                    resolved_manifest.relative_to(root.resolve())
                except ValueError:
                    blockers.append(
                        "pit_formal_candidate_archive_manifest_escapes_root:"
                        + manifest.as_posix()
                    )
                    continue
                candidates.append(resolved_manifest)
                if len(candidates) > MAX_ARCHIVE_MANIFESTS:
                    return candidates
    return candidates


def _read_archive_observation(
    manifest_path: Path,
    *,
    decision: datetime,
    expected_symbols: tuple[str, ...] | None,
    expected_universe_hash: object,
) -> dict[str, object]:
    # Lazy import avoids a module cycle: the daily producer owns the archive
    # reader, while this module only defines the history handoff contract.
    from data_module.formal_daily_input_producer import (  # noqa: PLC0415
        _pit_candidate_json_file,
        _readback_pit_candidate_archive,
    )

    archive = _pit_candidate_json_file(manifest_path, "PIT archive manifest")
    captured_at = _aware_datetime(archive.get("captured_at"), "archive.captured_at")
    archived_at = _aware_datetime(archive.get("archived_at"), "archive.archived_at")
    archive_decision_at = _aware_datetime(
        archive.get("decision_at"), "archive.decision_at"
    )
    # The machine publication validator is prospective by design and rejects
    # an effective date before the validator's *Taipei* calendar date.  A
    # durable archive is deliberately read on a later natural day, so replay
    # it at the recorded capture instant and apply the stronger handoff
    # checks (capture/archive <= requested decision) below.  This does not
    # manufacture time: the timestamp comes from the immutable archive bytes.
    readback = _readback_pit_candidate_archive(
        manifest_path,
        now=max(captured_at, archived_at),
    )
    effective_from = _required_date(archive.get("effective_from"), "effective_from")
    if effective_from != captured_at.astimezone(TAIPEI).date():
        raise FormalPITHistoryHandoffError(
            "archive effective_from does not equal Taipei capture date"
        )
    if archived_at < captured_at:
        raise FormalPITHistoryHandoffError("archive archived_at precedes capture")
    if archived_at > decision:
        raise FormalPITHistoryHandoffError(
            "archive was persisted after decision; historical backfill is forbidden"
        )
    if archive_decision_at > decision:
        raise FormalPITHistoryHandoffError(
            "archive decision was after requested decision; historical backfill is forbidden"
        )
    path_day = manifest_path.parent.parent.name
    if path_day != effective_from.isoformat():
        raise FormalPITHistoryHandoffError(
            "archive directory natural date does not match effective_from"
        )
    publication_path = Path(str(readback["publication_path"])).resolve()
    publication = _pit_candidate_json_file(
        publication_path,
        "archived PIT publication",
    )
    universe = publication.get("universe")
    if not isinstance(universe, Mapping):
        raise FormalPITHistoryHandoffError("PIT publication universe is missing")
    # Archive custody is independently useful even when the current capture
    # has not yet been bound to an external expected universe.  Keep that
    # observation valid, but expose the binding failure as a machine blocker;
    # otherwise a missing universe would erase the source/time/hash lineage
    # that QA needs to diagnose the next natural-day handoff.
    universe_match = True
    universe_binding_reason: str | None = None
    basis = universe.get("basis")
    if basis not in {
        "explicit_current_capture_scope",
        # A current capture made without a caller-supplied denominator records
        # this basis.  It may be accepted only after the separate expected
        # universe and row coverage checks below succeed; the basis alone never
        # supplies the denominator.
        "official_source_union_current_observation",
    }:
        universe_match = False
        universe_binding_reason = "publication_universe_basis_not_explicit"
    elif expected_symbols is None:
        universe_match = False
        universe_binding_reason = "independent_expected_universe_missing"
    else:
        symbols_value = universe.get("symbols")
        if symbols_value != list(expected_symbols):
            universe_match = False
            universe_binding_reason = "publication_symbols_do_not_match_expected_universe"
        elif universe.get("hash") != expected_universe_hash:
            universe_match = False
            universe_binding_reason = "publication_universe_hash_does_not_match_expected_universe"
    rows = publication.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise FormalPITHistoryHandoffError("PIT publication rows are invalid")
    row_symbols = [str(row.get("symbol")) for row in rows]
    if expected_symbols is not None and (
        tuple(sorted(set(row_symbols))) != expected_symbols
        or len(row_symbols) != len(expected_symbols)
    ):
        universe_match = False
        universe_binding_reason = "publication_rows_do_not_cover_expected_universe"
    license_scope = publication.get("license_scope")
    if not isinstance(license_scope, Mapping):
        raise FormalPITHistoryHandoffError("PIT publication license scope is missing")
    raw_row_count = readback.get("row_count")
    if (
        isinstance(raw_row_count, bool)
        or not isinstance(raw_row_count, int)
        or raw_row_count < 0
    ):
        raise FormalPITHistoryHandoffError("archive row_count is invalid")
    raw_source_ids = readback.get("source_ids")
    if not isinstance(raw_source_ids, list) or any(
        not isinstance(value, str) or not value.strip() for value in raw_source_ids
    ):
        raise FormalPITHistoryHandoffError("archive source_ids are invalid")
    raw_allowed = license_scope.get("allowed_use_cases", [])
    allowed_use_cases = (
        [str(value) for value in raw_allowed if isinstance(value, str)]
        if isinstance(raw_allowed, list)
        else []
    )
    return {
        "archive_id": str(readback["archive_id"]),
        "archive_manifest_path": str(manifest_path.resolve()),
        "archive_manifest_hash": str(readback["manifest_hash"]),
        "archive_file_hash": _file_sha256(manifest_path),
        "publication_content_hash": str(readback["publication_content_hash"]),
        "capture_id": str(readback["capture_id"]),
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "available_at": captured_at.astimezone(timezone.utc).isoformat(),
        "archived_at": archived_at.astimezone(timezone.utc).isoformat(),
        "archive_decision_at": archive_decision_at.astimezone(timezone.utc).isoformat(),
        "effective_from": effective_from.isoformat(),
        "row_count": raw_row_count,
        "source_ids": list(raw_source_ids),
        "license_status": str(license_scope.get("status") or "unknown"),
        "license_formal_acceptance_granted": license_scope.get(
            "formal_acceptance_granted"
        ),
        "license_allowed_use_cases": allowed_use_cases,
        "universe_match": universe_match,
        "universe_binding_reason": universe_binding_reason,
    }


def _validate_license_scope(
    lineage: list[dict[str, object]],
    blockers: list[str],
    report: dict[str, object],
    *,
    independent_license: Mapping[str, object] | None = None,
) -> None:
    if independent_license is not None:
        status = independent_license.get("status")
        allowed_raw = independent_license.get("allowed_use_cases")
        source_ids_raw = independent_license.get("source_ids")
        independent_allowed = (
            sorted(value for value in allowed_raw if isinstance(value, str))
            if isinstance(allowed_raw, list)
            else []
        )
        independent_source_ids = (
            sorted(value for value in source_ids_raw if isinstance(value, str))
            if isinstance(source_ids_raw, list)
            else []
        )
        lineage_sources_set: set[str] = set()
        for item in lineage:
            raw_source_ids = item.get("source_ids")
            if isinstance(raw_source_ids, list):
                lineage_sources_set.update(
                    value for value in raw_source_ids if isinstance(value, str)
                )
        lineage_sources = sorted(
            lineage_sources_set
        )
        scope_is_machine_verified = (
            status == "machine_scope_verified"
            and independent_license.get("machine_policy_only") is True
            and independent_license.get("formal_acceptance_granted") is True
            and independent_license.get("legal_acceptance_inferred") is False
            and "formal_pit_sector_membership" in independent_allowed
            and set(lineage_sources).issubset(independent_source_ids)
        )
        report["license_scope"] = {
            **dict(independent_license),
            "allowed_use_cases": independent_allowed,
            "source_ids": independent_source_ids,
            "lineage_source_ids": lineage_sources,
        }
        if not scope_is_machine_verified:
            blockers.append("pit_formal_license_scope_not_formally_accepted")
        if "formal_pit_sector_membership" not in independent_allowed:
            blockers.append("pit_formal_license_use_scope_missing")
        if not set(lineage_sources).issubset(independent_source_ids):
            blockers.append("pit_formal_license_source_scope_mismatch")
        return
    statuses = {str(item.get("license_status")) for item in lineage}
    grants = {item.get("license_formal_acceptance_granted") for item in lineage}
    allowed: set[str] = set()
    for item in lineage:
        raw_allowed = item.get("license_allowed_use_cases")
        if isinstance(raw_allowed, list):
            allowed.update(value for value in raw_allowed if isinstance(value, str))
    report["license_scope"] = {
        "status": sorted(statuses)[0] if len(statuses) == 1 else "mixed",
        "formal_acceptance_granted": grants == {True},
        "allowed_use_cases": sorted(allowed),
    }
    if grants != {True}:
        blockers.append("pit_formal_license_scope_not_formally_accepted")
    if "formal_pit_sector_membership" not in allowed:
        blockers.append("pit_formal_license_use_scope_missing")


def _load_expected_universe(
    path: Path | None,
    blockers: list[str],
    *,
    now: datetime | None = None,
) -> tuple[tuple[str, ...] | None, dict[str, object]]:
    projection = _empty_universe_projection(path)
    if path is None:
        blockers.append("pit_formal_independent_expected_universe_missing")
        return None, projection
    resolved = path.expanduser().resolve()
    projection["path"] = str(resolved)
    if not resolved.is_file():
        blockers.append("pit_formal_independent_expected_universe_file_missing")
        return None, projection
    try:
        raw = resolved.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        blockers.append(
            "pit_formal_independent_expected_universe_invalid:" + _safe_error(error)
        )
        return None, projection
    if isinstance(value, Mapping):
        # A verified data.gov/official-source denominator envelope is the only
        # mapping form accepted here.  Its validator re-reads every child
        # source, metadata, Swagger and license bytes; a caller-provided
        # non-empty ``symbols`` field alone is never enough.
        try:
            from data_module.pit_prospective_denominator import (  # noqa: PLC0415
                validate_prospective_pit_denominator,
            )

            denominator = validate_prospective_pit_denominator(
                resolved,
                now=now,
            )
        except Exception as error:  # noqa: BLE001 - expose typed handoff blocker
            blockers.append(
                "pit_formal_independent_expected_universe_invalid:"
                + _safe_error(error)
            )
            return None, projection
        symbols_value = denominator.get("symbols")
        if not isinstance(symbols_value, list):  # pragma: no cover - validator guard
            blockers.append("pit_formal_independent_expected_universe_invalid:symbols")
            return None, projection
        symbols = tuple(str(item) for item in symbols_value)
        projection.update(
            {
                "state": "verified",
                "file_hash": _sha256_bytes(raw),
                "content_hash": denominator.get("symbols_hash"),
                "symbol_count": denominator.get("symbol_count"),
                "coverage_start": denominator.get("coverage_start"),
                "producer": denominator.get("producer"),
                "producer_version": denominator.get("producer_version"),
                "producer_code_sha256": denominator.get("producer_code_sha256"),
                "source_registry": denominator.get("source_registry"),
                "source_capture_dates": denominator.get("source_capture_dates"),
                "license_scope": denominator.get("license_scope"),
                "denominator_content_hash": denominator.get("content_sha256"),
            }
        )
        return symbols, projection
    if not isinstance(value, list) or not value:
        blockers.append("pit_formal_independent_expected_universe_must_be_nonempty_array")
        return None, projection
    symbols = tuple(item.strip() for item in value if isinstance(item, str))
    if len(symbols) != len(value) or symbols != tuple(sorted(set(symbols))):
        blockers.append("pit_formal_independent_expected_universe_not_sorted_unique_text")
        return None, projection
    content_hash = _payload_hash(list(symbols))
    projection.update(
        {
            "state": "verified",
            "file_hash": _sha256_bytes(raw),
            "content_hash": content_hash,
            "symbol_count": len(symbols),
        }
    )
    return symbols, projection


def _empty_universe_projection(path: Path | None) -> dict[str, object]:
    return {
        "state": "missing",
        "path": str(path.expanduser().resolve()) if path is not None else None,
        "file_hash": None,
        "content_hash": None,
        "symbol_count": 0,
    }


def _require_publication_root(path: Path) -> None:
    repository_output = Path(__file__).resolve().parents[1] / "output"
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        path.relative_to(repository_output.resolve())
    except ValueError:
        try:
            path.relative_to(temp_root)
        except ValueError as error:
            raise FormalPITHistoryHandoffError(
                "PIT history handoff output must be under repository output or TEMP"
            ) from error
    if path == Path.cwd().resolve():
        raise FormalPITHistoryHandoffError(
            "PIT history handoff output must not be repository root"
        )
    path.mkdir(parents=True, exist_ok=True)


def _write_create_only_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
    except FileExistsError:
        existing = path.read_bytes()
        if existing != encoded:
            raise FormalPITHistoryHandoffError(
                "PIT history handoff immutable output differs on retry"
            )


def _required_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise FormalPITHistoryHandoffError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise FormalPITHistoryHandoffError(f"{field_name} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise FormalPITHistoryHandoffError(f"{field_name} must be YYYY-MM-DD")
    return parsed


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise FormalPITHistoryHandoffError(
                f"{field_name} must be ISO timestamp"
            ) from error
    else:
        raise FormalPITHistoryHandoffError(f"{field_name} must be ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FormalPITHistoryHandoffError(f"{field_name} must include timezone")
    return parsed


def _payload_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise FormalPITHistoryHandoffError("blockers must be an array")
    return [str(item) for item in value]


def _one_day() -> timedelta:
    return timedelta(days=1)


def _safe_error(error: Exception) -> str:
    detail = str(error).splitlines()[0].strip() or type(error).__name__
    return detail[:220].replace("\x00", "?")


__all__ = [
    "FORMAL_PIT_HISTORY_CANDIDATE_SCHEMA_VERSION",
    "FORMAL_PIT_HISTORY_HANDOFF_SCHEMA_VERSION",
    "FormalPITHistoryHandoffError",
    "PIT_DECISION_TIME",
    "inspect_pit_candidate_archive_history",
    "persist_pit_candidate_history_handoff",
    "read_pit_candidate_history_handoff",
]
