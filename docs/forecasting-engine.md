# Forecasting engine: local workflow

`forecast_engine` is the shared Python forecasting library. The commands below are
thin local adapters around the same fitting, prediction and export API used by an
application. They do not start a web service or require Jupyter.

## Installation

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
improvement or competition points. Independent baseline comparison belongs to Step 6;
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

## Verification scope so far

Step 5 tests use synthetic fitting data and small fixtures. A two-origin validation
fixture checks direct API agreement and runs the real official validator/scorer.
The real template generator is independently checked for the canonical validation
grid. A module command from another directory runs the full 673-origin test grid on
one synthetic day of history, confirming 26,920 structurally valid rows without test
actuals. This is a small-data command/path integration check, not challenge-data
acceptance or a quality claim. Failures, redaction, defaults, actuals separation and
import side effects are also tested. Full-data acceptance, repeatability and independent
notebook comparison remain Step 6 and require separate approval.
