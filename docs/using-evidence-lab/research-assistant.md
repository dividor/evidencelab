## Research Assistant

The Research Assistant is an AI-powered chat interface that answers questions about your document collection by searching, analyzing, and synthesizing evidence with full citations.

![Research Assistant](../images/assistant/assistant-response.png)

### Getting Started

1. Click the **Assistant** tab in the top navigation
2. Type a research question in the input box, or click one of the suggested example queries
3. The assistant will search your documents, then stream a structured response with inline citations

Each response includes:
- **Structured sections** with headings that organize the findings
- **Inline citation numbers** (e.g., 1 7 19) that reference specific document chunks
- **An expandable References section** listing all cited documents with titles and page numbers
- **A star rating** so you can provide feedback on response quality

### Normal Mode

The Assistant first searches with your original question. It can use up to four searches
for a focused question. If a question asks about different outcomes or comparisons, the
Assistant can plan up to four research streams, one for each part of the question. Each
stream starts with a focused search and can search again to fill a gap in its own results.

The Assistant combines the evidence into one answer. Expand the search list to see which
stream each query belonged to and why the Assistant searched again.

### Deep Research Mode

For questions that need more investigation, enable **Deep Research** with the checkbox
below the chat input.

![Deep Research checkbox](../images/assistant/deep-research-checkbox.png)

Deep Research can use up to ten searches for a focused question. For a question with
multiple streams, it can run up to four searches per stream after the original search.
The normal Assistant can run up to two per stream. Deep Research looks for evidence from
independent evaluations and investigates disagreements and limitations. Each stream can
finish early when its results are sufficient.

### Multi-Turn Conversations

The assistant supports follow-up questions within the same conversation. Each message maintains the context of the previous exchange, allowing you to:

- Ask clarifying questions about a previous response
- Request the assistant to dig deeper into a specific finding
- Refine your research direction based on initial results

### Chat History

Authenticated users have access to chat history features:

- **Thread sidebar** — click the clock icon next to the input to open a sidebar showing past conversations
- **Thread persistence** — conversations are automatically saved as threads
- **Rename threads** — click the pencil icon on any thread to give it a descriptive name
- **Resume conversations** — click a thread to reload its messages and continue the conversation
- **New chat** — click "+ New chat" to start a fresh conversation

### Search Settings

The assistant respects the same search settings available in the Search tab. This includes:

- **Dense/sparse weights** — adjust the balance between semantic and keyword search
- **Reranking model** — choose which reranking model scores the results
- **Recency boost** — prioritize newer documents
- **Field boost** — boost results matching detected field values (e.g., country names)
- **Wide Search** — each of the assistant's searches spreads across documents (at most *Max results per document* from any one document). The assistant reads 20 results per search, so with Wide Search on it takes the best excerpt from each document first, giving it broader coverage of the library instead of many excerpts from one report.

These settings are configured via the Search Settings panel and automatically forwarded to the assistant's search tool.
