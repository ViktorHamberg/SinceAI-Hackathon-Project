# Forecast frontend

Steps 2A, 2B and 3B connect React/TypeScript/Vite to the local FastAPI service. Choose
one of six cached historical forecasts: all 40 quarter-hours, P10/P50/P90 in EUR/MWh,
Helsinki timestamps with explicit offsets, and model/run identity. The accessible
table accompanies a median line and P10-to-P90 chart. Probability displays remain a
later step. The current model remains the persistence baseline.

Application styling lives in `src/index.css`, `src/App.css` and the component CSS
files. No Tailwind dependency is used. Recharts manages its own SVG/HTML geometry.
The white/charcoal/orange palette is inspired by the user's Turku Energia reference;
this is a challenge demonstration, not an official Turku Energia product.

## Run locally

Use Node **24.13.0** and npm **11.6.2**, the versions verified on Windows. `.nvmrc`
records Node's version for teammates who already use a Node version manager.
Install Node from its official distribution if needed; no version manager is required.
The package also declares compatible Node ranges, but those other versions have not
been tested here. macOS execution remains to be verified by the teammate.

Keep two terminals open. First, start the backend **from the repository root**, using
the shared Python 3.12 environment configured according to
[docs/python-environment.md](../docs/python-environment.md). That guide supersedes
older separate pip-install instructions. The backend behavior is documented in
[backend/README.md](../backend/README.md).

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

macOS:

```bash
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Wait for **Application startup complete**. Startup prepares the forecast once and can
take about a minute on this Windows machine. Browser requests only retrieve the cached
forecast; moving through the table or pressing Reload does not fit or predict again.

In the second terminal, also starting at the repository root:

Windows PowerShell:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

macOS:

```bash
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173/**. Keep both processes running. Stop each with Ctrl+C.
If you prefer to stay at the repository root, use `npm.cmd --prefix frontend run dev`
on Windows or `npm --prefix frontend run dev` on macOS. Install the new chart
dependencies with `npm ci` after pulling this step's changed package lockfile.
On Windows, `npm.cmd` avoids PowerShell's restriction on the separate `npm.ps1` script;
there is no need to change the computer's execution policy. Use `npm ci` after pulling
a changed lockfile; do not regenerate the lockfile separately on each operating system.
The dev server fails if port 5173 is occupied rather than silently changing the URL.

The browser calls relative `/api/origins` and `/api/forecast?origin=...`; Vite proxies `/api` to
`http://127.0.0.1:8000`. No backend CORS changes are needed. For a deliberately different
backend port, set the **server-side** `FORECAST_API_PORT` before starting Vite:

```powershell
$env:FORECAST_API_PORT='8001'
npm.cmd run dev
# Later, to restore the default in this terminal:
Remove-Item Env:FORECAST_API_PORT
```

On macOS: `FORECAST_API_PORT=8001 npm run dev`. This setting changes only the local
proxy destination, not forecast origin or model parameters. Do not put secrets in
`VITE_*` variables: Vite exposes them to the client bundle.

## Check behavior

The default origin is `2026-09-06T21:00:00Z`, displayed as 7 September at 00:00 UTC+3.
For this default, the last delivery starts at 09:45 Helsinki time; the window ends at 10:00.
Compare table values with http://127.0.0.1:8000/api/forecast or the backend's `/docs`.
Prices retain the API's numerical precision. Negative prices are valid. Dates default
to `Europe/Helsinki`; the visible Helsinki/UTC buttons change all presented times.
UTC instants remain the identifiers, including during the repeated autumn hour.

### Price chart

The solid charcoal line is P50; the shaded area between dashed brown boundaries is
P10 to P90. This is a nominal 80% interval, not measured coverage. Both the range and
median use steps: one forecast applies to its complete 15-minute delivery period.
Quarter 40 continues to the ten-hour endpoint. A final range rectangle and median
segment draw that duration without adding or forecasting a 41st quarter.

Hover, click or tap a delivery interval to inspect it. The selected-delivery strip
below the plot shows its start/end time, UTC equivalent when viewing Helsinki time,
and exact P10/P50/P90. Quarter 1 is selected initially. The vertical guide and median
dot identify the selection. The detail strip replaces floating tooltips so values
remain readable on narrow screens without covering the plot.

Tab to the chart. Left/Right move one quarter; Home/End select the first/last.
Selection stays bounded to 40 quarters, and Tab continues through the inspection
controls to the table. Mouse, touch
and keyboard share the same selection state. Taps select; swipes remain available for
page scrolling. Chart inspection and timezone switching do not request new forecasts.
Previous/Next buttons let touch users refine a selection one quarter at a time;
they become unavailable at the first/last quarter. They are also keyboard accessible.
The chart has no entrance or continuous animation. Price-axis labels can use compact
notation; the detail strip and table retain full values.

The plotting code loads separately from the main application. A loading message is
shown while it loads. If that chunk fails, the table and metadata remain usable; the
chart fallback tells the user to reload the browser page. This does not retry model
training. The existing API request errors still clear both forecast views.

- Scroll the table to reach quarter 40. At narrow widths, horizontal scrolling exposes
  every column; the table region is keyboard focusable and supports native scrolling.
- Tab through the skip link, Reload button, Helsinki/UTC controls, forecast navigation,
  timeline and exact-time list, chart, Previous/Next quarter controls, table region
  and Model and run details. Press Enter on the skip link to reach the main workspace.
  Open the details to see recipe/predictor, run ID, fitting cutoff and preparation time.
- Stop the backend and click **Reload forecast**. The table clears and a fixed error
  appears. Restart the backend, wait for readiness, then click **Retry connection**.
  No previous forecast is shown as a fresh result while a request is pending or fails.
- Use browser Network tools to confirm only `/api/origins` and `/api/forecast?origin=...`
  supply application data. No source CSVs, actual outcomes or restricted spot fields should appear.
  React development mode may cancel an initial request and issue another; neither
  causes extra model fitting. Stalled requests abort after 15 seconds.

From `frontend/`, run automated checks (use `npm` instead of `npm.cmd` on macOS):

```powershell
npm.cmd run test -- --run
npm.cmd run typecheck
npm.cmd run build
```

Tests use invented data only and cover response validation, negative/precise prices,
full horizons, Helsinki DST, midnight, loading, sanitized errors, timeout, retry and
stale-response cancellation. They do not establish forecast accuracy.
`npm.cmd run preview` serves the built `dist/` on http://127.0.0.1:4173/ with the same
local API proxy. This is a local build check, not a production deployment setup.

## Files and boundaries

| File | Responsibility |
| --- | --- |
| `package.json`, `package-lock.json`, `.nvmrc` | Commands, pinned dependencies and Node version |
| `vite.config.ts`, `tsconfig.json`, `index.html` | Local proxy, test/build configuration and HTML entry |
| `src/main.tsx`, `src/favicon.svg` | React entry and local icon |
| `src/App.tsx`, `src/App.css` | Request lifecycle, status states and page layout |
| `src/api/forecast.ts` | Public response types, v1 validation and safe HTTP errors |
| `src/time.ts` | Explicit Helsinki/UTC formatting and ten-hour end time |
| `src/components/ForecastTable.tsx`, `.css` | Accessible 40-quarter price table |
| `src/components/ForecastChart.tsx`, `.css` | Price/uncertainty plot, selection and exact-value readout |
| `src/components/OriginSelector.tsx`, `.css` | Date-scaled replay timeline, local drag preview, keyboard/buttons and exact-time selection |
| `src/forecastChart.ts` | UTC chart data, full-period geometry and axis formatting |
| `src/components/ChartBoundary.tsx` | Keeps the table available if the chart fails |
| `DESIGN.md` | Design direction and reasons for chart/interaction choices |
| `src/index.css` | Shared colors, fonts and focus styles |
| `src/**/*.test.*`, `src/test/` | Behavior checks, cleanup and synthetic fixtures |

The frontend imports no Python, challenge datasets, actuals or model artifacts. Runtime
has no fixture fallback. It accepts only the exact public v1 JSON structure and rejects
incomplete or invalid results rather than repairing them. The backend remains the
security boundary; client validation cannot undo a server-side disclosure.

Keep all private data under ignored root `data/`. The shared root `.gitignore` already
excludes `node_modules/`, `frontend/dist/`, `frontend/coverage/` and private evidence
under `baseline_output/`; no nested ignore is needed. Never copy datasets into client
assets, tests or screenshots. Inspect staged content before every commit.

## Dependencies and licences

Direct runtime dependencies React, React DOM, React Is and Recharts are MIT licensed.
Recharts 3.10.1 and React Is 19.3.1 are pinned for this step. The implementation uses
the documented [range-area support](https://recharts.github.io/en-US/api/Area/)
with application-owned selection and the existing semantic table for accessibility.
Direct development
dependencies Vite, its React plugin, TypeScript, Vitest, jsdom, Testing Library packages
and `@types/*` are MIT licensed except TypeScript, which is Apache-2.0. Exact direct
versions are in `package.json`; resolved transitive versions and integrity hashes are
in `package-lock.json`. No external fonts, image service or analytics is used.
Challenge source licences and restrictions remain in
[the root README](../README.md#9-sources-and-licences).

## Historical replay controls (Step 3B)

The issue-time panel selects when a forecast was issued. Its Previous/Next **forecast**
buttons are distinct from the chart's Previous/Next **quarter** inspection controls.
Only dates returned by the backend catalog are available; the initial selection uses
the catalog default. See [the backend guide](../backend/README.md) for the six dates.

The timeline uses a native range input. Marks are spaced by elapsed UTC time across
the full available span, rather than being placed at equal distances. The nearby first
origins therefore cluster; use the exact-time list or navigation buttons to select
them precisely. Empty gaps contain no cached forecast. The handle snaps to the nearest
available origin, with an exact tie choosing the earlier one.

While holding/dragging, the panel shows **Preview · release to load**. The chart/table
continue displaying the committed forecast and their issue time remains explicitly
labeled. Previewing creates no HTTP requests. Release commits one choice and retrieves
its cached forecast. Pointer cancellation or Escape abandons the preview. The range
reserves vertical touch gestures for page scrolling; physical touch/browser feel
still needs manual verification on the target device.

Tab to the timeline and use Left/Right or Up/Down to select the previous/next available
origin, regardless of gap length. Home/End choose first/last; PageUp/PageDown also
move one available origin. These explicit keyboard choices load immediately. The
exact-time list is native and all controls have accessible names and visible focus.
With only one configured origin, the timeline/navigation buttons are disabled.

On a committed change, the chart, table and metadata clear while loading, then update
together. Quarter inspection and table scroll reset for the new forecast; the display
timezone stays selected. Rapid selection aborts the previous request and ignores late
successes/failures even if cancellation is disregarded by the transport. The selector
remains available during forecast loading so users can choose another origin.

Both the catalog and forecast responses are validated against exact allowlisted
structures. A selected forecast must match its requested origin and every shared run/
model metadata field. If the backend restarts between requests, the mismatched result
is rejected. **Retry connection** refreshes the catalog and then fetches the requested
origin if it remains available; otherwise it selects the new default. Reload does the
same refresh deliberately. It does not train a model. Dragging, timezone changes and
delivery-quarter inspection do not refetch the catalog.

Manual checks after starting backend on 8000 and frontend on 5173:

1. Choose a different exact issue time. Chart/table/context change together; compare
   its values with `/api/forecast?origin=...`. Confirm quarter 1 is selected.
2. Drag toward a later marker without releasing. The preview changes while the old
   displayed forecast remains labeled; Network shows no new request. Release: one
   selected-origin request occurs. Same-origin release makes no additional request.
3. Try cancellation/Escape, arrows, Home/End, Previous/Next forecast and the exact-time
   list. End controls are disabled. Switch UTC/Helsinki without changing the origin.
4. Select rapidly between dates; the final selected forecast must win. Stop backend,
   select another origin and verify a safe error with no old chart/table. Restart,
   wait for readiness and Retry to refresh the catalog and recover.
5. Check 320px, intermediate widths, desktop, 200% zoom, keyboard focus/Tab exit,
   touch scrolling, browser Console and Network. No document horizontal overflow.

Relevant automated checks from root:

```powershell
npm.cmd --prefix frontend run test -- --run src/api/forecast.test.ts src/components/OriginSelector.test.tsx src/App.test.tsx
npm.cmd --prefix frontend run build
```

Verification on Windows: 29 API tests and 17 App/selector tests passed across focused
runs; TypeScript/production build passed. Real production-preview HTTP integration
used the actual frontend API module to validate the six-origin catalog and all 240
forecast rows (1,920 numerical values equal to the direct backend). Built assets served
successfully. Browser automation was unavailable, so these do not establish real
native-drag rendering/feel, touch, screen-reader behavior or responsive/zoom results.
macOS and unrelated backend/engine/chart/table suites were not rerun for this step.
No dependencies, backend, engine contract or forecasting accuracy changed.
