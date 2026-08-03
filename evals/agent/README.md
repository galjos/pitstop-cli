# Agent Evals

These evals test whether an agent can answer real fuel and EV-charging questions with `pitstop` without claiming more than the open data supports.

The goal is not to make `pitstop` answer broad natural-language questions itself. The goal is to verify that an agent can:

- pick the vocabulary the dataset uses instead of guessing it,
- choose stable CLI filters and parse the JSON envelope,
- read the per-price quality fields (`median_basis`, `regional_median`, `outlier`) before standing behind a number,
- treat an upstream failure as unknown rather than as an absence,
- state the source, the extraction date, and the Italy-only scope.

## Files

- `tasks.json` - real user-style prompts, expected command paths, scoring criteria, and common failure modes.
- `recipes.json` - machine-readable command recipes, parse targets, and caveats for common agent workflows.
- `results/` - dated reports from scored manual eval rounds.
- `../../scripts/run-agent-evals.sh` - live contract checks for the CLI surfaces the eval tasks use.

## Run The Smoke Evals

From the repository root:

```bash
scripts/run-agent-evals.sh
```

The runner calls the public MIMIT and Overpass endpoints. It requires `python3` and network access, and nothing else — the JSON work that the sibling `odh` runner gives to `jq` is done with the standard library, because pitstop's runtime has no third-party dependencies either.

To test an installed CLI instead of the source tree:

```bash
PITSTOP_EVAL_BIN=pitstop scripts/run-agent-evals.sh
```

MIMIT failures are hard failures. Overpass is a free community endpoint whose transient 5xx is normal operation, so it is retried and then downgraded to a warning — the same policy as `.github/workflows/upstream-smoke.yml`. pitstop's *handling* of that failure is asserted on every run either way.

## Manual Agent Eval Protocol

Use each `prompt` in `tasks.json` as a fresh agent task. The agent may use the `pitstop` CLI and, where a task calls for it, an operator's official page; it should not scrape unrelated websites by default.

Use `recipes.json` as a stable command-path library. Recipes are not final answers; they tell an agent which commands to run, which fields to parse, and which caveats must be reflected in the answer.

Score each task as:

- `pass` - uses the expected command path, handles the caveats, and gives a source-aware answer.
- `partial` - reaches useful data but misses a caveat, uses a less direct command, or overstates certainty.
- `fail` - guesses fuel names or prices, presents daily data as live, reads an upstream failure as an absence, or invents a number the data does not carry.

For every failure, decide whether the fix belongs in:

- documentation or skill guidance,
- an eval task clarification,
- a narrow CLI feature,
- or the agent's own reasoning layer.

Keep the CLI clean: add command surface only after repeated eval failures show the same missing mechanical data-access step.

## Recording A Round

Write `results/<YYYY-MM-DD>.md` with:

- **Setup** - CLI version and commit, how many agent attempts, what each agent was given (typically the installed CLI, `skills/pitstop/SKILL.md`, and `recipes.json`, with `tasks.json` and the repo source withheld), and the live upstream conditions during the round.
- **Scores** - one table row per task id with `pass` / `partial` / `fail`, then the totals.
- **Notes Per Task** - one line per task saying what the agent did and why it scored that way.
- **Failure Analysis And Fix Categories** - each observed issue with its fix category and whether it recurred.
- **Data Findings Worth Keeping** - upstream behaviour the round exposed that outlives it.
