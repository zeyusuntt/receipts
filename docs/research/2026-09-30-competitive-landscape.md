# Competitive landscape for the verified coding agent (2026-09-30)

Research by a subagent on Sep 30, 2026; links checked by it, not re-fetched here. Items marked unverified were not confirmed at the source.

Headline: "the agent's word is not evidence" is no longer a rare stance. At least eight small OSS receipt or proof-of-work gates shipped in 2026, and at least five entries in this same hackathon already fork Nebius Sandboxes to race patches. Nobody found combines, in one runtime: an independent canonical re-run, a deterministic gate with pass-to-pass plus no-shrink, a patch-scope policy, an image-id provenance chain, a per-claim audit, and forked candidates. That combination is the defensible story; each part alone is not.

## A. Table

| Name | Type | Verification | Trusts claim or re-verifies | Audits claims vs evidence | Forks / races | Link |
|---|---|---|---|---|---|---|
| SWE-bench harness | OSS | Fresh container, gold test patch, FAIL_TO_PASS and PASS_TO_PASS; SKIPPED counts as maintained in P2P | Re-verifies, offline | No | No | https://www.swebench.com/SWE-bench/api/harness/ |
| SWE-rebench (Nebius) | OSS dataset + harness | Task valid only if at least one test fails before, all fail-to-pass after, all pass stay pass; 21k tasks | Re-verifies | No | No | https://nebius.com/blog/posts/infrastructure-behind-swe-rebench |
| Terminal-Bench / Harbor | OSS | Verifier runs in a fresh container built from tests/; agent cannot touch the grader; nine-vector cheating taxonomy | Re-verifies | No | No | https://github.com/harbor-framework/terminal-bench/issues/2086 |
| OpenAI Codex cloud | Product | Runs tests in sandbox; PR cites terminal logs and test output | Self-report with logs | No | No | https://prlens.dev/guides/how-to-review-codex-pull-requests (openai.com fetch blocked) |
| GitHub Copilot cloud agent | Product | Tests in Actions; signed commits; each commit links to a session log | Self-report | No | No | https://docs.github.com/en/copilot/responsible-use/agents |
| Devin | Product | Runs the app, attaches screenshots and video | Same agent tests its own work | No | No | https://cognition.com/blog/testing-development |
| Greptile TREX | Product (beta) | Reviewer writes and runs its own tests on the PR branch | Independent of author agent | Indirectly | No | https://www.greptile.com/changelog |
| Critique | Product (early access) | `critique finish` rebuilds the change in a disposable workspace, re-runs tests, JSON outcome | Re-verifies | Yes (intent vs result) | No | https://www.critique.sh/ |
| AgentProof | OSS v0.2.0rc2 | Clean BASE and HEAD worktrees, canonical test command, proof tests, integrity rules AP001.. (deleted tests, new skips, narrowed discovery), receipt with SHA-256 | Re-verifies | Claims via `--claim`; classification unverified | No | https://github.com/GenRamzi/AgentProof |
| proof-of-work | OSS v0.2.0 | Re-runs tests; diff scan for deleted tests, weakened asserts, skip decorators, `sys.exit(0)`; Ed25519 hash-chained log, in-toto/DSSE | Re-verifies | Partial | No | https://github.com/Rajveerx11/proof-of-work |
| claimcheck | OSS | Reads diff, agent report and pytest log; per-claim verdicts verified / unsupported / refuted / uncheckable | Logs only, no re-run | Yes | No | https://github.com/bugyal/claimcheck |
| agent-trajectory-audit | OSS, archived | Transcript detectors: verification_claim_gap, completion_without_verification | No re-run | Yes | No | https://github.com/barlowa124/agent-trajectory-audit |
| agentwatch | OSS | Reconciles transcript against OS execve audit records | OS ground truth, no re-run | Yes | No | https://github.com/adelic-ai/agentwatch |
| Agent Review Control | OSS | Contract + Evidence + Verdict; excluded paths, exit codes, output digests | Checks evidence exists, no re-run | Yes | No | https://github.com/SimranPabla/agent-review-control |
| FixFork (this hackathon) | OSS | Forks 3 hypotheses in Nebius Sandboxes; branch touching test/CI/config is blocked; race report; Nemotron | Re-runs per branch | No | Yes, 3-way | https://github.com/tuyentran4992/fixfork |
| forkfix (this hackathon) | OSS | Forks at every action, judge-model pruning, P2P on changed files; 15/79 SWE-bench Lite vs 4/79 single | Re-runs | No | Yes, tree | https://github.com/jessecalvin08/forkfix |
| Arborist (this hackathon) | OSS | BFS k=4 x 3 levels over sandbox states; `--protect` refuses patches editing tests; junit identity diff vs parent | Re-runs | No | Yes | https://github.com/ZNLong2203/Nebius-Nvidia |
| SandForge (this hackathon) | OSS | plan, patch, test, backtrack to checkpoint, 4 attempts | Re-runs | No | Sequential | https://github.com/AntrikshH90/sandforge |
| ZNAK FORGE (this hackathon) | OSS | "The model can propose. It cannot declare its own success"; targeted, shadow, regression tests; receipt with source SHA | Re-runs locally | Partial | No Sandboxes | https://github.com/HumbleDrummer/znak-forge-nebius-nvidia-2026 |
| Claude Code Stop hook | Product feature | Hook exits 2 to block "done" until a script passes | In-process gate | No | No | https://code.claude.com/docs/en/hooks |

Also: Cursor 2.0 runs up to 8 agents in worktrees with a judge (https://engincanveske.substack.com/p/running-parallel-agents-in-cursor); SWE-Search MCTS (https://arxiv.org/abs/2410.20285); Contree MCP exposes `contree_run` returning a new immutable image per command and `contree_image_lineage` giving the parent chain to root (https://github.com/nebius/contree-mcp).

## B. Five things to borrow

1. SWE-bench's resolution rule and its habit of restoring test files to the base commit before running the canonical suite. Our R3 (skips must not grow) is stricter than SWE-bench, which counts SKIPPED as maintained; say so.
2. AgentProof's stable integrity rule ids and receipt digest.
3. claimcheck's four-way claim verdict (verified / unsupported / refuted / uncheckable).
4. Terminal-Bench's nine cheating vectors: V4 fail-open (empty suite, skipped tests, exit 0) is our R3; V5 sleeper process means kill leftover processes before canonical verification; V6 staging means R4 must reject symlinks and a new `conftest.py` anywhere, not only at the root.
5. Contree image lineage as the provenance primitive for R5.

## C. Gaps nothing in the table fills

- Nobody re-runs the baseline twice to derive a flaky-exclusion set and re-runs a single P2P failure once before rejecting.
- Nobody both audits per-claim and independently re-runs. claimcheck and agent-trajectory-audit audit without executing; AgentProof, proof-of-work, Critique, FixFork, Arborist execute without parsing what the agent said.
- No forking entrant applies a full deterministic gate per branch (F2P, P2P over the whole baseline set, no-shrink on collected count and skips, config scope, provenance). None checks collection shrink or pytest config edits; none records the sandbox image behind each receipt.
- Nobody distinguishes `unsupported` (never ran tests on the final image) from `contradicted` (own last run disagreed).
- Nobody gives an image-lineage chain from baseline checkpoint to verification receipt.

## D. Risks to the "we are different" story

1. Same-hackathon lookalikes fork Sandboxes with Nemotron. They optimise for finding a fix; we optimise for whether any fix should be believed. The demo must show a branch that passes its own tests and is still REJECTED or `contradicted`.
2. Receipts are commodity. Claim that ours are executor-owned per command, bound to a sandbox image id, and that the verdict comes from a re-run the agent never saw.
3. Big products attach evidence already (Codex logs, Copilot session links, Devin videos). Those are the agent's own logs; a reviewer still cannot tell whether the suite shrank or a test was skipped. Cite AgentLens 10.7 percent "lucky pass" (https://arxiv.org/abs/2605.12925) rather than asserting products are careless.

## E. Datasets of faked-success trajectories

- TRACE (PatronusAI): 517 trajectories, 268 hacked, 54 subcategories incl. Test Modification and Coverage Gaming; Claude Code tool-call format; CC-BY-SA-4.0. https://huggingface.co/datasets/PatronusAI/trace-dataset , paper https://arxiv.org/abs/2601.20103
- Terminal Wrench: 331 hackable tasks, 3,632 exploit trajectories with verifier output; Apache-2.0; includes pytest subversion via conftest.py hooks. https://github.com/few-sh/terminal-wrench
- METR MALT: 7,179 transcripts with reward hacking labels. https://metr.org/blog/2025-10-14-malt-dataset-of-natural-and-prompted-behaviors/
- EvilGenie: https://github.com/JonathanGabor/EvilGenie
- agent-trajectory-audit fixtures plus one sanitized Devin session: https://github.com/barlowa124/agent-trajectory-audit
- HVTB: https://arxiv.org/abs/2608.22103

Papers for one line in the README: SpecBench (https://arxiv.org/abs/2605.21384), "Looping Is Not Reliability" (https://arxiv.org/abs/2607.24604), Cursor on reward hacking in benchmarks (https://cursor.com/blog/reward-hacking-coding-benchmarks), in-toto issue 604 on AI code provenance (https://github.com/in-toto/attestation/issues/604).

Unverified: exact Codex wording, OpenHands eval README, AgentProof claim classification internals, Claude 4 system card reward-hacking rates.

## F. What Nebius has rewarded, and the Coding track as of Sep 30 (second pass)

Research by a subagent on Sep 30, 2026, links checked by it.

What Nebius has rewarded:
- Nebius.Build SF (Mar 15, 2026): 1st Injester, which strips token noise with Tavily, restructures pages via Nebius, and runs a self-iterating loop that took task accuracy from 2/5 to 5/5 (https://cerebralvalley.ai/e/nebius-build-sf/hackathon/gallery/33.md). 2nd a robot-policy preference dataset with ELO ratings and anti-cheating measures. No judge comments published.
- Nebius Serverless AI Builders Challenge (Aug 18, 2026): rubric of technical implementation, reproducibility, educational quality, product usage depth, usefulness, originality; every top-3 winner was cited for a measured, non-obvious finding (LLM judges agreeing at kappa 0.11; self-hosting wins on cost only at high utilisation; fault type matters more than fault count) (https://nebius.com/blog/posts/serverless-ai-builders-challenge-winners).
- Emergence x Nebius Enterprise Agents, NYC (Jul 2026): 1st Delivery Tracker, where the agent "refuses its own optimum", "numbers never pass through the LLM", fixtures are committed and it runs with zero credentials (https://devpost.com/software/delivery-tracker). TrustSQL, which verifies SQL against the business question, also won.
- Pattern: a measured surprising number, an anti-gaming or self-refusal mechanism, reproducibility.

Event updates since Sep 23: one official post on Sep 25: feedback is mandatory and must name the tool; name the project "like a human"; say "Token Factory" and the NVIDIA model aloud in the video; make the video "like a pitch, not a tutorial" (https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project). Open forum questions: Sandboxes beta stability through the December judging window; keeping apps live after the trial ends.

What the judges care about, from their public writing: Dylan Bristot (Token Factory PMM) on agentic RL being bottlenecked on sandbox work and on turning logs into training data (https://nebius.com/blog/posts/in-agentic-rl-faster-tokens-are-not-enough, https://nebius.com/blog/posts/your-best-dataset-is-already-in-your-logs); Aleksandr Patrushev on measuring the cost of a completed run (https://theregister.com/2026/04/23/stop_measuring_ai_training); Mikhail Rozhkov on ML reproducibility; Jacquie Capur, previously at Flox (reproducible environments), hosts the no-slides Build with Nebius livestream; AbdulMajed Raja wrote the OpenCode, OpenHands and "confidence-gated human validation" cookbooks. No public views found for the NVIDIA judges.

Nebius's own narrative: SWE-rebench V2 rewards 1.0 only when all FAIL_TO_PASS pass and all PASS_TO_PASS still pass, with a tamper-proof test patch (https://openreward.ai/nebius/SWE-rebench-V2); its maintainers document agents copying upstream fixes and warn that better models may cheat more. The Sandboxes docs pitch 7,000+ preloaded SWE environments, branching to try multiple patches, and auditable runs.

More Coding-track competitors, beyond section A:

| Repo | Completeness | Strongest thing we lack |
|---|---|---|
| FixFork https://github.com/tuyentran4992/fixfork | 32 commits, 201 tests, Sandboxes verified live | An upstream PR merged by the tomlkit maintainer (#620), patch hand-completed |
| forkfix https://github.com/jessecalvin08/forkfix | 28 commits, run viewer | 15/79 vs 4/79 on SWE-bench Lite with an equal-compute baseline, p = 0.003 |
| Arborist https://github.com/ZNLong2203/Nebius-Nvidia | 79 commits, CI, 182 tests, live replay site | A GitHub Action from red CI to PR listing rejected alternatives; Ultra flags test-gaming patches; 14/23 SWE-bench Lite at a third of linear cost |
| SandForge https://github.com/AntrikshH90/sandforge | 4 commits | Polished dashboard, real PR creation |
| ZNAK FORGE https://github.com/HumbleDrummer/znak-forge-nebius-nvidia-2026 | 14 commits, no Sandboxes, Best Apps track | Hidden shadow tests |
| MUTINY https://github.com/TusharTechs/mutiny | 94 commits, video, live demo | Measured 49 already-merged upstream PRs (it did not author them), zero false alarms, a "For judges" table mapping each criterion to evidence |
| Polyjury https://github.com/cine1052rene/polyjury | | Audits model claims: "a label is not evidence" |
| BranchForge, RepoMedic, PQC Factory | | Similar sandbox-branching agents |

Blunt assessment from that pass: sameness is the main way to lose (the gate is table stakes); no real-world proof is the second; fragile access the third. To win: publish one surprising measured number (the false-done rate on SWE-rebench), ship real artifacts (a no-key receipt viewer and a real upstream PR), and frame receipts as reward signals for RL and Data Lab.
