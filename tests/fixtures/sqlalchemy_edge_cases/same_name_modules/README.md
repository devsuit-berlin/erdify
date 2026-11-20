Multi-module source (#367, #380): a `Customer` model in `shop.core.models`
and in `shop.mart.models` (tables in schemas `core` and `mart`). The
ground-truth harness imports these packages for real (see
`tests/ground_truth/packages.py`).
