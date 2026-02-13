from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SearchResult(BaseModel):
    id: Optional[str] = None
    chunk_id: str
    doc_id: str
    document_title: Optional[str] = None
    data_source: Optional[str] = None
    text: str
    page_num: int
    chunk_elements: Optional[List[Dict[str, Any]]] = None
    headings: List[str]
    section_type: Optional[str] = None
    score: float
    item_types: Optional[List[str]] = None
    bbox: Optional[List] = None
    elements: Optional[List[Dict[str, Any]]] = None
    table_data: Optional[Dict[str, Any]] = None
    tables: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, Any]]] = None
    title: str
    organization: Optional[str] = None
    year: Optional[str] = None
    file_format: Optional[str] = None
    metadata: Dict[str, Any] = {}
    sys_parsed_folder: Optional[str] = None
    sys_filepath: Optional[str] = None

    class Config:
        extra = "allow"


class ModelConfig(BaseModel):
    name: str
    description: str
    is_default: bool


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total: int
    query: str
    filters: Optional[Dict[str, List[str]]] = None


class FacetValue(BaseModel):
    value: str
    count: int
    organization: Optional[str] = None
    published_year: Optional[str] = None


class Facets(BaseModel):
    facets: Dict[str, List[FacetValue]]
    filter_fields: Dict[str, str]


class HighlightBox(BaseModel):
    page: int
    bbox: Dict[str, float]
    text: str


class HighlightResponse(BaseModel):
    highlights: List[HighlightBox]
    total: int


class HighlightMatch(BaseModel):
    start: int
    end: int
    text: str
    match_type: str
    word: Optional[str] = None
    similarity: Optional[float] = None


class SummaryModelConfig(BaseModel):
    model: str
    max_tokens: int
    temperature: float
    chunk_overlap: int
    chunk_tokens_ratio: float


class UnifiedHighlightRequest(BaseModel):
    query: str
    text: str
    highlight_type: str = "both"
    semantic_threshold: float = 0.4
    min_sentence_length_ratio: float = 1.5
    semantic_model_config: Optional[SummaryModelConfig] = None


class UnifiedHighlightResponse(BaseModel):
    highlighted_text: str
    matches: List[HighlightMatch]
    total: int
    types_returned: List[str]


class AISummaryRequest(BaseModel):
    query: str
    results: List[SearchResult]
    max_results: int = 20
    summary_model: Optional[str] = None
    summary_model_config: Optional[SummaryModelConfig] = None


class TranslateRequest(BaseModel):
    text: str
    target_language: str


class AISummaryResponse(BaseModel):
    summary: str
    query: str
    results_count: int
    prompt: str = ""


class LLMConfig(BaseModel):
    name: str
    model: str
    provider: str
    inference_provider: Optional[str] = None


class ModelComboConfig(BaseModel):
    embedding_model: str
    embedding_model_id: Optional[str] = None
    embedding_model_location: Optional[str] = None
    sparse_model: Optional[str] = None
    sparse_model_location: Optional[str] = None
    summarization_model: SummaryModelConfig
    semantic_highlighting_model: SummaryModelConfig
    reranker_model: str
    summarization_model_location: Optional[str] = None
    semantic_highlighting_location: Optional[str] = None
    reranker_model_location: Optional[str] = None


class TocUpdate(BaseModel):
    toc_classified: str


class DocumentMetadataUpdate(BaseModel):
    toc_approved: Optional[bool] = None
