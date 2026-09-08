from pathlib import Path

import pytest

from scripts import build_mops_statement_pit_candidate as candidate


_RAW_2752 = Path(
    "output/v4_data_recovery_2026-09-07/quarterly/diagnostic-2752-xbrl-r1/"
    "mops_t164sb01_xbrl_2752_115Q2.html"
)
_OFFSETS_2752 = (387793, 387967, 388033, 388399, 389169, 389253)
_RAW_3226 = Path(
    "output/v4_data_recovery_2026-09-07/quarterly/diagnostic-r42-3226-xbrl-r1/"
    "mops_t164sb01_xbrl_3226_115Q2.html"
)
_OFFSETS_3226 = (365887, 366040, 366102, 366424, 367094, 367166)


def test_saved_2752_source_specific_c1_repair_uses_exact_offsets() -> None:
    if not _RAW_2752.is_file():
        pytest.skip("尚未提供本輪保存的 2752 官方 XBRL raw；不自行下載")
    body = _RAW_2752.read_bytes()
    decoded = candidate._decode_mops_xbrl(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert candidate.parse_xbrl_metadata(decoded)["companyid"] == "2752"
    lineage = candidate._xbrl_encoding_lineage(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert lineage["removed_byte_offsets"] == list(_OFFSETS_2752)
    assert lineage["removed_byte_count"] == 6
    assert lineage["repair"] == candidate._XBRL_ENCODING_REPAIR_C1


def test_2752_repair_rejects_same_count_but_wrong_context() -> None:
    if not _RAW_2752.is_file():
        pytest.skip("尚未提供本輪保存的 2752 官方 XBRL raw；不自行下載")
    body = bytearray(_RAW_2752.read_bytes())
    offset = _OFFSETS_2752[0]
    body[offset + 1] = ord("Q")
    with pytest.raises(ValueError, match="source-specific contract"):
        candidate._decode_mops_xbrl(
            bytes(body),
            encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
        )


def test_saved_3226_source_specific_c1_repair_uses_exact_offsets() -> None:
    if not _RAW_3226.is_file():
        pytest.skip("尚未提供本輪保存的 3226 官方 XBRL raw；不自行下載")
    body = _RAW_3226.read_bytes()
    decoded = candidate._decode_mops_xbrl(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert candidate.parse_xbrl_metadata(decoded)["companyid"] == "3226"
    lineage = candidate._xbrl_encoding_lineage(
        body,
        encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
    )
    assert lineage["removed_byte_offsets"] == list(_OFFSETS_3226)
    assert lineage["removed_byte_count"] == 6
    assert lineage["repair"] == candidate._XBRL_ENCODING_REPAIR_C1
    assert lineage["repair_source_sha256"] == (
        "sha256:d1fa3ac461750e6f8dc7e26395196a20d19499e1c140bb5018e7f89e8cabfcbd"
    )


def test_3226_repair_rejects_same_count_but_wrong_context() -> None:
    if not _RAW_3226.is_file():
        pytest.skip("尚未提供本輪保存的 3226 官方 XBRL raw；不自行下載")
    body = bytearray(_RAW_3226.read_bytes())
    offset = _OFFSETS_3226[0]
    body[offset + 1] = ord("Q")
    with pytest.raises(ValueError, match="source-specific contract"):
        candidate._decode_mops_xbrl(
            bytes(body),
            encoding_repair=candidate._XBRL_ENCODING_REPAIR_C1,
        )
