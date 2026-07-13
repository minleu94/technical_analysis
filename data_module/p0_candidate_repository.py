"""P0 candidate working-copy repository 的安全邊界。"""

from __future__ import annotations

from pathlib import Path


class ProductionPathRejectedError(ValueError):
    """目標解析到正式資料根或正式 DB 時拒絕。"""


def validate_candidate_working_copy_path(
    working_copy_db: str | Path | None,
    *,
    production_data_root: str | Path,
    production_db_path: str | Path,
) -> Path:
    """純路徑驗證；不建立目錄、DB、table 或 log。"""
    if working_copy_db is None or not str(working_copy_db).strip():
        raise ValueError("apply 必須提供 explicit working-copy DB path")

    candidate = Path(working_copy_db).expanduser().resolve(strict=False)
    data_root = Path(production_data_root).expanduser().resolve(strict=False)
    production_db = Path(production_db_path).expanduser().resolve(strict=False)
    if candidate == production_db or candidate == data_root or candidate.is_relative_to(data_root):
        raise ProductionPathRejectedError(f"candidate apply 拒絕正式資料路徑: {candidate}")
    return candidate
