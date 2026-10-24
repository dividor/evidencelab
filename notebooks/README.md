# Analysis notebooks

Jupyter notebooks for auditing what Evidence Lab produces. They read the local
stack's databases directly and are meant to be run by a reviewer, not deployed.

| Notebook | Purpose |
|---|---|
| `llm_judge_citation_fidelity.ipynb` | Fact-checks one saved brief: extracts every cited passage with the exact source excerpts the system stored, has an LLM judge decide whether each passage is supported by those excerpts only, and lists the passages it flags for human review. |

Helper code that is worth unit testing lives in the app, in `ui/backend/services/citation_fidelity.py` (imported here through the `citation_fidelity_lib.py` shim)
(tests: `tests/unit/test_citation_fidelity.py`); everything a reviewer
should *see* (prompts, verdicts, tables) stays in the notebook cells.

## Setup

Use a dedicated virtualenv so notebook-only dependencies never leak into the
app build:

```bash
python3.11 -m venv ~/.venvs/evidencelab-notebooks
~/.venvs/evidencelab-notebooks/bin/pip install -r notebooks/requirements.txt
~/.venvs/evidencelab-notebooks/bin/jupyter lab notebooks/llm_judge_citation_fidelity.ipynb
```

Requirements at run time:

- the local Docker stack's Postgres published on `localhost:5432` (the repo
  `.env` credentials are reused; override the host/port with
  `EVIDENCELAB_PG_HOST` / `EVIDENCELAB_PG_PORT`);
- `AZURE_FOUNDRY_KEY` and `AZURE_FOUNDRY_ENDPOINT` in `.env` for the judge.

## Outputs

Everything is written to `notebooks/output/` (git-ignored), named by brief id:

| File | Content |
|---|---|
| `citations_<brief-id>.xlsx` | One row per (passage, cited source): brief section, passage, citation number, document, page, source section, exact excerpt. Plus per-passage and per-section sheets. |
| `judge_flagged_<brief-id>.xlsx` | Flagged passages first, then every judgement and a per-section summary. |
| `judge_cache_<brief-id>.jsonl` | Audit log and cache: the exact messages sent to the judge and its raw answer. Delete it to re-judge from scratch. |
