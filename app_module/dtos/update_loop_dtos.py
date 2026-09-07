"""數據更新閉環的應用層狀態 DTO。

此模組只描述更新結果與唯讀狀態的交換契約，不負責資料庫查詢、檔案寫入
或技術指標計算。舊的 dict 回傳仍由 UpdateService 保留；DTO 透過
``to_dict`` 提供相容的序列化邊界，讓 UI 與後續服務可以逐步收斂到明確
的來源、實際日期、品質與警告欄位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping


def _canonical_date(value: Any) -> str | None:
    """將常見交易日表示轉成可比較的 ISO 日期；未知值維持 None。"""

    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw.lower() in {"nan", "nat", "none", "未知", "無"}:
        return None
    if raw.isdigit() and len(raw) >= 8:
        candidate = raw[:8]
        try:
            return date.fromisoformat(
                f"{candidate[:4]}-{candidate[4:6]}-{candidate[6:8]}"
            ).isoformat()
        except ValueError:
            return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        if len(raw) >= 10:
            return date.fromisoformat(raw[:10]).isoformat()
        if len(raw) == 7:
            year, month = (int(part) for part in raw.split("-"))
            return f"{year:04d}-{month:02d}"
    except (TypeError, ValueError):
        return None
    return raw


def _quality_for_status(status: str, total_records: int) -> str:
    """以明確狀態產生保守品質標籤；不把空資料標成 observed。"""

    normalized = status.strip().lower()
    if normalized in {"ok", "current", "reference", "summary"} and total_records > 0:
        return "observed"
    if normalized in {"lagging", "partial", "candidate_available"}:
        return "degraded"
    if normalized in {"missing", "empty", "unavailable", "unknown"}:
        return "unavailable"
    if normalized.startswith(("error", "failed", "failure", "exception")):
        return "error"
    return "unknown"


@dataclass(frozen=True)
class UpdateSourceStatusDTO:
    """單一更新來源的唯讀狀態。

    ``actual_date`` 表示該來源實際觀測到的最新日期，不能由呼叫端要求
    的檢查日期推測；``quality`` 與 ``warnings`` 用於讓 UI 保留降級語意。
    """

    source_id: str
    status: str = "unknown"
    latest_date: str | None = None
    actual_date: str | None = None
    quality: str = "unknown"
    total_records: int = 0
    source_version: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    candidate_only: bool = False
    read_mode: str | None = None

    @classmethod
    def from_mapping(
        cls,
        source_id: str,
        payload: Mapping[str, Any] | None,
    ) -> "UpdateSourceStatusDTO":
        """由既有 status dict 建立 DTO，保留缺資料與警告的明確語意。"""

        value = payload if isinstance(payload, Mapping) else {}
        status = str(value.get("status") or "unknown").strip() or "unknown"
        raw_count = value.get("total_records", 0)
        try:
            total_records = max(0, int(raw_count or 0))
        except (TypeError, ValueError):
            total_records = 0

        latest_date = _canonical_date(value.get("latest_date"))
        actual_date = _canonical_date(
            value.get("actual_date")
            or value.get("source_date")
            or value.get("observed_date")
            or value.get("latest_available_date")
            or value.get("available_date")
            or latest_date
        )
        raw_quality = value.get("quality") or value.get("quality_status")
        quality = str(raw_quality).strip() if raw_quality else _quality_for_status(status, total_records)
        raw_warnings = value.get("warnings") or value.get("quality_warnings") or []
        warnings: tuple[str, ...]
        if isinstance(raw_warnings, str):
            warnings = (raw_warnings,) if raw_warnings.strip() else ()
        else:
            warnings = tuple(
                str(item).strip()
                for item in raw_warnings
                if str(item).strip()
            )
        return cls(
            source_id=str(value.get("source_id") or source_id),
            status=status,
            latest_date=latest_date,
            actual_date=actual_date,
            quality=quality,
            total_records=total_records,
            source_version=(
                str(value["source_version"]).strip()
                if value.get("source_version") is not None
                else None
            ),
            warnings=tuple(dict.fromkeys(warnings)),
            candidate_only=bool(value.get("candidate_only", False)),
            read_mode=(
                str(value["read_mode"]).strip()
                if value.get("read_mode") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化為 UI／日誌可用的 plain dict。"""

        payload: dict[str, Any] = {
            "source_id": self.source_id,
            "status": self.status,
            "latest_date": self.latest_date,
            "actual_date": self.actual_date,
            "quality": self.quality,
            "total_records": self.total_records,
            "warnings": list(self.warnings),
            "candidate_only": self.candidate_only,
        }
        if self.source_version is not None:
            payload["source_version"] = self.source_version
        if self.read_mode is not None:
            payload["read_mode"] = self.read_mode
        return payload


@dataclass(frozen=True)
class UpdateStatusSnapshotDTO:
    """整體更新狀態快照；來源順序由呼叫端資料來源保留。"""

    sources: Mapping[str, UpdateSourceStatusDTO]
    snapshot_version: str = "update-status.v1"

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Mapping[str, Any]],
    ) -> "UpdateStatusSnapshotDTO":
        return cls(
            sources={
                str(source_id): UpdateSourceStatusDTO.from_mapping(source_id, value)
                for source_id, value in payload.items()
            }
        )

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {
            source_id: status.to_dict()
            for source_id, status in self.sources.items()
        }


# 供未來呼叫端使用的語意別名；不改變既有 dict API。
DataUpdateStatusDTO = UpdateSourceStatusDTO
UpdateStatusDTO = UpdateSourceStatusDTO


def enrich_status_mapping(
    payload: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """在保留既有欄位的前提下補上閉環狀態契約欄位。"""

    enriched: dict[str, dict[str, Any]] = {}
    for source_id, raw in payload.items():
        original = dict(raw) if isinstance(raw, Mapping) else {}
        dto = UpdateSourceStatusDTO.from_mapping(source_id, original)
        original.update(dto.to_dict())
        enriched[str(source_id)] = original
    return enriched
