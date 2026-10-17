When an econevals live case is killed after it has already run provider calls successfully, the spend of those calls is lost.

A 429 rejection itself bills nothing, and the rejected canary probes correctly record `cost_usd` 0.0. But a case that ran for a while and then failed had paid for its earlier provider calls, and its failure checkpoint carries no cost field at all, so no ledger counts that spend. In one real attempt, 243 sealed provider calls worth $0.047 were invisible to every ledger.

The sealed spend of a failed case should include the provider calls that case already paid for.
