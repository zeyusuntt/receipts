# Terry's trial (internal; removed with docs/submission/ before publishing)

What we want from it: one honest outside use of Receipts, and, with permission, one sentence and a receipt link for Devpost. If it fails or Terry is lukewarm, that is useful too, and nothing is written up that did not happen.

Before sending: the repository must be reachable (public, or Terry invited to the private repository), and the Docker path of `receipts fix` must have had its first live run (HANDOVER, pre-publish checks).

## The message to send

> Hi Terry, could you try something I built for the Nebius x NVIDIA hackathon? It's called Receipts: a coding agent (NVIDIA Nemotron) writes a fix for a failing test, then a clean sandbox the agent never touched re-runs your tests, and plain code (no model) decides whether the fix is real. Every fix comes with a receipt anyone can re-check.
>
> Two levels, whichever you have time for:
>
> **1. Re-check one of my receipts (about 10 minutes, no account).** You need Docker and uv.
> ```
> git clone https://github.com/zeyusuntt/receipts && cd receipts
> uv sync
> uv run receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json
> ```
> It should end with "Every check agrees with the receipt." If it doesn't, the message tells you which check disagreed, and that's exactly what I'd like to know.
>
> **2. Use it on a real bug in a Python repo you work on (30 to 60 minutes).** Pick a bug that has, or could have, a failing pytest test. Commit the failing test on a branch, write the issue in a few sentences into `issue.md`, and run:
> ```
> uv run receipts fix --repo <your repo's git URL> --commit <the commit with the failing test> \
>   --install "<how you install it, for example pip install -e .>" \
>   --test <the failing test's pytest id> --issue-file issue.md --executor docker --out runs/my-fix
> uv run receipts show runs/my-fix
> ```
> This one needs a Nebius Token Factory API key in `.env` (`OPENAI_API_KEY`; new accounts get free credits). It prints each step as it happens and ends with VERIFIED or REJECTED and a receipt.
>
> Afterwards, could you tell me: did it work, how long did it take, would you trust its VERIFIED before merging, and what was confusing? And if you're happy for me to, I'd quote one sentence from you (with your name or anonymously, your choice) and link your receipt in the submission.

## What to collect

- Level reached (1 or 2), wall time, and any error text.
- Terry's answers to the four questions, verbatim.
- Permission: quote by name, quote anonymously, or not at all; and whether the receipt may be linked.
