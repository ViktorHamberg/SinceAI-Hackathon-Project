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

Build the intended final architecture incrementally: one shared as-of feature
pipeline; pooled LightGBM heads for P50, P10/P90, direction and exceptional-price
probabilities; common direct/spot-relative target handling; chronological calibration;
and model-derived attribution. Step 2 produces every required numerical output.
Subsequent steps improve these same components rather than replacing temporary models.
Persistence remains the reference and explicit fallback.

LightGBM is the proposed primary framework from the start, not a claim of superiority
on our data. No planned migration to Transformers, LLMs or other speculative
architectures is included. Reconsider architecture only if future measured evidence
justifies a separate proposal. Do not implement an LLM or narrative generator inside
the engine. Expert-facing conclusions and operational suggestions belong to the
application workflow if separately authorized.

The earlier engine plan records histogram boosting and spot-relative targets as team
research directions; these remain hypotheses. No separate model-research report was
found in this checkout. The revised direction supersedes this roadmap's earlier
scikit-learn-first proposal and temporary residual-interval/probability-head sequence.
The resolved Wayfinder safeguards and existing baseline evidence still apply.

LightGBM documents quantile and multiclass objectives in its
[parameter reference](https://lightgbm.readthedocs.io/en/stable/Parameters.html), and
native feature contributions through
[Booster.predict](https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.Booster.html#lightgbm.Booster.predict).
Use the native Python Booster API with ordinary constant-leaf trees initially; no
additional SHAP framework is required for the proposed native contribution path.
Verify the supported objectives, contribution shapes and additive identities against
an approved pinned version during implementation. No version is selected or installed
by this plan. If installation is not approved or available, continue independent
feature/evaluation work and retain persistence; do not build a substitute learner.

## Permanent component design

- `features/`: one historical/inference implementation with stable ordered definitions,
  availability lineage, missingness policy and market-category metadata. Feature groups
  are configurable; design coverage of supplied data early without enabling everything.
- `models/lightgbm.py` and `models/heads.py`: a concrete `LightGBMPredictor` and private
  fitted implementation using the existing protocols. Five pooled boosters initially:
  three price quantiles and two three-class classifiers. A small immutable recipe
  controls each head's feature subset, target mode and parameters; no model registry
  framework or speculative class hierarchy.
- `models/targets.py`: direct price versus imbalance-minus-spot label construction and
  reconstruction. Classifier label meanings do not change with the price target mode.
- `models/calibration.py`: optional fitted transformations, identity initially, trained
  only on eligible chronological out-of-fold evidence when enabled in Step 5.
- `explainability/`: feature/category contributions and explicit transformation records,
  linked to origin, delivery, head, class and recipe. Private records stay separate
  from the unchanged `ForecastResult`; only approved categorical identifiers enter
  the existing `top_drivers` field. Rich application access is a future proposal.
- `experiments/`: explicit, reproducible fit/predict/export/official-tool orchestration
  and an engine-local guide. Keep existing CLI defaults and signatures unchanged.

Inference order is features → selected heads → price reconstruction → enabled
calibration → documented output constraints → attribution summary. Attribution must
track this chain rather than assume raw-head contributions explain every final value.
Fit/preprocessing/calibration are frozen; attribution is read-only inference work.

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
  Keep optional fields blank until supported. Step 3 populates `top_drivers` only from
  verified model contributions; no invented drivers or explanations.
- The application imports the engine directly. Compatibility means the same
  `fit(data, config=...)` and `forecast(fitted, data, origins=...)` calls and result
  access work for both models. No backend/frontend edits are included here. Choosing
  the improved predictor in application startup is separately coordinated work, even
  when its contract is unchanged.
- Keep package import free of data loading, training, file writes and heavy optional
  LightGBM imports. Persistence must remain usable without LightGBM installed.
- Never publish source data, spot prices, training matrices, residual targets, fitted
  objects or verbose diagnostics containing restricted values. Store any authorized
  run outputs privately under already ignored `baseline_output/engine/`; tracked tests
  use synthetic fixtures. Record seeds, versions, configuration, source/input hashes,
  counts, timing and value-free lineage. Do not commit generated results. Follow
  README source/licence/deletion rules, including restricted spot values in actuals.
- Performance work must preserve evidence for all actual dependencies. A lineage
  digest alone cannot replace the dependency records required by the existing contract.
  Do not weaken `engine.py` checks to accommodate a faster predictor.

## Standing test selection rule

For all future work, select tests from the actual change and its possible effects.
Start with focused tests for changed behavior, then include regression and integration
checks for consumers that could be affected. For example, feature changes can affect
training and prediction; result assembly can affect export, official validation and
backend serialization. Do not run every engine, backend and frontend suite by default.

Broaden testing when shared contracts, dependency/environment changes, failures or
uncertain impact justify it. Explain that reason before running a broad suite. After
checks pass, repeat or expand them only for new changes, failures, unresolved risks or
an explicitly required acceptance/reproducibility check. Do not repeat expensive
full-data experiments for unrelated edits. Documentation-only changes normally need
document and diff checks, not model training or code test suites.

Earlier references to running "both suites" or all package/engine/backend tests are
subject to this rule for future execution; they are not blanket requirements at every
checkpoint. Preserve each step's substantive acceptance criteria, including required
official validation/scoring and chronological full-data comparisons. At handoff,
report the checks selected, why they cover the affected behavior, actual results and
any remaining verification gaps. Do not infer compatibility from signatures alone.

This rule also applies to independent reviewers. Include it explicitly in review
prompts. Reviewers choose their checks independently and may expand coverage for
identified risks, explaining the reason before running broader tests.

## Standing integration compatibility rule

Apply this rule to every step and substep, including intermediate checkpoints. Keep
the existing engine usable by the application backend and the current forecast export,
official validation and scoring workflows throughout incremental development. New
unfinished modules may remain unconnected; do not make existing consumers depend on
them before they are ready.

If a proposed change would temporarily break any of those integrations, inform the
user before making it and obtain explicit approval through the cross-boundary protocol
below, even if every edited file is inside the engine package. If an unexpected break
is discovered, inform the user immediately rather than waiting for the step handoff.
Name the affected consumer, failing behavior, impact on the coding partner, and the
restoration plan and checks. Continue repairs within the authorized scope; separately
approve any required work outside that scope. A planned later fix is not evidence that
the current candidate is compatible.

At each step/substep handoff explicitly report **Integration compatibility: Preserved**,
**Broken** or **Not fully verified**, covering the backend and export/validation/scoring
workflows separately where their status differs. List checks actually run and remaining
gaps; do not claim compatibility solely because public signatures are unchanged.

Flag a broken or materially unverified candidate as **Not ready to push**. Before
recommending a push, require restoration and relevant compatibility verification plus
independent review, or an explicit user-approved coordinated migration plan identifying
the partner's required actions. Never recommend pushing a known integration break
without explaining it and obtaining that coordination approval. Commit/push permission
remains separate from step or review approval.

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

Foreseeable coordination: LightGBM installation/version recording and any native
runtime prerequisite; any later change to root packaging/requirements, external tests
or shared guides; application model
selection; and any request for new public interfaces. All need separate approval.
Adding private engine modules and package-local tests does not require editing those
files. Runtime artifacts in existing ignored output storage are part of a separately
authorized experiment, not permission to change outside source files.

New explanation accessors or result/provenance fields count as public integration
changes even if their source files would lie inside the engine directory. They require
a notice and approval before implementation. Existing `top_drivers` population does
not change the CSV contract, but application display/allowlist changes are separate.

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

## Step 1. Establish permanent features and evaluation foundations

Split this milestone into three sequential, independently reviewed substeps. Authorize
and implement one substep at a time; after each, explain what now works, report actual
checks, provide a review handoff and stop for explicit authorization. Approval of 1A
does not authorize 1B or 1C. Step 1 is complete only after all three are accepted.
All paths below are relative to `src/forecast_engine/`.

### Step 1A. Define features and build as-of inference rows

**Objective and implementation:** Build the shared as-of pipeline and feature registry
for one row per origin/step. Define each feature's source dependencies, timestamp/window,
unit, missingness policy and attribution category. Categories use stable identifiers:
`renewable_production`, `consumption`, `production`, `cross_border_flows`,
`neighboring_markets`, `balancing_conditions`, `historical_prices`,
`spot_price_conditions`, `calendar_horizon`. Assign each feature to one category so
additive grouping does not double count; freeze registry order/version with the fit.

Design feature groups covering historical imbalance-price levels/behavior; published
spot; mFRR prices, activations and direction; sparse aFRR prices; consumption/production;
published load/wind/solar forecasts; measured cross-border flows, supplied FI–EE
capacities and neighboring-market observations; calendar and horizon. Start with a
manageable subset: horizon/calendar, available imbalance/direction lags and ages,
past-only price summaries and published delivery spot where available. Other groups
are optional configurations tested later, not mandatory inputs for an early predictor.

Published future-delivery inputs are allowed; rolling measured features use eligible
observations in their declared past windows. Missing lag values remain missing, sparse
aFRR is not assumed zero, and derived signals need evidence for all dependencies.
Build feature rows and lineage for supplied origins without constructing training
labels or running experiments in this substep. Step 1B will reuse this same builder.

**Expected new files (5):** `features/{__init__,registry,asof}.py` and
`tests/{__init__,test_features}.py`. No training-example or experiment modules yet.

**Verify:** Run the package-local feature tests and unchanged external suite. Check
registry definitions/categories/units, deterministic feature ordering, full 40-step
feature rows, UTC/DST behavior, missing lags, publication equality, published future
inputs and complete transitive evidence. Perturb/remove unavailable rows and confirm
earlier features and lineage are unchanged. No full-data scoring run is required yet.

**After this substep / deliverables:** Feature definitions, category metadata and a
tested as-of builder returning ordered feature rows with value-free dependency
evidence. No training examples, fitted model or experiment harness yet.

**Acceptance criteria:** Feature availability, ordering and evidence checks pass;
unpublished values cannot affect earlier rows. Both suites pass, with no restricted
values in tracked fixtures/diagnostics and no changes to existing public interfaces.

**Anticipated cross-boundary changes:** None. All new files stay inside the engine;
no dependency installation or application work is needed.

### Step 1B. Construct training examples and enforce label safeguards

**Objective and implementation:** Reuse the accepted 1A builder for historical
origin/step examples. Add independent eligibility masks for price, direction and paired
imbalance/spot spike labels. Do not intersect all masks and silently discard usable
labels for other heads. Enforce delivery intervals and publication cutoffs separately
for each label and horizon; carry both feature and label evidence.

Construct the pre-validation expanding-window folds described above and purge labels
crossing each fitting boundary. Keep feature selection at each historical origin,
separate from label availability at fitting time. No model training, calibration or
scoring harness is included in this substep.

**Expected new files (1):** `features/training.py`. Extend `tests/test_features.py`
with historical-example and fold tests; modify existing feature modules only if
needed for reuse, preserving the accepted as-of behavior.

**Verify:** Run both suites. Check delayed and partially available labels, exact cutoff
boundaries, independent target masks, ten-hour horizon purging and missing paired spot
labels. Compare historical features against direct 1A inference construction for the
same origins. Changing future or otherwise ineligible labels must leave earlier
eligible examples and fitting evidence unchanged. No full-data scoring run yet.

**After this substep / deliverables:** Tested historical training examples, per-head
eligible labels and chronological fold construction using the permanent feature path.
No predictor has been trained.

**Acceptance criteria:** Every retained example has eligible feature/label lineage;
historical/inference feature parity holds; fold boundaries exclude crossing or delayed
labels. Both suites pass and independently usable labels are not silently lost.

**Anticipated cross-boundary changes:** None. Existing `RunConfig` and provenance
contracts suffice; any discovered need to change them triggers the standing notice.

### Step 1C. Build the experiment harness and reproduce persistence

**Objective and implementation:** Build the private experiment adapter using public
APIs, existing provenance utilities, export and unchanged official tools. Keep original
`run_workflow` and CLI unchanged. Reuse 1B fold definitions. For pre-validation folds,
construct scoring-only actuals from supplied eligible target series separately from
features, using the official definitions, and retain them privately. Actuals for a
fold are never inputs or training labels for that fold's fit.

Record configuration, source/input hashes, safe lineage summaries, counts, timing and
all four metrics in a fresh ignored run directory. Document the engine-local command
and failure diagnostics. Reproduce full persistence validation before accepting the
foundation; no LightGBM model or dependency is required.

**Expected new files (4):** `experiments/{__init__,run}.py`,
`experiments/README.md` and `tests/test_experiment_contract.py`. Modify 1A/1B modules
only for directly required integration fixes, with affected checks rerun.

**Verify:** Run both suites and synthetic orchestration tests covering scoring-actual
separation, safe failures, fresh output directories and official-tool invocation.
Run full persistence validation through the unchanged validator/scorer. Compare all
four metrics and row counts with the recorded baseline, retaining unlabelled tail
forecasts. Check metadata and generated diagnostic outputs for restricted values.

**After this substep / deliverables:** A reproducible experiment command/guide and
safe baseline acceptance evidence in ignored storage. Step 1's feature, training-example
and evaluation foundation is complete; persistence is still the only fitted predictor.

**Acceptance criteria:** Both suites pass, persistence reproduces all four recorded
metrics and scoring counts, and official structural validation passes. No test actuals
are accessed and scoring data stays outside prediction inputs. The handoff identifies
actual checks, engine revision, output locations and limitations.

**Anticipated cross-boundary changes:** None for source files. Authorized runs use
existing ignored storage. LightGBM provisioning remains a separate Step 2 prerequisite
requiring a notice and explicit approval; application work can continue independently.

### Step 1 verification commands

Run these from the repository root at each substep, reporting actual results. Full-data
persistence acceptance is required in 1C, not repeated for each earlier checkpoint.

```bash
.venv/bin/python -m unittest discover -s src/forecast_engine/tests -t src -v
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v
```

The total planned new files remain approximately ten: five in 1A, one in 1B and four
in 1C. Existing internal test files grow with their relevant checks. Each substep ends
with its own review handoff and approval pause; no implementation is authorized here.

## Step 2. Deliver the complete LightGBM forecasting system

Split this milestone into three sequential, independently reviewed substeps. Implement
only the explicitly authorized substep, then explain what works, report actual checks,
provide its review handoff and stop. Approval of 2A does not authorize 2B or 2C, and
dependency changes still require the standing cross-boundary notice and explicit
approval. Step 2 is complete only when all three are accepted. All engine paths below
are relative to `src/forecast_engine/`; shared dependency paths are repository-relative.

The same permanent architecture spans all three checkpoints: shared Step 1 features,
native LightGBM heads, common target handling and the unchanged forecasting contract.
No temporary predictor implementation or planned architecture replacement is introduced.

### Step 2A. Provision LightGBM and implement target handling

**Objective and implementation:** Present a concrete cross-boundary notice proposing
the LightGBM version, optional engine `ml` extra, combined lock update and any native
runtime prerequisites. Explain the macOS/Windows setup and compatibility implications;
wait for explicit approval before those dependency changes or installations. Follow
the shared uv workflow; do not separately install a second backend dependency copy.
Keep persistence usable when the optional dependency is absent.

Implement `models/targets.py` for both direct imbalance-price labels and
`imbalance_price - spot_price`, reusing Step 1B eligibility and evidence. Relative
labels require paired fitting-eligible price/spot rows. Reconstruction requires the
exact delivery spot published by the historical/inference origin; a fitting-time spot
label must not be reused as an origin-time feature. Define the reconstruction and
missing-spot decision now; the actual fitted direct-price backup is integrated in 2C.
Never invent a replacement spot price or silently turn a relative prediction into a
direct price. Keep target mode and transformation identity explicit for later attribution.

**Expected new engine files (2):** `models/targets.py`, `tests/test_targets.py`.
Separately approved modifications are expected in root `pyproject.toml`,
`requirements-dev.in`, generated `requirements-dev.lock`, and the engine-local
`experiments/README.md` for setup instructions. Update shared setup documentation only
if included in the approval. Preserve the original starter `requirements.txt`.

**Verify:** Test independent direct/relative label eligibility, missing pairs, negative
prices, reconstruction, exact publication equality, unavailable future spot and source
lineage. Confirm native LightGBM import in the approved environment and the installed
versions/lock match; no head fitting or training experiment is needed in this substep.
Run package-local, unchanged engine and existing backend tests after dependency sync.
Verify persistence import/use without LightGBM and report Windows/native-runtime checks
that could not be performed rather than claiming both platforms work.

**After this substep / deliverables:** Approved, reproducible dependency setup and tested
permanent target utilities. No LightGBM predictor or learned heads are implemented yet.

**Acceptance criteria:** Target transformations and evidence are correct, dependency
changes are authorized and recorded, and existing engine/backend/official-tool
integration remains verified through relevant tests. Missing dependency/native support
fails clearly. Report outstanding platform checks and whether they block adoption.

**Anticipated cross-boundary changes:** Required for the optional extra, combined input/
lock, environment installation and possible native runtime. No application source or
public interface change is proposed; the partner can continue with persistence. A
roadmap or substep approval alone is not approval of an unspecified dependency change.

### Step 2B. Implement the complete direct-price predictor

**Objective and implementation:** Implement `LightGBMPredictor.fit(data, config=...)`
and a frozen fitted implementation returning `ForecastResult` through unchanged
`forecast(...)`. Use the native Booster API, small fixed-seed CPU configurations and
fixed training iterations. No random validation split, automatic tuning, GPU requirement
or early-stopping dependency. Later early stopping needs explicit earlier chronological
assessment data. Start with direct price using the accepted 2A target utilities.

Train five horizon-aware pooled boosters sharing Step 1 infrastructure: quantile
objectives at 0.10, 0.50 and 0.90; one multiclass direction head with fixed class mapping
up/down/none; and one multiclass spike head with high/low/neither. Spikes use strictly
above spot + 50 or below spot − 50 EUR/MWh. Multiclass spike outputs supply the two
reported probabilities, ensuring their sum cannot exceed one. Per-head eligibility,
class mapping and evidence are explicit. Quantile-0.5 targets the median-price metric.

Relative label/reconstruction utilities already exist from 2A, but relative predictor
inference remains disabled until the complete safe backup path is accepted in 2C.

Keep P50 unchanged when resolving crossing quantiles initially: lower is the minimum
of raw reconstructed P10 and P50, upper the maximum of raw reconstructed P90 and P50.
Record this policy, raw outputs and its effect in private evaluation; do not sort all
three heads and inadvertently replace the median's identity. Calibration is identity
until Step 5. This explicit model policy does not weaken generic engine validation.

All heads are learned from the start on adequate data. For insufficient eligible
labels or absent classes, use an explicitly configured persistence component with
complete fitting/inference evidence, or fail clearly. Missing dependency or unexpected
training failures must not silently fall back. Do not use persistence as the planned
normal implementation of probability/uncertainty heads. Optional text stays blank
until Step 3. Retain head/target/recipe and transformation identity privately for
attribution; no new public result field is introduced.

**Expected new engine files (4):** `models/{lightgbm,heads}.py`,
`tests/{test_lightgbm,test_model_compatibility}.py`. Extend `tests/test_targets.py`
only for directly needed integration checks. Existing exports, baseline implementation,
CLI defaults and public signatures remain unchanged. The experiment API already
accepts a predictor; command-line model selection is handled in 2C.

**Verify:** Unit tests cover every head, strict spike boundaries, partial/absent labels,
class order, valid sums, negative prices, explicit fallback/error behavior and crossing
quantiles. Test single/batch equality, repeated prediction, detached caller data,
fit-call guards and model-state fingerprints before/after prediction. Run package-local,
unchanged engine and backend suites. Exercise the complete direct-price result through
export and the real unchanged validator/scorer on synthetic inputs. Baseline and ML
must use identical public caller code; persistence still works without LightGBM.
Full supplied-data validation and metric comparison are required in 2C.

**After this substep / deliverables:** A complete direct-price LightGBM forecast with
all required numerical outputs for 40 steps, safe fitting/inference lineage and
application-contract compatibility evidence. No application activation is included.

**Acceptance criteria:** All five learned heads execute on adequate synthetic data;
fallbacks are limited to declared evidence gaps and reported. The direct-price forecast
passes official structural validation/scoring integration and existing compatibility
checks, without refitting during prediction. No accuracy improvement is claimed.

**Anticipated cross-boundary changes:** None expected beyond the accepted 2A dependency
setup. New dependency/version or interface requirements trigger another notice.
Application predictor selection remains separate coordinated work.

### Step 2C. Integrate relative inference and run full-data acceptance

**Objective and implementation:** Enable the spot-relative mode in the same predictor,
using 2A transformations and 2B heads. For rows without delivery spot available at the
origin, use a separately fitted direct-price backup within the same architecture.
Fit required components once; preserve both models' frozen state. Track which price
path supplied each row and retain complete fitting/inference evidence for it. Do not
introduce unpublished spot, mix incompatible price units or alter classifier label
meanings with the price target mode. Keep the P50-preserving quantile constraint policy.

Add explicit candidate/recipe selection to the package-local experiment command and
guide while retaining persistence as default. Record target mode, per-head settings,
seeds, fallback policy and component identity with safe experiment configuration so
the selected run is reproducible. Keep richer transformation metadata private for
Step 3 attribution; do not add public result fields or populate invented top drivers.

Run full supplied-data chronological validation through unchanged official tools,
comparing all four metrics, coverage, counts and initialization/inference costs against
persistence on identical origins and outcomes. Exercise both target modes; report
spot availability and backup usage. This establishes a complete measured candidate,
not the broader target/feature tuning reserved for Step 4. Do not access test actuals
or generate the final test submission reserved for Step 6.

**Expected new engine files:** None planned. Modify `models/{lightgbm,heads,targets}.py`
as required, extend their tests and `tests/test_model_compatibility.py`, and update
`experiments/run.py`, `experiments/README.md` and `tests/test_experiment_contract.py`.
Full-data artifacts remain in fresh ignored run directories.

**Verify:** Test missing/unpublished spot, mixed primary/backup rows, both components'
lineage, negative-price reconstruction and frozen state. Re-run package-local, unchanged
engine and backend suites after final changes. Check experiment recipe recording,
single/batch agreement, baseline behavior without LightGBM, and both complete target
modes through real-data validation/scoring. Report exact metrics, matched counts,
fallback usage and environment/platform limits. Structural validation alone does not
establish leakage safety or prediction quality.

**After this substep / deliverables:** The full Step 2 system: complete direct/relative
LightGBM forecasting, safe backup behavior, reproducible experiment selection and
official full-data comparison with the baseline. Step 3 explainability remains separate.

**Acceptance criteria:** On adequate supplied data all five learned heads execute;
any fallback is explicitly justified and traced. Both target modes produce complete
valid horizons, and all four metrics/costs are reported honestly. Existing integration
checks pass. No improvement is assumed, and model promotion is not required for
technical completion. No application change or automatic activation occurs.

**Anticipated cross-boundary changes:** None required within the existing contract.
Application model/recipe selection and any additional dependency/native-runtime change
need a notice and explicit approval in their respective workflow. The application can
continue with persistence while these experiments are reviewed.

The planned new engine-file total remains six: two in 2A, four in 2B and none in 2C.
Existing files grow with integration and relevant tests. Each substep must report the
standing cross-boundary and integration compatibility statuses and stop for review
and explicit authorization before the next substep.

## Step 3. Add model contributions and meaningful top_drivers

**Objective and implementation:** Implement native `pred_contrib=True` attribution
for the supported ordinary-tree heads, using the exact features, model iteration and
class mapping used for prediction. This is prediction-specific model contribution,
not global split/gain importance, a description of the algorithm, or physical causation.
Verify native output layouts and additive identities for each approved objective;
unsupported cases must report unavailable attribution, never guessed drivers.

Private immutable records identify origin/delivery/step, head and class, model/recipe,
target mode, registry version, explanation scope, reference/base output, signed
feature/category contributions and units. Include the output being explained and a
transformation ledger for reconstruction, calibration, constraint handling and fallback.
Keep feature values and numeric references/contributions private because they can
reveal restricted market information. Do not add records to `ForecastResult`, DataFrame
attrs, provenance schemas or a new public explanation method. An engine-private helper
can serve internal tests/experiments; an application interface requires a separate
cross-boundary proposal.

For a direct uncalibrated P50, test that base plus feature contributions reconstructs
its raw prediction in EUR/MWh. For a relative P50, contributions explain the spread
component; record the private spot reconstruction offset separately and associate it
with `spot_price_conditions`. It is not a learned SHAP effect. Only claim a final-price
decomposition when that offset and every other transformation are explicitly accounted
for. Never serialize the offset or a reference/contribution that reveals spot values.

Group feature contributions by signed sum using the registry, preserving additivity;
retain individual contributions privately so within-category cancellation is visible.
Populate `top_drivers` with at most three nonzero categories ranked by absolute grouped
contribution, stable identifier order for ties, semicolon-separated and without numeric
values. It explains P50 only. Document this definition in the engine-local guide and
application handoff. Relative reconstruction can contribute its category to this
ranking, explicitly distinguished privately from learned effects. Zero contributions
or unsupported complete P50 explanations yield blank optional text; persistence
fallback rows do not receive LightGBM drivers.

Implement target-specific internal records for direction and spike classes where
native outputs are verified. Their additive contributions explain raw class margins;
record softmax/calibration separately. Do not call them probability-point changes or
reuse P50 categories as explanations of those heads. The class, baseline and unit
must always be explicit. Quantile attribution has the same transformation caveats.
If calibration/blending later prevents a faithful final-output attribution, keep the
raw-head scope explicit privately and leave affected final-P50 `top_drivers` blank
until a valid decomposition is available.

Allow internal comparison of contributions for the same delivery at consecutive
origins under the same frozen model/registry, using genuinely generated forecasts.
This can later support explanations of revisions, but is not evidence of revised
upstream weather/day-ahead forecasts: the supplied latest-vintage data cannot provide
that history. No revision endpoint or narrative generator is included.

**Expected new files:** `explainability/{__init__,records,contributions,drivers}.py`,
`tests/test_explainability.py`; modify candidate result assembly and local experiment
guide. Reuse registry metadata; no public contract or application file changes.

**Verify:** Test additive reconstruction with tolerances for price and each class raw
margin, multiclass shapes/class order, units/signs, grouped sums/cancellation, stable
ranking, zero effects and prediction-specific variation on synthetic models. Test
relative reconstruction, fallback, quantile constraints and unsupported transformations.
Perturb unavailable inputs and confirm predictions/drivers are unchanged. Privacy tests
must prohibit raw spot values, offset values, feature values and numeric attributions
in `top_drivers` or safe logs. Check output schema/export and official validator with
populated optional text. Fingerprint fitted state through attribution calls.

**After this step / deliverables:** Verified internal attribution records for supported
heads and safe P50 category identifiers in the existing optional CSV column, with
scope/units/transformation documentation and an application coordination handoff.

**Acceptance criteria:** Explanations reconstruct exactly their stated target/scale
within tolerance and distinguish final values from components. `top_drivers` is
model-derived, deterministic and free of restricted values; unavailable/fallback
explanations remain blank. No LLM, public explanation interface or causal claim.

**Anticipated cross-boundary changes:** The current backend `schemas.py` approves only
`last_imbalance_price`; new category names will be filtered to null until the application
workflow approves its allowlist/docs/tests update. Propose that update rather than
editing it. Existing predictor injection in `prepare_forecast` supports the contract.
A richer explanation accessor/record schema or response endpoint needs a separate
notice covering privacy, target/scale semantics, versioning and migration. Internal
attribution and CSV development can proceed without that public interface.

## Step 4. Improve the same architecture through controlled experiments

**Objective and implementation:** Use a bounded hypothesis table covering direct versus
relative targets, optional feature groups, regularization/tree/iteration settings,
horizon interactions and head-specific feature sets. Start with no more than six
recorded candidate recipes; expanding the budget requires justification and approval
as additional experiment scope. Avoid a Cartesian search. Choose configurations on
pre-validation expanding folds and report all four losses, coverage, availability,
fallback rates, per-horizon results and compute/attribution costs.

Test feature groups in small ablations: renewable/load forecasts and delivery ramps;
balancing observations; production/consumption; then cross-border and neighboring
markets. Both sides of every derived difference must be available. No undocumented
vintages, future filling or automatic zero interpretation of sparse aFRR. Compare target
modes both on shared eligible rows and complete horizons to expose missing-spot bias.
Consider horizon groups only after pooled diagnostics show a repeatable weakness.

Small same-family ensembles or regime-specific heads are optional follow-ups only
when earlier results justify their extra cost. A regime selector itself must be
as-of-safe. Preserve head/target identifiers and explain transformation/blend effects;
do not assume a mixed model has a single native contribution decomposition. Do not
speculatively build another architecture or require these options for completion.

**Expected files:** Modify `models/{lightgbm,heads,targets}.py`, `features/` definitions,
package-local experiment recipes/guide and associated internal tests. Extend private
attribution handling for retained changes only. No new framework is expected.

**Verify:** Run controlled fold comparisons with fixed seeds, data and matched score
rows. Test label purging, per-head subsets, missingness, fallback and hypothesis-specific
invariance. Run focused tests and affected consumer regressions after retained code
changes, plus attribution identities for the selected mode. Apply the predeclared
promotion rule; report discarded ideas as well as retained improvements in safe
experiment summaries.

**After this step / deliverables:** A measured configuration/feature comparison and
selected candidate within the permanent LightGBM architecture, or evidence for retaining
the initial recipe/persistence. No unsupported superiority claim.

**Acceptance criteria:** Every retained change has reproducible chronological evidence
and valid provenance/outputs. All four metrics/tradeoffs are visible. Test outcomes
are not accessed; forecast explanations retain correct head and transformation scope.

**Anticipated cross-boundary changes:** None required with approved dependencies.
External data, another library, broader experiments or public fields require a notice
and separate approval. Application code remains untouched.

## Step 5. Calibrate and freeze the final complete configuration

**Objective and implementation:** Add chronological quantile and probability calibration
to the same fitted system. Compare identity against pooled P10/P90 residual-quantile
offsets from earlier out-of-fold predictions, and scalar temperature calibration on
each classifier's multiclass margins. Fit temperatures using eligible earlier labels;
assess retention using official Brier losses. Maintain nonnegative normalized class
probabilities and the spike sum constraint. Start with P50 unchanged so its contribution
identity stays clear; any median correction is a separately evaluated configuration.

Within each assessment fold, all calibrator inputs and outcomes must come from earlier
eligible out-of-fold predictions, and calibrators freeze before the fold begins.
Never use in-sample errors, random splits or official validation outcomes to calibrate
the candidate evaluated on that interval. Final validation calibrators use only
pre-validation evidence. With inadequate evidence, use identity rather than invented
corrections. Coverage near 80% is diagnostic, not a replacement for pinball loss.

Track each quantile adjustment, constraint and temperature in private attribution
records with the correct scope/units. Raw classifier-margin contributions do not
become calibrated probability contributions by relabelling them. If a retained blend
or nonlinear transform cannot support a faithful final-P50 decomposition, clear its
`top_drivers` and retain explicitly scoped internal component records. Calibration
must not leave stale or misleading drivers on final outputs.

Freeze the complete recipe—features, target modes, per-head parameters, fallbacks,
calibrators and explanation policy—then run official chronological validation against
persistence. Record validation reuse, all metric deltas, coverage and rare-event
support. For final test refitting, rebuild training-only chronological calibration
folds within the larger permitted training interval using the frozen procedure; do
not carry validation leakage into earlier assessment predictions.

**Expected new files:** `models/calibration.py`, `tests/test_calibration_ml.py`;
modify candidate fitting, internal attribution tests/records and experiment guide.

**Verify:** Test disjoint chronological training/calibration/assessment use, publication
cutoffs and horizon purging, deterministic temperatures/offsets and identity behavior.
Change held-out/future outcomes and confirm earlier fits cannot change. Compare
calibrated/uncalibrated pinball and both Brier criteria on identical rows, plus MAE
and coverage. Verify sums, ordering, frozen state and attribution scope after transforms;
run relevant calibration, prediction, attribution and integration checks, plus frozen
full official validation.

**After this step / deliverables:** A frozen complete recipe, justified calibration
choices and full validation comparison, with updated explanation semantics. Persistence
remains the recommendation if no candidate meets the promotion rule.

**Acceptance criteria:** Retain only measured calibration benefits under predeclared
tradeoff rules; no coverage-only optimization. Every calibrator has eligible source
and model provenance. Final explanation claims match the actual transformed outputs;
no test-label selection or competition-points claims.

**Anticipated cross-boundary changes:** None for internal calibration. An application
change to display new explanation scope, calibration labels or model identity must
be proposed and approved in that workflow; no public explanation field is added here.

## Step 6. Verify, measure and hand off the selected engine

**Objective and implementation:** Run full contract, leakage, provenance, reproducibility
and compatibility acceptance. Measure feature generation, each head's fitting,
calibration, inference, native attribution and lineage memory/time separately. Optimize
only measured bottlenecks, preserving an audited reference path and complete evidence.
Do not weaken availability checks, remove lineage or add distributed/GPU infrastructure
without demonstrated need and separately approved scope/dependencies.

Repeat frozen full validation twice. Compare keys, numerical outputs, `top_drivers`,
all official metrics, fitted state, configuration and stable provenance hashes within
predeclared tolerances. Record LightGBM/native runtime versions, seeds, thread settings
and operating system; do not promise byte identity across platforms without testing.
Refit the frozen recipe once with `RunConfig.test()` and generate 673 origins × 40 =
26,920 test rows. Validate with unchanged tools; never load, hash or score test actuals.
Retain and identify baseline artifacts and any declared fallback usage.

Exercise one public caller with persistence and LightGBM for a single origin, later
origins and batches, including the application's first validation origin. The existing
backend accepts `predictor` and an explicit `model_id` at preparation; verify that
selection pattern in engine-side compatibility tests without editing the application.
Fit once and preserve learned state across requests/predictions. Record initialization
and attribution cost for the app's startup/cache design. If cost requires persistence
or artifact-loading changes, propose the adapter rather than altering startup here.

Prepare a copyable technical handoff in the engine-local guide: exact predictor import
and recipe selection, dependency setup/licences, tested source revision/hash, startup
and inference cost, output/fallback behavior, `top_drivers` vocabulary/P50 scope/privacy,
and remaining limits. Describe any proposed richer explanation interface separately
with example synthetic records, units, transformation scope and approval status.
No application activation, narrative generator or endpoint is part of this step.

**Expected files:** Add `tests/test_ml_acceptance.py`; modify only measured bottlenecks
under existing feature/model/explainability modules and their internal tests. Complete
`experiments/README.md` and compatibility tests. No optimization edit is required when
measurements show no worthwhile bottleneck; generated evidence stays ignored.

**Verify:** Run final engine acceptance and affected regression tests, required repeated
official validation, public caller compatibility, model-state fingerprints and safe
logging checks. Compare optimized/reference features, predictions, category rankings
and full lineage on boundaries and supplied samples.
Require zero test-validator errors and explain warnings. Inspect changed files for
restricted values; check starter/input integrity, baseline import without LightGBM,
and no test actual access. Report missing Windows/macOS/native-runtime checks honestly.

**After this step / deliverables:** A complete structurally validated test forecast,
reproducibility/performance evidence and a technical application handoff for the selected
model or explicit persistence fallback, ready for independent review.

**Acceptance criteria:** Correct full grid, ordered quantiles, valid probabilities,
chronological evidence and unchanged public integration pass verification. Attributions
remain faithful/private and top-driver identifiers reproducible. Any improvement claim
is supported by official chronological metrics; test accuracy remains unknown.
No implicit authorization to activate, commit, push or merge follows acceptance.

**Anticipated cross-boundary changes:** Coordinate application predictor/model-id
selection, driver allowlist display and LightGBM/native dependency setup before executing
those changes. Propose any optional explanation interface separately. Shared guides,
packaging, external tests or runtime adapters require the standing notice. Engine
acceptance can proceed through the existing contract without rich explanation access.

## Execution and review gates

This planning task modifies only `docs/model-improvement-roadmap.md`. No source file,
application file, dependency, test or training run is changed/executed by drafting.

For implementation, obtain explicit authorization for one step (or one Step 1/2 substep)
and any cross-boundary
prerequisites. At completion, stop and provide scope, exact changed files, rationale,
branch/base/HEAD, actual commands/results, dependency environment, private output
locations and limitations, plus the required cross-boundary and integration
compatibility statuses. Never infer a
successful check from an earlier log or silently proceed to the next step.

Follow [the separate-chat review workflow](REVIEW.md). An APPROVE verdict covers the
identified candidate only and does not authorize further implementation, dependency
changes, committing, pushing or merging. Those actions require explicit instructions.
