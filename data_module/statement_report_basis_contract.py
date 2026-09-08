"""財報報表範圍的明示與 legacy 相容判定。"""

from __future__ import annotations

from typing import Any


_REPORT_BASES = frozenset({"consolidated", "individual"})
_LEGACY_SOURCE_ID = "mops.financial_statement.raw"
_LEGACY_CONSOLIDATED_SOURCE_VERSION_PREFIX = "mops-t164-consolidated-"


def resolve_statement_report_basis(
    *,
    explicit_value: Any,
    explicit_column_present: bool,
    source: Any,
    source_version: Any,
) -> str:
    """解析 statement row 的報表範圍，未知語意時拒絕推導。

    新 schema 必須把 ``report_basis`` 寫在 row 上。只有已知的舊版 MOPS
    t164 合併來源契約沒有該欄位，才保留 ``consolidated`` 相容推導；不能
    因為欄位缺失或空白就把未知來源當成合併報表。
    """

    if explicit_column_present:
        basis = _text(explicit_value)
        if basis is None:
            raise ValueError("statement report_basis is missing")
        if basis not in _REPORT_BASES:
            raise ValueError("statement report_basis is unsupported")
        return basis

    source_text = _text(source)
    source_version_text = _text(source_version)
    if (
        source_text == _LEGACY_SOURCE_ID
        and source_version_text is not None
        and source_version_text.startswith(_LEGACY_CONSOLIDATED_SOURCE_VERSION_PREFIX)
    ):
        return "consolidated"
    raise ValueError(
        "statement report_basis is unproven for a source without an explicit column"
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
