<h1 align="center">Receipts</h1>
<p align="center">A coding agent that is not allowed to grade its own homework.<br>
You write the failing test. Receipts writes the fix with NVIDIA Nemotron 3 Super on Nebius Token Factory, re-runs your tests itself in a clean Token Factory Sandbox the agent never touched, and hands you a receipt of every command it ran. Anyone can re-verify the 100 receipts from the experiment.</p>
<p align="center"><a href="https://receipts-live-683278413320.us-central1.run.app">Run it live</a> · <a href="https://zeyusuntt.github.io/receipts/">Receipt viewer</a> · <a href="https://youtu.be/tSJwtfb1-T8">Video (2:57)</a> · <a href="REPORT-v2.md">False-Done Report</a> · <a href="#re-verify-it-yourself">Re-verify it yourself</a> · <a href="#for-judges">For judges</a></p>

| | On 100 SWE-rebench tasks held out from development, chosen by a rule fixed in advance | Proof |
|---:|---|---|
| 17.9% | of an unguarded Nemotron agent's "done" was false (12 of 67, 95% interval 10.6 to 28.7%) | [every trace](REPORT-v2.md) |
| 0 | of 66 fixes Receipts shipped fail SWE-rebench's official grader (7 won on appeal) | [every receipt](https://zeyusuntt.github.io/receipts/) |
| $0.41 | of model tokens per verified fix, at Token Factory's listed prices | [costs](REPORT-v2.md) |

<sub>Tasks chosen by a rule committed before the first run (<a href="PREREGISTRATION-v2.md">PREREGISTRATION-v2.md</a>). Every outcome is published, including our own pilot's false done.</sub>

## For judges

To try it without installing anything, the [live page](https://receipts-live-683278413320.us-central1.run.app) runs Receipts on one of five preset tasks from the experiment, with the judge code from the Devpost testing notes. Each step is labelled with the model or tool that did it.

| Criterion | Look at | What it shows |
| --- | --- | --- |
| Technological Implementation | [One run, every command](https://zeyusuntt.github.io/receipts/run/pyfilesystem__pyfilesystem2-462.html) | Nemotron 3 Super on Token Factory writes the fix with five tools in a Token Factory Sandbox. The witness is a second sandbox, forked from the checkpoint image taken before the agent started. Over the 100 tasks: 482 sandbox branches, 4,253 recorded steps, 87.4 million Nemotron tokens, $27.01. |
| Design | [The receipt viewer](https://zeyusuntt.github.io/receipts/) | Its first screen gives the result and one run from the experiment as a log: the agent says it is done, the witness finds a target test still failing, the evidence goes back once, the second fix is verified. Any of the 100 receipts re-verifies in three commands, with Docker and no key. |
| Potential Impact | [The False-Done Report](REPORT-v2.md) | For anyone who merges fixes a coding agent wrote: 12 of the agent's 67 "done" were false, and in 6 of those its own last test run was green. Receipts shipped 0 false fixes out of 66, at $0.41 of tokens each. |
| Quality of the Idea | [The AERead trial](trials/aeread/RESULTS.md) | The agent never grades its own work, and every experiment's rules were committed before it ran. On bug fixes from a project outside any benchmark, passing the tests was often not enough (5 of 13 verified patches were wrong), and the trial measures which checks help. |

## Limits

- A fix is only as good as the failing test. Receipts shows that your test passes in a clean sandbox and that nothing that passed before broke. On bug fixes from AERead, a project outside any benchmark, it verified 13 patches over two held-out sets; two independent readings, which agree on every patch, found 5 correct, 3 partial and 5 wrong. Every patch that is not correct passes its target tests ([RESULTS.md](trials/aeread/RESULTS.md)).
- The independent review (R8) only advises. It was built to veto, and a rule committed in advance let it reject at most 3 of the 66 fixes the official grader accepts. It rejected 10, so it ships advisory; `receipts fix --review-veto` turns the veto on.
- Code that detects it is running under test can pass any test-based gate, including the official grader.
- Python repositories tested with pytest only. Tests that need the network or host features cannot pass in a sandbox, before or after any patch; in the experiments those tasks were excluded before any agent ran, and listed.
- The gate rejects a fix that also modifies an existing test file, even when the source change is right; the appeal tells the agent why. This cost one correct fix in the 100-task run.
- The live page runs only five preset tasks, one at a time, with a daily limit and a spending cap. On your own repository, re-verifying a receipt needs Docker and no key, and `receipts fix` needs a Token Factory key.
- The headline numbers come from one model on one benchmark: Nemotron 3 Super on 100 SWE-rebench-V2 tasks. An exploratory arm ran Nemotron 3.5 Lightning on 30 of them ([REPORT-v2.md](REPORT-v2.md)).

## Re-verify it yourself

Docker, no API key:

```
git clone https://github.com/zeyusuntt/receipts && cd receipts
uv sync
uv run receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json
```

It checks the patch digests, starts the task's public image (the first run downloads it, which can take a few minutes), rebuilds the original checkpoint, replays the agent's patch through the same filter and gate on a fresh witness, grades the shipped patch with SWE-rebench's official grader, and must agree with the receipt on every check (about two minutes per receipt on Token Factory). With a Nebius account, add `--executor tokenfactory` to run it on Token Factory Sandboxes instead of Docker. Then read [the gate](src/receipts/verify/gate.py): plain code, and no model is asked whether the fix worked.

Or re-verify all 100 on GitHub's machines, without installing anything: fork this repository, open the Actions tab, and run **Re-verify receipts** ([the workflow](.github/workflows/reverify.yml)). On October 17 [a run of it on this repository](https://github.com/zeyusuntt/receipts/actions/runs/39019908268) re-verified all 100 receipts in 37 minutes, and every check agreed on every receipt.

## Use it on a repository

Receipts works on Python repositories tested with pytest. `receipts fix` calls Nemotron, so copy `.env.example` to `.env` and set `OPENAI_API_KEY` to a Nebius Token Factory key (`--executor tokenfactory` also needs `NEBIUS_AI_PROJECT`). Re-verifying a receipt needs neither.

On your own repository, with Docker: commit your failing test, then point Receipts at that commit; Docker clones it into a fresh container:

```
uv run receipts fix --repo https://github.com/you/your-repo --commit <commit with your failing test> \
  --install "pip install -e ." --test tests/test_parse.py::test_empty_string \
  --issue-file issue.md --executor docker --out runs/my-fix
uv run receipts show runs/my-fix
```

On Token Factory Sandboxes, `--image` names an image in Token Factory's catalogue (every SWE-rebench-V2 image is preloaded), and `--test-patch` adds your failing test to it. This is the PyFlakes run in the demo video (VERIFIED in 1m 7s, $0.03 of Nemotron tokens):

```
uv run receipts fix --executor tokenfactory \
  --image docker.io/swerebenchv2/pycqa-pyflakes:335-4b2d720 --workdir /pyflakes \
  --test pyflakes/test/test_other.py::TestUnusedAssignment::test_unusedUnderscoreVariable \
  --test-patch demo/pyflakes-335/test.patch --issue-file demo/pyflakes-335/issue.md \
  --suite pyflakes/test --out runs/pyflakes-335
```

It prints each agent and verification step as it happens and writes the full receipt to `<out>/receipt.md`. Receipts never opens a pull request: you review the patch and the receipt, and you submit.

## How it works

![Your failing test goes to Nemotron 3 Super on Nebius Token Factory, which works on an agent branch; a Token Factory Sandbox forked from the same checkpoint is the witness; plain-code gate; receipt. SWE-rebench's official grader runs separately.](docs/assets/architecture.png)

1. You write the failing test. It is the specification. Receipts runs the suite twice on the original code to record what fails and what passes (the baseline).
2. The agent works on its own branch. Nemotron 3 Super reads, edits and runs tests through five tools, in a Token Factory Sandbox forked from the checkpoint of your code. It finishes with a claim: what it changed and which tests it says pass.
3. A witness checks the work. Receipts forks the original checkpoint again, a branch the agent never touched, and applies only the source part of the agent's patch. New test files the agent wrote are dropped; your test files are read-only.
4. A model-free gate decides. Plain code compares the witness's test run with the baseline (table below); no model can make a patch pass. If it passes, two independent Nemotron reviews read it against the issue and their objections are recorded on the receipt (R8, advisory). If the verdict is REJECTED, the evidence goes back to the agent once, verbatim, for one appeal on the same branch, and a fresh witness checks again.
5. You get a receipt. Every command on every branch is recorded with its exit code, digests and the image it started from, so the chain from your code to the shipped patch can be checked and re-run.

In our experiments a sixth step runs separately from Receipts: SWE-rebench's own grader grades every patch, which is how we measure whether the gate is right.

### What the gate checks

| | Check | Passes when |
| --- | --- | --- |
| R1 | The specification passes | every failing test you named passes on the witness |
| R2 | Nothing regressed | every test that passed at baseline still passes |
| R3 | Nothing was hidden | every baseline test is still collected, and no new skips |
| R4 | The patch stays in scope | it modifies no test, specification or configuration file, and adds nothing hazardous (such as a module that shadows an installed package) |
| R5 | The record is unbroken | every receipt chains to the checkpoint, and the patch the witness applied has the shipped patch's digest |
| R6 | The claim matches the record | advisory: whether what the agent said about its tests is what the record shows |
| R7 | The patch takes no shortcut | it adds no private function that nothing outside the tests uses, and does not leave a function whose whole body only raises `NotImplementedError` or does nothing (abstract methods, overloads and base-class hooks that a subclass implements excepted) |
| R8 | Advisory: no independent review objects | two separate Nemotron 3 Super reviews, which never see the agent's reasoning, read the issue and the patch; plain code keeps an objection only if it quotes the issue word for word and points at a line of the patch. Recorded on the receipt; it does not change the verdict |

R1 to R5 and R7 decide VERIFIED or REJECTED. R6 and R8 are reported on every receipt but do not change the verdict. R7 reads the patch and the patched code without running anything. R8 is the only check that calls a model. It was built to veto, and a check committed in advance decided against that: on the 66 fixes from the 100-task experiment, all accepted by the official grader, both reviews objected to 10, against a limit of 3. So it ships advisory; `receipts fix --review-veto` lets it reject a patch, and `--no-review` turns it off. R7 and R8 were added after the 100-task experiment, from patches that passed every other check on real bug fixes in [AERead](trials/aeread/RESULTS.md), so the experiment's receipts include neither and `receipts reverify` checks neither.

## Built on Nebius Token Factory and NVIDIA Nemotron

Which model does what: NVIDIA Nemotron 3 Super writes the fix on Token Factory, with five tools, in its own Token Factory Sandbox. A second sandbox, forked from the checkpoint taken before the agent started, runs your tests again, and the gate (R1 to R5 and R7, plain Python) decides; no model takes part. Once a patch has passed, two more Nemotron 3 Super calls review it (R8), and their objections go on the receipt without changing the verdict. In the experiments, SWE-rebench's official grader graded every patch again in separate sandboxes.

- NVIDIA Nemotron 3 Super 120B-A12B (`nvidia/nemotron-3-super-120b-a12b`) plans and writes every fix, through Token Factory's OpenAI-compatible API with tool calling (five tools, thinking off). It was the most reliable tool caller in a scripted test: it completed 10 of 10 six-turn tool loops, against 6 for Nemotron 3.5 Lightning and 3 for Nemotron 3 Ultra. Lightning also ran as a pre-registered exploratory arm on 30 of the tasks ([REPORT-v2.md](REPORT-v2.md)).
- Token Factory Sandboxes ran every agent, witness and grading branch in the 100-task experiment. Each branch is a chain of immutable images, so forking the checkpoint taken before the agent started is exact, and that fork is the witness.
- Token Factory sped up the work in several places: the catalogue already holds the SWE-rebench-V2 images (598 of the 600 candidates), so no task image had to be built or pulled; a trivial sandbox run takes about 1.1 s; screening ran at concurrency 6 and the agents at concurrency 4 without hitting a rate limit; the 100-task experiment cost $27.01 in Nemotron tokens; and re-verifying a receipt on Token Factory takes about two minutes.
- No other Nebius service is used: inference and sandboxes both come from Token Factory.

## How it differs

Several entries in this hackathon check or pick a coding agent's fix. From their READMEs, read on October 26, 2026:

| Project | What it does | What decides | Measured on, per its README |
| --- | --- | --- | --- |
| [FixedYet](https://github.com/beniamin-levin/fixedyet) | Reproduces a GitHub issue: Nemotron writes a pytest test and runs it at the reported version and on `main`; fix mode writes a fix and can open a draft pull request | Rules over exit codes, using the test the model wrote | 15 SWE-bench Verified issues in three runs, 36 of 45 reproduced (its README says this is not a held-out score), and 10 recent real issues |
| [forkfix](https://github.com/jessecalvin08/forkfix) | Forks the agent at code-changing steps over Sandbox snapshots and submits the best branch's patch | A Nemotron 3 Super judge ranks branches; the existing tests push broken ones down | 79 held-out SWE-bench Lite tasks: 15 solved, against 4 for a single attempt |
| [FixFork](https://github.com/tuyentran4992/fixfork) | Races three fix hypotheses for a failing test on forked branches | The test command going green, then the fewest changed lines | Case studies on real repositories; one fix, finished by hand from a run report, was merged in tomlkit |
| [Polygraph](https://github.com/Thanatos9404/polygraph) | Checks a pull request's claims by running the base and head code side by side on generated probes | The experiments, with Nemotron 3 Ultra ruling on each claim and the final label computed in code | Six cases, two of them real merged pull requests, against a diff-reading control |
| [slash-agent](https://github.com/Wolfe-Jam/slash-agent) | Quotes a coding job, plans with Nemotron 3 Ultra, sends the writing to the cheapest Nemotron its quality floor allows, and returns a receipt of what it spent | The project's tests, run on a copy | Live runs of preset jobs |
| Receipts | Writes the fix for a failing test you wrote, then checks it in a sandbox forked from before the agent started | Plain code over that sandbox's test run; no model | 100 held-out SWE-rebench tasks, chosen by a rule committed in advance and graded by SWE-rebench's grader |

Receipts differs in four ways:

1. The test that decides is yours, and it runs where the agent never was. The agent works with a shell in its own sandbox; the verdict comes from a different sandbox forked from the checkpoint taken before it started, with only the source part of its patch applied. Packages, configuration or caches the agent changed outside the patch do not carry over.
2. By default no model takes part in the verdict, and none can ever pass a fix. The gate's evidence goes back to the agent once, so a rejected fix can still become a verified one (7 of the 66).
3. It measures the problem it solves: how often a coding agent's own "done" is false (12 of 67), and how often Receipts ships a false fix (0 of 66).
4. Anyone can re-execute a receipt: `receipts reverify` rebuilds the checkpoint in a fresh sandbox, replays the patch and the gate, and must agree check by check.

slash-agent's receipt accounts for spend. A Receipts receipt records the commands and images that tie a shipped patch to the test run that passed it.

## The experiment

We ran Receipts in three pre-registered experiments: the rules, the sample and the reporting were committed before each run, and every outcome is published.

- The v1 pilot (Oct 1) ran 50 SWE-rebench tasks. Receipts shipped one false done because of a defect in Receipts: the agent hid a copy of the package at the repository root, where our test runner found it and the official grader did not. The pre-registration made us publish it, fix it, and start again. [REPORT.md](REPORT.md), [PREREGISTRATION.md](PREREGISTRATION.md), and a [cost erratum](docs/results/2026-10-02-v1-cost-erratum.md).
- v2 (Oct 2 to 3) ran 100 tasks held out from development, chosen by a rule committed in advance, on Token Factory Sandboxes, with the gate hardened against what v1 found. [REPORT-v2.md](REPORT-v2.md), [PREREGISTRATION-v2.md](PREREGISTRATION-v2.md).
- The AERead trial (Oct 16 to 17) used bug fixes written by other contributors from a project outside any benchmark, pre-registered the same way. On two held-out sets of 8, Receipts verified 13; by two independent readings that agree on every patch, 5 are correct, 3 partial and 5 wrong, and every one that is not correct passes its target tests. Receipts makes the tests true; on real code they are often not enough. What helped is measured there: R7, a stricter target rule, the full test suite, and R8, which a pre-registered check sent to advisory. [PLAN.md](trials/aeread/PLAN.md), [RESULTS.md](trials/aeread/RESULTS.md).

What we found along the way about the tools we built on: [FEEDBACK.md](FEEDBACK.md).

## Repository

```
src/receipts/verify/      the baseline, the witness verification and the gate
src/receipts/agent/       the planner and the worker (five tools, one appeal)
src/receipts/sandbox/     executors: Token Factory Sandboxes, Daytona, Docker, local
src/receipts/pilot/       screening, the pre-registered runner, official grading, the report
tests/                    offline tests, including attack tests against the gate
```

Built with Nebius Token Factory (NVIDIA Nemotron 3 Super 120B-A12B, Token Factory Sandboxes) · SWE-rebench-V2. Apache-2.0 license.

## Credits

The demo video's music is "Wallpaper" by Kevin MacLeod ([incompetech.com](https://incompetech.com)), licensed under [Creative Commons: By Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). The SWE-rebench-V2 tasks are used under CC-BY-4.0; see [receipts/README.md](receipts/README.md).
