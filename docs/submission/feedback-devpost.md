# Feedback for the Devpost feedback section

Paste the text between the rules into the submission form's feedback section. It is the short, prioritized version of `FEEDBACK.md` (which has the evidence for every item and the SWE-rebench findings); keep the link at the end so a reader can check any line.

---

We ran Token Factory hard: 100 pre-registered SWE-rebench tasks and screening, 482 sandbox branches, 4,253 recorded sandbox steps, 146 million Nemotron 3 Super input tokens, plus live re-verification and a demo run. Everything below comes from those records; each item has its evidence in FEEDBACK.md in our repository.

**What worked very well**
- Sandboxes' checkpoint and branch is exactly the primitive an independent verifier needs: we fork the original checkpoint into a witness the agent never touched, and immutable images make that fork exact.
- The catalogue preloads 32,064 SWE-rebench-V2 images (598 of our 600 candidates), a trivial run takes about 1.1 s, and concurrency 4 to 6 never hit a rate limit.
- Nemotron 3 Super is a disciplined tool caller: 0 of 1,875 responses made more than one call when asked for one, and it completed 10 of 10 scripted six-turn tool loops.

**What would help most, in order of impact**
1. **Price for agent loops.** Nemotron 3 Super used 146.41M input tokens against 1.65M output (89 to 1); input was 96.7% of its cost. Every agent turn resends the conversation. A cached-input price or prompt caching would cut agent workloads several times over.
2. **The API's `duration` is CPU time, not wall time, and nothing says so.** One operation (`01a0ff63-2a85-72ca-b4a5-6acd9e56af33`) has three times: API `duration` 6.78 s (equal to the console's "Consumed CPU time"), console "Execution time" 10 s, and 14.9 s from creation to deletion. We first recorded `duration` as how long a command ran. Please document it or rename it, and return the wall-clock time.
3. **The API returns `resources: {cpu: 0, disk: 0, memory: 0}` for every run,** while the console shows real CPU and peak memory (98.63 MB for the run above). Clients cannot budget or report what they cannot read.
4. **Directory download and listing are undocumented and surprising:** downloading a directory returns 422 ("Path is not a regular file"), and the listing names entries relative to the listed directory. Our directory reads failed live until we found both.
5. **`contree-sdk` 0.3.6 returns 403 on some catalogue calls that succeed over REST,** and `GET /v1/inspect/?tag=` answers 302 with a relative `Location`. We moved to REST.
6. **Checkpoint rebuilds dominate re-verification:** 53.1 s of a 114 s re-verification. A checkpoint that could be cached or shared by digest would halve it.
7. **Output limits are undocumented:** the default truncates a run's output at 64 KB and `truncate_output_at` refuses 10 MiB or more, while a full pytest `-rA` log can exceed that. A way to fetch the full stdout would help.
8. **Console:** "Success" sits next to "Exit code 1" (the command failed, the sandbox ran); label it "Completed" and show the exit code. And publish the unit of a run's `cost` (0.0101 per second of `duration`) and the beta's pricing.

**For NVIDIA's Nemotron team:** when our harness offered its own tool names, Nemotron 3 Super still called tools from other harnesses that did not exist (`execute` 46 times, `bash`, `str_replace_editor` and others): 60 such calls across v1's 79 analysed attempts. Publishing the tool names and schemas it was tuned on would let harnesses match them. In our scripted tool loop, the newer Nemotron 3.5 Lightning completed 6 of 10 and Nemotron 3 Ultra 3 of 10, against Super's 10 of 10.

Full findings with evidence, including four for SWE-rebench-V2: https://github.com/zeyusuntt/receipts/blob/main/FEEDBACK.md

---
