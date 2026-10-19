# Next steps (Ignasi's hands-on list)

What is left to do **on the machines**, in order. Claude can't do these: they need the PDFs, Ollama models and
a GPU. Paste the output of every step marked 📋 into the next Claude session; it turns them into settings,
numbers in `docs/weekly/` and decisions. `TODO.md` keeps the plan; this file is the checklist.

**Stopping a long run** (`ingest`, `index`, `detect`): **Ctrl+C** anytime. Finished documents are kept; the same
command later resumes where it stopped. Before closing the laptop: Ctrl+C, then `docker compose stop` (optional).

Branch everywhere: `claude/vibrant-goodall-5rmyu2` = PR #3 + two proposed features that are off unless you ask for
them (D38 agent: `ask --agent`; D39 OCR: `extraction.ocr.enabled`). They go in a second PR after #3 is merged.

## 1. GTX 1080 PC (everything installed) — do this first

```powershell
cd $HOME\code\agent-apunts
git fetch; git checkout claude/vibrant-goodall-5rmyu2; git pull; uv sync
docker compose up -d
ollama pull bge-m3; ollama pull qwen2.5:7b
uv run agent-apunts doctor                 # all "ok" (the LLM line too)
```

| # | Command | Check | 📋 |
|---|---|---|---|
| 1 | `uv run agent-apunts ingest` | Progress bar moves; ends with 0 errors and ~2,366 points. Note the time: on the GPU it should be minutes, not the ~80 min of Omarchy's CPU | time + last lines |
| 2 | `uv run agent-apunts doctor` (right after) | Line `ollama memory`: `bge-m3 … 100% GPU` | that line |
| 3 | `uv run agent-apunts ingest` again | `0 indexed`, same point count (idempotent) | last line |
| 4 | `uv run agent-apunts images` | Per-subject table (Disseny ~31% on Omarchy: should match) | table |
| 5 | `uv run agent-apunts detect --evaluate` | Two accuracies: the second (without near-duplicates) is the CV number | everything |
| 6 | `uv run agent-apunts duplicates` | Pairs ≥ 0.9: are they really translations / with-without solutions? Open 3 | table + your verdict |
| 7 | `uv run agent-apunts search "què és el patró Creator?"` then the same with `--hybrid` | Right slides (slides_grasp) in the top 3? | both tables |
| 8 | `uv run agent-apunts search "TLB" --hybrid` and without `--hybrid` | Hybrid should rank the TLB pages higher (exact word) | both |
| 9 | `uv run agent-apunts ask "Què diu el patró Creator?"` | Answer in Catalan with `[n]` citations; a `tokens in / out` line; while it runs `ollama ps` says 100% GPU | answer + table + time |
| 10 | `uv run agent-apunts ask "Qui va guanyar el mundial de 2010?"` | Abstains ("No ho he trobat als teus apunts") with reason `low_score` or `not_found` | the output |
| 11 | 5 more `ask` in ca/es/en about things you know are in the notes | Wrong page? no citation? wrong language? | each wrong one |

### Optional on the GTX 1080: the agent (D38, proposed)
```powershell
uv run agent-apunts ask "Quins exàmens d'IS tinc i de quins anys?" --agent
uv run agent-apunts ask "Compara què van preguntar sobre signatura digital els exàmens d'IS de 2023-24 i 2024-25" --agent
```
📋 the `→ tool(...)` lines and the answer: did it pick sensible tools and filters, and cite pages?

## 2. Golden set (any machine, ~1 hour, the most valuable step)

`copy eval\golden.example.yaml eval\golden.yaml`, then write **20 questions** following `eval/README.md`
(~6 per subject, ca/es/en mixed, 3–4 unanswerable, some tagged `code-image`).
`uv run agent-apunts documents --subject disseny_software` lists the exact paths to copy and their page
counts; `uv run agent-apunts inspect <part of a file name> --page N` shows a page's text. Then:

```powershell
uv run agent-apunts eval --sweep          # 📋 the tables: hit@k, MRR, abstention sweep
uv run agent-apunts eval --hybrid         # 📋 then:
uv run agent-apunts compare               # 📋 dense -> hybrid: metric changes, questions gained/lost
uv run agent-apunts eval --answers        # 📋 GTX 1080 only (~20 x 10-30 s)
uv run agent-apunts eval --answers --agent   # 📋 GTX 1080: the agent on the same questions, then
uv run agent-apunts compare --kind answers   # 📋 ask -> agent
git add eval/golden.yaml; git commit -m "eval: first golden set (20 questions)"; git push
```
`eval` lists documents it doesn't know and pages a document doesn't have: fix those first.
The golden set is committed (D34): your questions and file names only, no course text.

## 3. Omarchy

`cd ~/code/agent-apunts && git fetch && git checkout claude/vibrant-goodall-5rmyu2 && git pull`, then
`uv run agent-apunts ingest` (re-extracts once for loader v7, re-chunks for the label fix, resumes the index
from 943 points; ~50 min on the CPU). Only needed if you want to work on Omarchy too: each machine has its
own Qdrant.

## 4. Windows PC 2 (Ryzen 5 3600, RX 480 8 GB, 16 GB RAM)

Only when you want to use it (`cd $HOME\code\agent-apunts`, same branch):
1. `winget install --id Ollama.Ollama -e` (or re-run `scripts\setup-windows.ps1`), open a new terminal,
   `ollama pull bge-m3`. `OLLAMA_VULKAN=1` is already set for your user.
2. Qdrant: Docker needs **SVM Mode** on in the BIOS (`docs/SETUP.md` > Troubleshooting). Without touching the
   BIOS: `powershell -ExecutionPolicy Bypass -File scripts\qdrant-windows.ps1` in a second window (keep it open).
3. `uv run agent-apunts ingest`, then `uv run agent-apunts doctor`: 📋 the `ollama memory` line says whether
   Vulkan works on the RX 480 (`100% GPU`) or it runs on the CPU; note the indexing time too.

## 5. GitHub

- Read the PR #3 description and merge it on GitHub when step 1 works.
- Then ask Claude for the follow-up PR (D38 agent + D39 OCR, from `claude/vibrant-goodall-5rmyu2`).
- Then delete the old branches (`claude/serene-brahmagupta-md8g0y`, `feat/dev-environment`) in GitHub's branch list.

## 6. Experiments, once the golden set exists (each: change, `ingest`, `eval`, `compare` 📋)
- OCR of code screenshots (D39): install the language files (`docs/SETUP.md` step 7), `doctor` → `ocr` ok,
  `extraction.ocr.enabled: true`. Look at the `code-image` questions in `compare`.
- Hybrid search: `eval --hybrid` vs `eval` (no re-index needed).
- Topic in chunk headers: below.
- The agent: `eval --answers --agent` vs `eval --answers`, then `compare --kind answers`.

## 7. Still yours to decide (no rush)

- Topic headers like "P5: Jerarquía de Memoria": built as an experiment, off by default. After the golden
  set: set `chunking.topic_in_header: true` in `config/settings.yaml`, `uv run agent-apunts ingest` (re-embeds
  the documents that have one), `uv run agent-apunts eval`, then `uv run agent-apunts compare` 📋; keep it on only if hit@k / MRR improve.
- Delete the local copy `testing/apunts_testing/` on this PC once OneDrive works here (TODO week 1).
