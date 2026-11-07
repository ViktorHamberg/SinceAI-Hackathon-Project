# Private chronological experiments

This adapter uses the existing fit/forecast/export contract and unchanged official
validator/scorer. It does not replace `python -m forecast_engine validation` or change
application integration. Only persistence is selected by this command initially.
There is no tuning, ML dependency, model promotion or test-period scoring here.

Use the existing Python 3.11+ environment and editable engine installation described
in `docs/forecasting-engine.md`. Run from the repository root; all relative paths
resolve against the current directory. On Windows replace `.venv/bin/python` with
`.venv\Scripts\python.exe`. No additional installation is required for this adapter.

```bash
.venv/bin/python -m forecast_engine.experiments.run --period validation --starter-dir . --data-dir data --output-dir baseline_output/engine/experiments/validation-01
.venv/bin/python -m forecast_engine.experiments.run --period fold-1 --starter-dir . --data-dir data --output-dir baseline_output/engine/experiments/fold-1-01
.venv/bin/python -m forecast_engine.experiments.run --period fold-2 --starter-dir . --data-dir data --output-dir baseline_output/engine/experiments/fold-2-01
```

Every run needs a fresh or empty output directory. Keep output under ignored
`baseline_output/engine/`; never publish generated forecasts or fold actuals.
Inputs are explicitly `DATA_DIR/inputs.csv` and `DATA_DIR/spot_nordpool.csv`; required
tools are `STARTER_DIR/validate_submission.py` and `STARTER_DIR/score.py`.
Parquet and arbitrary actuals overrides are not part of this command. It never
searches for, hashes, opens or scores test actuals. Use the existing test CLI for
the separately authorized final submission workflow.

## Fit, forecast and score

Validation uses `RunConfig.validation()` and all 672 canonical hourly origins. It
exports 26,880 rows, retaining unlabelled tail deliveries. Validation actuals are read
only by the scorer after forecast export and structural validation; their first-byte
access in this process is the scoring-stage hash of `actuals_validation.csv`.

The folds reuse Step 1B `expanding_window_folds()`: Finnish local weeks 24–30 August
and 31 August–6 September. Each fits once before its assessment starts, then forecasts
168 origins and 6,720 rows with frozen statistics. Features and fitting labels retain
the engine's origin/publication/cutoff rules. The adapter does not build training
matrices itself; each predictor remains responsible for its own safe fit.

After successful validation, fold scoring actuals are constructed from the supplied
long inputs and spot, separately from anything passed to the predictor. Label deliveries
are limited to the assessment window, with publication at or before the outer
pre-validation cutoff (`2026-09-06T21:00:00Z`). This later scoring cutoff is distinct
from the earlier model fitting cutoff. Missing price/spot/direction values stay missing;
the unchanged scorer selects the matched rows for each metric. Direction maps
1/-1/0 to up/down/none; spike labels and losses are computed by the official scorer
with margin 50. Fold tail deliveries outside the assessment interval remain forecast
rows without scored outcomes. Outcomes unavailable at the outer cutoff are unscored.
No official validation or test outcomes are used to assess these folds.

## Artifacts and safe diagnostics

Each successful directory contains `forecast_backtest.csv`, `forecast_origins.csv`,
`official_validation.json`, `official_scoring.json`, `score/` and `run_manifest.json`.
Fold runs also contain **restricted** `fold_actuals.csv`, including spot prices; this
file is for private scoring only and must follow README licensing/deletion rules.
Do not copy it into application assets, tracked fixtures, screenshots or reports.

The manifest records fitting/request configuration and recipe identity, environment
and Git/source/input fingerprints, safe provenance summaries, row counts, loading/
fitting/prediction timings, official tool arguments/status, all four numerical metrics,
coverage and artifact hashes. No fitted statistics, source values, matrices or raw
exception/subprocess output are copied into diagnostics. Full lineage remains in the
engine result during the run; manifest digests do not substitute for its checks.
Official aggregate/horizon reports stay in `score/`. This adapter reuses the internal
hashing, environment, safe provenance and subprocess adapters in `evaluation.py`;
keep that dependency covered by the experiment tests when those adapters change.

Metric keys are `mae_p50`, `calibration_pinball_mean`, `brier_spike_mean` and
`brier_direction`. Lower is better. Coverage is diagnostic, and missing metrics are
JSON null rather than invented scores. Compare candidates with persistence on the
same configuration, actuals hash, origins and per-metric matched counts. Record every
metric delta; a summary does not establish competition points or improvement on its
own. The script prints only completion/failure status and counts.

On failure, check `status`, `stage`, `failure` and fixed-format official reports in
the manifest. An existing CSV alone is not a successful experiment. Input and source
fingerprints are checked again before completion; do not edit engine files during a
run. Initialization failures can occur before a manifest exists. Original error text
is suppressed because parsers and model failures can contain restricted values.
Exit codes: 0 complete, 1 failed, 2 invalid CLI arguments. Retry in a fresh directory.

## Future predictor selection through the unchanged contract

```python
from forecast_engine.experiments.run import run_experiment

# predictor implements the existing Predictor protocol; no application edits here.
manifest = run_experiment(
    starter_dir=".", data_dir="data",
    output_dir="baseline_output/engine/experiments/candidate-01",
    predictor=predictor, recipe_id="candidate-v1",
)
```

Custom predictors require an explicit recipe identifier containing only letters,
digits, underscores and hyphens. The recipe and source hashes identify the run; record
future model hyperparameters/seeds in its immutable recipe implementation and extend
manifest configuration deliberately when that model is approved. Recipe identifiers
must never contain secrets or source values. The default remains `persistence-v1`.

Run the package-local and existing engine tests before a review handoff:

```bash
.venv/bin/python -W error::FutureWarning -m unittest discover -s src/forecast_engine/tests -t src -v
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v
```

Full-data baseline acceptance is a separate explicit run of the first command in this
guide, compared against recorded official metrics/counts. No new forecast model or
accuracy improvement is claimed by completing that acceptance.
