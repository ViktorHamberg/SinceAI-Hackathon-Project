# First forecasting engine: consolidated implementation plan

**Status: plan approved; Step 1 implemented and verified. Steps 2–6 await separate
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

## Step 5. Add the reproducible local command workflow

**Implement:** Thin validation/test CLI commands using the same engine API, explicit
paths and the unchanged official tools. Record manifests, commands, configuration,
versions, source revision/dirty state/source fingerprints, consumed-input and starter
SHA-256 hashes, fitting boundaries, provenance, counts, runtime and exit codes.

**Expected new files:** `cli.py`, `__main__.py`, `evaluation.py`,
`tests/test_cli.py`, and `docs/forecasting-engine.md`.

**Proposed command shape**, after documented package setup, from the repo root:

```text
python -m unittest discover -s tests
python -m forecast_engine validation --data-dir data --starter-dir . --output-dir baseline_output/engine/validation
python -m forecast_engine test --data-dir data --starter-dir . --output-dir baseline_output/engine/test
```

These engine commands do not exist yet. Validation invokes `make_templates.py` for its
own origins/template, fits at the validation cutoff, predicts, exports, validates and
scores. Test fits separately at its cutoff, uses the supplied test template, exports
and validates; it never evaluates test outcomes. Prediction itself never calls the
official tools or requires subprocesses, CSV files or the caller's working directory.

**Verify:** CLI/API agreement on a representative synthetic subset, explicit-path use
from another directory, clear failures and exit codes, and valid manifests. Keep
official tool invocations outside the prediction core.

**After this step:** Documented local execution, separate validation/test outputs and
audit evidence, ready for full-data acceptance.

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

Step 1 is complete. Stop here until the user explicitly approves Step 2. The package
foundation and tests exist; there is no actual fitting, prediction, data adapter, or
engine CLI yet. No commit, push, or merge is authorized.
