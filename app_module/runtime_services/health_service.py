from runtime.interfaces.store_interface import IRuntimeStore
from app_module.dtos.runtime_dtos import RuntimeHealthSnapshotDTO, RuntimeState, RuntimeEventDTO, GovernanceSeverity
from typing import List, Dict, Any
from datetime import datetime

class RuntimeHealthService:
    """
    Service responsible for Trend Analysis, Governance tracking, and determining FSM health state.
    """
    def __init__(self, store: IRuntimeStore):
        self.store = store
        
    def get_health_snapshot(self) -> RuntimeHealthSnapshotDTO:
        events = self.store.read_latest_events(100)
        
        is_healthy = True
        current_state = RuntimeState.IDLE
        consecutive_failures = 0
        last_critical = None
        
        rejections = 0
        total_validations = 0
        
        for e in events:
            sev_str = e.get("severity", "INFO")
            try:
                severity = GovernanceSeverity[sev_str.upper()]
            except KeyError:
                severity = GovernanceSeverity.INFO
                
            event_type = e.get("event_type", "")
            
            if event_type == "validation_rejected":
                rejections += 1
                total_validations += 1
                consecutive_failures += 1
                
                # Check for critical governance boundaries
                reason = e.get("payload", {}).get("reason", "")
                if reason in ["SchemaViolation", "GovernanceViolation"]:
                    severity = GovernanceSeverity.CRITICAL
                    
                if severity == GovernanceSeverity.CRITICAL:
                    is_healthy = False
                    current_state = RuntimeState.HALTED
                    
                    # Ensure timestamp parsing logic (fallback to now for MVP)
                    dt = datetime.utcnow()
                    if "timestamp" in e:
                        try:
                            # Parse "2026-05-12T15:30:00Z"
                            ts_str = e["timestamp"].replace("Z", "+00:00")
                            dt = datetime.fromisoformat(ts_str)
                        except Exception:
                            pass
                            
                    last_critical = RuntimeEventDTO(
                        event_id=e.get("event_id", ""),
                        timestamp=dt,
                        actor=e.get("actor", "system"),
                        event_type=event_type,
                        severity=severity,
                        human_readable_message=reason,
                        payload_preview=e.get("payload", {})
                    )
            elif event_type == "validation_approved":
                total_validations += 1
                consecutive_failures = 0
                if current_state != RuntimeState.HALTED:
                    current_state = RuntimeState.APPROVED
        
        rejection_rate = (rejections / total_validations) if total_validations > 0 else 0.0
        
        # Trend Analysis
        trend = "STABLE"
        if rejection_rate > 0.4:
            trend = "UP"
        elif rejection_rate < 0.15:
            trend = "DOWN"
            
        if not last_critical and consecutive_failures > 0:
            current_state = RuntimeState.ERROR
            
        return RuntimeHealthSnapshotDTO(
            is_healthy=is_healthy,
            current_state=current_state,
            rejection_rate=rejection_rate,
            rejection_rate_trend=trend,
            consecutive_failures=consecutive_failures,
            last_critical_violation=last_critical
        )
