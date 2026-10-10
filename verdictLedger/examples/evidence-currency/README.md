# Evidence currency: a worked example

This folder shows how verdictLedger measures **evidence currency** on a small LLM application,
built as a throwaway git repository. It runs in a few seconds.

This is a single-author proof of concept, built for and used in one dedicated environment. It demonstrates the measurement; it is not a production or complete tool.

**Requirements:** Python 3.11 or later and git 2.28 or later, on PATH. Nothing needs to be
installed with pip; the code uses only the Python standard library. Use a full checkout of this
repository, because `verdictLedger/` imports the shared `mcpcommon/` package that sits beside it.
Developed and tested on Windows; nothing in it is platform-specific.

## The metric

A *check* (an evaluation run, a red-team review, a scanner, a human review) produces a *verdict*
about some files. verdictLedger calls a check a **step**, and the output uses that word. Each
recorded verdict names the step, and for every file it covers, the file's path and its git blob
id (git's hash of the file's bytes). The record claims the step examined exactly those bytes.

At a given git revision, for each step and each file in that step's scope, exactly one of three
things is true:

| state | meaning |
|---|---|
| **current** | a verdict exists for this step at these exact bytes |
| **stale** | a verdict exists for this step and this path, but only at other bytes |
| **never examined** | no verdict exists for this step and this path at any version |

**Evidence currency** for a step is `current / in_scope`, where `in_scope = current + stale +
never_examined`. The total is computed the same way over all (step, file) pairs of the
applicable steps.

Three reporting rules are part of the method:

1. **The counts are always reported with the ratio.** "Stale" (examined, then changed) and
   "never examined" call for different follow-up, a re-run and a first run, so they are never
   combined into one number.
2. **A step that does not apply is not 100%.** It is reported as *not applicable*, with
   currency `null`, and is left out of the totals. The causes are listed below.
3. **A current verdict counts as current whatever it recorded:** PASS, FAIL or UNDECIDED.
   Currency is a property of the evidence, not of the outcome. The ledger reports outcomes
   separately.

What the metric does and does not establish:

- **It measures recorded verdicts, not checks that ran.** A record is validated before it is
  stored. Validation checks the record's structure and internal consistency. It does not re-run
  the check, so the metric is only as trustworthy as whatever writes the records.
- **Only the files in `in_scope` decide current versus stale.** A record can also name the
  program that produced it (the example names its evaluation harness). That program is not in
  `in_scope` unless it is declared as a switch (see below), so editing it does not change
  currency. The ledger's separate gate decision does react: the step's `status` field in the
  JSON output becomes `STALE`. That word is a gate status and is unrelated to the stale count
  above. The example leaves its harness undeclared on purpose, to keep the scenario to the
  four files the evaluation covers. Declaring it adds one file to `in_scope`, and editing it
  then makes that file stale: 4 of 5 current, which a test pins.
- **Verdicts are matched by path and content.** A file renamed without changing its bytes has a
  new path, so it counts as never examined until a verdict names the new path. A recorded
  file that carries no blob id cannot be matched to any content, and it also counts as never
  examined.
- **Per-file currency is finer than a per-commit check.** A coarser check, "were these results
  recorded at an older commit than the release?", flags any change at all, including one that
  touches no evaluated file. Currency names which files moved and which were never examined.

## Run it

From the `verdictLedger/` directory:

```
python examples/evidence-currency/run_example.py
```

The script:

- creates a temporary directory and prints its path;
- builds a git repository there;
- records verdicts through the ledger's own command line, so each one is validated like any
  real record;
- prints the metric after each stage.

The safety evaluation is simulated: the script records its result and does not run a model.
Nothing outside the temporary directory is touched.

## The scenario

The repository is a small LLM application: a system prompt, a guardrail policy, one tool
definition, a safety evaluation set, and the harness that runs the evaluation. The
configuration in `config/` defines two steps:

| step | scope | in the example repository |
|---|---|---|
| `safety_eval` | `prompts/system.md`, `guardrails/policy.yaml`, `tools/*.json`, `evals/safety_set.jsonl` | four files, later five |
| `model_card_review` | `MODEL_CARD.md` | no such file, so the step does not apply |

The script works through four stages. These are the `safety_eval` numbers it prints:

| stage | what happens | in scope | current | stale | never examined | currency |
|---|---|---|---|---|---|---|
| 1 | the safety evaluation runs and passes on all four files | 4 | 4 | 0 | 0 | 100% |
| 2 | `prompts/system.md` is edited | 4 | 3 | 1 | 0 | 75% |
| 3 | a new tool definition, `tools/browse.json`, is added | 5 | 3 | 1 | 1 | 60% |
| 4 | the safety evaluation is re-run over all five files | 5 | 5 | 0 | 0 | 100% |

At stage 3 the script also prints what a pass-only view of the same records says: **4 of 4
recorded results PASS**. Every recorded result is still a pass. But one describes a prompt that
no longer exists, and the new tool has no result at all. Currency reports this as 3 of 5.

`model_card_review` is reported as not applicable at every stage and never enters the totals.
`safety_eval` is the only applicable step, so the TOTAL line equals its line.

The last stage also prints the result as JSON. Each step there has a `status` field: the
ledger's separate pass/block decision under its configuration. The currency figures do not
depend on it.

## Using it on your own repository

Run from the `verdictLedger/` directory. `--repo` and `--data` are global options, so they come
before the command name:

```
python -m core.cli --repo <git-repo> --data <records.jsonl> evidence-currency --ref HEAD
python -m core.cli --repo <git-repo> --data <records.jsonl> evidence-currency --ref HEAD --json
```

You also need to supply configuration and record verdicts:

- **Configuration.** Give the file paths in `ZPLEDGER_POLICY` and `ZPLEDGER_REQUIRED`. Or set
  `ZPLEDGER_CONFIG` to a directory that holds them as `policy.v1.json` and `required.v2.json`.
  (`ZP` is the project's prefix; `ZPLOG_ENABLED=0`, set by the script, turns off request
  logging.) `run_example.py` shows the exact environment it uses.
- **Recording verdicts.** Use `python -m core.cli append <record.json>`. The record format is in
  `run_example.py`'s `record()` function. The fields the metric uses are `step` and `subjects`
  (path and blob id). The others describe how the verdict was reached, and the example fills
  them with fixed values: `tier`, `decided`, `basis`, `revision`, `run` and `cost`.

**Exit codes.**

| code | meaning |
|---|---|
| 0 | the metric was computed, whatever its value |
| 2 | nothing was measured: the verdict stream does not exist, the ref does not resolve to a commit, the configuration could not be read, or `--action` names an action the configuration does not define; the message says what to supply instead |

`--ref` takes any commit, branch or tag. It also accepts `staged`, which measures the files
as they are staged for the next commit rather than any committed revision.

### How a step's scope is determined

The required-steps file (`config/required.example.json`) lists each step under `types`. Every
step needs a `family` (the example uses `mechanical`). `reason` and `module` are optional
descriptions. None of the three affects the metric. Top-level `"default": "REQUIRED_FOR_ALL_ACTIONS"` makes every step required for every
action unless the step lists its own `actions`. The policy file's settings do not affect the
metric, and neither do the record fields the example fills with fixed values.

These settings come from the step's entry:

- `scope`, a list of patterns, selects files at the given ref. If it is absent, `when` (a single
  pattern) is used. If both are absent, the scope is **every file** in the repository.
- Patterns follow Python's `fnmatch` rules, so `*` also matches `/`: `tools/*.json` covers
  `tools/a/b.json` as well as `tools/b.json`. `fnmatch` also ignores letter case on Windows
  but not on Linux or macOS, so a repository whose paths differ only in case can be scoped
  differently by platform.
- A file added later under an existing pattern joins the scope at once, as `tools/browse.json`
  does at stage 3. Until a verdict is recorded for it, it counts as never examined.
- `scope_exclude` removes paths from the scope. So do files the configuration declares as
  session state, which no step may record.
- `switches` are files the step's result depends on beyond the files it examines: for
  example a baseline, an exemption list, or the harness itself. They count in `in_scope`. The
  ledger refuses any record for the step that does not list every declared switch among its
  files, so editing a switch always makes the step's verdicts stale for that file.
- A file deleted at the ref is no longer in scope, and its old verdicts no longer count.

### When a step counts as not applicable

The command reports a cause for each not-applicable step:

| cause (in the JSON) | meaning |
|---|---|
| `empty_scope` | nothing in the step's scope exists at the ref |
| `when_matched_no_file` | the step's applicability pattern (`when`) matches no file |
| `not_required_for_action` | the configuration does not require the step for the selected action (`--action`, default `push`) |
| `unclassified` | a safeguard, not a fourth cause: the ledger marked the step not applicable without saying which of the three applied, so the output shows that rather than guessing |

## Files

| file | purpose |
|---|---|
| `run_example.py` | builds the repository, records verdicts, prints the metric |
| `config/required.example.json` | the two steps and their scopes |
| `config/policy.example.json` | ledger policy thresholds; none of them affects the metric |

The metric is computed by `evidence_currency()` in `core/cli.py`, from the per-step rows that
`core/inventory.py` produces. Its tests are in `tests/test_evidence_currency.py`. They pin
the following, each end to end through the ledger:

- every number in the stage table above;
- the behaviour for PASS, FAIL and UNDECIDED verdicts;
- a harness edit, both undeclared and declared as a switch;
- each not-applicable cause.
