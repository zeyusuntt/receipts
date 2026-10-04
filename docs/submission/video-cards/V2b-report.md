# Receipts video V2b report

Implemented the approved V2b changes in video only. Preserved the uncommitted V2a foundation and 2560 by 1440 composition. No network, installations, commits, full-video render or submission-checkout access.

| Scene | Built | Main files changed |
| --- | --- | --- |
| 1, cold_open | Preserved the V2a picture; shared cue and caption timing now reads aligned timeline words automatically. | src/timing.ts, src/components/Captions.tsx |
| 2, who_and_numbers | Added the dark, rejected-colour and light dot legend under the grid. Reduced dot spacing to leave room for it. | src/scenes/who_and_numbers.tsx |
| 3, receipts | Rebalanced the shared architecture map. All node titles and subtitles stay on one line, with the original font sizes and frame margins. | src/components/ArchitectureMap.tsx |
| 4, featured_setup | Preserved the V2a issue and spec shot. The shared text helper keeps pytest identity and now lets surrounding prose wrap. | src/components/NodeText.tsx |
| 5, agent_works | Real display steps scroll upward in a terminal list, with five or six rows visible and the newest highlighted. Commands retain 48px type. Progress runs across the beat with the existing selected-steps 10x badge. The real quoted claim occupies the last 1.5 seconds. | src/scenes/agent_works.tsx |
| 6, rejected | Separated the large stamp from the evidence card. The final shot holds the complete failing test evidence beneath the stamp. Moved the source-patch label clear of map text. | src/scenes/rejected.tsx |
| 7, appeal_passes | The real appeal's first two lines and final instruction travel from Gate toward the agent on the map. Separate shots show both patch files, w2 from the same checkpoint, all five passing checks and the VERIFIED landing at the narration cue. | src/scenes/appeal_passes.tsx, src/components/GateChecks.tsx |
| 8, checks_and_official | Large plain check names and real attempt-two evidence, with shortened UUIDs. No-model emphasis follows the supported narration cue. Then the captured paper receipt and a separately labelled official resolved result appear together, with a red drawn circle. | src/scenes/checks_and_official.tsx, src/components/GateChecks.tsx |
| 9, reverify | Actual OffthreadVideo recording, normal-speed command and result excerpts, computed waiting speed, recording elapsed timer, normal-speed final output and a held result. Docker label follows its word cue. | src/scenes/reverify.tsx, src/timing.ts |
| 10, pilot_story | First-pilot PASS beside not resolved; a repository tree contrasts the real src package with all shipped root files. The amendment, fix commit and rerun checklist follow the narration. | src/scenes/pilot_story.tsx |
| 11, results | Three large cards: 66 verified fixes, zero false fixes shipped and $0.41 of Nemotron tokens per fix. The 66-of-66 agreement line comes from the report numbers. | src/scenes/results.tsx |
| 12, close | Centred closing lines, repository URL, offline qrcode SVG to the receipts site and the small plain-code tagline. The complete card stays through the end hold. | src/scenes/close.tsx, scripts/generate-qr.mjs, public/receipts-qr.svg |

Other files changed: src/Video.tsx wires all twelve scenes; src/scenes/types.ts includes scene duration; src/content/story.json stores approved display copy and measured recording metadata; scripts/extract_story.py preserves that metadata and includes the real package's build path; package.json regenerates the QR before studio, stills and render commands; scripts/check-video.mjs and scripts/check-frames.mjs exercise timing and scene behavior; V2b-plan.md records decisions.

All displayed run facts match a fresh extraction from the main checkout. The existing run facts, narration and timeline file were not changed. Captures and audio were read without modification.

Aligned words use global seconds in beat.words, with fields w, start_s and end_s. Captions and all cueFrame consumers convert those values to composition frames automatically. The optional older frame timestamp prop remains supported when aligned words are absent. Only beats without aligned words use word proportions. Caption text follows the aligned transcription if it differs from the scratch text.

The reverify recording is 104.12 seconds, 2560 by 1440 at 25 fps, measured with ffprobe. Source seconds 1 to 5.8 show command typing at 1x; 5.8 to 100.6 are the waiting interval; 100.6 to 102.2 show the real final result at 1x. The result is then held for at least one second and through the beat gap. The installed Remotion source was checked to confirm playback-rate and trim mapping. The timer uses media seconds, never playback elapsed time or the CLI's own wall-time figure.

The current beat has 265 speech frames. Typing takes 144, waiting 43, final output 48 and the required hold 30. The 94.8-second wait therefore displays 66.14x. This number is computed, not stored as a fixed playback rate.

Verification:

- npx --no-install tsc --noEmit: passed.
- Existing timing suite with three new regressions: 11 passed, zero failed. The three additions first failed against the old timing implementation.
- Server-side scene suite: 10 passed, zero failed. It also renders all twelve actual scenes at their start, midpoint and speech end, checks continuous fallback captions, the rejection hold and the final close hold.
- Added failing-then-passing checks for prose width and newest-row visibility, including capture patch immediately before the claim.
- Python extraction suite: two passed. A full refresh into video/out/checks/refreshed-story.json matches cold_open, featured, numbers, pilot_v1, presentation and media exactly.
- Offline Remotion bundle: passed. No browser or full-video render was performed.
- git diff --check -- video: passed.
- Measured bundled font advance widths for all architecture titles and subtitles. Receipt needed smaller padding; its 181.8px title now fits the 186px inner width when lit.
- A separate read-only review found the prose overflow and scrolling visibility issues. Both are fixed and covered by regression checks.

Limits and decisions:

- The current timeline is still the scratch voice and has no real aligned word arrays. Synthetic aligned timing tests pass; final voice synchronization and audio playback remain unverified.
- Browser layout, motion appearance and actual OffthreadVideo decoding remain unverified. Server-side checks exercise scene logic and authored geometry, not browser pixels. The receipt screenshot's small body text remains supporting evidence; the preceding shot presents the actual checks in readable text.
- The current narration does not contain No model decides any of it. The emphasis therefore lands on plain code. The exact no-model sentence takes priority if it appears in the regenerated narration.
- The agent list is a selected-step montage paced across the beat, with the requested existing 10x badge. It does not claim to replay the complete 151-second attempt continuously.
- The recording's printed CLI wall-time result says 114 seconds, while the video file itself lasts 104.12 seconds. The new timer accurately counts the recording's source seconds. The footage was not altered to reconcile those different clocks.
- A regenerated reverify beat must leave more than 7.4 seconds for normal typing, normal final output and the one-second hold. A shorter beat raises an explicit error instead of silently speeding the protected excerpts. Waiting speed is recalculated from every new timeline.
- Key evidence and closing information hold in the current cut. Very short replacement narration or compressed gaps still need a visual timing review.
