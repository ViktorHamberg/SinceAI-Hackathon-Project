# Private chronological experiments

This adapter uses the existing fit/forecast/export contract and unchanged official
validator/scorer. It does not replace `python -m forecast_engine validation` or change
application integration. Persistence remains the default; optional direct and
spot-relative LightGBM recipes require explicit selection. There is no tuning, model
promotion or test-period scoring here.

Use the shared Python 3.12 environment and editable engine installation described
in `docs/python-environment.md` and `docs/forecasting-engine.md`. Run from the repository root; all relative paths
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

## Custom predictors through the unchanged contract

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

## Optional LightGBM models (Step 2)

The approved engine extra pins `lightgbm==4.7.0`. The combined team input enables
`.[ml]`, and the shared lock resolves SciPy and Narwhals as transitive dependencies.
Use the same environment/sync workflow in `docs/python-environment.md`; do not install
another copy through backend requirements. Existing numerical/backend pins are retained.
The starter `requirements.txt` and public forecasting interfaces remain unchanged.

On macOS, install the OpenMP runtime before importing the native library:

```bash
brew install libomp
```

On 64-bit Windows, use the wheel and install Microsoft's supported Visual C++ runtime
if missing; source compilation, GPU and MPI are not required. See the
[official LightGBM installation notes](https://pypi.org/project/lightgbm/4.7.0/).
The native import has been verified on Apple Silicon; Windows execution still requires
the partner's verification. A package installed without its native runtime is not a
working ML setup. Confirm with the project interpreter:

```text
.venv/bin/python -c "import lightgbm; print(lightgbm.__version__)"
```

The direct predictor is explicitly selected through the same Python API:

```python
from forecast_engine import RunConfig, load_inputs, forecast
from forecast_engine.models.lightgbm import LightGBMPredictor

data = load_inputs("data/inputs.csv", spot_path="data/spot_nordpool.csv")
fitted = LightGBMPredictor().fit(data, config=RunConfig.validation())
result = forecast(fitted, data, origins=[RunConfig.validation().fit_cutoff_utc])
```

The experiment CLI selects the fixed recipes explicitly:

```bash
.venv/bin/python -m forecast_engine.experiments.run --model lightgbm-direct --output-dir baseline_output/engine/experiments/direct-01
.venv/bin/python -m forecast_engine.experiments.run --model lightgbm-relative --output-dir baseline_output/engine/experiments/relative-01
```

Use a fresh persistence run on the same period/data for comparison. Both ML modes
also support `--period fold-1` and `--period fold-2`. The original engine CLI and
application keep their existing persistence defaults. The v1 recipe is
30 fixed rounds, 15 leaves, minimum 20 rows per leaf, learning rate 0.05, L2 1.0,
seed 2026 and one CPU thread. All five pooled heads share the same ordered features,
including horizon. `TreeRecipe` in `models/heads.py` permits explicit small test recipes.

In direct mode, each price quantile uses imbalance-price labels. Direction classes are
up/down/none; spike classes are high/low/neither with strict ±50 EUR/MWh labels.
There must be at least 40 eligible examples per task and all classifier classes.
Insufficient evidence raises `MissingEvidenceError`; no partial/silent persistence
fallback occurs. Select persistence explicitly instead.

`LightGBMPredictor(target_mode="spot_relative")` trains price quantiles on eligible
imbalance-minus-spot label pairs. It also fits three separate direct-price quantile
heads on independently eligible imbalance labels, once in the same fit call. Direction
and spike classifiers keep their original labels, masks and class order. At inference,
only a delivery spot published by that origin can reconstruct the relative quantiles.
Missing/unpublished spot selects the fitted direct-price heads for that row; it never
uses a future value or treats a spread as an absolute price. Mixed horizons are allowed.
A missing backup is an explicit error. Quantile constraints are applied after choosing
the price path and reconstructing prices, preserving P50 including negative prices.

Fitting projects inputs to the declared feature sources plus required labels and removes
rows not published by the fitting cutoff before building historical examples. Every
historical origin still passes through the unchanged as-of builder; fitting-cutoff
availability alone never makes a historical feature usable. Inference projects to
declared sources and, for relative mode, the reconstruction spot source. No origin cache
or inferred publication time is introduced.

Fitted heads hold private immutable model strings, not training frames or mutable
Boosters. Prediction loads temporary native models and does not fit. These strings
contain learned numbers and must not be printed, exported or published. Full label
and actual historical feature-use evidence is retained separately in fitting provenance.
If a prediction uses only deterministic/missing features, its evidence references the
frozen fitted model's complete lineage. Per-head source classes and counts remain
explicit; no probabilities are invented for absent classes.

P50 is preserved: P10 is clamped down to P50 if needed and P90 up to P50. Independent
raw quantiles can therefore collapse the interval; tests verify this explicit policy.
There is no calibration yet; verified P50 driver attribution is described below.
The fitted record stores target/registry/recipe/policy identity privately for
attribution and recovers raw head predictions from the same model strings. No new
result fields are introduced. Each relative prediction records a named,
value-free dependency for every step identifying the relative or direct-backup path.
Offset evidence remains distinct from learned feature evidence. Fitting provenance
separately identifies relative-label pairs and direct-backup labels.

The manifest records `model_configuration` with target mode, registry and quantile
policy, minimum rows, fallback policy, and each component's identity/hash, feature
order, objective/classes, all explicit native parameters, rounds and native version.
`price_paths` records only counts: delivery spot available/unavailable, primary-relative,
direct-backup and direct rows. Relative path totals must match availability and the
complete forecast row count. These diagnostics contain no spot values or fitted model
strings. Compare all four official metrics, coverage and per-task matched counts along
with `timings.fit` and `timings.predict`; a faster or lower-MAE run alone does not
establish overall superiority.

Select focused tests and affected consumer checks for each change, following the
roadmap's standing test selection rule. Run broader suites only when the impact or
acceptance criteria justify them; these are available commands, not a requirement
to run both for every edit:

```bash
.venv/bin/python -W error::FutureWarning -m unittest discover -s src/forecast_engine/tests -t src -v
.venv/bin/python -W error::FutureWarning -m unittest discover -s tests -v
```

Full-data acceptance compares fresh persistence, direct and relative runs on identical
origins, fitting boundaries, source hashes and scoring-actuals hashes. Keep reports in
ignored run directories and report all metric deltas, coverage, matched counts, spot
availability and backup use. Do not promote a model automatically. Windows execution
and broader feature/recipe tuning require their own verification. Private contributions
and P50 driver labels are described below; the final test submission remains separate.

## Private contributions (Step 3A)

Internal experiments/tests can explicitly call the private helper on a fitted candidate:

```python
from forecast_engine.explainability.contributions import _explain

private_batch = _explain(fitted, data, origins=[RunConfig.validation().fit_cutoff_utc])
```

Calling this explicit helper does not modify predictions, populate `top_drivers`, attach
data to result frames, or provide an application explanation API. Do not print/serialize `private_batch` or its
records. They contain numeric information that can reveal restricted spot prices.
Frozen records contain only immutable tuples/scalars and suppress all fields in repr;
this is not permission to publish their contents with a generic serializer.

The calculation uses the same registered as-of features, saved model strings, active
price path and all saved iterations as prediction. Metadata identifies the head/class,
model fingerprint, immutable recipe, native version, actual iteration count, origin,
delivery, step, registry, target mode, scale and output. A model can finish with fewer
trees than the requested round budget when no further splits are possible; records use
the actual saved iteration count.

Native feature contributions plus the base reconstruct the raw head output. Price
heads use EUR/MWh; relative-head contributions explain the spread. A separate private
ledger records the published delivery spot offset, active direct-backup path, current
identity calibration and P50-preserving outer-bound clamp. The offset belongs to
`spot_price_conditions` but is not a learned feature effect and is not folded into
learned category sums. Direction/spike records explain raw class margins; softmax
records all class margins and the resulting probability separately. They are not
additive probability-point contributions.

Signed registry category sums preserve feature-level cancellation. No category ranking
or public label selection is implemented in 3A. Verified records are in
`private_batch.records`; component-specific failures are value-free reason codes in
`private_batch.unavailable`. Unsupported predictor/transformation policies fail with a
fixed `AttributionUnavailable` reason. Unverified native shapes, class mappings, linear
trees, objectives or additive identities never receive guessed explanations. Later
callers must check unavailable components before claiming a complete P50 explanation.
These helpers currently support the existing uncalibrated ordinary GBDT
heads only; future transformations must extend verification before being explained.

`_compare_contributions(earlier, later)` compares records for the same delivery/head
at consecutive hourly origins, requiring identical model fingerprint, recipe, active
component, registry, class and scale. It retains both original ledgers, signed feature/
category deltas, base/raw/output deltas and reconstruction-offset delta. Raw deltas have
the original raw unit; output deltas have the output unit. A switch to another active
head is unavailable for this comparison. Differences describe model contributions from
genuine origin-time predictions; they do not establish revised upstream forecast
vintages or physical causation.

Focused checks for 3A:

```bash
.venv/bin/python -W error::FutureWarning -m unittest forecast_engine.tests.test_explainability -v
.venv/bin/python -W error::FutureWarning -m unittest forecast_engine.tests.test_model_compatibility -v
```

The second module checks the unchanged public caller/backend serializer and native
export through the official validator/scorer on synthetic data. A full-data retraining
comparison is not required for this private helper alone. Full-data performance and
quality claims still require their own approved acceptance runs. Step 3B integrates
safe P50 category labels as described next; application allowlist/display changes
remain separately coordinated work.

## P50 driver labels (Step 3B)

LightGBM prediction now fills the existing optional `top_drivers` field with up to three
category identifiers, separated by semicolons. Each label is selected from a verified
complete explanation of that row's final P50. It does not explain direction/spike
probabilities, P10/P90 or real-world causation. Numerical forecasts, model state,
provenance, public signatures and the 13-column schema are unchanged. Persistence
keeps its existing behavior and remains the default predictor.

Learned feature contributions are summed with signs within each registry category.
For a relative primary prediction, its deterministic published spot reconstruction
offset is added to `spot_price_conditions` exactly once for this ranking. The private
record still distinguishes that offset from learned SHAP effects. The bias/base is
excluded. Categories with exactly zero total are omitted; the remaining categories
are ordered by descending absolute total, with category identifier order breaking
ties. Within-category cancellation can therefore remove a label. Only identifiers
are emitted, never contributions, offsets, base values, feature values or free text.

Direct-price backup rows use the active direct P50 head's contributions. A missing,
duplicate, foreign, blocked or incomplete explanation produces blank text for that
row. Unknown transformation policies, unverified P50 attribution, zero total effects
and unsupported complete decompositions also produce blank text. Persistence rows
never receive LightGBM labels. The ranking validates the identity calibration and
P50-preserving constraint ledger; future calibration/blending must extend verification
before affected P50 labels can be emitted.

Prediction reuses its existing private feature batch and reconstruction/price state.
Only active P50 heads need native contributions for driver selection; classifier and
outer-quantile attribution remain available through the explicit private 3A helper.
No model is refitted. Attribution adds inference work; full-data runtime measurement
and optimization remain separate work. Numeric records never enter ForecastResult,
frame attrs, provenance schemas, application payloads or diagnostics.

Focused checks for this integration:

```bash
.venv/bin/python -W error::FutureWarning -m unittest forecast_engine.tests.test_explainability -v
.venv/bin/python -W error::FutureWarning -m unittest forecast_engine.tests.test_lightgbm forecast_engine.tests.test_model_compatibility forecast_engine.tests.test_experiment_contract -v
```

The first module covers selector/privacy properties, private math and integrated
prediction. The second command covers affected model consumers: numerical/frozen-state
regressions, backend serialization, official validation/scoring of small synthetic
exports and experiment defaults/manifests. These are targeted checks for prediction
assembly changes; no full repository suite or full-data retraining is required solely
to verify optional labels.

### Application coordination handoff

Following explicit user approval after Step 3B review, the backend now accepts the nine
P50 categories below alongside `last_imbalance_price`. The serializer preserves engine
order, removes duplicates and drops the whole value for unknown/mixed unsafe lists.
Verified labels pass through cached JSON and `/api/forecast` when an ML predictor is
supplied through existing trusted composition. The default remains persistence. The
frontend accepts nullable driver strings but currently has no driver display; that
work remains with the frontend owner.

```text
CROSS-BOUNDARY CHANGE NOTICE
Approved change and affected files/components: User-authorized backend/app/schemas.py
allowlist/comment update, backend service/HTTP tests and backend documentation; the
engine-side serializer expectation and this guide were updated to match. No response
field/type change or frontend edit was made.
Reason and expected benefit: Let the application display verified P50 category drivers.
Application/team impact: Preserve last_imbalance_price and existing filtering of unknown
or unsafe text. Labels explain P50 only; relative spot ranking includes a deterministic
conversion offset, not just learned effects. No numeric explanation API is proposed.
Compatibility risks: Misstating the label scope or weakening the unknown-text filter.
Coordination or migration steps: Restart prepared services to use the updated boundary.
Valid combinations, rejection of unknown/private values and genuine native engine to
HTTP propagation are tested. Coordinate friendly labels/display with the frontend owner.
Can engine work proceed? Yes; supported category strings now pass through the backend.
Approval status: Explicit user authorization given for this backend follow-up. Frontend
display changes and default model activation remain separately coordinated work.
```

Registry identifiers: `renewable_production`, `consumption`, `production`,
`cross_border_flows`, `neighboring_markets`, `balancing_conditions`, `historical_prices`,
`spot_price_conditions`, `calendar_horizon`. Some require optional feature groups and
will not appear with the current minimal recipe. Do not expose private numerical
contribution records to implement this identifier-only display.

## Preregistered target/feature ablations (Step 4A)

`recipes.py` defines four fixed real-data configurations. They all use the original
30-round, 15-leaf recipe, minimum 20 rows per leaf, learning rate 0.05, L2 1.0,
seed 2026, one native CPU thread and independent per-head label eligibility:

| Recipe ID | Target | Features/hypothesis |
|---|---|---|
| `direct-control-v1` | Direct | Original minimal features; target-mode control. |
| `relative-control-v1` | Spot-relative | Same features/settings; target-mode control. |
| `relative-wind-load-v1` | Spot-relative | Add published delivery wind and load forecasts. |
| `relative-mfrr-v1` | Spot-relative | Add latest up/down mFRR prices/activations and their ages. |

Four of the six shared 4A/4B recipe slots are allocated here, including both ML
controls. Two remain for 4B. Persistence is a separate reference. Fold repetitions do
not add recipe slots. Synthetic verification is not a real-data selection experiment.
Solar, ramps, aFRR, production/consumption observations, neighboring/cross-border
features, head-specific subsets, horizon groups and ensembles remain untested unless
separately preregistered within the remaining scope/budget. No new feature definitions,
forecast vintages, calibration or automatic model activation are introduced here.

Create a plan in a fresh ignored directory before any real-data trial:

```bash
.venv/bin/python -m forecast_engine.experiments.compare plan --output-dir baseline_output/engine/step-4a-acceptance-01
```

The plan freezes hypotheses, recipe/feature settings, two existing earlier folds,
source/tool/package fingerprints, validation-reuse acknowledgement, retention rules
and budget allocation. Its checksum is recorded separately. Step 2C validation was
already inspected and informed the relative-only feature ablations; this is documented
development reuse, not a claim that validation remained untouched. Selection here
uses only the two pre-validation assessment windows. Do not edit package sources or
the plan while executing a registered study.

For each of `fold-1` and `fold-2`, run persistence once and each of the four recipes
once into the directory layout below. Replace the fold and recipe IDs explicitly:

```bash
.venv/bin/python -m forecast_engine.experiments.run --period fold-1 --model persistence --measure-attribution --output-dir baseline_output/engine/step-4a-acceptance-01/fold-1/persistence-v1
.venv/bin/python -m forecast_engine.experiments.run --period fold-1 --recipe direct-control-v1 --measure-attribution --output-dir baseline_output/engine/step-4a-acceptance-01/fold-1/direct-control-v1
```

`--model` and `--recipe` are mutually exclusive; omission still selects persistence.
`--measure-attribution` profiles prediction with cProfile and extracts only the private
P50 driver function's cumulative time. That time is part of prediction, not an
additional cost to add again. Prediction includes profiling overhead. Feature
availability counts are rebuilt privately with the unchanged as-of builder and timed
separately; no feature values are serialized. Ordinary runs without this flag retain
their existing prediction path and do not perform the extra diagnostics.

Each complete forecast is structurally validated before scoring. The measured run also
scores exactly those forecast rows whose delivery spot was nonmissing and published
by their own origin. It uses the validated export's timestamp spelling and numerical
precision. When this subset equals the full grid, scores are reused explicitly; when
empty, losses are null and counts zero. Partial subsets are diagnostic CSVs, not valid
complete-horizon submissions. The official scorer computes all losses unchanged.

After all ten runs complete:

```bash
.venv/bin/python -m forecast_engine.experiments.compare report --output-dir baseline_output/engine/step-4a-acceptance-01
```

The report checks source/recipe/artifact integrity and identical fold origins, outcome
hashes, forecast grids and per-metric matched counts, including shared-spot cohorts.
For pooling, it removes each fold's deliveries outside its assessment interval before
combining forecasts and actuals. Otherwise later-fold actuals would incorrectly relabel
an earlier fold's unscored tail. Original 40-step forecasts remain intact. Pooled
diagnostic rows are scored with unchanged `score.py`; matched counts must equal the
sum of the individual folds for each metric. Private pooled actuals include restricted
spot prices and must stay ignored under the README's licensing/deletion rules.

Retention requires at least a 1% pooled reduction in one of the four losses, with
no loss worsening by more than 1% on either fold or pooled rows. Absolute tolerance
is 0.000001, including zero-reference cases. Controls are compared with persistence;
feature variants must pass against persistence, the relative control and the selected
control. Passing candidates are ordered by pooled MAE, then pinball, spike Brier,
direction Brier and recipe ID. This is a predeclared selection priority, not an official
competition-points formula. Coverage and costs remain visible diagnostics; coverage
alone cannot promote a recipe. If nothing passes, keep persistence. A provisional
choice does not activate a model in the backend.

`comparison/comparison.json` includes fold and pooled losses/coverage/counts, shared
cohort results, training eligibility, feature availability, path counts, per-horizon
diagnostics, costs, decisions and remaining budget. `comparison.md` is a short summary.
Comparison output must be fresh; completed evidence is not overwritten. Jobs may run
in separate local processes, but overlapping workloads are not controlled runtime
benchmarks. Windows execution and final deployment costs need separate verification.

Focused checks for the experiment changes:

```bash
.venv/bin/python -W error::FutureWarning -m unittest forecast_engine.tests.test_ablation -v
.venv/bin/python -W error::FutureWarning -m unittest forecast_engine.tests.test_experiment_contract -v
```

The synthetic study exercises every registered recipe, both small folds, partial
availability, official validation/scoring, pooling boundaries and tamper rejection.
No application, original CLI, public forecast interface or dependency change is needed.
Stop after 4A evidence and review; do not consume the reserved 4B slots or start Step 5.
