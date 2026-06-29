## Brief

**Brief** turns a topic into a structured, evidence-backed research brief. You give a topic (and optional guidance), Evidence Lab drafts an outline grounded in the document library, and you research each heading into cited prose that you can edit, reorder, and export to Word.

![The Brief workspace — history, contents (TOC) and the document](/docs/images/brief/brief-workspace.png)

The workspace has three parts:

- **History** (left) — your saved briefs. Briefs auto-save as you work.
- **Contents** (the TOC at the top of the document) — where you add, name, reorder, and remove headings, and jump to a section.
- **The document** — the brief itself: each heading and its researched, cited text.

> Brief is a tab in the top navigation. If you don't see it, an administrator can enable it with `application.brief.enabled` in `config.json`.

---

### 1. Generate an outline

Click the **Brief** tab and you'll land on the start screen.

![Brief start screen — topic, instructions and number of sections](/docs/images/brief/brief-seed.png)

You have three ways to start:

- **Generate outline** — enter a **Topic** (e.g. *girls education in Kenya*), optionally add **Instructions** to steer the headings (e.g. *focus on East Africa, prioritise RCTs since 2018, structure around outcomes*), choose the **Number of sections**, and click **Generate outline**. Evidence Lab runs a deep-research survey across the document library and proposes headings grounded in what the collection actually contains.
- **Write my own headings** — skip the survey and start from a small set of placeholder headings you edit yourself.
- **Load a saved brief** — reopen any brief from your history.

When an outline is generated, the brief name and headings are capitalised automatically (e.g. *girls education kenya* → *Girls Education Kenya*).

To see what the survey searched for, click **Outline analysis** under the title — it lists the queries run and the sources read. Use the **×** to close it.

---

### 2. Build and edit the outline (Contents)

Everything structural happens in the **Contents** panel at the top of the document.

- **Add a heading** — click **Add heading**, type a name, and press **Enter**. Nothing is added until you enter a name.
- **Add a sub-heading** — click the **+** on a heading, type a name, and press **Enter**.
- **Reorder** — drag the grip handle (the three-line icon) on a row to move a heading. A top-level heading carries its sub-headings with it; sub-headings reorder within their parent. Dragging works with both mouse and touch.
- **Remove** — click the **×** on a row to delete that heading.
- **Jump to a section** — click a heading's text to scroll straight to it in the document.
- **Number headings** — toggle the switch on the Contents row to show or hide hierarchical numbering (`1.`, `2.1`, …). It's off by default.

### Editing heading text

To rename a heading, click its title in the document and type — the title is editable inline. (Editing a placeholder heading also enables it for research.)

---

### 3. Research a heading with AI

Each heading starts un-researched. To fill one in, open it and click **Research this section**. You can add optional focus or guidance for that section before running it.

![Researching a heading with optional guidance](/docs/images/brief/brief-research-section.png)

Evidence Lab runs deep research scoped to that heading — its searches take into account the brief topic, the heading's parent section (for sub-headings), and your guidance — then writes cited prose for the section. You can research sections one at a time, or click **Start deep research** to research the whole outline in sequence.

When a section finishes, it shows the written text with inline citations.

![A researched section with citations and edit controls](/docs/images/brief/brief-section-result.png)

For each completed section you can:

- **Edit text** — tweak the generated prose by hand.
- **Regenerate** — re-run the research, optionally with new guidance.

Citations work like the rest of Evidence Lab: inline number badges link to the source document and page, an expandable **Evidence** panel lists the supporting documents for that section, and a compiled **References** list appears at the end of the brief. Citation numbers are renumbered consecutively across the whole brief and combined per document.

---

### 4. Saved briefs (History)

Briefs save automatically as you research, and appear in the **History** rail on the left. From there you can:

- **Search** your briefs by name or topic.
- **Duplicate** a brief (the copy icon) to branch off a new version.
- **Delete** a brief (the **×**) — the brief you currently have open can't be deleted.
- **See more** — when you have more than ten briefs, open the full, searchable list.
- **New brief** — start again from the topic screen.

---

### 5. Export to Word

When your brief is ready, click **Export to Word** at the top right.

![Export to Word button](/docs/images/brief/brief-export-button.png)

The exported `.docx` is a polished, branded document titled **AI-generated Research Brief**, with:

- A clickable **table of contents** that jumps to each heading (no "update fields" prompt on open).
- An information box noting the content is AI-generated and should be verified.
- The brief topic as the heading, followed by each section's text.
- Inline citations linked to the source documents (and the cited page), plus a **References** list and a **Reference Excerpts** section with the supporting passages.

![The exported Word document](/docs/images/brief/brief-word-doc.png)

> Brief content is generated by AI through deep research over the document library. Always verify factual claims and review for coverage and accuracy — it's a guide for the writing process, not a finished product.
