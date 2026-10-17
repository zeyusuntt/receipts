Two defects in the EverOS memory candidate (`aeread/integrations/everos_memory.py`).

1. Agent cases are never injected. Agent-case search items carry `task_intent` and `key_insight` fields, not `summary` or `content`, so every extracted case is retrieved but formatted into an empty snippet and silently dropped. Agent-case items should become snippets from those fields.

2. Recall is blind to outcomes. In the v2 arm, 9 of 12 zero-value episodes filled the memory pool with recaps of failed episodes, and they compounded (v2 pooled +0.031, against +0.137 for v1 and +0.087 for the control). The candidate should record each session's realized AER when the episode ends, and drop recalled snippets from known-failed episodes when anything better survives. When nothing else survives, it should keep them rather than recall nothing.
