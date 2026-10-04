# Receipts video V1 report

Built the foundation, scenes 1 to 6, and placeholders for scenes 7 to 12. Everything written by this task is inside video. No dependency installation, network calls, commits, pushes, or changes to the submission checkout.

## Files

Created:

- src/theme.ts: site palette and seven locally bundled IBM Plex font weights and styles.
- src/timing.ts and src/content.ts: timeline windows, caption chunks, narration cues, semantic screenshot regions, and content imports.
- src/components/ArchitectureMap.tsx, Captions.tsx, CornerStrip.tsx, CountUp.tsx, LowerThird.tsx, Motion.tsx, ScreenshotPushIn.tsx, Stamp.tsx.
- src/scenes/cold_open.tsx, who_and_numbers.tsx, receipts.tsx, featured_setup.tsx, agent_works.tsx, rejected.tsx, Placeholder.tsx, types.ts.
- src/ArchitectureStill.tsx: standalone ArchitectureMap composition for README export.
- scripts/check-video.mjs, check-frames.mjs, render-stills.mjs.
- V1-plan.md and this report.

Updated src/Root.tsx, src/Video.tsx, src/content/story.json, scripts/extract_story.py, package.json, and .gitignore. Generated build and out artifacts are ignored. Existing story facts and narration were preserved. Captures and audio were not edited by this task.

## Timing and content

Receipts remains 2560 by 1440 at 30 fps. Its duration is ceil(timeline.total_s times timeline.fps), currently 4,612 frames and approximately 153.733 seconds. The scratch WAV is also 153.733 seconds and already contains the lead-in and end hold.

Each beat has a Sequence based on its start. Scene props include the local speech start and duration. The cold open starts at frame zero. Each scene holds through the gap before the next beat; a six-frame crossfade overlaps the next scene. The final card holds through the end of total_s.

Reveals use local narration cues and beat durations, with no absolute scene start times. Caption chunks contain at most 12 words, break at sentences, preserve every word, and allocate frames proportionally to word count. Video accepts optional wordTimestamps by beat id for captions and narration cues. Timestamp start and end values are global composition frames. Final recorded timestamps are needed for exact word synchronization.

Video also accepts an optional musicTrack path under public, with musicVolume defaulting to 0.08. Default music is none. The sponsor strip starts with the receipts beat and stays through the close. Captions use a separate bottom area.

ScreenshotPushIn matches a containing box by text, converts CSS coordinates to image pixels using capture.scale, and applies a slow push-in. The featured plan card is selected with The plan, so a fresh capture can relocate it without code changes.

## Verification

- npx --no-install tsc --noEmit: passed.
- Five pure timing and crop behavior tests: first 0 passed and 5 failed because the features were absent, then 5 passed and 0 failed.
- Final npm run check: passed TypeScript, all five behavior tests, server-side HTML renders of all 12 beats at start, midpoint, and speech end, and continuous captions across 4,267 narration frames. The rejection scene remains identical for two seconds after its spring settles; the final card is preserved through the end hold.
- npx --no-install remotion bundle src/index.ts out/bundle --log=error: passed with local font assets and current capture metadata.
- git diff --check: passed.
- Separate read-only final review: zero material defects; one inferred screenshot readability concern described below.

## Rendering limitation

The requested still attempt was:

```sh
npx --no-install remotion still src/index.ts Receipts out/stills/cold_open.png --frame=159 --log=error
```

Chromium exited with SIGTRAP. Its fatal error was bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer: Permission denied (1100). This sandbox cannot launch the browser. No still images were generated. Browser layout, actual font appearance, animation quality, and audio playback were not visually or audibly verified. Server-side HTML checks do not prove those properties.

From video on a machine that permits Chromium, run npm run stills. It calculates every midpoint from the current timeline and runs the requested Remotion still command for each beat, followed by the standalone architecture still.

Current midpoint frames:

| Beat | Frame |
| --- | ---: |
| cold_open | 159 |
| who_and_numbers | 582 |
| receipts | 1199 |
| featured_setup | 1593 |
| agent_works | 1771 |
| rejected | 2075 |
| appeal_passes | 2484 |
| checks_and_official | 2917 |
| reverify | 3299 |
| pilot_story | 3697 |
| results | 4164 |
| close | 4435 |

## Judgment calls

- Added the task's approved editorial labels to story.presentation. Authored display copy, numbers, commands, and test names are consumed from story.json and timeline.json; screenshot text remains the real captured site.
- Preserved the full first sentence of the cold-open claim, including its inline filename. Did not replace it with the older script's illustrative All tests pass quote.
- Added actual attempt-one receipt steps and witness operation ids from the featured run's main-checkout records to story.json. The extractor preserves the approved presentation copy and regenerates these trace fields.
- The 10x replay is four five-second excerpts from actual receipt timestamps, labelled selected recorded steps. Its final claim is held separately.
- The five gate checks use R1 to R5. R6 remains the separate claim audit in the content and is not shown as a sixth gate check. No test-file filtering animation is invented: this attempt's dropped_paths is empty.
- The rejection stamp follows the estimated Rejected narration cue. Under the current timing, it settles around 74.63 seconds and holds about 2.07 seconds before the next scene starts. Captions continue during this hold.
- The real plan card stays intact with a slow push-in; the task label and all three short spec names are shown separately in large type. Its body copy is still small. The reviewer inferred this readability concern from CSS; inspect the rendered shot before submission.

The final narrator recording, precise word synchronization, and scenes 7 to 12 remain for the later video task.
