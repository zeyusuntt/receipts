# Narration

The video's narration in clean verbatim, one paragraph per scene; `/` marks a pause. `video/scripts/timeline.py` reads it to align the recording and time the captions.

## The narration (revision 6, as recorded)

As recorded on 2026-10-05 (take 2, the on-camera introduction and two pickups, assembled by `video/scripts/assemble_narration.py`). The text below is what was said, in clean verbatim, so the captions match the voice.

Read it in one take, the way you'd explain it to a friend at a desk. Pause about a second at each `/`. Every claim is true of our runs. About 360 words: at a calm 140 words a minute that is about 2:35 of speech, about 2:50 with the pauses and the end card. If the take runs long, I cut a sentence (first candidates: "A fresh sandbox runs the same checks again." and "The failing test is the spec."); you don't speed up.

> This is a coding agent telling me it fixed the failing tests. /
> Well, it didn't. /
>
> Hi, I'm Zeyu. I build evaluations for AI agents. And I have heard "done" a lot from agents. So I gave NVIDIA's Nemotron 3 Super a hundred real bugs. It said "done" sixty-seven times. / Well, twelve weren't true. / If you are the one merging, you can't tell which twelve. /
>
> So I built Receipts for that: a coding agent that isn't allowed to grade its own homework. Nemotron writes the fix, on Nebius Token Factory. Then a fresh Token Factory Sandbox it never touched runs your tests again, / and plain code decides. /
>
> Here's one, from PyFilesystem2. The failing test is the spec. /
>
> Nemotron reads the code, edits it, runs the tests, and says it's done. /
>
> Receipts doesn't take its word for it. It forks the original checkpoint into a new sandbox, applies only the source change, and runs the tests itself. / Rejected. The spec still fails. /
>
> Receipts sends the gate's evidence back to the agent, once. It finds the real bug, in the base class. A fresh sandbox runs the same checks again. / This time it passes. /
>
> Every check is plain, boring code: the failing test passes, old tests still pass, no test is removed or skipped, the patch leaves your tests alone, and every step is hashed back to your code. / SWE-rebench's grader, run separately, agrees. /
>
> You can check this yourself. A receipt re-runs in about two minutes on Token Factory, or with Docker and no account. /
>
> I got this wrong first. In my first pilot, the gate let one bad fix through: the agent hid a copy of the package where my test runner would find it. I'd written the rules down in advance, so I published the mistake, fixed it, and started over. /
>
> On the hundred bugs: sixty-six verified fixes, zero false ones shipped, about forty cents of Nemotron tokens each. / It all ran on Nebius Token Factory: eighty-seven million Nemotron tokens, nearly five hundred sandboxes. / That's what I want before I merge anything an agent wrote: a receipt I can re-run. / Here it is on another repo: one command and a failing test. /
>
> Agents can write the code. Receipts makes them show their work.
