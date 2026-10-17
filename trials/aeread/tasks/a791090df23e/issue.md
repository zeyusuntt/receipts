The EverOS example client goes mute: the model sometimes returns an empty completion, and the client's `llm_fn` passes the empty text on as if it were an answer.

An empty completion should be retried with a larger completion-token budget instead of being returned, and the client's default completion budget should be 4096 tokens.
