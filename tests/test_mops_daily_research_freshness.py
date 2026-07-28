from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from data_module.mops_daily_research_freshness import (
    DIAGNOSTICS_SCHEMA_VERSION,
    SANITIZED_PROJECTION_SCHEMA_VERSION,
    run_mops_daily_freshness_diagnostics,
)
from data_module.mops_ezsearch_statement_availability import (
    MOPS_MARKETS,
    MOPS_STATEMENT_ITEMS,
    MOPSQueryResult,
)


def _row(
    *,
    market_name: str = "sii",
    company_id: str = "2330",
    company_name: str = "台積電",
    item: str = "F26",
    subject: str = "115年第2季資產負債表",
    clock: str = "18:17:06",
    cdate: str = "115/07/27",
) -> dict[str, str]:
    return {
        "CDATE": cdate,
        "CTIME": clock,
        "TYPEK": market_name,
        "COMPANY_ID": company_id,
        "COMPANY_NAME": company_name,
        "CODE_NAME": "半導體業",
        "AN_CODE": item,
        "AN_NAME": MOPS_STATEMENT_ITEMS.get(item, "財務報表"),
        "SUBJECT": subject,
        "HYPERLINK": (
            f"https://mopsov.twse.com.tw/mops/web/ajax_t164sb03?"
            f"co_id={company_id}&year=115&season=2&item={item}"
        ),
    }


def _full_success_matrix(
    rows_per_query: int = 1,
    cdate: str = "115/07/27",
) -> list[MOPSQueryResult]:
    results = []
    for market in MOPS_MARKETS:
        for item in sorted(MOPS_STATEMENT_ITEMS):
            r_list = []
            if rows_per_query > 0:
                cid = "2330" if market == "sii" else "5347" if market == "otc" else "3321" if market == "rotc" else "1234"
                r_list = [
                    _row(
                        market_name=market,
                        company_id=cid,
                        item=item,
                        cdate=cdate,
                    )
                ]
            results.append(
                MOPSQueryResult(
                    market=market,
                    announcement_item=item,
                    rows=tuple(r_list),
                    response_sha256="a" * 64,
                    source_status="success",
                )
            )
    return results


def test_full_matrix_success_returns_observed_status(tmp_path: Path) -> None:
    results = _full_success_matrix(1)
    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path,
        query_results=results,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert res.exit_code == 0
    assert res.run_status == "observed"
    assert res.artifact_path.exists()
    assert res.sanitized_projection_path.exists()

    artifact = json.loads(res.artifact_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION
    assert artifact["quality_summary"]["event_count"] > 0
    assert artifact["safety_boundary"]["formal_oos_allowed"] is False
    assert artifact["safety_boundary"]["production_blend_alpha_bp"] == 0
    assert artifact["safety_boundary"]["fubon_shadow_usable"] is True
    assert artifact["safety_boundary"]["fubon_formal_credit_allowed"] is False


def test_full_matrix_empty_success_returns_observed_empty(tmp_path: Path) -> None:
    results = _full_success_matrix(0)
    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path,
        query_results=results,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert res.exit_code == 0
    assert res.run_status == "observed_empty"
    assert res.summary["quality_summary"]["event_count"] == 0


def test_partial_matrix_returns_degraded_status(tmp_path: Path) -> None:
    partial_results = _full_success_matrix(1)[:5]  # 只取前 5 個 query
    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path,
        query_results=partial_results,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert res.exit_code == 0
    assert res.run_status == "degraded"
    assert "partial query matrix" in str(res.summary.get("degraded_reason"))


def test_query_window_over_31_days_fails_closed(tmp_path: Path) -> None:
    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 8, 5),  # 35 days
        output_root=tmp_path,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert res.exit_code == 1
    assert res.run_status == "capture_failed"
    assert "exceeds maximum allowed limit of 31 days" in res.summary["outage_reason"]


def test_m31_item_causes_artifact_build_failure(tmp_path: Path) -> None:
    results = _full_success_matrix(1)
    results[0] = MOPSQueryResult(
        market="sii",
        announcement_item="M31",
        rows=(_row(item="M31"),),
        response_sha256="b" * 64,
        source_status="success",
    )

    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path,
        query_results=results,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert res.exit_code == 1
    assert res.run_status == "capture_failed"
    assert "unsupported MOPS statement item: M31" in res.summary["outage_reason"]


def test_stale_status_when_query_end_earlier_than_expected_through(tmp_path: Path) -> None:
    results = _full_success_matrix(1, cdate="115/07/22")
    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 25),
        output_root=tmp_path,
        query_results=results,
        expected_through_date=date(2026, 7, 28),
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert res.exit_code == 0
    assert res.run_status == "stale"
    assert "earlier than expected_through" in res.summary.get("degraded_reason", "")


def test_row_conservation_math_and_duplicates(tmp_path: Path) -> None:
    results = _full_success_matrix(1)
    # Add duplicate row to first result
    first = results[0]
    duplicate_rows = first.rows + (first.rows[0],)
    results[0] = MOPSQueryResult(
        market=first.market,
        announcement_item=first.announcement_item,
        rows=duplicate_rows,
        response_sha256=first.response_sha256,
        source_status=first.source_status,
    )

    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path,
        query_results=results,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    assert res.exit_code == 0
    qs = res.summary["quality_summary"]
    assert qs["exact_duplicate_event_count"] == 1
    assert qs["manifest_raw_row_count"] == (
        qs["event_count"]
        + qs["exact_duplicate_event_count"]
        + qs["invalid_event_count"]
        + qs["future_event_count"]
    )


def test_comparison_detects_new_events_and_revision_candidates(tmp_path: Path) -> None:
    # Run 1: Prior
    results1 = _full_success_matrix(1)
    res1 = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path / "run1",
        query_results=results1,
        captured_at="2026-07-28T10:00:00+08:00",
    )

    # Run 2: Current with a revision on one item
    results2 = _full_success_matrix(1)
    revised_row = _row(clock="19:00:00", item="F26")  # changed announcement clock
    first = results2[0]
    results2[0] = MOPSQueryResult(
        market=first.market,
        announcement_item=first.announcement_item,
        rows=(revised_row,),
        response_sha256="c" * 64,
        source_status="success",
    )

    res2 = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path / "run2",
        query_results=results2,
        prior_artifact_path=res1.artifact_path,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    comp = res2.summary["comparison"]
    assert comp["prior_artifact_hash"] == f"sha256:{res1.artifact_sha256}"
    assert comp["revision_candidate_count"] > 0
    assert comp["comparison_status"] == "comparable"


def test_sanitized_projection_contains_no_raw_subject_or_detail_query(tmp_path: Path) -> None:
    results = _full_success_matrix(1)
    res = run_mops_daily_freshness_diagnostics(
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 28),
        output_root=tmp_path,
        query_results=results,
        captured_at="2026-07-28T12:00:00+08:00",
    )

    projection_bytes = res.sanitized_projection_path.read_bytes()
    projection = json.loads(projection_bytes)

    assert projection["schema_version"] == SANITIZED_PROJECTION_SCHEMA_VERSION
    assert "rows" not in projection
    assert "availability_projection" not in projection
    assert "SUBJECT" not in str(projection)
    assert "HYPERLINK" not in str(projection)
    assert projection["formal_allowed"] is False
    assert projection["production_allowed"] is False
    assert projection["status"]["formal_oos"] is False
    assert projection["status"]["alpha_bp"] == 0


def test_output_inside_data_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be outside DATA_ROOT"):
        from data_module.config import TWStockConfig
        config = TWStockConfig()
        run_mops_daily_freshness_diagnostics(
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 28),
            output_root=Path(config.data_root) / "mops_out",
        )
