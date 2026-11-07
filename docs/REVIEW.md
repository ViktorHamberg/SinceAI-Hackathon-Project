# Independent review before pushing

Use this shared workflow in a separate Codex chat before each push. Both teammates
should use the same version of this file and [AGENTS.md](AGENTS.md).

This is a manual review gate. It does not start an agent, install a Git hook, configure
GitHub protections, or automatically prevent a push.

## 1. Author handoff

After completing one approved step, stop implementation and give the user:

- The approved task/step and its acceptance criteria.
- Branch, base commit and current HEAD; whether the candidate includes committed,
  staged, unstaged or untracked changes.
- The exact files in scope, including new files, and what changed and why.
- Exact checks actually run, their results, environment and relevant output locations.
- Known limitations, checks not run and deliberate deviations from the approved plan.

Use [the implementation plan](docs/first-forecasting-engine-plan.md) and the relevant
resolved [Wayfinder tickets](.scratch/first-forecasting-engine/map.md) when applicable.
Use their final Answers rather than superseded discussion proposals.

Keep the candidate stable during review. A reviewer in the same project checkout can
inspect uncommitted work. A reviewer on another machine needs the identical committed
version or a complete patch including new files; a prompt alone does not transfer code.
Do not assume an author summary or an old test log establishes correctness.

## 2. Reviewer role and scope

Review independently against the user's request, approved scope, AGENTS.md, the official
[README](README.md), and relevant decisions. Inspect the actual files and diff before
accepting the author's explanation. Review only the requested change and directly
affected behaviour; do not turn review into a redesign or implementation session.

- Do not edit source, tests, configuration or documentation, or apply automatic fixes.
- Do not stage, commit, push, merge, switch branches, reset or discard changes.
- Do not install dependencies or change the environment without explicit authorization.
- Read-only inspection and relevant existing tests are allowed. Use the project
  environment; keep generated test outputs in ignored storage or temporary directories.
- Report missing prerequisites and verification limits. Never claim an unrun check
  passed, and distinguish an environment restriction from a defect in the change.

First establish the review base and candidate. Useful read-only commands include:

```text
git status --short
git diff --cached
git diff
git ls-files --others --exclude-standard
```

For committed changes, also inspect `git diff <BASE_COMMIT> HEAD` using the agreed base,
not an assumed previous commit. Inspect the content of relevant new files: ordinary
`git diff` does not include untracked files. Check staged and unstaged changes
separately, since they can differ. If the scope/base cannot be established, ask for
clarification before issuing approval. Never fetch or transmit restricted data as
part of a review.

## 3. What to check

Apply checks appropriate to the approved step. Step 1 contracts do not need to implement
Step 2 data handling or the later forecasting engine. Documentation-only changes need
documentation checks rather than an unnecessary full forecasting run.

| Area | Review focus |
|---|---|
| Correctness and scope | Required behaviour, errors, regressions, maintainable responsibility boundaries and acceptance criteria; flag unapproved scope expansion. |
| Historical availability | Inputs available at each origin; delivery and publication cutoffs for fitting labels; all dependencies of derived statistics; no future-dependent filling or test-outcome fitting. |
| Fitted state and provenance | Frozen statistics during inference, sufficient evidence, separate metadata and no reliance on DataFrame attrs. Apply the resolved ticket requirements where implemented. |
| Forecast contract | Required columns/types, complete horizons, UTC arithmetic, finite values, negative-price support, valid quantiles/probabilities and nullable optional fields. No fabricated probabilities or silent omission/repair. |
| Starter preservation | Unchanged reference notebook, algorithms, templates, requirements, validator and scorer unless a specific change was approved. Compare behaviour with justified safety differences documented. |
| Verification | Meaningful tests for the current step, actual results, reproducible commands and relevant Windows/macOS path, installation and timezone behaviour. |
| Data protection before push | No secrets, restricted datasets or restricted values in changed/staged/committed files, notebook outputs, logs, reports or artifacts. Gitignore does not protect already-tracked content. |

For code changes, normally run the existing focused suite in the project environment:

```text
python -m unittest discover -s tests -v
```

On Windows without activation, use `.venv\Scripts\python.exe`; on macOS use
`.venv/bin/python`. Additional checks should address the actual change. Full baseline
evaluation is required when the step or affected behaviour calls for it, not for every
documentation or contract-only change. Do not invent competition scores or claim
structural validation proves leakage safety.

## 4. Verdict

Return exactly one top-level verdict: **APPROVE** or **BLOCK**.

- **APPROVE:** no blocking issue found in the identified candidate, with sufficient
  verification for its scope. State residual limitations and nonblocking suggestions.
- **BLOCK:** a concrete correctness, leakage, data-exposure, scope or acceptance problem,
  or a material verification gap that prevents responsible approval. Explain what is
  wrong and the smallest correction or evidence needed. Do not block on stylistic
  preference, speculative future features or unrelated refactoring.

Use this response structure:

```text
Verdict: APPROVE | BLOCK
Reviewed scope: task/step, branch, base commit, HEAD and exact candidate files/diff

Blocking findings:
- None, or severity + file:line + consequence + evidence + required correction.

Checks actually run:
- Command, environment, result and relevant evidence.

Not verified:
- Missing checks/prerequisites and their impact, or none.

Nonblocking suggestions:
- Optional improvements, clearly separated from blockers.
```

Identify the reviewed version explicitly. For uncommitted candidates, record the file
list and a patch or content fingerprint sufficient to distinguish later changes.
Approval covers that candidate only. After a fix or other change, re-review the affected
diff and relevant checks; do not keep an earlier approval attached to different code.

## 5. After review

The user brings findings to the implementing chat. That chat fixes blockers only when
authorized, reports the changes/checks, and supplies an updated handoff. The reviewer
then checks the revision. Before push, confirm the proposed commits contain the reviewed
changes and no additional unreviewed content.

An APPROVE verdict is a review recommendation, not proof of correctness or permission
to commit, push, merge, or begin the next implementation step. The user retains those
decisions. No reviewer should silently perform the author's fixes.

## Reusable reviewer prompt

Paste this into a separate chat opened in the candidate project checkout. Replace the
bracketed fields and include the author's handoff.

```text
Act as the independent reviewer for this change.
Read AGENTS.md and REVIEW.md, then the relevant approved plan and resolved tickets.

Task/step: [approved scope]
Branch: [branch]
Base commit: [full commit ID]
Candidate: [HEAD ID plus committed/staged/unstaged/untracked scope]
Files in scope: [exact paths, including new files]

Inspect the actual changes independently. Treat the author's explanation and test
claims as context to verify. Check relevant new files as well as Git diffs.
Run appropriate existing checks and report what you actually observed.
Do not modify files, install dependencies, stage, commit, push, merge or fix findings.
Return APPROVE or BLOCK using REVIEW.md's response format, with file/line evidence
for blockers and explicit verification limits. Then stop.

Author handoff:
[what changed, why, actual checks/results, known limitations and deviations]
```
