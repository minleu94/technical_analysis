import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_mops_statement_correction import (
    compare_correction_to_candidate,
)


_SPECS = (
    ("A21200", "利息收入", 1, -1),
    ("A22500", "處分及報廢不動產、廠房及設備損失（利益）", -2, 2),
    ("A20010", "收益費損項目合計", 3, 4),
    ("A20000", "調整項目合計", 5, 6),
    ("A33100", "收取之利息", -7, 7),
    ("AAAA", "營業活動之淨現金流入（流出）", 8, 9),
    ("DDDD", "匯率變動對現金及約當現金之影響", 10, 11),
)


def _correction_html(stock_code: str = "2230", *, changed: bool = False) -> bytes:
    values = (
        ("利息收入", "1", "(1)"),
        ("處分及報廢不動產、廠房及設備利益", "(2)", "2"),
        ("不影響現金流量之收益費損項目合計", "3", "4"),
        ("調整項目合計", "5", "6"),
        ("收取之利息", "(7)", "7"),
        ("營業活動之淨現金流入(出)", "8", "9"),
        ("匯率變動對現金及約當現金之影響數", "10", "11"),
    )
    if changed:
        values = (*values[:-1], (values[-1][0], "10", "12"))
    lines = "\n".join(
        f"{label:<30} $ {before:>4}              $ {after:>4}"
        for label, before, after in values
    )
    html = f"""<html><body>
<div>公司代號：{stock_code}　　公司名稱：測試公司</div>
<div>年度季別　11502　財報類別　合併　資料說明　IFRSs合併財報</div>
<pre>第7頁
項目　115/1/1～115/6/30　更正前　更正後
{lines}
(A)第16頁
(B)第19頁
(C)第21頁
(D)第30頁
(E)第33頁
(F)第34頁
(G)第37頁</pre>
</body></html>"""
    return html.encode("utf-8")


def _candidate(path: Path, *, final_value: int = 11) -> Path:
    rows = []
    for code, name, _before, after in _SPECS:
        if code == "DDDD":
            after = final_value
        rows.append(
            {
                "stock_code": "2230",
                "market": "otc",
                "period": "2026-Q2",
                "statement_type": "cash_flows_statement",
                "item_code": code,
                "item_name": name,
                "value": after * 1000,
                "value_scale": 1000,
                "period_start": "2026-01-01",
                "period_end": "2026-06-30",
                "period_basis": "year_to_date",
                "report_basis": "consolidated",
                "revision": 1,
            }
        )
    payload = {
        "schema_version": "mops-statement-pit-candidate.v1",
        "source_version": "test-t164-v1",
        "research_only": True,
        "formal_oos_allowed": False,
        "report_basis": "consolidated",
        "pit_coverage_summary": {
            "stock_code": "2230",
            "market_request": "otc",
            "period": "2026-Q2",
            "numeric_available_at": "2026-09-07T18:02:41+00:00",
            "numeric_available_date": "2026-09-09",
        },
        "rows": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _evidence(html_path: Path, evidence_path: Path) -> Path:
    digest = hashlib.sha256(html_path.read_bytes()).hexdigest()
    payload = {
        "schema_version": "v4-mops-t56-browser-correction-http-observation.v1",
        "research_only": True,
        "formal_oos_allowed": False,
        "capture_mode": "live_official_readonly_http",
        "request": {
            "method": "GET",
            "url": (
                "https://mopsov.twse.com.tw/mops/web/t56sb31_q1?"
                "step=2&CID=2230&YEAR_SEASON=202602"
            ),
        },
        "request_started_at": "2026-09-07T18:33:37+00:00",
        "response_received_at": "2026-09-07T18:33:39+00:00",
        "http": {"status": 200, "sha256": f"sha256:{digest}", "byte_count": html_path.stat().st_size},
        "raw_response": {
            "sha256": f"sha256:{digest}",
            "byte_count": html_path.stat().st_size,
        },
        "correction": {
            "status": "reported",
            "summary": "更正115年度第二季合併財務報告",
            "scope": ["四大報表第7頁", "附註第16、19、21、30、33、34、37頁"],
            "attachment": {"url": "https://mopsov.twse.com.tw/nas/t56sa23/202602/a.pdf"},
        },
    }
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return evidence_path


def _inputs(
    tmp_path: Path,
    *,
    stock_code: str = "2230",
    final_value: int = 11,
    changed_html: bool = False,
) -> tuple[Path, Path, Path]:
    candidate = _candidate(tmp_path / "candidate.json", final_value=final_value)
    html_path = tmp_path / "correction.html"
    html_path.write_bytes(_correction_html(stock_code, changed=changed_html))
    evidence_path = _evidence(html_path, tmp_path / "evidence.json")
    return candidate, html_path, evidence_path


def test_official_page_seven_values_match_by_explicit_code_and_preserve_pit(
    tmp_path: Path,
) -> None:
    candidate, html, evidence = _inputs(tmp_path)
    result = compare_correction_to_candidate(candidate, html, evidence)

    assert result["identity"]["stock_code"] == "2230"
    assert result["comparison"]["matched_item_count"] == 7
    assert result["comparison"]["all_after_values_match"] is True
    assert result["comparison"]["candidate_numeric_values_changed"] is False
    assert result["comparison"]["numeric_available_at_preserved"] is True
    assert result["correction"]["note_scope"][0]["disclosure_only"] is True


def test_wrong_company_is_rejected_even_when_candidate_code_occurs_in_page(
    tmp_path: Path,
) -> None:
    candidate, html, evidence = _inputs(tmp_path, stock_code="2330")

    with pytest.raises(ValueError, match="company mismatch"):
        compare_correction_to_candidate(candidate, html, evidence)


def test_changed_after_value_is_rejected_closed(tmp_path: Path) -> None:
    candidate, html, evidence = _inputs(tmp_path, changed_html=True)

    with pytest.raises(ValueError, match="candidate value mismatch"):
        compare_correction_to_candidate(candidate, html, evidence)


def test_ambiguous_candidate_code_is_rejected(tmp_path: Path) -> None:
    candidate, html, evidence = _inputs(tmp_path)
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["rows"].append(dict(payload["rows"][0]))
    candidate.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="A21200 has 2 matching rows"):
        compare_correction_to_candidate(candidate, html, evidence)
