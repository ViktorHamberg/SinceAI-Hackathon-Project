# First working forecasting engine

Label: wayfinder:map
Status: resolved

## Destination

Define an implementation-ready path to a reproducible, leakage-safe, baseline-equivalent forecasting engine. It must produce the official 26,920-row test submission, pass the unchanged validator, support chronological validation against the official baseline, and document the 13-column output interface.

## Notes

- Use Wayfinder, grilling, and domain-modeling with the local Markdown tracker.
- Run locally through a documented command; require no deployed services.
- Preserve all supplied starter files, including the notebook, templates, validator, and scorer.
- Reuse existing functionality where practical. Put our development in separate files.
- The engine must be a directly importable Python package containing separate modules, callable by a future application. New optional experiment, test, and visualization notebooks must import its core logic. Preserve the original starter notebook unchanged.
- Keep forecasting logic replaceable; advanced model selection remains undecided.
- Use the supplied data initially and protect restricted data in every artifact.
- Plan for the 8 November, 10:00 Finnish-time deadline.
- This map plans the engine; it does not authorize implementation.
- Planning is complete: all four decision tickets are resolved and no in-scope decision remains before incremental implementation planning. No engine has been implemented or accepted by this planning closure.
- Next, create a short incremental implementation plan. Each step requires explicit user approval before Codex proceeds with it; no implementation step is approved by closing this map.

## Decisions so far

- [Define fitting cutoffs and leakage safeguards](issues/01-leakage-safeguards.md): Verified UTC fitting boundaries; freeze statistics from eligible, cutoff-available labels, apply per-origin availability, fail on missing essential evidence, and require leakage provenance and invariance checks.
- [Choose the starter-code reuse boundary](issues/02-starter-reuse.md): Extract/adapt starter algorithms into an importable package with separate modules for cohesive responsibilities, reusable fitted state, and shared application/CLI/notebook calls; preserve starter files and apply the agreed safeguards.
- [Specify the forecast output contract](issues/03-output-contract.md): Return a complete valid 13-column DataFrame matching the official CSV; keep optional fields empty initially but support future values without public-interface changes, with full provenance separately accessible.
- [Define the reproducible run and acceptance procedure](issues/04-reproducibility-acceptance.md): Use documented local runs, focused leakage/correctness checks, repeatability and official validation; compare baseline behavior proportionally, treating numerical tolerances as targets and documenting justified differences.

## Not yet specified

None. The implementation-ready planning destination has been reached; the four resolved tickets form the handoff. Concrete code names and step sequencing belong to the upcoming incremental implementation plan.

## Out of scope

Accuracy improvements beyond baseline equivalence; external model/API selection; additional data sources; UI and advanced features; deployed APIs, databases, and cloud infrastructure. These remain possible later work.
