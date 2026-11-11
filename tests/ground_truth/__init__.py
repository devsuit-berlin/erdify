"""Ground-truth harness: compare erdify's parse with what the real framework builds.

erdify reads models from source text only. These helpers load the same source
with the real library and reduce both results to one normalised :class:`Schema`,
so a test can assert that the diagram describes the schema the framework would
actually create.
"""
