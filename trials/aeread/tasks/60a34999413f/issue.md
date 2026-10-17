A historical housing plan (the v8 contract) can still be executed live after the runtime has drifted from the implementation it was frozen against.

Frozen implementation pins should be preserved, and live execution of such a plan should be refused with an evidence-integrity error saying that the runtime differs from the frozen implementation pin.
