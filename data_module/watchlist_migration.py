"""只在指定 sandbox 內驗證 JSON 候選池副本遷移，不改原檔。"""

import hashlib
import json
from pathlib import Path
from typing import Any

from data_module.watchlist_repository import WatchlistRepository


def migrate_watchlist_copy(source: Path, destination: Path, *, sandbox_root: Path, watchlist_id: str = "default") -> dict[str, Any]:
    root, source, destination = Path(sandbox_root).resolve(), Path(source).resolve(), Path(destination).resolve()
    if not source.is_relative_to(root) or not destination.is_relative_to(root) or source == destination:
        raise ValueError("來源副本與目標資料庫必須位於指定 sandbox 且互不相同")
    raw = source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("候選池 JSON 缺有效 items")
    codes = []
    for item in payload["items"]:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("stock_code", "stock_name", "added_at", "source")):
            raise ValueError("候選池存在不可遷移的項目")
        codes.append(item["stock_code"].strip())
    if len(set(codes)) != len(codes):
        raise ValueError("候選池存在重複股票身份")
    repository = WatchlistRepository(destination, initialize=True)
    existing = repository.load(watchlist_id)
    if existing is None:
        revision = repository.save(watchlist_id, payload, expected_revision=None, source_hash=source_hash)
    elif existing[0] == payload:
        revision = existing[1]
    else:
        raise RuntimeError("目標候選池已存在不同內容；禁止覆寫")
    loaded = repository.load(watchlist_id)
    if loaded is None or loaded[0] != payload or hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("候選池遷移比對失敗")
    return {"schema_version": "watchlist-copy.v1", "source_hash": source_hash, "item_count": len(codes), "revision": revision, "source_unchanged": True}
