## Using Evidence Lab

Now that you have Docker running (`docker compose up -d --build`), open your browser and navigate to:

**[http://localhost:3000](http://localhost:3000)**

This is the Evidence Lab user interface. From here you can search your document corpus, build research trees, create heatmap visualizations, and rate AI-generated content.

Use the navigation bar at the top to switch between the main features:

- **Search** — find documents using natural language queries with AI-powered summaries
- **Heatmapper** — visualize document distribution across attributes
- **Research Trees** — drill down into topics with structured, multi-level research
- **Research Assistant** — chat-based AI agent that searches, analyzes, and synthesizes findings with inline citations, multi-turn conversations, and an optional Deep Research mode for thorough investigations
- **Brief** — turn a topic into a structured research brief: generate a grounded outline, edit and reorder headings, research each one into cited text with AI, and export to Word
- **Monitor** — track pipeline performance and corpus statistics (admin)

The guides in this section walk you through each feature in detail.

### Your environmental impact

When signed in, click your user icon and choose **Environmental impact**. Select **Last 30 days** or **Year to date** to see ranges for your estimated energy use, greenhouse gas emissions and water use. Both periods include today and use UTC. Year to date starts on January 1.

We use [EcoLogits](https://ecologits.ai/latest/) to estimate the impact of text AI writes for your account. The figures leave out automatic document processing and the work of finding and sorting search results. The summary tells you how much AI-written text has no estimate, counted in tokens. A token is a small piece of text, like a word or part of a word. Administrators can control access to the summary in [Group Settings](../admin/user-administration.md#features--tabs).
