The shared runner's adapter canary (`run_adapter_canary`) writes a checkpoint that later runs resume from, and that checkpoint can record things it should not:

- A response cut off by the token limit is accepted, although its JSON may be incomplete.
- A provider cost that is negative, NaN or infinite is recorded as the canary's cost.
- A provider failure is written to the checkpoint with the provider's raw failure text, which can contain the provider's response body.
- An unexpected internal error (a bug in our own code, not a provider failure) is written to the checkpoint as if it were a canary outcome, instead of being raised.
- A checkpoint written for one family is resumed by a canary for a different family, without a new provider call.

The canary should reject a truncated response and an invalid cost, each with its own failure condition (`truncated_response`, `invalid_provider_cost`; an invalid cost is recorded as 0.0), record provider failures by type and condition only, let unexpected internal errors propagate without writing a checkpoint, and refuse to resume a checkpoint that belongs to a different family.
