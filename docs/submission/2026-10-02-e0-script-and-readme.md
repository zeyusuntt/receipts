# E0: the video script and the README first screen, written before the v2 run

Draft for Zeyu, Oct 2. Plan 5 item E0 (playbook law 1: write the demo script before the build it depends on). Numbers in `{braces}` come from the v2 report and are filled in by code or by hand from it, never estimated. Supersedes the drafts in the design spec, sections 12.1 and 12.2, where they disagree.

## 1. What changed from the spec's drafts, and why

| Spec draft said | Now | Why |
| --- | --- | --- |
| Fixes run "in Nebius Token Factory Sandboxes" | "in a clean sandbox"; the Built With line names Daytona | Sandboxes access was requested Sep 30 and never granted. A judge who checks would find the claim false. If access arrives before the freeze, this line changes back. |
| A hosted "Re-verify" button | "Re-verify it yourself" with Docker, in three commands (E2) | A public button spends credits per click and invites abuse. Proof that runs on the judge's own machine is stronger anyway. |
| "False dones shipped: zero" | `{shipped_false_dones}` from P, stated whatever it is | v1 shipped one. The pre-registered rule says the real count goes first. |
| Open on "this agent said done; the record says otherwise" | Kept | Judges have felt this pain. It is a story and a number in the first 15 seconds, with no architecture. |
| Our own false done was not in the video | It is the "why hard" beat (2:05) | It is the most credible thing we have: the process caught our own gate, we published it and fixed it. It goes after the demo, not first, because the first 20 seconds belong to the judge's problem, not ours. This changes the order in Plan 5's E4 spine. |

## 2. The story in one paragraph

A coding agent says "done, all tests pass". Nobody checked. Receipts is the coding agent that is not allowed to grade its own homework: you write the failing test, NVIDIA Nemotron 3 Super on Nebius Token Factory writes the fix, and a sandbox the agent never touched re-runs your tests and decides, with no model in the verdict. On {P_n} SWE-rebench tasks it had never seen, chosen by a rule fixed in advance and graded by SWE-rebench's own grader, {A_false_pct} percent of the unguarded agent's "done" was false. Receipts shipped {shipped_false_dones} false dones, at {cost_per_fix} per verified fix, and every receipt can be re-verified by anyone with Docker.

## 3. README first screen (literal draft)

```markdown
<h1 align="center">Receipts</h1>
<p align="center"><b>The coding agent that is not allowed to grade its own homework.</b><br>
You write the failing test. Receipts writes the fix with NVIDIA Nemotron 3 Super on Nebius Token Factory, re-runs your tests itself in a clean sandbox the agent never touched, and hands you a receipt anyone can re-verify.</p>
<p align="center"><a href="https://{pages_url}/"><b>Receipts from real runs</b></a> · <a href="https://youtu.be/{video_id}"><b>Video (2:50)</b></a> · <a href="REPORT-v2.md"><b>False-Done Report</b></a> · <a href="#re-verify-it-yourself"><b>Re-verify it yourself</b></a></p>

| | On {P_n} SWE-rebench tasks the agent had never seen | Proof |
|---:|---|---|
| **{A_false_pct}%** | of an unguarded Nemotron agent's "done" was false ({A_false} of {A_claimed}, 95% CI {ci_low} to {ci_high}%) | [every trace](REPORT-v2.md#unguarded) |
| **{shipped_false_dones}** | of {B_verified} fixes Receipts shipped fail SWE-rebench's official grader ({B_appeal} won on appeal) | [every receipt](REPORT-v2.md#receipts) |
| **{cost_per_fix}** | per verified fix, model tokens and sandbox time included | [costs](REPORT-v2.md#cost) |

<sub>Tasks chosen by a rule committed before the first run (PREREGISTRATION-v2.md). Every outcome is published, including our own pilot's false done.</sub>

![An agent says "all tests pass". A clean witness sandbox re-runs them: REJECTED, the spec test still fails. The evidence goes back once: VERIFIED.](docs/assets/caught-then-verified.gif)

> **Re-verify it yourself** (Docker, no API key)
> ```
> git clone https://github.com/{owner}/receipts && cd receipts
> uv sync
> uv run receipts reverify receipts/{featured_receipt}.json
> ```
> It applies the shipped patch to a clean copy of the task, checks the patch digest, re-runs the spec tests, and must agree with the receipt.
> Then read [the gate](src/receipts/verify/gate.py) (plain code, no model asks whether the fix worked) and [what it cannot catch](#limits).

**Built with** Nebius Token Factory · NVIDIA Nemotron 3 Super (120B-A12B) · Daytona sandboxes · SWE-rebench-V2
```

If the pre-registered headline is H2 or H3 rather than H1, the first table row becomes that rule's sentence; the table keeps the real counts either way.

## 4. Video, 2:50

Narration is scripted in full; three anchors are memorized (the first two sentences, the "rejected" line, the last 20 seconds). Every run on screen is a real, unmodified run whose id is shown. Speak slowly.

| Time | Beat | On screen | Narration |
| --- | --- | --- | --- |
| 0:00 | Cold open | A real trace: the agent's finish message, "All tests pass. The fix is complete." Then the witness receipt: the spec test, still failing. | "This coding agent just said: done, all tests pass. It wasn't true." |
| 0:08 | The number | One figure, `{A_false_pct}%`, with "Nemotron 3 Super · {P_n} unseen SWE-rebench tasks · rule fixed in advance · official grader". | "On {P_n} tasks it had never seen, {A_false_pct} percent of its 'done' was false. Graded by SWE-rebench's own grader, not by us." |
| 0:20 | One-liner | Title card: Receipts. Corner strip for the rest of the video: Nebius Token Factory · NVIDIA Nemotron. | "This is Receipts: the coding agent that is not allowed to grade its own homework. You write the failing test. Nemotron writes the fix. A sandbox it never touched decides." |
| 0:35 | Setup | The featured task: repository, issue, the frozen failing test, the baseline failure text, the plan card. | "Here is a real bug from {featured_repo}. The test fails, and the agent starts where the failure is." |
| 0:50 | The agent works | Agent lane, sped up: reads, edits, test runs. Then its finish claim. | "It reads, edits, runs the tests, and says it is done." |
| 1:00 | Rejected | The checkpoint branches into a clean witness lane. Only the source patch crosses over. The gate's checks fill in with evidence. **REJECTED.** Two-second pause. | "Receipts ignores what it said. It forks the original checkpoint, applies only the source patch, and runs the tests itself. Rejected." |
| 1:20 | Appeal | The gate's evidence lines go back to the agent verbatim. It fixes the source. A new witness from the same checkpoint. **VERIFIED.** | "The evidence goes back, once. The agent fixes the real problem. A fresh witness. Verified." |
| 1:40 | Proof of depth | "What it said" beside "what the record shows". Then: the official SWE-rebench grader, run separately: resolved. | "The verdict comes from plain code, not a model. And SWE-rebench's official grader, run separately, agrees." |
| 1:55 | Re-verify | A terminal, live: `receipts reverify ...`; digest matches; spec passes; "agrees with receipt". | "Don't trust us either. Anyone with Docker can re-verify any receipt in three commands." |
| 2:05 | Why it is hard | The pilot's scikit-build receipt: VERIFIED, then the official grader: not resolved. The cause in one line: a copy of the package at the repository root. Then Amendment 2 and the fix. | "Making this un-foolable is the hard part. In our own pilot the gate shipped one false fix: the agent hid a copy of the package where our test runner would find it. Our pre-registration made us publish it, fix it, and start over." |
| 2:25 | Impact | The three README numbers, and "{attack_tests} attack tests in the repository". | "{B_verified} verified fixes, {shipped_false_dones} shipped false dones, {cost_per_fix} each. For every maintainer who would hand a bug to an agent if they could believe its 'done'." |
| 2:45 | Close | Repository and receipts URL. | "Agents can write the code. Receipts makes them prove it." |

## 5. Which runs appear, chosen by rule

To keep the demo from looking hand-picked, the runs on screen are chosen by rule from v2's primary sample P, after the run:

- **Featured run (0:35 to 1:55):** the first task in P's committed order whose attempt 1 was REJECTED, whose appeal was VERIFIED, and whose official grade is resolved. If no task has that arc, the first VERIFIED task on its first verdict, and the script drops the appeal beat.
- **Cold open (0:00):** the first false done of configuration A in P's order whose own last test run was green (the "naive check would accept it" kind).
- **Why hard (2:05):** the v1 launch-2 scikit-build record, as published.

## 6. Open points for Zeyu

1. The order change: our own false done as the 2:05 beat instead of the opener. Recommended.
2. Voice and face: the spec's lower third says "Zeyu Sun, builds agent benchmarks". Keep it, or no face or name?
3. The repository name: the spec says `receipts`. That decides the clone URL in the README.
