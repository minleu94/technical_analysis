# Architecture Governance Checklist

The following rules MUST be strictly followed when implementing the Runtime Subsystem and UI integration. These rules ensure the system maintains "State Machine Observatory" integrity and limits technical debt.

## 1. Forbidden Dependency Rules
* **UI Layer (`ui_qt/`)**:
  * MUST NOT import `json`, `os`, or perform direct File I/O related to runtime states.
  * MUST NOT import `RuntimeStore` or `local_file_store.py`.
  * MUST ONLY communicate with `app_module` through DTOs (`app_module.dtos.runtime_dtos`).
* **Orchestration Layer (`app_module/`)**:
  * MUST NOT import `PySide6`, `PyQt5`, or any Qt-specific libraries.
  * MUST NOT contain UI formatting strings (HTML, CSS).
* **Core Subsystem Layer (`runtime/`)**:
  * MUST NOT import `app_module` or `ui_qt`.
  * MUST ONLY depend on Python standard libraries.

## 2. DTO Boundary Validation
* `RuntimeSnapshotService` and `RuntimeHealthService` are the **only** components permitted to query `IRuntimeStore` and translate raw JSON into DTOs.
* `QtRuntimeBridge` is the **only** component allowed to subscribe to `EventBus` and emit Qt `Signals`.
* UI components (e.g., `RuntimeView`) MUST accept DTOs through `pyqtSignal` parameters and perform pure rendering.

## 3. Governance Checklist
- [x] Are DTOs completely agnostic to the storage format? (Yes)
- [x] Does the EventBus rely on `PySide6`? (No, pure Python `Callable` lists)
- [x] Is the Qt translation layer isolated? (Yes, in `ui_qt/bridges/`)
- [x] Does HealthService calculate trends properly? (Yes, `rejection_rate_trend` is computed)
- [x] Are FSM States fully declared? (Yes, `IDLE`, `THINKING`, `ERROR`, `RECOVERY`, `HALTED` etc.)
