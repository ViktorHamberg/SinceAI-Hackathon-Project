# Choose the starter-code reuse boundary

Parent: [First working forecasting engine](../map.md)
Label: wayfinder:grilling
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: none

## Question

How can separate engine files reuse baseline loading, calibration, prediction, and export behavior without editing the notebook or other starter files? Compare practical reuse approaches, then select the smallest boundary that permits predictor replacement. Call the official validator and scorer unchanged.

## Comments

### 7 November 2026 — Requirement and options; awaiting decision

The user requires an importable Python module/package directly callable by a future application. New notebooks may experiment, test, and visualize by importing the engine; core logic must live in Python source. Preserve all original starter files unchanged. This explicit requirement is recorded in the map's Notes.

Read-only source inspection found reusable ordinary functions in baseline.ipynb: rows_available_at(), read_long(), series(), persistence_at(), calibrate(), build_forecast(), write_submission(), and read_origins(). Notebook setup introduces global paths, constants, current-working-directory assumptions, printing, and execution order. make_templates.py, validate_submission.py, and score.py provide guarded command-line entry points. Existing requirements cover pandas/numpy and parquet loading; no Jupyter runtime is needed for a separate engine.

Options to discuss:

- Extract/adapt into one importable Python module: quickest initial structure, but mixes responsibilities as the engine grows.
- Extract/adapt into a small Python package: retain starter algorithms with explicit data/configuration and fitted state; separate shared data/availability handling, replaceable baseline fitting/prediction, and orchestration/export. A thin CLI and future notebooks/application call the same in-memory Python API. Recommended.
- Independently rewrite the baseline in a package: permits a fresh design but duplicates working logic and adds avoidable behavior-comparison risk.

Runtime notebook parsing/execution would keep core logic dependent on the notebook and does not meet the requested source boundary. One-time extraction creates intentional duplication against the immutable reference; record source provenance and verify behavior later. Adapt calibration and error handling to the already-resolved leakage safeguards rather than copying their known gaps.

Recommended boundary: separate fitting from prediction, return reusable fitted state, support one origin and a batch without forcing CSV I/O, and avoid data loading, fitting, printing, file writes, or subprocesses merely on import. Explicit I/O adapters and a thin command workflow handle paths, export, and calls to the unchanged template generator, validator, and scorer. Scoring actuals remain outside prediction. The model-specific component owns its fitted statistics and inference; shared availability rules, result structure, and caller workflow remain usable when the predictor is replaced. No plugin framework or speculative abstract hierarchy is needed.

Exact forecast guarantees belong to Specify the forecast output contract; run commands and equivalence tolerances belong to Define the reproducible run and acceptance procedure. This proposal is pending user agreement, not a resolved decision. No implementation has begun.

### 7 November 2026 — Resolution

The user accepted extraction/adaptation into a small Python package and the proposed responsibility boundaries, explicitly requiring separate modules rather than a single Python file. They directed that maintainability, extensibility, and separation of concerns take precedence over minimizing file or class counts, while avoiding unnecessary complexity. This resolves this ticket only; implementation remains unauthorized.

## Answer

### Package and responsibilities

Implement the engine in a directly importable Python package containing separate modules. Its runtime must not depend on parsing or executing a notebook. The future application, a thin command-line entry point, and any new optional notebooks call the same Python engine API.

Separate these responsibilities with cohesive module boundaries:

- **Data and availability:** explicit loading adapters, UTC input handling, and shared as-of selection and safeguards.
- **Baseline predictor:** calibration/fitting, explicit reusable fitted state, and inference. Keep model-specific statistics and prediction logic replaceable behind a clear calling boundary.
- **Orchestration and export:** coordinate single-origin and batch forecasting, return in-memory results, and provide optional CSV export. Keep command-line parsing and official validation/scoring invocations outside the prediction core.

These are responsibility boundaries, not a fixed three-file limit. Use functions for operations, classes where state or lifecycle benefits from encapsulation, and abstractions where they clarify an actual boundary. Choose concrete names, signatures, and module subdivision during implementation within these constraints. Do not introduce a speculative plugin framework or class hierarchy; equally, do not combine distinct responsibilities merely to reduce the number of files or classes.

### Direct application use

Expose fitting and prediction separately with explicit input data and configuration. Fitting returns reusable fitted state; prediction consumes that state without refitting. Support both one origin and a batch, returning results in memory without requiring intermediate CSV files or command-line subprocesses. Preserve shared availability handling, result conventions, and caller workflow when replacing the baseline predictor. Exact forecast-result guarantees remain with Specify the forecast output contract.

Importing the package must not load challenge datasets, fit models, print reports, write files, or start subprocesses. Avoid reliance on notebook setup order, hidden global paths, or the caller's working directory. Explicit I/O adapters handle filesystem operations. Notebooks are optional consumers for experimentation, testing, and visualization; new notebooks import core logic from the package. Preserve the original reference notebook unchanged.

### Starter reuse and safeguards

Perform a deliberate one-time extraction and adaptation of useful starter algorithms into the package. Reuse loading, availability selection, persistence, historical-error calibration, probability estimation, and export behavior where compatible with the agreed requirements. Document the source functions and intentional adaptations. Duplication against the immutable reference notebook is accepted; runtime notebook loading and an independent rewrite of already-useful behavior were rejected as the reuse strategy.

Preserve every original starter file unchanged. Reuse make_templates.py through its existing command interface in the command workflow, and invoke the official validate_submission.py and score.py unchanged rather than duplicating their checks or metrics. These tools are workflow dependencies, not prerequisites for importing or calling prediction. Keep scoring actuals outside prediction generation.

Apply [Define fitting cutoffs and leakage safeguards](01-leakage-safeguards.md) throughout extraction: explicit label-period and availability boundaries, historical inputs reconstructed as of their origins, frozen fitted statistics, per-origin availability, required missing-evidence failures, and provenance. Retain baseline mathematics where compatible; do not copy the known missing-spot fallback or implicit fitting boundaries. Behavior comparison and equivalence tolerances remain with Define the reproducible run and acceptance procedure; no equivalence or performance improvement has yet been demonstrated.

No package, modules, dependencies, or implementation files are created by this decision. No new decision ticket is needed from this resolution; the existing output-contract and acceptance-procedure tickets cover the remaining specified questions.
