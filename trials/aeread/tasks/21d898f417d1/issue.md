In the govsim environment, a spokesperson who says nothing crashes the episode.

In the discuss branch of `step()`, a seat whose action is an empty object (a scripted policy, or a model that answered `{}`) raises KeyError.

An empty message should be recorded as an empty utterance: the episode must not crash, the turn must not be skipped, and no text should be invented in its place.
