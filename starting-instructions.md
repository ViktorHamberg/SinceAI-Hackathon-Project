# Start Castergy Insights

## 1. Requirements

- Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/), and Node.js 24 with npm.
- Internet access for the initial dependency installation.
- Authorised challenge files in a `data/` folder at the project root:
  `inputs.csv`, `spot_nordpool.csv`, and `actuals_validation.csv`.
  The actuals file is needed only for **Show actual outcomes**.

Restricted datasets are not included in the source ZIP. Obtain them through the
challenge organiser; do not publish or redistribute Nord Pool data.

Extract the ZIP and open a terminal in the project root (the folder containing
`README.md`). Run all commands below from there.

## 2. Install dependencies once

```text
uv venv --python 3.12 .venv
uv pip sync --python .venv requirements-dev.lock
uv pip check --python .venv
```

If a working project `.venv` already exists, skip the first command.

Install the frontend dependencies:

Windows PowerShell:
```powershell
npm.cmd --prefix frontend ci
```

macOS:
```bash
npm --prefix frontend ci
```

LightGBM may require Microsoft's Visual C++ runtime on Windows or OpenMP on macOS
(`brew install libomp`). See [environment setup](docs/python-environment.md) for details.

## 3. Start the backend

Windows PowerShell:
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

macOS:
```bash
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

**Wait for `Application startup complete`.** With no saved model, the first start
trains the model and can take an hour or longer. Compatible later starts load the
local model cache, then prepare the dashboard forecasts. Keep the terminal open.
Private model caches are not included in the source ZIP. If an existing cache is
incompatible, startup stops; see [backend troubleshooting](backend/README.md).

## 4. Start the frontend in a second terminal

Windows PowerShell:
```powershell
npm.cmd --prefix frontend run dev
```

macOS:
```bash
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173/**. Keep both terminals running; press Ctrl+C to stop them.

Use **Forecast** for prices and risk, **Price Drivers** for category explanations,
and **Raw Data** for the forecast table. Actual outcomes are optional retrospective
comparisons. This is historical replay, not a live feed. No LLM API key is required.

## Submission forecasts

The final `forecast_backtest.csv` is a separate prepared deliverable with 673 origins
and 26,920 rows. Starting the dashboard does not regenerate it. The organisers score
it against private test outcomes. See [README.md](README.md) for the official rules.
