from pathlib import Path

from scripts.audit_document_encoding import audit_document_encoding


def test_audit_document_encoding_accepts_utf8_markdown(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# 標題\n繁體中文內容\n", encoding="utf-8")

    result = audit_document_encoding(tmp_path)

    assert result.passed
    assert result.scanned_files == 1
    assert result.utf8_no_bom == 1
    assert result.invalid_utf8 == ()


def test_audit_document_encoding_fails_invalid_utf8(tmp_path: Path) -> None:
    (tmp_path / "BROKEN.md").write_bytes(b"# bad\n\xff\n")

    result = audit_document_encoding(tmp_path)

    assert not result.passed
    assert len(result.invalid_utf8) == 1
    assert result.invalid_utf8[0].kind == "invalid_utf8"


def test_audit_document_encoding_reports_mojibake_warning(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "troubleshooting.md").write_text(
        "branch_display_name = æ°¸è±ç«¹åŒ—\n",
        encoding="utf-8",
    )

    result = audit_document_encoding(tmp_path)

    assert result.passed
    assert len(result.mojibake_warnings) == 1
    assert result.mojibake_warnings[0].line_number == 1


def test_audit_document_encoding_scans_docs_text_files(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.txt").write_text("繁體中文文字檔\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("not a documentation file\n", encoding="utf-8")

    result = audit_document_encoding(tmp_path)

    assert result.passed
    assert result.scanned_files == 1
    assert result.utf8_no_bom == 1
