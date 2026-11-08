# Backend: historical forecast service and local HTTP API

The application service loads a saved model (or fits once on a cache miss) and
batch-prepares six genuine historical forecasts,
retaining safe JSON responses for selection through the local API. It uses the
spot-relative LightGBM predictor with the provisional `relative-control-v1` recipe.
Batch prediction happens once at startup; requests reuse cached JSON.
The frontend can select cached origins. Step 5A adds a separate retrospective history
API; the comparison UI is Step 5B.

## Files and responsibilities

| File | Responsibility |
|---|---|
| `app/config.py` | Private source paths and a bounded, validated selection of origins. |
| `app/forecast_service.py` | Load, fit once, predict once, retain the result and serve cached JSON. |
| `app/schemas.py` | Validate the forecast and serialize only approved response fields. |
| `app/actuals.py` | Read only permitted validation-outcome columns, join to cached forecasts and compute retrospective metrics. |
| `app/main.py` | Own FastAPI startup/shutdown, readiness and cached forecast routes. |
| `requirements.txt` | Pin the tested HTTP runtime, serialization stack and test client. |
| `tests/test_forecast_service.py` | Synthetic correctness, lifecycle, privacy and portability checks. |
| `tests/test_forecast_api.py` | HTTP contract, lifecycle, error safety and concurrent retrieval checks. |
| `tests/test_origin_selection.py` | Multi-origin caching, selection, shared identity, query validation and overlapping deliveries. |
| `tests/test_history.py` | Outcome privacy, missing data, metrics, lazy/concurrent loading, history caching and safe failure checks. |
| `tests/smoke_forecast.py` | Explicit real-data acceptance check with value-free output. |
| `tests/smoke_forecast_api.py` | Start a temporary loopback server and verify real HTTP responses against the engine. |

Step 1A required no new dependencies. Step 1B's dependencies are confined to the
backend manifest; root packaging, starter requirements and the engine are unchanged.
The backend is imported from the repository root, not separately installed.

## Setup on Windows and macOS

For ongoing team development, use the shared
[uv environment workflow](../docs/python-environment.md), including its verification
status. It installs engine and backend together with one committed lock. No separate
backend environment or separate dependency installation is needed.

Use the shared Python 3.12 environment and editable engine installation described in
[the engine guide](../docs/forecasting-engine.md). Do not share `.venv` directories
between machines. Both teammates need their own authorized local challenge data.
Do not copy datasets through GitHub.

The default data paths are `<checkout>/data/inputs.csv` and
`<checkout>/data/spot_nordpool.csv`. These remain the engine's only file inputs.
Separate `HistoryConfig` supplies `actuals_validation.csv` for explicit retrospective
requests; no outcome path or data is passed to ForecastConfig or the forecast engine.
Use `ForecastConfig.from_data_dir(...)` for an explicit data directory, or
`ForecastConfig(inputs_path=..., spot_path=...)` for two explicit source files.
Explicit relative paths resolve at configuration time from the caller's directory;
the default paths are independent of the working directory. Paths with spaces work.
The preparation service itself performs no file writes or network requests.

Run commands from the repository root. Windows PowerShell:

```powershell
uv pip sync --python .venv requirements-dev.lock
uv pip check --python .venv
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast --data-dir data
```

macOS:

```bash
uv pip sync --python .venv requirements-dev.lock
uv pip check --python .venv
.venv/bin/python -W error::FutureWarning -m unittest discover -s backend/tests -v
.venv/bin/python -W error::FutureWarning -m backend.tests.smoke_forecast --data-dir data
```

The synthetic suite needs no challenge data and creates only temporary synthetic
files. Synchronize the shared lock first if dependencies changed after a pull.
The Step 1A service tests can still run without HTTP dependencies using
`python -m unittest backend.tests.test_forecast_service -v` in the engine environment.
The smoke command explicitly uses local data and prints a JSON check report
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
printing or external work. Calling `prepare_forecast` loads sources, loads or fits
the default model with `RunConfig.validation()`, and calls public `forecast(...)` for
the configured origins in one batch. Fitting labels end before `2026-09-06T21:00:00Z`,
with publication no later than the cutoff. The engine enforces historical availability; actual outcomes
are never supplied to the service. These are historical forecasts, not live data.

The first preparation can be slow because it includes historical model fitting and
dependency evidence. Retain the returned service; do not call `prepare_forecast` for
each future HTTP request. Each deliberate new call creates a new independent run.
The FastAPI lifespan owns this service; each process/reload prepares again.
One worker is the initial policy. The default model uses private fitted-state
persistence as described below; forecast responses are regenerated rather than read
from an existing CSV.

### Saved model and repeat startup

Normal startup automatically uses
`baseline_output/application/models/relative-control-v1.json`, relative to the checkout.
On the first startup with no cache, the backend fits the current minimal spot-relative
LightGBM model, prepares the forecasts and atomically saves its native heads, direct
backup and complete fitting provenance. Subsequent starts load this state without
training. Start the server using the normal command; no separate build command or
dependency installation is required. The first real-data build still needs time;
it has not been run as part of this change.

The versioned JSON artifact contains private learned numeric state and must stay local
in the already ignored `baseline_output/` folder. Do not commit or share it. Each
teammate builds their own cache using their authorized local data. The loader uses
explicit allowed data types rather than pickle or arbitrary dynamic imports. Load
only artifacts generated by this code; checksums detect damage, not authenticity.

Cache identity includes input/spot content hashes, engine source fingerprint,
Python/library versions, recipe and historical fitting boundaries. The configured
origin selection is independent of fitting, so another allowed origin can reuse the
same model. Changed code, data or versions, damaged JSON, or invalid model state
abort startup with a sanitized preparation stage; they do not trigger a surprise
retrain or fallback. A future engine Python edit, including experiment changes, can
invalidate the cache even if the model algorithm is unchanged.

To deliberately rebuild, stop the backend, delete only the private model file
`baseline_output/application/models/relative-control-v1.json`, then restart normally.
Keep a compatible cache while working on the frontend to avoid repeated fits. A pull
that changes engine sources may require this rebuild. No rebuild is needed merely
because a frontend file changed. Rebuilding is a local training run, so run it in
your terminal rather than asking an agent to monitor it.

For trusted Python composition, `ForecastConfig.model_cache_path` selects a private
cache file; `None` disables persistence. `from_data_dir()` configures the default path,
including for custom data directories; using different contents at that path requires
an explicit rebuild or a separate configured cache path. Explicitly injected predictors
retain their existing fit-on-preparation behavior and do not use the default cache.

Repeat startup still hashes and parses the input files, constructs features, predicts
and verifies provenance. Requests only retrieve cached JSON. No startup-speed factor
or real-data timing has been measured; synthetic checks verify zero fitting on reuse,
exact forecasts/driver labels/lineage, invalidation and safe failure.

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
| `model_id` | Application-selected recipe label, currently `relative-control-v1`. Update it when deliberately selecting a different recipe/configuration. |
| `predictor_id` | The fitted engine predictor's short identifier, currently `lightgbm-relative-v1`. |
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

Driver text is filtered against an explicit approved-name set: the legacy
`last_imbalance_price` input marker and the nine verified P50 categories listed below.
An empty value, unknown name or mixed approved/unapproved list becomes `null`;
arbitrary free text is never echoed. Valid lists retain engine order, with duplicate
identifiers removed. Explicitly selected Persistence outputs leave both optional columns blank.
Valid provided cutoff values are preserved, not inferred from delivery times. The
service rejects incomplete or invalid engine results.

Approved P50 categories: `renewable_production`, `consumption`, `production`,
`cross_border_flows`, `neighboring_markets`, `balancing_conditions`, `historical_prices`,
`spot_price_conditions`, `calendar_horizon`. LightGBM emits up to three nonzero signed
category totals ranked by absolute size, with identifier order breaking ties. These
labels explain P50 only, not spike/direction probabilities or physical causation.
For relative forecasts, the spot category can include the deterministic reconstruction
offset as well as learned effects; it is not exclusively learned SHAP importance.
Numeric contributions, feature values, offsets and model references remain private.
Unavailable or zero-effect explanations remain null. The legacy persistence marker
describes an input and does not claim a measured contribution ranking.

The default spot-relative LightGBM predictor supplies verified category labels through
cached JSON and `/api/forecast`; unavailable explanations remain null. The allowlist
preserves the nullable string response type. Frontend rendering is a separate concern.
Alternative predictors can still use the trusted composition hook. Future category names
require explicit application approval and tests; do not derive the allowlist
automatically from engine internals or permit arbitrary text.

Focused verification for the driver boundary, from the repository root:

```bash
.venv/bin/python -W error::FutureWarning -m unittest backend.tests.test_forecast_service backend.tests.test_forecast_api forecast_engine.tests.test_model_compatibility.ModelCompatibilityTests.test_same_public_caller_and_backend_serializer -v
```

On Windows substitute `.venv\Scripts\python.exe`. The HTTP tests include a genuine
LightGBM relative forecast from small invented CSV inputs when the optional ML setup
is installed. No challenge datasets or full-data training are used. Frontend rendering
is handled separately by the frontend owner.

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
mock forecasts. The HTTP adapter fails startup with a fixed diagnostic, rather than
logging exception context or returning raw exceptions.

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

## Select cached historical forecasts (Step 3A)

The default selection is deliberately limited to these six hourly origins:

| UTC origin | Helsinki origin (UTC+3) |
|---|---|
| `2026-09-06T21:00:00Z` | 7 September 00:00; default |
| `2026-09-06T22:00:00Z` | 7 September 01:00 |
| `2026-09-07T03:00:00Z` | 7 September 06:00 |
| `2026-09-07T21:00:00Z` | 8 September 00:00 |
| `2026-09-13T21:00:00Z` | 14 September 00:00 |
| `2026-10-03T21:00:00Z` | 4 October 00:00 |

This is a small replay selection, not every hourly validation origin. Nearby origins
have overlapping delivery windows; the same delivery can have a different forecast
depending on when it was issued. No origins are selected using realized errors or
actual outcomes. All use `RunConfig.validation()` with the original pre-validation
fitting cutoff. Normal requests only retrieve prepared JSON, even at later origins.

`GET /api/origins` returns exactly these fields:
`schema_version`, `run_id`, `model_id`, `predictor_id`, `engine_revision`,
`generated_at_utc`, `fit_cutoff_utc`, `default_origin_utc`, and `origins` (a sorted
array of UTC strings). Identity fields match every forecast from that preparation.
They identify a shared generation run, not a unique origin; use run ID plus origin
to identify a specific snapshot. Both catalog and forecast responses use `no-store`.

`GET /api/forecast` retains its existing shape and default origin. Add one `origin`
query to select another cached forecast. Whole-second ISO UTC ending in `Z` or
`+00:00` is accepted; minutes and seconds must be zero. URL-encode a literal plus,
or use `Z`. No local/naive timestamp is guessed. Bad syntax, an empty value, duplicate
origin parameters or unknown parameters return sanitized **400**. A valid UTC hour
outside the prepared selection returns sanitized **404**. `/api/origins` and
`/api/health` reject all query parameters. An uninitialized service returns **503**.

For trusted local Python composition, `ForecastConfig.origins` accepts a tuple of
one to six aware full-hour datetimes in
`[2026-09-06T21:00:00Z, 2026-10-04T21:00:00Z)`. Values normalize/sort in UTC;
duplicates and out-of-period origins fail before loading data. The earliest becomes
the default. This is a startup setting, never a client-provided range. Expanding the
six-origin cap requires another measured implementation decision.

`service.response(origin)` and `response_json(origin)` optionally take an aware
datetime; omitted origin retains default retrieval. `origins_response()` returns a
detached catalog. The immutable JSON map is built completely before the service is
published. A missing/invalid engine batch aborts startup; no partial cache is served.

### Test Step 3A without a frontend selector

Restart the backend using the server command above and wait for startup. Open:

1. `http://127.0.0.1:8000/api/origins` — six choices and shared identity.
2. `http://127.0.0.1:8000/api/forecast` — the unchanged default forecast.
3. `http://127.0.0.1:8000/api/forecast?origin=2026-09-06T22:00:00Z` — 40 steps
   starting at 22:00 UTC, with the same run/model identity and original fitting cutoff.
4. Repeat the selected URL — values and generation metadata remain identical.
5. `http://127.0.0.1:8000/api/forecast?origin=bad` — 400.
6. `http://127.0.0.1:8000/api/forecast?origin=2026-09-07T00:00:00Z` — 404,
   because that hour is not prepared. Do not silently substitute a nearby forecast.

Alternatively use `/docs` to execute the two forecast routes and see response codes.
The existing frontend continues to fetch the default; its selector is Step 3B.

Focused synthetic checks, from root:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest backend.tests.test_origin_selection backend.tests.test_forecast_service backend.tests.test_forecast_api -q
```

The existing HTTP smoke now checks every cached origin:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast_api --data-dir data
```

It starts and stops its own temporary loopback server. No full-period forecast export
or actuals access is needed. The older non-HTTP smoke continues to check the default
40-quarter response, even though startup now prepares the full small selection.

Step 3A verification on Windows: all **33 relevant backend tests** passed. The real
HTTP smoke matched all eight prediction fields and identifiers for **240 rows** across
six origins; repeated responses and shared identity matched. One fit, one batch
prediction, two source CSV reads and zero actuals reads were observed, with unchanged
source hashes. Preparation took **30.709s**, startup **30.813s**, and the slowest of
six measured selected-origin HTTP retrievals took **0.022s**. These are local single-run
observations, not a benchmark or a claim of faster calibration than earlier steps.

Serialized forecast/catalog cache: **69,769 bytes**. Forecast DataFrame: **36,612
bytes**. These measurements exclude fitted model state, provenance and total process
memory; they justify keeping this small selection, not scaling to all origins.
Environment: Python 3.12.16, pandas 2.2.3, NumPy 2.3.5 and the shared locked HTTP
versions. Engine revision:
`sha256:657e7ac46031e67662d6dc2b5e64d7d0408dc77cbeda22afc08f7de8865b0fd7`.
Safe report: `baseline_output/application/step-3a-01/http_smoke_report.json`.
macOS, interactive Swagger rendering and a new browser walkthrough remain unverified;
real HTTP and OpenAPI passed. No frontend or engine suite rerun was needed for
unchanged code. Engine change proposals: **None**. Stop for review and Step 3B approval.

## Retrospective validation history (Step 5A)

`GET /api/history?origin=2026-09-06T21:00:00Z` compares one cached forecast with
outcomes revealed afterward. The UTC origin is **required** and must already appear
in `/api/origins`. No arbitrary date range, model, training setting or source path can
be supplied. This route does not train/predict and does not replace official scoring.
The existing forecast envelope and other route behavior remain unchanged.

The first successful explicit history request loads validation outcomes off the event
loop, using exactly `delivery_start_utc`, `imbalance_price`, and `direction` through
`pandas.read_csv(usecols=...)`. No spot column or publication column is materialized.
No outcome read occurs during import/startup or forecast/health/catalog requests.
A lock makes concurrent first requests share one load. Data and per-origin history
JSON stay cached for that lifespan. Restart to refresh a successfully loaded snapshot;
missing/invalid source failures can be fixed and retried without restarting forecasts.

History uses a distinct `HistoryConfig` and immutable `ActualsStore`. Default file:
`<checkout>/data/actuals_validation.csv`; explicit ForecastConfig paths default history
to that inputs directory. With a custom `service_factory`, pass `history_config` when
the private data directory differs from the checkout default. Trusted local example:

```python
create_app(ForecastConfig.from_data_dir("private data"),
           history_config=HistoryConfig.from_data_dir("private outcomes"))
```

Import both configuration classes from `backend.app.config`. The resolved filename
must be `actuals_validation.csv`, never test actuals. Source timestamps must be unique
UTC quarter-hours within `[2026-09-06T21:00:00Z, 2026-10-04T21:00:00Z)`. Offsets
`Z` and `+00:00` are accepted; no naive/local timestamps are guessed. Empty price or
direction fields become null independently; nonempty bad values/duplicates/out-of-
period rows reject the entire load. Negative finite imbalance prices are valid.

Outcomes are matched by delivery timestamp to every one of the forecast's 40 points.
No missing/tail quarter is dropped or filled. Different issue times can share the
same observed delivery while having different forecast errors. Outcomes intentionally
are not filtered as though known at forecast origin: the response explicitly says
`comparison_mode: "retrospective"`. They cannot feed back into the fitted engine or
forecast JSON. No spike outcome is calculated from restricted spot prices.

History response fields:

| Field | Meaning |
|---|---|
| `schema_version`, `run_id`, `model_id`, `predictor_id`, `engine_revision`, `generated_at_utc`, `forecast_origin_utc`, `fit_cutoff_utc` | Exact identity copied from the selected cached forecast. |
| `comparison_mode` | Always `retrospective`; these are outcomes revealed afterward. |
| `actuals_snapshot_id` | UUID for this loaded outcome snapshot, shared across origins; not a content hash. |
| `actuals_loaded_at_utc` | When the server loaded the snapshot, not historical publication time. |
| `points` | Forty ordered records: `delivery_start_utc`, `step`, nullable `actual_imbalance_price`, nullable `actual_direction` (`up`/`down`/`none`). |
| `metrics` | Selected-origin comparison values/counts below; not full validation scores. |

Metrics use available observed **prices**: `mae_p50` is mean absolute P50 error in
EUR/MWh; `coverage_p10_p90` is the fraction within inclusive `[P10,P90]`; both are
null if no prices match. `covered_price_count` is the interval numerator, and
`matched_price_count` its denominator. `total_quarters` is 40;
`missing_price_count = 40 - matched_price_count`. Independent
`matched_direction_count`/`missing_direction_count` describe direction availability.
There is no direction/spike score or official competition-points claim.

Missing/empty/duplicate/unknown query parameters or malformed/non-hourly UTC origins
return safe 400. Well-formed uncached origins return 404 **before outcome loading**.
Missing/invalid validation files return safe 503 for history while forecasts/health
remain available. Unready forecast service also returns 503. Invalid responses or
unexpected errors return sanitized 500, never raw source rows/paths/values. All
responses have `Cache-Control: no-store`; no source-file route exists.

### Test 5A without a comparison UI

Restart the backend with the normal single-worker/no-access-log command. Wait for
startup, then open `/docs`: GET `/api/history` requires the origin text. Or open:

1. `http://127.0.0.1:8000/api/history?origin=2026-09-06T21:00:00Z`
2. `http://127.0.0.1:8000/api/history?origin=2026-09-06T22:00:00Z`

Both return 40 steps, shared forecast run identity/outcome snapshot, and separately
labeled actual values. Compare each with `/api/forecast?origin=...`. Refreshing a URL
keeps identity/values stable while the backend remains running. Check metrics counts
and compare MAE/coverage with the corresponding forecast points and observed prices.

`/api/history` without origin, `?origin=bad` and unknown/duplicate parameters give 400.
`?origin=2026-09-06T23:00:00Z` gives 404 because that valid hour is not cached. Test
nullable/tail cases using synthetic tests; do not edit private challenge files to
manufacture errors. The current frontend has no actual-outcome toggle/overlay yet.

Focused tests from root (no real data):

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest backend.tests.test_history backend.tests.test_forecast_api.ForecastApiTests backend.tests.test_origin_selection backend.tests.test_forecast_service.ConfigurationAndImportTests -q
```

Explicit real-data HTTP acceptance:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast_api --data-dir data --include-history
```

The existing smoke still reads **no actuals** unless `--include-history` is supplied.
With the flag it starts/stops its own temporary loopback server, verifies all six
cached forecasts/history responses and compares outcomes/metrics with an independent
three-column reference read. It does not stop any already running user server or print
prices. The source CSV parser scans a file, but only the three approved outcome columns
are selected into dataframes; no spot field reaches store, comparison or serialization.

### 5A verification actually performed

Windows Python 3.12.16, pandas 2.2.3, NumPy 2.3.5, existing locked HTTP dependencies.
**31 relevant tests passed across focused runs**, including eight new history cases;
no unrelated engine/frontend or optional ML suites rerun. Source tests cover strict
three-column ingestion with an invented restricted sentinel, exact/inclusive metrics,
missing/tail data, overlap, cache detachment/lifetimes, concurrent load, default route
isolation, sanitized failures and required-origin OpenAPI behavior.

Real HTTP smoke passed **240 forecast and 240 history rows** across six origins,
matching every history value/metric against an independent three-column reference.
Application: one actuals load; verifier: one extra reference read. One fit and one
batch prediction remained, with unchanged forecast JSON/input hashes. Outcome cache
and metadata were shared; repeated responses matched. Temporary server shut down.
Preparation was 36.642s, startup 36.754s in this local run, not a performance guarantee.
The older cache-size fields in the report cover forecasts only, not history/outcomes.

Safe report: `baseline_output/application/step-5a-01/http_smoke_report.json`.
Engine revision used:
`sha256:b933f7932aefa2e4edd030291e259a92178d82afd6858b206b9b45a4cf3c0fae`.
Model remains persistence-v1. macOS, interactive Swagger rendering and the not-yet-built
5B comparison UI were not verified. No accuracy improvement claimed. Engine change
proposals: None. Stop for independent review and explicit Step 5B approval.

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

For that Step 1A acceptance, macOS, fresh provisioning, HTTP and browser behavior were
not verified. Its independent review was subsequently approved and the changes were
published by the user. Forecast accuracy remains baseline quality. Step 1B's separate
HTTP checks are recorded below.

## Start the local HTTP server

Use the synchronized shared environment described above. Do not install backend
packages separately, change the starter's root `requirements.txt` or copy `.venv`
to the other machine. Step 3A adds no dependencies.

Windows PowerShell, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

macOS, from the repository root:

```bash
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Keep that terminal open. Wait for `Application startup complete` before requesting
the API. Model loading (or first-time fitting) and forecast preparation happen once during startup. The earlier
startup measurement of about a minute used Persistence; startup time for the new
LightGBM default has not been measured. No interval-calibration step is performed here.
Uvicorn does not serve requests while preparation runs.
Use Ctrl+C to stop. If port 8000 is already in use, stop the other server or choose
another local port and use that port in the URLs.

Open these URLs after startup:

| URL | Result |
|---|---|
| `http://127.0.0.1:8000/docs` | Interactive Swagger API documentation; expand GET and use Try it out / Execute. |
| `http://127.0.0.1:8000/api/health` | `{"status":"ready"}` after successful preparation. |
| `http://127.0.0.1:8000/api/forecast` | The genuine cached 40-quarter historical forecast, including probabilities and run metadata. |
| `http://127.0.0.1:8000/api/origins` | Available UTC origins, default origin and shared model/run identity. |
| `http://127.0.0.1:8000/api/forecast?origin=2026-09-06T22:00:00Z` | The cached forecast issued one hour after the default. |
| `http://127.0.0.1:8000/openapi.json` | Machine-readable API schema derived from the existing response dataclasses. |

The backend root URL `/` returns 404; the frontend runs on its own Vite port. Documentation UI assets use
FastAPI's default external CDN; the API endpoints themselves work locally without
external market-data requests. A blocked CDN can prevent the interactive docs from
rendering while the JSON endpoints still work.

`/api/forecast` accepts one optional `origin` parameter. `/api/origins` and `/api/health`
accept none. No endpoint accepts source paths, training settings or model selection.
Omitting `origin` retains the first validation forecast, not today's date.
No dataset/static-file route, authentication or CORS middleware is
added. Bind only to loopback; the planned Vite proxy will keep browser API calls relative.

Server-side reuse and HTTP caching are separate: the service retains the prepared snapshots,
while responses send `Cache-Control: no-store` so clients do not retain stale snapshots
across restarts. A successful lifespan calls preparation once; requests never fit or
predict. Shutdown clears the service reference. Each independent process/reload starts
a new run. Avoid `--reload` for a stable demo; development reload repeats preparation,
but a compatible saved model prevents retraining.
The documented server command disables access logs to avoid logging client query text.

The route uses the existing `ForecastResponse` dataclass as its response model; there
is no parallel HTTP forecast schema. FastAPI validates/filters the detached response
again at the boundary and documents it in OpenAPI. Startup errors prevent serving;
uninitialized services yield 503 in direct ASGI checks. Invalid responses and unexpected
retrieval errors return fixed 500 messages without echoing/logging offending content.

For trusted local composition with a custom data directory, use
`create_app(ForecastConfig.from_data_dir(...))` from `backend.app.main`. A local
`service_factory` hook supports tests and separately approved predictor composition.
These are Python startup options, never browser parameters. The factory must return
the actual Step 1A `ForecastService`; normal `backend.app.main:app` always prepares the
genuine default predictor. No engine changes or new inference path were needed.

## Test HTTP without a frontend

Run in another terminal from the repository root:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast_api --data-dir data
```

On macOS substitute `.venv/bin/python`. The synthetic suite uses no challenge data.
The HTTP smoke starts one temporary Uvicorn server on an unused loopback port,
prepares the real forecast once, compares the HTTP response to the retained engine
result, tests repeated retrieval and documentation, and stops its own server. It
does not require or stop an already running port-8000 server. It prints only safe
metadata/counts, not individual prices. Source data remains server-side.

The HTTP smoke waits up to 180 seconds for startup by default. For an explicitly
authorized real-data run, allow more time for ML preparation with
`--startup-timeout 1200` (seconds), for example:

```bash
.venv/bin/python -W error::FutureWarning -m backend.tests.smoke_forecast_api --data-dir data --startup-timeout 1200
```

On Windows substitute `.venv\Scripts\python.exe`. The timeout must be finite and
greater than zero; it changes only the smoke script's startup wait, not model settings
or API request timeouts. This example is not a measurement of LightGBM startup time.

HTTP testing uses `httpx2`, the supported client for the pinned Starlette version;
plain `httpx` is deprecated in that TestClient. This choice follows the installed
library and [Starlette's current test-client documentation](https://starlette.dev/testclient/).
The lifespan and dataclass integration follow the
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) and
[dataclass response](https://fastapi.tiangolo.com/advanced/dataclasses/) guides.

| Direct component | Tested version | Package licence |
|---|---|---|
| FastAPI | 0.162.2 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| HTTPX2 | 2.16.0 | BSD-3-Clause |
| Pydantic | 2.14.3 | MIT |
| Starlette | 1.10.0 | BSD-3-Clause |

Licences above come from installed package metadata. Existing engine dependencies
were not upgraded. macOS installation/execution still needs verification.

## Step 1B verification actually performed

Windows, 7 November 2026, using the same Python/engine environment as Step 1A and the
HTTP versions listed above. All 27 backend tests passed (14 existing service tests
plus 13 new HTTP tests), with FutureWarnings treated as errors. All 74 unchanged
engine tests also passed. `pip check`, Python compilation and `git diff --check` passed.
Pre/post hashes confirmed 41 recorded engine, Step 1A, original-tool and ignore files
were unchanged.

The supplied-data HTTP smoke passed through a temporary Uvicorn server on loopback:
all 40 quarters matched the retained engine result, repeated HTTP responses preserved
values/metadata, fit/predict counts were one each, two source CSVs were parsed and zero
actuals were read. Source hashes stayed unchanged. Docs/OpenAPI, unsupported-origin
rejection, absence of a data-file route and server shutdown passed. Preparation took
56.275 seconds and server startup 56.384 seconds; these are local observations, not
performance guarantees. No raw prices were printed. The safe report is under ignored
`baseline_output/application/step-1b-01/http_smoke_report.json`.

macOS, fresh provisioning and interactive browser rendering of Swagger's CDN assets
remain unverified; documentation HTML/OpenAPI were checked over real HTTP. No new
full-period evaluation was needed because forecasting logic is unchanged. Step 1B
awaits independent review; no frontend work, commit, push or merge has been performed.
