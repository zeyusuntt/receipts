The shared runner's evaluation receipts accept coerced preimages and noncanonical rewrites.

Reading a receipt whose bytes on disk are valid JSON but not canonical succeeds, and writing a receipt over such bytes overwrites them; both should be refused. A transitional receipt whose `deferred_leaf_ids` was changed (for example to None, False, 0, an empty string or an empty object) still reads as valid; it should fail its `receipt_sha256` check.
