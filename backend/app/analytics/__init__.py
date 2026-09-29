"""Phase 15 Slice 1: a bounded, read-only analytics/evaluation surface.

Two independent evidence domains live here, never joined or cross-referenced:

- ``snapshot``: a curated view over Phase 12's existing, already-persisted
  evaluation artifacts (``artifacts/evaluation/``) and governance docs
  (``docs/evaluation/``). Nothing here re-runs an experiment, re-scores a
  metric, or invents a number -- every value is read verbatim from a fixed,
  named-canonical artifact file. See ``snapshot.py`` for exactly which
  artifacts are canonical and why.
- ``structured``: bounded, parameterless or top-N-bounded live aggregate
  SQL queries over the existing structured FHIR/SynPUF tables, reusing
  ``app.repository.analytics`` (Phase 9) unchanged. No new query is added
  by this module -- it only shapes the existing repository functions'
  output for the API.

Both are strictly read-only: no endpoint in this package can execute an
experiment, change a threshold, retrain anything, or write to any table.
"""
