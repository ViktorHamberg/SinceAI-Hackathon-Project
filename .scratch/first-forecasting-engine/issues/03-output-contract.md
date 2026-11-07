# Specify the forecast output contract

Parent: [First working forecasting engine](../map.md)
Label: wayfinder:grilling
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: none

## Question

What documented guarantees accompany the official CSV: column order, keys, units, UTC timestamps, step semantics, probability constraints, optional-field behavior, and completeness? Distinguish validation outputs from the final test submission.

## Comments

### 7 November 2026 — Contract proposal; awaiting user approval

Claimed by Codex. Checked README sections 2, 4, 5.1, and 7.3, make_templates.py, validate_submission.py, and the sample_submission.csv header. Original files remain unchanged; no engine has been implemented or tested.

Official requirements retained: all 13 template columns and their order; unique (forecast_origin_utc, step); integer steps 1–40; delivery_start_utc = origin + (step - 1) * 15 minutes; prices in EUR/MWh with p10 <= p50 <= p90; direction probabilities for up/down/none in [0,1] summing to one; strict spike events above spot +50 or below spot -50 EUR/MWh with probabilities in [0,1] summing to at most one. Official probability-sum tolerance is 0.001. Negative prices remain valid. Final test completeness means the supplied 673 origins and 26,920 rows. Validation uses its own origins/template and retains all 40 steps, including tail deliveries without scoring actuals.

Recommendations pending approval:

- Return forecast rows as a pandas DataFrame with the same 13 columns as the CSV. Use UTC-aware timestamps, integer steps, and finite numeric forecast values in memory; sort by origin and step. Keep required provenance accessible to Python callers separately from the forecast table, without depending on DataFrame attrs or adding submission columns. Exact container and function names are implementation details.
- Guarantee complete, valid results for every requested origin or raise a clear error identifying the affected origin/step/component. Do not silently drop failed origins, truncate horizons, substitute fabricated probabilities, or silently repair invalid predictions. Check constraints before returning and after CSV serialization. Export UTF-8, comma-separated, decimal-point CSV with canonical whole-second UTC Z timestamps and no index; preserve enough numeric precision to satisfy the official constraints. Acceptance commands/tolerances remain with the existing acceptance-procedure ticket.
- Leave data_cutoff_utc and top_drivers empty initially (missing values in memory, empty CSV cells), preserving both columns. Keep the full previously required calibration and inference provenance separately. A future-delivery timestamp can exceed the origin for legitimately published data, so maximum delivery timestamp is not a safe definition of data_cutoff_utc. No explainability ranking is claimed by the first baseline engine.

No decision has been resolved. The user has requested approval before resolution; the remaining ticket and map are unchanged.

### 7 November 2026 — Resolution

The user approved Q1, Q2, and Q3, adding that data_cutoff_utc and top_drivers must be populatable later without changing the public interface. This resolves this ticket only. No implementation is authorized or performed.

## Answer

### Public forecast table

Return forecasts as a pandas DataFrame with exactly the official 13 columns, in this order:

```text
forecast_origin_utc,delivery_start_utc,step,p10,p50,p90,p_up,p_down,p_none,p_spike_high,p_spike_low,data_cutoff_utc,top_drivers
```

Use timezone-aware UTC timestamp columns, integer steps, and finite numeric forecast values in memory. Sort rows by forecast_origin_utc and step. The unique key is (forecast_origin_utc, step). Each requested full-hour origin has exactly steps 1 through 40, with delivery_start_utc = forecast_origin_utc + (step - 1) * 15 minutes. Step 1 therefore starts at the origin.

Price columns contain imbalance-price quantiles in EUR/MWh, with p50 the point forecast and p10 <= p50 <= p90. Negative prices are valid. Direction columns contain probabilities of Fingrid 369 up/down/none, each in [0,1], summing to one. Spike columns contain probabilities of strict imbalance-price events above spot +50 or below spot -50 EUR/MWh, each in [0,1], summing to at most one. Apply the official probability-sum tolerance of 0.001 when checking serialized results; retain sufficient precision rather than treating the tolerance as a modeling allowance.

### Completeness, failures, and serialization

Return complete valid forecasts for every requested origin or raise a clear error identifying the affected origin, step, or component. Do not silently omit failed origins, truncate horizons, substitute fabricated probabilities, or silently repair invalid predictions. Preserve the previously agreed deliberate baseline quantile construction; this rule concerns invalid completed results rather than prohibiting that documented model behavior.

The final test output must match the supplied template identifiers and all 673 supplied origins, giving 26,920 rows. Validation uses its own generated origins/template, retaining all 40 steps per origin, including tail deliveries without scoring actuals. A single-origin application call returns 40 rows; test-file row counts are not imposed on arbitrary application calls.

CSV export preserves the same columns and identifiers, uses UTF-8, commas, decimal points, canonical whole-second UTC timestamps ending in Z, and no DataFrame index. Check constraints before returning the in-memory table and after serialization. Detailed execution commands and comparison tolerances remain with Define the reproducible run and acceptance procedure.

### Optional fields and interface stability

Both optional columns are permanent parts of the public table and CSV schema. Initially use missing values in memory and empty CSV cells. Define their types from the outset as nullable UTC timestamps for data_cutoff_utc and nullable text for top_drivers, so filling them later does not require a new return type, column, calling convention, or public function signature. Export must preserve valid supplied optional values rather than unconditionally replacing them with blanks. Callers must accept either missing or populated values from the beginning.

If populated later, data_cutoff_utc must follow the README's latest-data-used meaning and must not exceed the forecast origin. Its precise availability-based interpretation must be documented and include fitted-statistic dependencies; maximum delivery timestamp is unsafe because legitimately published future-delivery inputs may extend beyond the origin. top_drivers may contain truthful semicolon-separated driver names; it must not imply a measured importance ranking without evidence. Defining and calculating those future values is deferred, while support for their nullable types and preservation is part of the initial contract.

Keep the full calibration and per-origin inference provenance required by [Define fitting cutoffs and leakage safeguards](01-leakage-safeguards.md) separately accessible to Python callers. It must not rely on DataFrame attrs, add submission columns, or disappear merely because optional table fields are blank. Exact metadata container and API names remain implementation choices within the already-approved package boundaries.

Source: README sections 2, 4, 5.1, and 7.3; make_templates.py; validate_submission.py; and the sample_submission.csv header. These are contract decisions, not claims that an engine has passed validation or leakage checks. No new ticket is needed for this resolution.
