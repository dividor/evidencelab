## Ratings & Feedback

Evidence Lab lets you rate AI-generated content and search results using a 1–5 star system. Your feedback helps administrators understand what's working well and where improvements are needed.

> **Note:** Ratings are only available when you're signed in.

---

### What You Can Rate

You can rate five types of content across the application:

| Content | Where to Find It | What You're Rating |
|---------|------------------|--------------------|
| **Search Results** | Star icon on each result card | How relevant is this result to your query? |
| **AI Summaries** | Star icon in the AI Summary footer | How useful and accurate is the generated summary? |
| **Document Summaries** | Star icon in the document summary modal | How well does the AI summary capture the document? |
| **Taxonomy Tags** | Star icon in the taxonomy detail modal | How accurate is this AI-assigned classification? |
| **Heatmaps** | Star icon below the heatmap grid | How useful is this heatmap analysis? |

---

### How to Rate

#### Rating Search Results

Each search result card shows a small star rating in its footer. Click any star to open the rating modal.

![Rating a search result](/docs/images/ratings/search-result-rating.png)

#### Rating AI Summaries

After the AI Summary expands, you'll see a **"Rate"** label with stars at the bottom of the summary. Click to rate.

![Rating an AI summary](/docs/images/ratings/ai-summary-rating.png)

#### Rating Document Summaries

Open any document's AI summary from the Documents view. The rating stars appear at the bottom of the summary modal.

#### Rating Taxonomy Tags

Open a document's taxonomy tags and click into any tag detail. The rating stars are at the bottom of the taxonomy modal.

---

### The Rating Modal

When you click a star, a modal opens where you can:

1. **Choose your score** — click 1 to 5 stars
2. **Add a comment** — optional free-text feedback (up to 2,000 characters)
3. **Submit** — saves your rating

![Rating modal](/docs/images/ratings/rating-modal.png)

If you've already rated something, the modal shows your previous score and comment. You can update your rating at any time, or click **"Remove Rating"** to delete it.

> Each rating is unique per user — you can only have one rating per item. Submitting again updates your existing rating rather than creating a duplicate.

---

### What Gets Captured

Along with your star score and comment, Evidence Lab captures a snapshot of what you were looking at when you rated — the search query, filters, AI summary text, and surrounding results. This rich context helps administrators understand your feedback in full.

---

### Viewing Ratings (Admin)

Administrators can view all user ratings from the **Admin Panel → Ratings** tab.

![Admin Ratings panel](/docs/images/admin/ratings-panel.png)

The Ratings panel provides:

- **Search** — filter by email, reference ID, or comment text
- **Column filters** — filter by Type (search result, AI summary, document summary, taxonomy), Score (1–5), or User
- **Sortable columns** — sort by date, user, type, or score
- **Expandable rows** — click any row to see the full context: the query, AI summary, search results, and timing data that were captured when the rating was given
- **Export to Excel** — click **"Download Ratings"** to export all ratings as an XLSX file

The export includes: Date, User Email, User Name, Type, Score, Reference ID, Item ID, Comment, and URL.
