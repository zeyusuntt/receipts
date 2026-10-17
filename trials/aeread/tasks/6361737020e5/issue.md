An econevals live step that calls the submit tool twice is not caught by step validation.

A model returned `['submit_purchase_plan', 'submit_purchase_plan']` in one step. `_validate_step` records only the last occurrence of the submit tool, so it sees the submit as the final call and the step passes. The first submit then sits in the middle of the accumulated action, which the environment rejects as a whole (`submit_tool_must_be_the_final_call`), and the case fails after 100 periods of work.

A step that calls the submit tool more than once should be rejected by validation, with feedback to the model, before anything in it executes.
