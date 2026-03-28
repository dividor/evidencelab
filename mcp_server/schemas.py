"""Pydantic output models for MCP tool responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPSearchResult(BaseModel):
    """A single search result chunk returned by the search tool."""

    chunk_id: str = Field(description="Unique identifier for this chunk")
    doc_id: str = Field(description="Parent document identifier")
    text: str = Field(description="Chunk text content")
    page_num: int = Field(description="Page number in the source document")
    headings: List[str] = Field(
        default_factory=list, description="Section headings hierarchy"
    )
    score: float = Field(description="Relevance score (higher is better)")
    title: str = Field(description="Document title")
    organization: Optional[str] = Field(
        default=None, description="Publishing organization"
    )
    year: Optional[str] = Field(default=None, description="Publication year")
    data_source: Optional[str] = Field(
        default=None, description="Data source this result came from"
    )
    section_type: Optional[str] = Field(
        default=None, description="Section type tag (e.g. findings, recommendations)"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional document metadata (country, language, etc.)",
    )


class MCPCitation(BaseModel):
    """A citation linking a search result to its source document."""

    label: str = Field(description="Citation label e.g. '[1]'")
    url: str = Field(description="URL to the source document or evaluation page")
    title: str = Field(description="Formatted citation title with org and year")
    organization: Optional[str] = Field(
        default=None, description="Publishing organization"
    )
    year: Optional[str] = Field(default=None, description="Publication year")


class MCPSearchResponse(BaseModel):
    """Response from the Evidence Lab search tool."""

    total: int = Field(description="Total number of results returned")
    query: str = Field(description="Original search query")
    summary: str = Field(
        default="",
        description="Human-readable summary of results count and citations available",
    )
    results: List[MCPSearchResult] = Field(description="List of matching chunks")
    citations: List[MCPCitation] = Field(
        default_factory=list,
        description="Numbered citations for each result with clickable URLs",
    )
    references: List[str] = Field(
        default_factory=list,
        description="Pre-formatted markdown references for easy copying into responses",
    )
    citation_guidance: str = Field(
        default="",
        description="Instructions for how to use citations in responses",
    )
    data_source: Optional[str] = Field(
        default=None, description="Data source that was searched"
    )
    facets: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        default=None,
        description=(
            "Available filter values with counts, keyed by field name. "
            "Only present when include_facets=True. Each entry is a list "
            "of {value, count} objects sorted by count descending."
        ),
    )


class MCPDocumentResponse(BaseModel):
    """Response from the document retrieval tool."""

    doc_id: str = Field(description="Document identifier")
    title: str = Field(description="Document title")
    organization: Optional[str] = Field(
        default=None, description="Publishing organization"
    )
    year: Optional[str] = Field(default=None, description="Publication year")
    abstract: Optional[str] = Field(default=None, description="Document abstract")
    summary: Optional[str] = Field(
        default=None, description="AI-generated document summary"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Full document metadata"
    )


class MCPAssistantResponse(BaseModel):
    """Response from the AI research assistant tool."""

    answer: str = Field(description="Synthesized answer from the research assistant")
    sources: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Source documents referenced in the answer",
    )
    citations: List[MCPCitation] = Field(
        default_factory=list,
        description="Numbered citations for each source with clickable URLs",
    )
    references: List[str] = Field(
        default_factory=list,
        description="Pre-formatted markdown references for easy copying into responses",
    )
    citation_guidance: str = Field(
        default="",
        description="Instructions for how to use citations in responses",
    )
    query: str = Field(description="Original query")
    data_source: Optional[str] = Field(
        default=None, description="Data source that was searched"
    )
