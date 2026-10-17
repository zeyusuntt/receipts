The executor's length-retry growth has no ceiling.

On every length retry the executor doubles `max_output_tokens`, without a limit. A 2,400-token budget under a ten-attempt policy reached 1,228,800 tokens, larger than the model's context window, and the provider refused the request outright, turning a recoverable truncation into a dead case. This also pushed families to drop `length` from their retryable conditions, which removed truncation recovery entirely, because the executor labels a response that is both truncated and empty as `length`.

Doubling should stay the tactic, but the growth should be capped at eight times the budget the profile declared (exposed as `_LENGTH_RETRY_MAX_GROWTH`), and at half the provider's advertised context window when the provider declares one.
