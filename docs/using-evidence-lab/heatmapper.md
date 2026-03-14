## Heatmapper

Heatmapper is a visual analysis tool for identifying trends, gaps, and patterns across your document corpus. It generates a color-coded grid showing how documents are distributed across combinations of attributes you define.

![Heatmapper — Document Type × Year Published](/docs/images/heatmapper-overview.png)

### What Can You Visualize?

Think of Heatmapper as a configurable cross-tabulation. You choose what goes on each axis, and the grid shows document counts at each intersection. For example:

- **Document type × Year** — see how the mix of evaluations, reports, and thematic studies has changed over time.
- **AI-generated tag × Organization** — compare thematic coverage across publishing agencies.
- **Search query × Year** — track how frequently specific topics appear in documents over time.

### Heatmapper Modes

Heatmapper operates in two modes depending on whether you include search queries:

![Heatmapper — Search query mode](/docs/images/heatmapper-query-mode.png)

| Mode | When to Use | How It Counts |
|------|-------------|---------------|
| **Search Query Mode** | You provide search queries to filter results | Searches document content and counts unique documents among the top search hits. Best for focused analysis of specific topics. |
| **Document Attribute Mode** | No search queries — just attribute filters | Counts all documents matching the selected attributes. Covers the full corpus and gives the broadest view. |

![Heatmapper grid with data](/docs/images/heatmapper-grid-crop.png)

### Data Drilldown

Click any cell in the heatmap to drill down into the underlying data. You can:

- View individual **documents and paragraphs** that make up that cell's count.
- **Export to Excel** for further offline analysis and reporting.

### Tips

- Start with broad attribute combinations to get an overview, then add search queries to focus on specific topics.
- Use Heatmapper alongside [Search](/docs/using-evidence-lab/search.md) — if you spot an interesting pattern in the heatmap, run a search to explore the underlying evidence.
- Export data for inclusion in presentations or reports.
