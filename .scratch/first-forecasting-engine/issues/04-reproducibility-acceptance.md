# Define the reproducible run and acceptance procedure

Parent: [First working forecasting engine](../map.md)
Label: wayfinder:grilling
Type: grilling
Status: resolved
Assignee: Codex
Blocked by: 01, 02, 03

## Question

What commands, environment records, input/version identifiers, and checks establish reproducibility? Specify baseline equivalence tolerances, chronological validation, comparison across all scored metrics, leakage evidence, and validation of the 26,920-row test file.

## Comments

### 7 November 2026 — Acceptance proposal; awaiting approval

All three prerequisite decisions are resolved. Claimed by Codex. Reviewed README sections 7.2–7.3, score.py, .gitignore, the existing decisions, and reference notebook source. No notebook, model, or dataset computation was run. The following is a proposal, not a resolved decision or a claim that checks have passed.

1. **Local repeatable workflow.** Use the repository environment and requirements.txt. Document environment setup, a standard-library unittest command, an import/call example, and package CLI commands for validation and test, all using the same engine API. Name the package and exact flags during implementation; the required command behavior is fixed here. Validation generates its own origins/template with unchanged make_templates.py, fits once at the approved validation cutoff, predicts all origins, exports, validates, and scores. Test fits separately at the approved test cutoff, fills the supplied template, exports, and validates; it does not score test outcomes. Write outputs under the already-ignored baseline_output/engine/ tree, with validation/test and repeat runs in separate directories. No network service, container, cloud job, or new experiment platform is required.

2. **Run identity and reproducibility.** Record exact commands/configuration, Python and installed dependency versions, source revision plus dirty-state/source fingerprint, SHA-256 fingerprints of consumed input files and unchanged starter tools/templates, fitting boundaries, provenance, row counts, and elapsed time. Keep manifests and fingerprints local with outputs and omit restricted values and secrets. Repeat the full validation command with identical inputs/configuration/environment in a clean output directory; require identical forecast CSV bytes and equal numeric metric values. Run timestamps and elapsed time in metadata may differ. Also verify single-origin versus batch agreement and direct Python versus CLI agreement on a small representative subset. Record unavailable verification explicitly; do not claim cross-platform bitwise reproducibility.

3. **Focused correctness and leakage checks.** Use small synthetic fixtures for cutoff boundaries, partial historical horizons, future-delivery published inputs, missing/late rows, empty calibration components, and excluded-label/unavailable-input invariance. Check per-origin and fitting dependency availability, label intervals, frozen fitted state, and the required provenance. Check the 13-column contract, complete horizons, finite/valid values, optional nullable fields and populated-value export preservation, UTC/delivery arithmetic including DST dates, and clear failures. Use focused import/API/CLI smoke checks; importing must not initiate data loading or computation. Hash original starter files before/after verification to confirm preservation. Keep scoring actuals outside engine prediction. This is a small risk-focused test suite plus full chronological validation, not exhaustive coverage or a new testing framework.

4. **Independent baseline and fair comparison.** Generate validation reference forecasts from the unchanged starter notebook, keeping executed notebook output in an ignored separate file or transient copy; do not save outputs to the original or enable organiser mode. This optional reference-only notebook workflow must not become an engine runtime dependency. Validate and score reference and engine using identical validation template keys, actuals file, and spike margin 50. Require equal scored-row counts separately for price, spike, and direction; retain all horizon-tail rows even where actuals are absent. Compare score_summary.csv numeric values, not rounded Markdown: MAE, p10/p90 pinball and their mean, spike high/low Brier and their mean, direction Brier; also report interval coverage and score_by_horizon.csv summaries. --baseline-summary compares MAE only and does not replace this comparison.

5. **Baseline-equivalence gate.** Preserve reference rounding (prices to four decimals, probabilities to six, CSV numeric export to six). Require exact identifiers/keys and absolute differences at most 1e-6 in the eight required forecast columns after export; exclude optional fields from reference parity. Require absolute differences at most 1e-5 for MAE, pinball, and Brier metrics on identical scored rows. These are numerical parity tolerances, not accuracy-improvement targets. Report coverage differences separately because interval-boundary rounding can affect inclusion. Investigate all larger differences; explain intentional differences from approved safeguards with source/evidence, and do not silently relax tolerances or weaken leakage rules. If legitimate evidence eligibility differs, disclose that reference parity is not established; do not label a materially different result baseline-equivalent without further review.

6. **Acceptance evidence and handoff.** Require focused tests passing, chronological validation structurally passing with zero errors, recorded warnings reviewed, repeatability/parity checks passing, complete leakage evidence, and a final test CSV structurally passing with exactly 673 origins and 26,920 rows. Save commands/exit codes, validator reports, score files, comparison summary, provenance and manifest under ignored outputs. Document runnable setup/API/CLI instructions and a concise evaluation report explaining baseline equivalence rather than claiming improvement. Test-period quality cannot be verified locally without organiser-held actuals. Do not use final competition points or improved accuracy as the gate for this first-engine milestone. Original data licensing and notebook-output protections apply throughout.

Official command patterns to retain in the documented workflow (paths resolve from the repository root):

```bash
python make_templates.py --test-start 2026-09-07 --test-end 2026-10-04 --output-dir baseline_output/engine/validation
python validate_submission.py --backtest baseline_output/engine/validation/forecast_backtest.csv --origins baseline_output/engine/validation/forecast_origins.csv
python score.py --submission baseline_output/engine/validation/forecast_backtest.csv --actuals data/actuals_validation.csv --spike-margin 50 --output-dir baseline_output/engine/validation/score --baseline-summary baseline_output/validation/score/score_summary.csv
python validate_submission.py --backtest baseline_output/engine/test/forecast_backtest.csv --origins forecast_origins.csv
```

Engine generation commands must run before the corresponding validator/scorer; they do not exist yet. The reference baseline score path above assumes the documented original notebook workflow has completed. Reference generation failures must be reported rather than silently using an old or incompatible score file.

Pending user approval, keep this ticket claimed and the map open. After approval, assess whether any concrete in-scope decision remains. If none does, resolve this ticket, index it in the map, clear the generic fog, mark planning complete, and use the four decisions as the implementation handoff. Planning completion is not implementation or submission acceptance, and does not authorize implementation.

### 7 November 2026 — Resolution

The user approved Q1–Q4 with a refinement: numerical baseline tolerances are equivalent-behavior targets, not absolute acceptance requirements where agreed leakage safeguards or justified corrections produce differences. Such differences must be documented and explained. Baseline comparison must remain proportional to the hackathon timeline; exact notebook reproduction must not consume excessive time once correctness, validation, and reproducibility are demonstrated. The following Answer is authoritative where it qualifies the initial proposal.

## Answer

### Reproducible workflow

Adopt the local workflow, run identity records, focused tests, and official command patterns proposed above. Use the repository environment and requirements.txt, a documented import/call example, thin package CLI commands for validation and test, and standard-library unittest checks. Concrete package names and flags are implementation details to record in the upcoming incremental implementation plan and runnable instructions.

Validation generates separate templates, fits once using the approved chronological cutoff, forecasts every origin, exports, validates with unchanged validate_submission.py, and scores with unchanged score.py. Test fits separately using the approved test cutoff, fills the supplied template, and validates all 673 origins and 26,920 rows. Do not fit on test outcomes or attempt local test scoring without organiser-held actuals.

Keep generated artifacts under the ignored baseline_output/engine/ tree. Record commands/configuration, Python/dependency versions, source revision and dirty-state/source fingerprint, consumed-input and starter-file SHA-256 fingerprints, fitting boundaries, provenance, counts, runtime, and command exit codes. Keep restricted values and secrets out of reports. Repeat the full validation workflow with the same inputs, configuration, and environment in a separate output directory; require byte-identical forecast CSVs and equal numeric scores. Timing metadata may differ; cross-platform byte identity is not required. Compare direct Python versus CLI and single-origin versus batch results on a representative subset.

### Focused checks and official validation

Use small synthetic tests for the previously agreed leakage rules: exact availability boundaries, label-period bounds, partial historical horizons, already-published future-delivery inputs, missing evidence, excluded-label/unavailable-input invariance, dependency provenance, and frozen fitted state. Test UTC/DST delivery arithmetic, the 13-column contract, complete horizons, finite valid predictions, nullable optional fields and preservation of populated optional values, clear failure behavior, and import/API/CLI use without import-time work. Keep scoring actuals separate from prediction and verify starter-file hashes remain unchanged. No new testing platform or exhaustive coverage requirement is introduced.

Run full chronological validation and final test structural validation. Both must have zero validator errors; record and review warnings. Passing structural validation does not establish absence of leakage. Preserve the already-agreed evidence for all fitting and inference dependencies.

### Proportional baseline comparison

Generate an independent validation reference from the unchanged starter notebook, saving executed output separately under ignored storage or using a transient copy, with organiser mode disabled. This reference-only workflow must not become a package runtime dependency. Use identical template keys, actuals, spike margin 50, and scored-row counts for price, spikes, and direction. Retain unscored horizon-tail forecasts.

Compare numeric score CSVs for MAE, p10/p90 pinball losses and their mean, high/low spike Brier scores and their mean, and direction Brier. Report coverage and horizon summaries. The official --baseline-summary option compares MAE only. Keep commands, input identity, scoring counts, and reference provenance sufficient to make the comparison credible.

Use reference rounding where practical and retain the proposed targets: exact identifiers; absolute forecast-value differences at most 1e-6 after export; absolute MAE, pinball, and Brier differences at most 1e-5. Optional fields are excluded from parity. Coverage differences are reported separately. These tolerances diagnose equivalent behavior; they are not unconditional acceptance gates or accuracy-improvement requirements.

For differences caused by agreed leakage safeguards or justified corrections, record the affected behavior, source or eligibility change, numerical/metric impact, and supporting correctness evidence. Preserve the safer behavior and report whether numerical equivalence was actually achieved. Unexplained material discrepancies still require investigation; documenting a number alone does not establish correctness. Do not weaken safeguards, silently relax targets, claim untested improvement, or spend excessive time making the package reproduce notebook-specific details. A correct, officially validated, reproducible engine with evidence-backed differences may satisfy this milestone without exact notebook parity. If reference generation cannot be completed, explicitly report that comparison as unverified rather than fabricating or substituting incompatible results.

### First-engine acceptance and handoff

Accept the first engine when focused checks pass, chronological validation and the complete test file pass official structural validation, repeatability and leakage evidence are recorded, and baseline comparison is performed with either target agreement or documented justified differences. Retain manifests, validator reports, score files, comparison findings, and provenance locally; provide runnable setup/API/CLI instructions and a concise evaluation report. No improved-accuracy or competition-points threshold is required. Any unverified item remains explicit; completion of this planning map does not mean that these engineering checks have been run or passed.

All four decision tickets are now resolved. No concrete in-scope planning question remains: fitting/data safety, package boundaries, output guarantees, and run/acceptance procedure are specified. Clear the map's generic fog and mark the planning effort complete. The four resolved tickets are the implementation handoff; no additional specification or implementation artifact is needed in this session.

The next step is a short incremental implementation plan, with each step requiring explicit user approval before Codex proceeds with that step. This instruction governs future execution; approval of this decision does not approve any implementation step. Do not create that plan or begin implementation in this session.
