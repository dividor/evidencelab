# About Evidence Lab

Evidence lab is a free open source prototyping platform that provides a document pipeline, search, and AI-powered information discovery tools. The aim is to provide a quick start for those looking to use AI with their documents and a place where new ideas can be tested.

You can run the code yourself, or explore the online version at [evidencelab.ai](https://evidencelab.ai) which has so far been populated with 20,000 United Nations humanitarian evaluation reports sourced from the [United Nations Evaluation Group](https://www.un.org/evaluations) and 8,000 reports related to Fraud and Program Integrity as sourced from [The World Bank](https://www.worldbank.org/ext/en/home). See [Data](/data) for more information on these amazing documents.

If you would like to have your public documents added to Evidence Lab, or would like to contribute to the project, please reach out to [evidence-lab@astrobagel.com](mailto:evidence-lab@astrobagel.com).

Also, for the latest news check out the [AstroBagel Blog](https://medium.com/@astrobagel).

## Philosophy

Evidence Lab grew out of research work for the AstroBagel Blog. The core design principles are:

- **Runs on a desktop** — the full pipeline can process 20,000 30-page documents in a week for less than $50
- **Configurable** — point it at a folder of PDFs and configure via a single config.json
- **Progressive complexity** — start with simple parsing and layer on richer features (image annotation, reranking) later without re-processing
- **Model-agnostic** — supports both open-source and proprietary embedding and LLM models
- **Observable** — built-in tools for monitoring pipeline progress and exploring AI retrieval quality

Some lofty, often conflicting, goals! Always a work in progress, and low-cost high-speed processing which runs on a desktop computer, does come with a few shortcuts. To run on a modest server, the user interface might not be the fastest out there (but can be if you add more processing power), and in not using expensive LLMs for parsing (only cheap ones!), the ingestion had to be tuned to the document data styles. That said, the design has tried to allow for future improvements.

## Features

Evidence lab document processing pipeline includes the following features:

### Processing pipeline

- PDF/Word parsing with Docling, to include document structure detection
- Footnote and references, images and table detection
- Basic table extraction, with support for more expensive processing as required
- AI-assisted document summarization
- AI-assisted tagging of documents
- Indexing with Open (Huggingface) or proprietary models (Azure foundry, but extensible)

### User interface

- Hybrid search with AI summary and reranking
- Experimental features such as heatmapper to tracking trends in content
- Filtering by metadata, in-document section types
- Search and reranking settings to explore different models
- Auto min score filtering using percentile-based thresholding (filters bottom 30% of results)
- Semantic highlighting in search results
- Basic language translation
- PDF preview with in-document search
- Administration views to track pipeline, documents, performance and errors

More features will be added soon, focused on document evidence analysis.
