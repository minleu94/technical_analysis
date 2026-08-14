from datetime import datetime, timedelta, timezone
from typing import Callable

from runtime.interfaces.store_interface import IRuntimeStore
from app_module.dtos.runtime_dtos import (
    RuntimeHealthSnapshotDTO,
    RuntimeState,
    RuntimeEventDTO,
    GovernanceSeverity,
)
from app_module.runtime_services.event_time import parse_runtime_event_timestamp

class RuntimeHealthService:
    """
    Service responsible for Trend Analysis, Governance tracking, and determining FSM health state.
    """
    def __init__(
        self,
        store: IRuntimeStore,
        *,
        now_provider: Callable[[], datetime] | None = None,
        current_window: timedelta = timedelta(hours=24),
        future_tolerance: timedelta = timedelta(minutes=5),
    ):
        self.store = store
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._current_window = current_window
        self._future_tolerance = future_tolerance

    def get_health_snapshot(self) -> RuntimeHealthSnapshotDTO:
        read_result = self.store.read_latest_events_result(100)
        events = read_result.events
        now = _as_utc(self._now_provider())
        parsed_events = [
            (event, parse_runtime_event_timestamp(event.get("timestamp")))
            for event in events
            if isinstance(event, dict)
        ]
        valid_events = [
            (event, timestamp)
            for event, timestamp in parsed_events
            if timestamp is not None
        ]
        future_events = [
            (event, timestamp)
            for event, timestamp in valid_events
            if timestamp > now + self._future_tolerance
        ]
        eligible_events = [
            (event, timestamp)
            for event, timestamp in valid_events
            if timestamp <= now + self._future_tolerance
        ]
        current_events = [
            (event, timestamp)
            for event, timestamp in eligible_events
            if timestamp >= now - self._current_window
        ]
        historical_events = [
            (event, timestamp)
            for event, timestamp in eligible_events
            if timestamp < now - self._current_window
        ]
        current_events.sort(key=lambda item: item[1])
        historical_events.sort(key=lambda item: item[1])
        invalid_timestamp_count = len(parsed_events) - len(valid_events)
        latest_event = max(valid_events, key=lambda item: item[1], default=None)
        latest_event_at = latest_event[1] if latest_event is not None else None
        latest_event_raw = (
            str(latest_event[0].get("timestamp"))
            if latest_event is not None and latest_event[0].get("timestamp") is not None
            else None
        )
        
        is_healthy = read_result.read_state not in {"degraded", "unavailable"}
        current_state = RuntimeState.IDLE
        consecutive_failures = 0
        last_critical = None
        
        rejections = 0
        total_validations = 0
        
        last_historical_critical = None
        for e, timestamp in current_events:
            sev_str = str(e.get("severity", "INFO"))
            try:
                severity = GovernanceSeverity[sev_str.upper()]
            except KeyError:
                severity = GovernanceSeverity.INFO
                
            event_type = str(e.get("event_type", ""))
            
            if event_type == "validation_rejected":
                rejections += 1
                total_validations += 1
                consecutive_failures += 1
                
                # Check for critical governance boundaries
                payload = _payload_dict(e)
                reason = str(payload.get("reason", ""))
                if reason in ["SchemaViolation", "GovernanceViolation"]:
                    severity = GovernanceSeverity.CRITICAL
                    
                if severity == GovernanceSeverity.CRITICAL:
                    is_healthy = False
                    current_state = RuntimeState.HALTED
                    
                    last_critical = RuntimeEventDTO(
                        event_id=str(e.get("event_id", "")),
                        timestamp=timestamp,
                        actor=str(e.get("actor", "system")),
                        event_type=event_type,
                        severity=severity,
                        human_readable_message=reason,
                        payload_preview=payload,
                        timestamp_raw=str(e.get("timestamp")) if e.get("timestamp") is not None else None,
                    )
            elif event_type == "validation_approved":
                total_validations += 1
                consecutive_failures = 0
                if current_state != RuntimeState.HALTED:
                    current_state = RuntimeState.APPROVED
        
        for e, timestamp in historical_events:
            if _is_critical_violation(e):
                last_historical_critical = RuntimeEventDTO(
                    event_id=str(e.get("event_id", "")),
                    timestamp=timestamp,
                    actor=str(e.get("actor", "system")),
                    event_type=str(e.get("event_type", "")),
                    severity=GovernanceSeverity.CRITICAL,
                    human_readable_message=str(_payload_dict(e).get("reason", "")),
                    payload_preview=_payload_dict(e),
                    timestamp_raw=str(e.get("timestamp")) if e.get("timestamp") is not None else None,
                )

        rejection_rate = (rejections / total_validations) if total_validations > 0 else 0.0
        
        # Trend Analysis
        trend = "STABLE"
        if rejection_rate > 0.4:
            trend = "UP"
        elif rejection_rate < 0.15:
            trend = "DOWN"
            
        if not last_critical and consecutive_failures > 0:
            current_state = RuntimeState.ERROR

        if read_result.read_state == "unavailable":
            observation_scope = "event_log_unreadable"
            current_state = RuntimeState.IDLE
        elif current_events:
            observation_scope = "current"
        elif historical_events:
            observation_scope = "historical_only"
            current_state = RuntimeState.IDLE
        elif future_events:
            observation_scope = "timestamp_future"
            current_state = RuntimeState.IDLE
        elif invalid_timestamp_count:
            observation_scope = "timestamp_invalid"
            current_state = RuntimeState.IDLE
        elif read_result.read_state == "degraded":
            observation_scope = "event_log_degraded"
            current_state = RuntimeState.IDLE
        else:
            observation_scope = "no_events"

        if observation_scope != "current":
            last_critical = last_historical_critical
            
        return RuntimeHealthSnapshotDTO(
            is_healthy=is_healthy,
            current_state=current_state,
            rejection_rate=rejection_rate,
            rejection_rate_trend=trend,
            consecutive_failures=consecutive_failures,
            last_critical_violation=last_critical,
            observation_scope=observation_scope,
            latest_event_at=latest_event_at,
            latest_event_timestamp_raw=latest_event_raw,
            historical_event_count=len(historical_events),
            timestamp_invalid_count=invalid_timestamp_count,
            future_event_count=len(future_events),
            event_log_read_state=read_result.read_state,
            event_log_diagnostic=read_result.diagnostic,
        )


def _is_critical_violation(event: dict) -> bool:
    event_type = event.get("event_type", "")
    reason = _payload_dict(event).get("reason", "")
    severity = str(event.get("severity", "INFO")).upper()
    return event_type == "validation_rejected" and (
        severity == "CRITICAL" or reason in {"SchemaViolation", "GovernanceViolation"}
    )


def _payload_dict(event: dict) -> dict:
    payload = event.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
