"""以 MOPS t164 官方回應建立單一公司季度財報研究候選。

本工具只抓取一家公司、一個季度的合併或個別資產負債表、綜合損益表與現金流量表，
並將原始回應、公告 listing 與逐項整數值保存在隔離的研究輸出目錄。它不寫入
FA_Data、SQLite、正式 availability mapping 或 source acceptance 狀態。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any, Mapping
import unicodedata
from urllib.parse import parse_qs, urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.config import TWStockConfig
from development_module.output_guard import resolve_development_output_dir
from scripts.build_mops_numeric_pit_candidate import (
    _fetch_listing_response,
    _file_sha256_reference,
    _listing_url,
    parse_listing_event,
)
from scripts.validate_mops_quarterly_artifact import validate_artifact


MOPS_STATEMENT_BASE_URL = "https://mopsov.twse.com.tw/mops/web"
MOPS_XBRL_URL = "https://mopsov.twse.com.tw/server-java/t164sb01"
MOPS_EZSEARCH_URL = "https://mopsov.twse.com.tw/mops/web/ezsearch_query"
_EZSEARCH_ITEMS: dict[str, tuple[str, str, str]] = {
    "F26": ("balance_sheet", "資產負債表", "ajax_t164sb03"),
    "F27": ("income_statement", "綜合損益表", "ajax_t164sb04"),
    "F28": ("cash_flows_statement", "現金流量表", "ajax_t164sb05"),
}
_EZSEARCH_MARKET_NAMES = {
    "sii": "上市",
    "otc": "上櫃",
    "rotc": "興櫃",
    "pub": "公開發行",
}
MOPS_STATEMENT_ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "balance_sheet": (
        "ajax_t164sb03",
        "mops.t164sb03.consolidated_balance_sheet",
        "合併資產負債表",
    ),
    "income_statement": (
        "ajax_t164sb04",
        "mops.t164sb04.consolidated_income_statement",
        "合併綜合損益表",
    ),
    "cash_flows_statement": (
        "ajax_t164sb05",
        "mops.t164sb05.consolidated_cash_flows_statement",
        "合併現金流量表",
    ),
}
_REPORT_BASES = frozenset({"consolidated", "individual"})
_REPORT_BASIS_TITLES: dict[str, dict[str, str]] = {
    "consolidated": {
        "balance_sheet": "合併資產負債表",
        "income_statement": "合併綜合損益表",
        "cash_flows_statement": "合併現金流量表",
    },
    "individual": {
        "balance_sheet": "個別資產負債表",
        "income_statement": "個別綜合損益表",
        "cash_flows_statement": "個別現金流量表",
    },
}
_REPORT_BASIS_XBRL_ID = {"consolidated": "C", "individual": "A"}
_REPORT_BASIS_XBRL_CATEGORY = {
    "consolidated": "Consolidated report",
    "individual": "Individual report",
}
_XBRL_ENCODING_REPAIR_C1 = "strip_declared_big5_c1_controls"
# 只接受已保存且已人工核對過的官方 response。這不是通用的 0x84 清理規則；
# 每個來源都必須以完整 raw SHA 與精確 offset 建立可重驗的非語意位置契約。
_XBRL_C1_REPAIR_SOURCE_RULES: dict[str, tuple[int, ...]] = {
    "17859ef06199b4325c352810f819ea4ed9099623eb361e3e754521f5456f4981": (
        422759,
        422935,
        422998,
        423354,
        423751,
        423827,
    ),
    "c4afe7da22e2d4190368e381d798dc4afe6900e0e3538fecffc4e9257952c6d1": (
        387793,
        387967,
        388033,
        388399,
        389169,
        389253,
    ),
    # 3226 的官方 115 年第 2 季頁面也只在 IFRS18／IAS7 敘述項目符號出現孤立 0x84；
    # 來源 SHA、六個 offset 與各 offset 的換行加 P 上下文均已離線核對。
    "d1fa3ac461750e6f8dc7e26395196a20d19499e1c140bb5018e7f89e8cabfcbd": (
        365887,
        366040,
        366102,
        366424,
        367094,
        367166,
    ),
    # 3499 的官方頁面同樣只在 IFRS18／IAS7 敘述項目符號出現孤立 0x84；
    # 來源 SHA、六個 offset 與預設的換行加 P 上下文均已離線核對。
    "6e59cf3519d179137f6688210195b667f91597e2d1e73a9ce2f75a1b4e063a71": (
        419490,
        419644,
        419706,
        420028,
        420707,
        420781,
    ),
    # 3526 的官方頁面只在投資與被投資公司附註的非語意換行項目符號出現孤立 0x84；
    # 來源 SHA、五個 offset 與預設的換行加 P 上下文均已離線核對。
    "4267346c8127510b1baf22a4bacfeac2488feaebd61034b93c1ec0e04e0366d1": (
        406096,
        406251,
        406312,
        406637,
        407323,
    ),
}
_XBRL_C1_REPAIR_CONTEXT = b"\n\x84P"
# 2752 的官方頁面在同一個非語意項目符號前保留四個空白；
# 依完整 raw SHA 綁定上下文，不能把此格式推廣到其他來源。
_XBRL_C1_REPAIR_CONTEXTS: dict[str, bytes] = {
    "c4afe7da22e2d4190368e381d798dc4afe6900e0e3538fecffc4e9257952c6d1": (
        b"\n    \x84P"
    ),
}


def _statement_title(*, statement_type: str, report_basis: str) -> str:
    if report_basis not in _REPORT_BASES:
        raise ValueError(f"unsupported report_basis: {report_basis}")
    try:
        return _REPORT_BASIS_TITLES[report_basis][statement_type]
    except KeyError as error:
        raise ValueError(f"unsupported statement_type: {statement_type}") from error


def _statement_source_id(*, statement_type: str, report_basis: str) -> str:
    """以報表範圍生成不會混淆合併／個別的官方 endpoint 身分。"""
    endpoint, source_id, _ = MOPS_STATEMENT_ENDPOINTS[statement_type]
    del endpoint
    return source_id.replace("consolidated", report_basis)
_STOCK_CODE_RE = re.compile(r"^\d{4,6}$")
_QUARTER_NAME = ("一", "二", "三", "四")
_PER_SHARE_ITEM_NAMES = frozenset(
    {
        "基本每股盈餘",
        "稀釋每股盈餘",
        # MOPS 某些公司把 continuing basic／diluted EPS 顯示成同一中文列名；
        # XBRL 的 9710／9810 順序再由 candidate occurrence 做局部消歧。
        "繼續營業單位淨利（淨損）",
        # MOPS 同樣會把 discontinued basic／diluted EPS 顯示成同一中文列名；
        # 只有在 XBRL 官方 row code 與 scale 都相符時才接受此已核對欄位。
        "停業單位淨利（淨損）",
    }
)
_MISSING_VALUE_MARKERS = frozenset({"", "-", "--", "—", "–", "－"})
_TAIPEI_TIMEZONE = timezone(timedelta(hours=8))


class _StatementTableParser(HTMLParser):
    """保留表格邊界，避免把頁尾或其他表格列誤當財報科目。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "table" and self._table is None:
            self._table = []
        elif tag_name == "tr" and self._table is not None:
            self._row = []
        elif tag_name in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in {"td", "th"} and self._cell is not None and self._row is not None:
            raw_cell = "".join(self._cell)
            leading = raw_cell[: len(raw_cell) - len(raw_cell.lstrip(" \t\u3000"))]
            self._row.append(leading + " ".join(raw_cell.split()))
            self._cell = None
        elif tag_name == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag_name == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


class _MopsCompanySelectorParser(HTMLParser):
    """解析 t164 首次回傳的公司選擇表，不以代碼 substring 猜測公司。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str | None]] = []
        self._in_row = False
        self._cells: list[str] = []
        self._cell_parts: list[str] | None = None
        self._submit_code: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "tr":
            self._in_row = True
            self._cells = []
            self._cell_parts = None
            self._submit_code = None
            return
        if not self._in_row:
            return
        if tag_name in {"td", "th"}:
            self._cell_parts = []
            return
        if tag_name == "input":
            attr_map = {key.lower(): value for key, value in attrs}
            onclick = attr_map.get("onclick") or ""
            match = re.search(
                r"\bco_id\s*\.\s*value\s*=\s*(['\"])([^'\"]+)\1",
                onclick,
                flags=re.IGNORECASE,
            )
            if match is not None:
                self._submit_code = match.group(2).strip()

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in {"td", "th"} and self._cell_parts is not None:
            self._cells.append(" ".join("".join(self._cell_parts).split()))
            self._cell_parts = None
            return
        if tag_name == "tr" and self._in_row:
            if self._cells:
                self.rows.append((self._cells[0], self._submit_code))
            self._in_row = False
            self._cells = []
            self._cell_parts = None
            self._submit_code = None


def _selector_detail_code(html_text: str, stock_code: str) -> str | None:
    """只接受顯示代碼精確相等且唯一的 t164 詳細查詢代碼。"""
    parser = _MopsCompanySelectorParser()
    parser.feed(html_text)
    parser.close()
    matches = {
        submit_code
        for displayed_code, submit_code in parser.rows
        if displayed_code.strip() == stock_code and submit_code
    }
    return next(iter(matches)) if len(matches) == 1 else None


@dataclass(frozen=True)
class OfficialItemCode:
    """MOPS XBRL 回應中的官方 row code 與概念名稱。"""

    item_code: str
    official_item_name: str
    xbrl_concept: str | None
    reported_value: str | None
    indent_depth: int | None


_XBRL_METADATA_FIELDS = frozenset(
    {"companyid", "year", "quarter", "reportcategory", "market"}
)


class _OfficialXbrlMetadataParser(HTMLParser):
    """只讀取官方 ix:nonNumeric metadata，不以全文搜尋判斷身分。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, set[str]] = {}
        self._active_field: str | None = None
        self._active_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not tag.lower().endswith(":nonnumeric"):
            return
        attr_map = {key.lower(): value for key, value in attrs}
        name = attr_map.get("name")
        if not name:
            self._active_field = None
            self._active_parts = []
            return
        field = name.rsplit(":", 1)[-1].lower()
        if field not in _XBRL_METADATA_FIELDS:
            self._active_field = None
            self._active_parts = []
            return
        self._active_field = field
        self._active_parts = []

    def handle_data(self, data: str) -> None:
        if self._active_field is not None:
            self._active_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not tag.lower().endswith(":nonnumeric"):
            return
        if self._active_field is not None:
            value = " ".join("".join(self._active_parts).split())
            self.values.setdefault(self._active_field, set()).add(value)
        self._active_field = None
        self._active_parts = []


def parse_xbrl_metadata(html_text: str) -> dict[str, str]:
    """解析官方 XBRL 隱藏身分欄位，缺值或多值一律拒絕。"""
    parser = _OfficialXbrlMetadataParser()
    parser.feed(html_text)
    parser.close()
    metadata: dict[str, str] = {}
    for field, values in parser.values.items():
        if len(values) != 1:
            raise ValueError(f"MOPS XBRL metadata field is ambiguous: {field}")
        metadata[field] = next(iter(values))
    return metadata


def _declared_xbrl_encoding(body: bytes) -> str | None:
    """讀取 response 開頭的 charset 宣告，缺少宣告時回傳 None。"""
    header = body[:8192].decode("ascii", errors="ignore")
    match = re.search(
        r"charset\s*=\s*['\"]?([a-z0-9._-]+)",
        header,
        flags=re.IGNORECASE,
    )
    return match.group(1).lower() if match is not None else None


def _verified_xbrl_c1_offsets(body: bytes, *, last_error: UnicodeDecodeError) -> tuple[int, ...]:
    """驗證已核實來源的孤立 0x84 位置，不以內容替換猜測語意。"""
    if _declared_xbrl_encoding(body) != "big5":
        raise ValueError(
            "MOPS XBRL encoding repair requires an official charset=big5 declaration"
        ) from last_error
    c1_values = {value for value in body if 0x80 <= value <= 0x9F}
    if c1_values != {0x84}:
        raise ValueError(
            "MOPS XBRL encoding repair found unsupported C1 control bytes"
        ) from last_error
    source_sha256 = sha256(body).hexdigest()
    expected_offsets = _XBRL_C1_REPAIR_SOURCE_RULES.get(source_sha256)
    if expected_offsets is None:
        raise ValueError(
            "MOPS XBRL encoding repair has no verified source-specific contract"
        ) from last_error
    actual_offsets = tuple(index for index, value in enumerate(body) if value == 0x84)
    if actual_offsets != expected_offsets:
        raise ValueError(
            "MOPS XBRL encoding repair offsets do not match the verified raw response"
        ) from last_error
    context = _XBRL_C1_REPAIR_CONTEXTS.get(
        source_sha256,
        _XBRL_C1_REPAIR_CONTEXT,
    )
    marker_index = context.find(b"\x84")
    if marker_index < 0:
        raise ValueError("MOPS XBRL encoding repair context lacks the C1 marker") from last_error
    for offset in expected_offsets:
        start = offset - marker_index
        end = start + len(context)
        if start < 0 or body[start:end] != context:
            raise ValueError(
                "MOPS XBRL encoding repair found an unverified 0x84 position"
            ) from last_error
    return expected_offsets


def _decode_mops_xbrl_with_lineage(
    body: bytes,
    *,
    encoding_repair: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """嚴格解碼 XBRL，並回傳與實際分支一致的編碼 lineage。"""
    if encoding_repair not in {None, _XBRL_ENCODING_REPAIR_C1}:
        raise ValueError(f"unsupported MOPS XBRL encoding repair: {encoding_repair}")

    errors: list[UnicodeDecodeError] = []
    for encoding in ("big5hkscs", "big5"):
        try:
            text = body.decode(encoding, errors="strict")
            return text, {
                "declared_encoding": _declared_xbrl_encoding(body) or "unknown",
                "decoder": encoding,
                "repair": None,
                "removed_byte_count": 0,
                "raw_bytes_preserved": True,
            }
        except UnicodeDecodeError as error:
            errors.append(error)

    if encoding_repair != _XBRL_ENCODING_REPAIR_C1:
        raise ValueError("MOPS XBRL response is not valid strict Big5/HKSCS text") from errors[-1]

    offsets = _verified_xbrl_c1_offsets(body, last_error=errors[-1])
    repaired = bytearray(body)
    # 由後往前刪除，保持其餘 raw byte 的 offset 與內容不被誤改。
    for offset in reversed(offsets):
        del repaired[offset]
    for encoding in ("big5hkscs", "big5"):
        try:
            text = bytes(repaired).decode(encoding, errors="strict")
            return text, {
                "declared_encoding": "big5",
                "decoder": encoding,
                "repair": encoding_repair,
                "removed_byte_hex": "84",
                "removed_byte_count": len(offsets),
                "removed_byte_offsets": list(offsets),
                "raw_bytes_preserved": True,
                "repair_source_sha256": f"sha256:{sha256(body).hexdigest()}",
            }
        except UnicodeDecodeError:
            continue
    raise ValueError(
        "MOPS XBRL encoding repair did not produce strict Big5/HKSCS text"
    ) from errors[-1]


def _decode_mops_xbrl(
    body: bytes,
    *,
    encoding_repair: str | None = None,
) -> str:
    """依官方宣告嚴格解碼；修復只接受已核實 raw 的精確位置。"""
    text, _lineage = _decode_mops_xbrl_with_lineage(
        body,
        encoding_repair=encoding_repair,
    )
    return text


def _xbrl_encoding_lineage(
    body: bytes,
    *,
    encoding_repair: str | None,
) -> dict[str, Any]:
    """輸出與實際 decoder 分支一致的 XBRL lineage，不改寫原始 response。"""
    _text, lineage = _decode_mops_xbrl_with_lineage(
        body,
        encoding_repair=encoding_repair,
    )
    return lineage


class _OfficialXbrlRowParser(HTMLParser):
    """解析 XBRL 財報的代號、中文科目與概念名稱。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str | None, str | None, int | None]] = []
        self._in_row = False
        self._cells: list[str] = []
        self._cell_parts: list[str] | None = None
        self._zh_parts: list[str] = []
        self._zh_depth = 0
        self._concepts: list[str] = []
        self._in_nonfraction = False
        self._value_parts: list[str] = []
        self._value_sign: str | None = None
        self._value_parenthesized = False
        self._reported_values: list[str] = []
        self._cell_indents: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "tr":
            self._in_row = True
            self._cells = []
            self._cell_parts = None
            self._zh_parts = []
            self._zh_depth = 0
            self._concepts = []
            self._in_nonfraction = False
            self._value_parts = []
            self._value_sign = None
            self._value_parenthesized = False
            self._reported_values = []
            self._cell_indents = []
            return
        if not self._in_row:
            return
        if tag_name in {"td", "th"}:
            self._cell_parts = []
            self._zh_parts = []
            self._zh_depth = 0
            return
        if tag_name == "span":
            classes = {
                value.strip().lower()
                for key, value in attrs
                if key.lower() == "class" and value
                for value in value.split()
            }
            if "zh" in classes:
                self._zh_depth += 1
        if tag_name.endswith(":nonfraction") or tag_name == "ix:nonfraction":
            attr_map = {key.lower(): value for key, value in attrs}
            concept = attr_map.get("name")
            if concept and concept not in self._concepts:
                self._concepts.append(concept)
            self._in_nonfraction = True
            self._value_parts = []
            self._value_sign = attr_map.get("sign")
            # MOPS 有些負數以欄位外括號表達，不能只依賴 ix:nonFraction 的 sign 屬性。
            previous_cell_text = "".join(self._cell_parts or [])
            self._value_parenthesized = previous_cell_text.rstrip().endswith(("(", "（"))

    def handle_data(self, data: str) -> None:
        if self._cell_parts is None:
            return
        self._cell_parts.append(data)
        if self._zh_depth > 0:
            self._zh_parts.append(data)
        if self._in_nonfraction:
            self._value_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if (tag_name.endswith(":nonfraction") or tag_name == "ix:nonfraction") and self._in_nonfraction:
            value = " ".join("".join(self._value_parts).split())
            if value:
                if self._value_sign == "-" and not value.startswith("-"):
                    value = f"-{value}"
                elif (
                    self._value_parenthesized
                    and self._value_sign != "+"
                    and not value.startswith("-")
                ):
                    value = f"-{value}"
                self._reported_values.append(value)
            self._in_nonfraction = False
            self._value_parts = []
            self._value_sign = None
            self._value_parenthesized = False
            return
        if tag_name == "span" and self._zh_depth > 0:
            self._zh_depth -= 1
            return
        if tag_name in {"td", "th"} and self._cell_parts is not None:
            source = self._zh_parts if self._zh_parts else self._cell_parts
            raw_source = "".join(source)
            self._cell_indents.append(
                len(raw_source) - len(raw_source.lstrip(" \t\u3000"))
            )
            self._cells.append(" ".join(raw_source.split()))
            self._cell_parts = None
            self._zh_parts = []
            self._zh_depth = 0
            return
        if tag_name == "tr" and self._in_row:
            if len(self._cells) >= 2:
                code = self._cells[0].strip()
                label = self._cells[1].strip()
                if _OFFICIAL_ITEM_CODE_RE.fullmatch(code) and label:
                    self.rows.append(
                        (
                            code,
                            label,
                            self._concepts[0] if self._concepts else None,
                            self._reported_values[0] if self._reported_values else None,
                            self._cell_indents[1] if len(self._cell_indents) > 1 else None,
                        )
                    )
            self._in_row = False
            self._cells = []
            self._cell_parts = None
            self._zh_parts = []
            self._zh_depth = 0
            self._concepts = []
            self._in_nonfraction = False
            self._value_parts = []
            self._value_sign = None
            self._value_parenthesized = False
            self._reported_values = []
            self._cell_indents = []


_OFFICIAL_ITEM_CODE_RE = re.compile(r"[A-Z0-9]{2,8}")


@dataclass(frozen=True)
class StatementTableParseResult:
    statement_type: str
    report_basis: str
    endpoint: str
    rows: tuple[dict[str, Any], ...]
    excluded_rows: tuple[dict[str, str], ...]
    table_row_count: int
    named_row_count: int
    period_start: date | None
    period_end: date
    period_basis: str
    period_header: str


def parse_statement_table(
    html_text: str,
    *,
    statement_type: str,
    roc_year: int,
    season: int,
    report_basis: str = "consolidated",
) -> StatementTableParseResult:
    """解析指定期別第一欄金額，並保留沒有數值的科目列。"""
    if statement_type not in MOPS_STATEMENT_ENDPOINTS:
        raise ValueError(f"unsupported statement_type: {statement_type}")
    if report_basis not in _REPORT_BASES:
        raise ValueError(f"unsupported report_basis: {report_basis}")
    if not 1 <= season <= 4:
        raise ValueError("season must be between 1 and 4")
    normalized_text = " ".join(html_text.split())
    normalized_no_space = normalized_text.replace(" ", "")
    expected_markers = (
        f"民國{roc_year}年第{season}季",
        f"民國{roc_year}年第{_QUARTER_NAME[season - 1]}季",
    )
    if not any(marker in normalized_no_space for marker in expected_markers):
        raise ValueError(
            "MOPS statement response period marker does not match the request; "
            f"expected_one_of={expected_markers}"
        )
    expected_title = _statement_title(
        statement_type=statement_type,
        report_basis=report_basis,
    )
    if expected_title not in normalized_text:
        raise ValueError(
            "MOPS statement response title does not match the requested statement type; "
            f"expected={expected_title}"
        )

    parser = _StatementTableParser()
    parser.feed(html_text)
    target_header = _target_header(roc_year=roc_year, season=season, statement_type=statement_type)
    target_table, header_index, value_index = _find_target_table(
        parser.tables,
        target_header=target_header,
    )
    period_start, period_end, period_basis = _period_window(
        statement_type=statement_type,
        roc_year=roc_year,
        season=season,
    )
    period_header = target_table[header_index][value_index]
    rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, str]] = []
    named_row_count = 0
    for row_index, cells in enumerate(target_table[header_index + 1 :], start=header_index + 2):
        raw_item_name = cells[0] if cells else ""
        item_indent = len(raw_item_name) - len(raw_item_name.lstrip(" \t\u3000"))
        item_name = raw_item_name.strip()
        if not item_name or item_name == "會計項目":
            continue
        named_row_count += 1
        value_raw = cells[value_index].strip() if len(cells) > value_index else ""
        if value_raw in _MISSING_VALUE_MARKERS:
            excluded_rows.append(
                {
                    "statement_type": statement_type,
                    "item_name": item_name,
                    "row_index": str(row_index),
                    "reason": "empty_or_unavailable_value",
                }
            )
            continue
        try:
            value, value_unit, value_scale = _parse_item_value(
                value_raw,
                statement_type=statement_type,
                item_name=item_name,
            )
        except ValueError as error:
            raise ValueError(
                "MOPS statement value is not an integer governed unit value; "
                f"statement_type={statement_type}; item_name={item_name}; value={value_raw}"
            ) from error
        raw_material = {
            "statement_type": statement_type,
            "item_name": item_name,
            "value": value_raw,
            # 保持既有 source-row hash 的正規化形狀；縮排另存 item_indent。
            "cells": [" ".join(cell.split()) for cell in cells],
        }
        rows.append(
            {
                "item_name": item_name,
                "value": value,
                "value_unit": value_unit,
                "value_scale": value_scale,
                "raw_value": value_raw,
                "item_indent": item_indent,
                "source_row_sha256": _canonical_sha256(raw_material),
            }
        )
    if not rows:
        raise ValueError(f"MOPS statement response has no numeric rows: {statement_type}")
    return StatementTableParseResult(
        statement_type=statement_type,
        report_basis=report_basis,
        endpoint=MOPS_STATEMENT_ENDPOINTS[statement_type][0],
        rows=tuple(rows),
        excluded_rows=tuple(excluded_rows),
        table_row_count=len(target_table),
        named_row_count=named_row_count,
        period_start=period_start,
        period_end=period_end,
        period_basis=period_basis,
        period_header=period_header,
    )


def parse_xbrl_item_codes(
    html_text: str,
) -> dict[str, tuple[OfficialItemCode, ...]]:
    """解析 MOPS t164 XBRL 回應中的官方代號索引。

    XBRL 頁面同時列出代號、中文科目與 IFRS concept。中文顯示頁沒有
    代號欄，因此正式 materialization 只能先以這個官方回應建立對照；
    同名而對應不同代號時保留所有官方列，讓下游可用報表類型、數值與縮排
    逐步消歧；仍無法唯一確認時明確 fail-closed。
    """
    parser = _OfficialXbrlRowParser()
    parser.feed(html_text)
    by_name: dict[str, list[OfficialItemCode]] = {}
    for item_code, official_item_name, xbrl_concept, reported_value, indent_depth in parser.rows:
        key = _normalize_item_name(official_item_name)
        if not key:
            continue
        current = OfficialItemCode(
            item_code=item_code,
            official_item_name=official_item_name,
            xbrl_concept=xbrl_concept,
            reported_value=reported_value,
            indent_depth=indent_depth,
        )
        existing_codes = {item.item_code for item in by_name.get(key, ())}
        if item_code not in existing_codes:
            by_name.setdefault(key, []).append(current)
    if not by_name:
        raise ValueError("MOPS XBRL response contains no official item codes")
    return {key: tuple(values) for key, values in by_name.items()}


def resolve_official_item_code(
    item_name: str,
    item_codes: Mapping[str, tuple[OfficialItemCode, ...]],
    *,
    statement_type: str | None = None,
    candidate_value: int | None = None,
    candidate_scale: int | None = None,
    candidate_indent_depth: int | None = None,
    candidate_occurrence: int | None = None,
) -> OfficialItemCode | None:
    """以中文科目尋找唯一官方 row code，保留已核對的局部消歧規則。"""
    normalized = _normalize_item_name(item_name)
    if not normalized:
        return None
    aliases = _item_name_aliases(normalized)
    for alias_index, alias in enumerate(aliases):
        matches: dict[str, OfficialItemCode] = {}
        for detail in item_codes.get(alias, ()):
            if _item_code_matches_statement(detail.item_code, statement_type):
                matches[detail.item_code] = detail
        if candidate_value is not None:
            if candidate_scale is None or candidate_scale <= 0:
                raise ValueError("candidate_scale is required with candidate_value")
            value_matches = {
                code: detail
                for code, detail in matches.items()
                if _reported_value_matches(
                    detail.reported_value,
                    candidate_value=candidate_value,
                    candidate_scale=candidate_scale,
                )
            }
            # 提供候選數值時，沒有任何官方回報值相等就必須清空；
            # 不能保留未核對的唯一 code，否則錯期別／錯單位仍會被接受。
            matches = value_matches
        if candidate_indent_depth is not None and len(matches) > 1:
            indent_matches = {
                code: detail
                for code, detail in matches.items()
                if detail.indent_depth == candidate_indent_depth
            }
            if indent_matches:
                matches = indent_matches
        if (
            len(matches) > 1
            and candidate_occurrence is not None
            and statement_type == "income_statement"
            and normalized
            in {
                "繼續營業單位淨利(淨損)",
                "停業單位淨利(淨損)",
            }
            and candidate_scale == 100
            and 0 <= candidate_occurrence < len(matches)
        ):
            # MOPS 同時以相同中文名稱列出 basic／diluted EPS；
            # 官方 XBRL 順序與顯示表順序一致，僅對已核對科目使用出現序號。
            ordered = tuple(matches.values())
            matches = {ordered[candidate_occurrence].item_code: ordered[candidate_occurrence]}
        if matches:
            if len(matches) == 1:
                # 先採精確名稱；只有精確名稱無法唯一消歧時才考慮已核對別名。
                return next(iter(matches.values()))
            if alias_index == 0 and len(aliases) > 1:
                # 某些官方 XBRL 會把顯示頁的同一總列與明細列都寫成同名；
                # 只讓明確登錄的別名繼續比對，未登錄的歧義仍 fail-closed。
                continue
            return None
        if alias_index == 0:
            continue
    return None


def _reported_value_matches(
    reported_value: str | None,
    *,
    candidate_value: int,
    candidate_scale: int,
) -> bool:
    if not reported_value:
        return False
    normalized = reported_value.replace(",", "").strip()
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = f"-{normalized[1:-1]}"
    try:
        official_value = Decimal(normalized)
    except InvalidOperation:
        return False
    return official_value == Decimal(candidate_value) / Decimal(candidate_scale)


def _item_name_aliases(normalized: str) -> tuple[str, ...]:
    # 只列入已由 MOPS 顯示頁與 XBRL row 逐一核對的名稱差異；
    # 不以通用「合計／總額」規則改寫科目語意。
    explicit_aliases = {
        "基本每股盈餘": "基本每股盈餘合計",
        "稀釋每股盈餘": "稀釋每股盈餘合計",
        "其他應收款-關係人淨額": "其他應收款-關係人",
        "其他應收款淨額": "其他應收款",
        "保險合約資產及再保險合約資產-淨額": "保險合約資產及再保險合約資產",
        "資產總額": "資產總計",
        "負債總額": "負債總計",
        "權益總額": "權益總計",
        "股本": "股本合計",
        "保留盈餘": "保留盈餘合計",
        "其他權益": "其他權益合計",
        "歸屬於母公司業主之權益": "歸屬於母公司業主之權益合計",
        "權益總計": "權益總額",
        "預收股款(權益項下)之約當發行股數(單位:股)": "預收股款(股東權益項下)之約當發行股數(單位:股)",
        "預收股款(權益項下)之約當發行股數": "預收股款(股東權益項下)之約當發行股數",
        "預收股款(權益項下)之約當發行股數(單位:股)": "預收股款(權益項下)之約當發行股數",
        "銷貨成本": "銷貨成本合計",
        "勞務收入": "勞務收入合計",
        # 3064 的 t164 顯示頁稱「勞務收入淨額」，同一期 XBRL 正式列為 4600「勞務收入合計」；
        # 只在候選數值、報表類型與 XBRL row code 都逐一核對時使用，不推廣成通用合計規則。
        "勞務收入淨額": "勞務收入合計",
        # 3252 的同一期 t164 顯示頁稱「餐旅服務收入淨額」，官方 XBRL
        # 以相同數值與縮排列為 4410「餐旅服務收入」；只接受這個已核對的
        # 名稱對照，值、報表類型與縮排仍由呼叫端逐一驗證。
        "餐旅服務收入淨額": "餐旅服務收入",
        # 3252 的顯示頁將 4400／5400 的列簡寫為「旅遊服務收入／成本」；
        # 官方 XBRL 對應為完整「合計」名稱，僅保留這兩個已核對對照。
        "旅遊服務收入": "旅遊服務收入合計",
        "旅遊服務成本": "旅遊服務成本(觀光飯店業適用)合計",
        # 3379／3402 的 t164 顯示頁稱「工程收入淨額」，同一期官方
        # XBRL row 4520 顯示為「工程收入」；兩家公司都以同一回報值、
        # 報表類型與縮排逐一核對，故只增加這個窄範圍名稱對照。
        "工程收入淨額": "工程收入",
        # 同兩份已保存官方 XBRL 將顯示頁的「營建工程收入」列以
        # 4500「營建工程收入合計」呈現；數值與縮排仍由呼叫端核對。
        "營建工程收入": "營建工程收入合計",
        # 同兩份已保存官方 XBRL 將顯示頁的「營建工程成本」列以
        # 5500「營建工程成本合計」呈現；數值與縮排仍由呼叫端核對。
        "營建工程成本": "營建工程成本合計",
        "勞務成本": "勞務成本合計",
        "待註銷股本股數(單位:股)": "待註銷股本股數",
        "其他收入": "其他收入合計",
        "利息收入": "利息收入合計",
        "營業費用": "營業費用合計",
        "預期信用減損損失(利益)": "預期信用減損損失(利益)淨額",
        "稅前淨利(淨損)": "繼續營業單位稅前淨利(淨損)",
        "繼續營業單位稅前損益": "繼續營業單位稅前淨利(淨損)",
        "本期稅後淨利(淨損)": "本期淨利(淨損)",
        "不重分類至損益之項目:": "不重分類至損益之項目總額",
        "不重分類至損益之項目(稅後)": "不重分類至損益之項目總額(稅後)",
        "後續可能重分類至損益之項目:": "後續可能重分類至損益之項目總額",
        "後續可能重分類至損益之項目(稅後)": "後續可能重分類至損益之項目總額(稅後)",
        "本期其他綜合損益(稅後淨額)": "本期其他綜合損益",
        "母公司業主(淨利/淨損)": "母公司業主",
        "非控制權益(淨利/淨損)": "非控制權益",
        "母公司業主(綜合損益)": "母公司業主",
        "非控制權益(綜合損益)": "非控制股權",
        "非控制股權(綜合損益)": "非控制股權",
        "營業活動之淨現金流入(流出)": "營運產生之現金流入(流出)",
        "避險之金融資產": "避險之金融資產-淨額",
        "權益─具證券性質之虛擬通貨": "權益─具證券性質之虛擬通貨合計",
    }
    alias = explicit_aliases.get(normalized)
    return (normalized, alias) if alias else (normalized,)


def _item_code_matches_statement(item_code: str, statement_type: str | None) -> bool:
    if statement_type is None:
        return True
    if statement_type == "cash_flows_statement":
        return item_code[:1] in {"A", "B", "C", "D", "E"}
    if not item_code[:1].isdigit():
        return False
    if statement_type == "balance_sheet":
        return item_code[0] in {"1", "2", "3"} or item_code == "3X2XX"
    if statement_type == "income_statement":
        return item_code[0] in {"4", "5", "6", "7", "8", "9"}
    return False


def _normalize_item_name(value: str) -> str:
    """移除 XBRL 中文欄位縮排與空白，不改動原始顯示名稱。"""
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(normalized.split())


def _fetch_xbrl_response(
    *,
    stock_code: str,
    roc_year: int,
    season: int,
    timeout_seconds: int,
    market: str | None = None,
    report_basis: str = "consolidated",
    market_identity_evidence: Mapping[str, Any] | None = None,
    encoding_repair: str | None = None,
) -> bytes:
    """取得單一公司單一期別且指定範圍的官方 XBRL row-code 回應。"""
    if report_basis not in _REPORT_BASES:
        raise ValueError(f"unsupported report_basis: {report_basis}")
    response = requests.get(
        MOPS_XBRL_URL,
        params={
            "step": "1",
            "CO_ID": stock_code,
            "SYEAR": str(roc_year + 1911),
            "SSEASON": str(season),
            "REPORT_ID": _REPORT_BASIS_XBRL_ID[report_basis],
        },
        headers={"User-Agent": "technical-analysis-research-readonly/1.0"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    body = response.content
    text = _decode_mops_xbrl(body, encoding_repair=encoding_repair)
    _validate_xbrl_identity(
        text,
        stock_code=stock_code,
        period_year=roc_year + 1911,
        season=season,
        market=market,
        report_basis=report_basis,
        market_identity_evidence=market_identity_evidence,
    )
    return body


def _resolved_regular_input(path: Path, *, description: str) -> Path:
    """解析保存的官方輸入，拒絕別名與非一般檔案。"""
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    resolved = requested.resolve(strict=False)
    if requested.is_symlink() or not requested.is_file() or resolved != requested:
        raise ValueError(f"{description} must be a regular non-alias file")
    return resolved


def _resolved_regular_directory(path: Path, *, description: str) -> Path:
    """解析保存的官方 raw 目錄，拒絕別名與非一般目錄。"""
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    resolved = requested.resolve(strict=False)
    if requested.is_symlink() or not requested.is_dir() or resolved != requested:
        raise ValueError(f"{description} must be a regular non-alias directory")
    return resolved


def _sha256_without_prefix(value: object, *, field: str) -> str:
    """讀取 evidence 內的 SHA-256，允許是否帶 sha256: 前綴。"""
    if not isinstance(value, str):
        raise ValueError(f"listing evidence {field} must be text")
    normalized = value.removeprefix("sha256:").lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ValueError(f"listing evidence {field} must be a SHA-256 digest")
    return normalized


def _validate_saved_listing_evidence(
    evidence_path: Path,
    *,
    listing_path: Path,
    listing_hash: str,
    stock_code: str,
    roc_year: int,
    season: int,
    listing_event: Mapping[str, str],
) -> dict[str, Any]:
    """驗證保存的官方 t57 response evidence 與 HTML、請求、期別一致。"""
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("saved listing evidence must be valid UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("saved listing evidence must be a JSON object")
    if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
        raise ValueError("saved listing evidence must remain research_only")
    request = payload.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("saved listing evidence request is missing")
    if (
        str(request.get("co_id")) != stock_code
        or request.get("roc_year") != roc_year
        or request.get("season") != season
    ):
        raise ValueError("saved listing evidence request does not match the candidate")
    expected_url = _listing_url(stock_code=stock_code, roc_year=roc_year)
    if payload.get("request_url") != expected_url:
        raise ValueError("saved listing evidence request URL does not match the official request")
    http = payload.get("http")
    if not isinstance(http, Mapping) or http.get("status") != 200:
        raise ValueError("saved listing evidence must record HTTP 200")
    if http.get("byte_count") != listing_path.stat().st_size:
        raise ValueError("saved listing evidence byte count does not match the raw response")
    expected_digest = _sha256_without_prefix(listing_hash, field="raw hash")
    evidence_digest = _sha256_without_prefix(http.get("sha256"), field="http.sha256")
    if evidence_digest != expected_digest:
        raise ValueError("saved listing evidence hash does not match the raw response")
    event = payload.get("event")
    if not isinstance(event, Mapping):
        raise ValueError("saved listing evidence event is missing")
    for key in ("stock_code", "period", "period_end", "publication_timestamp", "listing_row_sha256"):
        if event.get(key) != listing_event.get(key):
            raise ValueError(f"saved listing evidence event {key} does not match the parsed listing")
    return {
        "schema_version": str(payload.get("schema_version", "")),
        "source_path": str(evidence_path),
        "source_sha256": _file_sha256_reference(evidence_path),
        "request_url": expected_url,
        "http_status": 200,
        "raw_sha256": _file_sha256_reference(listing_path),
        "event": dict(event),
        "status": "verified_saved_response",
    }


def _parse_ezsearch_timestamp(cdate: object, ctime: object) -> datetime:
    """解析 EZSearch 公告列的台北時區時間。"""
    if not isinstance(cdate, str) or not isinstance(ctime, str):
        raise ValueError("EZSearch announcement date/time is missing")
    date_match = re.fullmatch(r"(\d{3})/(\d{2})/(\d{2})", cdate.strip())
    if date_match is None:
        raise ValueError("EZSearch announcement date is invalid")
    try:
        parsed_time = datetime.strptime(ctime.strip(), "%H:%M:%S").time()
    except ValueError as error:
        raise ValueError("EZSearch announcement time is invalid") from error
    return datetime(
        int(date_match.group(1)) + 1911,
        int(date_match.group(2)),
        int(date_match.group(3)),
        parsed_time.hour,
        parsed_time.minute,
        parsed_time.second,
        tzinfo=_TAIPEI_TIMEZONE,
    )


def _parse_ezsearch_json(body: bytes) -> Mapping[str, Any]:
    """嚴格解析官方 EZSearch JSON，拒絕尾端非 JSON 內容。"""
    try:
        parsed = json.loads(body.decode("utf-8-sig", errors="strict").strip())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("EZSearch raw response is not strict JSON") from error
    if not isinstance(parsed, Mapping):
        raise ValueError("EZSearch raw response must be a JSON object")
    return parsed


def _validate_saved_ezsearch_availability_evidence(
    evidence_path: Path,
    *,
    stock_code: str,
    market: str,
    roc_year: int,
    season: int,
) -> dict[str, Any]:
    """驗證 EZSearch 公告事件及其共享 raw response，不冒充 t57 listing。"""
    resolved_evidence_path = _resolved_regular_input(
        evidence_path,
        description="saved EZSearch availability evidence",
    )
    try:
        payload = json.loads(resolved_evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("EZSearch availability evidence must be valid UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("EZSearch availability evidence must be a JSON object")
    expected_period = f"{roc_year + 1911:04d}-Q{season}"
    expected_period_end = date(
        roc_year + 1911,
        season * 3,
        (31, 30, 30, 31)[season - 1],
    ).isoformat()
    if (
        payload.get("schema_version") != "v4-mops-ezsearch-statement-availability-observation.v1"
        or payload.get("source_id") != "mops.ezsearch.statement_publication"
        or payload.get("source_version") != "mops-ezsearch-statement-publication.v1"
        or payload.get("source_url") != MOPS_EZSEARCH_URL
        or payload.get("stock_code") != stock_code
        or payload.get("market") != market
        or payload.get("period") != expected_period
        or payload.get("period_end") != expected_period_end
        or payload.get("research_only") is not True
        or payload.get("formal_oos_allowed") is not False
    ):
        raise ValueError("EZSearch availability evidence identity or schema is unsupported")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("EZSearch availability evidence records are missing")
    expected_items = set(_EZSEARCH_ITEMS)
    by_item: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("EZSearch availability evidence record must be an object")
        item = record.get("announcement_item")
        if not isinstance(item, str) or item not in expected_items or item in by_item:
            raise ValueError("EZSearch availability evidence item set is incomplete or duplicated")
        by_item[item] = record
    if set(by_item) != expected_items:
        missing = sorted(expected_items - set(by_item))
        raise ValueError(f"EZSearch availability evidence is missing statement items: {missing}")

    event_rows: list[dict[str, Any]] = []
    raw_files: list[dict[str, Any]] = []
    for announcement_item in sorted(expected_items):
        record = by_item[announcement_item]
        if record.get("status") != "matched":
            raise ValueError(
                "EZSearch availability evidence has no unique company/period row: "
                f"item={announcement_item}; status={record.get('status')}"
            )
        request = record.get("request")
        if (
            not isinstance(request, Mapping)
            or request.get("method") != "POST"
            or request.get("url") != MOPS_EZSEARCH_URL
        ):
            raise ValueError("EZSearch availability request is not the official POST endpoint")
        request_data = request.get("data")
        if not isinstance(request_data, Mapping):
            raise ValueError("EZSearch availability request data is missing")
        if request_data.get("TYPEK") != market or request_data.get("PRO_ITEM") != announcement_item:
            raise ValueError("EZSearch availability request market or item does not match")
        try:
            request_started = datetime.fromisoformat(
                str(record.get("request_started_at")).replace("Z", "+00:00")
            )
            response_received = datetime.fromisoformat(
                str(record.get("response_received_at")).replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("EZSearch availability timestamps are invalid") from error
        if (
            request_started.tzinfo is None
            or response_received.tzinfo is None
            or response_received < request_started
        ):
            raise ValueError("EZSearch availability timestamps must be ordered and zoned")
        raw_name = record.get("raw_file")
        if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
            raise ValueError("EZSearch availability raw filename is unsafe")
        raw_path = _resolved_regular_input(
            resolved_evidence_path.parent / raw_name,
            description="saved EZSearch raw response",
        )
        http = record.get("http")
        if not isinstance(http, Mapping) or http.get("status") != 200:
            raise ValueError("EZSearch availability raw response must record HTTP 200")
        expected_raw_hash = _file_sha256_reference(raw_path)
        if (
            http.get("sha256") != expected_raw_hash
            or http.get("byte_count") != raw_path.stat().st_size
        ):
            raise ValueError("EZSearch availability raw hash or byte count does not match")
        raw_payload = _parse_ezsearch_json(raw_path.read_bytes())
        if raw_payload.get("status") != "success":
            raise ValueError("EZSearch availability raw response is not a successful result")
        raw_rows = raw_payload.get("data")
        if not isinstance(raw_rows, list) or not all(isinstance(row, Mapping) for row in raw_rows):
            raise ValueError("EZSearch availability raw data must be a list of objects")
        expected_subject = f"{roc_year}年第{season}季{_EZSEARCH_ITEMS[announcement_item][1]}"
        matches = [
            row
            for row in raw_rows
            if str(row.get("COMPANY_ID", "")).strip() == stock_code
            and str(row.get("AN_CODE", "")).strip() == announcement_item
            and str(row.get("TYPEK", "")).strip() == _EZSEARCH_MARKET_NAMES[market]
            and "".join(str(row.get("SUBJECT", "")).split()) == expected_subject
        ]
        if len(matches) != 1:
            raise ValueError(
                "EZSearch raw response does not contain exactly one requested company/period row: "
                f"item={announcement_item}; matches={len(matches)}"
            )
        matched_row = record.get("matched_row")
        if not isinstance(matched_row, Mapping):
            raise ValueError("EZSearch availability matched row is missing")
        normalized_match = {str(key): str(value) for key, value in matches[0].items()}
        normalized_evidence_row = {str(key): str(value) for key, value in matched_row.items()}
        if normalized_evidence_row != normalized_match:
            raise ValueError("EZSearch availability matched row does not match raw response")
        if record.get("matched_row_sha256") != f"sha256:{_canonical_sha256(normalized_match)}":
            raise ValueError("EZSearch availability matched row hash does not match raw response")
        announcement_at = _parse_ezsearch_timestamp(
            normalized_match.get("CDATE"), normalized_match.get("CTIME")
        )
        if announcement_at > response_received.astimezone(_TAIPEI_TIMEZONE):
            raise ValueError("EZSearch announcement event is later than response capture")
        detail_url = normalized_match.get("HYPERLINK", "")
        parsed_url = urlsplit(detail_url)
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc.lower() != "mopsov.twse.com.tw"
            or parsed_url.path != f"/mops/web/{_EZSEARCH_ITEMS[announcement_item][2]}"
        ):
            raise ValueError("EZSearch detail URL is not the expected official MOPS endpoint")
        detail_query = parse_qs(parsed_url.query, keep_blank_values=True)
        for key, expected in (
            ("co_id", stock_code),
            ("year", str(roc_year)),
            ("season", str(season)),
        ):
            if detail_query.get(key) != [expected]:
                raise ValueError("EZSearch detail URL identity does not match the request")
        raw_files.append(
            {
                "basename": raw_name,
                "sha256": expected_raw_hash,
                "byte_count": raw_path.stat().st_size,
            }
        )
        event_rows.append(
            {
                "announcement_item": announcement_item,
                "announcement_timestamp": announcement_at.isoformat(),
                "detail_url": detail_url,
                "matched_row_sha256": record["matched_row_sha256"],
                "raw_sha256": expected_raw_hash,
            }
        )
    event_hash = "sha256:" + _canonical_sha256(
        sorted(event_rows, key=lambda row: str(row["announcement_item"]))
    )
    sorted_event_rows = sorted(event_rows, key=lambda row: str(row["announcement_item"]))
    event = {
        "stock_code": stock_code,
        "period": expected_period,
        "period_end": expected_period_end,
        "publication_timestamp": max(
            str(row["announcement_timestamp"]) for row in sorted_event_rows
        ),
        "announcement_items": [row["announcement_item"] for row in sorted_event_rows],
        "availability_event_sha256": event_hash,
        "correction_status": "unknown",
        "correction_evidence": "EZSearch 公告事件未提供 t57 correction 欄；未宣稱無修訂",
    }
    validated_evidence = dict(payload)
    validated_evidence["source_sha256"] = _file_sha256_reference(resolved_evidence_path)
    validated_evidence["raw_files"] = raw_files
    validated_evidence["event"] = event
    validated_evidence["status"] = "verified_saved_ezsearch_response"
    return {
        "schema_version": str(payload["schema_version"]),
        "source_id": str(payload["source_id"]),
        "source_version": str(payload["source_version"]),
        "source_url": str(payload["source_url"]),
        "source_path": str(resolved_evidence_path),
        "source_sha256": _file_sha256_reference(resolved_evidence_path),
        "raw_files": raw_files,
        "event": event,
        "evidence": validated_evidence,
        "status": "verified_saved_ezsearch_response",
    }


def _validate_browser_listing_observation(
    evidence_path: Path,
    *,
    listing_path: Path,
    listing_hash: str,
    stock_code: str,
    market: str,
    roc_year: int,
    season: int,
    listing_event: Mapping[str, str],
) -> dict[str, Any]:
    """驗證瀏覽器 DOM 保存的 t57 publication row，但不冒充 HTTP raw。"""
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("browser listing evidence must be valid UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("browser listing evidence must be a JSON object")
    if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
        raise ValueError("browser listing evidence must remain research_only")
    request = payload.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("browser listing evidence request is missing")
    if (
        str(request.get("stock_code")) != stock_code
        or request.get("market") != market
        or request.get("roc_year") != roc_year
        or request.get("season") != season
    ):
        raise ValueError("browser listing evidence request does not match the candidate")
    expected_url = _listing_url(stock_code=stock_code, roc_year=roc_year)
    request_url = request.get("url")
    if request_url != expected_url:
        raise ValueError("browser listing evidence request URL does not match the official request")
    if payload.get("schema_version") != "v4-mops-t57-browser-listing-observation.v2":
        raise ValueError("browser listing evidence schema version is unsupported")
    if payload.get("capture_basis") != "Chrome rendered DOM observation":
        raise ValueError("browser listing evidence must declare the Chrome DOM capture basis")
    def _parse_observed_at(value: object, *, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"browser listing evidence {field} must be an ISO timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError(f"browser listing evidence {field} must include a timezone")
        return parsed

    selector_observed_at = _parse_observed_at(payload.get("observed_at"), field="observed_at")
    capture_completed_at = _parse_observed_at(
        payload.get("capture_completed_at"),
        field="capture_completed_at",
    )
    if selector_observed_at > capture_completed_at:
        raise ValueError("browser selector observation is after capture completion")
    selector_response = payload.get("selector_response")
    if not isinstance(selector_response, Mapping):
        raise ValueError("browser listing evidence selector response is missing")
    selector_dom_name = selector_response.get("saved_dom_artifact")
    if not isinstance(selector_dom_name, str) or not selector_dom_name:
        raise ValueError("browser listing evidence selector DOM artifact is missing")
    selector_dom_path = _resolved_regular_input(
        evidence_path.parent / selector_dom_name,
        description="saved browser selector DOM artifact",
    )
    if selector_response.get("raw_http_bytes_saved") is not False:
        raise ValueError("browser selector evidence must state raw HTTP bytes were not saved")
    if selector_response.get("saved_dom_artifact_bytes") != selector_dom_path.stat().st_size:
        raise ValueError("browser selector DOM byte count does not match the saved artifact")
    selector_digest = _sha256_without_prefix(
        selector_response.get("saved_dom_artifact_sha256"),
        field="selector DOM hash",
    )
    if selector_digest != _sha256_without_prefix(
        _file_sha256_reference(selector_dom_path),
        field="selector DOM input hash",
    ):
        raise ValueError("browser selector DOM hash does not match the saved artifact")
    selector = payload.get("selector_observation")
    if not isinstance(selector, Mapping):
        raise ValueError("browser listing evidence selector observation is missing")
    exact_company = selector.get("exact_requested_company")
    if not isinstance(exact_company, Mapping) or str(exact_company.get("stock_code")) != stock_code:
        raise ValueError("browser listing evidence does not contain the exact requested company")
    publication = payload.get("publication_listing_response")
    if not isinstance(publication, Mapping):
        raise ValueError("browser listing evidence publication response is missing")
    if publication.get("raw_http_bytes_saved") is not False:
        raise ValueError("browser listing evidence must state raw HTTP bytes were not saved")
    if publication.get("result_url") != "https://doc.twse.com.tw/server-java/t57sb01":
        raise ValueError("browser listing evidence result URL is not the official t57 endpoint")
    publication_observed_at = _parse_observed_at(
        publication.get("observed_at"),
        field="publication observed_at",
    )
    if publication_observed_at < selector_observed_at:
        raise ValueError("browser publication observation precedes selector observation")
    if publication_observed_at > capture_completed_at:
        raise ValueError("browser publication observation is after capture completion")
    publication_dom_name = publication.get("saved_dom_artifact")
    if not isinstance(publication_dom_name, str) or not publication_dom_name:
        raise ValueError("browser listing evidence publication DOM artifact is missing")
    publication_dom_path = _resolved_regular_input(
        evidence_path.parent / publication_dom_name,
        description="saved browser publication DOM artifact",
    )
    if publication.get("saved_dom_artifact_bytes") != publication_dom_path.stat().st_size:
        raise ValueError("browser publication DOM byte count does not match the saved artifact")
    publication_dom_digest = _sha256_without_prefix(
        publication.get("saved_dom_artifact_sha256"),
        field="publication DOM hash",
    )
    if publication_dom_digest != _sha256_without_prefix(
        _file_sha256_reference(publication_dom_path),
        field="publication DOM input hash",
    ):
        raise ValueError("browser publication DOM hash does not match the saved artifact")
    try:
        publication_dom_bytes = publication_dom_path.read_bytes()
        publication_dom_text = publication_dom_bytes.decode("utf-8", errors="strict")
        if publication_dom_text.encode("utf-8", errors="strict") != publication_dom_bytes:
            raise ValueError("UTF-8 DOM strict round-trip changed the saved bytes")
        encoding_replay = publication_dom_text.encode("big5", errors="strict")
    except (OSError, UnicodeError) as error:
        raise ValueError(
            "browser publication DOM cannot be strictly re-encoded as Big5"
        ) from error
    if encoding_replay != listing_path.read_bytes():
        raise ValueError(
            "browser Big5 listing replay is not a strict encoding of the saved UTF-8 DOM"
        )
    replay_name = publication.get("encoding_replay_artifact")
    if replay_name != listing_path.name:
        raise ValueError("browser listing evidence encoding artifact does not match the listing input")
    if publication.get("encoding_replay_basis") != (
        "strict_utf8_decode_then_big5_encode_of_saved_dom_artifact"
    ):
        raise ValueError("browser listing evidence encoding replay basis is unsupported")
    replay_digest = _sha256_without_prefix(
        publication.get("encoding_replay_artifact_sha256"),
        field="encoding replay hash",
    )
    expected_digest = _sha256_without_prefix(listing_hash, field="browser listing hash")
    actual_digest = _sha256_without_prefix(
        _file_sha256_reference(listing_path),
        field="browser listing input hash",
    )
    if actual_digest != expected_digest:
        raise ValueError("browser listing input hash does not match the supplied listing hash")
    if replay_digest != expected_digest:
        raise ValueError("browser listing evidence hash does not match the encoding replay artifact")
    if publication.get("encoding_replay_artifact_bytes") != listing_path.stat().st_size:
        raise ValueError("browser listing evidence encoding byte count does not match the artifact")
    row = publication.get("row")
    if not isinstance(row, Mapping):
        raise ValueError("browser listing evidence publication row is missing")
    expected_row = {
        "stock_code": stock_code,
        "period": f"{roc_year + 1911:04d}-Q{season}",
        "period_end": listing_event["period_end"],
        "publication_timestamp": listing_event["publication_timestamp"],
        "document_filename": listing_event["document_filename"],
        "file_size_bytes": listing_event["document_size_bytes"],
        "listing_row_sha256": listing_event["listing_row_sha256"],
    }
    actual_row = {
        "stock_code": str(row.get("stock_code")),
        "period": str(row.get("period")),
        "period_end": str(row.get("period_end")),
        "publication_timestamp": str(row.get("upload_timestamp")),
        "document_filename": str(row.get("file_name")),
        "file_size_bytes": str(row.get("file_size_bytes")),
        "listing_row_sha256": _sha256_without_prefix(
            row.get("listing_row_sha256"),
            field="publication row hash",
        ),
    }
    expected_row["listing_row_sha256"] = _sha256_without_prefix(
        expected_row["listing_row_sha256"],
        field="parsed listing row hash",
    )
    if actual_row != expected_row:
        raise ValueError("browser listing evidence publication row does not match the parsed listing")
    return {
        "schema_version": str(payload.get("schema_version", "")),
        "source_path": str(evidence_path),
        "source_sha256": _file_sha256_reference(evidence_path),
        "request_url": expected_url,
        "http_status": None,
        "raw_sha256": _file_sha256_reference(listing_path),
        "raw_custody": False,
        "capture_basis": "Chrome rendered DOM observation",
        "capture_completed_at": capture_completed_at.isoformat(),
        "browser_dom_artifacts": {
            "selector": selector_dom_name,
            "publication": publication_dom_name,
        },
        "encoding_replay_artifact": replay_name,
        "event": dict(listing_event),
        "status": "browser_observed_response",
    }


def _validate_xbrl_identity(
    html_text: str,
    *,
    stock_code: str,
    period_year: int,
    season: int,
    market: str | None = None,
    report_basis: str = "consolidated",
    market_identity_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """以官方隱藏 metadata 精確核對公司、期別、報表範圍與市場。"""
    if report_basis not in _REPORT_BASES:
        raise ValueError(f"unsupported report_basis: {report_basis}")
    metadata = parse_xbrl_metadata(html_text)
    if metadata.get("companyid") != stock_code:
        raise ValueError("MOPS XBRL response company code does not match the request")
    if metadata.get("year") != str(period_year) or metadata.get("quarter") != str(season):
        raise ValueError("MOPS XBRL response period does not match the request")
    expected_category = _REPORT_BASIS_XBRL_CATEGORY[report_basis]
    if metadata.get("reportcategory") != expected_category:
        raise ValueError(
            "MOPS XBRL response report category does not match the requested report basis; "
            f"expected={expected_category}"
        )
    expected_market = {
        "sii": "Listed company",
        "otc": "Over-the-counter",
    }.get(market or "")
    if expected_market is not None and metadata.get("market") != expected_market:
        actual_market = metadata.get("market")
        # EZSearch 的三筆官方公告列會保留市場 TYPEK；少數上櫃公司
        # t164 XBRL 隱藏欄位誤標 Listed company。只有同一期、同公司、三種
        # 公告列都已由 strict evidence 驗證時，才接受這個明確且可追溯的衝突，
        # 並把 XBRL 原值留在 lineage，不把它改寫成 OTC。
        if not (
            market == "otc"
            and actual_market == "Listed company"
            and _is_verified_ezsearch_market_identity(
                market_identity_evidence,
                stock_code=stock_code,
                period_year=period_year,
                season=season,
            )
        ):
            raise ValueError("MOPS XBRL response market does not match the request")
        assert market_identity_evidence is not None
        event = market_identity_evidence["event"]
        return {
            "status": "explicit_official_market_metadata_conflict",
            "requested_market": market,
            "xbrl_metadata_market": actual_market,
            "market_identity_basis": "verified EZSearch TYPEK exact company-period rows",
            "evidence_sha256": market_identity_evidence["source_sha256"],
            "availability_event_sha256": event["availability_event_sha256"],
        }
    return None


def _is_verified_ezsearch_market_identity(
    evidence: Mapping[str, Any] | None,
    *,
    stock_code: str,
    period_year: int,
    season: int,
) -> bool:
    """只接受已由 strict EZSearch validator 產生的市場交叉核對結果。"""
    if not isinstance(evidence, Mapping):
        return False
    if (
        evidence.get("status") != "verified_saved_ezsearch_response"
        or evidence.get("source_id") != "mops.ezsearch.statement_publication"
        or evidence.get("source_version") != "mops-ezsearch-statement-publication.v1"
        or evidence.get("source_url") != MOPS_EZSEARCH_URL
        or evidence.get("source_sha256") is None
    ):
        return False
    event = evidence.get("event")
    if not isinstance(event, Mapping):
        return False
    expected_period = f"{period_year:04d}-Q{season}"
    if (
        event.get("stock_code") != stock_code
        or event.get("period") != expected_period
        or event.get("period_end")
        != date(period_year, season * 3, (31, 30, 30, 31)[season - 1]).isoformat()
        or event.get("announcement_items") != sorted(_EZSEARCH_ITEMS)
        or not isinstance(event.get("availability_event_sha256"), str)
    ):
        return False
    return True


def _xbrl_request_url(
    *, stock_code: str, roc_year: int, season: int, report_basis: str = "consolidated"
) -> str:
    """建立單一公司單一期別的官方 t164 XBRL 查詢 URL。"""
    if report_basis not in _REPORT_BASES:
        raise ValueError(f"unsupported report_basis: {report_basis}")
    return (
        f"{MOPS_XBRL_URL}?step=1&CO_ID={stock_code}"
        f"&SYEAR={roc_year + 1911}&SSEASON={season}"
        f"&REPORT_ID={_REPORT_BASIS_XBRL_ID[report_basis]}"
    )


def _official_xbrl_url_matches(
    value: object,
    *,
    stock_code: str,
    roc_year: int,
    season: int,
    report_basis: str = "consolidated",
) -> bool:
    """只接受官方 t164 XBRL 路徑及完整、精確的查詢參數。"""
    if report_basis not in _REPORT_BASES:
        return False
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "mopsov.twse.com.tw"
        or parsed.path != "/server-java/t164sb01"
        or parsed.fragment
    ):
        return False
    expected = {
        "step": "1",
        "CO_ID": stock_code,
        "SYEAR": str(roc_year + 1911),
        "SSEASON": str(season),
        "REPORT_ID": _REPORT_BASIS_XBRL_ID[report_basis],
    }
    query = parse_qs(parsed.query, keep_blank_values=True)
    return set(query) == set(expected) and all(query[key] == [value] for key, value in expected.items())


def _validate_browser_xbrl_observation(
    evidence_path: Path,
    *,
    dom_path: Path,
    stock_code: str,
    market: str,
    roc_year: int,
    season: int,
    report_basis: str = "consolidated",
) -> dict[str, Any]:
    """驗證官方 t164 XBRL 的瀏覽器 DOM observation，不冒充 HTTP raw。"""
    resolved_evidence_path = _resolved_regular_input(
        evidence_path,
        description="saved browser XBRL evidence",
    )
    resolved_dom_path = _resolved_regular_input(
        dom_path,
        description="saved browser XBRL DOM",
    )
    try:
        payload = json.loads(resolved_evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("browser XBRL evidence must be valid UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("browser XBRL evidence must be a JSON object")
    if (
        payload.get("schema_version") != "v4-mops-t164-browser-observation.v1"
        or payload.get("capture_basis") != "Chrome rendered DOM observation"
    ):
        raise ValueError("browser XBRL evidence schema or capture basis is unsupported")
    if payload.get("research_only") is not True or payload.get("formal_oos_allowed") is not False:
        raise ValueError("browser XBRL evidence must remain research_only")

    def _parse_timestamp(value: object, *, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"browser XBRL evidence {field} must be an ISO timestamp") from error
        if parsed.tzinfo is None:
            raise ValueError(f"browser XBRL evidence {field} must include a timezone")
        return parsed

    observed_at = _parse_timestamp(payload.get("observed_at"), field="observed_at")
    capture_completed_at = _parse_timestamp(
        payload.get("capture_completed_at"),
        field="capture_completed_at",
    )
    if observed_at > capture_completed_at:
        raise ValueError("browser XBRL observation is after capture completion")
    request = payload.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("browser XBRL evidence request is missing")
    if (
        request.get("method") != "GET"
        or str(request.get("stock_code")) != stock_code
        or request.get("market") != market
        or request.get("roc_year") != roc_year
        or request.get("season") != season
        or not _official_xbrl_url_matches(
            request.get("url"),
            stock_code=stock_code,
            roc_year=roc_year,
            season=season,
            report_basis=report_basis,
        )
    ):
        raise ValueError("browser XBRL evidence request does not match the candidate")
    if not _official_xbrl_url_matches(
        payload.get("result_url"),
        stock_code=stock_code,
        roc_year=roc_year,
        season=season,
        report_basis=report_basis,
    ):
        raise ValueError("browser XBRL evidence result URL is not the official t164 endpoint")
    if payload.get("raw_http_bytes_saved") is not False:
        raise ValueError("browser XBRL evidence must state raw HTTP bytes were not saved")

    saved_name = payload.get("saved_dom_artifact")
    if not isinstance(saved_name, str) or not saved_name or Path(saved_name).name != saved_name:
        raise ValueError("browser XBRL evidence DOM artifact name is unsafe")
    evidence_dom = _resolved_regular_input(
        resolved_evidence_path.parent / saved_name,
        description="saved browser XBRL DOM artifact",
    )
    if (
        evidence_dom != resolved_dom_path
        or evidence_dom.parent != resolved_evidence_path.parent
    ):
        raise ValueError("browser XBRL DOM artifact must be the evidence directory artifact")
    dom_bytes = evidence_dom.read_bytes()
    if payload.get("saved_dom_artifact_bytes") != len(dom_bytes):
        raise ValueError("browser XBRL DOM byte count does not match the saved artifact")
    dom_hash = _sha256_without_prefix(
        payload.get("saved_dom_artifact_sha256"),
        field="saved DOM hash",
    )
    if dom_hash != _sha256_without_prefix(
        _file_sha256_reference(evidence_dom),
        field="saved DOM input hash",
    ):
        raise ValueError("browser XBRL DOM hash does not match the saved artifact")
    try:
        dom_text = dom_bytes.decode("utf-8", errors="strict")
        if dom_text.encode("utf-8", errors="strict") != dom_bytes:
            raise ValueError("UTF-8 DOM strict round-trip changed the saved bytes")
    except (OSError, UnicodeError) as error:
        raise ValueError("browser XBRL DOM is not a strict UTF-8 artifact") from error

    expected_metadata = {
        "companyid": stock_code,
        "year": str(roc_year + 1911),
        "quarter": str(season),
        "reportcategory": _REPORT_BASIS_XBRL_CATEGORY[report_basis],
        "market": {
            "sii": "Listed company",
            "otc": "Over-the-counter",
        }.get(market, ""),
    }
    metadata = parse_xbrl_metadata(dom_text)
    if metadata != expected_metadata:
        raise ValueError("browser XBRL DOM identity does not match the candidate")
    evidence_identity = payload.get("identity")
    if not isinstance(evidence_identity, Mapping) or dict(evidence_identity) != metadata:
        raise ValueError("browser XBRL evidence identity does not match the DOM metadata")
    codes = parse_xbrl_item_codes(dom_text)
    code_count = sum(len(details) for details in codes.values())
    if not codes or code_count == 0:
        raise ValueError("browser XBRL DOM contains no official row codes")
    if payload.get("official_name_count") != len(codes) or payload.get("official_row_count") != code_count:
        raise ValueError("browser XBRL evidence code counts do not match the DOM")
    return {
        "schema_version": str(payload["schema_version"]),
        "source_path": str(resolved_evidence_path),
        "source_sha256": _file_sha256_reference(resolved_evidence_path),
        "request_url": _xbrl_request_url(
            stock_code=stock_code,
            roc_year=roc_year,
            season=season,
            report_basis=report_basis,
        ),
        "result_url": str(payload["result_url"]),
        "http_status": None,
        "raw_sha256": _file_sha256_reference(evidence_dom),
        "raw_custody": False,
        "capture_basis": "Chrome rendered DOM observation",
        "capture_time_basis": str(payload.get("capture_time_basis", "")),
        "capture_completed_at": capture_completed_at.isoformat(),
        "metadata": metadata,
        "official_name_count": len(codes),
        "official_row_count": code_count,
        "status": "browser_observed_response",
    }


def _validate_saved_statement_http_evidence(
    evidence_path: Path,
    *,
    raw_dir: Path,
    stock_code: str,
    market: str,
    roc_year: int,
    season: int,
    report_basis: str = "consolidated",
) -> dict[str, Any]:
    """驗證 replay 三張 t164 HTTP raw 及其請求／hash evidence。"""
    resolved_evidence_path = _resolved_regular_input(
        evidence_path,
        description="saved statement HTTP evidence",
    )
    resolved_raw_dir = _resolved_regular_directory(
        raw_dir,
        description="saved statement raw directory",
    )
    if resolved_evidence_path.parent != resolved_raw_dir:
        raise ValueError("statement HTTP evidence must be beside its saved raw responses")
    try:
        payload = json.loads(resolved_evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("statement HTTP evidence must be valid UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("statement HTTP evidence must be a JSON object")
    if report_basis not in _REPORT_BASES:
        raise ValueError(f"unsupported report_basis: {report_basis}")
    if (
        payload.get("schema_version") != "v4-mops-statement-http-observation.v1"
        or payload.get("stock_code") != stock_code
        or payload.get("market") != market
        or payload.get("period") != f"{roc_year + 1911:04d}-Q{season}"
        or payload.get("research_only") is not True
        or payload.get("formal_oos_allowed") is not False
        or payload.get("report_basis", "consolidated") != report_basis
    ):
        raise ValueError("statement HTTP evidence identity or schema is unsupported")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("statement HTTP evidence records are missing")
    expected_endpoints = {
        endpoint: statement_type for statement_type, (endpoint, _, _) in MOPS_STATEMENT_ENDPOINTS.items()
    }
    seen: set[str] = set()
    raw_files: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("statement HTTP evidence record must be an object")
        endpoint = record.get("endpoint")
        statement_type = record.get("statement_type")
        if (
            not isinstance(endpoint, str)
            or endpoint not in expected_endpoints
            or statement_type != expected_endpoints[endpoint]
            or endpoint in seen
        ):
            raise ValueError("statement HTTP evidence endpoint set is incomplete or duplicated")
        seen.add(endpoint)
        if record.get("method") != "POST":
            raise ValueError("statement HTTP evidence must record POST requests")
        expected_url = f"{MOPS_STATEMENT_BASE_URL}/{endpoint}"
        if record.get("request_url") != expected_url:
            raise ValueError("statement HTTP evidence request URL is not the official endpoint")
        request_data = record.get("request_data")
        if not isinstance(request_data, Mapping):
            raise ValueError("statement HTTP evidence request data is missing")
        expected_data = {
            "co_id": stock_code,
            "TYPEK": market,
            "year": str(roc_year),
            "season": str(season),
        }
        if any(request_data.get(key) != value for key, value in expected_data.items()):
            raise ValueError("statement HTTP evidence request data does not match the candidate")
        try:
            started = datetime.fromisoformat(str(record.get("request_started_at")).replace("Z", "+00:00"))
            received = datetime.fromisoformat(str(record.get("response_received_at")).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("statement HTTP evidence timestamps are invalid") from error
        if started.tzinfo is None or received.tzinfo is None or received < started:
            raise ValueError("statement HTTP evidence timestamps must be ordered and zoned")
        raw_name = record.get("raw_file")
        expected_name = f"{endpoint}_{stock_code}_{roc_year}Q{season}.html"
        if not isinstance(raw_name, str) or raw_name != expected_name or Path(raw_name).name != raw_name:
            raise ValueError("statement HTTP evidence raw filename does not match the request")
        raw_path = _resolved_regular_input(
            resolved_raw_dir / raw_name,
            description="saved statement raw response",
        )
        http = record.get("http")
        if not isinstance(http, Mapping) or http.get("status") != 200:
            raise ValueError("statement HTTP evidence must record HTTP 200")
        raw_hash = _sha256_without_prefix(
            _file_sha256_reference(raw_path),
            field="statement raw hash",
        )
        evidence_hash = _sha256_without_prefix(http.get("sha256"), field="statement HTTP hash")
        if raw_hash != evidence_hash or http.get("byte_count") != raw_path.stat().st_size:
            raise ValueError("statement HTTP evidence hash or byte count does not match the raw response")
        raw_files[endpoint] = {
            "basename": raw_name,
            "sha256": _file_sha256_reference(raw_path),
            "byte_count": raw_path.stat().st_size,
        }
    if seen != set(expected_endpoints):
        raise ValueError("statement HTTP evidence must cover all three official statement endpoints")
    return {
        "schema_version": str(payload["schema_version"]),
        "source_path": str(resolved_evidence_path),
        "source_sha256": _file_sha256_reference(resolved_evidence_path),
        "capture_mode": "previously_saved_official_response",
        "raw_custody": True,
        "record_count": len(records),
        "raw_files": raw_files,
        "status": "verified_saved_statement_http",
    }


def build_candidate(
    *,
    stock_code: str,
    roc_year: int,
    season: int,
    market: str,
    output_root: Path,
    run_id: str,
    canonical_manifest: Path,
    canonical_dataset: Path,
    timeout_seconds: int,
    report_basis: str = "consolidated",
    listing_response_path: Path | None = None,
    listing_evidence_path: Path | None = None,
    listing_browser_evidence_path: Path | None = None,
    ezsearch_availability_evidence_path: Path | None = None,
    statement_raw_dir: Path | None = None,
    xbrl_browser_dom_path: Path | None = None,
    xbrl_browser_evidence_path: Path | None = None,
    xbrl_encoding_repair: str | None = None,
    partial_output_root: Path | None = None,
) -> dict[str, Path]:
    _validate_inputs(
        stock_code=stock_code,
        roc_year=roc_year,
        season=season,
        market=market,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        report_basis=report_basis,
    )
    config = TWStockConfig()
    target = resolve_development_output_dir(
        output_root,
        run_id,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    if target.exists():
        raise ValueError("run output already exists; immutable candidates require a new run_id")
    if not canonical_manifest.is_file() or not canonical_dataset.is_file():
        raise ValueError("canonical manifest and dataset must both exist")
    if (xbrl_browser_dom_path is None) != (xbrl_browser_evidence_path is None):
        raise ValueError("browser XBRL DOM and evidence must be supplied together")

    partial_target: Path | None = None
    if partial_output_root is not None:
        partial_target = resolve_development_output_dir(
            partial_output_root,
            run_id,
            data_root=Path(config.data_root),
            formal_db=Path(config.db_file),
        )
        if partial_target == target:
            raise ValueError("partial output must be separate from the completed child output")

    validated_ezsearch_result: dict[str, Any] | None = None
    if ezsearch_availability_evidence_path is not None:
        validated_ezsearch_result = _validate_saved_ezsearch_availability_evidence(
            ezsearch_availability_evidence_path,
            stock_code=stock_code,
            market=market,
            roc_year=roc_year,
            season=season,
        )

    capture_started_at = datetime.now(timezone.utc).isoformat()
    safe_root = target.parent
    safe_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=safe_root))
    current_phase = "initializing"
    xbrl_name = f"mops_t164sb01_xbrl_{stock_code}_{roc_year}Q{season}.html"
    try:
        raw_dir = staging / "raw"
        raw_dir.mkdir()
        replay_raw_dir = (
            _resolved_regular_directory(
                statement_raw_dir,
                description="saved statement raw directory",
            )
            if statement_raw_dir is not None
            else None
        )
        statement_replay_evidence: dict[str, Any] | None = None
        if replay_raw_dir is not None:
            replay_evidence_path = replay_raw_dir / "evidence.json"
            if replay_evidence_path.is_file():
                statement_replay_evidence = _validate_saved_statement_http_evidence(
                    replay_evidence_path,
                    raw_dir=replay_raw_dir,
                    stock_code=stock_code,
                    market=market,
                    roc_year=roc_year,
                    season=season,
                    report_basis=report_basis,
                )
        statement_capture_mode = (
            "previously_saved_official_response"
            if replay_raw_dir is not None
            else "live_official_request"
        )
        parsed_tables: list[StatementTableParseResult] = []
        statement_live_records: list[dict[str, Any]] = []
        current_phase = "statement_fetch"
        for statement_type in MOPS_STATEMENT_ENDPOINTS:
            expected_endpoint = MOPS_STATEMENT_ENDPOINTS[statement_type][0]
            expected_name = f"{expected_endpoint}_{stock_code}_{roc_year}Q{season}.html"
            if replay_raw_dir is None:
                request_started_at = datetime.now(timezone.utc).isoformat()
                response_body = _fetch_statement_response(
                    stock_code=stock_code,
                    market=market,
                    roc_year=roc_year,
                    season=season,
                    statement_type=statement_type,
                    timeout_seconds=timeout_seconds,
                    report_basis=report_basis,
                )
                response_received_at = datetime.now(timezone.utc).isoformat()
            else:
                replay_path = _resolved_regular_input(
                    replay_raw_dir / expected_name,
                    description="saved statement raw response",
                )
                response_body = replay_path.read_bytes()
            statement_path = raw_dir / f"{MOPS_STATEMENT_ENDPOINTS[statement_type][0]}_{stock_code}_{roc_year}Q{season}.html"
            statement_path.write_bytes(response_body)
            if replay_raw_dir is None:
                statement_live_records.append(
                    {
                        "endpoint": expected_endpoint,
                        "statement_type": statement_type,
                        "method": "POST",
                        "request_url": f"{MOPS_STATEMENT_BASE_URL}/{expected_endpoint}",
                        "request_data": {
                            "encodeURIComponent": "1",
                            "step": "1",
                            "firstin": "1",
                            "off": "1",
                            "co_id": stock_code,
                            "TYPEK": market,
                            "year": str(roc_year),
                            "season": str(season),
                        },
                        "request_started_at": request_started_at,
                        "response_received_at": response_received_at,
                        "raw_file": statement_path.name,
                        "http": {
                            "status": 200,
                            "byte_count": statement_path.stat().st_size,
                            "sha256": _file_sha256_reference(statement_path),
                        },
                    }
                )
            parsed_tables.append(
                parse_statement_table(
                    response_body.decode("utf-8", errors="strict"),
                    statement_type=statement_type,
                    roc_year=roc_year,
                    season=season,
                    report_basis=report_basis,
                )
            )

        if replay_raw_dir is None:
            # 先固定 live t164 三筆的 request／response 時間與內容 hash；
            # 後續 XBRL 或 listing 失敗時，下一次可只重用這些 raw。
            _write_json(
                raw_dir / "evidence.json",
                {
                    "schema_version": "v4-mops-statement-http-observation.v1",
                    "stock_code": stock_code,
                    "market": market,
                    "period": f"{roc_year + 1911:04d}-Q{season}",
                    "report_basis": report_basis,
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "capture_mode": "live_official_request",
                    "records": statement_live_records,
                },
            )

        xbrl_browser_evidence: dict[str, Any] | None = None
        xbrl_browser_evidence_copy_path: Path | None = None
        xbrl_identity_conflict: dict[str, Any] | None = None
        current_phase = "xbrl_fetch"
        if xbrl_browser_dom_path is not None and xbrl_browser_evidence_path is not None:
            xbrl_input = _resolved_regular_input(
                xbrl_browser_dom_path,
                description="saved browser XBRL DOM",
            )
            xbrl_evidence_input = _resolved_regular_input(
                xbrl_browser_evidence_path,
                description="saved browser XBRL evidence",
            )
            xbrl_browser_evidence = _validate_browser_xbrl_observation(
                xbrl_evidence_input,
                dom_path=xbrl_input,
                stock_code=stock_code,
                market=market,
                roc_year=roc_year,
                season=season,
                report_basis=report_basis,
            )
            xbrl_response = xbrl_input.read_bytes()
            xbrl_text = xbrl_response.decode("utf-8", errors="strict")
            xbrl_capture_mode = "browser_rendered_dom_observation"
            xbrl_artifact_kind = "browser_dom_utf8"
            xbrl_raw_custody = False
        elif replay_raw_dir is None:
            xbrl_response = _fetch_xbrl_response(
                stock_code=stock_code,
                roc_year=roc_year,
                season=season,
                timeout_seconds=timeout_seconds,
                market=market,
                report_basis=report_basis,
                market_identity_evidence=validated_ezsearch_result,
                encoding_repair=xbrl_encoding_repair,
            )
            xbrl_text = _decode_mops_xbrl(
                xbrl_response,
                encoding_repair=xbrl_encoding_repair,
            )
            xbrl_capture_mode = "live_official_request"
            xbrl_artifact_kind = "http_response_bytes"
            xbrl_raw_custody = True
        else:
            xbrl_input = _resolved_regular_input(
                replay_raw_dir / xbrl_name,
                description="saved XBRL raw response",
            )
            xbrl_response = xbrl_input.read_bytes()
            xbrl_text = _decode_mops_xbrl(
                xbrl_response,
                encoding_repair=xbrl_encoding_repair,
            )
            xbrl_capture_mode = "previously_saved_official_response"
            xbrl_artifact_kind = "http_response_bytes"
            xbrl_raw_custody = True
        if xbrl_browser_evidence is None:
            xbrl_identity_conflict = _validate_xbrl_identity(
                xbrl_text,
                stock_code=stock_code,
                period_year=roc_year + 1911,
                season=season,
                market=market,
                report_basis=report_basis,
                market_identity_evidence=validated_ezsearch_result,
            )
        xbrl_encoding = (
            {
                "declared_encoding": "utf-8",
                "decoder": "utf-8",
                "repair": None,
                "removed_byte_count": 0,
                "raw_bytes_preserved": True,
            }
            if xbrl_browser_evidence is not None
            else _xbrl_encoding_lineage(
                xbrl_response,
                encoding_repair=xbrl_encoding_repair,
            )
        )
        xbrl_path = raw_dir / xbrl_name
        xbrl_path.write_bytes(xbrl_response)
        if xbrl_browser_evidence is not None and xbrl_browser_evidence_path is not None:
            xbrl_evidence_payload = json.loads(
                _resolved_regular_input(
                    xbrl_browser_evidence_path,
                    description="saved browser XBRL evidence",
                ).read_text(encoding="utf-8")
            )
            if not isinstance(xbrl_evidence_payload, dict):
                raise ValueError("browser XBRL evidence must be a JSON object")
            xbrl_evidence_payload["saved_dom_artifact"] = xbrl_path.name
            xbrl_evidence_payload["saved_dom_artifact_bytes"] = xbrl_path.stat().st_size
            xbrl_evidence_payload["saved_dom_artifact_sha256"] = _file_sha256_reference(xbrl_path)
            xbrl_browser_evidence_copy_path = raw_dir / f"{xbrl_path.name}.evidence.json"
            _write_json(xbrl_browser_evidence_copy_path, xbrl_evidence_payload)
            xbrl_browser_evidence["copied_evidence_path"] = str(xbrl_browser_evidence_copy_path)
            xbrl_browser_evidence["copied_evidence_sha256"] = _file_sha256_reference(
                xbrl_browser_evidence_copy_path
            )
        xbrl_codes = parse_xbrl_item_codes(xbrl_text)
        xbrl_hash = _file_sha256_reference(xbrl_path)
        statement_replay_evidence_copy_path: Path | None = None
        if statement_replay_evidence is not None and replay_raw_dir is not None:
            replay_evidence_input = _resolved_regular_input(
                replay_raw_dir / "evidence.json",
                description="saved statement HTTP evidence",
            )
            statement_replay_evidence_copy_path = raw_dir / "statement-http-evidence.json"
            shutil.copyfile(replay_evidence_input, statement_replay_evidence_copy_path)
            statement_replay_evidence["copied_evidence_basename"] = (
                statement_replay_evidence_copy_path.name
            )
            statement_replay_evidence["copied_evidence_sha256"] = _file_sha256_reference(
                statement_replay_evidence_copy_path
            )

        current_phase = "listing_fetch"
        if (
            ezsearch_availability_evidence_path is not None
            and (
                listing_response_path is not None
                or listing_evidence_path is not None
                or listing_browser_evidence_path is not None
            )
        ):
            raise ValueError("EZSearch availability evidence is mutually exclusive with t57 listing inputs")
        if listing_evidence_path is not None and listing_browser_evidence_path is not None:
            raise ValueError("listing HTTP evidence and browser evidence are mutually exclusive")
        listing_evidence: dict[str, Any] | None = None
        availability_source_id = "mops.document_listing.statement_publication"
        availability_source_version = "mops-t57sb01.v1"
        availability_source_url = _listing_url(stock_code=stock_code, roc_year=roc_year)
        availability_raw_files: list[dict[str, Any]] = []
        listing_path: Path | None = None
        expected_period = f"{roc_year + 1911:04d}-Q{season}"
        if ezsearch_availability_evidence_path is not None:
            if validated_ezsearch_result is None:
                raise ValueError("EZSearch availability evidence validation was not completed")
            ezsearch_result = validated_ezsearch_result
            listing_event = ezsearch_result["event"]
            listing_evidence = ezsearch_result["evidence"]
            listing_capture_mode = "ezsearch_saved_official_response"
            listing_evidence_status = "verified_ezsearch_response"
            listing_input_sha256 = ezsearch_result["source_sha256"]
            availability_source_id = str(ezsearch_result["source_id"])
            availability_source_version = str(ezsearch_result["source_version"])
            availability_source_url = str(ezsearch_result["source_url"])
            for raw_file in ezsearch_result["raw_files"]:
                if not isinstance(raw_file, Mapping):
                    raise ValueError("EZSearch availability raw file metadata is malformed")
                raw_name = raw_file.get("basename")
                if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
                    raise ValueError("EZSearch availability raw filename is unsafe")
                source_raw = _resolved_regular_input(
                    Path(ezsearch_availability_evidence_path).parent / raw_name,
                    description="saved EZSearch availability raw response",
                )
                destination_raw = raw_dir / source_raw.name
                shutil.copyfile(source_raw, destination_raw)
                copied_raw = {
                    "basename": destination_raw.name,
                    "sha256": _file_sha256_reference(destination_raw),
                    "byte_count": destination_raw.stat().st_size,
                    "artifact_kind": "http_response_bytes",
                    "raw_custody": True,
                }
                availability_raw_files.append(copied_raw)
            availability_evidence_copy_path = raw_dir / "mops-ezsearch-availability-evidence.json"
            shutil.copyfile(
                _resolved_regular_input(
                    ezsearch_availability_evidence_path,
                    description="saved EZSearch availability evidence",
                ),
                availability_evidence_copy_path,
            )
            listing_evidence["copied_evidence_path"] = str(availability_evidence_copy_path)
            listing_evidence["copied_evidence_sha256"] = _file_sha256_reference(
                availability_evidence_copy_path
            )
        elif listing_response_path is None:
            if listing_evidence_path is not None or listing_browser_evidence_path is not None:
                raise ValueError("listing evidence requires a saved listing response")
            listing_response = _fetch_listing_response(
                stock_code=stock_code,
                roc_year=roc_year,
                timeout_seconds=timeout_seconds,
            )
            listing_capture_mode = "live_official_request"
            listing_input_sha256 = None
            listing_path = raw_dir / f"mops_t57sb01_{stock_code}_{roc_year}.html"
            listing_path.write_bytes(listing_response)
            listing_event = parse_listing_event(
                listing_response,
                stock_code=stock_code,
                roc_year=roc_year,
                season=season,
            )
        else:
            listing_input = _resolved_regular_input(
                listing_response_path,
                description="saved official listing response",
            )
            listing_response = listing_input.read_bytes()
            listing_capture_mode = "previously_saved_official_response"
            listing_input_sha256 = _file_sha256_reference(listing_input)
            listing_path = raw_dir / f"mops_t57sb01_{stock_code}_{roc_year}.html"
            listing_path.write_bytes(listing_response)
            listing_event = parse_listing_event(
                listing_response,
                stock_code=stock_code,
                roc_year=roc_year,
                season=season,
            )
        if ezsearch_availability_evidence_path is None and listing_event["period"] != expected_period:
            raise ValueError(
                "MOPS listing period does not match the requested period; "
                f"requested={expected_period}; actual={listing_event['period']}"
            )
        listing_evidence_copy_path: Path | None = None
        if ezsearch_availability_evidence_path is not None:
            listing_evidence_copy_path = availability_evidence_copy_path
        elif listing_response_path is None:
            listing_evidence_status = "live_official_request"
        elif listing_browser_evidence_path is not None:
            evidence_input = _resolved_regular_input(
                listing_browser_evidence_path,
                description="saved browser listing evidence",
            )
            if evidence_input == listing_input:
                raise ValueError("saved browser evidence must be separate from the raw response")
            listing_evidence = _validate_browser_listing_observation(
                evidence_input,
                listing_path=listing_input,
                listing_hash=str(listing_input_sha256),
                stock_code=stock_code,
                market=market,
                roc_year=roc_year,
                season=season,
                listing_event=listing_event,
            )
            listing_evidence_copy_path = raw_dir / (
                f"mops_t57sb01_{stock_code}_{roc_year}.evidence.json"
            )
            browser_artifacts = listing_evidence.get("browser_dom_artifacts")
            if not isinstance(browser_artifacts, Mapping):
                raise ValueError("browser listing evidence did not expose DOM artifact lineage")
            copied_browser_artifacts: dict[str, str] = {}
            for artifact_key in ("selector", "publication"):
                artifact_name = browser_artifacts.get(artifact_key)
                if not isinstance(artifact_name, str) or not artifact_name:
                    raise ValueError(
                        f"browser listing evidence {artifact_key} DOM artifact is missing"
                    )
                artifact_input = _resolved_regular_input(
                    evidence_input.parent / artifact_name,
                    description=f"saved browser {artifact_key} DOM artifact",
                )
                artifact_output = raw_dir / artifact_input.name
                if artifact_input != artifact_output:
                    shutil.copyfile(artifact_input, artifact_output)
                copied_browser_artifacts[artifact_key] = artifact_output.name

            # 子 run 的 raw listing 會使用固定 basename；複製 evidence 時同步改寫
            # replay artifact 名稱與 hash，讓 immutable child 可以獨立重驗。
            try:
                browser_evidence_payload = json.loads(
                    evidence_input.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("browser listing evidence must be valid UTF-8 JSON") from error
            if not isinstance(browser_evidence_payload, dict):
                raise ValueError("browser listing evidence must be a JSON object")
            publication_payload = browser_evidence_payload.get("publication_listing_response")
            if not isinstance(publication_payload, dict):
                raise ValueError("browser listing evidence publication response is missing")
            if listing_path is None:
                raise ValueError("browser listing raw copy path is missing")
            listing_output_path = listing_path
            if listing_evidence_copy_path is None:
                raise ValueError("browser listing evidence copy path is missing")
            listing_copy_path = listing_evidence_copy_path
            publication_payload = dict(publication_payload)
            publication_payload.update(
                {
                    "encoding_replay_artifact": listing_output_path.name,
                    "encoding_replay_artifact_bytes": listing_output_path.stat().st_size,
                    "encoding_replay_artifact_sha256": _file_sha256_reference(listing_output_path),
                    "saved_dom_artifact": copied_browser_artifacts["publication"],
                }
            )
            browser_evidence_payload["publication_listing_response"] = publication_payload
            selector_payload = browser_evidence_payload.get("selector_response")
            if isinstance(selector_payload, dict):
                selector_payload = dict(selector_payload)
                selector_payload["saved_dom_artifact"] = copied_browser_artifacts["selector"]
                browser_evidence_payload["selector_response"] = selector_payload
            _write_json(listing_copy_path, browser_evidence_payload)
            listing_evidence["copied_raw_sha256"] = _file_sha256_reference(
                listing_copy_path
            )
            listing_evidence["copied_browser_dom_artifacts"] = copied_browser_artifacts
            listing_evidence_status = "browser_observed_response"
            listing_capture_mode = "browser_rendered_dom_observation"
        elif listing_evidence_path is None:
            # 沒有可核對的 HTTP evidence 時只保留 research 狀態，不得當成正式來源接受。
            listing_evidence_status = "unverified_saved_response"
        else:
            evidence_input = _resolved_regular_input(
                listing_evidence_path,
                description="saved listing evidence",
            )
            if evidence_input == listing_input:
                raise ValueError("saved listing evidence must be separate from the raw response")
            listing_evidence = _validate_saved_listing_evidence(
                evidence_input,
                listing_path=listing_input,
                listing_hash=str(listing_input_sha256),
                stock_code=stock_code,
                roc_year=roc_year,
                season=season,
                listing_event=listing_event,
            )
            listing_evidence_copy_path = raw_dir / (
                f"mops_t57sb01_{stock_code}_{roc_year}.evidence.json"
            )
            listing_evidence_copy_path.write_bytes(evidence_input.read_bytes())
            listing_evidence["copied_raw_sha256"] = _file_sha256_reference(
                listing_evidence_copy_path
            )
            listing_evidence_status = "verified_saved_response"
        captured_publication = listing_event["publication_timestamp"]
        capture_completed_at = datetime.now(timezone.utc).isoformat()
        numeric_available_date = (
            max(
                date.fromisoformat(captured_publication[:10]) + timedelta(days=1),
                _capture_session_available_date(capture_completed_at),
            )
        )
        for parsed in parsed_tables:
            if parsed.period_end.isoformat() != listing_event["period_end"]:
                raise ValueError(
                    "MOPS statement period end does not match the official listing; "
                    f"statement_type={parsed.statement_type}; "
                    f"statement={parsed.period_end.isoformat()}; "
                    f"listing={listing_event['period_end']}"
                )

        statement_sources: list[dict[str, Any]] = []
        for parsed in parsed_tables:
            statement_type = parsed.statement_type
            raw_path = raw_dir / f"{parsed.endpoint}_{stock_code}_{roc_year}Q{season}.html"
            coded_rows: list[dict[str, Any]] = []
            item_occurrences: dict[str, int] = {}
            for item in parsed.rows:
                item_name = str(item["item_name"])
                normalized_item_name = _normalize_item_name(item_name)
                candidate_occurrence = item_occurrences.get(normalized_item_name, 0)
                item_occurrences[normalized_item_name] = candidate_occurrence + 1
                official_code = resolve_official_item_code(
                    item_name,
                    xbrl_codes,
                    statement_type=statement_type,
                    candidate_value=int(item["value"]),
                    candidate_scale=int(item["value_scale"]),
                    candidate_indent_depth=int(item["item_indent"]),
                    candidate_occurrence=candidate_occurrence,
                )
                if official_code is None:
                    raise ValueError(
                        "MOPS XBRL response has no unique official row code for numeric item; "
                        f"statement_type={statement_type}; item_name={item_name}"
                    )
                coded_rows.append(
                    {
                        **item,
                        "item_code": official_code.item_code,
                        "item_code_source": "mops.t164sb01.xbrl.row_code",
                        "official_item_name": official_code.official_item_name,
                        "xbrl_concept": official_code.xbrl_concept,
                        "xbrl_reported_value": official_code.reported_value,
                        "official_indent_depth": official_code.indent_depth,
                        "item_code_lineage_sha256": xbrl_hash,
                    }
                )
            statement_sources.append(
                {
                    "schema_version": "mops-t164-statement-source.v1",
                    "source_id": _statement_source_id(
                        statement_type=statement_type,
                        report_basis=report_basis,
                    ),
                    "source_version": f"{parsed.endpoint}.{report_basis}.v1",
                    "statement_type": statement_type,
                    "source_url": f"{MOPS_STATEMENT_BASE_URL}/{parsed.endpoint}",
                    "request": {
                        "TYPEK": market,
                        "co_id": stock_code,
                        "year": str(roc_year),
                        "season": str(season),
                    },
                    "captured_at": capture_completed_at,
                    "capture_mode": statement_capture_mode,
                    "period": expected_period,
                    "period_start": (
                        parsed.period_start.isoformat() if parsed.period_start else None
                    ),
                    "period_end": parsed.period_end.isoformat(),
                    "period_basis": parsed.period_basis,
                    "period_header": parsed.period_header,
                    "announcement_event_date": captured_publication,
                    "numeric_available_at": capture_completed_at,
                    "numeric_available_date": numeric_available_date.isoformat(),
                    "available_date": numeric_available_date.isoformat(),
                    "report_basis": report_basis,
                    "statement_scope": report_basis,
                    "response_table_row_count": parsed.table_row_count,
                    "response_named_row_count": parsed.named_row_count,
                    "accepted_numeric_row_count": len(parsed.rows),
                    "excluded_row_count": len(parsed.excluded_rows),
                    "excluded_rows": list(parsed.excluded_rows),
                    "raw_response": {
                        "basename": raw_path.name,
                        "sha256": _file_sha256_reference(raw_path),
                        "byte_count": raw_path.stat().st_size,
                        "capture_mode": statement_capture_mode,
                        "raw_custody": True,
                        "artifact_kind": "http_response_bytes",
                    },
                    "replay_http_evidence": statement_replay_evidence,
                    "official_item_code_source": {
                        "source_id": "mops.t164sb01.xbrl",
                        "source_version": f"mops-t164sb01-{report_basis}-xbrl-row-code.v1",
                        "source_url": MOPS_XBRL_URL,
                        "capture_mode": xbrl_capture_mode,
                        "raw_custody": xbrl_raw_custody,
                        "artifact_kind": xbrl_artifact_kind,
                        "raw_response": {
                            "basename": xbrl_path.name,
                            "sha256": xbrl_hash,
                            "byte_count": xbrl_path.stat().st_size,
                        },
                        "unique_code_count": len(xbrl_codes),
                        "encoding": xbrl_encoding,
                        "market_identity_conflict": xbrl_identity_conflict,
                        "browser_evidence": xbrl_browser_evidence,
                    },
                    "rows": coded_rows,
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                }
            )

        if ezsearch_availability_evidence_path is not None:
            availability_raw_response: dict[str, Any] = {
                "artifacts": availability_raw_files,
                "evidence_basename": "mops-ezsearch-availability-evidence.json",
                "evidence_sha256": _file_sha256_reference(availability_evidence_copy_path),
                "raw_custody": True,
                "artifact_kind": "http_response_bytes",
            }
        else:
            if listing_path is None:
                raise ValueError("t57 listing path is missing")
            availability_raw_response = {
                "basename": listing_path.name,
                "sha256": _file_sha256_reference(listing_path),
                "byte_count": listing_path.stat().st_size,
                "raw_custody": listing_capture_mode != "browser_rendered_dom_observation",
                "artifact_kind": (
                    "browser_dom_encoding_replay"
                    if listing_capture_mode == "browser_rendered_dom_observation"
                    else "http_response_bytes"
                ),
            }
        listing_source = {
            "schema_version": (
                "mops-ezsearch-statement-availability.v1"
                if ezsearch_availability_evidence_path is not None
                else "mops-document-listing-availability.v1"
            ),
            "source_id": availability_source_id,
            "source_version": availability_source_version,
            "source_url": availability_source_url,
            "captured_at": capture_completed_at,
            "capture_started_at": capture_started_at,
            "capture_completed_at": capture_completed_at,
            "capture_mode": listing_capture_mode,
            "input_raw_sha256": listing_input_sha256,
            "evidence_status": listing_evidence_status,
            "evidence": listing_evidence,
            "raw_response": availability_raw_response,
            "rows": [listing_event],
            "research_only": True,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
        }
        listing_source_path = staging / "availability-source.json"
        _write_json(listing_source_path, listing_source)
        statement_sources_path = staging / "statement-sources.json"
        _write_json(statement_sources_path, {"sources": statement_sources})

        availability_event_sha256 = listing_event.get("listing_row_sha256")
        if availability_event_sha256 is None:
            availability_event_sha256 = listing_event.get("availability_event_sha256")
        if not isinstance(availability_event_sha256, str) or not availability_event_sha256:
            raise ValueError("availability event hash is missing")
        if not availability_event_sha256.startswith("sha256:"):
            availability_event_sha256 = f"sha256:{availability_event_sha256}"
        correction_status = str(listing_event.get("correction_status", "unknown"))
        correction_evidence = str(
            listing_event.get(
                "correction_evidence",
                "MOPS t57sb01 listing correction column is 無",
            )
        )
        candidate_source_version = (
            f"mops-t164-{report_basis}-statements-with-"
            f"{'mops-ezsearch-publication' if ezsearch_availability_evidence_path is not None else 't57sb01'}-"
            "xbrl-row-codes.v3"
        )
        candidate_rows: list[dict[str, Any]] = []
        for source in statement_sources:
            parsed_type = str(source["statement_type"])
            for item in source["rows"]:
                assert isinstance(item, Mapping)
                item_name = str(item["item_name"])
                value = int(item["value"])
                value_unit = str(item["value_unit"])
                value_scale = int(item["value_scale"])
                content = {
                    "stock_code": stock_code,
                    "market": market,
                    "statement_type": parsed_type,
                    "report_basis": report_basis,
                    "statement_scope": report_basis,
                    "period": expected_period,
                    "period_start": source["period_start"],
                    "period_end": source["period_end"],
                    "period_basis": source["period_basis"],
                    "item_name": item_name,
                    "value": value,
                    "value_unit": value_unit,
                    "value_scale": value_scale,
                    "item_code": str(item["item_code"]),
                    "item_code_source": str(item["item_code_source"]),
                    "official_item_name": str(item["official_item_name"]),
                    "xbrl_concept": item.get("xbrl_concept"),
                    "xbrl_reported_value": item.get("xbrl_reported_value"),
                    "item_code_lineage_sha256": str(item["item_code_lineage_sha256"]),
                    "item_indent": int(item["item_indent"]),
                    "official_indent_depth": item.get("official_indent_depth"),
                }
                content_hash = _canonical_sha256(content)
                candidate_rows.append(
                    {
                        **content,
                        "symbol": stock_code,
                        "period_header": source["period_header"],
                        "announcement_date": captured_publication,
                        "publication_timestamp": captured_publication,
                        "announcement_event_date": captured_publication,
                        "announcement_event_timestamp": captured_publication,
                        "numeric_available_at": capture_completed_at,
                        "numeric_available_date": numeric_available_date.isoformat(),
                        "available_date": numeric_available_date.isoformat(),
                        "revision": 1,
                        "parent_revision": None,
                        "revision_basis": (
                            "current MOPS availability capture; publication timestamp is the "
                            "observed official event time, not a first-publication claim"
                        ),
                        "correction_status": correction_status,
                        "correction_evidence": correction_evidence,
                        "content_hash": content_hash,
                        "numeric_source_row_sha256": f"sha256:{item['source_row_sha256']}",
                        "availability_event_sha256": availability_event_sha256,
                        "statement_items": {item_name: value},
                        "raw_value": item["raw_value"],
                    }
                )

        candidate = {
            "schema_version": "mops-statement-pit-candidate.v1",
            "source_id": "mops.statement.publication",
            "source_version": candidate_source_version,
            "report_basis": report_basis,
            "statement_scope": report_basis,
            "captured_at": capture_completed_at,
            "capture_started_at": capture_started_at,
            "capture_completed_at": capture_completed_at,
            "research_only": True,
            "read_only_source": True,
            "formal_oos_allowed": False,
            "formal_credit_authorized": False,
            "production_scheduler_allowed": False,
            "production_blend_alpha_bp": 0,
            "downstream_eligibility": "none",
            "rows": candidate_rows,
            "pit_coverage_summary": {
                "statement_numeric_rows_supplied": True,
                "stock_code": stock_code,
                "market_request": market,
                "period": expected_period,
                "period_end": listing_event["period_end"],
                "announcement_event_timestamp": captured_publication,
                "numeric_available_at": capture_completed_at,
                "numeric_available_date": numeric_available_date.isoformat(),
                "statement_counts": {
                    parsed.statement_type: {
                        "response_table_row_count": parsed.table_row_count,
                        "response_named_row_count": parsed.named_row_count,
                        "accepted_numeric_row_count": len(parsed.rows),
                        "excluded_row_count": len(parsed.excluded_rows),
                        "excluded_rows": list(parsed.excluded_rows),
                    }
                    for parsed in parsed_tables
                },
                "coverage_interpretation": (
                    f"bounded single-stock {report_basis} statement candidate; not a full-universe "
                    "fundamental_statement_items materialization"
                ),
            },
            "lineage": {
                "numeric_statement_source": {
                    "source_id": "mops.financial_statement.raw",
                    "source_version": (
                        f"mops-t164sb03-04-05-{report_basis}-with-"
                        "t164sb01-xbrl-row-codes.v3"
                    ),
                    "capture_mode": statement_capture_mode,
                    "artifact_sha256": _file_sha256_reference(statement_sources_path),
                    "replay_http_evidence": statement_replay_evidence,
                },
                "official_item_code_source": {
                    "source_id": "mops.t164sb01.xbrl",
                    "source_version": f"mops-t164sb01-{report_basis}-xbrl-row-code.v1",
                    "source_url": MOPS_XBRL_URL,
                    "capture_mode": xbrl_capture_mode,
                    "raw_custody": xbrl_raw_custody,
                    "artifact_kind": xbrl_artifact_kind,
                    "raw_response": {
                        "basename": xbrl_path.name,
                        "sha256": xbrl_hash,
                        "byte_count": xbrl_path.stat().st_size,
                    },
                    "unique_code_count": len(xbrl_codes),
                    "encoding": xbrl_encoding,
                    "market_identity_conflict": xbrl_identity_conflict,
                    "browser_evidence": xbrl_browser_evidence,
                },
                "availability_source": {
                    "source_id": availability_source_id,
                    "source_version": availability_source_version,
                    "capture_mode": listing_capture_mode,
                    "evidence_status": listing_evidence_status,
                    "raw_response": availability_raw_response,
                    "evidence": listing_evidence,
                },
                "availability_artifact_sha256": _file_sha256_reference(listing_source_path),
                "canonical_dataset_lineage": {
                    "manifest_sha256": _file_sha256_reference(canonical_manifest),
                    "dataset_sha256": _file_sha256_reference(canonical_dataset),
                },
                "revision_correction_policy": (
                    "listing correction status is preserved; a later capture must compare "
                    "immutable statement-source and item hashes before any revision decision"
                ),
            },
        }
        current_phase = "candidate_validation"
        validate_artifact(candidate)
        candidate_path = staging / "statement-pit-candidate.json"
        _write_json(candidate_path, candidate)
        manifest = {
            "schema_version": "mops-statement-pit-run-manifest.v1",
            "run_id": run_id,
            "captured_at": capture_completed_at,
            "capture_started_at": capture_started_at,
            "capture_completed_at": capture_completed_at,
            "files": {
                "statement_sources": _file_sha256_reference(statement_sources_path),
                "availability_source": _file_sha256_reference(listing_source_path),
                "candidate": _file_sha256_reference(candidate_path),
                **{
                    f"raw_{path.name}": _file_sha256_reference(path)
                    for path in sorted(raw_dir.iterdir())
                },
            },
            "research_only": True,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
        }
        manifest_path = staging / "run-manifest.json"
        _write_json(manifest_path, manifest)
        _publish_staging_directory(staging, target)
    except Exception as error:
        if partial_target is None or partial_target.exists():
            # 同一 run_id 的 partial 目錄也是 immutable；既有 partial 留作下一次
            # resume 的原始輸入，不因新的失敗嘗試覆寫。
            shutil.rmtree(staging, ignore_errors=True)
        else:
            raw_files: list[dict[str, Any]] = []
            if raw_dir.is_dir():
                for path in sorted(raw_dir.iterdir()):
                    if path.is_file():
                        raw_files.append(
                            {
                                "basename": path.name,
                                "sha256": _file_sha256_reference(path),
                                "byte_count": path.stat().st_size,
                            }
                        )
            expected_raw_names = {
                f"{MOPS_STATEMENT_ENDPOINTS[statement_type][0]}_{stock_code}_{roc_year}Q{season}.html"
                for statement_type in MOPS_STATEMENT_ENDPOINTS
            }
            replay_ready = bool(
                expected_raw_names.issubset({str(item["basename"]) for item in raw_files})
                and any(str(item["basename"]) == xbrl_name for item in raw_files)
                and (raw_dir / "evidence.json").is_file()
            )
            partial_payload = {
                "schema_version": "mops-statement-pit-partial.v1",
                "run_id": run_id,
                "stock_code": stock_code,
                "market": market,
                "period": f"{roc_year + 1911:04d}-Q{season}",
                "report_basis": report_basis,
                "research_only": True,
                "formal_oos_allowed": False,
                "phase": current_phase,
                "capture_started_at": capture_started_at,
                "failure_observed_at": datetime.now(timezone.utc).isoformat(),
                "failure_type": type(error).__name__,
                "failure": str(error),
                "replay_ready": replay_ready,
                "raw_directory": "raw",
                "raw_files": raw_files,
            }
            try:
                _write_json(staging / "partial-failure.json", partial_payload)
                # partial 根目錄可能是本次執行第一次使用；先建立其父目錄，
                # 再以 rename 發布 immutable staging，避免 FileNotFoundError
                # 讓已取得的 raw 被清掉而沒有留下可重播 receipt。
                partial_target.parent.mkdir(parents=True, exist_ok=True)
                _publish_staging_directory(staging, partial_target)
            except Exception:
                # 保留原始取數例外；partial publish 失敗不能遮蔽真正的來源／解析原因。
                shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "output_directory": target,
        "candidate": target / "statement-pit-candidate.json",
        "manifest": target / "run-manifest.json",
    }


def _fetch_statement_response(
    *,
    stock_code: str,
    market: str,
    roc_year: int,
    season: int,
    statement_type: str,
    timeout_seconds: int,
    report_basis: str = "consolidated",
) -> bytes:
    endpoint, _, _ = MOPS_STATEMENT_ENDPOINTS[statement_type]
    expected_title = _statement_title(
        statement_type=statement_type,
        report_basis=report_basis,
    )
    request_url = f"{MOPS_STATEMENT_BASE_URL}/{endpoint}"
    headers = {
        "Referer": f"{MOPS_STATEMENT_BASE_URL}/{endpoint.removeprefix('ajax_')}",
        "User-Agent": "technical-analysis-research-readonly/1.0",
    }
    request_data = {
        "encodeURIComponent": "1",
        "step": "1",
        "firstin": "1",
        "off": "1",
        "co_id": stock_code,
        "TYPEK": market,
        "year": str(roc_year),
        "season": str(season),
    }

    def _post(data: Mapping[str, str]) -> tuple[bytes, str]:
        response = requests.post(
            request_url,
            data=data,
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.content
        return body, body.decode(response.encoding or "utf-8", errors="strict")

    body, text = _post(request_data)
    if expected_title not in text:
        # 金控公司可能先回傳母子公司選擇表；只有官方表格第一欄精確等於
        # 請求代碼且 onclick 唯一時，才依現有 MOPS 表單進行 step=2 follow-up。
        detail_code = _selector_detail_code(text, stock_code)
        if detail_code is not None:
            detail_data = dict(request_data)
            detail_data.update({"step": "2", "co_id": detail_code})
            body, text = _post(detail_data)
    if expected_title not in text:
        raise ValueError(
            "MOPS statement response does not contain the expected official title; "
            f"statement_type={statement_type}"
        )
    return body


def _target_header(*, roc_year: int, season: int, statement_type: str) -> tuple[str, ...]:
    month = season * 3
    day = (31, 30, 30, 31)[season - 1]
    quarter_name = _QUARTER_NAME[season - 1]
    if statement_type == "balance_sheet":
        return (f"{roc_year}年{month:02d}月{day:02d}日", f"{roc_year}年{month}月{day}日")
    if statement_type == "income_statement":
        return (f"{roc_year}年第{season}季", f"{roc_year}年第{quarter_name}季")
    return (
        f"{roc_year}年01月01日至{roc_year}年{month:02d}月{day:02d}日",
        f"{roc_year}年1月1日至{roc_year}年{month}月{day}日",
    )


def _find_target_table(
    tables: list[list[list[str]]],
    *,
    target_header: tuple[str, ...],
) -> tuple[list[list[str]], int, int]:
    for table in tables:
        for row_index, cells in enumerate(table):
            for header in target_header:
                if header in cells:
                    return table, row_index, cells.index(header)
    raise ValueError(
        "MOPS statement response does not contain the requested period value header; "
        f"expected_one_of={target_header}"
    )


def _period_window(
    *,
    statement_type: str,
    roc_year: int,
    season: int,
) -> tuple[date | None, date, str]:
    year = roc_year + 1911
    month = season * 3
    day = (31, 30, 30, 31)[season - 1]
    period_end = date(year, month, day)
    if statement_type == "balance_sheet":
        return None, period_end, "period_end_snapshot"
    if statement_type == "income_statement":
        return date(year, (season - 1) * 3 + 1, 1), period_end, "quarter_single"
    return date(year, 1, 1), period_end, "year_to_date"


def _parse_item_value(
    value: str,
    *,
    statement_type: str,
    item_name: str,
) -> tuple[int, str, int]:
    if statement_type == "income_statement" and item_name in _PER_SHARE_ITEM_NAMES:
        return _parse_scaled_integer(value, scale=100, unit="TWD_per_share", field="EPS")
    return _parse_scaled_integer(value, scale=1000, unit="TWD", field="statement_amount")


def _parse_scaled_integer(
    value: str,
    *,
    scale: int,
    unit: str,
    field: str,
) -> tuple[int, str, int]:
    normalized = unescape(value).replace(",", "").strip()
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = f"-{normalized[1:-1]}"
    try:
        scaled = Decimal(normalized) * Decimal(scale)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} is not decimal") from exc
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{field} is not representable at scale {scale}")
    return int(scaled), unit, scale


def _capture_session_available_date(captured_at: str) -> date:
    """將捕捉時間轉成 date-only 的保守可用日。

    date-only consumer 不能在捕捉當日早盤使用盤後資料，因此固定採下一個
    台北曆日；需要同日精確判斷時，應使用 ``numeric_available_at`` timestamp。
    這裡不把下一個曆日宣稱為交易所實際 next session。
    """
    try:
        parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    local = parsed.astimezone(_TAIPEI_TIMEZONE)
    return local.date() + timedelta(days=1)


def _validate_inputs(
    *,
    stock_code: str,
    roc_year: int,
    season: int,
    market: str,
    run_id: str,
    timeout_seconds: int,
    report_basis: str = "consolidated",
) -> None:
    if not _STOCK_CODE_RE.fullmatch(stock_code):
        raise ValueError("stock_code must be a 4-to-6 digit security identifier")
    if roc_year < 1:
        raise ValueError("roc_year must be positive")
    if not 1 <= season <= 4:
        raise ValueError("season must be between 1 and 4")
    if market not in {"sii", "otc", "rotc", "pub"}:
        raise ValueError("market must be one of sii, otc, rotc, pub")
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,80}", run_id) is None:
        raise ValueError("run_id must be 3-81 lowercase letters, digits, hyphens, or underscores")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if report_basis not in _REPORT_BASES:
        raise ValueError("report_basis must be consolidated or individual")


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _publish_staging_directory(staging: Path, target: Path) -> None:
    """在 Windows 短暫檔案掃描鎖定時有限次重試 immutable publish。"""
    for attempt in range(3):
        try:
            os.replace(staging, target)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.2 * (attempt + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-code", required=True)
    parser.add_argument("--roc-year", type=int, required=True)
    parser.add_argument("--season", type=int, required=True, choices=(1, 2, 3, 4))
    parser.add_argument("--market", required=True, choices=("sii", "otc", "rotc", "pub"))
    parser.add_argument(
        "--report-basis",
        choices=("consolidated", "individual"),
        default="consolidated",
        help="報表範圍；individual 僅接受官方個別報表與 Individual report XBRL metadata",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument(
        "--listing-raw",
        type=Path,
        help="使用已保存的官方 t57 raw；需另以 --listing-evidence 綁定 HTTP evidence",
    )
    parser.add_argument(
        "--listing-evidence",
        type=Path,
        help="驗證 --listing-raw 的官方 HTTP evidence JSON",
    )
    parser.add_argument(
        "--listing-browser-evidence",
        type=Path,
        help="驗證 --listing-raw 的瀏覽器 DOM observation evidence JSON；不提供 HTTP raw custody",
    )
    parser.add_argument(
        "--ezsearch-availability-evidence",
        type=Path,
        help="使用已保存的官方 EZSearch 公告事件 evidence；不偽裝成 t57 listing",
    )
    parser.add_argument(
        "--statement-raw-dir",
        type=Path,
        help="重用已保存的三張 t164 與 XBRL raw；不重新發送 numeric request",
    )
    parser.add_argument(
        "--xbrl-browser-dom",
        type=Path,
        help="使用已保存的官方 t164 XBRL 瀏覽器 DOM；不冒充 HTTP raw",
    )
    parser.add_argument(
        "--xbrl-browser-evidence",
        type=Path,
        help="驗證 --xbrl-browser-dom 的官方公司／期別／row-code DOM evidence",
    )
    parser.add_argument(
        "--xbrl-encoding-repair",
        choices=(_XBRL_ENCODING_REPAIR_C1,),
        help="只對已核對官方 charset=big5 且含孤立 0x84 的 response 明示套用修復",
    )
    parser.add_argument(
        "--partial-output-root",
        type=Path,
        help="來源／解析失敗時保存可重用 raw 的隔離 partial 根目錄",
    )
    args = parser.parse_args(argv)
    paths = build_candidate(
        stock_code=args.stock_code,
        roc_year=args.roc_year,
        season=args.season,
        market=args.market,
        output_root=args.output_root,
        run_id=args.run_id,
        canonical_manifest=args.canonical_manifest,
        canonical_dataset=args.canonical_dataset,
        timeout_seconds=args.timeout_seconds,
        report_basis=args.report_basis,
        listing_response_path=args.listing_raw,
        listing_evidence_path=args.listing_evidence,
        listing_browser_evidence_path=args.listing_browser_evidence,
        ezsearch_availability_evidence_path=args.ezsearch_availability_evidence,
        statement_raw_dir=args.statement_raw_dir,
        xbrl_browser_dom_path=args.xbrl_browser_dom,
        xbrl_browser_evidence_path=args.xbrl_browser_evidence,
        xbrl_encoding_repair=args.xbrl_encoding_repair,
        partial_output_root=args.partial_output_root,
    )
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
