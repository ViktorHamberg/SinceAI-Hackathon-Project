# Forecast frontend

Step 2A connects React/TypeScript/Vite to the existing local FastAPI service. It shows
one genuine historical forecast: all 40 quarter-hours, P10/P50/P90 in EUR/MWh,
Helsinki timestamps with explicit offsets, and model/run identity. The accessible
table remains useful when Step 2B adds a chart. Origin selection and probability
displays are later steps. The current model remains the persistence baseline.

Styling lives in `src/index.css`, `src/App.css` and
`src/components/ForecastTable.css`. There is no Tailwind dependency or inline styling.
The white/charcoal/orange palette is inspired by the user's Turku Energia reference;
this is a challenge demonstration, not an official Turku Energia product.

## Run locally

Use Node **24.13.0** and npm **11.6.2**, the versions verified on Windows. `.nvmrc`
records Node's version for teammates who already use a Node version manager.
Install Node from its official distribution if needed; no version manager is required.
The package also declares compatible Node ranges, but those other versions have not
been tested here. macOS execution remains to be verified by the teammate.

Keep two terminals open. First, start the backend **from the repository root**, using
the existing Python environment and the setup in [backend/README.md](../backend/README.md).

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
On Windows, `npm.cmd` avoids PowerShell's restriction on the separate `npm.ps1` script;
there is no need to change the computer's execution policy. Use `npm ci` after pulling
a changed lockfile; do not regenerate the lockfile separately on each operating system.
The dev server fails if port 5173 is occupied rather than silently changing the URL.

The browser calls relative `/api/forecast`; Vite proxies `/api` to
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

The fixed origin is `2026-09-06T21:00:00Z`, displayed as 7 September at 00:00 UTC+3.
The last delivery starts at 09:45 Helsinki time; the window ends at 10:00.
Compare table values with http://127.0.0.1:8000/api/forecast or the backend's `/docs`.
Prices retain the API's numerical precision. Negative prices are valid. Dates always
use `Europe/Helsinki`; hovering a timestamp shows its UTC equivalent. UTC instants
remain the row identifiers, including during the repeated autumn hour.

- Scroll the table to reach quarter 40. At narrow widths, horizontal scrolling exposes
  every column; the table region is keyboard focusable and supports native scrolling.
- Tab through the skip link, Reload button, table region and Model and run details.
  Open the details to see recipe/predictor, run ID, fitting cutoff and preparation time.
- Stop the backend and click **Reload forecast**. The table clears and a fixed error
  appears. Restart the backend, wait for readiness, then click **Retry connection**.
  No previous forecast is shown as a fresh result while a request is pending or fails.
- Use browser Network tools to confirm `/api/forecast` is the only application data
  endpoint. No source CSVs, actual outcomes or restricted spot fields should appear.
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

Direct runtime dependencies React and React DOM are MIT licensed. Direct development
dependencies Vite, its React plugin, TypeScript, Vitest, jsdom, Testing Library packages
and `@types/*` are MIT licensed except TypeScript, which is Apache-2.0. Exact direct
versions are in `package.json`; resolved transitive versions and integrity hashes are
in `package-lock.json`. No external fonts, image service or analytics is used.
Challenge source licences and restrictions remain in
[the root README](../README.md#9-sources-and-licences).
