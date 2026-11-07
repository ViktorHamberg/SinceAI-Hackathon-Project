# Application: incremental implementation plan

**Status: Steps 1A and 1B passed independent review and were published by the user.
Step 2 is now split into 2A (API connection and table) and 2B (chart).
Steps 2A and 2B were approved and published by the user. Step 3 is split into 3A
(backend selection/cache) and 3B (browser selector). The user authorized 3A on
7 November 2026; its implementation and verification limits are recorded below.
Step 3B and later work require separate approval. The user confirmed on
7 November 2026 that engine Step 6
passed independent review and was published to GitHub. Older engine documents still
describe that review as pending; this plan records the update without editing them.**

This plan follows the stepwise approach of
[the forecasting-engine plan](first-forecasting-engine-plan.md). The application
developer owns `backend/` and `frontend/`; the other developer continues engine and ML
work independently. [README.md](../README.md) remains the official technical source;
[AGENTS.md](../AGENTS.md) supplies project constraints and supplementary judging context.
The review workflow actually resides at [docs/REVIEW.md](REVIEW.md), rather than the
root path mentioned in AGENTS.md.

## Scope and first milestone

Build a local decision-support application using Python/FastAPI, TypeScript/React/Vite,
plain CSS files and JSON REST. Step 2B uses Recharts with a true range band and
application-owned selection. Steps 1A, 1B and 2A connect one genuine
40-step forecast to a browser table; Step 2B adds a p50 line and p10–p90 band at that
fixed historical origin. The first usable application milestone
finishes after Steps 3–4: select a historical origin and inspect its forecast,
uncertainty and risk probabilities. Steps 5–6 add retrospective outcomes and final
usability/demo refinement.

Steps 1 and 2 are split into independently checked and approved halves. Step 3 adds
origin selection separately from Step 5's actual-outcome comparison. Each step or
half ends with a short explanation of what now works, actual checks, a reviewer
handoff and a stop for explicit approval. Later steps can be split further before
implementation if their scope is too large for one clear checkpoint.

No database, authentication, cloud deployment, extra backend language, live market-data
service or new forecasting algorithm is included. This application does not replace
the official CSV validation/scoring workflow or complete the other submission
deliverables. Better presentation does not establish better forecast accuracy.

## Fixed constraints for every step

- Treat `forecast_engine` as an independent dependency. Application work must not edit
  `src/forecast_engine/`, its public interfaces, engine tests, original starter files,
  root packaging or unrelated shared code. Use only public exports and documented
  predictor entry points. Record missing capabilities and practical application-side
  adapters in `backend/README.md`; propose engine improvements through the standing
  coordination protocol below and coordinate implementation as separate work.
- Keep dependencies and tooling application-local: `backend/requirements.txt` and frontend
  package/lock files. Use the shared root `.gitignore`, as agreed by the user, for both
  applications and operating systems. Preserve the starter `requirements.txt`.
  Use the existing Python environment. Choose compatible dependency versions and record
  actual setup results during implementation; none are installed by this plan.
- Keep responsibilities small: FastAPI owns HTTP and lifecycle; an application service
  owns engine calls and cached results; explicit response models own serialization;
  React owns fetching, interaction and display. Do not introduce repository layers,
  plugin frameworks, background queues or generic model registries.
- Select a predictor at backend startup behind the existing `Predictor` /
  `FittedPredictor` contract. Initially use the documented `PersistencePredictor`.
  Load inputs and fit once per process lifecycle, then call public `forecast(...)`.
  There is no documented fitted-model save/load API: do not invent or depend on one.
  Use one backend worker initially; development reload restarts the lifecycle.
  Startup generation and in-memory caching are the initial integration approach:
  cached forecasts are precomputed before requests, but are regenerated on restart.
  This does not load existing forecast CSVs or persist fitted models. Record startup
  cost and reassess this approach when adopting a more expensive model; loading a
  validated forecast artifact with matching run metadata is a possible later adapter,
  not an additional implementation requirement for these first checkpoints.
- Start with `RunConfig.validation()` and origin `2026-09-06T21:00:00Z`, the first
  validation origin and the documented application example. Fitting label deliveries
  are `[2026-05-31T21:00:00Z, 2026-09-06T21:00:00Z)` with publication no later than
  the cutoff. Never use the later test-fit configuration to review validation origins.
  Preserve the engine's availability rules and frozen fitted state. No request fits a
  model, and actual outcomes never enter prediction inputs.
- Keep all 40 rows, including deliveries without actuals. Step 1 starts at the origin;
  step 40 starts 9 hours 45 minutes later and ends at origin + 10 hours. Transport
  timezone-aware ISO UTC timestamps with `Z`; convert only for display. Label the
  origin separately from deliveries and from backend generation time.
- Restricted spot data may be read privately by the engine, but must never appear in
  responses, UI, logs, test snapshots, screenshots or exported artifacts. Do not expose
  raw source tables, actuals files, DataFrames or full provenance objects. Use explicit
  response field allowlists and sanitized errors; do not log payloads or raw parser
  exceptions. Do not add spot charts or spot-relative numeric price levels.
- Keep data server-side under ignored `data/`. Keep any private generated evidence
  under already ignored `baseline_output/application/`; do not copy data into Vite's
  public directory or bundle it. Use synthetic fixtures in tracked tests. The shared
  ignore file must cover dependency/build/test outputs. Follow README licence and
  deletion rules; do not redistribute restricted source values through derived views.
- Bind the unauthenticated app to loopback. Use a Vite `/api` proxy to the local backend,
  keeping browser calls relative and avoiding unnecessary CORS configuration. No
  static file route may serve datasets or arbitrary filesystem paths.
- Include readable units, labels, keyboard access and non-colour cues as relevant
  components are introduced. The final usability step refines these; it does not
  defer basic accessibility until the end.
- Keep engine and application work on separate branches/checkouts where practical.
  Record the tested engine revision in each handoff and recheck integration when it
  changes. Future models may change values; application acceptance must test contract
  and provenance compatibility rather than fixed baseline numbers.

## Standing engine coordination protocol

Apply this protocol to every implementation step. When application work reveals a
missing engine capability or a useful improvement, propose it explicitly. The engine
boundary prohibits executing changes, not identifying or recommending them. Do not
modify the engine package, its public interfaces or engine tests in this workflow.

Present a concise, self-contained notice that can be copied to the engine developer:

```text
ENGINE CHANGE PROPOSAL
Application need and concrete example: ...
Proposed engine improvement and likely affected components: ...
Would the existing public integration contract change? ...
Application-side workaround and its limitations: ...
Expected benefit, compatibility risks and verification needed: ...
Recommended coordination or migration steps: ...
Can application work continue independently? ...
```

Continue with a practical application-side adapter within the approved scope where
possible. If the missing capability blocks the approved step, report the blocker and
wait for coordination before dependent work; continue independent work where practical.
Do not build substantial workarounds that expand the approved scope without approval.

A proposal does not authorize implementation. Engine changes belong to the separate
engine workflow and require the user's explicit authorization there. Coordinate the
tested engine revision and any migration before adopting the resulting change in the
application; preserve the existing integration until that work is approved and verified.

## Step 1A. Prepare one genuine forecast and its safe JSON response

**Objective and implementation:** Establish the backend's application-side service,
configuration and explicit response schema/serialization. An explicit initialization
call loads private CSV inputs/spot using `load_inputs`, creates the predictor, fits
with `RunConfig.validation()`, and generates the fixed origin through
`forecast(fitted, data, origins=[origin])`. Retain the fitted object, validated result
and prepared response in the service. Importing modules must not load or fit data.
This half has no web server, HTTP routes or frontend.

Define a JSON response containing a forecast origin, fit cutoff, predictor identifier
and 40 ordered points. Point fields preserve the 13 official names; absent
`data_cutoff_utc` and `top_drivers` become JSON `null`. The API
envelope is application-owned and does not change the engine/CSV contract. Serialize
finite numbers and UTC strings without rounding prediction values. Expose only safe
metadata; omit raw dependency lineage and source values. Include the probability
fields now even though Step 2 initially displays only prices. Treat future nonempty
free-text `top_drivers` as untrusted: expose only approved driver names, otherwise
return null.

**Implementation detail to resolve in this half:** Specify how responses identify the
model/configuration and generation run, and distinguish generation time from historical
forecast time. Candidate envelope fields are `schema_version`, `run_id`, `model_id`,
`engine_revision` and `generated_at_utc`, alongside the predictor, origin and fit cutoff.
Record final names and meanings in `backend/README.md` and test them before Step 1B
exposes the response. A predictor name and fit cutoff alone do not identify a run.
Repeated retrieval of one cached result must preserve its identity and generation
timestamp. This is a small application-owned decision to complete during Step 1A,
not an outstanding roadmap blocker or a request to change the engine interface.

Initialization failures produce sanitized diagnostics; never substitute fabricated
predictions. Document explicit initialization, configured input paths, fixed origin,
measured preparation cost and troubleshooting in the backend guide. Declare only
dependencies needed for this half in `backend/requirements.txt`, if any beyond the
existing engine environment; defer HTTP runtime/test dependencies to Step 1B.

**Expected new files:** `backend/__init__.py`,
`backend/app/{__init__,config,forecast_service,schemas}.py`,
`backend/README.md`,
`backend/tests/{__init__,test_forecast_service}.py`, and `backend/requirements.txt`
only if a new serialization dependency is needed.
No existing engine files change. Updating the shared root `.gitignore` is the user's
explicitly approved exception for ignore-rule maintenance.

**Verify:** Use standard-library unittest for full 40-step JSON shape, UTC arithmetic,
null conversion, probability/quantile validity, run metadata, repeated service retrieval
without additional fit/predict calls, and sanitized initialization failures. Synthetic
fixtures isolate service/serialization checks; a separate local smoke must call the
real engine with supplied data and compare all required JSON prediction values and
identifiers against the retained engine result. Test that restricted fields and
sentinel source values cannot pass response serialization or error logging. Check
import does not initialize the engine.

**After this half:** One real historical forecast can be prepared and retrieved as a
safe JSON-compatible response through Python. The service is tested before adding HTTP.

**Acceptance criteria:** Real-data preparation succeeds and returns exactly 40 complete
steps with documented identity metadata. Repeat retrieval reuses one fit and one cached
prediction per service initialization. No actuals are loaded. Safe errors and privacy
checks pass. Record actual checks, engine revision and preparation time. Stop for
review and explicit Step 1B approval.

### Step 1A result and verification

Implemented the config, forecast service and explicit response schema under
`backend/app/`, with synthetic tests, an explicit real-data smoke command and
`backend/README.md`. No new dependency or HTTP/frontend code was added. The shared
root `.gitignore` now covers `results/`, Python test/coverage outputs and frontend
dependency/build/coverage outputs. No nested ignore file was created. Original engine
sources, external tests, packaging and challenge tools remain unchanged.

Identity is resolved: application schema version, a UUID per preparation, an explicit
model recipe label, predictor identifier, engine source fingerprint, generation time,
historical origin and fitting cutoff. Retrieval preserves metadata and returns detached
JSON containers. Driver text uses an explicit approved-name list; raw sources and full
provenance are never response fields. See the backend guide for exact meanings.

Windows verification on 7 November 2026 used Python 3.14.2, pandas 3.1.1, NumPy 2.5.4
and forecast-engine 0.1.0:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast --data-dir data
git diff --check
```

All 14 new backend tests and all 74 unchanged engine tests passed. The real-data smoke
passed with 40 quarters matching all required engine values/identifiers, cached
retrieval, two source CSV reads, zero actuals reads and unchanged source hashes.
Preparation took 54.086 seconds while the engine suite ran concurrently; this is not
an isolated performance benchmark. Safe smoke evidence is local under ignored
`baseline_output/application/step-1a-01/smoke_report.json`.

The backend suite also checks import isolation, restricted-value/error filtering,
invalid-output rejection, alternative-predictor compatibility and a real engine run
on synthetic CSVs from an unrelated directory with paths containing spaces. macOS,
fresh provisioning, HTTP and browser checks remain unverified. No improved accuracy
is claimed. **Engine change proposals: None.** Stop for independent review and explicit
Step 1B approval; no commit, push or merge is authorized.

## Step 1B. Serve the prepared forecast through FastAPI

**Objective and implementation:** Add the HTTP adapter around Step 1A's tested service.
FastAPI lifespan initializes the service once and retains it in application state.
`GET /api/forecast` returns its cached, explicitly allowlisted response;
`GET /api/health` reports safe readiness status. No handler loads source data, fits,
predicts or runs official tools. Importing the app must not initialize the engine.

Startup failure prevents forecast serving and produces a sanitized diagnostic. Declare
compatible FastAPI, server and HTTP test dependencies in `backend/requirements.txt`.
Extend the backend guide with verified installation, loopback binding, single-worker
execution, reload behavior and HTTP troubleshooting. Reuse Step 1A's response contract
and serialization rather than introducing a second competing response definition.

**Expected new files:** `backend/app/main.py`, `backend/tests/test_forecast_api.py`,
and `backend/requirements.txt` if not already needed in Step 1A. Modify only the
backend service/schema integration, backend guide and dependency manifest as needed.

**Verify:** Use unittest plus FastAPI's test client and its declared HTTP test dependency.
Check forecast/readiness routes, the complete response contract, sanitized startup
failure and repeated requests without extra fit/predict calls. Reuse Step 1A's lower-level
checks. A real-data HTTP smoke must compare returned identifiers and all eight forecast
fields against the service's retained engine result, and inspect responses/errors for
restricted data. Verify import remains free of engine initialization.

**After this half:** A locally runnable JSON backend serves one real historical
forecast, ready for the frontend.

**Acceptance criteria:** A real-data startup succeeds, `/api/forecast` returns exactly
40 complete steps, and repeat calls reuse one fit and one cached prediction per
lifecycle. No actuals are loaded. Safe errors and privacy checks pass. Record actual
checks, engine revision and startup time; make no performance claim in advance.
Stop for review and explicit Step 2 approval.

### Step 1B result and verification

Added `backend/app/main.py`, `backend/requirements.txt`,
`backend/tests/test_forecast_api.py` and `backend/tests/smoke_forecast_api.py`.
Updated the backend guide with Windows/macOS installation, single-worker loopback
startup, endpoint/docs usage, supported response behavior and component licences.
No Step 1A service/schema/config change, engine change or additional ignore file
was needed. Dependencies were installed only into the existing project environment;
the original requirements and packaging remain unchanged.

The app factory declares HTTP behavior without preparing the engine on import.
Lifespan prepares the genuine service once, off the event loop, and clears its state
on shutdown. GET `/api/forecast` reuses the existing `ForecastResponse` dataclass for
response validation/OpenAPI and returns the cached data. GET `/api/health` reports
readiness only. Responses have `Cache-Control: no-store`; unsupported query parameters
return 400 rather than silently pretending origin selection works. Startup/response
failures expose fixed diagnostics. No data-file route or CORS middleware was added.

Windows checks on 7 November 2026 used Python 3.14.2, pandas 3.1.1, NumPy 2.5.4,
FastAPI 0.162.2, Uvicorn 0.54.0, HTTPX2 2.16.0, Pydantic 2.14.3 and Starlette 1.10.0:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast_api --data-dir data
.\.venv\Scripts\python.exe -m compileall -q backend
git diff --check
```

All 27 backend tests (14 existing plus 13 HTTP) and all 74 unchanged engine tests
passed. Pre/post hashes confirmed 41 recorded engine, Step 1A, original-tool and
ignore files unchanged. The HTTP tests cover lifespan readiness/cleanup, concurrent retrieval, safe
startup/retrieval/validation failures, response filtering, import isolation, query
rejection and docs/OpenAPI. The real-data smoke started a temporary loopback Uvicorn
server and passed exact 40-quarter HTTP/engine agreement, repeated-response equality,
one fit/predict per startup, two source CSV parses, zero actuals reads, unchanged input
hashes, docs/OpenAPI, unavailable file routes and shutdown. Preparation was 56.275
seconds; server startup was 56.384 seconds. These are local observations. Safe evidence:
`baseline_output/application/step-1b-01/http_smoke_report.json`.

macOS, fresh provisioning and interactive browser rendering remain unverified.
HTTPX2 follows the pinned Starlette version's supported TestClient; plain HTTPX is
deprecated there. Direct HTTP/serialization packages are pinned; transitive dependency
versions are recorded in private evidence rather than claimed fully locked.
**Engine change proposals: None.** Stop for independent review and explicit Step 2
approval. No frontend, commit, push or merge is authorized by these results.

## Step 2A. Connect the browser and display the forecast table

**Objective and implementation:** Create the Vite React/TypeScript frontend with
styles in actual CSS files, as requested by the user. Fetch `/api/forecast` through
the development proxy. Define
application-owned TypeScript response types and validate essential response shape at
the boundary so malformed or incomplete data produces an error state.

The user's visual reference is Turku Energia's website: a white background, charcoal
text and restrained warm-orange accents, with supporting colours only where useful.
Use our own clear layout and prioritize simple controls, readable values and solid
functionality. Add no chart dependency or empty chart placeholder in this half.

Show all 40 quarters in an accessible table, with exact p10/p50/p90 values, EUR/MWh
units, origin, full ten-hour window, historical replay status and model/run identity.
Keep optional details collapsible. Use explicit Europe/Helsinki offsets with a visible
Helsinki/UTC switch, retaining UTC instants as row keys. Include loading, sanitized
network/HTTP/malformed-response errors, timeout and retry. Clear previous data during
reload; ignore cancelled/stale responses. Never use a runtime mock fallback.

**Expected new files:** `frontend/{package.json,package-lock.json,.nvmrc,index.html,
vite.config.ts,tsconfig.json,README.md}`, `frontend/src/{main.tsx,App.tsx,App.css,
index.css,favicon.svg,time.ts}`, `frontend/src/api/forecast.ts`,
`frontend/src/components/{ForecastTable.tsx,ForecastTable.css}`, focused API/App/table/
time tests and `frontend/src/test/` setup/synthetic fixtures. Backend/engine code and
the public API contract remain unchanged. Existing root ignore rules cover outputs.

**Verify:** Run frontend tests, TypeScript checking and production build. Test negative
prices, all 40 rows, response rejection, reload/retry, cancelled requests, midnight and
the repeated Helsinki hour on 25 October. Run the existing backend tests. Open the real
backend/frontend, inspect displayed values, units, metadata and browser requests; check
desktop/narrow widths and keyboard navigation. State any browser verification limits.

**After this half:** A genuine forecast is readable in the browser. Stop for independent
review and explicit Step 2B approval. This does not authorize a chart or later features.

**Acceptance criteria:** Document reproducible Windows/macOS setup with a lockfile;
verify on available systems and state untested platforms. All 40 rows are accessible,
the UI preserves values and UTC identity, and failures never present stale/partial data
as the requested forecast. No source datasets or actuals enter client assets or HTTP.

### Step 2A result and verification

Implemented the frontend files above using React 19.3.1, Vite 8.3.6 and TypeScript
7.0.2. Dependency versions are pinned and the npm lockfile is included. CSS remains
in three CSS files; Tailwind and chart dependencies were not added. The current
table will remain the accessible exact-value view when Step 2B adds the chart.
The API boundary rejects unsupported structure, incomplete horizons, invalid values
or timestamps; errors show fixed messages. Request cleanup cancels/ignores stale
responses, and reload clears the previous view. Backend/engine code is unchanged.

Windows checks used Node 24.13.0, npm 11.6.2 and the existing Python 3.14.2 environment:

```powershell
# From frontend/:
npm.cmd ci --offline --no-audit --no-fund
npm.cmd run test -- --run
npm.cmd run typecheck
npm.cmd run build
# From the repository root:
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s backend/tests -q
git diff --check
```

All 34 frontend tests and 27 backend tests passed. TypeScript checking and production
build passed, including another build/test run after clean lockfile installation from
the local npm cache. Synthetic tests cover precise/negative prices, all 40 quarters,
malformed responses, HTTP/network/JSON failure, timeout/cancellation, retry, stale
responses, midnight and repeated Helsinki-hour offsets.

A real backend on an author-owned port 8001 was checked through both Vite development
and production-preview proxies. Direct, proxied and repeated forecast bodies were
byte-identical; each contained 40 points and no restricted spot/actuals fields.
Attempts to retrieve data files yielded denial, 404 or the frontend HTML fallback,
never dataset bytes. Built HTML, CSS, JavaScript and the local icon loaded successfully.
Brave rendered all 40 real quarters, Helsinki labels and the full ten-hour window;
the final production preview console showed zero messages. An initial development
favicon 404 was corrected with the local SVG icon.

Pre/post hashes confirmed 52 engine/backend/original-tool/config files unchanged.
The shared root ignore rules cover dependencies, build/test outputs, secrets and data;
no ignore edit was needed. Safe private evidence and review handoff are under
`baseline_output/application/step-2a-01/`. The real backend reported engine revision
`sha256:437e2978eeba10a2eb61a08bb22a3cf5c6387e3ba5cf928b072f0c2fa386d639`.

macOS and fresh online provisioning were not verified. Browser-access automation was
unavailable; desktop Brave was used instead. A complete browser Network-panel audit,
narrow-width walkthrough and keyboard-only/retry walkthrough remain manual checks
for the user/reviewer; automated component/HTTP checks do not replace those checks.
The engine suite was not rerun for this frontend-only change; backend tests and real
integration passed, and engine sources/tests were unchanged. No forecast-accuracy
improvement is claimed. **Engine change proposals: None.** Stop for independent review
and explicit Step 2B approval; no commit, push or merge was performed.

The subsequent authorized visual redesign added the visible Helsinki/UTC switch and
increased the frontend suite to 37 passing tests. Independent review found no concrete
implementation defect but blocked on incomplete browser verification. The user then
confirmed that those manual checks worked, approved Step 2A and published it. The
34-test results above describe the earlier candidate, rather than the final redesign.

## Step 2B. Add the price chart and uncertainty band

**Objective and implementation:** Reuse Step 2A's API module, time helpers, request
states, page layout and accessible table. Select the chart library against required
interactions. Recharts was selected during this step. Keep styling in CSS files.

Render p50 as a line and p10–p90 as an interval over all 40 delivery quarters, with
EUR/MWh units, legend and an exact-value inspection strip. Use a range area or equivalent band
that remains correct for negative prices; a zero-based stacked area must not distort
the interval. Preserve quarter-hour values and avoid smoothing that implies additional
forecasts. Show forecast origin, historical replay label and the full ten-hour window.
Default labels to `Europe/Helsinki` with explicit timezone/offset; retain UTC instants
as chart keys and offer UTC in the inspection strip. The user's machine timezone must not change
which forecast is shown. Include loading, API failure, malformed response and retry
states; stale charts must not appear to represent a newly requested result.

**Expected new files:** `frontend/src/components/{ForecastChart.tsx,ForecastChart.css}`
and focused chart tests. Modify App/styles, package/lock files and the frontend guide
as needed. Preserve the table as the accessible exact-value view.

**Verify:** Reuse the existing frontend test setup. Check chart interaction,
negative and crossing-zero bands, origin/delivery labels and timezone formatting.
Use synthetic fixtures for component tests, including the repeated Helsinki hour on
25 October and dates crossing midnight. Run TypeScript checking and production build.
Manually open the real backend/frontend together and confirm 40 points and selected values
agree with the API, with no console errors. Network inspection must show no restricted
spot fields or data-file requests. Automated fixtures do not replace this real smoke.

**After this step:** The connection checkpoint is complete: one genuine engine forecast
is visible in the browser, with median, uncertainty, correct times and usable failure
states. Origin selection and risk display remain Steps 3–4 of the first usable milestone.

**Acceptance criteria:** A teammate can follow the local guides to reproduce the
browser view. All 40 quarters remain accessible; the interval handles negative values;
the origin and delivery window are unambiguous. The normal application path uses the
real endpoint, without hardcoded predictions or a mock fallback. Tests/build and real
browser verification pass, with any environment limits stated explicitly.

### Step 2B implementation and verification

Follow-up authorized axis polish: price ticks now use evenly spaced round values
(for the current forecast: -100, -50, 0, 50, 100), with outward-rounded bounds.
All 55 frontend tests, TypeScript/build and `git diff --check` passed after this change.
The 54-test and HTTP evidence below describe the earlier candidate; forecast values
and request behavior are unchanged. The user confirmed quarter bounds, Previous/Next
and supplied desktop screenshots before this axis adjustment.

Added `src/components/ForecastChart.tsx` and its CSS, `src/forecastChart.ts`, a
chart-only `ChartBoundary.tsx` and focused tests under `frontend/`. App mounts the
chart above the existing table using a separate lazy-loaded chunk. Updated package/
lock files, App tests/styles, synthetic resize setup, time formatter caching and the
frontend guides. Backend, engine, API contract and original challenge files are
unchanged. Recharts 3.10.1 and matching React Is 19.3.1 are pinned; both are MIT licensed.

The median and true P10-to-P90 range use step-after geometry, including negative and
crossing-zero prices. A final range rectangle and median segment cover quarter 40's
complete duration without adding a 41st forecast. Selection works through hover,
click/tap, Left/Right/Home/End and native Previous/Next buttons. A persistent strip
shows exact prices and full delivery start/end timestamps. This deliberate alternative
to floating tooltips keeps values visible on narrow screens. React owns one selection
state; Recharts' built-in interaction layer is disabled. Chart interactions make no
new data request, and there is no chart animation. If plotting fails, the table remains
available. Timezone switching changes presentation only.

Windows verification used Node 24.13.0, npm 11.6.2 and the shared Python 3.12.16
environment (pandas 2.2.3, NumPy 2.3.5). Commands actually run include:

```powershell
npm.cmd --prefix frontend ci --offline --no-audit --no-fund
npm.cmd --prefix frontend run test -- --run --reporter=json --outputFile=../baseline_output/application/step-2b-01/frontend-tests.json
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend ls --depth=0
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest discover -s backend/tests -t . -q
git diff --check
```

All 54 frontend tests and 27 backend tests passed. The build includes TypeScript
checking and passed without a large-chunk warning: main JavaScript is approximately
73 KB gzipped and the separately loaded chart approximately 105 KB gzipped. A clean
lockfile installation from the npm cache passed. Synthetic checks cover all 40
keyboard selections, mixed input methods, touch taps/swipes, bounded controls,
midnight/DST offsets, negative/crossing-zero SVG geometry, final-quarter duration and
chart failure isolation. The synthetic layout dimensions do not verify real responsive
layout or browser scrolling performance.

A real backend on port 8001 and production preview on 4174 passed HTTP integration.
Direct and proxied responses were byte-identical. The frontend parser accepted all
40 points, and its chart adapter retained all 120 price values exactly across the
full ten-hour span without mutating the response. Built assets returned HTTP 200.
The backend reported engine revision
`sha256:657e7ac46031e67662d6dc2b5e64d7d0408dc77cbeda22afc08f7de8865b0fd7`.
No restricted spot field was present. Private evidence and the review handoff live
under ignored `baseline_output/application/step-2b-01/`.

Calculated contrast checks passed for the changed plot's specified color pairs,
including the interval boundary against its fill (4.57:1). This does not establish
overall accessibility conformance. Browser automation reported that its access host
was unavailable, so real visual/keyboard/touch verification, narrow/intermediate widths,
200% zoom, console/Network inspection and scrolling performance remain manual checks.
The Anti Slop browser gate has no overall PASS. macOS and a fresh online install were
not verified. The full engine suites were not rerun for this frontend change.
No forecast-accuracy improvement is claimed. **Engine change proposals: None.**
Stop for independent review and explicit approval before Step 3; no Git write is
authorized by this result.

## Step 3. Select historical forecast origins

Implement this step in two separately reviewed halves, as agreed with the user.
Step 3A is authorized; Step 3B requires explicit approval after the backend handoff.

### Step 3A. Backend origin selection and caching

**Objective and implementation:** Extend the service to a bounded selection of validation
origins from 7 September–4 October, using the existing validation-fitted predictor.
Support `GET /api/forecast?origin=...` and `GET /api/origins` with a small documented
allowlist initially; expand only if measured startup/memory cost permits. Generate/cache
that bounded set during startup through the existing batch API and reuse it for requests.
Preserve the documented run/model identity and return the selected historical origin.
Reject unsupported, naive or non-hourly origins safely; never accept client filesystem
paths, arbitrary training dates or model parameters. No actuals are loaded in this step.

Keep the existing no-query forecast response and its default origin compatible with
the current frontend. Return an explicit origin catalog with shared generation/run
identity. Configuration and query validation must reject unsupported selections
without echoing user input or accepting paths/model/training settings.

**Files:** Add `backend/tests/test_origin_selection.py`. Modify backend
config/service/routes/schemas, affected service/API tests, existing smoke commands,
the backend guide and this roadmap. No frontend, engine or dependency changes.

**Verify:** Check allowed/invalid origins, complete horizons, exact UTC selection,
overlapping delivery windows and stable shared metadata. Count fit/predict calls to
prove selection only retrieves cached results. Real-data smoke compares a small set
of API forecasts against the engine and verifies repeated retrieval and stable metadata.

**After this half:** The API lists a small set of origins and serves each complete
cached forecast. Users can test it through JSON URLs or Swagger without a selector.

**Acceptance criteria:** Only allowed validation origins are selectable, all use the
correct pre-validation fit, and each returns 40 steps. Selection does no fitting or
prediction; times, metadata and safe failure states remain unambiguous. Record startup
and cache size, then stop for review and explicit Step 3B approval.

### Step 3A result and verification

Default configuration now contains six origins at offsets 0, 1, 6, 24, 168 and 648
hours from the first validation origin. The last is 4 October 00:00 Helsinki time.
This is a documented small selection, not the complete validation range or an
outcome-selected showcase. One `RunConfig.validation()` fit and one public batch
`forecast(...)` generate all 240 rows during startup. Each 40-row result retains its
original inference evidence when serialized. The complete immutable cache and catalog
publish only after successful validation and engine-source integrity checks.

`GET /api/origins` returns sorted UTC strings, the default and shared safe identity.
`GET /api/forecast?origin=...` accepts one whole-hour UTC origin from that catalog.
Omitting the parameter retains the current default envelope/40 points, so the existing
frontend remains compatible. Bad/duplicate/unknown query parameters return 400;
well-formed uncached origins return 404. No client range or generation endpoint exists.
The six-origin startup cap prevents accidental full-period preparation. Dates outside
validation, naive/non-hourly timestamps and duplicate UTC instants cannot be configured.

All **33 relevant backend tests** passed with FutureWarnings treated as errors:

```powershell
.\.venv\Scripts\python.exe -W error::FutureWarning -m unittest backend.tests.test_origin_selection backend.tests.test_forecast_service backend.tests.test_forecast_api -q
.\.venv\Scripts\python.exe -W error::FutureWarning -m backend.tests.smoke_forecast_api --data-dir data
git diff --check
```

The real-data HTTP smoke matched every identifier and all eight numerical fields
against the engine's retained 240-row batch, with stable repeated responses and shared
run metadata. It observed one fit, one batch prediction, two source reads, no actuals
reads and unchanged source hashes. Default retrieval, selection, bad/uncached origins,
OpenAPI/docs HTML, unavailable data routes and temporary server shutdown passed.
Preparation was **30.709s**, startup **30.813s** and the maximum of six measured
selected-origin HTTP retrievals **0.022s** in this one local run. Serialized JSON cache
and catalog occupy **69,769 bytes**; the forecast table **36,612 bytes**. These size
measurements exclude fitted state, provenance and process memory. No scaling or
performance improvement claim follows from them.

Windows environment: Python 3.12.16, pandas 2.2.3, NumPy 2.3.5; locked HTTP dependencies
unchanged. Engine revision:
`sha256:657e7ac46031e67662d6dc2b5e64d7d0408dc77cbeda22afc08f7de8865b0fd7`.
Safe evidence and the handoff are under ignored `baseline_output/application/step-3a-01/`.
macOS and a fresh interactive browser/Swagger walkthrough were not verified. Frontend
and engine suites were not rerun because their code is unchanged; backend compatibility
and real HTTP passed. No accuracy improvement is claimed. **Engine change proposals:
None.** Stop for independent review and explicit Step 3B approval. No Git write.

### Step 3B. Browser origin selector and integration (not yet authorized)

Add a keyboard-accessible `OriginSelector.tsx` and CSS, using 3A's catalog. Selecting
an origin retrieves its cached forecast and updates chart, table and metadata. Reuse
the existing API/time helpers. Cancel/ignore stale responses when selection changes;
loading/errors must not present the previous chart as a newly requested result.
Define/reset chart-quarter selection explicitly when the selected origin changes.

Modify frontend API/types/App/chart and the frontend guide as needed, with focused
selection/race tests. Verify real API integration, exact UTC identity, overlapping
delivery windows, keyboard/narrow-screen use and recovery. Requests must retrieve
cached results only. The backend contract is already established by 3A.

After 3B, users can move between real historical forecasts in the browser. Stop for
independent review and explicit Step 4 approval.

## Step 4. Add direction, exceptional-price probabilities and risk summaries

**Objective and implementation:** Display the already supplied `p_up/p_down/p_none`
and `p_spike_high/p_spike_low` by delivery quarter, sharing the price chart's time axis
and selection. Explain that direction means dominating balancing regulation, and
spikes mean strictly above spot + 50 EUR/MWh or below spot − 50 EUR/MWh. This definition
does not require exposing spot values.

Add simple situational summaries computed from the returned forecast: maximum
per-quarter high/low spike probability and its delivery time, widest p10–p90 interval,
and the direction with highest probability for a selected quarter. Show ties and flat
forecasts honestly. Label these as forecast summaries rather than trading advice or
model explanations. Do not interpret the maximum as the probability of any event
across ten hours, or sum correlated per-quarter probabilities into a horizon risk.
Avoid arbitrary red/green thresholds; any later alert rule needs a visible definition
and separate justification. Compute display summaries in frontend functions without
adding backend endpoints or duplicating model logic.

**Expected new files:** `frontend/src/components/{ProbabilityChart,RiskSummary}.tsx`,
`frontend/src/forecastSummary.ts` and focused tests. Modify `App.tsx`, frontend styles,
chart selection handling and `frontend/README.md` as needed; API contract stays stable.

**Verify:** Synthetic cases cover ties, constant probabilities, boundary probabilities,
interval widths and percentage formatting. Check 0–100% axes, direction totals, shared
selection/time labels and separate high/low events. Verify real engine values are
displayed unchanged and no numerical spot price or implied threshold price is exposed.

**After this step:** Users can inspect balancing direction and exceptional-price risk
and find the quarters with the largest predicted risk or uncertainty for a selected
origin. The first usable application milestone is complete.

**Acceptance criteria:** Summaries trace to specific returned quarters and stated
calculations; probabilities retain their official meanings. No horizon-event claim,
fabricated signal, causal explanation or accuracy improvement is asserted. Real-data
and synthetic verification pass, including the baseline's potentially flat signals.

## Step 5. Compare forecasts with actual outcomes

**Objective and implementation:** Reuse Step 3's origin selection and cached forecasts.
Create a separate actuals adapter and `GET /api/history?origin=...`. Explicitly read
only delivery timestamp, imbalance price and direction from validation actuals;
exclude `spot_price` at ingestion and serialization. Join by delivery timestamp, retain
all forecast rows, and return missing outcomes as null. Do not send original actuals
files or derive historical spot values for display. Actuals are loaded only for
retrospective comparison and have no path into the engine adapter or fitting.

Add an actual imbalance-price overlay, off by default and enabled only by an explicit
"Show actual outcomes" control. Clearly label the overlay and metrics as retrospective
outcomes revealed afterward, rather than information available at the forecast origin.
Fetch history only when the user enables comparison. Report observed MAE, interval
coverage and matched/missing counts for the selected origin where outcomes exist;
use an application summary with explicit sample
size, not official competition points. Do not calculate spike outcomes from restricted
spot data for the UI. Selecting an earlier origin selects its already valid forecast;
it does not retrain or use actuals as an input. Cancel/ignore stale frontend responses
when selection changes.

**Expected new files:** `backend/app/actuals.py`, `backend/tests/test_history.py`,
`frontend/src/components/HistoricalReview.tsx`, and focused frontend
history tests. Modify backend config/service/routes/schemas and their tests, frontend
API/types/App/chart, and both local guides. No test-period actuals are accessed.

**Verify:** Check missing/tail actuals, exact UTC joins, distinct forecasts for overlapping
delivery windows, invalid origins and counts/metrics against hand-calculated synthetic
examples. Guard fit call count across selection and ensure actuals cannot enter the
prediction service. Verify response races, loading/errors and null chart gaps. Check
that no history request or outcome display occurs before comparison is enabled.
Use a synthetic restricted spot sentinel to prove the actuals adapter does not read/serialize
that column. Real validation-data smoke compares a small set of origins through the
API and engine; verify repeated retrieval and honest missing-outcome display.

**After this step:** Users can review selected historical forecasts against observed
outcomes and see both uncertainty and realized forecast error.

**Acceptance criteria:** Only allowed validation origins are selectable; all predictions
use the correct pre-validation fit and original as-of rules. Forty steps remain present
even with missing outcomes. Selected-origin metrics show denominators and are not
presented as full validation scores. Restricted fields remain absent, requests do not
refit, and actuals/prediction separation is verified.

## Step 6. Improve usability, evidence and the local demonstration

**Objective and implementation:** Refine the complete workflow for an energy expert:
readable responsive layout, keyboard-accessible selection, clear legends/units,
non-colour cues, concise metric definitions, empty states and recoverable errors.
Refine the accessible table introduced in Step 2A and add a short guided route from
situational overview to a chosen delivery and historical outcome. Include model
identifier, fit cutoff and historical replay status so a snapshot is not mistaken for
a live forecast.

Optionally show evidence-based explanations only when already supported by the engine
contract: approved driver names and safe selected provenance timestamps/ages. Missing
drivers remain unavailable. Timestamp freshness is evidence about input timing, not
proof of importance or a causal account. Do not infer drivers from chart movement or
add an explanation model. Record unavailable evidence as an integration limitation.

Finish setup/troubleshooting and a short local demo checklist, including licences,
private-data placement and post-event deletion. This step prepares a usable application
demo; recording the final video, slides and submission packaging remain separate tasks.

**Expected new files:** `frontend/src/components/ForecastEvidence.tsx`
if required, associated tests, and `docs/application-demo.md`. Modify the existing table, application
components/styles, local guides and allowlisted backend metadata only where necessary.
Do not expand the public engine contract for optional explanations.

**Verify:** Walk through overview, probabilities, origin selection, historical review,
failure/retry and keyboard navigation at desktop and narrow widths. Test blank optional
evidence, negative source ages for already-published future deliveries, and correct
timezone labels through DST. Run backend tests, frontend tests/typecheck/build and the
existing engine suite without editing engine files. Confirm a predictor substitution
through the existing interface needs only startup selection: a synthetic contract
double may test this, but runtime still uses a real predictor. Re-run real integration
against the recorded engine revision and inspect API/error output for restricted data.

**After this step:** A coherent local demonstration covers situational insight,
historical review and usability, with honest model limitations and reproducible setup.

**Acceptance criteria:** A teammate completes the documented flow without developer
intervention. Displayed claims trace to forecast fields, allowed outcomes or explicit
evidence; absent evidence is not invented. Relevant checks pass, privacy inspection
passes, and remaining limits are recorded without claiming unmeasured Level 2 points.

## Local execution and verification contract

The individual step results record checks actually run; these commands summarize the
local workflow. Run from the repository root using the shared Python 3.12 environment
described in [python-environment.md](python-environment.md). That guide supersedes older
separate pip-install instructions. The frontend guide records Node/npm and its lockfile.
The engine guide remains the source for engine installation and private input setup.

```bash
# Synchronize the committed shared Python lock after pulling dependency changes:
uv pip sync --python .venv requirements-dev.lock
uv pip check --python .venv

# Backend checks and explicit smoke:
.venv/bin/python -m unittest discover -s backend/tests -v
.venv/bin/python -m backend.tests.smoke_forecast --data-dir data

# Start the existing HTTP adapter:
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log

# In another terminal, once Step 2 exists:
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
npm run test -- --run
npm run typecheck
npm run build
```

On Windows use `.venv\Scripts\python.exe` for Python commands and `npm.cmd` for npm.
Test both platforms
when available and report what remains unverified. Each guide must specify actual
required configuration, paths, supported versions, proxy port and browser URL. Runtime
data stays outside frontend assets; local HTTP responses do not require persisted
forecast exports. No Docker, database or deployment setup is required.

## Step completion and review

Implement only the next explicitly authorized step or half, then stop. An instruction
to begin "Step 1" starts Step 1A only; the same rule applies to Step 2A. Each second
half requires separate approval after its predecessor's handoff. Supply a handoff with
scope, exact changed files, rationale, branch/base/HEAD, engine revision, actual checks
and results, local evidence locations and limitations. Keep private outputs ignored.
Include any **ENGINE CHANGE PROPOSAL** and its coordination status, or explicitly
report **Engine change proposals: None**.
Use [the independent review workflow](REVIEW.md); obtain approval for the affected
candidate before any separately authorized push. An approved roadmap or review verdict
does not authorize implementation of the next step, committing, pushing or merging.

The roadmap was initially a planning-only change. Steps 1A, 1B, 2A, 2B and 3A's separately
authorized implementation and actual verification are recorded above; later steps remain gated.
