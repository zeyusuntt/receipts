# R8 review costs

Each line is the cost meter summary that `scripts/r8_check.py` printed at the end of the run (Nemotron 3 Super, or Nemotron 3 Ultra for record 3, at Token Factory's listed prices). Records 1 to 4 come from development code that did not store usage per review, so these printed totals are the only cost record for them; records 5 to 7 also store usage in each review.

| Record | Reviews | Prompt tokens | Completion tokens (reasoning) | Cost |
| --- | ---: | ---: | ---: | ---: |
| `r8-dev-1-super-thinking-off.jsonl` | 18 | 28,570 | 2,229 (0) | $0.0106 |
| `r8-dev-2-super-thinking-on.jsonl` | 18 | 28,570 | 24,954 (24,082) | $0.0310 |
| `r8-dev-3-ultra-thinking-on.jsonl` | 18 | 30,263 | 42,398 (41,472) | $0.1575 |
| `r8-dev-4-super-thinking-on.jsonl` | 18 | 28,570 | 25,468 (24,640) | $0.0315 |
| `r8-dev-5-frozen-two-votes.jsonl` | 36 | 57,140 | 52,774 (51,204) | $0.0646 |
| `r8-check-swe-66.jsonl` | 132 | 182,086 | 125,389 (120,813) | $0.1675 |
| `r8-check-heldout2.jsonl` | 12 | 13,734 | 15,955 (15,346) | $0.0185 |
| Total | 252 | 368,933 | 289,167 | $0.4812 |
