A provider rejection that arrives after a route has already answered successfully in the same run is treated like a first-call rejection.

A 404 normally means a wrong model id and must fail fast. But once a profile's pinned route has answered successfully in this run, that reading is impossible: the same request worked minutes earlier. Parasail returned exactly this twice during a live run, and each time it killed a panel mid-run.

Such a rejection should be typed as its own condition, `provider_rejected_after_route_proven`, which a profile opts into by name. A rejection on the first call must stay non-retryable, and no other condition (rate limits, timeouts, provider 5xx) should be relabelled.
