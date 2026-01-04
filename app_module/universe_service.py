"""
選股清單服務 (Universe/Watchlist Service)
管理選股清單的儲存、載入、刪除
"""

import json
import csv
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class Watchlist:
    """選股清單資料結構"""
    name: str
    codes: List[str]  # 股票代號列表
    source: str = "manual"  # 來源：manual, screening, industry, etc.
    filters: Dict = None  # 篩選條件（可選）
    created_at: str = None
    updated_at: str = None
    description: str = ""
    
    def __post_init__(self):
        """初始化後處理"""
        if self.filters is None:
            self.filters = {}
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.now().isoformat()
        # 清理代號（去除空白、去重）
        self.codes = list(set([str(c).strip() for c in self.codes if c]))


class UniverseService:
    """選股清單服務"""
    
    def __init__(self, config):
        """
        初始化選股清單服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        # 儲存在 data_root/backtest/watchlists/
        self.watchlists_dir = config.resolve_output_path('backtest/watchlists')
        self.watchlists_dir.mkdir(parents=True, exist_ok=True)
    
    def save_watchlist(
        self,
        name: str,
        codes: List[str],
        source: str = "manual",
        filters: Optional[Dict] = None,
        description: str = "",
        watchlist_id: Optional[str] = None
    ) -> str:
        """
        儲存選股清單
        
        Args:
            name: 清單名稱
            codes: 股票代號列表
            source: 來源
            filters: 篩選條件（可選）
            description: 描述（可選）
            watchlist_id: 清單ID（如果提供則更新，否則新建）
        
        Returns:
            清單ID
        """
        if watchlist_id is None:
            watchlist_id = f"watchlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        watchlist = Watchlist(
            name=name,
            codes=codes,
            source=source,
            filters=filters or {},
            description=description,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        # 如果更新現有清單，保留原始創建時間
        existing_file = self.watchlists_dir / f"{watchlist_id}.json"
        if existing_file.exists():
            try:
                existing_data = json.loads(existing_file.read_text(encoding='utf-8'))
                watchlist.created_at = existing_data.get('created_at', watchlist.created_at)
            except:
                pass
        
        # 儲存為JSON
        watchlist_file = self.watchlists_dir / f"{watchlist_id}.json"
        watchlist_data = {
            'version': 1,
            'watchlist_id': watchlist_id,
            **asdict(watchlist)
        }
        
        watchlist_file.write_text(
            json.dumps(watchlist_data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        return watchlist_id
    
    def list_watchlists(self) -> List[Dict[str, Any]]:
        """
        列出所有選股清單
        
        Returns:
            清單列表
        """
        watchlists = []
        
        for watchlist_file in self.watchlists_dir.glob("*.json"):
            try:
                data = json.loads(watchlist_file.read_text(encoding='utf-8'))
                watchlists.append({
                    'watchlist_id': data.get('watchlist_id', watchlist_file.stem),
                    'name': data.get('name', ''),
                    'codes': data.get('codes', []),
                    'source': data.get('source', 'manual'),
                    'count': len(data.get('codes', [])),
                    'created_at': data.get('created_at', ''),
                    'updated_at': data.get('updated_at', ''),
                    'description': data.get('description', '')
                })
            except Exception as e:
                print(f"[UniverseService] 讀取清單失敗 {watchlist_file}: {e}")
                continue
        
        # 按更新時間排序
        watchlists.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        return watchlists
    
    def load_watchlist(self, watchlist_id: str) -> Optional[Watchlist]:
        """
        載入選股清單
        
        Args:
            watchlist_id: 清單ID
        
        Returns:
            Watchlist 對象或 None
        """
        watchlist_file = self.watchlists_dir / f"{watchlist_id}.json"
        
        if not watchlist_file.exists():
            return None
        
        try:
            data = json.loads(watchlist_file.read_text(encoding='utf-8'))
            return Watchlist(
                name=data.get('name', ''),
                codes=data.get('codes', []),
                source=data.get('source', 'manual'),
                filters=data.get('filters', {}),
                description=data.get('description', ''),
                created_at=data.get('created_at'),
                updated_at=data.get('updated_at')
            )
        except Exception as e:
            print(f"[UniverseService] 載入清單失敗 {watchlist_id}: {e}")
            return None
    
    def delete_watchlist(self, watchlist_id: str) -> bool:
        """
        刪除選股清單
        
        Args:
            watchlist_id: 清單ID
        
        Returns:
            是否成功刪除
        """
        watchlist_file = self.watchlists_dir / f"{watchlist_id}.json"
        
        if not watchlist_file.exists():
            return False
        
        try:
            watchlist_file.unlink()
            return True
        except Exception as e:
            print(f"[UniverseService] 刪除清單失敗 {watchlist_id}: {e}")
            return False
    
    def parse_codes_from_text(self, text: str) -> List[str]:
        """
        從文字解析股票代號（支援逗號、換行、空格分隔）
        
        Args:
            text: 輸入文字
        
        Returns:
            股票代號列表
        """
        # 替換各種分隔符為換行
        text = text.replace(',', '\n').replace(';', '\n').replace(' ', '\n')
        
        codes = []
        for line in text.split('\n'):
            code = line.strip()
            if code:
                codes.append(code)
        
        return list(set(codes))  # 去重
    
    def export_watchlist_csv(self, watchlist_id: str, output_file: Optional[Path] = None) -> Path:
        """
        匯出選股清單為CSV
        
        Args:
            watchlist_id: 清單ID
            output_file: 輸出檔案路徑（可選）
        
        Returns:
            輸出檔案路徑
        """
        watchlist = self.load_watchlist(watchlist_id)
        if watchlist is None:
            raise ValueError(f"找不到清單: {watchlist_id}")
        
        if output_file is None:
            output_file = self.watchlists_dir / f"{watchlist_id}.csv"
        
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['股票代號'])
            for code in watchlist.codes:
                writer.writerow([code])
        
        return output_file
    
    def import_watchlist_csv(self, csv_file: Path, name: str, source: str = "imported") -> str:
        """
        從CSV匯入選股清單
        
        Args:
            csv_file: CSV檔案路徑
            name: 清單名稱
            source: 來源
        
        Returns:
            新的清單ID
        """
        codes = []
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader)  # 跳過標題
            for row in reader:
                if row and row[0].strip():
                    codes.append(row[0].strip())
        
        return self.save_watchlist(name, codes, source=source)

