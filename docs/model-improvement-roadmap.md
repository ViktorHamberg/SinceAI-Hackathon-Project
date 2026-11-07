# Forecasting engine: incremental model-improvement plan

**Status: Proposed for review. Planning only; no implementation, training or dependency
installation is authorized by this document. The user confirmed on 7 November 2026
that the original engine's Step 6 passed independent review and was published. Older
documents describing that review as pending have not been changed.**

This plan extends [the completed engine plan](first-forecasting-engine-plan.md) and
[the documented engine](forecasting-engine.md). [README.md](../README.md) supplies the
official requirements; [AGENTS.md](../AGENTS.md) supplies project instructions and
supplementary judging context. The review workflow is [docs/REVIEW.md](REVIEW.md);
there is no root `REVIEW.md` in this checkout.

## Scope and research basis

Develop a competing model early, then run bounded experiments with the supplied data.
Priorities are reusable as-of features, horizon-aware gradient-boosted trees, direct
versus spot-relative targets, probabilistic outputs, chronological evaluation and
measured performance improvements. Preserve persistence as the working reference and
explicit fallback. External data, deep learning, LLM features and advanced ensembles
are optional later proposals, outside these six steps.

The existing engine plan records the team's research direction as histogram gradient
boosting and spot-relative prediction, and explicitly requests horizon-aware features
and comparison on all four official numerical metrics. The resolved Wayfinder tickets
establish leakage, contract and reproducibility constraints. No separate model-research
report was found in the current checkout; do not attribute experiments or results to
one. These recorded ideas remain hypotheses, not evidence of improved accuracy.

For a first implementation, propose scikit-learn histogram gradient boosting rather
than several competing libraries. Its documented regressor supports quantile loss and
missing numeric values; the exact compatible version must be checked before approval.
Disable automatic early stopping initially and use explicit chronological selection.
See the [official estimator documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html).
This is a proposed dependency, not a selection already installed or approved. If the
dependency cannot be approved/provisioned, retain persistence and finish independent
feature/evaluation work; do not implement a custom tree learner to bypass the gate.

## Fixed constraints for every step

- All implementation files, including new tests and model notes, stay inside
  `src/forecast_engine/` unless separately approved. This roadmap is the sole authorized
  exception for this planning task. Do not edit application code, root configuration,
  original starter files, external `tests/`, or existing shared documentation.
- Reuse `ForecastInputs`, `RunConfig`, `Predictor`, `FittedPredictor`, `ForecastResult`
  and the existing provenance records. Preserve all existing public signatures, return
  types, exports and official 13-column schema. A new predictor may be imported from
  its own model module; existing imports and baseline CLI behavior continue to work.
- Retain `models/persistence.py` behavior. Prefer new cohesive modules over refactoring
  the baseline. Select models explicitly at the composition point; no silent promotion
  of an experimental model or silent fallback on errors. Missing evidence must cause a
  clear failure or a documented, proven as-of-safe model policy.
- Fit once per run and keep learned parameters, preprocessing, feature schema and
  calibration frozen during inference. Later published observations may update inputs
  only. Hide mutable third-party estimators inside fitted implementations, detach
  caller data, and verify that prediction does not mutate learned state.
- Every origin returns all 40 quarter-hours through public `forecast(...)`. Preserve
  UTC-aware timestamps, negative prices, ordered quantiles and valid probabilities.
  Keep optional output fields blank initially; no invented drivers or explanations.
- The application imports the engine directly. Compatibility means the same
  `fit(data, config=...)` and `forecast(fitted, data, origins=...)` calls and result
  access work for both models. No backend/frontend edits are included here. Choosing
  the improved predictor in application startup is separately coordinated work, even
  when its contract is unchanged.
- Keep package import free of data loading, training, file writes and heavy optional
  ML imports. Persistence must remain usable without the optional ML dependency.
- Never publish source data, spot prices, training matrices, residual targets, fitted
  objects or verbose diagnostics containing restricted values. Store any authorized
  run outputs privately under already ignored `baseline_output/engine/`; tracked tests
  use synthetic fixtures. Record seeds, versions, configuration, source/input hashes,
  counts, timing and value-free lineage. Do not commit generated results. Follow
  README source/licence/deletion rules, including restricted spot values in actuals.
- Performance work must preserve evidence for all actual dependencies. A lineage
  digest alone cannot replace the dependency records required by the existing contract.
  Do not weaken `engine.py` checks to accommodate a faster predictor.

## Standing cross-boundary change protocol

Apply this rule to every step, including dependencies and validation tooling. Before
executing a necessary or useful change outside the boundary, stop that change, name
the affected files/components and explain its impact on public integration, dependency
setup, runtime behavior and shared resources. Send this concise, copyable notice:

```text
CROSS-BOUNDARY CHANGE NOTICE
Proposed change and affected files/components: ...
Reason and expected benefit: ...
Application/team impact: ...
Compatibility risks: ...
Recommended coordination or migration steps: ...
Can engine work proceed without this change? ...
Approval requested: ...
```

Wait for the user's explicit approval before executing the proposed change. If it is
optional, continue independent engine work where practical. Do not infer permission
from roadmap approval, a review verdict or an installed library's availability.
Dependency installation or updating a shared environment requires a notice even if a
proposed dependency manifest would live inside the engine directory.

Foreseeable coordination: optional ML installation/version recording; any later change
to root packaging/requirements, external tests or shared guides; application model
selection; and any request for new public interfaces. All need separate approval.
Adding private engine modules and package-local tests does not require editing those
files. Runtime artifacts in existing ignored output storage are part of a separately
authorized experiment, not permission to change outside source files.

At every step completion report exactly the applicable status: **Cross-boundary
changes: None**, or a **CROSS-BOUNDARY CHANGE NOTICE** using the fields above. Also
report separately approved changes actually performed; do not label them as none.

## Chronological evaluation and promotion rules

Use the existing boundaries, inclusive at the start/publication cutoff and exclusive
at the label-delivery end:

| Run | Label start | Label end | Fitting publication cutoff |
|---|---|---|---|
| Validation | `2026-05-31T21:00:00Z` | `2026-09-06T21:00:00Z` | `2026-09-06T21:00:00Z` |
| Test | `2026-05-31T21:00:00Z` | `2026-10-04T21:00:00Z` | `2026-10-04T21:00:00Z` |

At a historical origin, select every raw feature dependency by its own
`first_usable_origin_utc <= origin`. Future-delivery spot/forecasts are eligible only
when already published. Check label delivery and publication separately for each
horizon and target. A label known at fitting time need not have been known at its
historical prediction origin; features must have been. Derived features carry all
transitive input evidence. Missing values stay missing or use a training-only learned
policy; no backward fill, retrospective interpolation or whole-dataset imputation.

Choose hyperparameters/features using a small, recorded set of expanding-window folds
inside the pre-validation training interval. Start with two assessment windows, for
example Finnish local weeks 24–30 August and 31 August–6 September, with their fitting
cutoffs at each window's start. Use explicit aware UTC equivalents and `RunConfig`
instances. Purge training examples whose delivery labels cross a fold's boundary,
including up to the full ten-hour horizon, and reject labels published after cutoff.
Calendar row grouping alone is insufficient. Earlier tuning/calibration folds use
the same rules and must precede the predictions they assess.

Keep the official 7 September–4 October validation as the final chronological
comparison for a frozen candidate. If it is inspected repeatedly to guide changes,
record that reuse and treat results as development evidence rather than an untouched
holdout. Never inspect or score test outcomes for selection. Scoring actuals stay
outside training and are supplied to unchanged `score.py` only after forecasts exist.

Report all four metrics: p50 MAE, mean p10/p90 pinball, mean high/low spike Brier and
three-class direction Brier, plus coverage and per-horizon diagnostics. Compare on
identical origins, matched actuals and row counts against a fresh persistence run.
The recorded baseline reference is MAE 66.2033, pinball 24.1776, spike Brier 0.113176,
direction Brier 0.450907 and coverage 68.29%; these are historical checks, not fresh
results. Validation contains 26,880 forecast rows; its known unlabelled tail remains
in outputs and is excluded by the scorer.

Before an experiment, record its hypothesis, small configuration budget and retention
rule. Default promotion requires improvement beyond a predeclared numerical tolerance
on at least one official metric and no material regression on the others; define any
allowed tradeoff before inspecting the result. Report raw changes and fold consistency.
There is no known best-team score, so do not invent competition points or compress
the metrics into an arbitrary official-looking score. Keep persistence if no candidate
passes. A technically complete experiment may finish with no model promoted.

## Step 1. Build reusable as-of features and an evaluation harness

**Objective and implementation:** Establish a minimal shared feature builder for
historical training examples and inference. Use one row per origin/step with explicit
horizon and delivery-calendar values, latest available imbalance/direction observations,
their ages and a small number of past-only rolling summaries. Compute windows from
eligible timestamped rows; unavailable requested lags remain missing. Record feature
order, missingness policy and exact evidence. Calendar values are known in advance.
Keep all optional supplied series out until controlled experiments justify them.

Create a private experiment adapter alongside the existing unchanged CLI: it calls
public engine APIs, exports forecasts, invokes unchanged official validator/scorer,
and records safe run configuration, hashes and metrics. It must first reproduce a
persistence validation run. Do not change the existing `run_workflow` signature or
replace its default predictor. Add a small package-local command guide.

**Expected new files:** `features/{__init__,asof,training}.py`,
`experiments/{__init__,run,README.md}`, `tests/{__init__,test_features,
test_experiment_contract}.py`, all under `src/forecast_engine/`. Paths below use that
same root. Prefer reuse of public availability/provenance/export functions.

**Verify:** Run new tests with
`.venv/bin/python -m unittest discover -s src/forecast_engine/tests -t src -v` and the
unchanged external suite with `.venv/bin/python -W error::FutureWarning -m unittest
discover -s tests -v`. Test exact availability equality, delayed labels, horizon
purging, DST, missing lags, published future deliveries and all transitive rolling
dependencies. Perturb/remove unavailable rows and confirm features/evidence do not
change; compare historical and inference feature construction for the same origin.
Authorized real-data acceptance runs must reproduce official baseline metrics and
counts without reading any test actuals.

**After this step:** A tested as-of feature path and repeatable model-neutral comparison
workflow, with persistence still the only working predictor.

**Acceptance criteria:** Historical features cannot see later publications; each label
is independently eligible. Both suites pass and the harness matches persistence on
all four official metrics. Run metadata contains no restricted values. No application,
starter, external test or public-interface change is needed.

**Anticipated cross-boundary changes:** None for these source files/tests. Generating
private outputs requires explicit authorization for the corresponding run; no ML
dependency is needed yet. A shared documentation update is optional and deferred.

## Step 2. Deliver a complete competing gradient-boosted predictor

**Objective and implementation:** Once the optional dependency is approved and usable,
add a horizon-aware pooled tree regressor with quantile-0.5 loss for direct imbalance
price prediction. Horizon is a feature; do not begin with 40 separately tuned models.
Use a fixed seed, small tree budget and disabled automatic/random early stopping.
Reuse Step 1 features for both fitting and inference.

Return a full `ForecastResult` immediately. Initially take direction/spike probabilities
from a once-fitted persistence component. Fit horizon-specific lower/upper residual
offsets from chronological out-of-fold predictions inside the training interval;
apply them around the ML median with an explicit ordered construction. Do not use
in-sample residuals or official-validation errors for these offsets. Include residual
labels, historical features, submodel fits and baseline components in fitting lineage.
This is a hybrid candidate with disclosed baseline probability components.

**Expected new files:** `models/{gradient_boosted,residual_intervals}.py`,
`tests/{test_gradient_boosted,test_model_compatibility}.py`.
Modify `experiments/run.py` and its local guide to select the candidate explicitly.
Lazy-load the ML library; existing exports and default CLI stay unchanged.

**Verify:** Test complete schema, finite predictions, ordered intervals, negative
prices, exact UTC steps, provenance, single/batch agreement and repeatability. Snapshot
learned state before/after prediction and guard fit calls. Run baseline and candidate
through identical public caller code and a synthetic contract test; no application
edits. Run the package/external suites and a real full-validation comparison through
the unchanged official tools. Confirm persistence still imports/runs without ML.

**After this step:** A working competing ML model produces all required outputs through
the existing application interface, regardless of whether it beats persistence.

**Acceptance criteria:** Correctness/leakage/compatibility checks and official structural
validation pass. All four metrics and compute costs are reported against baseline;
unimproved results are recorded honestly and do not trigger promotion. Predictions
never retrain or mutate the fitted estimator.

**Anticipated cross-boundary changes:** An ML dependency installation/version decision
requires a notice and explicit approval before execution. Starter requirements and
root packaging remain untouched unless separately approved. Application development
can continue with persistence; switching its startup selection is separate work.

## Step 3. Compare direct-price and spot-relative targets with feature ablations

**Objective and implementation:** Add a controlled target mode for
`imbalance_price - spot_price`, and reconstruct prices using the delivery spot value
available at the forecast origin. Train/evaluate direct and relative variants on
matched folds and feature sets before expanding features. For relative labels both
imbalance and spot must satisfy fitting delivery/publication eligibility. The historical
spot offset used as an inference feature must additionally have been published at that
historical origin; a fitting-time spot label is not automatically an available feature.

Specify the unavailable-spot policy before running: use the separately fitted direct
model for that row, with its evidence, or fail clearly if no complete safe forecast is
possible. Never substitute a future spot value. Compare common eligible rows and report
availability/fallback rates alongside full-output metrics to avoid selection bias.

Add a few supplied-data feature groups one at a time: published delivery load/wind/solar
forecasts and ramps, eligible neighboring-area observations, then measured production,
consumption, activated balancing volumes and cross-border flows. Derived differences
need both dependencies available; sparse aFRR is missing, not automatically zero.
Only claim forecast revisions if historical vintages actually exist; the supplied
latest-version forecasts do not establish a revision history.

**Expected new files:** `models/targets.py`, `tests/test_targets.py`; modify
`features/asof.py`, `features/training.py`, `models/gradient_boosted.py`, feature tests
and the engine-local experiment guide/configuration.

**Verify:** Test publication boundaries for future spot, missing spot, both label
dependencies, price reconstruction and row-level fallback provenance. Ablate feature
groups on chronological folds with fixed budgets and report all metrics, missingness,
availability and runtime. Perturb unpublished spot and feature rows: fitted statistics
and earlier predictions must remain unchanged. Keep restricted offsets and matrices
out of logs/artifacts intended for sharing.

**After this step:** Evidence establishes whether spot-relative prediction or any added
feature group is worth retaining; the direct candidate remains available.

**Acceptance criteria:** An explicit results matrix compares target modes and small
ablations on identical evaluation rows, with no unsupported improvement claim. The
chosen mode emits complete valid horizons with documented missing-spot behavior.
Selection follows predeclared rules rather than test-period observations.

**Anticipated cross-boundary changes:** None expected; use the existing approved ML
dependency. No spot-price endpoint or application change is proposed. Additional data
sources, documentation outside the package or dependency changes require notices.

## Step 4. Learn quantiles, direction and spike probabilities

**Objective and implementation:** Replace baseline-derived components individually,
retaining each only when tested. Fit p10/p50/p90 quantile regressors with the selected
target/features; compare them to Step 2 residual intervals. Document deterministic
quantile rearrangement if independent predictions cross, and evaluate its effect.
Do not silently repair invalid values in generic engine validation.

Fit a three-class direction model and a three-class exceptional-price model
(`high`, `low`, `neither`) using strict ±50 EUR/MWh spike labels. Derive the two spike
probabilities from the joint three-class output to preserve their sum constraint.
Select eligible direction labels separately from price/spot pairs; partial label
availability must not leak or silently remove unrelated training tasks. Align classes
explicitly. For absent/rare classes, use a documented eligible-data prior or retained
baseline component with provenance, rather than invented probability estimates.

**Expected new files:** `models/probabilistic.py`, `tests/test_probabilistic.py`;
modify `models/gradient_boosted.py`, compatibility tests and the experiment adapter.
Reuse the feature builder and existing contract; do not expand it for model heads.

**Verify:** Test strict spike boundaries, independent label eligibility, class order,
missing classes, probability sums, quantile crossing and source lineage. Fit once,
compare single/batch predictions and assert no inference state mutation. Run ablations
for each new head on chronological folds, then a frozen candidate through official
validation/scoring. Report all four metrics plus coverage by horizon.

**After this step:** The candidate can learn every required output, with baseline or
residual components retained where the learned alternative lacks evidence of value.

**Acceptance criteria:** Complete valid outputs and both suites pass. Every head has
traceable labels and availability. Retained components have measured benefit or an
explicit fallback justification; fitting all learned heads is not itself a success
claim. No probability-sum or quantile constraint is weakened.

**Anticipated cross-boundary changes:** None if the approved library supports the
required heads. Any new library, public result field or application visualization
request requires a notice and separate approval.

## Step 5. Calibrate and select a bounded final candidate

**Objective and implementation:** Evaluate whether additional uncertainty/probability
calibration improves official losses. Use chronologically held-out pre-validation
predictions or expanding out-of-fold predictions, never in-sample scores. Within each
assessment fold, calibrators must be fitted on earlier eligible predictions/outcomes
and frozen before that fold begins. Final pre-validation calibrators may use eligible
pre-validation out-of-fold evidence only.

Compare no calibration with a small, justified option for quantile offsets and a
joint probability calibration that preserves class sums. Pool horizons initially;
use horizon groups only with sufficient evidence. Coverage alone is not an objective:
widening an interval toward 80% can worsen pinball loss. Avoid broad hyperparameter
search or unsupported guarantees about future calibration.

Freeze the feature/target/head/calibration recipe after the bounded experiments and
evaluate it against persistence on the official validation interval. Record component
choices, fold scores, all four metric deltas, coverage, rare-event support and known
validation reuse. Do not automatically choose a different winner for every metric.

**Expected new files:** `models/calibration.py`, `tests/test_calibration_ml.py`;
modify candidate fitting, package-local experiment configuration and its guide.

**Verify:** Synthetic fold tests forbid calibration labels published after cutoff or
delivered across it. Verify disjoint training/calibration/assessment use, finite valid
outputs and frozen calibrators. Test that modifying held-out outcomes cannot change
an earlier fit. Compare calibrated and uncalibrated scores through official tools on
matching rows and report losses rather than coverage alone.

**After this step:** A documented candidate recipe is frozen for final verification,
or persistence remains the recommended model if experiments do not justify promotion.

**Acceptance criteria:** Calibration is retained only under the recorded selection
rule; every statistic has fitting evidence. The final comparison includes all metrics
and limitations without using test labels or implying final competition points.

**Anticipated cross-boundary changes:** None expected. Updating shared evaluation
reports or application model labels remains separately approved work.

## Step 6. Verify performance, reproducibility and application compatibility

**Objective and implementation:** Measure feature-building, fitting, prediction and
provenance costs separately. Optimize only demonstrated bottlenecks, for example
indexing publication times, reusing normalized tables or batching horizon features.
Keep the audited feature path as a reference for equivalence. Do not introduce unsafe
cross-origin caches, lose dependency evidence, or add GPU/distributed infrastructure
without a demonstrated need and separate scope approval.

Run the frozen validation recipe twice and compare identifiers, prediction values,
metrics, fitting state and stable provenance/configuration hashes within declared
tolerances. Record environment/thread settings and timing/memory observations. Refit
the frozen selected recipe once using `RunConfig.test()` and generate the full test
submission without scoring or reading test actuals. Preserve the baseline artifact
and identify which model generated every run.

Exercise the documented application caller with each fitted model, including one
origin, later origins and a batch. Model initialization remains the only selection
point; no public signature, JSON assumption or application implementation is changed
here. Provide a copyable handoff naming the model module, dependency versions, tested
engine revision, startup costs and known limitations. Do not activate it in the app.

**Expected files:** Modify only measured bottlenecks under `features/` or the candidate
model modules; add `tests/test_ml_acceptance.py` and extend package-local compatibility
tests and experiment guide. No optimization change is required if measurements show
no useful bottleneck.

**Verify:** Run both suites, real-data single/batch compatibility and repeated full
validation. Compare optimized and reference features, outputs and full evidence on
synthetic boundary cases and supplied-data samples. Run unchanged official validator
on 673 test origins × 40 = 26,920 rows; require zero errors and explain any warnings.
Check source/input integrity, no test actual access, no restricted values in tracked
files, and baseline usability without ML. Report checks unavailable on other platforms.

**After this step:** A reproducible, validated selected model or explicit baseline
fallback is ready for application integration and submission review, with measured
resource costs and a separate review handoff.

**Acceptance criteria:** The complete test grid passes official validation; repeated
validation is reproducible; performance changes preserve leakage/evidence/contract
checks; and a single public caller works with baseline and candidate. Any claimed
improvement has official chronological comparison evidence. Test accuracy remains
unknown. Final integration, commit, push and merge are not authorized by acceptance.

**Anticipated cross-boundary changes:** Application startup selection and installing
the approved dependency on the coworker's environment require coordination and explicit
approval before execution. A shared guide/report update is optional. A public-interface
change is not planned; if one appears necessary, stop it and issue the standing notice.

## Execution and review gates

This planning task creates only `docs/model-improvement-roadmap.md`. No source file,
dependency, application file, test or training run is changed/executed by drafting.

For implementation, obtain explicit authorization for one step and any cross-boundary
prerequisites. At completion, stop and provide scope, exact changed files, rationale,
branch/base/HEAD, actual commands/results, dependency environment, private output
locations and limitations, plus the required cross-boundary status. Never infer a
successful check from an earlier log or silently proceed to the next step.

Follow [the separate-chat review workflow](REVIEW.md). An APPROVE verdict covers the
identified candidate only and does not authorize further implementation, dependency
changes, committing, pushing or merging. Those actions require explicit instructions.
