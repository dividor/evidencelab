# Draft — header-driven agent research authoring

> Status: **scoping / design**. This is a design spec, not user documentation — it is
> intentionally not wired into `docs/docs.json` until the feature ships.

## Summary

A new top-level tab — **Draft** — that sits alongside **Search**, **Assistant**, and
**Heatmap**. It lets a user assemble a structured, evidence-backed document by:

1. **Defining section headers** in a document editor — typed manually, or
   **auto-generated** from a prompt / topic.
2. **Triggering agent research per header** — each header kicks off a research agent
   that retrieves from the indexed corpus and **writes the section text with inline
   citations**.
3. **Compiling references** — inline citations are collected into **footnotes / a
   reference list at the end** of the document.

The output is a coherent draft the user can review, edit, and export.

## Where it lives

- New tab in the main nav (`TopBar` / app tab routing), same pattern as the existing
  Search / Assistant / Heatmap tabs.
- Must work **without** deployment customization (stock build), consistent with the
  rest of the app.

## User flow (happy path)

```
[ New draft ]
   │
   ├─ Add section headers ──────── manual entry
   │                          └──── "Generate headers" from a topic/prompt (optional)
   │
   ├─ For each header:  ▶ Research        (agent retrieves + drafts the section)
   │                    ▶ Re-run / refine (regenerate, adjust scope)
   │                    ▶ status: idle → researching → drafted
   │
   ├─ Inline citations rendered in section text  [1] [2] …
   │
   └─ References / footnotes compiled at end of document
        │
        └─ Export (format TBD — e.g. Word/Markdown, reusing existing export paths)
```

## Building blocks to reuse (verify before relying on)

- The **Assistant / research agent** stack (LangChain/LangGraph) for per-header research.
- Hybrid **search retrieval** for grounding each section in the corpus.
- Existing **citation rendering** and document **export** paths used elsewhere in the UI.

## Open design questions (for screenshots / iteration)

- **Editor**: rich-text vs Markdown vs block editor? Per-section panels vs one continuous doc?
- **Granularity**: research each header independently, or one pass over the whole outline
  with cross-section awareness?
- **Citations**: numbered footnotes vs author-date; how to de-duplicate sources across
  sections; click-through to source documents.
- **Header generation**: from a free-text topic, from a selected dataset, or from a saved search?
- **Run model**: synchronous per-header vs a single "Research all" batch with live progress
  (cf. the live run progress already used in the Testing tab).
- **Persistence**: are drafts saved server-side (new tables) or client-only initially?

## Phasing (proposed)

- **P0** — Tab scaffold: nav entry + empty Draft view (placeholder), so layout/placement
  can be designed.
- **P1** — Manual headers + per-header research producing cited text.
- **P2** — Auto-generate headers; compiled footnotes/references; export.
- **P3** — Persistence, refinement controls, cross-section coherence.

## Out of scope (initially)

- Multi-user collaborative editing.
- Arbitrary external-web research (grounding stays on the indexed corpus unless decided otherwise).
