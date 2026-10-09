# Evidence currency: a worked example

This folder shows how verdictLedger measures **evidence currency** on a small, throwaway git
repository. It runs in under a minute.

**Requirements:** Python 3.11 or later and git 2.28 or later, on PATH. Nothing needs to be
installed with pip; the code uses only the Python standard library. Use a full checkout of this
repository, because `verdictLedger/` imports the shared `mcpcommon/` package that sits beside it.
Developed and tested on Windows; nothing in it is platform-specific.

## The metric

A *check* (a spell-checker, a license-header check, a human review) produces a *verdict* about
some files. verdictLedger calls a check a **step**, and the output uses that word. Each recorded
verdict names the step, and for every file it covers, the file's path and its git blob id
(git's hash of the file's bytes). The record claims the step examined exactly those bytes.

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

Three properties are deliberate:

- **The three states are reported separately.** "Stale" (examined, then changed) and "never
  examined" call for different follow-up, so they are never combined into one number.
- **An empty scope is not 100%.** A step with nothing in scope is reported as *not applicable*,
  with currency `null`, and is left out of the totals.
- **Currency is not a pass rate.** A current FAIL verdict counts as current evidence. The metric
  answers "is there a verdict about these exact bytes?", not "did the files pass?".

What the metric does and does not establish:

- **It measures recorded verdicts, not checks that ran.** A record is validated before it is
  stored. Validation checks the record's structure and internal consistency. It does not re-run
  the check, so the metric is only as trustworthy as whatever writes the records.
- **Only the subject file's bytes decide current versus stale.** A record can also name the
  checker that produced it (the example does), but editing the checker does not make its
  verdicts stale in this metric.

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
- prints the metric after each step.

Nothing outside the temporary directory is touched.

## What the example does

The configuration in `config/` defines three steps:

| step | scope | in the example repository |
|---|---|---|
| `spelling` | `docs/*.md` | two files |
| `license_header` | `src/*.py` | two files, later three |
| `changelog_review` | `CHANGELOG.md` | no such file, so the step does not apply |

The script then works through four stages:

1. **Initial state.** It creates the repository, runs both checks, and records a PASS for each
   file. Currency is 100% for both steps, and `changelog_review` is reported as not
   applicable.
2. **An edit makes a verdict stale.** It edits `docs/usage.md`, so that file's spelling verdict
   now describes older bytes. `spelling` shows 1 current and 1 stale (50%).
3. **A new file is never examined.** It adds `src/extra.py`, which no check has examined.
   `license_header` shows 2 current and 1 never examined (66.7%).
4. **A re-check restores currency.** It re-runs the spelling check on `docs/usage.md`.
   `spelling` returns to 100%. The total is 4 of 5 (80%), and the one never-examined file is
   still visible.

The last stage also prints the result as JSON. That output has a `status` field per step, which
is the ledger's separate pass/block decision under its configuration. This example's
configuration accepts partial coverage, so a step can read `SATISFIED` at 66.7% currency. The
currency figures do not depend on that setting.

## Using it on your own repository

Run from the `verdictLedger/` directory. `--repo` and `--data` are global options, so they come
before the command name:

```
python -m core.cli --repo <git-repo> --data <records.jsonl> evidence-currency --ref HEAD
python -m core.cli --repo <git-repo> --data <records.jsonl> evidence-currency --ref HEAD --json
```

You also need to supply configuration and record verdicts:

- **Configuration.** Give the file paths in `ZPLEDGER_POLICY` and `ZPLEDGER_REQUIRED`. Or set
  `ZPLEDGER_CONFIG` to a directory that holds them as `policy.v1.json` and `required.v2.json`. (`ZP` is the project's prefix; `ZPLOG_ENABLED=0`,
  set by the script, turns off request logging.) `run_example.py` shows the exact environment
  it uses.
- **Recording verdicts.** Use `python -m core.cli append <record.json>`. The record format is in
  `run_example.py`'s `record()` function. The fields the metric uses are `step` and `subjects`
  (path and blob id). The others describe how the verdict was reached, and the example fills
  them with fixed values: `tier`, `decided`, `basis`, `revision`, `run` and `cost`.

**Exit codes.**

| code | meaning |
|---|---|
| 0 | the metric was computed, whatever its value |
| 2 | nothing was measured: the verdict stream does not exist, the ref does not resolve to a commit, or the configuration could not be read; the message says what to supply instead |

### How a step's scope is determined

These settings come from the step's entry in the required-steps configuration:

- `scope`, a list of glob patterns, selects files at the given ref. If it is absent, `when` (a
  single glob) is used. If both are absent, the scope is **every file** in the repository.
- `scope_exclude` removes paths from the scope. So do files the configuration declares as
  session state, which no step may record.
- `switches`, files whose content changes how the step behaves, are judged with the subjects
  and count in `in_scope`.
- A file deleted at the ref is no longer in scope, and its old verdicts no longer count.

### When a step counts as not applicable

A step is reported as not applicable, and left out of the totals, if any of these holds:

- its scope is empty at the ref;
- its `when` pattern matches no file;
- the configuration does not require it for the selected action. Use `--action`, which defaults
  to `push`, to select one. The example's configuration requires every step for every action.

## Files

| file | purpose |
|---|---|
| `run_example.py` | builds the repository, records verdicts, prints the metric |
| `config/required.example.json` | the three steps and their scopes |
| `config/policy.example.json` | ledger policy thresholds; none of them affects the metric |

The metric is computed by `evidence_currency()` in `core/cli.py`, from the per-step rows that
`core/inventory.py` produces. Its tests are in `tests/test_evidence_currency.py`.
