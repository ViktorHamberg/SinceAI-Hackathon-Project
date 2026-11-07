# Backend: prepare a historical forecast (Step 1A)

The application service prepares one genuine engine forecast and retains a safe JSON
response. It uses the existing persistence predictor, not an improved ML model.
FastAPI routes and the browser are later steps; this version does not start a server.

## Files and responsibilities

| File | Responsibility |
|---|---|
| `app/config.py` | Explicit local source paths; defaults derive from this checkout. |
| `app/forecast_service.py` | Load, fit once, predict once, retain the result and serve cached JSON. |
| `app/schemas.py` | Validate the forecast and serialize only approved response fields. |
| `tests/test_forecast_service.py` | Synthetic correctness, lifecycle, privacy and portability checks. |
| `tests/smoke_forecast.py` | Explicit real-data acceptance check with value-free output. |

No new dependency, root packaging change or engine modification is required. This
backend is imported from the repository root; it is not a separately installed package.

## Setup on Windows and macOS

Use the existing Python 3.11+ environment and editable engine installation described in
[the engine guide](../docs/forecasting-engine.md). Do not share `.venv` directories
between machines. Both teammates need their own authorized local challenge data.
Do not copy datasets through GitHub.

The default data paths are `<checkout>/data/inputs.csv` and
`<checkout>/data/spot_nordpool.csv`. There is no actuals path or dataset discovery.
Use `ForecastConfig.from_data_dir(...)` for an explicit data directory, or
`ForecastConfig(inputs_path=..., spot_path=...)` for two explicit source files.
Explicit relative paths resolve at configuration time from the caller's directory;
the default paths are independent of the working directory. Paths with spaces work.
The preparation service itself performs no file writes or network requests.

Run commands from the repository root. Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast --data-dir data
```

macOS:

```bash
.venv/bin/python -W error::FutureWarning -m unittest discover -s backend/tests -v
.venv/bin/python -W error::FutureWarning -m backend.tests.smoke_forecast --data-dir data
```

The synthetic suite needs no challenge data and creates only temporary synthetic
files. The smoke command explicitly uses local data and prints a JSON check report
with counts, identifiers, dependency versions and preparation time. It prints no
source prices or individual forecasts. It exits 0 on success and nonzero on failure.
Run that same command on the Mac before claiming this step is verified on both OSes.

## Service usage

```python
from backend.app.config import ForecastConfig
from backend.app.forecast_service import prepare_forecast

# Explicit preparation, once during application initialization:
service = prepare_forecast(ForecastConfig.from_data_dir())

# Later consumers retrieve a detached JSON-compatible dictionary:
payload = service.response()
assert len(payload["points"]) == 40

# Or retrieve the already serialized JSON without recomputation:
serialized = service.response_json()
```

Importing these modules performs no input loading, fitting, heavy numeric imports,
printing or external work. Calling `prepare_forecast` loads sources, fits with
`RunConfig.validation()`, and calls public `forecast(...)` for
`2026-09-06T21:00:00Z`. Fitting labels end before that origin, with publication no
later than the cutoff. The engine enforces historical availability; actual outcomes
are never supplied to the service. These are historical forecasts, not live data.

Preparation can be slow because it includes full historical calibration and its
dependency evidence. Retain the returned service; do not call `prepare_forecast` for
each future HTTP request. Each deliberate new call creates a new independent run.
In Step 1B the FastAPI lifespan will own this service; each process/reload will prepare
again. One worker is the initial policy. No fitted-model persistence or existing-CSV
reader is implemented. Reassess preparation costs before adopting an expensive model.

Retrieval performs no loading, fitting, prediction, source hashing or disk writes.
The cached JSON string is immutable; changing the dictionary returned by `response()`
cannot change the cached forecast. The service keeps fitted state and the engine
result privately for later controlled use and audit; HTTP consumers must use only the
response methods. Their repr does not include data values.

## Response contract and identity

The application envelope is separate from the locked challenge CSV schema:

| Field | Meaning |
|---|---|
| `schema_version` | Application JSON contract version, currently `1.0`; independent of CSV versioning. |
| `run_id` | A new UUID for each successful preparation. Stable on retrieval, not a reproducibility hash or a fitted-model artifact ID. |
| `model_id` | Application-selected recipe label, initially `persistence-v1`. Update it when deliberately selecting a different recipe/configuration. |
| `predictor_id` | The fitted engine predictor's short identifier, initially `persistence`. |
| `engine_revision` | `sha256:` fingerprint of all installed engine Python sources, including uncommitted changes. Relative filenames and raw contents are hashed in sorted order. It is not a Git commit or data hash. |
| `generated_at_utc` | UTC wall-clock time when this response was constructed, at whole-second precision. It is not the historical forecast origin or an input publication time. |
| `forecast_origin_utc` | Historical hourly origin represented by this snapshot. |
| `fit_cutoff_utc` | Availability cutoff of the model's fitting run. |
| `points` | Forty points in step order, with all 13 official column names. |

Each point preserves `forecast_origin_utc`, `delivery_start_utc`, integer `step`,
`p10`, `p50`, `p90`, `p_up`, `p_down`, `p_none`, `p_spike_high`, `p_spike_low`,
`data_cutoff_utc` and `top_drivers`. Times are whole-second UTC strings ending in `Z`.
Numbers preserve engine precision; no application rounding or probability repair is
performed. Negative prices are valid. Step 1 starts at the origin; step 40 starts
9h45m later and ends at origin +10h. Missing optional values become JSON `null`.

Driver text is filtered against an explicit approved-name set, initially only
`last_imbalance_price`. An empty value, unknown name or mixed approved/unapproved list
becomes `null`; arbitrary free text is never echoed. Approved names describe inputs,
not causal explanations or measured importance. Current persistence outputs leave
both optional columns blank. Valid provided cutoff values are preserved, not inferred
from delivery times. The service rejects incomplete or invalid engine results.

There is no automatic model promotion. A separately approved alternative predictor
can be supplied via `prepare_forecast(config, predictor=..., model_id="recipe-v2")`
using the same public `Predictor` contract. Supplying a predictor requires an explicit
recipe label. No new registry or engine signature is needed. Metadata labels come
from application composition and engine provenance, never browser input. The unique
run ID distinguishes preparations even when a recipe label and cutoff are identical;
the response is not a replacement for the engine's detailed experiment manifests.
Source changes detected during preparation invalidate the snapshot.

## Failures and data protection

Preparation either returns a complete validated service or raises
`ForecastPreparationError`. Its message identifies a fixed failure stage and suppresses
raw chained parser/model diagnostics. The service writes no logs and never substitutes
mock forecasts. A future HTTP adapter should handle this safe error, rather than logging
exception context or returning raw exceptions.

For `loading inputs` failures, check paths, private file presence and the engine's
required seven-column source format. For `fitting`/`prediction` failures, run the
synthetic suite and consult the engine's availability/evidence requirements. For an
`engine integrity` failure, stop concurrent engine edits and prepare again from stable
sources. Diagnose locally without dumping source rows or restricted values into logs.

Spot prices are private engine inputs only. The response includes no numerical spot
levels, raw tables, paths, dependency lineage or scoring actuals. The existing
Fingrid/ENTSO-E source licences and Nord Pool restrictions remain those in
[README section 9](../README.md#9-sources-and-licences): do not redistribute restricted
data, and delete it after the event. The smoke test accesses the private retained
engine result for comparison only; that is not a public response API.

One shared root `.gitignore` covers both applications and operating systems. Keep
generated check evidence under ignored `baseline_output/application/`; use synthetic
fixtures in tracked tests. Before committing, inspect staged files and diffs, including
already tracked files. Ignore patterns cannot prevent leaks in tracked content.

## Verification actually performed

Step 1A on Windows, 7 November 2026: Python 3.14.2, pandas 3.1.1, NumPy 2.5.4,
forecast-engine 0.1.0. All 14 backend tests passed, and all 74 unchanged engine tests
passed, with FutureWarnings treated as errors. The backend suite includes a real
engine run on synthetic CSVs from an unrelated directory with space-containing paths.

The separate supplied-data smoke passed: 40 quarters, exact agreement of all eight
forecast values and identifiers with the retained engine result, cached retrieval,
two source CSV reads and zero actuals reads, and unchanged source-file hashes.
Preparation took 54.086 seconds while the engine suite ran concurrently; this is a
local cost observation, not an isolated performance benchmark. Safe evidence is in
`baseline_output/application/step-1a-01/smoke_report.json`.

macOS execution, fresh environment provisioning, HTTP and browser behavior are not
verified in this step. Forecast accuracy is unchanged baseline quality. Step 1B has
not started and requires separate authorization after the review handoff.
