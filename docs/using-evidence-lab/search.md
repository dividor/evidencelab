## Search

Evidence Lab's search combines hybrid retrieval with AI-powered summaries to help you find and understand the most relevant content across thousands of documents.

### Entering a Search Query

Type your question or topic into the search bar using natural language. Evidence Lab understands full questions, phrases, and keywords — in multiple languages. You can also click one of the **suggested queries** on the homepage to get started quickly.

The search bar also contains a **Filters** toggle button (≡ Filters) that lets you pre-filter by section type before running a search. By default, all sections are included (executive summary, context, methodology, findings, conclusions, recommendations).

Click **Search** or press Enter to run your query.

![Search results overview](/docs/images/search-guide/search-results-full.png)

---

### AI Summary

At the top of your results, Evidence Lab generates an **AI Summary** — a synthesized answer drawn from the top-matching document excerpts. This gives you an immediate overview without needing to read individual results.

- The summary includes structured **headings** and **sub-topics** derived from your query.
- Click **"See more"** to expand the full summary.
- Use the **language dropdown** (top-right of the summary card) to translate the summary into 10+ languages.
- Click **"Find out more"** next to a heading to drill into that sub-topic as a new search — this launches a **Research Tree** (see [Research Trees](/docs/using-evidence-lab/research-trees.md)).
- You can also **highlight any text** within the summary and click the popup button to research that specific phrase further.
- The **Response variability** slider under **AI Summary** in the left sidebar sets the model's sampling temperature, shown beside the label. At **More Consistent** (temperature 0, the default) the model always takes its most likely wording, so the same results give the same summary every time. Towards **Creative Insights** (1) it may choose less likely wordings, so summaries differ between runs and paraphrase more loosely.
- By default the summary is built from the top **20** results. Under **AI Summary** in the left sidebar you can change that number, or untick **Limit Results Used** to give it every result on the page (slower and costlier, but nothing is left out). With Wide Search on, the results are spread across documents first.

> *Note: The AI summary is generated in real-time and may take a few seconds to stream in. A disclaimer reminds you that AI can make mistakes — always verify important findings against the source documents.*

---

### Search Results

Below the AI summary, results are organized into several sections:

#### Organization Chips

A row of **organization filter chips** (e.g., UNDP (14), UNICEF (4), FAO (4)) appears above the results. Click any chip to instantly filter results to that organization. This is a quick way to focus on a specific agency's documents.

#### Document Carousel

A horizontal **carousel of document cards** shows the top-matching documents with their cover images, titles, organizations, and publication years. Each card carries a badge with the number of matching excerpts from that document. Click any card to jump directly to that document's results below, or scroll the carousel to browse more.

#### Result Cards

Each result card shows:

- **Document title** — click to open the document in the PDF viewer
- **Page number badge** (e.g., "Page 24") — click to open the PDF directly at that page
- **Metadata line** — organization, year, and country
- **Section breadcrumb** — shows where in the document this excerpt came from (e.g., "CONTEXT > Nutrition situation in Bangladesh > Humanitarian context")
- **Text excerpt** with **semantic highlighting** — key phrases relevant to your query are shown in bold, even when the search was in a different language from the document
- **Language indicator and translation** — click the language dropdown to translate the result snippet

#### Group by Document

Tick **Group by document** under **Search Settings** in the left sidebar to see one row per document instead of a flat list of excerpts. Each row shows the document's cover thumbnail, title, source and year, and how many excerpts matched. Because the rows carry the thumbnails, the document carousel is not shown in this mode; the organization chips stay, and still filter the rows. Rows start collapsed; click a row to expand it and see that document's excerpt cards (the same cards as the flat list, with page numbers, highlighting, translation and ratings), and click again to collapse it. A line above the rows tells you how many excerpts and documents you are looking at.

Grouping changes only how results are shown: the search, its ranking and the AI summary are unchanged. A **Sort by** control next to the Export button orders the rows by **Relevance** (the cumulative relevance of each document's excerpts, so a document with several good matches ranks above one with a single match) or by **Publication Date** (newest first, undated documents last). Excerpts inside a row keep their rank order either way. The chevron at the left of each row, or the **Expand all / Collapse all** button next to the sort control, opens and closes the rows. **Export to Word** in this mode adds a **Document List** table under References: each document (its title linked to the document online), its source and year, and how many times the AI summary cites it, in the same order as the rows. The setting is kept in the page link (`group_by_doc=true`) and administrators can set it as a team default under **Admin → Group Settings**.

---

### Filters

The left sidebar provides **faceted navigation** to narrow your results:

![Filters sidebar](/docs/images/search-guide/filters-crop.png)

| Filter | Description |
|--------|-------------|
| **Organization** | Filter by publishing agency (e.g., UNDP, UNICEF, ILO). Shows document counts beside each option. Use the search box within the facet to find a specific organization. |
| **Document Title** | Search for specific document titles. |
| **Year Published** | Filter by publication year range. |
| **Document Type** | Filter by type (e.g., Project/Programme, Thematic, Country). |
| **Country** | Filter by the country or countries covered by the document. |
| **Geographic Scope** | Filter by scope level (Country, Regional, Global). |
| **UN Sustainable Development Goals** | Filter by SDG classification (AI-generated). |
| **Cross-Cutting Themes** | Filter by thematic tags (AI-generated). |
| **Language** | Filter by document language. |

Click any filter option to apply it immediately — results update in real-time. Active filters appear as removable tags. Click **"Clear filters"** to reset all filters at once.

> *Tip: Filters and search work together. Start with a broad query, then use filters to progressively narrow results to exactly what you need.*

### Wide Search

By default a search returns the best-matching **excerpts**, wherever they come from. When a topic is covered in depth by one report, that report can fill most of the list on its own, so you see a lot of one document and little of the rest of the library.

**Wide Search** changes what a result is: instead of the top excerpts, you get a set number of **documents**, each contributing at most a few excerpts, with documents ranked by their single best match. Turn it on under **Search Settings** in the left sidebar, then set:

| Field | What it does | Default |
|-------|--------------|---------|
| **Max results per document** | The most excerpts any one document can contribute. | 5 |
| **Number of documents** | How many documents to return. The total number of excerpts is at most *documents × max per document*. | 20 |

Wide Search respects your other settings: filters and section types still narrow what is searched, the semantic/keyword balance still applies, and the reranker, recency boost and deduplication still run on what comes back. The document carousel above the results shows how many excerpts each document contributed. The AI Summary is built from the best excerpt of each document first, so its references spread across the returned documents too.

Use it when you want coverage across the library, such as scanning how many evaluations touch a theme, rather than the deepest matches on one report. Leave it off for a focused question where the most relevant passages matter more than spread.

Administrators can set Wide Search and its two fields as defaults for a team under **Admin → Group Settings**; users can still change them for a session.

---

### Document Preview & PDF Viewer

Click a **document title** or **page number badge** on any result to open the integrated PDF viewer. The viewer opens directly at the relevant page so you can see the source material in context.

![Document preview](/docs/images/search-guide/doc-preview.png)

The PDF viewer includes:

- **Document header** — title, organization badge, year, and page reference
- **Quick-link chips** — jump to the hosting page or source document on the original website
- **Page navigation** — Previous/Next buttons and a direct page number input to navigate through the document (e.g., "Page 24 of 106")
- **Search in document** — a dedicated search bar to find specific text within the PDF
- **Zoom controls** — zoom in/out and reset zoom for comfortable reading
- **Contents tab** — view the document's table of contents for quick navigation
- **Metadata tab** — view structured metadata including organization, title, year, document type, country, geographic scope, language, AI-generated summary, and table of contents

#### Metadata Card

When you click a result to open the document preview, a **metadata card** appears alongside the PDF viewer. This card shows key information about the document at a glance — title, organization, year, document type, country, language, and the AI-generated summary. It gives you quick context without needing to read the full document.

![Document metadata card](/docs/images/search-guide/metadata-card.png)

---

### Filters & Metadata Configuration

The filter fields shown in the left sidebar and the metadata fields shown in the document panel are **configurable per datasource** by admin users via the [`config.json`](https://github.com/dividor/evidencelab/blob/main/config.json) file. Each datasource defines its own `default_filter_fields` and `metadata_panel_fields`, so different teams can tailor the search experience to their data. See [Pipeline Configuration](/docs/admin/pipeline-configuration.md) for details.

---

### Translation

Evidence Lab supports searching across languages. You can:

- **Search in one language, find results in another** — the semantic search engine understands meaning across languages, so a query in English can surface relevant French, Spanish, or Arabic documents.
- **Translate results** — use the language dropdown on any result card or the AI summary to translate content on the fly.
- **Semantic highlighting works cross-lingually** — even when your query language differs from the document language, relevant phrases are still highlighted in the results.
