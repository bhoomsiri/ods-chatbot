"""Offline RAG ablation & quality-evaluation harness.

A black-box-free, *in-process* harness that reuses the production adapters
(``app.core.providers``) and the real pipeline logic (``AnswerQuestion.retrieve``)
to prove the value of each magic number via one-factor-at-a-time (OFAT)
ablation. Lives outside ``app`` so it never ships in the API image and cannot
affect a running server: every run is read-only against Qdrant and, in phase 1,
never calls an LLM.

See ``ABLATION_HARNESS_SPEC.md`` in ``benchmark/`` for the full design.
"""
