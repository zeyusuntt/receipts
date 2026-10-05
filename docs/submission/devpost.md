# Devpost submission text (draft)

Every number comes from `REPORT-v2.md` (main branch, commit `1a56165`) and `pilot/v2-P/report.json`; none is estimated.

## Tagline

The coding agent that is not allowed to grade its own homework.

## Inspiration

Coding agents say "done, all tests pass", and whoever merges the fix has to take that on faith or re-run everything. We measured how often that faith is misplaced: on 100 SWE-rebench tasks held out from development, chosen by a rule committed in advance, 17.9% of an unguarded Nemotron agent's "done" was false, by SWE-rebench's own grader (12 of 67). Nothing in the agent's own report tells you which twelve. So we built a checker the agent cannot influence, and a receipt that lets anyone repeat the check.

## What it does

You write the failing test. Receipts:

1. Plans and writes the fix with NVIDIA Nemotron 3 Super on Nebius Token Factory, on its own branch in a Token Factory Sandbox.
2. Forks the original checkpoint into a clean witness the agent never touched, applies only the source part of the agent's patch, and re-runs your tests.
3. Decides with a model-free gate: your failing test passes, nothing that passed regressed, no test was removed or skipped, the patch touches no test or configuration file, and every step chains back to your code by digest. If it rejects, the evidence goes back to the agent once, verbatim, and a fresh witness checks again.
4. Hands you a receipt: every command on every branch, with exit codes, digests and the image it started from. Anyone can re-verify it in three commands: on Token Factory Sandboxes in about two minutes, or with Docker and no account.

## How we built it

- **Nebius Token Factory, models:** Nemotron 3 Super 120B-A12B plans and works through five tools (read, edit, write, run, finish), thinking off, temperature 1.0. The client counts tokens and dollars per run at Token Factory's listed prices.
- **Nebius Token Factory, Sandboxes:** each branch is a chain of immutable images, so "fork the original checkpoint" is exact and the witness provably never saw the agent's environment. Trusted tools (a pinned static busybox and our test runner) are injected per run at a fresh path, never read from the image. Over the 100 tasks that meant 482 sandbox branches, 4,253 hash-chained steps and 87,379,659 Nemotron tokens, with up to four tasks running at once.
- **The gate:** plain Python over junit reports and diffs. No model is asked whether a fix worked. 26 attack tests in the repository try to fool it (shadow packages, quoted patch paths, edited specifications, hidden skips).
- **The experiment:** we pre-registered two runs, committing the rules, the sample and the analysis before each one, and graded every patch again with SWE-rebench-V2's official grader in a separate sandbox. Every outcome is published, including our own mistakes.

## Challenges we ran into

Closing the ways to fool the gate. In our own pilot the gate shipped one false fix: the agent put a copy of the package at the repository root, where our test runner found it and the official grader did not. The pre-registration made us publish it, fix the runner, and start again. A review before v2 found three more ways to fool the gate (a quoted patch path, an editable specification file, unchecked shipped bytes); each was closed and has an attack test.

## Accomplishments that we're proud of

- On these 100 tasks: 0 false fixes among the 66 Receipts shipped, by SWE-rebench's official grader, and the gate and the grader agreed on 138 of 141 attempts (the other 3, the gate was stricter).
- $0.41 of model tokens per verified fix.
- A receipt anyone can re-check without trusting us: on their own machine with Docker and no API key, or on Token Factory.

## What we learned

An agent's claim and its record diverge often, and the gap is invisible unless something else re-runs the tests. Most of the work is not in the agent but in the checker: which files the agent may touch, which tests count, and proving the bytes you shipped are the bytes you tested.

## What's next

A GitHub Action that runs the gate on a pull request and posts the receipt as a check, so "the agent says it works" becomes "here is the receipt". Then other languages: the five checks do not depend on Python; what does is how the tests are run and read. The gate reads pytest's JUnit XML report; Java, JavaScript (jest) and Go runners can write the same format, so each new language needs a runner adapter that maps its test ids, not a new gate.

## How Receipts meets the judging criteria

- **Technological Implementation:** Nemotron 3 Super on Token Factory for every model call; Token Factory Sandboxes for every agent, witness and grading branch; a model-free gate with attack tests; a pre-registered evaluation graded by an independent official grader.
- **Design:** the product is a receipt: a run page that shows what the agent said beside what the record shows, a receipt page with a verdict stamp, and three commands to re-verify. ([receipts from real runs](https://zeyusuntt.github.io/receipts/))
- **Potential Impact:** anyone who merges agent-written code (maintainers, and teams adopting coding agents) can accept a fix on evidence instead of trust. `receipts fix` runs on any Python repository with a pytest test that fails, and each receipt page includes a ready pull request description that carries the receipt.
- **Quality of the Idea:** instead of a better agent, a referee the agent cannot influence, plus a public, pre-registered measurement of how often agents' "done" is false.

## Built with

nebius-token-factory, nvidia-nemotron, token-factory-sandboxes, python, pytest, swe-rebench, docker
