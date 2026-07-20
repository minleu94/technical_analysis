from pathlib import Path

import pytest

from scripts.build_mops_quarterly_pit_artifact import build_artifact


def _listing() -> bytes:
    return b'''<!-- saved from url=(0097)https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&mtype=A&co_id=2330&year=115 -->
<input type="hidden" name="co_id" value="2330"><input type="hidden" name="year" value="115">
<tr><td align="center">2330</td><td>115 \xa6~ \xb2\xc4\xa4@\xa9u</td><td>IFRSs\xa6X\xa8\xd6\xb0]\xb3\xf8</td><td><a href="javascript:readfile2(&quot;A&quot;,&quot;2330&quot;,&quot;202601_2330_AI1.pdf&quot;);">202601_2330_AI1.pdf</a></td><td>115/05/15 14:43:02</td><td align="center">\xb5L</td></tr>'''


def test_builds_traceable_chinese_consolidated_artifact(tmp_path: Path) -> None:
    listing = tmp_path / "listing.html"
    listing.write_bytes(_listing())
    report = tmp_path / "202601_2330_AI1.pdf"
    report.write_bytes(b"official-pdf")
    artifact = build_artifact(listing_html=listing, primary_pdf=report, captured_at="2026-07-19T18:22:14-07:00")
    row = artifact["rows"][0]
    assert row["period"] == "2026-Q1"
    assert row["period_end"] == "2026-03-31"
    assert row["announcement_date"] == "2026-05-15T14:43:02+08:00"
    assert row["correction_status"] == "none"
    assert len(row["content_hash"]) == 64


def test_rejects_mismatched_primary_filename(tmp_path: Path) -> None:
    listing = tmp_path / "listing.html"
    listing.write_bytes(_listing())
    report = tmp_path / "wrong.pdf"
    report.write_bytes(b"official-pdf")
    with pytest.raises(ValueError, match="filename"):
        build_artifact(listing_html=listing, primary_pdf=report, captured_at="2026-07-19T18:22:14-07:00")
