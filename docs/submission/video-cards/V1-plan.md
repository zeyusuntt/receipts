# Receipts video V1 implementation plan

Goal: build the approved foundation and scenes 1 to 6, with evidence from the supplied content, offline fonts, beat-relative timing, and readable 2560 by 1440 frames.

Architecture: separate pure timing and crop selection from reusable visual components and beat scenes. Store the task's approved display copy in story.json alongside the existing facts. Preserve all existing facts and narration. Sequences cover pauses and the final hold. The architecture map also has its own still composition.

Constraints: edit only video; no installation, network, commits, or writes to other checkouts. The owner's explicit task approval supersedes skill approval gates and alternate worktree recommendations. Implement inline; perform a final read and visual review.

- [x] Verify timing, caption coverage, word cues, and semantic crop selection with offline Node tests, first failing and then passing.
- [x] Add fonts, palette, data-driven copy, components, composition and voice wiring.
- [x] Build six beat scenes and six placeholder beats. Use narration word proportions until recorded timestamps arrive.
- [x] Run TypeScript, timing tests, and attempt midpoint still rendering. Chromium cannot launch in this sandbox. Bundle and server-side scene checks pass; rendered visual and audio review remains unverified.

Review focus: gaps between narration beats, first-beat lead-in, fractional frame rounding, refreshed screenshot metadata, caption interference, true evidence rather than invented commands, and a two-second rejection hold.

Ruling: source approved editorial labels from this task into story.json; this lets every rendered text originate in one of the two content JSON files.
Ruling: the first real cold-open sentence is long and contains an inline filename. Fit the entire sentence in the lead-in rather than replacing it with the earlier script's illustrative quote.
Ruling: five gate checks use R1 to R5. R6 is the separate claim audit and is not presented as a sixth gate check.

Ruling: replay four five-second excerpts from the real attempt-one receipt timestamps at 10x. Disclose selected recorded steps so the montage is not mistaken for a continuous replay.

Ruling: retain the complete real plan card as a screenshot, with the task title and three short spec names displayed separately in large type. The captured plan's body text is supporting evidence; it needs browser review before final submission.

Verification: five pure behavior checks RED 0 passed, 5 failed; GREEN 5 passed, 0 failed. TypeScript and offline bundle pass. Server-side checks exercise all 12 scenes at start, midpoint and speech end, verify caption coverage, and compare the held rejection frames. The first hold assertion exposed Remotion's spring returning its exact resting value one frame after its configured duration; the check now starts at that resting frame.

Final review: separate read-only reviewer found no material defects and flagged small screenshot body text as an inferred visual concern. No rendered visual proof available. No commits or pushes.
