# How winning hackathon videos are made: a frame-level study (2026-10-03)

Purpose: decide how the Receipts video is built, from what winners actually put on screen, not from transcripts alone. Method: downloaded 12 winning videos at 720p, cut each into a 24-frame overview sheet and a one-frame-per-second sheet of its first 24 seconds (ffmpeg), counted cuts with scene detection (threshold 0.12), measured narration pace from the published subtitles, and read every sheet. Sources were each video's Devpost page and the official winner announcements. Two could not be studied: ORION (Gemini Live Agent Challenge grand prize) is age-gated on YouTube, and the Jayu link on its Devpost page is a later repository walkthrough, not the competition video.

## The videos

| Video | Prize | Length | Words per minute | Cuts per minute | What it does on screen |
| --- | --- | ---: | ---: | ---: | --- |
| [Nomi](https://devpost.com/software/nomi-aoim58) | AWS x NVIDIA agentic hackathon, winner | 2:30 | 155 | 34 | Two founders on camera; a full-screen "1.6 BILLION" and a population pyramid from 12% to 22% in the first 20 s; real hardware; the NVIDIA NIM catalogue page and the AWS DynamoDB console on screen; code calling NVIDIA. |
| [EcoLafaek](https://youtu.be/ZWKOsdWfSsA) | AWS global, 1st of 9,470 | 3:51 | 127 | 9 | A deck with one brand colour: "The Problem", "Hackathon Requirements Met" (AWS services as icons), "Architecture Overview", "DEMO 1/2/3", "Real-World Impact", "Call to Action" with QR codes. Demos are three labelled panes side by side: the user in the field, the phone app, the backend logs. Red hand-drawn arrows and circles. |
| [Province](https://youtu.be/_ipE3EZEw40) | AWS, 3rd | 2:50 | 146 | 10 | Cold open: "April = Most Dreaded Month?" white on black. Then "Your Choices": tax software ("100+ confusing questions") vs a CPA ("$300 to $500"). During the demo it cuts back to one architecture diagram with a red box on the component that is running now. |
| [JohnKeats.AI](https://devpost.com/software/johnkeats-ai) | Gemini Live, Best Technical Execution | 4:00 | 107 | 3 | Cinematic, dark, serif type. The architecture is animated: tokens flow down a pipeline, pass gates, and sensitive data is stopped in red ("ACTION BLOCKED"). Ends on "We didn't build a better chatbot. We built a presence." |
| [Wand](https://devpost.com/software/wand-a-live-agent-that-sees-browses-and-clicks-with-you) | Gemini Live, Best Multimodal UX | 4:00 | | 5 | The founder on camera for one line, then one long real session with a picture-in-picture webcam: the agent works across YouTube, Amazon and Maps while she talks to it. |
| [Rayan Memory](https://devpost.com/software/rayan-memory) | Gemini Live, Best Innovation | 3:57 | | 12 | Real product footage throughout (a 3D memory palace) in a warm frame, founder webcam in the corner. |
| [SecondVoice](https://youtu.be/6HqoqgsnvRU) | OpenAI Build Week | 2:44 | 106 | 1 | The most polished. Cold open on black: the waveform of a real dysarthric speaker, captioned "[a woman with dysarthria is speaking]", then "Did you understand her?", then "Neither did the machine.", then the title. Warm dark palette, serif headings, captions burned in for the whole video. Ends on "GPT-5.6 reconstructs. The human decides." |
| [AegisAgent](https://youtu.be/FNWsFtOX4d4) | AWS winner | 2:24 | | 2 | A plain screen recording of the real web app, scrolled step by step through the workflow. |
| drone-copilot, Moonwalk, Upload Drive-In | Gemini Live and Kiro category winners | 1:56 to 4:55 | | 7 to 20 | Real product footage with narration; checked for range, not studied shot by shot. |

## What they have in common

1. **The first ten seconds make you feel the problem.** SecondVoice plays the real voice; Province asks a question; Nomi and EcoLafaek put one big number on screen. None opens with a logo or with the team.
2. **The name and one-liner arrive by about 20 seconds.**
3. **The status quo has a price.** Province's "$300 to $500" for a CPA. A concrete cost makes the gap obvious without adjectives.
4. **The sponsor's technology is on screen, not just in the narration.** Nomi shows the NVIDIA NIM catalogue and the AWS console; EcoLafaek has a whole "Hackathon Requirements Met" card. The organizers of our event ask for the same thing in the narration.
5. **One architecture diagram is the map, and the video keeps returning to it.** Province highlights the active component each time; EcoLafaek gives it a full card. It is also what technical judges look for first.
6. **The core mechanism is animated as data moving through gates.** JohnKeats won Best Technical Execution with exactly this: tokens flowing, rules stopping them in red.
7. **The proof is real footage, often in long takes.** Wand, Rayan and AegisAgent barely cut. The rules require footage of the project working, and long uninterrupted runs read as honest.
8. **Front end and back end are shown together, labelled.** EcoLafaek's three panes (person, app, logs) answer "is this real?" in one frame.
9. **Annotations point at what matters.** Red circles, arrows and boxes on real screenshots (EcoLafaek, Province).
10. **Captions are burned in, and the look is consistent.** SecondVoice keeps one palette and one type system from the first frame to the last.
11. **Pace and length.** Narration at 106 to 155 words per minute; 2:24 to 4:00 long (our limit is under 3:00). Cut rate varies from 1 to 34 per minute, so it is not what wins; what matters is one idea per shot and enough time on each key frame.
12. **The close is a two-part line.** "GPT-5.6 reconstructs. The human decides." "We didn't build a better chatbot. We built a presence." Then links or QR codes.
13. **Production value is not the deciding factor.** Nomi was filmed on a phone; JohnKeats is cinematic; both won. Story, visible sponsor technology and real footage are common to all of them; polish of type and colour is cheap and helps.

Two earlier sources agree. The owner's AI video report (`~/Documents/AI art/ai-video-workflow-report-2026-09-21.md`, section 5.3) finds judges rank narrative and directorial intent above polish, treat sound design as a hard requirement, and that looking not AI-generated is itself an advantage. The hackathon playbook (`~/Documents/beta fund/playbook/winning-playbook.md`) says to design a trust wow rather than a capability wow, get to the demo by 90 seconds, pause two seconds after the wow, prefer precision to charisma, and that in online marathons the write-up, the architecture diagram and the video carry the win.

## What changes in the Receipts video

| From | Change |
| --- | --- |
| 1, SecondVoice | Cold open on black: the agent's real finish message types out in monospace ("All tests pass. The fix is complete."), then "Was it?", then the witness's real result, the spec test FAILED in red, then "It wasn't." The number follows. |
| 5, Province | One architecture map built for the video and reused in the README and Devpost: your failing test, Nemotron 3 Super on Token Factory (agent branch), a Token Factory Sandbox forked from the checkpoint (witness), the gate (plain code), the receipt, and SWE-rebench's grader off to the side. It returns at each beat with the active node lit. |
| 6, JohnKeats | The 0:55 beat animates the mechanism: the patch flows from the agent branch to the witness, test files fall away at the filter, the five checks light up one by one, the failing one turns red, REJECTED lands. |
| 4, Nomi and EcoLafaek | A real Token Factory moment on screen: the model id and the sandbox operation and image ids from a receipt, and a screenshot of the Token Factory console's Sandboxes page if the owner can capture one. |
| 8 and 9, EcoLafaek | The 1:32 proof beat shows two labelled panes, the receipt page and the official grader's log, with circles on the lines that matter. |
| 10, SecondVoice | Captions burned in throughout; one palette and type system, taken from the receipt site (paper, ink, accent blue, verified green, rejected orange; IBM Plex Sans and Mono). |
| 12 | Close on two lines, "Nemotron writes the fix. Plain code decides." and "Agents can write the code. Receipts makes them prove it.", then the URL and a QR code to the receipts site. |
