The termsbench primary leaf changes by case, which ruling R13 (PR #112) forbids.

The termsbench finalizer makes the regime-conditional leaf the primary: `surplus_efficiency` for the overlap regime and `no_deal_agreement` for the nodeal regime. A primary whose identity changes by case cannot be aggregated across cases, and both the primary and the admission leaf must exist for every execution admitted under one static manifest.

`protocol_compliance` is the only leaf both regimes declare. It should be both the primary and the admission leaf for every case. The conditional leaves should still be scored and reported; they should just never carry the primary role.
