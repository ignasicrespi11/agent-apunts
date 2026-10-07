# eval/

The golden set: questions **written by Ignasi** with the document (and pages) where the answer is.
`agent-apunts eval` measures how often retrieval finds them (D8, D34). It contains no course text,
only questions and file paths, so it can be committed.

## How to write `golden.yaml`
Copy `golden.example.yaml` to `golden.yaml` and replace the examples. Aim for **20 questions** first:

- ~6 per subject, mixing **ca / es / en** (and some asked in a different language from the slides:
  that tests cross-lingual retrieval, D3).
- Different kinds, marked with `tags`: `definition`, `formula`, `procedure`, `exam-exercise`, and
  **`code-image`** for questions answered by a code screenshot or diagram (D30: measures what
  OCR would add).
- **3–4 unanswerable questions** (`answerable: false`): plausible but not in your notes. They
  calibrate when `ask` should say "not in your notes" (`--sweep`).
- `expected.document` is the path printed by `inspect` (`subject/doc_type/file.pdf`);
  `pages` lists every page that answers it (leave it empty if any page of the document counts).
- Write the question first, then look up where the answer is. Don't copy the slide's wording:
  real questions use your own words.

## Run
```bash
uv run agent-apunts eval                 # hit@1/3/5, MRR, per language / subject / tag
uv run agent-apunts eval --sweep         # + abstention quality for min_score 0.20..0.80
uv run agent-apunts eval --filter-subject   # each query filtered by its subject
```
Each run is saved to `data/eval/retrieval-<timestamp>.json` with the settings used, so runs before
and after a change (cleaning, chunking, OCR, model) can be compared.
