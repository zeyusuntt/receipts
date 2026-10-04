# Task card V3e: the witness run in the console, and `receipts fix` on another repo

Approval is already given. Same rules as the earlier V3 cards (work only in `video/`, plus `video/scripts/extract_story.py` and its test; no commit, no network, no Chromium; proof is `npm run check` and the extract test). Since V3d the main session added one narration sentence and regenerated `timeline.json`, added `media.fix` to `story.json` (preserved across re-extraction), and added a `witness-operation` entry and image to `public/captures/console/`. Keep all of that.

## 1. The witness run, as the Token Factory console shows it (`appeal_passes`)

The judges asked to see one real Sandbox operation tied to our record. The owner looked up the featured run's attempt-2 witness test run in the Nebius Token Factory console and took a screenshot: `public/captures/console/witness-operation.png`, described in `boxes.json` under `witness-operation` (a highlight box on the Operation UUID and one on the Success status).

- Data: in `extract_story.py`, add `featured.witness_operations`: for each witness branch of the featured run (`w1`, `w2`), the operation id from the run's `cost.json` `sandbox_usage` entry for that branch with the largest `duration_s` (its test run). Expected: `w1` is `01a0ff61-b8fb-77a8-a0a0-dc178108f719`, `w2` is `01a0ff63-2a85-72ca-b4a5-6acd9e56af33`. Test it.
- Picture: on the appeal cue "A fresh sandbox" (the sentence "A fresh sandbox runs the same checks again."), show the console crop (about 1.4x, readable) with the red annotations on the UUID and on Success, labelled "This witness run in the Nebius Token Factory console" (36). Beside or under it, our record's line in mono: "receipt record · witness w2 · operation 01a0ff63-2a85-72ca-b4a5-6acd9e56af33", with the id highlighted the same way, so the two ids visibly match. Then continue to "This time it passes." and the VERIFIED hold as now. Nothing overlaps; everything inside y 110 to 1220.

## 2. `receipts fix` on another repo (`results`, part D)

The narration's results paragraph now ends "... a receipt I can re-run. / On another repo, it's one command and a failing test." On the cue "On another repo", after the pull request card:

- Show the real terminal recording `media.fix` (`captures/fix-tf.mp4`) the way `reverify` shows its recording: same panel, the same replay plan that plays the typing and the result at 1x and speeds up the wait with a visible speed badge, and the same "real recording · the waits are sped up" note. Header (48): "Another repo, one command: PyFlakes issue 335 on Nebius Token Factory Sandboxes". The run took 1m 7s and the recording's result appears at 77 s (`result_start_s`); hold the final frame (the five ✓ lines, "VERIFIED in 1m 7s · $0.03 of Nemotron tokens" and the receipt path) until the close.
- Fit the terminal like `reverify` does: the widest line must be whole, and the last line ("receipt: runs/pyflakes-335/receipt.md") visible above the caption band. The recording's content spans roughly x 70 to 2010 and y 70 to 1300 of 2560x1440 at its final frame; scale and crop so all of the final screen from the "Fixing:" line down to the receipt line is visible and readable.
- Reuse the reverify scene's components; do not duplicate the replay logic.

## 3. Length

The scratch timeline is now 2:47. Keep the close's 4-second hold. If the results beat needs more time than its narration gives, take it from the end hold of the results beat, not from the close.

## Tests

- `appeal_passes` shows the console image and the record line with `01a0ff63-2a85-72ca-b4a5-6acd9e56af33` after the cue.
- `results` part D shows the fix recording after "On another repo" and holds its final frame; the replay plan plays the typing and the result at 1x.
- Data: `featured.witness_operations` values as above.

## Report

Changes, new data values, tests, choices made.
