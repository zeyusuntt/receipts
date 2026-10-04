# Receipts video V2b implementation plan

Goal: complete the approved twelve-scene cut, preserving V2a's paper, ink, typography, frame margins and evidence sources.

Architecture: retain one component per beat and add small shared check and replay components. Aligned timeline words are global seconds and become composition frames at the timing boundary. Source media times stay in story.json; scene lengths always come from the current beat.

Scope: only video files. No network, installs, commits, full-video render or submission-checkout access. The user's explicit approval and inline implementation request supersede extra approval and worktree steps.

- [x] Add failing timing checks for aligned words, retimed replay boundaries, and the final claim hold. Implement automatic aligned captions and cues.
- [x] Refine the scrolling attempt, unobstructed rejection evidence, map widths and grid legend. Preserve minimum text sizes.
- [x] Build appeal, source files, checkpoint fork, five passing checks and the verified landing. Build large check evidence followed by separately labelled receipt and official result panes.
- [x] Build the real OffthreadVideo replay with normal typing, computed waiting speed, recording elapsed time, normal results and a hold. Build the pilot mismatch, repository tree and remediation checklist.
- [x] Build results and the closing lines, URL and offline qrcode SVG. Wire all twelve scenes and verify TypeScript, timing tests and server-side scene checks.
- [x] Review the scoped changes and write V2b-report.md with scene coverage and limitations.

Review focus: aligned word times versus proportional fallback; a recording shorter than normal-speed excerpts; receipt capture cropping; evidence and stamps sharing space; final card holds after narration.

Ruling: retain the current narration and support both the exact no-model sentence and the existing plain-code cue. The on-screen assertion is approved display copy in story.presentation.

Ruling: the terminal list is a montage of recorded display steps, paced across its beat. The existing selected-recorded-steps label and 10x badge remain; it is not presented as a continuous 151-second terminal recording.

Ruling: media metadata belongs in story.json and survives story extraction. No scene relies on scratch beat start times.

Verification: three new timing checks first failed and then passed. Scene checks caught the missing later beats and early capture-patch behavior. Review identified unbreakable prose and a newest-row visibility defect; each received a failing regression check and a fix. Final results: TypeScript passed, 11 timing tests passed, 10 scene tests passed, two extraction tests passed, offline bundle passed, and refreshed facts match the source content.

Ruling: prose may wrap at spaces; pytest class and function segments remain intact. This fixes overflow without changing any evidence text.

Ruling: retain 48px trace commands, 32px supporting evidence, 40px check text, 46px captions, 52px map titles and 40px map subtitles. Long trace commands receive taller rows. The receipt node has smaller horizontal padding so its existing title fits.
