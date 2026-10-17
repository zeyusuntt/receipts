Three datacenter scorers do not follow the kernel scoring contract, so every live cell is excluded.

`DataCenterDevelopmentScorer` was migrated to the kernel scoring contract, but the other three were not: the scorers in `datacenter_development_terms`, `datacenter_development/objective_measurement.py` and `datacenter_development/adoption_measurement.py` still take the recorded-outcome mapping directly when called. The finalizer passes a `FamilyScoringInput`, so the terms validator receives a dataclass, reports "data-center terms outcome must be an object", and every live cell is excluded as an invalid measurement (21 failures).

Each of the three scorers should, when called, take the scoring input and score `scoring_input.outcome` (the outcome from the verified re-execution, the same mapping they score today) through the existing recorded-outcome scoring (`score_recorded_outcome`), which should stay available under that name.
