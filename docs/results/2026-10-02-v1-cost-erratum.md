# Erratum: v1's model cost (2026-10-02)

v1's `REPORT.md` states a cost per verified fix of "$0.095 model, $0.035 sandbox, $0.13 total". The model figure is wrong. `REPORT.md` is not rewritten (pre-registration rule); this note corrects it.

## What was wrong

`src/receipts/cost.py` priced Nemotron 3 Super at $0.06 per million prompt tokens and $0.24 per million completion tokens. Token Factory lists it at $0.30 and $0.90 (`GET https://api.tokenfactory.nebius.com/v1/models?verbose=true`, read 2026-10-02). The token counts were right; the price per token was not.

The account's billing confirms the listed price: every worker token recorded across v1 and the three v2 rehearsals, priced at $0.30 and $0.90, comes to $15.98, and the account shows $16 spent.

## Corrected v1 numbers

Over the 50 tasks that ran in launch 3, with 24 verified fixes:

| | As reported | Corrected |
| --- | ---: | ---: |
| Worker prompt tokens | 36.32 million | 36.32 million |
| Worker completion tokens | 0.42 million | 0.42 million |
| Model dollars, total | $2.28 | $11.28 |
| Model dollars per verified fix | $0.095 | $0.470 |
| Sandbox dollars per verified fix | $0.035 | $0.035 |
| Total per verified fix | $0.13 | about $0.51 |

The corrected model figure counts the worker only. v1 did not record the planner's tokens; it makes one structured call per run, so its share is small, and the corrected total is a slight underestimate.

Nothing else in `REPORT.md` depends on the price: the false-done rate, the verified fixes, the agreement matrix and every disagreement are unchanged.

## Why it matters, and what changed

Prompt tokens dominate the cost (36.32 million against 0.42 million completion tokens), because the worker sends its whole conversation on every turn. The price table was corrected in the v2 code (`src/receipts/cost.py`, with its read date and source), and v2's pre-registration states the prices it uses.
