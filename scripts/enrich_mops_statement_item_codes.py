"""以官方 MOPS XBRL row code enrich 已捕捉的季度候選。

這個工具只讀取既有候選與其不可變 t164 HTML，另以單一公司單一期別的
MOPS XBRL 回應補上官方科目代號。它會建立新的 research output run，保留
輸入候選與 raw bytes，不覆寫輸入、D 槽資料或正式 SQLite。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.config import TWStockConfig
from development_module.output_guard import resolve_development_output_dir
from scripts.build_mops_statement_pit_candidate import (
    MOPS_STATEMENT_ENDPOINTS,
    MOPS_XBRL_URL,
    _canonical_sha256,
    _decode_mops_xbrl,
    _fetch_xbrl_response,
    _file_sha256_reference,
    _validate_xbrl_identity as _validate_official_xbrl_identity,
    parse_statement_table,
    parse_xbrl_item_codes,
    resolve_official_item_code,
)
from scripts.validate_mops_quarterly_artifact import validate_artifact


def enrich_candidate(
    *,
    candidate_path: Path,
    xbrl_body: bytes,
    output_root: Path,
    run_id: str,
) -> dict[str, Path]:
    """從不可變輸入建立含官方 row code 的新 candidate run。"""
    candidate_path = Path(candidate_path)
    if not candidate_path.is_file():
        raise FileNotFoundError(candidate_path)
    input_dir = candidate_path.parent.resolve()
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("research_only") is not True:
        raise ValueError("input candidate must be a research-only JSON object")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("input candidate rows must be a non-empty list")

    first_row = raw_rows[0]
    if not isinstance(first_row, Mapping):
        raise ValueError("input candidate row must be an object")
    stock_code = _required_text(first_row, "stock_code")
    period = _required_text(first_row, "period")
    try:
        year_text, quarter_text = period.split("-Q", 1)
        period_year = int(year_text)
        season = int(quarter_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("candidate period must be YYYY-Qn") from exc
    roc_year = period_year - 1911

    xbrl_text = _decode_mops_xbrl(xbrl_body)
    _validate_xbrl_identity(
        xbrl_text,
        stock_code=stock_code,
        period_year=period_year,
        season=season,
        market=_required_text(first_row, "market"),
    )
    xbrl_codes = parse_xbrl_item_codes(xbrl_text)
    xbrl_hash = _sha256_bytes(xbrl_body)

    parsed_by_type: dict[str, dict[str, Mapping[str, Any]]] = {}
    for statement_type, (endpoint, _, _) in MOPS_STATEMENT_ENDPOINTS.items():
        raw_path = input_dir / "raw" / f"{endpoint}_{stock_code}_{roc_year}Q{season}.html"
        if not raw_path.is_file():
            raise ValueError(f"input candidate is missing immutable raw source: {raw_path}")
        parsed = parse_statement_table(
            raw_path.read_text(encoding="utf-8", errors="strict"),
            statement_type=statement_type,
            roc_year=roc_year,
            season=season,
        )
        parsed_by_type[statement_type] = {
            f"sha256:{str(item['source_row_sha256'])}": item for item in parsed.rows
        }

    enriched_rows: list[dict[str, Any]] = []
    for row_index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"input candidate row {row_index} must be an object")
        statement_type = _required_text(raw_row, "statement_type")
        source_row_hash = _required_text(raw_row, "numeric_source_row_sha256")
        parsed_row = parsed_by_type.get(statement_type, {}).get(source_row_hash)
        if parsed_row is None:
            raise ValueError(
                "candidate row cannot be matched to its immutable t164 row; "
                f"statement_type={statement_type}; source_row={source_row_hash}"
            )
        item_name = _required_text(raw_row, "item_name")
        value = _required_int(raw_row, "value")
        value_scale = _required_int(raw_row, "value_scale")
        official_code = resolve_official_item_code(
            item_name,
            xbrl_codes,
            statement_type=statement_type,
            candidate_value=value,
            candidate_scale=value_scale,
            candidate_indent_depth=int(parsed_row["item_indent"]),
        )
        if official_code is None:
            raise ValueError(
                "MOPS XBRL row code is not uniquely proven for candidate row; "
                f"statement_type={statement_type}; item_name={item_name}"
            )
        enriched = dict(raw_row)
        enriched.update(
            {
                "item_code": official_code.item_code,
                "item_code_source": "mops.t164sb01.xbrl.row_code",
                "official_item_name": official_code.official_item_name,
                "xbrl_concept": official_code.xbrl_concept,
                "xbrl_reported_value": official_code.reported_value,
                "item_indent": int(parsed_row["item_indent"]),
                "official_indent_depth": official_code.indent_depth,
                "item_code_lineage_sha256": xbrl_hash,
            }
        )
        enriched["content_hash"] = _candidate_content_hash(enriched)
        enriched_rows.append(enriched)

    enriched_payload = dict(payload)
    enriched_payload["schema_version"] = "mops-statement-pit-candidate.v2"
    enriched_payload["source_version"] = (
        "mops-t164-consolidated-statements-with-t57sb01-xbrl-row-codes.v2"
    )
    enriched_payload["rows"] = enriched_rows
    enriched_payload["code_mapping_enriched_at"] = datetime.now(timezone.utc).isoformat()
    lineage = dict(_mapping(payload.get("lineage")))
    lineage["official_item_code_source"] = {
        "source_id": "mops.t164sb01.xbrl",
        "source_version": "mops-t164sb01-xbrl-row-code.v1",
        "source_url": MOPS_XBRL_URL,
        "raw_response": {
            "basename": f"mops_t164sb01_xbrl_{stock_code}_{roc_year}Q{season}.html",
            "sha256": xbrl_hash,
            "byte_count": len(xbrl_body),
        },
        "unique_code_name_count": len(xbrl_codes),
        "mapping_rule": "exact name first; explicit audited aliases; value and indentation disambiguation",
    }
    enriched_payload["lineage"] = lineage
    validate_artifact(enriched_payload)

    config = TWStockConfig()
    target = resolve_development_output_dir(
        output_root,
        run_id,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    if target.exists():
        raise ValueError("output run already exists; use a new immutable run_id")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.staging-", dir=target.parent))
    try:
        shutil.copytree(input_dir, staging, dirs_exist_ok=True)
        raw_dir = staging / "raw"
        xbrl_path = raw_dir / f"mops_t164sb01_xbrl_{stock_code}_{roc_year}Q{season}.html"
        xbrl_path.write_bytes(xbrl_body)

        statement_sources_path = staging / "statement-sources.json"
        if statement_sources_path.is_file():
            statement_sources_payload = json.loads(
                statement_sources_path.read_text(encoding="utf-8")
            )
            sources = statement_sources_payload.get("sources")
            if not isinstance(sources, list):
                raise ValueError("input statement-sources.json is malformed")
            for source in sources:
                if not isinstance(source, dict):
                    continue
                source_type = str(source.get("statement_type") or "")
                coded = [
                    row
                    for row in enriched_rows
                    if row.get("statement_type") == source_type
                ]
                source["source_version"] = "mops-t164sb03-04-05-with-t164sb01-xbrl-row-codes.v2"
                source["official_item_code_source"] = lineage["official_item_code_source"]
                source["rows"] = coded
            statement_sources_path.write_text(
                json.dumps(statement_sources_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            raise ValueError("input candidate is missing statement-sources.json")

        lineage["numeric_statement_source"] = {
            **_mapping(lineage.get("numeric_statement_source")),
            "source_version": "mops-t164sb03-04-05-with-t164sb01-xbrl-row-codes.v2",
            "artifact_sha256": _file_sha256_reference(statement_sources_path),
        }
        enriched_payload["lineage"] = lineage
        validate_artifact(enriched_payload)
        candidate_output = staging / "statement-pit-candidate.json"
        candidate_output.write_text(
            json.dumps(enriched_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        code_map_output = staging / "official-item-code-map.json"
        code_map_output.write_text(
            json.dumps(
                {
                    "schema_version": "mops-t164sb01-xbrl-row-code-map.v1",
                    "source_id": "mops.t164sb01.xbrl",
                    "source_url": MOPS_XBRL_URL,
                    "raw_response": {
                        "basename": xbrl_path.name,
                        "sha256": xbrl_hash,
                        "byte_count": len(xbrl_body),
                    },
                    "candidate_row_count": len(enriched_rows),
                    "mapped_row_count": len(enriched_rows),
                    "mappings": [
                        {
                            "statement_type": row["statement_type"],
                            "item_name": row["item_name"],
                            "item_code": row["item_code"],
                            "official_item_name": row["official_item_name"],
                            "xbrl_concept": row.get("xbrl_concept"),
                            "reported_value": row.get("xbrl_reported_value"),
                        }
                        for row in enriched_rows
                    ],
                    "research_only": True,
                    "formal_oos_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest = {
            "schema_version": "mops-statement-pit-run-manifest.v2",
            "run_id": run_id,
            "input_candidate": _file_sha256_reference(candidate_path),
            "captured_at": enriched_payload.get("captured_at"),
            "code_mapping_enriched_at": enriched_payload["code_mapping_enriched_at"],
            "files": {
                path.name: _file_sha256_reference(path)
                for path in sorted(staging.iterdir())
                if path.is_file() and path.name != "run-manifest.json"
            },
            "raw_files": {
                path.name: _file_sha256_reference(path)
                for path in sorted(raw_dir.iterdir())
                if path.is_file()
            },
            "research_only": True,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
        }
        manifest_path = staging / "run-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        validate_run_manifest(manifest_path)
        # Windows 無法以 os.replace 重新命名非空資料夾；target 尚不存在，
        # 以同磁碟 move 完成隔離 run 發布，輸入目錄仍保持唯讀。
        shutil.move(str(staging), str(target))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "output_directory": target,
        "candidate": target / "statement-pit-candidate.json",
        "manifest": target / "run-manifest.json",
        "code_map": target / "official-item-code-map.json",
        "xbrl_raw": target / "raw" / f"mops_t164sb01_xbrl_{stock_code}_{roc_year}Q{season}.html",
    }


def _candidate_content_hash(row: Mapping[str, Any]) -> str:
    fields = {
        key: row.get(key)
        for key in (
            "stock_code",
            "market",
            "statement_type",
            "statement_scope",
            "period",
            "period_start",
            "period_end",
            "period_basis",
            "item_name",
            "value",
            "value_unit",
            "value_scale",
            "item_code",
            "item_code_source",
            "official_item_name",
            "xbrl_concept",
            "xbrl_reported_value",
            "item_indent",
            "official_indent_depth",
        )
    }
    return _canonical_sha256(fields)


def validate_run_manifest(manifest_path: Path) -> None:
    """逐一核對 run manifest 的頂層檔案與 raw 檔案 hash。"""
    manifest_path = Path(manifest_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("run manifest must be a JSON object")
    files = payload.get("files")
    raw_files = payload.get("raw_files")
    if not isinstance(files, Mapping) or not isinstance(raw_files, Mapping):
        raise ValueError("run manifest must contain files and raw_files")
    if "run-manifest.json" in files:
        raise ValueError("run manifest cannot hash itself")
    root = manifest_path.parent.resolve()
    raw_root = (root / "raw").resolve()
    for name, expected in files.items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("run manifest contains an unsafe top-level path")
        if not isinstance(expected, str):
            raise ValueError("run manifest file hash must be text")
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise ValueError(f"run manifest top-level file is missing: {name}")
        if _file_sha256_reference(path) != expected:
            raise ValueError(f"run manifest top-level hash mismatch: {name}")
    for name, expected in raw_files.items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("run manifest contains an unsafe raw path")
        if not isinstance(expected, str):
            raise ValueError("run manifest raw hash must be text")
        path = (raw_root / name).resolve()
        if path.parent != raw_root or not path.is_file():
            raise ValueError(f"run manifest raw file is missing: {name}")
        if _file_sha256_reference(path) != expected:
            raise ValueError(f"run manifest raw file hash mismatch: {name}")


def _validate_xbrl_identity(
    html_text: str,
    *,
    stock_code: str,
    period_year: int,
    season: int,
    market: str | None = None,
) -> None:
    try:
        _validate_official_xbrl_identity(
            html_text,
            stock_code=stock_code,
            period_year=period_year,
            season=season,
            market=market,
        )
    except ValueError as error:
        raise ValueError(str(error).replace("the request", "candidate")) from error


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {field}")
    return value.strip()


def _required_int(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _sha256_bytes(body: bytes) -> str:
    from hashlib import sha256

    return f"sha256:{sha256(body).hexdigest()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    payload = json.loads(args.candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("rows"), list) or not payload["rows"]:
        raise ValueError("candidate rows are required")
    first_row = payload["rows"][0]
    if not isinstance(first_row, Mapping):
        raise ValueError("candidate row must be an object")
    period = _required_text(first_row, "period")
    period_year = int(period.split("-Q", 1)[0])
    season = int(period.split("-Q", 1)[1])
    xbrl_body = _fetch_xbrl_response(
        stock_code=_required_text(first_row, "stock_code"),
        roc_year=period_year - 1911,
        season=season,
        timeout_seconds=args.timeout_seconds,
        market=_required_text(first_row, "market"),
    )
    paths = enrich_candidate(
        candidate_path=args.candidate,
        xbrl_body=xbrl_body,
        output_root=args.output_root,
        run_id=args.run_id,
    )
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
