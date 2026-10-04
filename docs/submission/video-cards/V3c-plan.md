# Task card V3c: last layout fixes from the V3b render review

Approval is already given. Same rules as `V3-plan.md` and `V3b-plan.md` (work only in `video/`, no commit, no network, no Chromium; proof is `npm run check` and the extract test). Note: since V3b the main session changed the narration slightly (`timeline.json` regenerated) and repointed three cues in `presentation` (`cues.title` is "I built Receipts", `appeal.cues.patch` is "It finds the real problem", `appeal.cues.fork` is "A fresh sandbox") and the appeal title; keep those.

## 1. `results` part B: the operations push-in covers the heading

- When a console crop takes the stage, its panel must start below the heading "Built on Nebius Token Factory" (top at least 200), or the heading fades out first; the heading's text is never overlapped or clipped.
- The numbers under the operations crop: "482" over "sandboxes" and "4,253" over "hash-chained steps", each label on one line, then a single centred line "over the 100 tasks" (40) under both. Same for the usage push-in ("87,379,659" over "Nemotron tokens", then "over the 100 tasks").
- Test: at the push-in frames the panel's top is below the heading's bottom, and no label wraps (character budget or width check).

## 2. The receipt prints like a receipt

While lines print in `checks_and_official`, the paper is already full height, so half of it is blank paper for several seconds. Make the paper grow with its content: its height is the printed lines plus padding, animated smoothly (about 0.25 s per new line) as each line appears, with the torn edge moving down; it reaches full height when the last line and the VERIFIED stamp land. Keep the top edge fixed at its current position and the bottom within 1190. The compact reuse in `results` part C shows its final (complete) state.

Test: at a frame after the first check line and before the third, the paper's height is less than 60% of its final height; at the end of the narration it equals the final height.

## 3. `who_and_numbers`: the right half is empty for 15 s

Fill the right half with a counter that follows the narration, one idea at a time, replacing each other in place (same position, crossfade):

- on "a hundred": "100" (220, Sans 600) over "real bugs" (48);
- on "sixty-seven": "67" over "said “done”" (48);
- on "Twelve": the existing 17.9% block ("17.9%", "of the unguarded agent's “done” was false", the grader and interval line), with "12 of 67" (64, `palette.rejected`) above the percentage.

Also enlarge the dot grid by about 1.4x (dots and gaps), and centre the heading, grid and counter as one composition vertically between y 110 and 1220. The lower third stays clear of the grid.

Test: the right-half counter shows "100", then "67", then "17.9%" at frames after each cue.

## 4. `results` part A: bigger

Scale the before-and-after up so it fills the frame: column headers 56; "67" and "66" at 160 with labels 56; "12" and "0" at 260 with labels 56; the grader line 40; "$0.41 of Nemotron tokens per verified fix" 56. Keep it vertically centred above the caption band, and the divider between the columns.

## Report

The changes per item, the tests added, and any choice you made.
