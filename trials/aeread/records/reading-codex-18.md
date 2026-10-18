**8 correct, 2 partial, 8 wrong.** No files changed, tests run, or dependencies installed. Below, `start/` refers to the supplied start tree for that run; patch links reference the shipped diff.

1. **9c72e635e2b6: wrong.** The patch adds `_sealed_spend` but never calls it ([filtered.diff:9](trials/aeread/runs/9c72e635e2b6/attempts/1/filtered.diff:9)); the failure checkpoint at `start/src/aeread_families/econevals/campaign.py:425-437` still omits cost, so a case that paid for calls before failing remains uncounted. Upstream connects the helper to that checkpoint, while the target test only exercises the helper directly (`start/tests/test_econevals_live_campaign.py:321-343`).

2. **d4a6107bdab7: wrong.** The new route-proof set and predicate are never connected to the retry decision ([filtered.diff:46](trials/aeread/runs/d4a6107bdab7/attempts/1/filtered.diff:46)); `start/src/aeread/shared_runner/task/execution.py:2980-2994` still uses the original condition and retryable flag. Consequently, a non-retryable 404 after a successful call still kills the run even when the profile opts into the new condition, whereas upstream applies the reinterpretation at this retry seam.

3. **a791090df23e: correct.** The patch changes the default to 4096 and retries an empty response with twice the initial budget, preserving usage accounting for both calls ([filtered.diff:10](trials/aeread/runs/a791090df23e/attempts/1/filtered.diff:10), [filtered.diff:46](trials/aeread/runs/a791090df23e/attempts/1/filtered.diff:46)). Upstream additionally imposes an 8192-token retry minimum, but doubling satisfies the issue’s requirement for a larger budget.

4. **96dc5893c8a0: correct.** Sorting integer tenant IDs numerically puts tenant 2 before tenant 10, and the existing strict higher-bid comparison preserves tenant 2 on a tie ([filtered.diff:10](trials/aeread/runs/96dc5893c8a0/attempts/1/filtered.diff:10); `start/src/aeread/housing_env.py:252-254`). Unlike upstream, it sorts malformed keys before filtering them, so incomparable tuple keys could still raise; no ordinary caller producing those keys was found, so this is an edge-case note.

5. **43670c88be2c: wrong.** The patch removes the real provider probe and substitutes an unconditional `NotImplementedError` ([filtered.diff:17](trials/aeread/runs/43670c88be2c/attempts/1/filtered.diff:17)), which the retry loop calls at diff line 140, so even a healthy provider cannot admit a fresh campaign. Upstream preserves the real probe, while the passing tests replace `_probe_canary` entirely (`start/tests/test_econevals_live_campaign.py:155-186`).

6. **21d898f417d1: correct.** Using `.get("message", "")` records an empty utterance without skipping the transcript entry or inventing text ([filtered.diff:10](trials/aeread/runs/21d898f417d1/attempts/1/filtered.diff:10)). This matches upstream’s functional change and preserves the subsequent turn transition in `start/src/aeread_families/govsim/environment.py:600-617`.

7. **60a34999413f: wrong.** The new check refuses execution whenever a profile has an implementation and version, rather than comparing frozen implementation hashes ([filtered.diff:11](trials/aeread/runs/60a34999413f/attempts/2/filtered.diff:11)); ordinary generated profiles already contain both fields (`start/src/aeread_families/housing/runner.py:1209-1212`). Thus current, unchanged campaigns are also blocked, whereas upstream preserves the historical pins and rejects an actual runtime-hash mismatch.

8. **d44d046e2122: wrong.** Besides fixing the default, the patch rebases every explicitly supplied relative glob onto the repository root ([filtered.diff:18](trials/aeread/runs/d44d046e2122/attempts/1/filtered.diff:18)). A caller outside the checkout using `build_rows("my_cases/case*.json")` now loses its previously working local files; upstream retains a current-directory fallback, while the preservation test supplies only an absolute glob (`start/tests/test_rllm_integration.py:30-35`).

9. **d4ea59c9e7fd: partial.** The prompt now excludes late and wrong-variant listings before considering price and limits sampling to feasible offers ([filtered.diff:23](trials/aeread/runs/d4ea59c9e7fd/attempts/1/filtered.diff:23)). However, the sealed plan adds only “adaptive development treatment” at diff line 36, omitting the explicitly requested statement that a confirmatory claim requires a held-out panel, which upstream includes.

10. **6bb802cc35f0: wrong.** The patch rejects `cost <= 0.0`, so an otherwise valid zero-cost response becomes a permanently rejected checkpoint ([filtered.diff:57](trials/aeread/runs/6bb802cc35f0/attempts/1/filtered.diff:57)); the Arena adapter accepts zero and can omit cost, which the canary converts to zero (`start/src/aeread/shared_runner/task/execution.py:1836-1843`). It also returns truncated outcomes before hashing or writing their checkpoint and catches internal `ValueError`s with raw messages ([filtered.diff:35](trials/aeread/runs/6bb802cc35f0/attempts/1/filtered.diff:35), [filtered.diff:90](trials/aeread/runs/6bb802cc35f0/attempts/1/filtered.diff:90)), unlike upstream’s persisted, sanitized rejection path.

11. **424ed3def0c2: correct.** Embedded top-level and choice-level 429 errors now carry numeric metadata or conventional `Retry-After` header values into a retryable failure, and the actual retry caller passes it into the capped wait ([filtered.diff:21](trials/aeread/runs/424ed3def0c2/attempts/2/filtered.diff:21), [filtered.diff:92](trials/aeread/runs/424ed3def0c2/attempts/2/filtered.diff:92)). Both procurement setups and the campaign plan declare 60 seconds at diff lines 151-179, satisfying the described path. Compared with upstream, numeric-string metadata is unsupported and Retry-After replaces the exponential delay, but neither difference establishes failure of the stated ordinary-use contract.

12. **9b37cc341a5d: partial.** The patch handles the illustrated malformed values and documents allocation welfare, but tenant validation checks only integer type, omitting membership bounds ([filtered.diff:20](trials/aeread/runs/9b37cc341a5d/attempts/1/filtered.diff:20)). With two tenants, an above-ask bid from tenant key `2` can beat a valid bid and then raise `IndexError` in the welfare calculation at diff line 51, violating the explicit requirement to ignore non-tenants independently. Upstream checks `0 <= t < world.num_tenants`; the tests cover a string non-tenant but no out-of-range integer (`start/tests/test_housing_bids.py:60-94`).

13. **294b0d3378b1: correct.** The version branch now selects `httpx2` for SDK 3 and `httpx` for SDK 2, matching upstream on normal installations ([filtered.diff:12](trials/aeread/runs/294b0d3378b1/attempts/1/filtered.diff:12)). It retains a fallback to `httpx` if SDK 3’s transport dependency is missing, but that incomplete-installation case does not invalidate the reported fix.

14. **6361737020e5: correct.** Rejecting any submit that is not the final call necessarily rejects a two-submit burst, while retaining valid non-submit exploration and a single final submit ([filtered.diff:17](trials/aeread/runs/6361737020e5/attempts/1/filtered.diff:17)). Although upstream detects the duplicate explicitly, both implementations return validation feedback before tool execution (`start/src/aeread_families/econevals/live.py:377-409`).

15. **a791090df23e-rerun: wrong.** At the new default of 4096, `token_budgets` contains only `[4096]`, so an empty completion returns immediately without any larger-budget retry ([filtered.diff:47](trials/aeread/runs/a791090df23e-rerun/attempts/1/filtered.diff:47), diff lines 60-69). Upstream retries regardless of the initial budget; the target test explicitly starts at 1200 and therefore misses this default-path failure (`start/tests/test_everos_memory.py:280-285`).

16. **96dc5893c8a0-rerun: correct.** Numeric sorting fixes the reported 10-versus-2 tie, and the finite-amount conversion preserves normal accepted bids ([filtered.diff:10](trials/aeread/runs/96dc5893c8a0-rerun/attempts/1/filtered.diff:10), diff lines 20-29). As in the first run, sorting malformed keys before filtering differs from upstream and retains the incomparable-tuple edge case, without an identified ordinary caller.

17. **43670c88be2c-rerun: wrong.** The patch changes `run_canary` to require `run_root` ([filtered.diff:75](trials/aeread/runs/43670c88be2c-rerun/attempts/1/filtered.diff:75)), but `execute_campaign` still passes `path`, so normal execution raises an unexpected-keyword `TypeError` before probing (`start/src/aeread_families/econevals/campaign.py:291-294`). Upstream updates that caller alongside the signature; the target tests call `run_canary(run_root=...)` directly and miss the integration failure (`start/tests/test_econevals_live_campaign.py:168,186`).

18. **21d898f417d1-rerun: correct.** This patch repeats the valid `.get("message", "")` change, recording silence while preserving the transcript entry and turn advancement ([filtered.diff:10](trials/aeread/runs/21d898f417d1-rerun/attempts/1/filtered.diff:10)). It matches upstream’s behavior for the named `step()` path, covered by `start/tests/test_govsim_environment.py:504-537`.

| Run name | Classification |
|---|---|
| 9c72e635e2b6 | wrong |
| d4a6107bdab7 | wrong |
| a791090df23e | correct |
| 96dc5893c8a0 | correct |
| 43670c88be2c | wrong |
| 21d898f417d1 | correct |
| 60a34999413f | wrong |
| d44d046e2122 | wrong |
| d4ea59c9e7fd | partial |
| 6bb802cc35f0 | wrong |
| 424ed3def0c2 | correct |
| 9b37cc341a5d | partial |
| 294b0d3378b1 | correct |
| 6361737020e5 | correct |
| a791090df23e-rerun | wrong |
| 96dc5893c8a0-rerun | correct |
| 43670c88be2c-rerun | wrong |
| 21d898f417d1-rerun | correct |
