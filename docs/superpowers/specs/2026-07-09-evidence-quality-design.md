# Evidence Quality Semantics Design

## Goal

Keep the existing MoneyDJ 48-branch update as the upstream source while making
the scheduled recommendation snapshot and evidence report distinguish expected
source limitations from actual data failures.

## Confirmed Facts

- The daily quick update already refreshes 48 tracked MoneyDJ branches and
  synchronizes `broker_flows` into the market SQLite database.
- MoneyDJ supplies ranked lots and amount lists, not complete branch trading
  detail. A stock that appears only in an amount list has no observed lots in
  that source; lots may be estimated from amount and closing price.
- The ordinary FinMind token limit is 600 requests per hour, but its
  government-bank dataset is sponsor-only and covers only eight banks. It
  cannot replace the 48-branch MoneyDJ source.
- The scheduled profile uses `fixed` thresholds. It does not persist a valid
  ranked eligible universe, so a score percentile cannot be derived honestly.

## Design

### Recommendation Percentile

For a fixed-threshold scheduled result with no persisted comparable universe,
`score_percentile_bp` remains absent and is explicitly `not applicable`; it is
not reported as `score_percentile_missing`. The result metadata records the
fixed-threshold ranking method so consumers can distinguish this from a missing
percentile in a ranking-based run. No percentile is calculated from only the
selected recommendations or from candidates filtered at a different stage.

### MoneyDJ Source Quality

MoneyDJ rows retain their observed, estimated, or unavailable provenance. The
evidence report aggregates that provenance per affected stock, including
observed, estimated, unavailable, and total event counts. A complete mixed
observed/estimated source is an advisory, not a missing-data failure.

The pipeline must not copy one snapshot-level source-quality advisory into
every derived risk-prompt event. The report counts the advisory once at its
source and retains event-level quality in the event payloads.

### Status Rules

- `failed`: execution error or blocking source gap.
- `degraded`: missing, stale, or below-threshold source coverage.
- `ready_with_advisories`: data is usable, with disclosed estimated provenance
  or accepted within-threshold exclusions.
- `ready`: no warnings or advisories.

The scheduled status service and UI display these states distinctly. An
advisory never implies that observed values were fabricated or that the
production evidence database was written.

## Boundaries

- Do not add FinMind to this flow without sponsor access and a documented
  source contract.
- Do not overwrite historical MoneyDJ raw files merely to retry ranked lists.
- Do not change recommendation weights, ranking scores, trading behavior, or
  evidence production-write settings.
- All percentage and coverage logic uses integer counts or `Decimal` at the
  domain boundary; it has no look-ahead dependency.

## Verification

- Test fixed-threshold results do not produce a percentile-missing warning.
- Test a mixed observed/estimated MoneyDJ summary is an advisory with its
  coverage counts retained.
- Test repeated derived risk prompts do not inflate source-quality warnings.
- Run the relevant evidence/scheduled tests, UI validation, type checks, and a
  manual scheduled dry-run. Verify the formal evidence DB remains unchanged.
