# Task card FIX: `receipts fix` that a person can watch and run on another repo

Approval is already given by the owner (2026-10-04). Do not stop to ask; list your choices in the report.

## Where

Repository `/Users/sunzeyu/dev/nebius-hackathon`, branch `build/plan-1`. Product code in `src/receipts/`, tests in `tests/`. Do not commit. No network. Your sandbox cannot reach Docker, so Docker tests skip there; the main session runs them. Run the rest with `.venv/bin/python -m pytest -q` (and the targeted files you touch).

## Why

The demo video will show one real run of `receipts fix` on Token Factory Sandboxes, recorded in a terminal. Today the command is silent for minutes and then prints the whole Markdown receipt (including dozens of frozen-test hashes), and there is no way to put the failing test into a prebuilt repo image. Both make the product look unfinished.

## 1. `--test-patch FILE` (sandbox executors)

- New option on `receipts fix`: a unified diff that adds or changes test files (the person's failing test). For sandbox executors (`tokenfactory`, `daytona`) it is applied in the sandbox before the baseline, with the same mechanism the SWE-rebench path uses (`swerebench._setup_commands`: write the patch into the sandbox, then `git apply`), by putting those commands into `ImageSource.setup`.
- The test files the patch touches are added to `spec_paths` (use the same helper the SWE-rebench path uses, `_test_files_from_patch` or equivalent), so they are frozen and protected exactly as in the pilot.
- With `local` or `docker` it is an error with a clear message (those executors take `--repo` and `--commit`, where the test is already committed).

## 2. Live progress, in the style of `receipts reverify`

- `orchestrate.fix` gets an optional `progress` callback (default `None`, so the pilot and every existing caller behave exactly as now). It reports, as they happen:
  - the checkpoint built (image, short checkpoint id, seconds);
  - the baseline (how many spec tests fail, how many tests pass, seconds);
  - each agent tool call as one readable action: what it did (reads, edits, writes, runs) and the command or path shown the way the site shows it (`receipts.site._display_command` or the same logic: never a `/opt/receipts-*` wrapper or a local absolute path), with the exit code for commands;
  - the agent's finish (the first sentence of its summary);
  - the witness (branch id, "fresh sandbox from checkpoint <short id>", files applied, dropped paths if any);
  - each gate check R1 to R5 with pass or fail and a short readable reason (for example "1 of 1 target tests pass", "512 of 512 still pass"); R6 is advisory: show it only if it contradicts the claim, labelled as advisory;
  - an appeal, if one is sent;
  - the final verdict.
- `receipts fix` renders these as aligned lines, like `reverify`: a header "Fixing <first line of the issue> with <model id> on Nebius Token Factory Sandboxes" (or the executor's name), then one line per event with a short label column, `✓` or `✗` for checks, and seconds in parentheses where known; colour only on a TTY, `NO_COLOR` wins and `FORCE_COLOR` forces (reuse the helper in `reverify.py`). End with one summary line, for example "VERIFIED in 1m 52s · $0.01 of Nemotron tokens", or REJECTED with the failed check, and then "receipt: <out>/receipt.md".
- Write the full Markdown receipt (the current `render(result)`) to `<out>/receipt.md`; stop printing it to stdout. `receipts show` still prints it. The exit code is unchanged (0 only for a verified fix).
- Keep each line under 100 characters (truncate long commands with an ellipsis), so a 2560-wide terminal at the demo's font size shows every line whole.

## 3. Tests

Using the existing fakes in `tests/test_cli.py` and `tests/test_orchestrate.py`:
- the progress events arrive in order for a verified run and for a rejected-then-appealed run;
- the CLI output has the header, agent lines, the five check lines, the summary and the receipt path, contains no `/opt/receipts-` and no absolute local path, and has no colour codes when `NO_COLOR` is set;
- `<out>/receipt.md` is written and equals `render(result)`;
- `--test-patch` puts the setup commands in `ImageSource.setup` and its test files in `spec_paths`; it is rejected for `local` and `docker`;
- the pilot path is unchanged (an existing pilot test still passes untouched).

## 4. README

Add a short "Run it on another repo" snippet under "Re-verify it yourself", showing the `receipts fix` command with `--image`, `--workdir`, `--test`, `--test-patch`, `--issue-file`, `--executor tokenfactory` and `--out`, and one sentence on what it prints. Plain writing, no em dashes.

## Report

What changed (files), an example of the new output from a test (paste it), the test results, and your choices.
