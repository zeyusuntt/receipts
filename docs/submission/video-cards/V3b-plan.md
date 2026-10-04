# Task card V3b: fixes from the V3 render review

Approval is already given. Same rules as `V3-plan.md` (work only in `video/`, no commit, no network, no Chromium; proof is `npm run check` and the extract test). The main session rendered V3 and reviewed it frame by frame; these are the defects, in priority order. Every on-screen fact still comes from data.

## 1. The receipt is cut off and wraps badly (scene `checks_and_official`, and its reuse in `results` part C)

- The paper's top is above the frame: the header line is hidden. The whole receipt must sit inside y 110 to 1220 (above the caption band), with its top edge visible.
- Lines wrap mid-phrase ("still / pass", "(342 / collected)", "hash- / chained", "attempt 2 / verified", "on Nebius / Token Factory"). No receipt line may wrap: widen the paper to about 1180 and use mono 38, and keep each line at most 46 characters. Header: "RECEIPT" on its own line, then the instance id, then the repository line. Suggested lines: "spec: 3 of 3 target tests pass", "kept: 333 of 333 passing tests", "removed or skipped: none", "scope: 2 files, no tests", "steps: 36 agent + 2 witness, chained", "attempt 1 rejected, attempt 2 verified", "Nemotron 3 Super · Nebius Token Factory", "904,972 tokens · $0.28", "witness: fresh fork of bc230a98". Use the values from data as now.
- The VERIFIED stamp sits fully on the paper, not on the torn edge.
- Add a static or SSR test that the receipt's top is at least 110 and its bottom at most 1220, and that no receipt line exceeds 46 characters.
- In `results` part C, the compact receipt follows the same rules, and the reverify command box is wide enough that `receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json` stays on one line (mono 36 is fine), or breaks only after `reverify`.

## 2. The Token Factory proof is unreadable (scene `results` part B)

The console crops are 1x screenshots shown at about 1000 px wide, so their text is too small. Make them readable with push-ins, one idea per shot:

- On "It all ran on Nebius Token Factory": the heading "Built on Nebius Token Factory" and both crops side by side for about 1.5 s (as now).
- On "eighty-seven million": the usage crop takes the stage and pushes in on its highlight box (the two Nemotron-3-Super-120B rows) so that box is about 2200 px wide; the red annotation stays on it. Below it, big: "87,379,659" (120, Sans 600) and "Nemotron tokens over the 100 tasks" (48).
- On "five hundred sandboxes": the operations crop takes the stage, pushed in on its header and first five rows (about 2200 px wide), with the annotation around those rows. Below it, big: "482" and "4,253" (120) with "sandboxes" and "hash-chained steps over the 100 tasks" (48).
- Shorten the usage label to "Token Factory usage, Sep 4 to Oct 4 (all of development)" so it fits on one line; the operations label stays "Token Factory Sandboxes, real operations".
- Extend `boxes.json` only if you need a second highlight box (for the operations push-in); keep the existing keys.

## 3. `who_and_numbers`

- The 17.9% block (number, "of the unguarded agent's “done” was false", the grader and interval line) appears on the "Twelve" cue, not at the beat start.
- The heading fits on one line (shorten to "100 real bugs, 100 open-source projects" or size it down to 64).
- Centre the composition vertically between y 110 and 1220. The lower third must not overlap the dot grid.

## 4. `results` part A, the before and after

Make it the impact moment. Two columns, vertically centred. Left, "Nemotron on its own" (48): "67" (120) with "said done" (48), then "12" (180, `palette.rejected`) with "were false" (48). Right, "With Receipts" (48): "66" (120) with "shipped" (48), then "0" (180, `palette.verified`) with "false" (48). Under them: "by SWE-rebench's official grader, on these 100 bugs" (36) and "$0.41 of Nemotron tokens per verified fix" (48). The 12 and the 0 are the largest numbers in the video after 17.9%.

## 5. Vertical balance and small text elsewhere

- `receipts`: between the wordmark and the console inset, the map sits at the top with an empty lower half for about 6 s. Keep the tagline ("the coding agent that isn't allowed to grade its own homework", 56) under the map until the console inset appears.
- `appeal_passes` "This time it passes." and "Same five checks.": the check rows at 44 at least, and the block centred horizontally.
- `pilot_story`: the file tree (mono 44) and the checklist (48) centred vertically; no content block pinned to the top with an empty bottom half.
- `agent_works`: the action label column wide enough that "reads the code" does not wrap.

## 6. The draft mark

Move "DRAFT · placeholder voice" to the top right, where the removed corner strip was, so it never covers a heading. It still appears only for scratch timelines.

## Report

The changes per item, the tests added, and any choice you made.
