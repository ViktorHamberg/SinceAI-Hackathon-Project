# First forecasting engine: consolidated implementation plan

**Status: plan approved; Steps 1–5 implemented and verified. Step 6 awaits separate
explicit approval.**

This plan combines the resolved Wayfinder map and the four resolved decision-ticket
Answers supplied on 7 November 2026 with our dataset and baseline analysis. The final
Answers take precedence over the tickets' earlier proposals. The map and ticket copies
are available under `.scratch/first-forecasting-engine/`.

## Scope and relationship to the competing model

The current milestone is a reusable, leakage-safe engine that initially reproduces
baseline behaviour. Our research proposes a later competing model using histogram
gradient boosting and spot-relative prices. These are complementary milestones.

Complete a focused engine foundation first, then separately approve the competing-model
experiment behind the same interface. This plan does not select or install an ML
library, add external data, build a UI/API/database, or claim an accuracy improvement.
Keep baseline comparison proportional to the deadline; retain justified safety
corrections even when they prevent exact numerical parity.

## Fixed constraints for every step

- Preserve every original starter file, including the notebook, requirements, templates,
  validator, scorer and dataset builder. All implementation goes in new files.
- Use the existing project environment and dependencies; use standard-library `unittest`
  for focused checks. No Jupyter runtime or additional testing platform is required.
- Extract/adapt useful starter functions once, document their source, and keep notebook
  parsing/execution out of the package runtime. Importing must perform no data loading,
  fitting, printing, file writes or subprocess work.
- Separate explicit I/O and as-of rules, replaceable model fitting/inference, in-memory
  orchestration/export, and command-line/evaluation adapters. Use classes for useful
  state/lifecycle boundaries and functions for operations; no speculative hierarchy.
- Scoring actuals are never prediction inputs. Keep private/generated artifacts under
  `baseline_output/engine/`, already ignored by git; log no restricted prices or secrets.
- Fit once per run and preserve its fitted state during inference. Later observations
  may update inference lags only when published by the relevant origin.
- Keep the public fit/predict/result interface independent of the baseline algorithm;
  a future gradient-boosted tree predictor must fit behind the same application contract.
- Prioritize leakage safety, official validation, the complete test CSV, and
  reproducibility. Notebook parity remains a diagnostic target; justified safety or
  correctness differences must be explained rather than allowed to delay a working engine.
- Keep packaging simple and document a verified editable installation command. Do not
  alter the original starter requirements or require Jupyter for engine use.

The agreed UTC boundaries are inclusive at the start and availability cutoff, and
exclusive at the label-delivery end:

| Run | Label delivery start | Label delivery end | Fitting availability cutoff |
|---|---|---|---|
| Validation | `2026-05-31T21:00:00Z` | `2026-09-06T21:00:00Z` | `2026-09-06T21:00:00Z` |
| Test | `2026-05-31T21:00:00Z` | `2026-10-04T21:00:00Z` | `2026-10-04T21:00:00Z` |

A label must satisfy both its delivery interval and publication by the fitting cutoff.
Each historical calibration pair reconstructs inputs at that pair's own origin, while
its later outcome must be eligible by fitting time. Check each step separately; a
qualifying historical origin does not make its entire horizon eligible.

## Step 1. Establish the importable package and contract

**Implement:** The `forecast_engine` package, explicit run configuration and forecast/
provenance types. Establish a public shape that separates fitting from prediction,
supports one origin and batches, and exposes a forecast DataFrame with separately
accessible provenance. Optional fields have stable nullable types from the outset.

**Expected new files:** `pyproject.toml`, `src/forecast_engine/__init__.py`,
`config.py`, `contracts.py`, and `tests/test_contracts.py`, `tests/test_import.py`.
Paths without a prefix in these steps are relative to `src/forecast_engine/`.

**Verify:** Import from a separate process and working directory without challenge
data. Check no import-time I/O/computation, stdout or files. Use synthetic tables to
check the 13 ordered columns, UTC timestamps, integer steps and nullable optional
types. Define the package setup command without altering starter requirements.

**After this step:** A directly importable foundation and documented caller contract;
no actual forecast fitting or prediction yet.

### Step 1 result and verified setup

Implemented `pyproject.toml`, `src/forecast_engine/{__init__,config,contracts}.py`,
and the two focused test files listed above. No implementation of Step 2 or later is
included. All original starter files, including requirements.txt, remain unchanged.

With Python 3.11+ and the build tools (`setuptools>=64`, `wheel`) available in the
active environment, run from the repository root:

```bash
python -m pip install --no-build-isolation -e .
python -m unittest discover -s tests -v
```

The installation command checks/installs the package's pandas/NumPy dependencies;
their ranges match the starter requirements. Full starter dependency provisioning
continues to use the unchanged `requirements.txt`. No packaging framework or test
dependency was added. `--no-build-isolation` uses the existing build tools instead of
trying to download them into a temporary build environment.

Verification used `.venv/bin/python` (Python 3.12.14, pandas 2.2.3, NumPy 2.3.5,
setuptools 84.2.1, wheel 0.48.0). The shell's default `python3` is 3.6 and is unsuitable.
No project environment existed; the local ignored `.venv` was created with access to
the existing Codex Python runtime's installed packages. The editable install succeeded
both offline with `--no-index --no-deps --no-build-isolation` and with the documented
command above. A fresh `pip install -r requirements.txt` could not reach the package
index; full fresh-environment provisioning was not verified. In particular, pyarrow is
not installed in this verification environment; Step 1 does not load Parquet or data.

All **9 unittest checks passed**. These cover official header/order, timestamp/integer/
numeric/nullable dtypes, optional values missing then populated, invalid schemas rejected
without mutation, separate provenance, fitting boundaries and immutable configuration,
and interchangeable model-neutral fit/predict call shapes using synthetic test doubles.
The installed package also imports in a separate process from an empty unrelated
directory with non-code reads, file writes, subprocess/network work blocked, no pandas
or NumPy import, no stdout/stderr, and no created files.

The public API consists of:

- `RunConfig.validation()` / `.test()` for explicit UTC fitting boundaries.
- `ForecastInputs(series, spot=None)` for caller-owned in-memory source tables.
- The structural `Predictor.fit(data, *, config) -> FittedPredictor` interface.
- `FittedPredictor.predict(data, *, origins=[...]) -> ForecastResult`, using one or
  multiple origins without changing the caller's interface. Fitted implementations
  expose `provenance` and must not refit during prediction.
- `ForecastResult.forecasts` (the official-schema DataFrame) and `.provenance`, with
  `FitProvenance`, `OriginProvenance`, and `ForecastProvenance` records.
- `FORECAST_COLUMNS`, fixed horizon/resolution constants, `empty_forecast_frame()`, and
  `check_forecast_schema()` for structural schema use. Optional fields already support
  nullable UTC timestamps and text without signature/schema changes.

The Protocols declare interfaces; they are not working model implementations. Input
selection, provenance construction/availability enforcement, full forecast value and
completeness checks, export, CLI execution, and official validator/scorer runs remain
in their approved later steps. The schema helper is not a substitute for those checks.
Frozen record envelopes do not make caller-owned DataFrames or mapping contents deeply
immutable; concrete fitted-state immutability will be enforced in the fitting step.

## Step 2. Add explicit data loading and historical availability

**Implement:** Input/spot loading adapters, UTC handling, origin-specific selection,
fitting-label eligibility, and dependency/provenance records. Future-delivery inputs
are allowed when already published. Do not load scoring actuals through these adapters.

**Expected new files:** `data.py`, `availability.py`, `provenance.py`,
`tests/test_data.py`, and `tests/test_availability.py`.

**Verify:** Synthetic exact-boundary cases: availability equal to origin/cutoff is
eligible, delivery equal to the label upper bound is not. Test published future
deliveries, delayed labels, missing evidence and derived dependencies. Changing or
removing unavailable rows must leave the selected eligible evidence unchanged. Keep
missing nonessential inputs missing; no future-dependent interpolation/backfill.

**After this step:** Reusable historical input selection and fitting evidence with
explicit, testable availability guarantees.

### Step 2 result and verification

Implemented `data.py`, `availability.py`, and `provenance.py`. Extended the existing
public fitting/origin provenance records with backward-compatible dependency tuples;
the model-independent fit/predict interfaces are unchanged. Added synthetic loading,
availability, and provenance tests and extended the isolated import check to cover all
new modules. No starter file, requirements, model, forecast, export, or CLI was changed.

Public interfaces:

- `load_input_data(path)` and `load_spot_prices(path)` explicitly load CSV/Parquet;
  `load_inputs(inputs_path, spot_path=...)` returns the existing `ForecastInputs` type.
  Omitted spot data stays `None`; an explicitly supplied missing path raises. The
  seven-column source schema is checked, scoring actuals are rejected, timezone-aware
  timestamps are converted to UTC, duplicates/malformed/nonfinite values fail, and
  genuinely missing values remain missing. `normalize_long(frame)` applies the same
  rules to caller-provided in-memory tables without mutating them.
- `select_available(rows, origin_utc, required_series=...)` retains publication
  `<= origin` and metadata, including already-published future-delivery rows.
  `select_fitting_labels(rows, config, required_series=...)` additionally enforces
  `[label_start, label_end)`. These return copied long tables. Required series need
  finite eligible evidence or raise `MissingEvidenceError`. Optional missing rows are
  not invented. `rows_available_at(rows, origin_utc)` provides the reference's wide
  pivot after filtering, without filling gaps.
- `evidence_from_rows(rows, name=..., used_at_utc=...)` records the rows actually used,
  with no values. `SourceDependency` retains each row's series/delivery/publication
  and historical use time. `derive_evidence(name, ..., used_at_utc=...)` retains every
  transitive source use and inherits the latest publication; it rejects missing or
  later evidence. Only identical source/use records are deduplicated.
- `origin_provenance(origin, dependencies)` and `fitting_provenance(config,
  predictor_id=..., labels=..., historical_inputs=...)` populate the existing public
  records with exact evidence and summary timestamps/counts. Fitting label dependencies
  are all checked against the permitted delivery interval; publication and original
  historical source-use constraints are checked throughout. These functions record and
  validate evidence only; they do not fit anything.

Call selectors on relevant source rows, construct evidence only for rows actually used,
and keep historical features selected/recorded at their own origin. Label evidence may
be recorded later at fitting time. These utilities verify declared dependencies, not
arbitrary calculations or omitted dependencies; later models must supply full lineage.
Table adapters do not load `actuals_validation.csv` or discover files implicitly.

Verification on Python 3.12.14, pandas 2.2.3, NumPy 2.3.5:

```bash
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src/forecast_engine tests
git diff --check
```

All **29 tests passed**, including the 9 original Step 1 tests. Coverage includes both
cutoffs and exact boundaries, delayed labels, optional/essential gaps, future-delivery
inputs and spot, selection invariance, nested derived dependencies, historical use
times, DST/UTC handling, parser rejection/privacy, and isolated side-effect-free import.
Separate real-CSV smoke checks loaded 465,101 input rows and 14,824 spot rows and checked
selection/label assertions at both fitting cutoffs, plus value-free origin provenance.
No source values were printed, scoring actuals read, or fitting/forecasting performed.

The loader and as-of pivot adapt `baseline.ipynb`'s `read_long()` and
`rows_available_at()`. Deliberate safety changes reject naive timestamps and malformed
or duplicate rows, preserve long-form publication metadata, explicitly bound fitting
labels, and fail on missing required evidence rather than guessing availability.

Real Parquet reads remain unverified because `pyarrow` is absent in this environment.
Dispatch to pandas and the actionable missing-backend error were tested with mocks;
real CSV paths were exercised. No dependency was installed or starter requirement
changed for Step 2. Windows execution and full later forecasting/official validation
remain unverified and outside this step. Stop here pending explicit Step 3 approval.

## Step 3. Extract baseline fitting into reusable frozen state

**Implement:** Adapt historical persistence-error calibration, quantile offsets,
direction frequencies and spike frequencies. Check all source dependencies and eligible
pairs per step, not just a final summary timestamp. Document the source functions and
intentional adaptations from the reference.

**Expected new files:** `models/__init__.py`, `models/persistence.py`,
`tests/test_calibration.py`; extend configuration and provenance types as needed.

**Verify:** Small examples with known expected statistics; per-step partial horizons;
both label cutoffs; both source availabilities for spike labels; and strict spike
thresholds. Changing/removing ineligible labels must not change fitted state. Fail
clearly for no finite errors in any step, no eligible valid direction labels, or no
finite eligible imbalance/spot pairs. Record counts and dependencies without prices.

**After this step:** Fitting returns explicit reusable state and calibration provenance,
without generating forecasts or silently fabricating missing-evidence probabilities.

### Step 3 result and verification

Implemented `models/__init__.py`, `models/persistence.py`, and
`tests/test_calibration.py`; extended the isolated import test to include the models.
No original starter file, existing fit/predict signature, dependency, or data source
was changed. The pre-existing dataset_id metadata normalization fix in `data.py` and
`test_data.py` remains intact and is separate from the Step 3 implementation.

Fitting is directly callable through the existing interface:

```python
from forecast_engine import RunConfig
from forecast_engine.models import PersistencePredictor

# data is an existing ForecastInputs instance; this call does no I/O.
fitted = PersistencePredictor().fit(data, config=RunConfig.validation())
# fitted.q10 / q90: 40 raw persistence-error offsets, not completed prices.
# fitted.p_up / p_down / p_none / p_spike_high / p_spike_low: fitted frequencies.
# fitted.error_counts: 40 per-horizon counts.
# fitted.provenance: fitting boundaries, counts, source-use and derived evidence.
```

`FittedPersistence` uses frozen fields and immutable offset tuples. Its detached
provenance counts are read-only; dependency records/tuples are immutable and retain no
raw values. The object has no reference to caller-owned source tables. Its repr hides
fitted numbers and lineage, keeping accidental logs small and value-free. It conforms
to the existing FittedPredictor interface, but `predict(...)` explicitly raises
NotImplementedError: actual prediction remains unimplemented pending Step 4 approval.

Historical residual calibration reconstructs the latest available imbalance observation
at each contributing hourly origin, with the reference's three-day search followed by
all-earlier fallback. Each step independently looks up a label admitted by both RunConfig
delivery and availability bounds. Evidence for each horizon's quantile statistic retains
the target labels used at fitting time and the observations used at their historical
origins. No missing early observation is fabricated; origins without a usable starting
price do not contribute, and any horizon with no eligible error fails explicitly.

Direction frequencies use eligible finite -1/0/1 labels. Spike frequencies use aligned
eligible imbalance/spot deliveries and retain BOTH source dependencies, with strict
`imbalance > spot + 50` and `imbalance < spot - 50` thresholds. Missing labels, missing
spot pairs, invalid direction classes, or invalid fitted values produce clear errors
without logging input values. Counts include each horizon, contributing historical
origins, total error pairs, direction rows, both spike-source row counts, and spike pairs.

Adaptations from baseline.ipynb's `calibrate()` and `persistence_at()`:

- Preserve raw unrounded persistence residuals, NumPy linear empirical quantiles,
  round-to-six-decimal frequencies and p_none computed as the remaining probability.
  Quantile clipping and price/export rounding are deferred to Step 4 as in the reference.
- Enforce the agreed delivery bounds as well as publication cutoffs. Excluded labels
  cannot alter historical origin selection; stop the origin loop once later origins
  cannot target any eligible label. This avoids useless iterations without changing
  contributing pairs. Reconstruct observations only from eligible history, never from
  held-out/test outcomes or observations unavailable at that historical origin.
- Raise on missing essential evidence, invalid direction labels, or nonfinite errors
  instead of the reference's missing-spot zeros or implicit NaN/stack failures.
- Retain exact value-free dependency evidence, including historical source-use times,
  rather than trusting the reference's summary maximum availability alone.

Verification on the existing Python 3.12.14 / pandas 2.2.3 / NumPy 2.3.5 environment:

```bash
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src/forecast_engine tests
git diff --check
```

All **44 tests passed**, including all 31 existing tests. The 13 new checks cover
known linear and nonlinear quantiles, per-step partial horizons, both standard cutoffs,
historical publication delays, strict spike thresholds/both dependencies, excluded-label
modification/removal invariance, three-day fallback, direction rounding, missing evidence,
repeatable fitting, detached/frozen state, and value-free provenance. A test-only
extraction of the unchanged notebook's calibration functions matches offsets within
1e-12 and frequencies/counts exactly on eligible synthetic history. No notebook outputs
are inspected, and package runtime never parses or executes the notebook.

This is synthetic calibration verification, not a full-data baseline comparison or
accuracy claim. No full-data fitting, forecast generation, CSV export, CLI, official
forecast validation or scoring was run. Windows and real Parquet execution remain
unverified in this environment. Step 4 still requires explicit user approval.

## Step 4. Implement in-memory forecasting and optional export

**Implement:** Single-origin and batch prediction, using fitted state without refitting.
Preserve latest-usable persistence's three-day search and then all-earlier-history
fallback; record observation age and add no new staleness cap. Preserve deliberate
baseline quantile construction. Return the complete sorted 13-column DataFrame or a
clear origin/step/component error. Provide separate inference provenance and optional
CSV export. Preserve valid populated optional values as well as initially missing ones.

**Expected new files:** `engine.py`, `submission.py`, `tests/test_prediction.py`,
`tests/test_submission.py`; extend `models/persistence.py` and provenance types.

**Verify:** One-origin calls return 40 rows; batch and single-origin outputs agree.
Fitted state stays unchanged. Test unavailable-input invariance through actual
prediction, persistence fallback, missing required evidence, finite outputs, negative
prices, probability constraints, UTC/DST arithmetic, nullable and populated optional
values, and CSV round trips. Check the contract without duplicating the official
validator as a new scoring/validation tool. No silent horizon dropping or repairs.

**After this step:** An application can fit once, call prediction directly and receive
valid in-memory results and provenance, with CSV export available separately.

### Step 4 result and verification

Implemented `engine.py`, `submission.py`, `tests/test_prediction.py`, and
`tests/test_submission.py`. Completed `FittedPersistence.predict(...)` using the existing
signature; shared the existing latest-observation selector between calibration and
prediction. Extended OriginProvenance with a defaulted `source_ages` mapping, populated
by the existing provenance builder. Updated exports, import tests and the earlier test
that asserted prediction was unavailable during Step 3. No fitting algorithm, original
starter file, dependency, CLI or official tool was changed or added.

Public application use:

```python
from forecast_engine import forecast, export_forecasts

# fitted and inputs come from the existing fit/data interfaces.
result = fitted.predict(inputs, origins=[origin])
# Or dispatch any fitted predictor through the model-independent checked wrapper:
batch = forecast(fitted, inputs, origins=[origin, later_origin])
# Export only when explicitly requested; prediction itself has no filesystem work:
export_forecasts(batch.forecasts, output_path, origins=[origin, later_origin])
```

Requests must be nonempty sequences of unique aware full-hour datetimes. Explicit
offsets normalize to UTC; outputs and inference records sort by origin and step.
Repeated requests for the same UTC origin are rejected rather than silently deduplicated.
Each origin yields all 40 quarter-hours, or a clear component/origin/step error; no
partially completed result is returned. Direct and wrapper calls use the same checks.

Prediction follows the unchanged notebook's build_forecast(): latest usable historical
imbalance value, three-day search then all-earlier fallback, no new staleness limit,
p50 rounded to four decimals, lower offset min(q10, 0), upper offset max(q90, 0), and
rounded p10/p90. Negative prices are retained. No fitting, probability adaptation or
data-dependent updating of statistics occurs during inference. Published later-period
observations can supply lags, but observed imbalance deliveries later than the origin
are excluded. This baseline does not consume spot data during inference.

The result retains the same fitted provenance separately from per-origin actual
observation evidence, source availability, and delivery-relative age. All fitted
dependencies must have been usable by the fitting cutoff and the requested origin;
backdated use of a later fit is rejected. All inference dependencies are checked too.
No raw observation prices are retained in provenance or printed. The generic age
mapping can be negative for already-published future-delivery feature inputs; the
baseline's actual historical-observation age is nonnegative.

`validate_forecasts(frame, origins=...)` enforces the schema, finite required values,
quantile ordering, probability bounds/sums, exact keys, full horizons, sorting, UTC
arithmetic and optional cutoff rules. It performs no repair. It is an internal/public
table-contract helper, not a replacement for the official validator. Pass requested
origins when checking a caller-edited table to detect an entirely removed origin;
without them, completeness is checked for all origins present.

`export_forecasts(frame, path, origins=...)` copies and validates the table, serializes
UTF-8 comma CSV with no index, six-decimal numbers and whole-second UTC Z timestamps,
and re-parses the serialized content before any write. Empty optional values become
empty cells; populated timestamps and text (including literal NA/nan, Unicode, quoting
and embedded newlines) survive. In-memory probability sums use numerical precision;
after six-decimal serialization the official 0.001 tolerance is allowed without
renormalizing values. Export then atomically replaces the destination with a temporary
file in the same directory; validation/serialization failures preserve an existing
target, and replacement failures clean up the temporary file.

Intentional differences from the notebook remain the approved blank optional output
fields plus explicit full-result, source-availability and dependency checks. Full
calibration/inference provenance is separate from the official table. No additional
statistical method or forecast improvement is claimed.

Verification on Python 3.12.14 / pandas 2.2.3 / NumPy 2.3.5:

```bash
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src/forecast_engine tests
git diff --check
```

All **64 tests passed**, including the existing 44 tests (with the obsolete Step 3
NotImplementedError expectation removed). The 20 new tests cover single/batch and
generic-model calls, no refitting or input/state mutation, publication equality and
unavailable-row invariance, old/recent/missing observation selection, negative prices,
quantile clipping and rounding, pre-fit requests, DST-repeated local hours, malformed
and missing keys/values, complete horizons, nullable types and optional metadata,
CSV serialization/round trips, invalid serialized output, and atomic replacement
failure cleanup. No challenge inputs/actuals were read for this step; all new tests
use synthetic values and temporary output paths.

The official validator/scorer were not invoked, and there were no full validation or
test-period runs. Windows, actual Parquet and full-data performance remain unverified.
These remain for their approved later verification scopes. Stop pending explicit
Step 5 approval; no command-line workflow exists yet.

## Step 5. Add the reproducible local command workflow

**Implement:** Thin validation/test CLI commands using the same engine API, explicit
paths and the unchanged official tools. Record manifests, commands, configuration,
versions, source revision/dirty state/source fingerprints, consumed-input and starter
SHA-256 hashes, fitting boundaries, provenance, counts, runtime and exit codes.

**Expected new files:** `cli.py`, `__main__.py`, `evaluation.py`,
`tests/test_cli.py`, and `docs/forecasting-engine.md`.

**Implemented command shape**, after documented package setup, from the repo root:

```text
python -m unittest discover -s tests
python -m forecast_engine validation --data-dir data --starter-dir . --output-dir baseline_output/engine/validation
python -m forecast_engine test --data-dir data --starter-dir . --output-dir baseline_output/engine/test
```

Validation invokes `make_templates.py` for its
own origins/template, fits at the validation cutoff, predicts, exports, validates and
scores. Test fits separately at its cutoff, uses the supplied test template, exports
and validates; it never evaluates test outcomes. Prediction itself never calls the
official tools or requires subprocesses, CSV files or the caller's working directory.

**Verify:** CLI/API agreement on a representative synthetic subset, explicit-path use
from another directory, clear failures and exit codes, and valid manifests. Keep
official tool invocations outside the prediction core.

**After this step:** Documented local execution, separate validation/test outputs and
audit evidence, ready for full-data acceptance.

### Step 5 result and verification

Added `cli.py`, `__main__.py`, `evaluation.py`, `tests/test_cli.py` and
`docs/forecasting-engine.md`; extended import-side-effect coverage for the new modules.
The existing model, fitting/prediction, availability, export algorithms, public core
interfaces and original starter files were not modified. No dependency was added.

The module CLI implements the two commands above with `--starter-dir`, `--data-dir`,
`--output-dir`, `--inputs-file` and `--spot-file`; validation additionally accepts
`--actuals-file`. Explicit relative paths resolve from the caller's directory, while
omitted data/output paths derive from starter-dir. Defaults use CSV inputs and ignored
baseline_output/engine/MODE storage. Require a new/empty output directory to prevent
stale results and accidental overwriting of starter files. Repeat or failed runs use
a fresh output path rather than silently reusing previous artifacts.

Validation invokes the unchanged generator for 7 September–4 October, checks all
canonical origins/template identifiers, fits once at the approved validation cutoff,
calls the shared in-memory API/export, then invokes the official validator and scorer.
The first actuals-byte read/hash occurs only after prediction/export/validation; actuals
never enter the forecasting API. Test copies/verifies the supplied canonical 673-origin
template, fits separately at the approved test cutoff, exports 26,920 rows and invokes
only the validator. It does not discover, hash or evaluate test actuals. Known actuals
filenames are rejected as forecasting sources before source fingerprinting, and known
test actuals cannot be passed as validation scoring inputs.

The local adapter saves forecast/templates, official aggregate score files for validation,
safe JSON tool reports and run_manifest.json. Manifests record accepted arguments,
resolved paths, exact commands/exit codes, timestamps/runtime, Python/dependency versions,
Git commit/dirty-state digest when available, package source fingerprints, consumed
input/relevant starter hashes, run configuration, counts, safe fitting lineage digest
and per-origin observation timestamps/availability/ages. Source/input integrity is
checked again before completion. No raw source/forecast values, fitted numbers, environment
variables or raw exception/subprocess output are included in logs/manifests. Official
diagnostics retain only fixed-format statuses, counts and finding codes. Failed runs
save safe failure stage/type metadata and return nonzero, without claiming completion.

The editable installation command `python -m pip install --no-cache-dir
--no-build-isolation -e .` was rerun successfully in the existing environment. Package
and both subcommand help outputs were verified, as were the real official scripts'
argument names. See docs/forecasting-engine.md for setup, paths, artifacts, limitations
and failure/retry instructions; no original requirements were changed.

Verification on Python 3.12.14 / pandas 2.2.3 / NumPy 2.3.5:

```bash
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src/forecast_engine tests
git diff --check
```

All **74 tests passed**, including the existing 64 tests. The ten new tests cover:

- An 80-row synthetic validation run with direct Python API agreement, the correct
  validation cutoff, real unchanged validator/scorer subprocesses and aggregate score
  artifacts. Only template generation/expected-origin selection are shortened by a
  private test fixture, not a production CLI flag.
- The real unchanged template generator's complete 672-origin validation grid and
  canonical identifiers.
- Synthetic test-mode cutoff/actuals separation and a real `python -m forecast_engine
  test` process from another working directory using space-containing absolute paths,
  the complete 673-origin template and just one synthetic fitting day. It exported
  26,920 rows and passed the real unchanged validator. This is a small-data command/path
  integration check, not challenge-data acceptance.
- Missing files, failed validator/scorer processes, unknown actuals options, known
  actuals-source guards, nonempty output protection, defaults, failure manifests and
  redaction of synthetic private-value/secret diagnostics. No challenge actuals were read.

Fresh environment provisioning, Windows execution, real Parquet and challenge-data
performance remain unverified. No expensive full-data acceptance, repeated full-data
run or independent notebook-parity experiment was performed. Step 6 remains separately
authorized work. The review handoff includes local candidate fingerprints and checks.

## Step 6. Run full acceptance and document the result

**Implement/complete:** Full-data verification, comparison reporting and runnable
setup/API/CLI documentation. Make only corrections justified by the preceding checks.

**Expected files:** Extend `evaluation.py`, focused tests and
`docs/forecasting-engine.md` where needed. Create reports/manifests only under
`baseline_output/engine/`, with repeat runs in separate directories.

**Verify:**

1. All focused `unittest` checks pass, including required leakage invariance tests.
2. Generate a fresh independent validation reference from the unchanged notebook in a
   transient/reference-only process with organiser mode disabled. Never save executed
   outputs into the original notebook or make this an engine runtime dependency.
3. Validate and score engine/reference with identical keys, actuals and spike margin 50.
   Require equal scored-row counts for price, spikes and direction. For this package
   expect 26,880 validation rows and 26,700 scored rows, retaining all 180 tail rows.
4. Compare numeric CSV results: MAE; p10/p90 pinball and their mean; high/low spike Brier
   and their mean; direction Brier; coverage and horizon summaries. The official
   `--baseline-summary` option alone compares MAE and is insufficient here.
5. Target exact identifiers, forecast-value absolute differences at most `1e-6`, and
   MAE/pinball/Brier differences at most `1e-5`, using reference rounding where practical.
   Exclude optional fields from parity and report coverage differences separately.
   These are diagnostic targets. Explain safety-related/correctness differences with
   source, eligibility change, numerical impact and evidence; retain safer behaviour.
   Investigate unexplained material discrepancies without spending excessive time on
   notebook-specific reproduction. State any unverified reference comparison honestly.
6. Repeat the full validation command with identical inputs/configuration/environment
   in a clean output directory. Require byte-identical forecast CSVs and equal numeric
   metrics; timing metadata may differ. Check direct API/CLI and one/batch agreement.
7. Generate and structurally validate the final-format test file: all 673 origins and
   26,920 rows, zero validator errors. Record/review warnings. Do not score test outcomes.
8. Verify original starter hashes remain unchanged and retain complete fitting and
   inference evidence. Protect restricted data and values in every artifact.

**After this step:** A correct, reproducible, independently compared engine and a valid
baseline-quality fallback submission. Acceptance means verified behaviour and evidence;
it does not mean improved accuracy or competition points. Report whether numerical
baseline equivalence was actually achieved.

## Follow-up milestone: first competing model

After engine acceptance, separately review the proposed supplied-data histogram GBDT
experiment, direct-price versus spot-relative targets, horizon-aware features and all
four official metrics. Reuse the engine's data rules, output contract, workflow and
provenance; replace the predictor. This is outside the current Wayfinder map and is
not an approved implementation step in this plan. External revisions, UI, deployment
and database work also remain separate decisions.

## Approval and execution

Review the whole plan first. Once the user approves it, implement Step 1 only, report
changed files and actual test results, then stop. Each subsequent step requires
explicit user approval before work begins. If a step reveals a material scope change,
explain it before proceeding. Do not commit, push or merge unless explicitly requested.

Steps 1–5 are complete. Stop here until the user explicitly approves Step 6. The shared
engine, optional export and reproducible CLI workflow exist; full-data acceptance has
not been performed. No commit, push, or merge is authorized.
