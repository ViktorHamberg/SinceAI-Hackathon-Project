# Application: incremental implementation plan

**Status: Proposed for review. Planning only; no application step is implemented or
authorized by this document. The user confirmed on 7 November 2026 that engine Step 6
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
Tailwind CSS, Recharts and JSON REST. Steps 1–2 deliver the first milestone: one genuine
40-step engine forecast shown in the browser as p50 and a p10–p90 band. A fixed
historical origin is sufficient. Steps 3–5 add the Level 2 priorities of situational
insights, historical review and usability.

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
- Keep dependencies and tooling application-local: `backend/requirements.txt`, frontend
  package/lock files and local ignore files. Preserve the starter `requirements.txt`.
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
  public directory or bundle it. Use synthetic fixtures in tracked tests. App-local
  ignore files must cover dependency/build/test outputs. Follow README licence and
  deletion rules; do not redistribute restricted source values through derived views.
- Bind the unauthenticated app to loopback. Use a Vite `/api` proxy to the local backend,
  keeping browser calls relative and avoiding unnecessary CORS configuration. No
  static file route may serve datasets or arbitrary filesystem paths.
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

## Step 1. Serve one genuine engine forecast through FastAPI

**Objective and implementation:** Establish the backend and its application-side
adapter. In FastAPI lifespan startup, explicitly load private CSV inputs/spot using
`load_inputs`, create the predictor, fit with `RunConfig.validation()`, and generate
the fixed origin through `forecast(fitted, data, origins=[origin])`. Retain the fitted
object and validated result in application state. Importing modules must not load or
fit data. Serve the cached forecast; do not run training or official tools in handlers.

Define `GET /api/forecast` with an explicit JSON response containing a forecast origin,
fit cutoff, predictor identifier, and 40 ordered points. Point fields preserve the 13
official names; absent `data_cutoff_utc` and `top_drivers` become JSON `null`. The API
envelope is application-owned and does not change the engine/CSV contract. Serialize
finite numbers and UTC strings without rounding prediction values. Expose only safe
metadata; omit raw dependency lineage and source values. Include the probability
fields now even though Step 2 displays only prices. Treat future nonempty free-text
`top_drivers` as untrusted: expose only approved driver names, otherwise return null.

Add `GET /api/health` for safe readiness status. Startup failure prevents forecast
serving and produces a sanitized diagnostic; never substitute fabricated predictions.
Document configured input paths, fixed origin, startup cost, dependency installation,
single-worker execution and troubleshooting in the backend guide.

**Expected new files:** `backend/__init__.py`, `backend/app/{__init__,main,config,
forecast_service,schemas}.py`, `backend/requirements.txt`, `backend/.gitignore`,
`backend/README.md`, and `backend/tests/{__init__,test_forecast_api}.py`.
No existing engine or starter files change.

**Verify:** Use standard-library unittest plus FastAPI's test client and its declared
HTTP test dependency. Check full 40-step JSON shape, UTC arithmetic, null conversion,
probability/quantile validity, repeated requests without additional fit/predict calls,
and sanitized startup failures. Synthetic fixtures may isolate HTTP tests; a separate
local smoke must call the real engine with supplied data and compare all required
JSON prediction values and identifiers against the retained engine result. Test that
restricted fields and sentinel source values cannot pass response serialization or
error logging. Check import does not initialize the engine.

**After this step:** A locally runnable JSON backend serving one real historical
forecast, ready for a frontend; there is no browser interface yet.

**Acceptance criteria:** A real-data startup succeeds, `/api/forecast` returns exactly
40 complete steps, and repeat calls reuse one fit and one cached prediction per
lifecycle. No actuals are loaded. Safe errors and privacy checks pass. Record actual
checks, engine revision and startup time; make no performance claim in advance.

## Step 2. Display the forecast and uncertainty in the browser

**Objective and implementation:** Create the Vite React/TypeScript frontend with
Tailwind and Recharts. Fetch `/api/forecast` through the development proxy. Define
application-owned TypeScript response types and validate essential response shape at
the boundary so malformed or incomplete data produces an error state.

Render p50 as a line and p10–p90 as an interval over all 40 delivery quarters, with
EUR/MWh units, legend and exact-value tooltips. Use a range area or equivalent band
that remains correct for negative prices; a zero-based stacked area must not distort
the interval. Preserve quarter-hour values and avoid smoothing that implies additional
forecasts. Show forecast origin, historical replay label and the full ten-hour window.
Default labels to `Europe/Helsinki` with explicit timezone/offset; retain UTC instants
as chart keys and offer UTC in tooltips. The user's machine timezone must not change
which forecast is shown. Include loading, API failure, malformed response and retry
states; stale charts must not appear to represent a newly requested result.

**Expected new files:** `frontend/{package.json,package-lock.json,index.html,
vite.config.ts,tsconfig*.json,.gitignore,README.md}`, `frontend/src/{main.tsx,App.tsx,
index.css}`, `frontend/src/api/forecast.ts`, `frontend/src/components/ForecastChart.tsx`,
`frontend/src/time.ts`, and focused API/chart/time tests beside these modules.
Modify only backend documentation if the joint startup instructions need clarification.

**Verify:** Declare a small frontend test setup such as Vitest and React Testing
Library in the frontend package. Check response validation, loading/error/retry,
negative and crossing-zero bands, origin/delivery labels and timezone formatting.
Use synthetic fixtures for component tests, including the repeated Helsinki hour on
25 October and dates crossing midnight. Run TypeScript checking and production build.
Manually open the real backend/frontend together and confirm 40 points and tooltips
agree with the API, with no console errors. Network inspection must show no restricted
spot fields or data-file requests. Automated fixtures do not replace this real smoke.

**After this step:** The first milestone is complete: one genuine engine forecast is
visible in the browser, with median, uncertainty, correct times and usable failure states.

**Acceptance criteria:** A teammate can follow the local guides to reproduce the
browser view. All 40 quarters remain accessible; the interval handles negative values;
the origin and delivery window are unambiguous. The normal application path uses the
real endpoint, without hardcoded predictions or a mock fallback. Tests/build and real
browser verification pass, with any environment limits stated explicitly.

## Step 3. Add direction, exceptional-price probabilities and risk summaries

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
and find the quarters with the largest predicted risk or uncertainty.

**Acceptance criteria:** Summaries trace to specific returned quarters and stated
calculations; probabilities retain their official meanings. No horizon-event claim,
fabricated signal, causal explanation or accuracy improvement is asserted. Real-data
and synthetic verification pass, including the baseline's potentially flat signals.

## Step 4. Add historical selection and comparison with actual outcomes

**Objective and implementation:** Extend the same service to a bounded selection of
validation origins from 7 September–4 October, using the existing validation-fitted
predictor. Support `GET /api/forecast?origin=...` and `GET /api/origins` with a small,
documented allowlist initially; expand only if measured startup/memory cost permits.
Generate/cache that bounded set during startup through the existing batch API and
reuse it for all requests. Reject unsupported, naive or non-hourly origins safely;
never accept client filesystem paths, arbitrary training dates or model parameters.

Create a separate actuals adapter and `GET /api/history?origin=...`. Explicitly read
only delivery timestamp, imbalance price and direction from validation actuals;
exclude `spot_price` at ingestion and serialization. Join by delivery timestamp, retain
all forecast rows, and return missing outcomes as null. Do not send original actuals
files or derive historical spot values for display. Actuals are loaded only for
retrospective comparison and have no path into the engine adapter or fitting.

Add an origin selector and actual imbalance-price overlay with a clear retrospective
label. Report observed MAE, interval coverage and matched/missing counts for the
selected origin where outcomes exist; use an application summary with explicit sample
size, not official competition points. Do not calculate spike outcomes from restricted
spot data for the UI. Selecting an earlier origin selects its already valid forecast;
it does not retrain or use actuals as an input. Cancel/ignore stale frontend responses
when selection changes.

**Expected new files:** `backend/app/actuals.py`, `backend/tests/test_history.py`,
`frontend/src/components/{OriginSelector,HistoricalReview}.tsx`, and focused frontend
history tests. Modify backend config/service/routes/schemas and their tests, frontend
API/types/App/chart, and both local guides. No test-period actuals are accessed.

**Verify:** Check missing/tail actuals, exact UTC joins, distinct forecasts for overlapping
delivery windows, invalid origins and counts/metrics against hand-calculated synthetic
examples. Guard fit call count across selection and ensure actuals cannot enter the
prediction service. Verify response races, loading/errors and null chart gaps. Use a
synthetic restricted spot sentinel to prove the actuals adapter does not read/serialize
that column. Real validation-data smoke compares a small set of origins through the
API and engine; verify repeated retrieval and honest missing-outcome display.

**After this step:** Users can review selected historical forecasts against observed
outcomes and see both uncertainty and realized forecast error.

**Acceptance criteria:** Only allowed validation origins are selectable; all predictions
use the correct pre-validation fit and original as-of rules. Forty steps remain present
even with missing outcomes. Selected-origin metrics show denominators and are not
presented as full validation scores. Restricted fields remain absent, requests do not
refit, and actuals/prediction separation is verified.

## Step 5. Improve usability, evidence and the local demonstration

**Objective and implementation:** Refine the complete workflow for an energy expert:
readable responsive layout, keyboard-accessible selection, clear legends/units,
non-colour cues, concise metric definitions, empty states and recoverable errors.
Add an accessible tabular view of quarter-hour values and a short guided route from
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

**Expected new files:** `frontend/src/components/{ForecastTable,ForecastEvidence}.tsx`
if required, associated tests, and `docs/application-demo.md`. Modify application
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

These are planned commands to make concrete and verify in Steps 1–2, not commands run
while drafting. Run from the repository root using Python 3.11+ and the existing
environment. Verify Node/npm compatibility when selecting Vite and lock versions then.
The engine guide remains the source for engine installation and private input setup.

```bash
# Once Step 1 is authorized and its files exist:
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m unittest discover -s backend/tests -v
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# In another terminal, once Step 2 exists:
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
npm run test -- --run
npm run typecheck
npm run build
```

On Windows use `.venv\Scripts\python.exe` for Python commands. Test both platforms
when available and report what remains unverified. Each guide must specify actual
required configuration, paths, supported versions, proxy port and browser URL. Runtime
data stays outside frontend assets; local HTTP responses do not require persisted
forecast exports. No Docker, database or deployment setup is required.

## Step completion and review

Implement only the next explicitly authorized step, then stop. Supply a handoff with
scope, exact changed files, rationale, branch/base/HEAD, engine revision, actual checks
and results, local evidence locations and limitations. Keep private outputs ignored.
Include any **ENGINE CHANGE PROPOSAL** and its coordination status, or explicitly
report **Engine change proposals: None**.
Use [the independent review workflow](REVIEW.md); obtain approval for the affected
candidate before any separately authorized push. An approved roadmap or review verdict
does not authorize implementation of the next step, committing, pushing or merging.

This planning change creates only this file. No dependency installation, scaffolding,
code changes or application test execution is part of drafting the roadmap.
