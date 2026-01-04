"""
觀察清單服務 (Watchlist Service)
管理跨 Tab 共用的股票觀察清單
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class WatchlistItem:
    """觀察清單項目"""
    stock_code: str
    stock_name: str
    added_at: str
    source: str  # 'market_watch', 'recommendation', 'manual'
    notes: str = ""
    tags: List[str] = None
    
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
    
    def __post_init__(self):
        """初始化後處理"""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()


class WatchlistService:
    """觀察清單服務"""
    
    def __init__(self, config):
        """
        初始化觀察清單服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        # 儲存在 output_root/watchlist/
        self.watchlist_dir = config.resolve_output_path('watchlist')
        self.watchlist_dir.mkdir(parents=True, exist_ok=True)
        
        # 預設觀察清單檔案
        self.default_watchlist_file = self.watchlist_dir / "default.json"
        
        # 載入預設觀察清單
        self._ensure_default_watchlist()
    
    def _ensure_default_watchlist(self):
        """確保預設觀察清單存在"""
        if not self.default_watchlist_file.exists():
            default_watchlist = Watchlist(
                name="預設觀察清單",
                items=[],
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                description="系統預設觀察清單"
            )
            self._save_watchlist("default", default_watchlist)
        else:
            # 文件存在，嘗試載入以驗證是否損壞
            try:
                watchlist = self._load_watchlist("default")
                if watchlist is None:
                    # 文件損壞，創建新的
                    default_watchlist = Watchlist(
                        name="預設觀察清單",
                        items=[],
                        created_at=datetime.now().isoformat(),
                        updated_at=datetime.now().isoformat(),
                        description="系統預設觀察清單"
                    )
                    self._save_watchlist("default", default_watchlist)
            except Exception as e:
                # 載入失敗，備份並創建新的
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"預設觀察清單文件損壞，將創建新的: {e}")
                
                # 備份損壞的文件
                backup_file = self.default_watchlist_file.with_suffix('.json.bak')
                try:
                    self.default_watchlist_file.rename(backup_file)
                    logger.info(f"已備份損壞的文件到: {backup_file}")
                except Exception as backup_error:
                    logger.error(f"備份文件失敗: {backup_error}")
                
                # 創建新的觀察清單
                default_watchlist = Watchlist(
                    name="預設觀察清單",
                    items=[],
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat(),
                    description="系統預設觀察清單"
                )
                self._save_watchlist("default", default_watchlist)
    
    def _load_watchlist(self, watchlist_id: str) -> Optional[Watchlist]:
        """載入觀察清單"""
        watchlist_file = self.watchlist_dir / f"{watchlist_id}.json"
        if not watchlist_file.exists():
            return None
        
        try:
            # 讀取文件內容
            file_content = watchlist_file.read_text(encoding='utf-8')
            if not file_content.strip():
                # 文件為空，創建新的觀察清單
                return None
            
            # 解析 JSON
            data = json.loads(file_content)
            
            # 驗證數據結構
            if not isinstance(data, dict):
                raise ValueError("觀察清單數據格式錯誤：不是字典格式")
            
            # 解析項目
            items = []
            for item_data in data.get('items', []):
                try:
                    item = WatchlistItem(**item_data)
                    items.append(item)
                except Exception as e:
                    # 跳過無效的項目，繼續處理其他項目
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"跳過無效的觀察清單項目: {item_data}, 錯誤: {e}")
                    continue
            
            return Watchlist(
                name=data.get('name', '未命名清單'),
                items=items,
                created_at=data.get('created_at', datetime.now().isoformat()),
                updated_at=data.get('updated_at', datetime.now().isoformat()),
                description=data.get('description', '')
            )
        except json.JSONDecodeError as e:
            # JSON 解析錯誤，備份損壞的文件並創建新的
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"觀察清單文件損壞（JSON 解析錯誤）: {watchlist_file}, 錯誤: {e}")
            
            # 備份損壞的文件
            backup_file = watchlist_file.with_suffix('.json.bak')
            try:
                watchlist_file.rename(backup_file)
                logger.info(f"已備份損壞的文件到: {backup_file}")
            except Exception as backup_error:
                logger.error(f"備份文件失敗: {backup_error}")
            
            # 返回 None，讓調用者創建新的觀察清單
            return None
        except Exception as e:
            # 其他錯誤，記錄並返回 None
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"載入觀察清單失敗: {watchlist_file}, 錯誤: {e}")
            return None
    
    def _save_watchlist(self, watchlist_id: str, watchlist: Watchlist):
        """儲存觀察清單"""
        import logging
        logger = logging.getLogger(__name__)
        
        watchlist_file = self.watchlist_dir / f"{watchlist_id}.json"
        watchlist.updated_at = datetime.now().isoformat()
        
        try:
            # 準備數據
            items_data = []
            for item in watchlist.items:
                try:
                    # 確保所有字段都是可序列化的
                    item_dict = {
                        'stock_code': str(item.stock_code),
                        'stock_name': str(item.stock_name),
                        'added_at': str(item.added_at),
                        'source': str(item.source),
                        'notes': str(item.notes) if item.notes else '',
                        'tags': [str(tag) for tag in (item.tags or [])]
                    }
                    items_data.append(item_dict)
                except Exception as e:
                    logger.warning(f"跳過無法序列化的項目: {item}, 錯誤: {e}")
                    continue
            
            data = {
                'version': 1,
                'name': str(watchlist.name),
                'description': str(watchlist.description) if watchlist.description else '',
                'created_at': str(watchlist.created_at),
                'updated_at': str(watchlist.updated_at),
                'items': items_data
            }
            
            # 先寫入臨時文件，然後重命名（原子操作）
            temp_file = watchlist_file.with_suffix('.json.tmp')
            try:
                json_str = json.dumps(data, ensure_ascii=False, indent=2)
                temp_file.write_text(json_str, encoding='utf-8')
                
                # 驗證 JSON 是否有效
                json.loads(json_str)
                
                # 原子操作：重命名臨時文件為正式文件
                if watchlist_file.exists():
                    backup_file = watchlist_file.with_suffix('.json.bak')
                    watchlist_file.rename(backup_file)
                
                temp_file.rename(watchlist_file)
                
                # 刪除備份文件（如果存在）
                backup_file = watchlist_file.with_suffix('.json.bak')
                if backup_file.exists():
                    backup_file.unlink()
                
                logger.debug(f"成功保存觀察清單: {watchlist_file}")
            except json.JSONEncodeError as e:
                logger.error(f"JSON 編碼錯誤: {e}")
                if temp_file.exists():
                    temp_file.unlink()
                raise
            except Exception as e:
                logger.error(f"保存觀察清單文件失敗: {e}")
                if temp_file.exists():
                    temp_file.unlink()
                raise
        except Exception as e:
            logger.error(f"準備觀察清單數據失敗: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def get_default_watchlist(self) -> Watchlist:
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
        stocks: List[Dict[str, str]],
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
                    item = WatchlistItem(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        added_at=datetime.now().isoformat(),
                        source=source,
                        notes=str(stock.get('notes', '')).strip(),
                        tags=stock.get('tags', []) if isinstance(stock.get('tags'), list) else []
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
    
    def get_stocks(self, watchlist_id: str = "default") -> List[Dict[str, str]]:
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
                'tags': item.tags
            }
            for item in watchlist.items
        ]
    
    def list_watchlists(self) -> List[Dict[str, str]]:
        """
        列出所有觀察清單
        
        Returns:
            觀察清單列表，每個項目包含 watchlist_id, name, item_count 等
        """
        watchlists = []
        for watchlist_file in self.watchlist_dir.glob("*.json"):
            watchlist_id = watchlist_file.stem
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
        
        watchlist_file = self.watchlist_dir / f"{watchlist_id}.json"
        if watchlist_file.exists():
            watchlist_file.unlink()
            return True
        
        return False

