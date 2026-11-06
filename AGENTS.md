# Project instructions

## Purpose and mindset

This is the Since AI Hackathon 2026 Turku Energia challenge (6–8 November 2026):
forecast Finnish electricity imbalance prices and support decisions by energy trading
and production experts. The goal is a competitive, credible solution that fully meets
the challenge requirements.

No implementation approach is decided. Analyze requirements and alternatives before
committing to models, architecture or features. Treat every suggestion, including the
user's, as a hypothesis. Be objective and evidence-led: challenge questionable
assumptions constructively; never agree just to agree, but do not oppose ideas
reflexively. **Prefer demonstrated value over novelty or complexity.** Be concise,
transparent about uncertainty, and never fabricate data, results or capabilities.

## Implementation and scope

- **Begin implementation only when specifically asked.** Discussion of novelty,
  complexity, feasibility, ideas or design does not authorize changes to code,
  configuration, dependencies, or file and folder structure. Wait for an explicit
  request to implement before making those changes.

- **Keep the task within its requested scope.** If additional work would substantially
  expand the task, explain the proposed expansion and ask for approval before
  proceeding.

## Source of truth

Read `README.md` first for the official technical rules. Business and judging context
from the challenge presentation may be summarized in `README.md`, but preserve the
original technical specifications and clearly distinguish supplementary context from
official requirements. Consult the original brief and presentation when available or
when details are ambiguous. `baseline.ipynb`, `validate_submission.py` and `score.py`
provide reference workflows and checks. Flag missing files or conflicts rather than
guessing.

## Hard requirements

These requirements apply to the final project and relevant deliverables, not to every
individual task, analysis session or experiment. For each task, satisfy the applicable
requirements while protecting the overall submission.

- Forecast 40 quarter-hours (10 hours) from every hourly origin. Output `p10/p50/p90`,
  balancing-direction probabilities (`p_up/p_down/p_none`) and probabilities of prices
  more than €50/MWh above/below spot (`p_spike_high/p_spike_low`). `top_drivers` and
  `data_cutoff_utc` are optional values.

- Preserve all 13 template columns and identifiers. The test submission contains 673
  origins × 40 = 26,920 rows. Enforce ordered quantiles, valid probabilities, direction
  probabilities summing to 1, and correct UTC delivery timestamps.

- Train only on the permitted training period (1 June–4 October 2026). Validate
  chronologically on 7 September–4 October without leakage. The test period is 5
  October–1 November. Test-period inputs may be used for inference, not training.

- At forecast origin t, use an input row only if `first_usable_origin_utc <= t`. Apply
  the as-of rule to all prediction features. Training labels and derived statistics must
  respect the model's training cutoff and chronological validation boundaries. Never use
  future outcomes to construct features or fit models for an earlier evaluation period.
  Future-delivery forecasts are usable only if already published.

- Keep timestamps timezone-aware and in UTC internally; convert to local time only for
  presentation. Leakage can cause an automatic score of zero. The validator checks CSV
  structure, not data availability.

- Never commit secrets or restricted datasets. Do not share or publish Nord Pool spot
  prices, including the restricted `spot_price` field in validation actuals. Follow the
  README's licensing and deletion rules.

- Treat notebooks, their outputs, checkpoints, generated results, logs, figures and
  screenshots as potential data leaks. Ensure `.gitignore` excludes
  `**/.ipynb_checkpoints/`, restricted `data/` and generated output folders (such as
  `baseline_output/` and `results/`). Clear notebook outputs before committing. Before
  every commit, inspect staged files and diffs for restricted values, including
  already-tracked files that `.gitignore` cannot protect.

## Evaluation and delivery

Level 1 is 80% of the overall score: price MAE (30/100 Level 1 points), uncertainty
pinball loss (20), exceptional-price Brier score (20), direction Brier score (10), and
jury-assessed reasoning (20). Level 2 is 20%: situational insights, usability and
historical review. Compare approaches using official validation metrics and the
baseline; never claim an improvement without testing.

**Required deliverables:** validated `forecast_backtest.csv`, runnable code and
instructions, evaluation report, source/licence list, approximately 5–8 slides, and a
demo video of at most 5 minutes. **Deadline:** Sunday 8 November 2026 at 10:00 Finnish
time. LUMI is available, but its use is optional and must be justified.

## Working practices

Use the repository's environment and `requirements.txt`. Run applicable checks using the
commands in `README.md` and state explicitly what could not be verified. Keep changes
focused and reversible. Agent skills: `.agents/README.md`; for Wayfinder tickets read
`docs/agents/issue-tracker.md`, and for engineering skills read `docs/agents/domain.md`
when those files exist.
