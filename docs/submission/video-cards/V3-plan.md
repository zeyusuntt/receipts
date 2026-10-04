# Task card V3: the Receipts video at winner level (narration revision 6)

Approval is already given by the owner (2026-10-04, "可以改吧"). Do not stop to ask; where this card leaves a choice, make it, and list it in your report.

## Where and what

- Repository `/Users/sunzeyu/dev/nebius-hackathon`. Work only in `video/` (including `video/scripts/extract_story.py` and its test). Do not commit. No network.
- Remotion 4.0.532, composition `Receipts`, 2560x1440 at 30 fps. Scenes `video/src/scenes/*.tsx`, components `video/src/components/`, timing `video/src/timing.ts`, theme `video/src/theme.ts`.
- Facts: `video/src/content/story.json`, written by `video/scripts/extract_story.py --repo /Users/sunzeyu/dev/nebius-hackathon --out video/src/content/story.json` (run with `PYTHONPATH=src .venv/bin/python` from the repository root). Its `presentation` object is the on-screen copy and is preserved across re-extraction. Nothing on screen is typed by hand if it is a fact from the records.
- Narration: `video/src/content/timeline.json`, already regenerated for revision 6 (`python3 video/scripts/timeline.py scratch`). Do not edit it by hand. The text is in `docs/submission/video-script.md`, section "The narration to record (revision 6)".
- Captures (gitignored, present on disk): `public/captures/site/*.png` and `*.json`, `public/captures/reverify-tf.mp4`, and NEW `public/captures/console/{sandboxes-about,usage,operations}.png` with `boxes.json`: real Nebius Token Factory console screenshots (1x, already cropped to remove the organization id, project id and balance), with a highlight box per image in crop pixels and a description of each.
- You cannot launch Chromium. The main session renders stills and reviews them. Your proof is `npm run check` in `video/` (tsc, `scripts/check-video.mjs`, `scripts/check-frames.mjs`) and the Python test `video/scripts/test_extract_story.py`.

## Why

A review against the four judging criteria (Technological Implementation, Design, Potential Impact, Quality of Idea) scored the draft 8 / 7 / 6 / 9. Points are lost because: the product name lands at 0:30 and the audience at 2:21; Token Factory and Nemotron appear mostly as diagrams; many frames are sparse, centered-title-plus-cards, with text too small to read in a Devpost embed; the receipt, which the product is named after, is a tiny screenshot. The fixes below copy what 12 studied winners did (`docs/submission/video-study.md`): SecondVoice's one consistent type and colour system and cold open; Province's architecture map with the active component lit; JohnKeats' data flowing through gates; Nomi's and EcoLafaek's sponsor console pages and "requirements met" card; red hand-drawn annotations on real screenshots; holds after key moments; a two-part closing line with a QR code.

## Design system (apply to every scene)

- Type: IBM Plex Sans for our own words (titles, labels, numbers). IBM Plex Mono only for machine evidence (commands, test ids, hashes, terminal, the receipt paper). IBM Plex Serif only in two places: the cold-open "Was it?" and the closing tagline. The 17.9% figure and every other serif use become Plex Sans 600 with tabular figures.
- Type scale at 2560x1440: big numbers 160 to 220; titles 88; headings 64; body 48, the minimum for anything the viewer must read; mono evidence at least 40; ids and other non-essential meta at least 34. No `fontSize` below 34 anywhere under `src/` (add a static test).
- Colour: keep the `theme.ts` tokens. One failure colour, `palette.rejected`, for every failure state (the hand-drawn circle's `#B92318` goes). Annotations on screenshots are `palette.rejected`, about 6 px, a rounded rectangle with a slight rotation, like the winners' red circles.
- Layout: remove the permanent `CornerStrip` sponsor line; sponsors appear inside the content instead. No beat opens on an empty or nearly empty frame and no card is ever shown empty. Captions own the bottom band (y >= 1240): nothing else goes there. Side margins 128.
- Motion: one idea per shot; reveals happen on narration cues, not as fade-and-slide on every element. Holds: FAILED in the cold open at least 1.5 s; REJECTED at least 2 s (already tested); VERIFIED at least 1.5 s; the finished receipt at least 2 s; the close at least 4 s.

## Scenes (beat ids from timeline.json)

1. `cold_open`: keep. FAILED in `palette.rejected`, the failing test id at least 48 mono, the meta line at least 36. Ensure the 1.5 s hold.
2. `who_and_numbers` (narration: "I'm Zeyu. I build evaluations for AI agents, so I measured this. I gave NVIDIA's Nemotron 3 Super a hundred real bugs. It said "done" sixty-seven times. / Twelve weren't true. / If you're the one merging, you can't tell which twelve."):
   - No standalone introduction frame. From the beat's first frame: the 100-dot grid, large, in the left half; heading "100 real bugs from 100 open-source projects" (the project count comes from data, see below) and the subline "picked by a rule fixed before the first run".
   - A lower third, bottom left just above the caption band: "Zeyu Sun" (64, 600) over "builds evaluations for AI agents" (40), in for about 3.5 s from the beat start, then out.
   - Dots: 67 fill ink on "sixty-seven"; 12 of them turn `palette.rejected` on "Twelve"; on "which twelve" all 67 return to the same ink colour, so the red ones become indistinguishable (the picture of "you can't tell which twelve").
   - Right half: "17.9%" (Sans 600, about 220, `palette.rejected`) with "of the unguarded agent's “done” was false" (48) and "by SWE-rebench's own grader · 95% interval 10.6 to 28.7%" (36). Drop the small legend.
3. `receipts` ("So I built Receipts: a coding agent that isn't allowed to grade its own homework. Nemotron writes the fix, on Nebius Token Factory. Then a fresh Token Factory Sandbox it never touched runs your tests again, / and plain code decides."):
   - On "Receipts": the wordmark and tagline for about 3 s, then the architecture map takes the full width with larger text (node titles 56, sublines 40, mono tags 36).
   - Nodes light on their cues: the agent node on "Nemotron", with the real model id `nvidia/nemotron-3-super-120b-a12b` in mono under it; the witness node on "Token Factory Sandbox", and at the same time the real console crop `sandboxes-about.png` appears beside or below that node at about 1.8x with the red annotation on its "Checkpoint & branch" box and the label "Nebius Token Factory console"; the gate node on "plain code". The SWE-rebench grader side node stays.
   - No repeated "Receipts" title over the map; the map is the picture. Later scenes keep reusing the map with the active node lit.
4. `featured_setup`: keep (just fixed). Spec test ids at least 44.
5. `agent_works` ("Nemotron reads the code, edits it, runs the tests, and says it's done."): replace the fast command stream with three action rows that light on "reads", "edits" and "runs the tests". Each shows one real step from `story.featured.agent_steps` (kinds are `command`, `write`, `diff`): a read (a grep or find command), an edit (`write fs/ftpfs.py`), a test run (a `pytest ...` command with its exit code). Add a count from data ("24 recorded steps"). On "done": the agent's attempt-1 claim as a quote (52) with the model id under it.
6. `rejected`: keep the structure. Check labels 48, PASS and FAIL 40, the evidence card text at least 44, the id lines at least 34. While the map is on screen use no heading (or a short one from the narration); after the failure keep "The spec still fails."
7. `appeal_passes`: the failure evidence travels as a card from the gate back to the agent node (data moving through the map), readable (mono 40). Keep "New sandbox. Same checkpoint." VERIFIED holds at least 1.5 s.
8. `checks_and_official`, the receipt is the hero. Replace the checks table and the small screenshot with a printed paper receipt: thermal-receipt look (paper colour, mono 40, a column about 900 wide, zigzag torn bottom edge, soft shadow), left of centre.
   - It prints line by line on the narration cues: a header "RECEIPT · pyfilesystem__pyfilesystem2-462" and "PyFilesystem/pyfilesystem2 @ ac8a91a"; then one line per check, each ending in PASS, as its cue is spoken: "spec: 3 of 3 target tests now pass", "kept: 333 of 333 passing tests still pass", "removed or skipped: none (342 collected)", "scope: 2 files, none of them tests", "steps: 36 agent + 2 witness, hash-chained"; then "attempt 1 rejected · attempt 2 verified", "model: Nemotron 3 Super on Nebius Token Factory", "904,972 tokens · $0.28", "witness: fresh sandbox from checkpoint bc230a98"; then a VERIFIED stamp lands on the paper and holds.
   - Every value comes from data (predicate evidence, `featured.cost`, checkpoint id, receipts per branch); extend `readableEvidence` and `extract_story.py` as needed.
   - Right side: "No model decides any of it." (64, accent) on its cue. Then, on "SWE-rebench's grader, run separately, agrees", the official grader panel: the instance id, "resolved" in `palette.verified` with the hand-drawn circle also in `palette.verified`, and "agrees with the gate" (40).
9. `reverify`: keep. Header text at least 40. The final frame with "(114s)" must hold readably.
10. `pilot_story`: no empty cards. Open with both outcome cards filled (the gate: PASS; the official grader: not resolved) on the cue "let one bad fix through", then the file tree, then the checklist (at least 44).
11. `results` ("On the hundred bugs: sixty-six verified fixes, zero false ones shipped, about forty cents of Nemotron tokens each. / It all ran on Nebius Token Factory: eighty-seven million Nemotron tokens, nearly five hundred sandboxes. / That's what I want before I merge anything an agent wrote: a receipt I can re-run."):
    - Part A, from the start: a before and after. Left column "Nemotron on its own": "67 said done" and "12 were false" (`palette.rejected`). Right column "With Receipts": "66 shipped" and "0 false" (`palette.verified`). Under them: "by SWE-rebench's official grader, on these 100 bugs" (36) and "$0.41 of Nemotron tokens per verified fix" (48).
    - Part B, on "It all ran on Nebius Token Factory": a "Built on Nebius Token Factory" proof frame. Left: the console usage crop with the red annotation on the Nemotron-3-Super rows, labelled "Token Factory usage, Sep 4 to Oct 4 2026, all development and runs". Right: the operations crop (real Sandbox runs, Success) with an annotation, labelled "Token Factory Sandboxes, real operations". Across it, three numbers from data: "87,379,659 Nemotron tokens", "482 sandboxes", "4,253 hash-chained steps", with "over the 100 tasks".
    - Part C, on "a receipt I can re-run": the receipt from scene 8 (reuse the component, compact or its top part) beside the command `receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json`.
12. `close`: keep the serif two-line tagline, the URL and the QR; hold at least 4 s. The small subline goes, or is at least 40.

## Data (`extract_story.py`; nothing typed by hand)

- The 100 ran tasks are `pilot/v2-P/report.json` `instances` whose `b_outcome` is not `infrastructure error` (that leaves 100; music21 and natcap are the two excluded by the pre-registration's amendments).
- `numbers.repos`: distinct repositories among them (instance id without its trailing `-<number>`); expect 100.
- `numbers.scale`: `tokens` = `spend.final.tokens` (87,379,659); `sandboxes` = the number of `branches/*/receipts.jsonl` files in each ran task's `run_dir` (482); `steps` = the total non-empty lines in those files (4,253).
- The featured run's receipt lines, from its record and verdicts: tokens 904,972, model dollars 0.28, the checkpoint id, receipts per branch, predicate counts.
- Console highlight boxes come from `public/captures/console/boxes.json` (capture metadata, not story facts).
- Update `video/scripts/test_extract_story.py` for the new fields.

## Cues

Update every cue phrase in `presentation` to the revision-6 narration. For example, `who_and_numbers` has no "by SWE-rebench's own grader" any more; check-frames currently fails with "Narration cue missing: who_and_numbers: by SWE-rebench's own grader". Every cue must exist in its beat's text.

## Tests to add (SSR checks; keep every existing hold and cue test)

- A static test: no `fontSize` below 34 in `src/**/*.tsx`, and `Video.tsx` no longer renders `CornerStrip`.
- `who_and_numbers`: the dot grid is present at the beat's first frame; the lower third is present at 1 s and gone at 5 s.
- `checks_and_official`: the receipt contains each check line by the end of the narration, VERIFIED, and "agrees with the gate" after the grader cue.
- `results`: part B contains both console images and the three scale numbers; part C contains the reverify command.
- `pilot_story`: at the first frame where the outcome cards appear, the gate card already contains PASS.

## Rules

- Plain on-screen English, sentence case, no em dashes. No all-caps labels except the stamps (VERIFIED, REJECTED, FAILED) and the receipt header, which imitates a printed receipt.
- Match the existing code style; keep scene files readable; reuse components (the map, Stamp, NodeText, ScreenshotPushIn) rather than duplicating them.
- Report: the changes per scene, every new data field with its value, the test results, and each choice you made where this card left one open.
