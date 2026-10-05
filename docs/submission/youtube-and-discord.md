# YouTube upload and Discord posts (internal; removed with docs/submission/ before publishing)

Post only after the repository and the receipt site are public, and replace `<VIDEO_URL>` with the YouTube link.

## YouTube

- File: `video/out/receipts-v4.mp4` (2:57, 2560x1440). Thumbnail: `video/out/gallery/0-cover-16x9.png`. Captions: upload `video/out/receipts.srt` as English (regenerate with `python3 video/scripts/make_srt.py` after any re-render).
- Visibility: **Public** (the rules require a publicly visible YouTube video). Audience: not made for kids. Category: Science & Technology.
- Title: `Receipts: the coding agent that isn't allowed to grade its own homework`
- Tags: Nebius, Token Factory, NVIDIA Nemotron, coding agents, AI agents, SWE-bench, evaluation, verification, hackathon

Description:

```
Coding agents say "done". On 100 real SWE-rebench bugs, picked by a rule committed before the first run, an unguarded NVIDIA Nemotron 3 Super agent said "done" 67 times, and 12 of those were false by SWE-rebench's own grader.

Receipts keeps Nemotron as the author and takes away its vote. Nemotron writes the fix on Nebius Token Factory; a fresh Token Factory Sandbox, forked from the checkpoint before the agent started, re-runs your tests with only the source change applied; plain code decides. One appeal with the gate's evidence. On the 100 bugs: 66 verified fixes, 0 false ones shipped, about $0.41 of Nemotron tokens each. Every fix comes with a receipt anyone can re-run.

Built for the Nebius x NVIDIA Global AI Hackathon (Coding and Agentic Engineering).

Code: https://github.com/zeyusuntt/receipts
Receipts from the real runs: https://zeyusuntt.github.io/receipts/
The pre-registered experiment: https://github.com/zeyusuntt/receipts/blob/main/REPORT-v2.md

0:00 The agent said it was done. How often is that true?
0:30 Receipts: Nemotron writes the fix, plain code decides
0:49 One real bug, end to end: rejected
1:16 The appeal, and VERIFIED
1:28 Every check is plain code; re-run any receipt yourself
1:59 I got this wrong first
2:19 Results, built on Nebius Token Factory
2:43 Another repo, one command

Music: "Wallpaper" by Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0, https://creativecommons.org/licenses/by/4.0/
```

## Discord: the project post (showcase or project-sharing channel)

```
**Receipts: the coding agent that isn't allowed to grade its own homework** (Coding and Agentic Engineering)

Coding agents say "done". I measured how often that's true: on 100 real SWE-rebench bugs, picked by a rule I committed before the first run, an unguarded Nemotron 3 Super agent said "done" 67 times, and 12 were false by SWE-rebench's own grader.

Receipts keeps Nemotron as the author and takes away its vote. It forks the original checkpoint into a fresh Token Factory Sandbox the agent never touched, applies only the source change, and plain code decides: the spec passes, nothing that passed breaks, no test removed or skipped, your tests untouched, every step hash-chained. One appeal with the gate's evidence. Result: 66 verified fixes, 0 false ones shipped, about $0.41 of Nemotron tokens each. Any receipt re-runs on Token Factory in about two minutes, or with Docker and no account.

I also published my own pilot's false fix and how I fixed the gate.

Video (2:57): <VIDEO_URL>
Repo: https://github.com/zeyusuntt/receipts
Receipts from the real runs: https://zeyusuntt.github.io/receipts/

Feedback welcome, especially: would you trust a VERIFIED like this before merging?
```

## Discord: Token Factory findings (a feedback, support or Sandboxes channel)

Constructive and short; the full list is in FEEDBACK.md. Post it as information, not as a request for anything.

```
Sharing a few things we hit running Token Factory Sandboxes at scale (482 sandbox branches, 4,253 recorded steps), in case they help others or the team:

1. A run's `duration` is CPU time, not wall time. For one operation the API says 6.78 s (the console's "Consumed CPU time"), the console's "Execution time" is 10 s, and the sandbox lived 14.9 s. If you report run times, measure wall time yourself.
2. The API's `resources` is `{cpu: 0, disk: 0, memory: 0}` for every run, while the console shows real CPU and peak memory.
3. Downloading a directory returns 422 ("Path is not a regular file"); list the directory and fetch files one by one. Listing paths are relative to the listed directory.
4. Agent loops are almost all input tokens: Nemotron 3 Super used 146M input vs 1.65M output tokens for us. A cached-input price would make a big difference for agents.

Details and evidence: https://github.com/zeyusuntt/receipts/blob/main/FEEDBACK.md
```
