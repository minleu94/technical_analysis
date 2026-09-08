"""驗證 MOPS 財報更正頁並建立 immutable replacement child。

此工具只讀取已保存的官方更正頁、候選與既有 child manifest。它以明確的
XBRL item code、報表類別與期間逐項核對更正頁的更正後金額，並把更正
證據另存為新的 research-only child；舊候選與舊 raw 永不覆寫。更正公告
的觀察時間不會改寫 numeric candidate 的可用時間。
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_COMPARISON_SCHEMA = "v4-mops-statement-correction-comparison.v1"
_SUPERSESSION_SCHEMA = "mops-statement-artifact-correction.v1"
_OFFICIAL_HOST = "https://mopsov.twse.com.tw/"
_EXPECTED_ROC_YEAR_SEASON = "11502"
_EXPECTED_PERIOD = "2026-Q2"
_CORRECTION_RAW_NAME = "correction_t56sb31_q1_2230_202602_r2.html"
_CORRECTION_EVIDENCE_NAME = "correction-evidence-r2.json"
_COMPARISON_NAME = "correction-comparison-r1.json"


class _PreCollector(HTMLParser):
    """保留官方頁面中的 pre 文字，讓頁面區塊可被機器重播。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._active: list[str] | None = None
        self.all_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "pre":
            self._active = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "pre" and self._active is not None:
            self.blocks.append("".join(self._active))
            self._active = None

    def handle_data(self, data: str) -> None:
        self.all_text.append(data)
        if self._active is not None:
            self._active.append(data)


def _sha256_reference(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _regular_file(path: Path, *, description: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if path.expanduser().is_symlink() or not resolved.is_file():
        raise ValueError(f"{description} must be a regular file")
    return resolved


def _load_json(path: Path, *, description: str) -> dict[str, Any]:
    resolved = _regular_file(path, description=description)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is not valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must be a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _parse_amount(value: str) -> int:
    compact = value.replace("$", "").replace(",", "")
    compact = re.sub(r"\s+", "", compact)
    if compact.startswith("(") and compact.endswith(")"):
        return -int(compact[1:-1])
    if not re.fullmatch(r"-?\d+", compact):
        raise ValueError(f"unsupported correction amount: {value!r}")
    return int(compact)


_CURRENCY_RE = re.compile(
    r"\$\s*(?:\(\s*)?\d[\d,]*(?:\s*\))?",
)


# 每一個別名都是已從 2230 t164 row code 與更正頁逐字核對的契約；
# 不以模糊名稱或相鄰列猜測科目。
_PAGE7_SPECS: tuple[dict[str, Any], ...] = (
    {
        "item_code": "A21200",
        "correction_label": "利息收入",
        "candidate_labels": ("利息收入",),
    },
    {
        "item_code": "A22500",
        "correction_label": "處分及報廢不動產、廠房及設備利益",
        "candidate_labels": ("處分及報廢不動產、廠房及設備損失（利益）",),
    },
    {
        "item_code": "A20010",
        "correction_label": "不影響現金流量之收益費損項目合計",
        "candidate_labels": ("收益費損項目合計",),
    },
    {
        "item_code": "A20000",
        "correction_label": "調整項目合計",
        "candidate_labels": ("調整項目合計",),
    },
    {
        "item_code": "A33100",
        "correction_label": "收取之利息",
        "candidate_labels": ("收取之利息",),
    },
    {
        "item_code": "AAAA",
        "correction_label": "營業活動之淨現金流入(出)",
        "candidate_labels": ("營業活動之淨現金流入（流出）",),
    },
    {
        "item_code": "DDDD",
        "correction_label": "匯率變動對現金及約當現金之影響數",
        "candidate_labels": ("匯率變動對現金及約當現金之影響",),
    },
)


def _read_correction_inputs(
    html_path: Path,
    evidence_path: Path,
) -> tuple[bytes, dict[str, Any], _PreCollector]:
    html_file = _regular_file(html_path, description="correction HTML")
    evidence = _load_json(evidence_path, description="correction evidence")
    try:
        raw = html_file.read_bytes()
    except OSError as error:
        raise ValueError("correction HTML cannot be read") from error
    raw_hash = _sha256_reference(html_file)
    raw_response = evidence.get("raw_response")
    http = evidence.get("http")
    if not isinstance(raw_response, Mapping) or not isinstance(http, Mapping):
        raise ValueError("correction evidence lacks raw_response/http metadata")
    for field in ("sha256", "byte_count"):
        if raw_response.get(field) != (raw_hash if field == "sha256" else len(raw)):
            raise ValueError(f"correction evidence {field} does not match saved HTML")
        if http.get(field) != (raw_hash if field == "sha256" else len(raw)):
            raise ValueError(f"correction HTTP {field} does not match saved HTML")
    if http.get("status") != 200 or evidence.get("research_only") is not True:
        raise ValueError("correction evidence is not a research-only HTTP 200 response")
    request = evidence.get("request")
    if not isinstance(request, Mapping):
        raise ValueError("correction evidence request metadata is missing")
    url = request.get("url")
    if (
        not isinstance(url, str)
        or not url.startswith(_OFFICIAL_HOST + "mops/web/t56sb31_q1?")
        or "CID=2230" not in url
        or "YEAR_SEASON=202602" not in url
    ):
        raise ValueError("correction URL is outside the observed official t56 path")
    correction = evidence.get("correction")
    if not isinstance(correction, Mapping) or correction.get("status") != "reported":
        raise ValueError("official correction status is not reported")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("correction HTML must be strict UTF-8") from error
    collector = _PreCollector()
    try:
        collector.feed(text)
        collector.close()
    except Exception as error:
        raise ValueError("correction HTML cannot be parsed") from error
    if not collector.blocks:
        raise ValueError("correction page contains no pre blocks")
    return raw, evidence, collector


def _parse_identity(
    collector: _PreCollector,
    *,
    expected_stock_code: str,
    expected_roc_year_season: str = _EXPECTED_ROC_YEAR_SEASON,
) -> dict[str, str]:
    normalized = re.sub(r"\s+", " ", " ".join(collector.all_text))
    stock_match = re.search(r"公司代號\s*[：:]\s*(\d{4})", normalized)
    name_match = re.search(r"公司名稱\s*[：:]\s*([^\s<]+)", normalized)
    period_match = re.search(r"年度季別\s+(\d{5,6})", normalized)
    basis_match = re.search(r"財報類別\s+([^\s]+)", normalized)
    description_match = re.search(r"資料說明\s+([^\s]+)", normalized)
    if not stock_match or not name_match or not period_match or not basis_match:
        raise ValueError("correction page identity metadata is incomplete")
    stock_code = stock_match.group(1)
    roc_year_season = period_match.group(1)
    report_basis_text = basis_match.group(1)
    if stock_code != expected_stock_code:
        raise ValueError(
            f"correction page company mismatch: expected {expected_stock_code}, got {stock_code}"
        )
    if roc_year_season != expected_roc_year_season:
        raise ValueError(
            "correction page period mismatch: "
            f"expected {expected_roc_year_season}, got {roc_year_season}"
        )
    if report_basis_text != "合併":
        raise ValueError("correction page is not a consolidated report")
    return {
        "stock_code": stock_code,
        "company_name": name_match.group(1),
        "roc_year_season": roc_year_season,
        "report_basis": "consolidated",
        "report_basis_text": report_basis_text,
        "report_description": (
            description_match.group(1) if description_match else "unavailable"
        ),
    }


def _parse_page7_block(collector: _PreCollector) -> tuple[str, list[dict[str, Any]]]:
    page7_blocks = [
        block
        for block in collector.blocks
        if "更正前" in block and "更正後" in block and "利息收入" in block
    ]
    if len(page7_blocks) != 1:
        raise ValueError("correction page 7 block is missing or ambiguous")
    page7 = page7_blocks[0]
    parsed: dict[str, dict[str, Any]] = {}
    for line in page7.splitlines():
        amounts = _CURRENCY_RE.findall(line)
        if len(amounts) != 2:
            continue
        label = _compact(line[: line.find(amounts[0])])
        for spec in _PAGE7_SPECS:
            if _compact(str(spec["correction_label"])) != label:
                continue
            code = str(spec["item_code"])
            if code in parsed:
                raise ValueError(f"correction page 7 repeats item code {code}")
            before_thousands = _parse_amount(amounts[0])
            after_thousands = _parse_amount(amounts[1])
            parsed[code] = {
                "item_code": code,
                "correction_label": spec["correction_label"],
                "before_thousands": before_thousands,
                "after_thousands": after_thousands,
                "before_twd": before_thousands * 1000,
                "after_twd": after_thousands * 1000,
                "unit": "TWD_thousands",
                "period_start": "2026-01-01",
                "period_end": "2026-06-30",
                "period_basis": "year_to_date",
            }
            break
    expected_codes = {str(spec["item_code"]) for spec in _PAGE7_SPECS}
    if set(parsed) != expected_codes:
        missing = sorted(expected_codes - set(parsed))
        extra = sorted(set(parsed) - expected_codes)
        raise ValueError(
            f"correction page 7 item coverage mismatch; missing={missing}, extra={extra}"
        )
    return page7, [parsed[code] for code in (str(spec["item_code"]) for spec in _PAGE7_SPECS)]


def _parse_note_scope(collector: _PreCollector) -> list[dict[str, Any]]:
    pages = (16, 19, 21, 30, 33, 34, 37)
    full_text = "\n".join(collector.blocks)
    result: list[dict[str, Any]] = []
    for page in pages:
        marker = f"第{page}頁"
        if marker not in full_text:
            raise ValueError(f"correction disclosure page marker is missing: {marker}")
        result.append(
            {
                "page": page,
                "marker": marker,
                "numeric_t164_mapping": "not_attempted",
                "disclosure_only": True,
                "reason": "official correction scope names a note page; no statement row was silently inferred",
            }
        )
    return result


def _candidate_identity(candidate: Mapping[str, Any]) -> dict[str, str]:
    summary = candidate.get("pit_coverage_summary")
    if not isinstance(summary, Mapping):
        raise ValueError("candidate coverage summary is missing")
    stock_code = summary.get("stock_code")
    market = summary.get("market_request")
    period = summary.get("period")
    if (
        not isinstance(stock_code, str)
        or not isinstance(market, str)
        or not isinstance(period, str)
    ):
        raise ValueError("candidate identity is incomplete")
    if period != _EXPECTED_PERIOD:
        raise ValueError("candidate period is not 2026-Q2")
    if candidate.get("report_basis") != "consolidated":
        raise ValueError("candidate report basis is not consolidated")
    return {
        "stock_code": stock_code,
        "market_request": market,
        "period": period,
        "report_basis": "consolidated",
    }


def _compare_page7_to_candidate(
    candidate: Mapping[str, Any],
    page7: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = candidate.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("candidate contains no rows")
    identity = _candidate_identity(candidate)
    comparisons: list[dict[str, Any]] = []
    for correction in page7:
        code = str(correction["item_code"])
        spec = next(spec for spec in _PAGE7_SPECS if spec["item_code"] == code)
        matches = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and row.get("item_code") == code
            and row.get("stock_code") == identity["stock_code"]
            and row.get("market") == identity["market_request"]
            and row.get("period") == identity["period"]
            and row.get("statement_type") == "cash_flows_statement"
            and row.get("period_start") == correction["period_start"]
            and row.get("period_end") == correction["period_end"]
            and row.get("period_basis") == correction["period_basis"]
            and row.get("report_basis") == "consolidated"
            and _compact(str(row.get("item_name", "")))
            in {_compact(str(label)) for label in spec["candidate_labels"]}
        ]
        if len(matches) != 1:
            raise ValueError(
                f"candidate item code {code} has {len(matches)} matching rows; "
                "explicit code/period/basis mapping is required"
            )
        row = matches[0]
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"candidate item code {code} has a non-integer value")
        if int(value) != int(correction["after_twd"]):
            raise ValueError(
                f"candidate value mismatch for {code}: "
                f"expected after={correction['after_twd']}, got {value}"
            )
        comparisons.append(
            {
                **correction,
                "candidate_item_name": str(row["item_name"]),
                "candidate_value_twd": int(value),
                "candidate_value_matches_after": True,
                "candidate_source_version": str(candidate.get("source_version", "")),
                "candidate_revision": row.get("revision"),
            }
        )
    return comparisons


def compare_correction_to_candidate(
    candidate_path: Path,
    html_path: Path,
    evidence_path: Path,
) -> dict[str, Any]:
    """以官方 identity、頁 7 七筆 code 與 candidate 逐項比對更正後數值。"""

    candidate_file = _regular_file(candidate_path, description="candidate")
    candidate = _load_json(candidate_file, description="candidate")
    raw, evidence, collector = _read_correction_inputs(html_path, evidence_path)
    candidate_identity = _candidate_identity(candidate)
    identity = _parse_identity(
        collector,
        expected_stock_code=candidate_identity["stock_code"],
    )
    correction = evidence.get("correction")
    assert isinstance(correction, Mapping)
    page7_text, page7 = _parse_page7_block(collector)
    matched = _compare_page7_to_candidate(candidate, page7)
    notes = _parse_note_scope(collector)
    request = evidence["request"]
    http = evidence["http"]
    raw_hash = _sha256_reference(Path(html_path).resolve())
    evidence_hash = _sha256_reference(Path(evidence_path).resolve())
    return {
        "schema_version": _COMPARISON_SCHEMA,
        "research_only": True,
        "formal_oos_allowed": False,
        "raw_data_modified": False,
        "source": {
            "raw_response_path": str(Path(html_path).resolve()),
            "raw_response_sha256": raw_hash,
            "raw_response_byte_count": len(raw),
            "evidence_path": str(Path(evidence_path).resolve()),
            "evidence_sha256": evidence_hash,
            "url": str(request["url"]),
            "http_status": http.get("status"),
            "request_started_at": evidence.get("request_started_at"),
            "response_received_at": evidence.get("response_received_at"),
            "capture_mode": evidence.get("capture_mode"),
        },
        "identity": {
            **identity,
            "candidate_stock_code": candidate_identity["stock_code"],
            "candidate_market_request": candidate_identity["market_request"],
            "candidate_period": candidate_identity["period"],
            "candidate_report_basis": candidate_identity["report_basis"],
            "market_alignment": (
                "correction detail was observed through the official global detail "
                "endpoint; numeric candidate market_request remains unchanged"
            ),
        },
        "correction": {
            "status": correction.get("status"),
            "summary": correction.get("summary"),
            "scope": correction.get("scope"),
            "attachment": correction.get("attachment"),
            "page7_source_text": page7_text,
            "page7_numeric_comparisons": matched,
            "note_scope": notes,
        },
        "comparison": {
            "candidate_path": str(candidate_file),
            "candidate_sha256": _sha256_reference(candidate_file),
            "matched_item_count": len(matched),
            "all_after_values_match": all(
                bool(item["candidate_value_matches_after"]) for item in matched
            ),
            "candidate_numeric_values_changed": False,
            "numeric_available_at_preserved": True,
            "historical_pit_backfill": False,
            "disclosure_note_pages_mapped_to_statement_rows": False,
        },
    }


def _manifest_file_path(root: Path, name: str) -> Path:
    if name.startswith("raw_"):
        return root / "raw" / name.removeprefix("raw_")
    legacy_names = {
        "candidate": "statement-pit-candidate.json",
        "statement_sources": "statement-sources.json",
        "availability_source": "availability-source.json",
    }
    return root / legacy_names.get(name, name)


def _copy_manifest_files(
    old_root: Path,
    new_root: Path,
    manifest: Mapping[str, Any],
) -> None:
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise ValueError("old child manifest files are missing")
    names = {str(name) for name in files if str(name) != "candidate"}
    raw_files = manifest.get("raw_files")
    if isinstance(raw_files, Mapping):
        names.update(f"raw_{name}" for name in raw_files)
    for name in sorted(names):
        source = _manifest_file_path(old_root, name)
        if not source.is_file() or source.resolve(strict=False) != source:
            raise ValueError(f"old child file is missing or aliased: {name}")
        target = _manifest_file_path(new_root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _hash_manifest_files(root: Path, names: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        path = _manifest_file_path(root, name)
        if not path.is_file() or path.resolve(strict=False) != path:
            raise ValueError(f"new child file is missing: {name}")
        result[name] = _sha256_reference(path)
    return result


def create_immutable_replacement(
    *,
    candidate_path: Path,
    manifest_path: Path,
    correction_html_path: Path,
    correction_evidence_path: Path,
    output_root: Path,
    child_name: str = "v4-quarterly-r33-2230-correction-r1-otc-2230-2026q2",
) -> dict[str, Any]:
    """建立更正後的新 child、manifest 與 supersession record。"""

    candidate_file = _regular_file(candidate_path, description="candidate")
    old_manifest_file = _regular_file(manifest_path, description="child manifest")
    old_root = old_manifest_file.parent
    old_manifest = _load_json(old_manifest_file, description="child manifest")
    comparison = compare_correction_to_candidate(
        candidate_file,
        correction_html_path,
        correction_evidence_path,
    )
    if comparison["comparison"]["all_after_values_match"] is not True:
        raise ValueError("official correction values did not all match the candidate")
    output_parent = Path(output_root).expanduser().resolve(strict=False)
    if output_parent.exists():
        raise ValueError("immutable correction output already exists")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", child_name):
        raise ValueError("child_name contains unsafe path characters")
    output_parent.mkdir(parents=True, exist_ok=False)
    new_root = output_parent / child_name
    new_root.mkdir()
    _copy_manifest_files(old_root, new_root, old_manifest)
    raw_target = new_root / "raw" / _CORRECTION_RAW_NAME
    raw_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        _regular_file(correction_html_path, description="correction HTML"),
        raw_target,
    )
    evidence_target = new_root / _CORRECTION_EVIDENCE_NAME
    shutil.copy2(
        _regular_file(correction_evidence_path, description="correction evidence"),
        evidence_target,
    )

    candidate_payload = _load_json(candidate_file, description="candidate")
    rows = candidate_payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("candidate rows are missing")
    matched_codes = {
        str(item["item_code"])
        for item in comparison["correction"]["page7_numeric_comparisons"]
    }
    correction_message = (
        "官方 t56sb31 更正頁逐項核對；更正後值與當期 t164 candidate 相符，"
        f"raw={comparison['source']['raw_response_sha256']} "
        f"evidence={comparison['source']['evidence_sha256']}"
    )
    replacement_payload = deepcopy(candidate_payload)
    for row in replacement_payload["rows"]:
        if not isinstance(row, dict):
            continue
        if str(row.get("item_code")) in matched_codes:
            row["correction_status"] = "verified_current_matches_official_correction"
            row["correction_evidence"] = correction_message
    replacement_payload["correction_status"] = (
        "verified_current_matches_official_correction"
    )
    replacement_payload["correction_evidence"] = correction_message
    replacement_payload["correction_lineage"] = {
        "schema_version": "mops-statement-correction-lineage.v1",
        "status": "official_correction_compared",
        "raw_response_sha256": comparison["source"]["raw_response_sha256"],
        "evidence_sha256": comparison["source"]["evidence_sha256"],
        "comparison_basename": _COMPARISON_NAME,
        "observed_at": comparison["source"]["response_received_at"],
        "numeric_source_version_preserved": True,
        "numeric_available_at_preserved": True,
        "historical_pit_backfill": False,
        "note_pages_disclosure_only": True,
    }
    replacement_candidate = new_root / "statement-pit-candidate.json"
    _write_json(replacement_candidate, replacement_payload)
    replacement_candidate_hash = _sha256_reference(replacement_candidate)

    comparison["comparison"]["replacement_candidate_path"] = str(
        replacement_candidate.resolve()
    )
    comparison["comparison"]["replacement_candidate_sha256"] = replacement_candidate_hash
    comparison_path = new_root / _COMPARISON_NAME
    _write_json(comparison_path, comparison)

    old_files = old_manifest.get("files")
    if not isinstance(old_files, Mapping):
        raise ValueError("old child manifest files are malformed")
    file_names = [str(name) for name in old_files if str(name) != "candidate"]
    file_names.extend([_CORRECTION_EVIDENCE_NAME, _COMPARISON_NAME])
    file_names.append(f"raw_{_CORRECTION_RAW_NAME}")
    file_names = sorted(set(file_names))
    new_files = _hash_manifest_files(new_root, file_names)
    new_files["candidate"] = replacement_candidate_hash
    replacement_manifest_payload = dict(old_manifest)
    replacement_manifest_payload["run_id"] = child_name
    replacement_manifest_payload["files"] = new_files
    replacement_manifest_payload["correction_observed_at"] = comparison["source"][
        "response_received_at"
    ]
    replacement_manifest_payload["correction_capture_mode"] = comparison["source"][
        "capture_mode"
    ]
    replacement_manifest = new_root / "run-manifest.json"
    _write_json(replacement_manifest, replacement_manifest_payload)
    replacement_manifest_hash = _sha256_reference(replacement_manifest)

    old_candidate_hash = _sha256_reference(candidate_file)
    old_manifest_hash = _sha256_reference(old_manifest_file)
    record_payload: dict[str, Any] = {
        "schema_version": _SUPERSESSION_SCHEMA,
        "research_only": True,
        "formal_oos_allowed": False,
        "status": "accepted_replacement",
        "target": {
            "stock_code": "2230",
            "registry_market": (
                "twse" if str(candidate_payload["pit_coverage_summary"]["market_request"]) == "sii" else "tpex"
            ),
            "batch_market": str(candidate_payload["pit_coverage_summary"]["market_request"]),
            "period": _EXPECTED_PERIOD,
            "report_basis": "consolidated",
        },
        "superseded": {
            "candidate_path": str(candidate_file),
            "candidate_sha256": old_candidate_hash,
            "manifest_path": str(old_manifest_file),
            "manifest_sha256": old_manifest_hash,
        },
        "replacement": {
            "candidate_path": str(replacement_candidate.resolve()),
            "candidate_sha256": replacement_candidate_hash,
            "manifest_path": str(replacement_manifest.resolve()),
            "manifest_sha256": replacement_manifest_hash,
        },
        "reason": (
            "official t56 correction detail was observed and all seven page-7 "
            "numeric after-values matched the existing 2026-Q2 consolidated "
            "candidate by explicit XBRL item code; numeric capture and conservative "
            "availability were preserved and no historical PIT date was backfilled"
        ),
        "correction_comparison": {
            "path": str(comparison_path.resolve()),
            "sha256": _sha256_reference(comparison_path),
            "matched_item_count": 7,
            "disclosure_note_pages": [16, 19, 21, 30, 33, 34, 37],
        },
    }
    record_path = output_parent / "2230-supersedes-r28-correction-r1.json"
    _write_json(record_path, record_payload)
    return {
        "comparison_path": str(comparison_path.resolve()),
        "comparison_sha256": _sha256_reference(comparison_path),
        "replacement_candidate_path": str(replacement_candidate.resolve()),
        "replacement_candidate_sha256": replacement_candidate_hash,
        "replacement_manifest_path": str(replacement_manifest.resolve()),
        "replacement_manifest_sha256": replacement_manifest_hash,
        "supersession_record_path": str(record_path.resolve()),
        "supersession_record_sha256": _sha256_reference(record_path),
        "matched_item_count": 7,
        "preserved_numeric_available_at": candidate_payload["pit_coverage_summary"].get(
            "numeric_available_at"
        ),
        "preserved_numeric_available_date": candidate_payload["pit_coverage_summary"].get(
            "numeric_available_date"
        ),
        "old_candidate_sha256": old_candidate_hash,
        "old_manifest_sha256": old_manifest_hash,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--correction-html", type=Path, required=True)
    parser.add_argument("--correction-evidence", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--child-name", default="v4-quarterly-r33-2230-correction-r1-otc-2230-2026q2")
    args = parser.parse_args(argv)
    report = create_immutable_replacement(
        candidate_path=args.candidate,
        manifest_path=args.manifest,
        correction_html_path=args.correction_html,
        correction_evidence_path=args.correction_evidence,
        output_root=args.output_root,
        child_name=args.child_name,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
