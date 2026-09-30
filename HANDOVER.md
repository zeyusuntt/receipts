# HANDOVER: Nebius × NVIDIA Global AI Hackathon entry

> 一句话：Nebius 和 NVIDIA 在 Devpost 办的线上赛，10 月 30 日上午 10 点（太平洋时间）截止，只看提交材料不看现场；做什么还没定，这个 repo 目前只有交接文档。
> 需要本人决定：build 什么（候选见下）；GitHub 仓库名。
> 5 分钟版本：本文「The event」和「Candidate builds」。
> 完整版：HQ repo `activities/nebius-nvidia-global-ai-2026/README.md`。
> 过期：2026-10-30 10:00am PT。

Written 2026-09-29 for a session that starts cold. Event facts were read from the Devpost overview, rules, updates and resources pages on Sep 23 and Sep 29, 2026. Do not write product code here until Zeyu has chosen what to build.

## The event

- Page: https://nebiusglobalaihackathon.devpost.com/ · Rules: /rules · Updates: /updates · Resources: /resources · Discord: https://discord.gg/eXYTGhgnhK
- Online, worldwide. 14,415 registered on Sep 29. Submit by **Oct 30, 2026, 10:00am PDT**. Judging Dec 1 to 15 from submitted materials only ("Judges are not required to test the Project and may choose to judge based solely on the text description, images, and video"). Winners about Jan 11, 2027.
- Hard requirements: a runtime call to the Token Factory inference API (or Nebius AI Cloud compute), and at least one NVIDIA open source model (Nemotron, GR00T, Cosmos, or Sonic). Existing projects allowed if significantly updated after Aug 26.
- Tracks (verbatim): Coding and Agentic Engineering "Build coding agents and developer tools: agents that write, run, and test code in Token Factory." · Best Apps and Agents "Build any app or agent someone would actually use, from a productivity tool or copilot to a workflow that runs itself." · Personal AI "Build an always-on, private assistant that works for you while keeping your data under your control." · Physical AI (robotics, IoT, edge).
- Organizer's judging note: judges "love to see tracks pushed further than the basics"; a standout Coding entry is "an agent that plans, writes, tests, and iterates on a real repo with minimal human input".
- Submission: public repo with an OSS license, README, working demo URL, video under 3 minutes with audio, text description, feedback on the tools.
- Judging, four equal criteria: Technological Implementation (how effectively it uses Token Factory and Nemotron), Design (complete, coherent product experience), Potential Impact (credible case for a real audience), Quality of Idea (creative, non-obvious use).
- Prizes: $20k / $10k / $6k; one Jetson Orin Nano per track; Best Use of Tavily $3k; 20 City Winner awards $500 (SF meetup Fri Oct 9, 4 to 10pm, Motoring Coffee, 1525 Union St); 10 Most Valuable Feedback awards $100.
- Credits: claimed Sep 29 (promo code $25 plus Builder Program $25). Model id `nvidia/nemotron-3-super-120b-a12b`, base URL `https://api.tokenfactory.nebius.com/v1/`, OpenAI-compatible; tool calling and json_schema output supported. Sandboxes via `contree-sdk` (https://docs.tokenfactory.nebius.com/sandboxes/overview.md).

## Candidate builds (none chosen yet)

1. A repo-iterating coding agent, built from the judges' sentence: given a repo and an issue, plan, edit, run tests in a Token Factory Sandbox, iterate on failure, all on Nemotron. Closest to the track text; from zero.
2. A diagnostic agent for other coding agents' failures (the agent-postmortem idea moved onto Nemotron and Sandboxes). Differentiated; fits Best Apps and Agents better than the Coding track.
3. Foreman adapted (job description in, agent plus benchmark out, deploy gated). Most reuse, partial fit to the track sentence. Zeyu has not chosen this.
4. Something else Zeyu prefers.

## Needs Zeyu

- [x] Registered on Devpost; credits claimed
- [ ] Token Factory API key into this repo's `.env` when building starts
- [ ] Choose the build
- [ ] GitHub name, then `gh repo create zeyusuntt/nebius-hackathon --private --source=. --remote=origin` (public before submission)

## Rules for any agent working here

No product code until the build is chosen. No commits or pushes unless asked. No AI attribution in commits. Event facts from the pages above, not memory. Plain writing, no em-dashes. When a session ends, append one line to the "Agent 交接" section of `~/Documents/Obsidian Vault/Projects/beta fund.md`.
