# testing/

Private test data. Everything in this folder except this README is gitignored.
Not to be confused with `tests/` (pytest code tests, which only use self-generated fixtures).

- `apunts_testing/<subject>/<doc_type>/<file>.pdf`: manually labelled material. It is the development corpus
  for the pipeline and the **ground truth** used to measure metadata auto-detection accuracy (D18).
