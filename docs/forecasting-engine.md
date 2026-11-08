# Forecasting engine: local workflow

`forecast_engine` is the shared Python forecasting library. The commands below are
thin local adapters around the same fitting, prediction and export API used by an
application. They do not start a web service or require Jupyter.

## Installation

For ongoing engine/backend development, use the shared
[uv environment workflow](python-environment.md), including its verification status.
It preserves starter requirements and provides the same sync command on macOS and
Windows. The pip examples below describe the original installation procedure.

Use Python 3.11 or newer. The system `python3` on the development Mac points to 3.6,
so select a suitable interpreter explicitly when creating an environment.

macOS, with Python 3.11 installed:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install "setuptools>=64" wheel
python -m pip install --no-build-isolation -e .
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install "setuptools>=64" wheel
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -e .
```

The editable installation command was verified in the existing `.venv` with Python
3.12.14, pandas 2.2.3 and NumPy 2.3.5. Fresh dependency downloads and Windows setup
were not verified in this environment. Original starter requirements remain unchanged.
The CLI defaults to CSV; Parquet is available through an explicit input-file override
when a backend such as the starter's pyarrow dependency is installed.

## Commands

From the repository root, using the activated environment:

```bash
python -m unittest discover -s tests -v
python -m forecast_engine --help
python -m forecast_engine validation --data-dir data --starter-dir . --output-dir baseline_output/engine/validation
python -m forecast_engine test --data-dir data --starter-dir . --output-dir baseline_output/engine/test
```

On Windows without activation, replace `python` with `.\.venv\Scripts\python.exe`;
on macOS without activation, use `.venv/bin/python`.

Every run requires a **new or empty output directory**. Existing runs and starter
files are never overwritten by these commands. For another attempt, including after
a failed run, select a fresh destination such as
`--output-dir baseline_output/engine/validation-run-02`.

All explicitly supplied relative paths resolve against the caller's current directory.
For execution elsewhere, use absolute paths. If omitted, `--starter-dir` is the current
directory, `--data-dir` is STARTER_DIR/data, and `--output-dir` is
STARTER_DIR/baseline_output/engine/MODE. Input and starter-tool paths do not depend on the package's
installation directory. The interpreter used to invoke the package also runs the
official scripts, including paths containing spaces.

Input overrides:

- `--inputs-file PATH`: default DATA_DIR/inputs.csv; accepts the supplied CSV/Parquet.
- `--spot-file PATH`: default DATA_DIR/spot_nordpool.csv.
- `--actuals-file PATH`: validation scoring only; default
  DATA_DIR/actuals_validation.csv. Use only validation actuals. Test mode does not
  accept this flag and never searches for a test actuals file. Known actuals filenames
  are rejected when supplied as forecasting inputs; known test actuals are rejected
  as validation scoring inputs.

## Validation flow

1. Invoke unchanged `make_templates.py --test-start 2026-09-07 --test-end 2026-10-04
   --timezone Europe/Helsinki --output-dir OUTPUT_DIR`.
2. Check the canonical 672 hourly origins and all template identifiers, including the
   complete 40-step horizons. Fit once with `RunConfig.validation()`.
3. Predict through the existing in-memory API and export 26,880 forecast rows. Keep
   tail deliveries even where actuals are absent.
4. Invoke unchanged `validate_submission.py --backtest FORECAST --origins ORIGINS`.
5. Only after successful validation, hash/pass validation actuals to unchanged
   `score.py --submission FORECAST --actuals ACTUALS --spike-margin 50 --output-dir SCORE_DIR`.

The fitting cutoff is 2026-09-06T21:00:00Z. Publication and label-delivery rules are
enforced by the existing engine. Actuals never enter the prediction API. The scorer
creates `score_summary.csv`, `score_summary.md` and `score_by_horizon.csv`; it skips
unlabelled deliveries and reports counts. This workflow records scores, not baseline
improvement or competition points. The Step 6 comparison below covers all metrics;
the scorer's optional `--baseline-summary` alone would compare MAE only.

## Test flow

Copy the supplied `forecast_origins.csv` and `sample_submission.csv` into the run
directory without editing the originals. Verify the canonical 673 origins and their
40-step identifiers. Fit separately with `RunConfig.test()` at
2026-10-04T21:00:00Z, predict/export all 26,920 rows, and invoke the unchanged validator.
No scorer is invoked, and no test actuals are loaded, hashed, or passed to fitting or
prediction. Later available test-period observations may provide inference lags, as
allowed by the official availability rule; fitted statistics remain frozen.

## Artifacts and audit information

Each run stores:

- `forecast_origins.csv`, `sample_submission.csv`, and `forecast_backtest.csv`.
- Safe `official_templates.json` / `official_validation.json` /
  `official_scoring.json` reports for tools actually invoked.
- `score/` with the official aggregate score reports for validation only.
- `run_manifest.json`, with complete/failed status and the failing stage if applicable.

The manifest records accepted command arguments, resolved paths, Python/dependency
versions, Git commit/dirty status when available, package source hashes, consumed-file
and relevant starter-file SHA-256 hashes, fitting boundaries, counts, safe fitting
lineage summaries/digest, per-origin observation availability/age, elapsed time, tool
commands/exit codes, and artifact paths/hashes. Source/input integrity is checked again
before marking the run complete. Git is optional; source fingerprints remain available
when Git metadata cannot be obtained.

Only fixed-format statuses, counts and finding codes from official stdout are retained.
Raw stdout/stderr and exception text are not logged because parser diagnostics can
contain input values. Failures give a safe stage/type diagnostic and nonzero exit code;
inspect the JSON tool report for exit codes and validator finding codes. No environment
variables, individual forecasts, restricted spot values, or fitted numeric statistics
are copied into manifests/logs. Forecast values are stored only in the intended CSV;
score files contain official aggregate metrics. Keep all generated artifacts local
under ignored storage and follow the README's data licence/deletion rules.

Exit codes: 0 means workflow complete; 1 means preflight, engine, filesystem or official
tool failure; 2 means invalid command syntax. A forecast CSV in a failed directory is
not evidence that validation/scoring completed: check manifest status and exit codes.

## Python application interface

Applications and experiments can call the same engine without the CLI, notebook or
official-tool subprocesses:

```python
from forecast_engine import RunConfig, load_inputs, forecast
from forecast_engine.models import PersistencePredictor

data = load_inputs("data/inputs.csv", spot_path="data/spot_nordpool.csv")
config = RunConfig.validation()
fitted = PersistencePredictor().fit(data, config=config)
result = forecast(fitted, data, origins=[config.fit_cutoff_utc])
frame = result.forecasts       # 40 rows, official 13-column DataFrame
evidence = result.provenance   # separate fitting and inference evidence
```

Reuse `fitted` for later origins with appropriately available inputs. The public
`forecast` contract accepts other implementations of `FittedPredictor`; selecting
the persistence model above does not bind the application contract to that model.
The backend currently selects `LightGBMPredictor(target_mode="spot_relative")` with
the provisional `relative-control-v1` recipe and reports predictor ID
`lightgbm-relative-v1`. It fits once before serving cached forecasts. The example
above explicitly selects Persistence; engine CLI defaults remain unchanged.
Optional disk export is `export_forecasts(frame, path, origins=origins)` from
`forecast_engine`. Official validation/scoring remain workflow responsibilities.

## Focused verification

Step 5 tests use synthetic fitting data and small fixtures. A two-origin validation
fixture checks direct API agreement and runs the real official validator/scorer.
The real template generator is independently checked for the canonical validation
grid. A module command from another directory runs the full 673-origin test grid on
one synthetic day of history, confirming 26,920 structurally valid rows without test
actuals. This is a small-data command/path integration check, not challenge-data
acceptance or a quality claim. Failures, redaction, defaults, actuals separation and
import side effects are also tested. Full-data acceptance is recorded below.

## Step 6 acceptance: PASS recommendation, pending independent review

Executed on 7 November 2026 on macOS, branch `dev_viktor`, engine revision
`b168ad2ddc225cbe8fd5229458baea99036ccb3d`, with a clean tracked working tree during
the runs. Environment: Python 3.12.14, pandas 2.2.3, NumPy 2.3.5, setuptools 84.2.1,
wheel 0.48.0. The existing editable installation was used; no dependency installation
or starter-requirements change was needed. CSV input was used because pyarrow is
absent. There was approximately 6.9 GiB of free disk space before execution.

No engine defect was found and no production code or test correction was needed.
This step changes documentation and retains private acceptance evidence under the
ignored `baseline_output/engine/acceptance-01/` directory. This is first-engine
acceptance, not completion of the application's other deliverables.

### Commands actually executed

From the repository root, using the existing environment:

```bash
mkdir -p baseline_output/engine/acceptance-01
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v > baseline_output/engine/acceptance-01/tests.log 2>&1
.venv/bin/python -m forecast_engine validation --data-dir data --starter-dir . --output-dir baseline_output/engine/acceptance-01/validation-1 > baseline_output/engine/acceptance-01/validation-1.log 2>&1
.venv/bin/python -m forecast_engine test --data-dir data --starter-dir . --output-dir baseline_output/engine/acceptance-01/test > baseline_output/engine/acceptance-01/test.log 2>&1
.venv/bin/python baseline_output/engine/acceptance-01/generate_reference.py . data baseline_output/engine/acceptance-01/validation-1 baseline_output/engine/acceptance-01/reference > baseline_output/engine/acceptance-01/reference.log 2>&1
.venv/bin/python -m forecast_engine validation --data-dir data --starter-dir . --output-dir baseline_output/engine/acceptance-01/validation-2 > baseline_output/engine/acceptance-01/validation-2.log 2>&1
.venv/bin/python baseline_output/engine/acceptance-01/compare_acceptance.py baseline_output/engine/acceptance-01 > baseline_output/engine/acceptance-01/comparison.log 2>&1
```

All commands exited 0. The full suite passed **74 tests**, with no failures or skips
(26.0 seconds), including leakage invariance, fitting boundaries, frozen state,
one/batch agreement, serialization, CLI/API integration and import isolation. The
validation runs took 32.0 and 30.1 seconds, test 31.9 seconds, reference 11.0 seconds.
Initial validation and test ran concurrently; these timings are local observations,
not performance benchmarks. Re-execution requires fresh output directories.

The two helper scripts are local ignored acceptance artifacts, not installed engine
components. They are available in this checkout; Git does not transfer them or their
results to a teammate. Ordinary engine execution needs only the package and the CLI
commands above. Recreating the independent reference elsewhere requires the notebook
source-cell procedure described below, or an authorized local copy of the helpers.
Exact subprocess arguments, input/source hashes and environment are in each run's
`run_manifest.json` and `reference/reference_manifest.json`.

### Official results and artifacts

All paths in this subsection are relative to `baseline_output/engine/acceptance-01/`.

| Run | Origins | Forecast rows | Official validator | Official scorer |
|---|---:|---:|---|---|
| `validation-1` | 672 | 26,880 | 0 errors, 0 warnings | exit 0 |
| `validation-2` | 672 | 26,880 | 0 errors, 0 warnings | exit 0 |
| `reference` | 672 | 26,880 | 0 errors, 0 warnings | exit 0 |
| `test` | 673 | 26,920 | 0 errors, 0 warnings | not invoked |

Both validation runs and the reference scored **26,700 rows** for price, spike and
direction. The scorer skipped **180** unlabelled tail rows; all 26,880 predictions
remain in the CSV. The official spike margin was 50 EUR/MWh with strict above/below
thresholds. The four official numerical metrics and supporting diagnostics follow;
every engine/reference difference is zero, including the unrounded reported scores.

| Validation metric | Engine and independent reference |
|---|---:|
| Median-price MAE (EUR/MWh) | 66.20330374531835 |
| Mean p10/p90 pinball loss | 24.1776182752809 |
| Mean high/low spike Brier | 0.1131762465808895 |
| Direction Brier | 0.4509074368240898 |
| p10 pinball | 25.10757813483146 |
| p90 pinball | 23.24765841573034 |
| High-spike Brier | 0.1082571072098989 |
| Low-spike Brier | 0.1180953859518801 |
| p10–p90 interval coverage | 68.28838951310862% |

Official hourly horizon summaries (rounded here only) are identical for engine and
reference. The full precision reports also retain separate high/low Brier and
p10/p90 pinball values in each run's `score/score_by_horizon.csv`.

| Horizon hour | Scored rows | MAE | Mean pinball | Mean spike Brier | Direction Brier | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 2,688 | 51.743144 | 19.895822 | 0.112451 | 0.451263 | 70.3497% |
| 2 | 2,684 | 57.125853 | 21.149369 | 0.112611 | 0.451563 | 68.4054% |
| 3 | 2,680 | 62.255410 | 22.775454 | 0.112772 | 0.451427 | 68.5075% |
| 4 | 2,676 | 64.841386 | 23.599972 | 0.112933 | 0.450851 | 68.3109% |
| 5 | 2,672 | 66.422275 | 24.085369 | 0.113095 | 0.450273 | 68.6751% |
| 6 | 2,668 | 68.500176 | 25.068589 | 0.113257 | 0.450134 | 69.4153% |
| 7 | 2,664 | 70.156066 | 25.561405 | 0.113420 | 0.450435 | 69.4444% |
| 8 | 2,660 | 72.579868 | 26.480198 | 0.113583 | 0.450737 | 67.3308% |
| 9 | 2,656 | 74.346480 | 26.749912 | 0.113747 | 0.451040 | 66.6792% |
| 10 | 2,652 | 74.357296 | 26.503021 | 0.113911 | 0.451344 | 65.7240% |

The complete final-format test artifact is
`baseline_output/engine/acceptance-01/test/forecast_backtest.csv`, SHA-256:

```text
c1794383fad4ae0561802d8b4e07bebb5131ce20253e80fb2360ab80b2c117ff
```

Validation artifacts are `validation-1/forecast_backtest.csv` and
`validation-2/forecast_backtest.csv`; both have SHA-256
`6bf1248ab16513d227903edc1aa6084e3d6867f6bb7b6119a0a3dfaa233f0540`.
Aggregate checks are in `acceptance_report.json`, with maximum absolute differences
by horizon and UTC origin date in `forecast_difference_by_horizon.csv` and
`forecast_difference_by_date.csv`. No individual forecast values are copied here.

### Independent reference and reproducibility

The reference helper reads the unchanged `baseline.ipynb` as JSON in a separate
process. With `SINCEAI_ORGANIZER=0`, it executes only the original source cells
`ac684b31` (setup/loaders), `25a7f3c5` (availability helper) and `ccab90f4`
(calibration/prediction/export definitions) in memory. It explicitly loads the same
CSV inputs and validation origins/template, then calls the original `calibrate`,
`build_forecast` and `write_submission`. It imports no engine code and uses no engine
statistics or forecasts. Notebook stdout/stderr are suppressed and no executed
notebook is saved. The unchanged validator and scorer run on its separate CSV with
the same actuals and margin. Notebook SHA-256 before/after:
`03e914a23fdc580d466ff8e91771e764b6afcf085ad9190421b17c3d00b38dca`.

All identifiers and all eight required forecast fields match exactly: maximum
absolute difference **0**, within the diagnostic `1e-6` target. All numerical score
differences are **0**, within `1e-5`; coverage and horizon scores match exactly too.
Date/horizon comparisons find no discrepancies. Optional fields are intentionally
blank in the engine and populated by the reference, so the reference CSV's byte hash
differs. These optional fields are excluded from numerical parity. The engine retains
the stricter historical/per-step eligibility checks agreed earlier; they cause no
numerical difference on this supplied validation history.

Repeated validation produced byte-identical forecasts and identical aggregate/horizon
scores, keys, counts, fitting configuration, provenance, input hashes and environment
records. Runtime metadata differs as expected. A separate full-data API smoke fitted
once, checked two origins as single calls and one batch against the corresponding
80 CLI rows, and guarded against refitting; fitted statistics/counts/provenance remained
unchanged. Its safe result is `api_smoke_report.json`.

### Availability evidence, integrity and sources

Validation used label deliveries `[2026-05-31T21:00Z, 2026-09-06T21:00Z)` with
publication at or before `2026-09-06T21:00Z`; test used
`[2026-05-31T21:00Z, 2026-10-04T21:00Z)` with publication at or before
`2026-10-04T21:00Z`. Historical inputs are reconstructed at each historical origin,
and each step's label is checked independently. Spike calibration requires both
imbalance and corresponding spot evidence; no missing evidence is invented.

Validation recorded 2,349 calibration origins, 93,780 eligible error pairs and 9,404
spike pairs; test recorded 3,021 origins, 120,660 error pairs and 12,092 spike pairs.
The latest fitted label deliveries were respectively `2026-09-06T19:45Z` and
`2026-10-04T19:45Z`; maximum fitting publication times equalled their permitted
cutoffs. Value-free fitting lineage digests/counts and every inference observation's
timestamp, availability and age are in the manifests. An independent metadata-only
audit checked every selected inference observation against source publication times
and confirmed fitting summary boundaries for all three engine runs. Full dependency
eligibility and leakage invariance are also enforced by the engine and focused tests;
the official validator alone does not establish leakage safety.

Validation actuals were supplied only to the scorer after forecast validation. The
test manifest consumes only inputs, spot, origins and template; no test actuals were
opened, hashed, scored or used for training/model selection. Test-period published
observations serve only as inference lags, with fitted statistics frozen.

Consumed dataset SHA-256 fingerprints (no dataset values):

| File | SHA-256 |
|---|---|
| `data/inputs.csv` | `2728accff78dcac8cff1d164a1661aeb4336f0cd1d5f39812d0d89afec4d4ce2` |
| `data/spot_nordpool.csv` | `fdbe99eae9092794e47cbd4bfbe4cd39f49ccd7096492c1f417e618ba1a25ee1` |
| `data/actuals_validation.csv` | `6c146b0f333a179ac8f6be4620f7d97dba0eb9e9dc59cdb1eee38759db2bb908` |

Run manifests retain package/tool/template hashes. Original starter and instruction
files remain byte-identical to the reviewed revision; consumed input hashes were
rechecked after execution. Generated artifacts are ignored, not publication material.
Per README section 9, Fingrid uses CC BY 4.0; the supplied ENTSO-E free-reuse-list
series use CC BY 4.0, converted to UTC/15-minute form. Nord Pool is licensed to Turku
Energia for this hackathon: do not redistribute or publish its data, including the
validation actuals' `spot_price` column, and delete it after the event. No new data
source or dependency was introduced.

### Acceptance and remaining limits

All first-engine acceptance criteria passed: the focused suite, chronological
availability checks, complete official validation/test grids, zero validator
errors/warnings, official scoring, independent numerical comparison, repeated
validation and preservation of starter/source data. This is an author **PASS**
recommendation for independent review, not a reviewer verdict or permission to push.

This establishes baseline-equivalent performance, with no demonstrated improvement
or competition-points claim. Coverage is 68.29%, below the nominal 80%; that is a
measured model-quality limitation, not a structural acceptance failure. Windows,
fresh dependency provisioning and actual Parquet reads remain unverified. Test-period
accuracy is unknown and was deliberately not evaluated. Optional explainability
fields remain blank. The independent helper scripts and all results are local ignored
artifacts; another machine must reproduce or obtain the authorized local evidence.
Stop for user review; no competing-model implementation, commit, push or merge is
authorized by this result.
