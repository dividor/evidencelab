"""MCP prompt templates for research workflows."""

from __future__ import annotations


def research_question_prompt(topic: str, data_source: str = "uneg") -> str:
    """Generate a structured research prompt for investigating a topic.

    Creates a prompt that guides the AI assistant to conduct thorough
    research on the given topic across evaluation documents.

    Args:
        topic: The research topic or question to investigate.
        data_source: The document collection to search (default "uneg").

    Returns:
        A formatted prompt string.
    """
    return (
        f"Research the following topic using the {data_source} evaluation "
        f"document collection:\n\n"
        f"Topic: {topic}\n\n"
        f"Recommended workflow:\n"
        f"1. Start with the search tool — run several targeted queries to "
        f"retrieve raw passages. Present the key passages directly so the "
        f"user can read the source evidence themselves.\n"
        f"2. Use get_document on any document IDs worth exploring further "
        f"to retrieve full metadata and context.\n"
        f"3. Only use ask_assistant if the user wants a synthesized narrative "
        f"summary across many documents — it is slower and less transparent "
        f"than working with raw search results.\n\n"
        f"When presenting search results:\n"
        f"- Quote relevant passages directly rather than paraphrasing\n"
        f"- Note patterns, themes, and contradictions you observe across results\n"
        f"- Cite specific documents and sections with inline citations\n"
        f"- Flag any gaps in the evidence base\n\n"
        f"Focus on evaluation-specific evidence: findings, recommendations, "
        f"lessons learned, and conclusions from formal evaluations."
    )


def comparative_analysis_prompt(topic: str, dimension: str = "organization") -> str:
    """Generate a prompt for comparative analysis across a dimension.

    Creates a prompt that guides the AI assistant to compare how
    different entities (organizations, countries, time periods, etc.)
    address a particular topic.

    Args:
        topic: The subject to analyze comparatively.
        dimension: The dimension for comparison — e.g. "organization",
            "country", "time_period", "sector".

    Returns:
        A formatted prompt string.
    """
    return (
        f"Conduct a comparative analysis on the following topic, comparing "
        f"across the dimension of '{dimension}':\n\n"
        f"Topic: {topic}\n\n"
        f"Recommended workflow:\n"
        f"1. Start with the search tool — run separate queries per "
        f"{dimension} (or use the filters parameter) to retrieve raw passages "
        f"for each group. Present the passages so the user can see the "
        f"underlying evidence before any synthesis.\n"
        f"2. Use get_document for any specific documents that look particularly "
        f"relevant.\n"
        f"3. Use ask_assistant only if the user asks for a narrative synthesis "
        f"across all the results — it trades transparency for convenience.\n\n"
        f"When comparing across {dimension}s:\n"
        f"- Show which {dimension}s have the most evidence (document counts)\n"
        f"- Quote key passages directly rather than paraphrasing\n"
        f"- Identify similarities and differences in approaches and findings\n"
        f"- Highlight best practices and common challenges with citations\n"
        f"- Provide a comparative summary table if appropriate\n\n"
        f"Base your analysis on evaluation evidence: formal evaluation "
        f"findings, recommendations, and documented lessons learned."
    )
