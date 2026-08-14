import hashlib
from datetime import date
import importlib
import json
from pathlib import Path


_MODULE = importlib.import_module(
    "scripts.scheduled.run_official_market_event_backfill"
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_latest_publication(
    publication_root: Path,
    *,
    start_year: int,
    end_year: int,
) -> None:
    publication_directory = publication_root / "runs" / "publication-1"
    canonical_path = publication_directory / "canonical" / "events.jsonl"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_bytes(b"canonical\n")
    manifest = {
        "canonical_events": {
            "file_hash": _sha256(canonical_path),
            "path": "canonical/events.jsonl",
        },
        "generated_at": "2026-08-10T11:50:00+00:00",
        "manifest_hash": "sha256:manifest-1",
        "request": {"start_year": start_year, "end_year": end_year},
        "status": "formal_source_publication",
    }
    manifest_path = publication_directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    publication_root.mkdir(parents=True, exist_ok=True)
    (publication_root / "latest_manifest.json").write_text(
        json.dumps(
            {
                "manifest_file_hash": _sha256(manifest_path),
                "manifest_hash": manifest["manifest_hash"],
                "manifest_path": "runs/publication-1/manifest.json",
                "publication_id": "publication-1",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_failure_context_verifies_last_formal_publication(tmp_path: Path) -> None:
    publication_root = tmp_path / "official_market_events"
    _write_latest_publication(
        publication_root,
        start_year=2025,
        end_year=2026,
    )

    context = _MODULE._failure_context(
        publication_root,
        RuntimeError(
            "official endpoint fetch failed: "
            "https://www.tpex.org.tw/www/zh-tw/bulletin/sprcHis"
        ),
    )

    assert context["failure_class"] == "tpex_official_endpoint_unavailable"
    assert context["automatic_retry"] is True
    assert context["manual_action_required"] is False
    assert context["formal_publication_preserved"] is True
    known_good = context["last_known_good_publication"]
    assert isinstance(known_good, dict)
    assert known_good["validation_status"] == "verified"
    assert known_good["publication_id"] == "publication-1"


def test_failure_context_does_not_claim_invalid_formal_publication_is_safe(
    tmp_path: Path,
) -> None:
    publication_root = tmp_path / "official_market_events"
    publication_root.mkdir(parents=True)
    (publication_root / "latest_manifest.json").write_text(
        json.dumps(
            {
                "manifest_hash": "sha256:wrong",
                "manifest_path": "runs/missing/manifest.json",
            }
        ),
        encoding="utf-8",
    )

    context = _MODULE._failure_context(
        publication_root,
        RuntimeError("official endpoint returned HTTP 520"),
    )

    assert context["formal_publication_preserved"] is False
    known_good = context["last_known_good_publication"]
    assert isinstance(known_good, dict)
    assert known_good["validation_status"] == "invalid"


def test_year_window_recovers_narrowed_formal_pointer(
    tmp_path: Path,
) -> None:
    publication_root = tmp_path / "official_market_events"
    _write_latest_publication(
        publication_root,
        start_year=2025,
        end_year=2026,
    )

    assert _MODULE._year_window(
        date(2026, 8, 11),
        publication_root,
    ) == (2014, 2026)


def test_year_window_returns_incremental_window_after_full_coverage(
    tmp_path: Path,
) -> None:
    publication_root = tmp_path / "official_market_events"
    _write_latest_publication(
        publication_root,
        start_year=2014,
        end_year=2026,
    )

    assert _MODULE._year_window(
        date(2026, 8, 11),
        publication_root,
    ) == (2025, 2026)
