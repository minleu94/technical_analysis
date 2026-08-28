"""月營收 MOPS snapshot 檔案的唯讀選擇與檔名 metadata。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_SNAPSHOT_FILENAME = re.compile(
    r"^mops_monthly_revenue_snapshot_"
    r"(?P<start>\d{4}-\d{2})_(?P<end>\d{4}-\d{2})_"
    r"(?P<fetch_date>\d{4}-\d{2}-\d{2})\.csv$"
)


@dataclass(frozen=True)
class MonthlyRevenueSnapshotInfo:
    """從受控 snapshot 檔名解析出的非正式候選 metadata。"""

    path: Path
    start_period: str | None
    end_period: str | None
    fetch_date: str | None

    @property
    def latest_period(self) -> str | None:
        return self.end_period

    @property
    def is_named_snapshot(self) -> bool:
        return self.end_period is not None and self.fetch_date is not None


def inspect_monthly_revenue_snapshot(path: Path) -> MonthlyRevenueSnapshotInfo:
    """只讀取檔名，不讀取 CSV 內容，也不把檔名當成正式 provenance。"""

    resolved = Path(path).expanduser().resolve()
    match = _SNAPSHOT_FILENAME.match(resolved.name)
    if match is None:
        return MonthlyRevenueSnapshotInfo(
            path=resolved,
            start_period=None,
            end_period=None,
            fetch_date=None,
        )
    return MonthlyRevenueSnapshotInfo(
        path=resolved,
        start_period=match.group("start"),
        end_period=match.group("end"),
        fetch_date=match.group("fetch_date"),
    )


def iter_monthly_revenue_snapshot_files(snapshot_dir: Path) -> tuple[Path, ...]:
    """列出候選 snapshot；忽略備份檔、目錄與 symlink。"""

    root = Path(snapshot_dir).expanduser()
    if not root.is_dir():
        return ()
    return tuple(
        path
        for path in root.glob("mops_monthly_revenue_snapshot_*.csv")
        if path.is_file() and not path.is_symlink() and ".before_" not in path.name
    )


def select_latest_monthly_revenue_snapshot(snapshot_dir: Path) -> Path | None:
    """依資料期別、抓取日選最新 snapshot，而非依檔案大小猜測。"""

    candidates = iter_monthly_revenue_snapshot_files(snapshot_dir)
    if not candidates:
        return None

    def sort_key(path: Path) -> tuple[int, str, str, str, int, str]:
        info = inspect_monthly_revenue_snapshot(path)
        if info.is_named_snapshot:
            return (
                1,
                info.end_period or "",
                info.fetch_date or "",
                info.start_period or "",
                _mtime_ns(path),
                path.name,
            )
        return (0, "", "", "", _mtime_ns(path), path.name)

    return max(candidates, key=sort_key)


def _mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        # 檔案仍可被列出但 metadata 讀取受限時，期別／抓取日排序仍可用。
        return 0
