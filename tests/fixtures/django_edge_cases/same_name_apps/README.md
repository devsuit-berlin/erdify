Multi-app source (#367, #380): a `Profile` model in the `billing` and the
`shipping` app. The ground-truth harness installs both packages as apps and
imports their models for real (see `tests/ground_truth/packages.py`).
