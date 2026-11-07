# Define fitting cutoffs and leakage safeguards

Parent: [First working forecasting engine](../map.md)
Label: wayfinder:grilling
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: none

## Question

What exact boundaries govern calibration, historical labels, and per-origin inputs for validation and test generation? What evidence will demonstrate that unavailable rows cannot influence predictions? Include missing-data behavior and already-published future-delivery data.

## Comments

### 7 November 2026 — Initial review; awaiting user decisions

Claimed by Codex. Reviewed README sections 3–7, availability.csv, make_templates.py, and baseline.ipynb source functions rows_available_at(), persistence_at(), calibrate(), and build_forecast(); did not execute the notebook or inspect its outputs.

The reference freezes calibration at the first origin of each forecast period and selects persistence inputs as of each individual origin. It does not explicitly bound calibration delivery timestamps to the permitted training period. Persistence searches three days first, then all earlier history. Missing spot data produces zero spike probabilities, while an empty eligible spot join or insufficient error history can produce invalid statistics. These are reference behaviors, not accepted policies for this engine.

Pending discussion:

- Freeze calibration separately for validation and test; explicitly enforce training-period and pre-validation label boundaries as well as availability cutoffs. Reconstruct each historical forecast's inputs as of its own origin. Permit already-published future-delivery inputs and newly available observed lags during inference without updating fitted statistics.
- Preserve the baseline's latest-usable persistence fallback with age recorded; fail clearly if no usable price or insufficient calibration evidence exists, including absent spot pairs, rather than inventing probabilities.
- Require availability assertions, calibration provenance, historical-pair checks, and invariance to changing or removing unavailable inputs and ineligible fitting labels. Keep scoring actuals separate from prediction generation.

These are recommendations awaiting the user's answers. No decision has been resolved and implementation has not begun.

### 7 November 2026 — Resolution

The user accepted Q1, Q2, and Q3, requesting verification of exact timestamps and explicit availability constraints for training labels and fitted statistics. The cutoffs below match README sections 3–4, the constants in baseline.ipynb's setup cell, and make_templates.py's build_origins() local-midnight conversion. Both boundary dates use Europe/Helsinki UTC+03:00. This resolves this ticket only; no implementation is authorized or performed.

## Answer

### Verified boundaries and frozen calibration

All comparisons use timezone-aware UTC timestamps. Delivery intervals below include their start and exclude their end; availability comparisons include the cutoff.

| Run | Eligible label delivery interval | Fitting availability cutoff C | Finnish-time meaning of C |
|---|---|---|---|
| Validation | `2026-05-31T21:00:00Z <= delivery < 2026-09-06T21:00:00Z` | `2026-09-06T21:00:00Z` | 7 September 2026, 00:00 |
| Test | `2026-05-31T21:00:00Z <= delivery < 2026-10-04T21:00:00Z` | `2026-10-04T21:00:00Z` | 5 October 2026, 00:00 |

The permitted overall training delivery period is 1 June through 4 October Finnish time. The earlier validation boundary is our agreed chronological holdout policy within that permitted period. Freezing calibration once per run is our selected baseline-compatible policy, not an additional organiser requirement.

Every label must satisfy BOTH its delivery interval and `first_usable_origin_utc <= C`. Being delivered before C alone is insufficient: an outcome published after C is excluded even if its delivery belongs to the training period. Availability exactly at C is permitted. No label at or beyond the exclusive delivery boundary is eligible, even if an input with that future delivery was already published.

Quantile offsets, direction frequencies, spike frequencies, and any other fitted or learned statistics must be derived solely from eligible evidence available at C and then remain frozen throughout the run. This includes any learned preprocessing, imputation, normalization, or fallback statistics if later introduced. Derived evidence inherits the latest availability of all its source dependencies; filtering only the final statistic's nominal timestamp is insufficient. Validation outcomes cannot fit the validation run. They may enter the separate final test fit only where both test-fit conditions hold. Test outcomes never enter fitting.

For each historical error-calibration pair with origin o and delivery d, reconstruct predictor inputs using only rows available at o, with o no later than C; admit the target only when d belongs to the run's eligible label interval and its label is available by C. A target need not have been available at o: it is the subsequently observed outcome used to measure that historical forecast's error. Each step uses only its eligible pairs; do not admit a whole 40-step horizon merely because its historical origin qualifies. Direction labels follow the same delivery and availability restrictions. Spike labels require an imbalance/spot pair at the same eligible delivery, with BOTH source rows available by C; retain the official strict thresholds above spot +50 and below spot -50 EUR/MWh.

### Per-origin inference and missing data

At each forecast origin t, apply `first_usable_origin_utc <= t` before feature construction or aggregation. Published future-delivery forecasts, spot prices, and known calendar inputs are permitted under that rule. Newly available observed validation/test values may supply inference lags, including the persistence observation, without updating fitted statistics. Keep scoring actuals_validation.csv outside prediction generation; obtain inference observations from the supplied input series.

Use the latest nonmissing usable imbalance observation for persistence. Preserve the reference's three-day search followed by all earlier history, without imposing a new staleness cap; record the selected observation's age. Never fill a gap using an unavailable future observation or interpolation that depends on one. Missing nonessential inputs remain missing unless a separately specified, availability-safe handling rule exists.

Stop clearly rather than emit a completed forecast if there is no usable persistence observation, any horizon step has no finite eligible calibration errors, direction history has no eligible valid labels, or spike calibration has no eligible finite imbalance/spot pairs. Require finite fitted values and valid resulting probabilities and quantiles. Positive eligible counts are the minimum computational requirement for this first engine, not a claim of statistical adequacy. In particular, absent spot evidence must not silently produce zero spike probabilities. Failures must identify the affected origin, step, or calibration component without exposing restricted values.

### Required leakage evidence

- Assert source-row availability at every inference origin and reconstructed historical origin, plus fitting-label membership in the approved delivery intervals and availability by C. Check all dependencies of fitted statistics, not only a summary maximum.
- Record separate calibration and inference provenance: fitting cutoff, label interval, eligible counts per horizon/component, latest label delivery, maximum source availability used, and persistence observation timestamp/age. Keep restricted prices out of logs and planning artifacts. A single optional CSV data_cutoff_utc value does not establish this evidence; its output semantics remain for Specify the forecast output contract.
- Require forecast invariance when unavailable input values are changed or their rows removed at a given origin, keeping eligible evidence fixed. Require calibration invariance when labels outside the delivery interval or unavailable at C are changed or removed. Include exact-boundary cases: availability equal to C/t is eligible; delivery equal to the label interval's upper bound is excluded.
- Ensure validation actuals are consumed only by scoring, after forecasts are generated. Validation horizons extending beyond the validation delivery period do not authorize fitting on those future labels; README section 7 explains that unlabelled tail deliveries are not scored.
- Preserve the official validator unchanged and use it for structure. Its success does not verify these leakage safeguards. Evidence checks are requirements for later implementation; none has been run against an engine yet.

### Source references

- [README — Schedule and data availability](../../../README.md#3-schedule): permitted training period, validation dates, first test origin, and binding availability rule in section 4.
- [README — Reference workflow](../../../README.md#73-baseline-notebook): frozen historical calibration and validation-tail scoring behavior in section 7.3.
- [Reference notebook](../../../baseline.ipynb): setup constants VALIDATION_FIRST_ORIGIN and TEST_FIRST_ORIGIN; rows_available_at(), persistence_at(), calibrate(), and build_forecast(). Only source cells were inspected.
- [Template generator](../../../make_templates.py): build_origins() converts local midnight boundaries to UTC.
