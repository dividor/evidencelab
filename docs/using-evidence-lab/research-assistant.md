## Research Assistant

The Research Assistant is an AI-powered chat interface that answers questions about your document collection by searching, analyzing, and synthesizing evidence with full citations.

![Research Assistant](/docs/images/assistant/assistant-response.png)

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

In normal mode, the assistant uses a single AI agent that iterates through a plan-search-synthesize loop. It typically performs 2-5 searches to gather evidence before writing a response. This mode is fast and suitable for most research questions.

The assistant will:
1. Plan a set of search queries based on your question
2. Execute each search against your document collection using hybrid retrieval
3. Analyze the results and synthesize a cited response
4. Show the number of searches performed and total results found (e.g., "4 searches · 70 results")

### Deep Research Mode

For more complex questions that require broader investigation, enable **Deep Research** by checking the checkbox below the chat input.

![Deep Research checkbox](/docs/images/assistant/deep-research-checkbox.png)

Deep Research uses a coordinator/researcher sub-agent architecture:

- A **coordinator agent** plans the investigation and breaks it into focused research tasks
- **Researcher sub-agents** execute specific search tasks independently
- The coordinator synthesizes the sub-agent findings into a comprehensive response

This mode performs more searches (up to 12 vs 6 in normal mode) and can investigate multiple aspects of a question in parallel, producing more thorough and detailed responses.

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

These settings are configured via the Search Settings panel and automatically forwarded to the assistant's search tool.

### Tips for Better Results

- **Be specific** — instead of "Tell me about climate change," try "How has climate change affected food production in East Africa according to evaluation reports?"
- **Use Deep Research for complex topics** — if your question spans multiple themes or requires evidence from many documents, Deep Research will produce more comprehensive results
- **Follow up** — if the initial response misses an angle, ask a follow-up question to steer the research
- **Check the citations** — click on citation numbers to verify the source material and read the original context
