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

> *Note: The AI summary is generated in real-time and may take a few seconds to stream in. A disclaimer reminds you that AI can make mistakes — always verify important findings against the source documents.*

---

### Search Results

Below the AI summary, results are organized into several sections:

#### Organization Chips

A row of **organization filter chips** (e.g., UNDP (14), UNICEF (4), FAO (4)) appears above the results. Click any chip to instantly filter results to that organization. This is a quick way to focus on a specific agency's documents.

#### Document Carousel

A horizontal **carousel of document cards** shows the top-matching documents with their cover images, titles, organizations, and publication years. Click any card to jump directly to that document's results below, or scroll the carousel to browse more.

#### Result Cards

Each result card shows:

- **Document title** — click to open the document in the PDF viewer
- **Page number badge** (e.g., "Page 24") — click to open the PDF directly at that page
- **Metadata line** — organization, year, and country
- **Section breadcrumb** — shows where in the document this excerpt came from (e.g., "CONTEXT > Nutrition situation in Bangladesh > Humanitarian context")
- **Text excerpt** with **semantic highlighting** — key phrases relevant to your query are shown in bold, even when the search was in a different language from the document
- **Language indicator and translation** — click the language dropdown to translate the result snippet

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
