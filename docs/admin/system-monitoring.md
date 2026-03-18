## System Monitoring

Evidence Lab provides built-in monitoring tools to track pipeline performance, document processing, corpus statistics, and user activity. Access them from the **Monitor** dropdown in the top navigation bar.

---

### Pipeline View

The Pipeline view gives you a high-level overview of your document processing status.

![Pipeline view with Sankey diagram](/docs/images/monitor/pipeline-view.png)

**Key Metrics Cards** — four summary cards at the top show:
- **Total Reports** — total document count in the corpus
- **Indexed Reports** — successfully processed and searchable
- **Agencies** — number of publishing organizations
- **Success Rate** — percentage of documents that made it through the full pipeline

**Sankey Diagram** — the flow chart below shows how documents move through each processing stage: Organizations → Downloaded → Parsed → Summarized → Tagged → Indexed. Error branches (Parse Failed, Summarize Failed, etc.) are shown as side flows so you can quickly spot where documents are dropping out.

Hover over any node or link in the diagram to see detailed counts and tooltips.

---

### Stats View

The Stats view shows interactive bar charts breaking down your document corpus by different attributes.

![Stats view with bar charts](/docs/images/monitor/stats-view.png)

Toggle between seven breakdown views using the buttons at the top:

| View | Shows |
|------|-------|
| **Year** | Documents by publication year |
| **Type** | By document type |
| **Organization** | By publishing organization |
| **Language** | By document language |
| **Format** | By file format |
| **Country** | By country covered |
| **Status** | By processing status (indexed, parsed, error, etc.) |

Each bar is color-coded by processing status. Click any bar to jump to the Documents view pre-filtered to that category.

---

### Processing View

The Processing view shows real-time performance metrics for your pipeline.

![Processing performance charts](/docs/images/monitor/processing-view.png)

Toggle the time range: **Last 24 hours**, **Last 48 hours**, or **All Time**.

Three charts are shown:

1. **Throughput** — dual-axis bar chart showing indexed documents and pages indexed per time bucket
2. **Phase Distribution** — 100% stacked bar chart showing how processing time is split between Parsing, Summarizing, Tagging, and Indexing
3. **Error Chart** — stacked bar chart showing error counts by type (parse failed, summarization failed, indexing failed)

---

### Documents View

The Documents view is a full document library with detailed inspection tools.

![Documents library](/docs/images/monitor/documents-view.png)

Features include:

- **Sortable, filterable table** — columns for title, organization, year, type, status, and more
- **Free-text search** — find documents by title or metadata
- **Column filter popovers** — click any column header to filter by specific values
- **Server-side pagination** — efficiently browse large corpora

Click any document row to access detailed inspection modals:

| Modal | What It Shows |
|-------|---------------|
| **Summary** | AI-generated document summary with approval workflow |
| **TOC** | Table of contents with section classification |
| **Metadata** | Full document metadata including source fields |
| **Processing Timeline** | Stage-by-stage processing history with timestamps |
| **Processing Logs** | Raw processing output and error messages |
| **Chunks** | Vector chunks with PDF viewer overlay |
| **PDF Preview** | Inline PDF viewer |
| **Taxonomy** | AI-assigned taxonomy tags with confidence |
| **Reprocess** | Re-trigger the processing pipeline for this document |

---

### User Activity (Admin)

Administrators can track all search activity from the **Admin Panel → Activity** tab.

![Admin Activity panel](/docs/images/admin/activity-panel.png)

The Activity panel shows:

- **Searchable, sortable table** — columns for Date, User, Query, number of Results, Search time, Summary time, and Heatmap time
- **Filter by user** — narrow down to a specific user's activity
- **Expandable rows** — click any row to see the complete detail:
  - **URL** where the search was performed
  - **Filters applied** — every search parameter the user set
  - **Timing breakdown** — search, summary, and heatmap durations
  - **AI Summary** — the full generated summary with citations
  - **Research Tree** — if the user explored sub-topics, the full drilldown tree is shown
  - **Search Results** — snapshot of the results the user saw
  - **Heatmap Data** — for heatmap searches, the full cell count cross-tabulation
- **Export to Excel** — click **"Download Activity"** to export all activity as an XLSX file

The export includes: Date, User Email, User Name, Query, Results count, Search/Summary/Heatmap timing, AI Summary text, URL, Has Ratings flag, and Search ID.

> **Privacy note:** Activity logging works for both authenticated and anonymous users (anonymous users are tracked by session ID). All activity data is automatically anonymized when a user deletes their account.
