The post-admission retry in the shared runner's execution layer has four gaps on the production path.

1. Multi-round proof. A route is recorded as proven only when a whole attempt returns, so when round 1 of an attempt succeeds and round 2 returns a 404, the failure escapes untyped and is not retried. A settled earlier round should already prove the route when the later failure is classified.

2. Classification is too broad. Every `provider_rejected` after one success is promoted to `provider_rejected_after_route_proven`, but that bucket also holds 400, 401 and 403 and invalid request, model or configuration errors; a 401 after a success is a revoked credential, not a flaky route. Only a 404 should be promoted. The proof should belong to the route that answered (provider, base URL and model), not to the profile, within one executor.

3. The condition is not durable. The effective condition is computed after the provider record and its events have been sealed under the raw condition, so nothing durable ever says `provider_rejected_after_route_proven`. The same effective condition should be used for the provider record, both events, the retry decision, the backoff and the finalizer's failure code.

4. Arena length path. Completion-budget growth happens only after a `ProviderResult`; Arena raises `ProviderFailure('length')` directly, and that path retries at the same limit. Growth should apply on both paths, and stay capped at a multiple of the declared budget.

Also, the provider context-window cap is dead code (nothing ever sets `_provider_capabilities`), and the family hook compatibility check should cover every trusted built-in plugin key: check the real registered plugin for each key that resolves, and require each key that cannot resolve in a plain environment to be named with a reason.
