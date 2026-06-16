"""Audit repository documentation encoding.

The audit is intentionally read-only. It fails on files that cannot be
decoded as UTF-8 and reports suspicious mojibake-looking text separately.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".yaml", ".yml"}
DOC_TEXT_EXTENSIONS = {".txt", ".csv", ".yaml", ".yml"}
MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "â€",
    "ï¼",
    "æ°",
    "è±",
    "ç«",
    "åŒ",
)


@dataclass(frozen=True)
class EncodingIssue:
    path: Path
    kind: str
    detail: str


@dataclass(frozen=True)
class MojibakeWarning:
    path: Path
    line_number: int
    line: str


@dataclass(frozen=True)
class AuditResult:
    scanned_files: int
    utf8_no_bom: int
    utf8_bom: int
    utf16_bom: int
    invalid_utf8: tuple[EncodingIssue, ...]
    mojibake_warnings: tuple[MojibakeWarning, ...]

    @property
    def passed(self) -> bool:
        return not self.invalid_utf8 and self.utf16_bom == 0


def iter_document_files(root: Path) -> Iterable[Path]:
    """Yield docs text files and all repository Markdown files."""
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        suffix = path.suffix.lower()
        if suffix == ".md" or (
            relative_parts
            and relative_parts[0] == "docs"
            and suffix in DOC_TEXT_EXTENSIONS
        ):
            yield path


def audit_document_encoding(root: Path) -> AuditResult:
    scanned = 0
    utf8_no_bom = 0
    utf8_bom = 0
    utf16_bom = 0
    invalid_utf8: list[EncodingIssue] = []
    mojibake_warnings: list[MojibakeWarning] = []

    for path in iter_document_files(root):
        scanned += 1
        data = path.read_bytes()
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            utf16_bom += 1
            invalid_utf8.append(
                EncodingIssue(path=path, kind="utf16_bom", detail=data[:8].hex())
            )
            continue

        has_utf8_bom = data.startswith(b"\xef\xbb\xbf")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            invalid_utf8.append(
                EncodingIssue(
                    path=path,
                    kind="invalid_utf8",
                    detail=f"byte={exc.start}; reason={exc.reason}",
                )
            )
            continue

        if has_utf8_bom:
            utf8_bom += 1
        else:
            utf8_no_bom += 1

        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in MOJIBAKE_MARKERS):
                mojibake_warnings.append(
                    MojibakeWarning(
                        path=path,
                        line_number=line_number,
                        line=line.strip(),
                    )
                )

    return AuditResult(
        scanned_files=scanned,
        utf8_no_bom=utf8_no_bom,
        utf8_bom=utf8_bom,
        utf16_bom=utf16_bom,
        invalid_utf8=tuple(invalid_utf8),
        mojibake_warnings=tuple(mojibake_warnings),
    )


def _format_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root to scan. Defaults to current directory.",
    )
    parser.add_argument(
        "--fail-on-mojibake",
        action="store_true",
        help="Return non-zero when suspicious mojibake-looking text is found.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    result = audit_document_encoding(root)

    print(f"scanned_files={result.scanned_files}")
    print(f"utf8_no_bom={result.utf8_no_bom}")
    print(f"utf8_bom={result.utf8_bom}")
    print(f"utf16_bom={result.utf16_bom}")
    print(f"invalid_utf8={len(result.invalid_utf8)}")
    print(f"mojibake_warnings={len(result.mojibake_warnings)}")

    for issue in result.invalid_utf8:
        print(
            "ERROR "
            f"{issue.kind} "
            f"{_format_path(issue.path, root)} "
            f"{issue.detail}"
        )

    for warning in result.mojibake_warnings:
        print(
            "WARNING mojibake "
            f"{_format_path(warning.path, root)}:{warning.line_number} "
            f"{warning.line}"
        )

    if not result.passed:
        return 1
    if args.fail_on_mojibake and result.mojibake_warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
