# Document Encoding Audit - 2026-06-16

## Summary

The apparent garbled Traditional Chinese output observed in PowerShell was caused by terminal decoding behavior, not by corrupted Markdown content.

All scanned documentation files decode as UTF-8. No batch conversion was required.

## Scope

Command:

```powershell
.\.venv\Scripts\python.exe scripts\audit_document_encoding.py
```

The audit scans:

- all repository Markdown files (`*.md`)
- text-like files under `docs/` with `.txt`, `.csv`, `.yaml`, or `.yml` extensions

## Result

```text
scanned_files=237
utf8_no_bom=237
utf8_bom=0
utf16_bom=0
invalid_utf8=0
mojibake_warnings=1
```

The single mojibake warning is an intentional troubleshooting example in `docs/04_broker_branch/BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md`, not a damaged file.

## Root Cause

The file content is UTF-8, but Windows terminal output can look garbled when a command or console layer decodes UTF-8 bytes with the wrong code page. Reading with explicit UTF-8 fixes the display:

```powershell
Get-Content -Encoding utf8 docs\00_core\DOCUMENTATION_INDEX.md
```

For interactive PowerShell sessions that need stable Traditional Chinese output:

```powershell
chcp 65001
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

## Maintenance Rule

Run the audit when a document appears garbled or before mass-editing documentation:

```powershell
.\.venv\Scripts\python.exe scripts\audit_document_encoding.py
```

Only convert files that fail strict UTF-8 decoding. Do not batch-rewrite already valid UTF-8 documentation.
