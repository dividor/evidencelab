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
        f"Please:\n"
        f"1. Search for relevant evaluation findings and evidence\n"
        f"2. Identify key patterns, themes, and conclusions across documents\n"
        f"3. Note any contradictions or gaps in the evidence\n"
        f"4. Cite specific documents and sections that support your analysis\n"
        f"5. Provide a synthesis with actionable insights\n\n"
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
        f"Please:\n"
        f"1. Search for evidence related to this topic from multiple {dimension}s\n"
        f"2. Identify similarities and differences in approaches and findings\n"
        f"3. Highlight best practices and common challenges\n"
        f"4. Note which {dimension}s have the strongest evidence base\n"
        f"5. Provide a comparative summary table if appropriate\n\n"
        f"Base your analysis on evaluation evidence: formal evaluation "
        f"findings, recommendations, and documented lessons learned."
    )
