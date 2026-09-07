"""
觀察清單服務 (Watchlist Service)
管理跨 Tab 共用的股票觀察清單
"""

import json
from pathlib import Path
from typing import Any, List, Dict, Optional, Set
from datetime import date, datetime
from contextlib import closing
import sqlite3
import pandas as pd
from data_module.watchlist_repository import WatchlistRepository
from dataclasses import dataclass, asdict


@dataclass
class WatchlistItem:
    """觀察清單項目"""
    stock_code: str
    stock_name: str
    added_at: str
    source: str  # 'market_watch', 'recommendation', 'manual'
    notes: str = ""
    tags: Optional[List[str]] = None
    source_id: str = ""
    
    def __post_init__(self):
        """初始化後處理"""
        if self.tags is None:
            self.tags = []
        if not self.added_at:
            self.added_at = datetime.now().isoformat()


@dataclass
class Watchlist:
    """觀察清單"""
    name: str
    items: List[WatchlistItem]
    created_at: str
    updated_at: str
    description: str = ""
    revision: int | None = None
    
    def __post_init__(self):
        """初始化後處理"""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()


class WatchlistService:
    """觀察清單服務"""
    
    def __init__(self, config, *, repository: WatchlistRepository | None = None):
        """
        初始化觀察清單服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.repository = repository
        # 儲存在 output_root/watchlist/
        self.watchlist_dir = config.resolve_output_path('watchlist')
        self.watchlist_dir.mkdir(parents=True, exist_ok=True)
        
        # 預設觀察清單檔案
        self.default_watchlist_file = self.watchlist_dir / "default.json"
        
        # 載入預設觀察清單
        self._ensure_default_watchlist()
    
    def _watchlist_file(self, watchlist_id: str) -> Path:
        if not watchlist_id or Path(watchlist_id).name != watchlist_id or any(char in watchlist_id for char in ("/", "\\", ":")):
            raise ValueError("無效候選池 ID")
        return self.watchlist_dir / f"{watchlist_id}.json"

    def _ensure_default_watchlist(self):
        # 讀取損毀資料時保留原檔並回報；不可自動備份改名或覆寫空清單。
        if self.repository is not None:
            return
        if not self.default_watchlist_file.exists():
            self._save_watchlist("default", Watchlist("預設觀察清單", [], datetime.now().isoformat(), datetime.now().isoformat(), "系統預設觀察清單"))

    def _load_watchlist(self, watchlist_id: str) -> Optional[Watchlist]:
        watchlist_file = self._watchlist_file(watchlist_id)
        revision = None
        if self.repository is not None:
            stored = self.repository.load(watchlist_id)
            if stored is None:
                return None
            data, revision = stored
        else:
            if not watchlist_file.exists():
                return None
            data = json.loads(watchlist_file.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("候選池資料損毀：必須包含 items 陣列")
        items = [WatchlistItem(**item) for item in data["items"]]
        return Watchlist(name=data.get("name", "未命名清單"), items=items,
                         created_at=data.get("created_at", ""), updated_at=data.get("updated_at", ""),
                         description=data.get("description", ""), revision=revision)

    def _save_watchlist(self, watchlist_id: str, watchlist: Watchlist):
        watchlist_file = self._watchlist_file(watchlist_id)
        watchlist.updated_at = datetime.now().isoformat()
        data = {"version": 1, "name": watchlist.name, "description": watchlist.description,
                "created_at": watchlist.created_at, "updated_at": watchlist.updated_at,
                "items": [asdict(item) for item in watchlist.items]}
        if self.repository is not None:
            watchlist.revision = self.repository.save(watchlist_id, data, expected_revision=watchlist.revision)
            return
        raw = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        # 同目錄原子取代；不先搬走來源，失敗仍保留既有有效 JSON。
        temp_file = watchlist_file.with_suffix(".json.tmp")
        temp_file.write_text(raw, encoding="utf-8")
        temp_file.replace(watchlist_file)

    def query_stock_names(self, stock_codes: List[str]) -> Dict[str, str]:
        """UI 的名稱查詢接點；只讀既有來源，不初始化市場資料庫。"""
        codes = [str(code).strip() for code in stock_codes if str(code).strip()]
        if not codes:
            return {}
        db_path = getattr(self.config, "db_file", None)
        if getattr(self.config, "use_sqlite", False) and db_path is not None and Path(db_path).is_file():
            try:
                with closing(sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)) as conn:
                    conn.execute("PRAGMA query_only=ON")
                    placeholders = ",".join("?" for _ in codes)
                    rows = conn.execute(f"SELECT 證券代號, 證券名稱 FROM daily_prices WHERE 證券代號 IN ({placeholders}) ORDER BY 日期", tuple(codes)).fetchall()
                    return {str(code): str(name) for code, name in rows if name and str(name).strip()}
            except sqlite3.Error:
                pass
        path = getattr(self.config, "stock_data_file", None)
        if path is None or not Path(path).is_file():
            return {}
        frame = pd.read_csv(path, dtype={"證券代號": str}, usecols=["證券代號", "證券名稱"])
        return {str(row["證券代號"]): str(row["證券名稱"]) for _, row in frame.iterrows()
                if str(row["證券代號"]) in codes and pd.notna(row["證券名稱"])}

    def get_default_watchlist(self) -> Optional[Watchlist]:
        """取得預設觀察清單"""
        return self._load_watchlist("default")
    
    def get_watchlist(self, watchlist_id: str = "default") -> Optional[Watchlist]:
        """
        取得觀察清單（包含完整 Metadata）
        
        Args:
            watchlist_id: 觀察清單ID（預設為 "default"）
        
        Returns:
            Watchlist 對象，如果不存在則返回 None
        """
        return self._load_watchlist(watchlist_id)
    
    def add_stocks(
        self,
        stocks: List[Dict[str, Any]],
        source: str = "manual",
        watchlist_id: str = "default"
    ) -> int:
        """
        新增股票到觀察清單
        
        Args:
            stocks: 股票列表，每個項目包含 stock_code 和 stock_name
            source: 來源（'market_watch', 'recommendation', 'manual'）
            watchlist_id: 觀察清單ID（預設為 "default"）
        
        Returns:
            新增的股票數量（排除重複）
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            watchlist = self._load_watchlist(watchlist_id)
            if watchlist is None:
                watchlist = Watchlist(
                    name="預設觀察清單" if watchlist_id == "default" else watchlist_id,
                    items=[],
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
            
            # 取得現有股票代號集合（避免重複）
            existing_codes = {item.stock_code for item in watchlist.items}
            
            # 新增股票
            added_count = 0
            for stock in stocks:
                try:
                    stock_code = stock.get('stock_code') or stock.get('證券代號')
                    stock_name = stock.get('stock_name') or stock.get('證券名稱', stock_code)
                    
                    # 驗證和清理數據
                    if not stock_code:
                        logger.warning(f"跳過無效的股票（缺少 stock_code）: {stock}")
                        continue
                    
                    # 確保是字符串且不為空
                    stock_code = str(stock_code).strip()
                    if not stock_code or stock_code.lower() in ['none', 'nan', '-', '']:
                        logger.warning(f"跳過無效的股票代號: {stock_code}")
                        continue
                    
                    if not stock_name:
                        stock_name = stock_code
                    else:
                        stock_name = str(stock_name).strip()
                        if not stock_name or stock_name.lower() in ['none', 'nan', '-', '']:
                            stock_name = stock_code
                    
                    # 如果已存在，跳過
                    if stock_code in existing_codes:
                        logger.debug(f"股票 {stock_code} 已在觀察清單中，跳過")
                        continue
                    
                    # 新增項目
                    raw_tags = stock.get('tags', [])
                    tags = raw_tags if isinstance(raw_tags, list) else []
                    item = WatchlistItem(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        added_at=datetime.now().isoformat(),
                        source=source,
                        notes=str(stock.get('notes', '')).strip(),
                        tags=[str(tag) for tag in tags],
                        source_id=str(stock.get("source_id") or stock.get("result_id") or "")
                    )
                    watchlist.items.append(item)
                    existing_codes.add(stock_code)
                    added_count += 1
                    logger.debug(f"成功添加股票到觀察清單: {stock_code} ({stock_name})")
                except Exception as e:
                    logger.error(f"處理股票數據時出錯: {stock}, 錯誤: {e}")
                    continue
            
            # 儲存
            if added_count > 0:
                self._save_watchlist(watchlist_id, watchlist)
                logger.info(f"成功添加 {added_count} 檔股票到觀察清單")
            
            return added_count
        except Exception as e:
            logger.error(f"添加股票到觀察清單失敗: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def remove_stocks(
        self,
        stock_codes: List[str],
        watchlist_id: str = "default"
    ) -> int:
        """
        從觀察清單移除股票
        
        Args:
            stock_codes: 要移除的股票代號列表
            watchlist_id: 觀察清單ID
        
        Returns:
            移除的股票數量
        """
        watchlist = self._load_watchlist(watchlist_id)
        if watchlist is None:
            return 0
        
        # 記錄原始數量
        original_count = len(watchlist.items)
        
        # 移除股票
        stock_codes_set = set(stock_codes)
        watchlist.items = [
            item for item in watchlist.items
            if item.stock_code not in stock_codes_set
        ]
        
        # 計算移除數量
        removed_count = original_count - len(watchlist.items)
        
        # 儲存
        self._save_watchlist(watchlist_id, watchlist)
        
        return removed_count
    
    def remove_stock(
        self,
        watchlist_id: str = "default",
        stock_code: str = None
    ) -> int:
        """
        從觀察清單移除單一股票（便捷方法）
        
        Args:
            watchlist_id: 觀察清單ID
            stock_code: 要移除的股票代號
        
        Returns:
            移除的股票數量（0 或 1）
        """
        if stock_code is None:
            return 0
        return self.remove_stocks([stock_code], watchlist_id)
    
    def clear_watchlist(self, watchlist_id: str = "default") -> bool:
        """
        清空觀察清單
        
        Args:
            watchlist_id: 觀察清單ID
        
        Returns:
            是否成功清空
        """
        watchlist = self._load_watchlist(watchlist_id)
        if watchlist is None:
            return False
        
        watchlist.items = []
        watchlist.updated_at = datetime.now().isoformat()
        self._save_watchlist(watchlist_id, watchlist)
        return True
    
    def get_stock_codes(self, watchlist_id: str = "default") -> List[str]:
        """
        取得觀察清單中的股票代號列表
        
        Args:
            watchlist_id: 觀察清單ID
        
        Returns:
            股票代號列表
        """
        watchlist = self._load_watchlist(watchlist_id)
        if watchlist is None:
            return []
        
        return [item.stock_code for item in watchlist.items]
    
    def get_stocks(self, watchlist_id: str = "default") -> List[Dict[str, Any]]:
        """
        取得觀察清單中的股票列表（包含詳細資訊）
        
        Args:
            watchlist_id: 觀察清單ID
        
        Returns:
            股票列表，每個項目包含 stock_code, stock_name, added_at, source 等
        """
        watchlist = self._load_watchlist(watchlist_id)
        if watchlist is None:
            return []
        
        return [
            {
                'stock_code': item.stock_code,
                'stock_name': item.stock_name,
                'added_at': item.added_at,
                'source': item.source,
                'notes': item.notes,
                'tags': item.tags,
                'source_id': item.source_id
            }
            for item in watchlist.items
        ]
    
    def list_watchlists(self) -> List[Dict[str, Any]]:
        """
        列出所有觀察清單
        
        Returns:
            觀察清單列表，每個項目包含 watchlist_id, name, item_count 等
        """
        watchlists = []
        ids = self.repository.list_ids() if self.repository is not None else [path.stem for path in self.watchlist_dir.glob("*.json")]
        for watchlist_id in ids:
            try:
                watchlist = self._load_watchlist(watchlist_id)
                if watchlist:
                    watchlists.append({
                        'watchlist_id': watchlist_id,
                        'name': watchlist.name,
                        'item_count': len(watchlist.items),
                        'created_at': watchlist.created_at,
                        'updated_at': watchlist.updated_at,
                        'description': watchlist.description
                    })
            except:
                continue
        
        return watchlists
    
    def create_watchlist(
        self,
        name: str,
        description: str = ""
    ) -> str:
        """
        建立新的觀察清單
        
        Args:
            name: 清單名稱
            description: 描述
        
        Returns:
            觀察清單ID
        """
        # 生成ID（使用時間戳）
        watchlist_id = f"watchlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        watchlist = Watchlist(
            name=name,
            items=[],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            description=description
        )
        
        self._save_watchlist(watchlist_id, watchlist)
        
        return watchlist_id
    
    def delete_watchlist(self, watchlist_id: str) -> bool:
        """
        刪除觀察清單
        
        Args:
            watchlist_id: 觀察清單ID
        
        Returns:
            是否成功刪除
        """
        # 不允許刪除預設清單
        if watchlist_id == "default":
            return False
        
        watchlist_file = self._watchlist_file(watchlist_id)
        if self.repository is not None:
            loaded = self.repository.load(watchlist_id)
            return self.repository.delete(watchlist_id, expected_revision=loaded[1]) if loaded else False
        if watchlist_file.exists():
            watchlist_file.unlink()
            return True
        
        return False

