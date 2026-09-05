## Brief

**Brief** turns a topic into a structured, evidence-backed research brief. You give a topic (and optional guidance), Evidence Lab drafts an outline grounded in the document library, and you research each heading into cited prose that you can edit, reorder, and export to Word.

![The Brief workspace — history, contents (TOC) and the document](/docs/images/brief/brief-workspace.png)

When you are signed in, briefs are saved to your account and open from **Brief Central** — the landing page listing your **Saved Briefs**, briefs **Shared with me**, your **Templates**, and your **Voice & tone** profiles.

The workspace itself has three parts:

- **Contents** (left) — where you add, name, reorder, and remove headings, and jump to a section. It follows you as you scroll and highlights the section you are reading.
- **The document** (middle) — the brief itself: each heading and its researched, cited text.
- **Comments** (right) — review threads on the brief, when there are any.

> Brief is a tab in the top navigation. If you don't see it, an administrator can enable it with `application.brief.enabled` in `config.json`.

---

### 1. Generate an outline

Click the **Brief** tab and you'll land on the start screen.

![Brief start screen — topic, instructions and number of sections](/docs/images/brief/brief-seed.png)

You have three ways to start:

- **Generate outline** — enter a **Topic** (e.g. *girls education in Kenya*), optionally add **Instructions** to steer the headings (e.g. *focus on East Africa, prioritise RCTs since 2018, structure around outcomes*), choose the **Number of sections**, and click **Generate outline**. Evidence Lab runs a deep-research survey across the document library and proposes headings grounded in what the collection actually contains. While the survey runs, a *Deep research in progress* panel shows what it is searching; click the **×** at the end of that row to stop it and return to the form with your topic and instructions kept.
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

Citations work like the rest of Evidence Lab: inline number badges link to the source document and page, an expandable **Evidence** panel lists the supporting documents for that section, and a compiled **References** list appears at the end of the brief. Citation numbers are renumbered consecutively across the whole brief, one number per cited passage — the same numbering the Research Assistant uses, so a document cited from three pages carries three numbers.

---

### 4. Saved briefs (Brief Central)

Briefs save automatically as you research. Signed in, they are stored against your account (so they follow you between browsers) and listed under **Saved Briefs** in Brief Central. Each card shows the topic, section and source counts, the voice profile in use, and who it is shared with.

From a card you can **open**, **share** or **delete** a brief. **New brief** starts again from the topic screen.

> Signed out, briefs are kept in your browser's local storage instead, and sharing, templates, voice profiles and comments are unavailable.

---

### 5. Export to Word

When your brief is ready, click **Export to Word** at the top right.

The exported document mirrors what you see on screen: inline `[n]` citation numbers in the prose and a compiled **References** list at the end, laid out according to the **Group by document** checkbox above that list. Leave it off for one line per citation; tick it to collapse the list to one line per document — `Title, [1] p. 32, [2] p. 56` — which is more compact when a brief leans on a handful of reports.

![Export to Word button](/docs/images/brief/brief-export-button.png)

The exported `.docx` is a polished, branded document titled **AI-generated Research Brief**, with:

- A clickable **table of contents** that jumps to each heading (no "update fields" prompt on open).
- An information box noting the content is AI-generated and should be verified.
- The brief topic as the heading, followed by each section's text.
- Citations linked to the **actual source PDF at the cited page**, so a reader outside Evidence Lab can open the document in their browser. The **Reference Excerpts** section carries the supporting passages. Any tables or figures in those passages are embedded as the same images shown on screen, so they keep their original layout.

![The exported Word document](/docs/images/brief/brief-word-doc.png)

> Brief content is generated by AI through deep research over the document library. Always verify factual claims and review for coverage and accuracy — it's a guide for the writing process, not a finished product.

---

### 6. Share a brief

Open a brief and click **Share**, or use **Share** on its card in Brief Central.

Sharing is **viewer-only**: recipients can read the brief, follow its citations, export it and leave comments, but they cannot change the text, re-research a section, or re-share it. Only the owner can edit.

- **Add people or groups** — start typing a name, email address or group name. Matching users and groups appear after two characters; pick one and click **Add**. Groups share with every current member.
- **Brief link** — copy the brief's URL (`/brief/<id>`) and send it. The link only opens for people you have added, so it is safe to paste into a channel where others might see it.
- **Remove access** — click the **×** beside a person or group.

Briefs shared with you appear under **Shared with me** in Brief Central, labelled with the owner's name.

---

### 7. Templates

A template stores a heading structure so the next brief starts with the shape you want, rather than a blank outline or an AI-generated one.

- **Save a brief as a template** — open a brief and click **Save as Template**. You can edit the headings before saving, and choose whether to **include section text** (off by default, which saves the headings only).
- **Create one from scratch** — on the **Templates** tab in Brief Central, click **New template** and add headings (and sub-headings) by hand.
- **Use a template** — click **Use** on a template card, or pick it in the **Manual** tab of the New brief dialog. The brief opens with those headings ready to research.

Templates are private to you.

---

### 8. Voice & tone profiles

A voice & tone profile is a set of style instructions applied whenever a section is written, so briefs read consistently for their audience — a donor board memo and a field-team summary need different registers.

- **Create one** — on the **Voice & tone** tab in Brief Central, click **New voice & tone profile** and give it a name, a one-line description of when to use it, and the style instructions themselves (for example: *Write in plain English at CEFR B2. Lead each section with the finding, then the evidence. Avoid acronyms on first use.*).
- **Apply it to a brief** — choose a profile in the New brief dialog, or in **AI Regenerate All**.
- **Override it for one section** — a section's Research or Regenerate panel has its own profile selector; leave it on *Use brief default* to inherit the brief's.

The instructions are passed to the model when the outline is generated, when a section is researched or regenerated, and when a section is revised with **AI Edit**.

---

### 9. Comments

Comments let reviewers respond to a brief in place, which is the usual next step after sharing one.

![Commenting on a passage of a brief](/docs/images/brief/brief-comments.png)

- **Start a thread** — select any text in the brief and choose **Comment** from the toolbar that appears over the selection. The comment is anchored to the passage you highlighted, which is quoted at the top of the thread.
- **Reply** — type in the box at the bottom of a thread. Threads are one level deep, so a conversation stays readable.
- **Edit** — you can change the wording of your own comments at any time.
- **Resolve** — mark a thread as dealt with; the brief's owner can resolve any thread, and you can always resolve your own. Resolved threads are hidden until you tick **Show resolved**, and can be reopened.
- **Delete** — remove your own comment; the brief's owner can also clear a thread. Deleting the comment that opened a thread removes its replies too.

Anyone who can see a brief can comment on it, including viewers of a shared brief — that is the point of sharing one for review.

Because a comment is anchored to the **text** you highlighted rather than to a position in the document, it survives ordinary editing and re-flowing. If a section is re-researched and the quoted passage is gone entirely, the comment remains in the rail with its quote, so the discussion is not lost.
