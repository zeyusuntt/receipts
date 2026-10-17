`housing_env.resolve_bids` does not hold to a clear bid contract.

Malformed bids are not reliably ignored: a boolean tenant key, a listing index that is a boolean or not an integer (such as `1.9`), and a bid amount that is NaN, infinite or a string such as `"Infinity"` can be accepted or make the resolver fail, instead of being skipped. A key that is not a tenant at all should not stop an independent valid bid from winning either. A malformed bid should simply be ignored: it wins nothing and leaves the other bids to resolve normally.

The resolver also does not say what its score measures. Rent is a transfer, so an extreme overbid can leave a tenant with negative payoff without lowering joint surplus: the score is allocation welfare, not tenant payoff. `resolve_bids`' docstring should state that contract.
