from datetime import datetime, timedelta
from typing import List

class MarketDateRange:
    """市場數據日期範圍控制"""
    def __init__(self, start_date: str = None, end_date: str = None):
        self.end_date = end_date if end_date else datetime.today().strftime('%Y-%m-%d')
        self.start_date = start_date if start_date else self._get_default_start_date()
    
    @staticmethod
    def _get_default_start_date() -> str:
        """獲取預設起始日期（前一個月）"""
        return (datetime.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    @classmethod
    def last_n_days(cls, n: int) -> 'MarketDateRange':
        """創建最近 n 天的日期範圍"""
        end_date = datetime.today()
        start_date = end_date - timedelta(days=n)
        return cls(
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )
    
    @classmethod
    def last_month(cls) -> 'MarketDateRange':
        """創建最近一個月的日期範圍"""
        return cls.last_n_days(30)
    
    @classmethod
    def last_quarter(cls) -> 'MarketDateRange':
        """創建最近一季的日期範圍"""
        return cls.last_n_days(90)
    
    @classmethod
    def last_year(cls) -> 'MarketDateRange':
        """創建最近一年的日期範圍"""
        return cls.last_n_days(365)
    
    @classmethod
    def year_to_date(cls) -> 'MarketDateRange':
        """創建今年至今的日期範圍"""
        return cls(
            start_date=datetime.today().replace(month=1, day=1).strftime('%Y-%m-%d')
        )
    
    @property
    def date_range_str(self) -> str:
        """返回日期範圍的字符串表示"""
        return f"從 {self.start_date or '最早'} 到 {self.end_date}"
    
    def get_date_list(self) -> List[datetime]:
        """獲取日期範圍內的所有日期"""
        start = datetime.strptime(self.start_date, '%Y-%m-%d')
        end = datetime.strptime(self.end_date, '%Y-%m-%d')
        return [start + timedelta(days=x) for x in range((end-start).days + 1)] 