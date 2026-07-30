"""每日增量發布官方市場事件；不寫 active SQLite、不觸及券商執行。"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.official_market_event_backfill import (  # noqa: E402
    OfficialMarketEventBackfillBuilder,
    OfficialMarketEventBackfillRequest,
)


_TAIPEI = ZoneInfo("Asia/Taipei")


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--as-of-date", type=date.fromisoformat)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--retry-delay-seconds", type=int, default=2)
    parser.add_argument("--request-delay-seconds", type=int, default=1)
    return parser


def _year_window(as_of_date: date) -> tuple[int, int]:
    return as_of_date.year - 1, as_of_date.year


def _same_day_failed_custody(
    publication_root: Path,
    *,
    as_of_date: date,
) -> Path | None:
    quarantine_root = publication_root / "quarantine"
    if not quarantine_root.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    for directory in quarantine_root.iterdir():
        manifest_path = directory / "failure_manifest.json"
        if not directory.is_dir() or not manifest_path.is_file():
            continue
        try:
            payload = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            generated_at = datetime.fromisoformat(
                str(payload["generated_at"]).replace("Z", "+00:00")
            ).astimezone(_TAIPEI)
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            continue
        if generated_at.date() == as_of_date:
            candidates.append((manifest_path.stat().st_mtime, directory))
    return (
        max(candidates, key=lambda item: item[0])[1]
        if candidates
        else None
    )


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = _parser().parse_args(argv)
    now = datetime.now(_TAIPEI)
    as_of_date = args.as_of_date or now.date()
    start_year, end_year = _year_window(as_of_date)
    output_root = args.output_root.resolve()
    publication_root = (
        output_root / "release_v4" / "official_market_events"
    )
    status_root = output_root / "scheduled" / "official_market_events"
    status_root.mkdir(parents=True, exist_ok=True)
    raw_custody = _same_day_failed_custody(
        publication_root,
        as_of_date=as_of_date,
    )
    base_status: dict[str, object] = {
        "schema_version": "scheduled-official-market-events.v1",
        "as_of_date": as_of_date.isoformat(),
        "requested_start_year": start_year,
        "requested_end_year": end_year,
        "publication_root": str(publication_root),
        "raw_custody": (
            None if raw_custody is None else str(raw_custody)
        ),
        "active_sqlite_written": False,
        "broker_execution": False,
        "production_action_allowed": False,
        "manual_prompt_required": False,
    }
    try:
        publication = OfficialMarketEventBackfillBuilder().build(
            OfficialMarketEventBackfillRequest(
                output_root=publication_root,
                raw_custody=raw_custody,
                start_year=start_year,
                end_year=end_year,
                timeout_seconds=args.timeout_seconds,
                max_attempts=args.max_attempts,
                retry_delay_seconds=args.retry_delay_seconds,
                request_delay_seconds=args.request_delay_seconds,
            )
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        status = {
            **base_status,
            "status": "failed",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "latest_manifest_updated_by_failed_run": False,
        }
        _publish_status(status_root, status, now=now)
        print(
            json.dumps(status, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    status = {
        **base_status,
        "status": "published",
        "publication_id": publication.publication_id,
        "manifest_path": str(publication.manifest_path),
        "manifest_hash": publication.manifest_hash,
        "manifest_file_hash": publication.manifest_file_hash,
        "canonical_events_hash": publication.canonical_events_hash,
        "canonical_event_count": publication.canonical_event_count,
        "new_event_count": publication.new_event_count,
        "raw_request_count": publication.raw_request_count,
    }
    _publish_status(status_root, status, now=now)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0


def _publish_status(
    status_root: Path,
    payload: dict[str, object],
    *,
    now: datetime,
) -> None:
    run_path = status_root / (
        f"{now.strftime('%Y%m%dT%H%M%S%z')}-{uuid4().hex}.json"
    )
    _atomic_write_json(run_path, payload)
    _atomic_write_json(status_root / "latest_status.json", payload)


def _atomic_write_json(path: Path, payload: object) -> None:
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
