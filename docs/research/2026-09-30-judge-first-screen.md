# Judge first-screen study (2026-09-30)

A subagent read five competitor READMEs through the GitHub API and their demo sites from HTML and bundles (not rendered in a browser), and MUTINY's video through captions and storyboard frames.

| Repo | First sentence | First number | Visual | Demo link | For judges | Remembered after 30 s |
|---|---|---|---|---|---|---|
| MUTINY | "Did that refactor actually preserve behaviour?" | "106 tests passing" badge, then 49 merged PRs (measured, not authored) | Logo | Video and live demo first two links | Criterion-to-evidence table incl. "what it gets wrong" | A refactor checker written for the judge that admits its errors |
| Arborist | "A coding agent that repairs a failing repository by searching a tree of sandbox states..." | Only inside the screenshot | Large screenshot | Yes | No | The tree picture |
| Polyjury | "One AI wrote your code. Don't let one AI judge it." | 17 findings, 2 by more than one model | None | Only in About | No | The tagline |
| forkfix | "A coding agent that searches over checkpointed sandbox states instead of making one attempt." | 15/79 vs 4/79, p = 0.003, at the fold | None | No | No | "15 vs 4" if the judge scrolls |
| FixFork | "Give a repo and a failing test. FixFork forks three hypotheses... hands back the branch that passes, with evidence." | "~$0.003 per run" inside "Status: early development" | None | None | No | "Early development" |

Ranking: MUTINY, Arborist, Polyjury, forkfix, FixFork. MUTINY is the only first screen written for the judge.

Implications adopted in design v3: lead with the stance because FixFork's tagline is nearly our contract; "no model in the verdict" and "re-verified from a clean checkout" are not ours alone (MUTINY, Arborist), so the false-done number and the judge's Re-verify button lead; official-grader agreement is P0 so "zero shipped" is not true by construction; demo link on line 4 straight to a finished receipt; a 60-second judges box; repository named `receipts` with About and Website set.

Common mistakes seen: no product visual (4 of 5); no demo link (3 of 5); headline result missing or buried; hedging and internals before the pitch; repository identity not matching the pitch. MUTINY's video names no sponsor in its first 30 seconds.
