Multi-module source (#367, #380): `Address` exists in `billing` and in
`shipping`; `orders` refers to each through a different import form. The
ground-truth harness imports these packages for real (see
`tests/ground_truth/packages.py`).
