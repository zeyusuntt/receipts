A transient 429 on the econevals live campaign's unscored canary permanently seals the attempt root, because the canary is write-once.

Write-once is the right rule for a measurement and the wrong one for a probe that produces no measurement. It cost two attempt roots within an hour.

The canary should re-probe typed transient conditions (rate_limit, provider_5xx, timeout) up to a budget declared in the frozen plan, keeping a write-once record of each probe. A non-transient rejection should still stop the run on the first probe.
