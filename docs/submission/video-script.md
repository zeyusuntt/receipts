# Video script

## Who is speaking (the narrator's persona)

Grounded in the owner's own playbook (`~/Documents/beta fund/playbook/winning-playbook.md`, section 4.2) and in how this project was run, not invented:

- An engineer who measures things for a living and doesn't take an agent's "done" on faith. The authority comes from having measured it, not from enthusiasm.
- Calm, exact, a little dry. Numbers are said flatly; precision replaces charisma (the playbook's "Greg Brockman GPT-4 demo register").
- Slow. Slower than feels natural; it reads as command.
- Owns the mistake. The pilot's false fix is told plainly, because publishing it is the most credible thing in the video.
- One human beat: the dry "It didn't." at the start, and "I got it wrong first" later.

What winners do that this borrows: a first line that says who you are and why you care (Pulse: "I'm a cardiologist"; EcoLafaek: "I'm from Timor-Leste; my capital produces 300 tons of waste a day"); no hype words anywhere; one moment of humour or candour; a close said with conviction.

## The narration to record (revision 6)

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
> Receipts doesn't take its word for it. It forks the original checkpoint into a new sandbox, applies only the source change, and runs the tests itself. / Rejected. Oh, the spec still fails. /
>
> Receipts sends the gate's evidence back to the agent, once. It finds the real bug, in the base class. A fresh sandbox runs the same checks again. / This time it passes. /
>
> Every check is plain, boring code: the failing test passes, old tests still pass, no test is removed or skipped, the patch leaves your tests alone, and every step is hashed back to your code. / SWE-rebench's grader, run separately, agrees. /
>
> You can check this yourself. A receipt re-runs in about two minutes on Token Factory, or with Docker and no account. /
>
> I got this wrong first. In my first pilot, the gate let one bad fix through: the agent hid a copy of the package where my test runner would find it. I'd written the rules down in advance, so I published the mistake, fixed it, and started over. /
>
> On the hundred bugs: sixty-six verified fixes, zero false ones shipped, about forty cents of Nemotron tokens each. / It all ran on Nebius Token Factory: eighty-seven million Nemotron tokens, nearly five hundred sandboxes. / That's what I want before I merge anything an agent wrote: a receipt I can re-run. / On another repo, it's one command and a failing test. /
>
> Agents can write the code. Receipts makes them show their work.

### How to say it (borrowed from the winners, fitted to this narrator)

- The first two sentences, "Rejected. The spec still fails.", and the last two sentences are the anchors: say them slowest.
- "It didn't." is dry, almost a shrug. Don't dramatize it.
- Numbers flat and exact: "twelve", "sixty-six", "zero". Let the number do the work.
- "I got this wrong first" is said plainly, not apologetically. It's the moment judges start trusting you.
- The last line slower than everything else, with a full stop after "code".
- Record in one take with a phone voice memo; if you stumble, pause, and restart the sentence. I'll cut the stumbles.

What changed in revision 6, and why: a review against the four judging criteria (Codex as a three-judge panel, 2026-10-04) found the product name arrived at 0:30 and the audience only at 2:21. So the introduction is one sentence, "by SWE-rebench's own grader" moved to the screen, the reader who merges is named by about 0:25 ("you can't tell which twelve"), the agent's verbs are spelled out for the NVIDIA judge, and the results add the Token Factory scale (87,379,659 Nemotron tokens and 482 sandbox branches over the 100 tasks, from `pilot/v2-P/report.json` and the run directories) and end on the action a reader takes. A humanizer pass (blader/humanizer rules) then restored the one wry personal line ("I hear 'done' a lot"), replaced the staged "You don't have to trust me" with the fact itself, turned the fragment row "New sandbox, same checks." into a sentence, and named the real fix (the base class) instead of "the actual problem". A second judging pass (2026-10-04) caught two lines the records do not support: the cold-open agent claimed its target tests passed, not the whole suite (so "All tests pass" became "it fixed the failing tests"), and the appeal sends the gate's evidence and a claim audit, not the failure "exactly as it happened". It also suggested "plain, boring code", which is how this narrator talks.

What changed in revision 4 (kept since), and why: first person and contractions, because it is one person explaining their own project; "tasks it had never seen" became "picked by a rule I wrote down before running anything", because we can show nobody looked at the tasks during development but cannot show the model never saw them in training; the slogans ("Do not take our word for it", "impossible to fool", "for every maintainer who...") became plain sentences; the numbers are the reported ones (`REPORT-v2.md`); "I" assumes a solo entry, so say "we" throughout if the team has more people.

The shot list below still holds for the picture; its narration column is revision 2 and is superseded by the text above.

---

## Shot list (revision 2 timing, revision 3 picture)

Revises E0 section 4 (`2026-10-02-e0-script-and-readme.md`) after the video research: the organizers ask that Token Factory and the NVIDIA model be named in the narration, not in passing, and winning videos run at 106 to 163 words per minute (E0 ran at about 85). This revision is about 345 words over 170 seconds, about 120 words per minute. Numbers in `{braces}` come from `REPORT-v2.md` by code, never estimated. Every run on screen is a real, unmodified run with its id shown; anything sped up shows its speed.

The cold open and the 0:07 number follow the pre-registered headline rule (`PREREGISTRATION-v2.md`, "Headline rule"). If the rule picks H2 or H3 instead of H1, the 0:07 line becomes that rule's sentence and the rest stays.

Quiet music: one standard-license track from the YouTube Audio Library, mixed low under the voice, out under the 1:05 "Rejected" pause and the close.

| Time | On screen | Narration | Words |
| --- | --- | --- | ---: |
| 0:00 | A real trace: the agent's finish message, "All tests pass. The fix is complete." Cut to the witness receipt: the spec test, still failing. | "This coding agent just said: done, all tests pass. It wasn't true." | 12 |
| 0:07 | One figure, `{A_false_pct}%`, counting up; labels: NVIDIA Nemotron 3 Super · {P_n} held-out SWE-rebench tasks · rule fixed in advance · official grader. | "On {P_n} real SWE-rebench tasks it had never seen, {A_false_pct} percent of its 'done' claims were false. That is SWE-rebench's own grader, not us." | 27 |
| 0:18 | Title card: Receipts. A three-step strip: Nemotron writes · a clean sandbox re-runs · plain code decides. Corner strip for the rest of the video: Nebius Token Factory · NVIDIA Nemotron. | "This is Receipts: the coding agent that is not allowed to grade its own homework. NVIDIA Nemotron 3 Super, running on Nebius Token Factory, writes the fix. A clean Token Factory Sandbox it never touched re-runs your tests, and plain code decides." | 41 |
| 0:33 | The featured task: repository, issue, the frozen failing test, the baseline failure text, the plan card (receipt site, run page). | "Here is a real bug from {featured_repo}. You write the failing test; that is the specification. Receipts records what fails and what passes before anything changes." | 27 |
| 0:45 | Agent lane, replayed from the record with a speed badge: reads, edits, test runs, then its finish claim. | "Nemotron plans, reads the code, edits, runs the tests, and reports back: done." | 13 |
| 0:55 | The checkpoint forks into a clean witness lane labelled Token Factory Sandbox. Only the source patch crosses; test files fall away. The gate's checks fill in with evidence. **REJECTED.** Two seconds of silence. | "Receipts ignores what it said. It forks the original checkpoint into a fresh Token Factory Sandbox, applies only the source change, and runs your tests itself. Rejected: the specification still fails." | 32 |
| 1:15 | The gate's evidence lines travel back to the agent verbatim. It fixes the source. A new witness from the same checkpoint. **VERIFIED.** | "The evidence goes back to the agent, word for word, once. It fixes the real problem. A new sandbox, the same checks. Verified." | 23 |
| 1:32 | The five checks with their evidence; "What it said" beside "What the record shows"; then the official SWE-rebench grader, run separately: resolved. | "The verdict comes from plain code. The specification passes, nothing that passed regressed, no test was removed or skipped, the patch stays out of your tests, and every step chains back to your code by digest. No model is asked whether the fix worked. And SWE-rebench's official grader, run separately, agrees." | 52 |
| 1:55 | A real terminal: `receipts reverify ... --executor tokenfactory`, sped up while it waits, with a visible speed badge; the AGREES lines at normal speed. | "Do not take our word for it. Anyone can re-check a receipt: on Token Factory Sandboxes in about two minutes, or with Docker and no account at all. It has to agree, check by check." | 35 |
| 2:10 | The pilot's scikit-build receipt: VERIFIED, then the official grader: not resolved. A small file tree with the package copy at the repository root. Amendment 2, dated. | "Making this impossible to fool is the hard part. In our own pilot, the gate shipped one false fix: the agent hid a copy of the package where our test runner found it. Our pre-registration made us publish it, fix it, and start over." | 44 |
| 2:30 | The three report numbers as cards, bound to the report. | "On {P_n} unseen tasks: {B_verified} verified fixes, {shipped_false_dones} shipped false dones, {cost_per_fix} of Nemotron tokens each. For every maintainer who would hand a bug to an agent, if they could believe its 'done'." | 34 |
| 2:45 | Close: repository and receipts URL, held four seconds. | "Agents can write the code. Receipts makes them prove it." | 10 |

Total: about 350 words in 170 seconds.

## Recording notes for the narrator

- Record the whole script in one take first as a scratch read (about 15 minutes, any microphone), to lock the timing; the final read comes after the numbers exist.
- Quiet room, soft furnishings around you, phone or laptop microphone 20 to 30 cm away, 48 kHz WAV if the app allows.
- Pause a full second after "It wasn't true", after "Rejected", and after "Verified". Stress "never touched" and "plain code".
- Numbers are read as written in the final script, which will spell them out (for example "twenty-four").

## Revision 3: picture changes from the video study

The narration above is unchanged. What is on screen changes as follows (reasons in `video-study.md`):

- **0:00 cold open, on black** (SecondVoice): the agent's real finish message types out in monospace, "All tests pass. The fix is complete." A beat of silence. "Was it?" in serif. Cut to the witness's real result: the spec test, FAILED, in red. The narration lands on "It wasn't true."
- **One architecture map** (Province, EcoLafaek): introduced at 0:18 as the three-step strip expanding into the map: your failing test → Nemotron 3 Super on Nebius Token Factory (agent branch) → a Token Factory Sandbox forked from the checkpoint (witness) → the gate, plain code → the receipt, with SWE-rebench's official grader to the side. It returns at 0:45, 0:55, 1:15 and 1:32 with the active node lit. The same diagram goes into the README and the Devpost text.
- **Sponsor technology on screen** (Nomi, EcoLafaek): at 0:45 a lower third shows the real model id from the run's disclosure (`nvidia/nemotron-3-super-120b-a12b`, Token Factory); at 0:55 the real sandbox image and operation ids from the receipt. If the owner captures the Token Factory console's Sandboxes page, it appears for two seconds at 0:55.
- **0:55 the mechanism, animated** (JohnKeats): the patch travels from the agent branch to the witness; test files fall away at the filter; the five checks light up in order; the failing one turns red; REJECTED stamps. Two seconds of silence.
- **1:32 proof, two labelled panes** (EcoLafaek): the receipt page and the official grader's log side by side, red circles on the lines that matter.
- **Captions burned in throughout**, one visual system from the receipt site: paper, ink, accent blue, verified green, rejected orange; IBM Plex Sans and Mono; serif only for the cold-open lines.
- **2:45 close**: "Nemotron writes the fix. Plain code decides." as on-screen text under the spoken line, then the URL and a QR code to the receipts site, held four seconds.
