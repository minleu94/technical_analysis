# Data Update Workbench Redesign

## Purpose

Redesign the Qt data update tab into a more professional operations workbench while preserving the existing information and actions. The page should make current data health easy to scan, keep single-source update controls available, and add a safe "update all data" path for routine use.

## Chosen Direction

Use a mixed workbench layout:

- A left navigation rail lists update areas.
- The right content area changes based on the selected area.
- "All Data" is the default landing view and acts as the command center.
- Individual data areas keep their existing update, merge, and configuration controls close to their status.

Left navigation items:

- All Data
- Daily Stock Data
- Market Index
- Industry Index
- Broker Branch
- Technical Indicators

## All Data View

The All Data view provides the routine operating flow.

It shows a summary of every data source:

- latest date
- total records
- status

It includes one primary action:

- Safe Update All Data

Safe Update All Data runs the conservative routine workflow:

1. Check data status.
2. Update missing daily stock data for the selected lookback range.
3. Update market index data for the same range.
4. Update industry index data for the same range.
5. Update broker branch data for the same range.
6. Merge daily stock data.
7. Merge broker branch data.
8. Calculate technical indicators in incremental mode.
9. Refresh data status.

The view also shows:

- current step
- progress indicator
- final success/failure summary
- shared update log

## Advanced Rebuild

High-cost or potentially disruptive operations should not sit beside the routine primary action. They should live in a clearly separated advanced rebuild area, collapsed or visually secondary by default.

Advanced rebuild actions:

- Force re-merge daily data.
- Force full technical indicator recalculation.

These actions keep the current confirmation behavior and warning copy. They are intended for repair or rebuild situations, not daily use.

## Individual Data Views

Each individual data view shows the selected source's status and controls:

- source-specific latest date, total records, and status
- existing date range or lookback configuration when relevant
- existing single-source update action
- source-specific merge action when relevant
- operation result summary

Daily Stock Data keeps:

- lookback range
- end date
- update daily stock data
- merge daily data
- force re-merge daily data in advanced area

Market Index keeps:

- lookback range
- end date
- update market index data

Industry Index keeps:

- lookback range
- end date
- update industry index data

Broker Branch keeps:

- lookback range
- end date
- update broker branch data
- merge broker branch data

Technical Indicators keeps:

- incremental update
- full recalculation
- optional stock code input
- success, failure, and insufficient-data result counts

## Existing Information To Preserve

The redesign must preserve the current functional surface from `ui_qt/views/update_view.py`:

- data status for daily stock data, market index, industry index, and broker branch data
- update type selection behavior, represented through the new navigation model
- end date selection
- lookback days selection
- update action
- merge daily data action
- force re-merge action
- merge broker branch data action
- check data status action
- technical indicator mode selection
- optional technical indicator stock code input
- calculate technical indicators action
- progress bar
- progress label
- update log
- existing result dialogs and error handling patterns

## Service Design

Keep the existing update service methods as the first implementation target:

- `check_data_status`
- `update_daily`
- `update_market`
- `update_industry`
- `update_broker_branch`
- `merge_daily_data`
- `merge_broker_branch_data`
- `calculate_technical_indicators`

Add a UI-level orchestration path for Safe Update All Data first. If the sequence becomes too large or needs reuse outside the UI, extract it into `UpdateService` after the UI behavior is proven.

The safe update workflow should run in a background worker and report progress per step. It should stop on critical failures and summarize completed, failed, and skipped steps in the log and final dialog.

## Error Handling

Use the existing conventions:

- disable relevant action buttons while a worker is running
- show a visible progress indicator
- log each step with timestamps
- show friendly dialogs for final success, partial failure, or critical failure
- truncate very long errors in dialogs and keep full details in logs
- refresh data status after successful update or merge operations

For Safe Update All Data:

- failures in one core data update step should stop later dependent steps
- final output should list the step that failed
- partial progress should remain visible in the log

## Testing And Validation

Validation should cover:

- service contract remains compatible with the current QA script
- the update tab initializes without errors
- each left navigation item switches the displayed content
- existing single-source actions still call the expected service methods
- Safe Update All Data runs the expected step sequence with mocked service results
- failure in one step produces a clear partial-failure result
- progress labels and button enabled states are restored after success and failure

Manual visual QA should verify:

- the workbench reads clearly on typical desktop width
- no text overlaps in buttons, status panels, or navigation labels
- advanced rebuild actions are visually separated from routine safe update actions

## Scope Boundaries

In scope:

- layout redesign of the data update tab
- navigation-based organization
- safe update all orchestration
- preserving existing controls and behavior
- focused tests or QA updates needed for the new layout

Out of scope:

- replacing the underlying data fetching scripts
- changing the external data format
- changing the technical indicator calculation algorithm
- adding scheduling or background automation
- redesigning unrelated tabs
