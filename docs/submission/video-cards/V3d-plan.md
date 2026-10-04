# Task card V3d: show the maintainer's step (the pull request description)

Approval is already given. Same rules as the earlier V3 cards (work only in `video/`, plus `video/scripts/extract_story.py` and its test; no commit, no network, no Chromium; proof is `npm run check` and the extract test). Since V3c the main session changed some narration lines and cues (`timeline.json` regenerated; `cold_open.cue`, `proof.check_cues`, `proof.no_model_cues`, `appeal.cues.return` updated); keep them.

## Why

The judges' second pass scored Impact 8 and said the video "barely shows how a maintainer would use Receipts during real work". Receipts already writes a pull request description for every verified run (`_pr_description` in `src/receipts/site.py`, shown on each receipt page of the site). Show that real output at the moment the narration says "That's what I want before I merge anything an agent wrote: a receipt I can re-run."

## Data

In `extract_story.py`, add `featured.pr_description`: the exact string `receipts.site._pr_description` returns for the featured run (build the site's `_Run` for it the way `site.py` does; do not retype the text). It begins "Fixes pyfilesystem__pyfilesystem2-462: FTPFS should use MDTM." and contains the "Verified by Receipts on a fresh sandbox the agent never touched:" lines and the `re-verify:` line. If the last line contains the placeholder "[your name]", keep it as is. Update `test_extract_story.py` (the field exists, starts with "Fixes pyfilesystem__pyfilesystem2-462", contains "re-verify: uv run receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json").

## Picture (`results` part C, from the cue "a receipt I can re-run" or the start of that sentence, whichever reads better)

- Left: the compact receipt as now (complete state).
- Right: a pull request card styled plainly like a code-host PR description: a small label above it, "Pull request description, written by Receipts" (36, secondary); the first line as the PR title (Sans 600, 44); the body in mono 34 on paper, lines wrapped only at word or path boundaries; the `re-verify:` line highlighted with the red annotation (`palette.rejected` rounded rectangle). Remove the separate reverify command box (the PR card carries it).
- Both inside y 110 to 1220, nothing overlapping, and the part holds until the close.

## Tests

- `results` part C contains the PR title line and the re-verify line, and no longer renders the separate command box.
- The PR card's lines fit its width (character budget for mono 34) and the card bottom is at most 1220.

## Report

Changes, the new field's value, tests, choices made.
