"""
Search API Backend
FastAPI server that provides semantic search over indexed documents in Qdrant.
"""

import os
import secrets
import signal
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from pipeline.db import (
    DB_VECTORS,
    DENSE_VECTOR_NAME,
    SUPPORTED_LLMS,
    SUPPORTED_RERANK_MODELS,
    UI_MODEL_COMBOS,
    get_filter_fields,
)
from pipeline.utilities.tasks import app as celery_app
from ui.backend.routes import config as config_routes
from ui.backend.routes import documents as documents_routes
from ui.backend.routes import highlight as highlight_routes
from ui.backend.routes import search as search_routes
from ui.backend.routes import stats as stats_routes
from ui.backend.routes import summary as summary_routes
from ui.backend.routes.documents import get_document as _get_document
from ui.backend.routes.documents import get_document_chunks as _get_document_chunks
from ui.backend.routes.documents import get_document_logs as _get_document_logs
from ui.backend.routes.documents import get_documents as _get_documents
from ui.backend.routes.documents import get_queue_status as _get_queue_status
from ui.backend.routes.documents import reprocess_document as _reprocess_document
from ui.backend.routes.documents import (
    reprocess_document_toc as _reprocess_document_toc,
)
from ui.backend.routes.documents import serve_file as _serve_file
from ui.backend.routes.documents import serve_pdf as _serve_pdf
from ui.backend.routes.documents import (
    update_document_metadata as _update_document_metadata,
)
from ui.backend.routes.documents import update_document_toc as _update_document_toc
from ui.backend.routes.search import get_facets as _get_facets
from ui.backend.routes.search import perform_title_search as _perform_title_search
from ui.backend.routes.search import search as _search
from ui.backend.routes.search import (
    search_facet_values_endpoint as _search_facet_values_endpoint,
)
from ui.backend.routes.stats import get_stats as _get_stats
from ui.backend.schemas import DocumentMetadataUpdate, TocUpdate
from ui.backend.services.search import (
    RERANK_MODEL,
    get_models,
    get_rerank_model,
    search_chunks,
    search_facet_values,
    search_titles,
)
from ui.backend.utils.app_limits import get_rate_limits, limiter
from ui.backend.utils.app_state import get_db_for_source, get_pg_for_source, logger

# Add parent directory to path for imports


def _log_signal(signum, _frame) -> None:
    logger.warning("Received signal %s", signum)


signal.signal(signal.SIGTERM, _log_signal)
signal.signal(signal.SIGINT, _log_signal)

# Rate limiting configuration (from environment or defaults)
RATE_LIMIT_SEARCH, RATE_LIMIT_DEFAULT, RATE_LIMIT_AI = get_rate_limits()
MAX_CONCURRENT_SEARCHES = int(os.environ.get("MAX_CONCURRENT_SEARCHES", "2"))
PRELOAD_EMBEDDING_MODELS = os.environ.get(
    "PRELOAD_EMBEDDING_MODELS", "true"
).lower() in (
    "1",
    "true",
    "yes",
)
USE_EMBEDDING_SERVER = os.environ.get("USE_EMBEDDING_SERVER", "false").lower() in (
    "1",
    "true",
    "yes",
)

# API Key Authentication
API_KEY = os.environ.get("API_SECRET_KEY")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(request: Request, api_key: str = Depends(api_key_header)):
    """Verify the API key from request header"""
    if request.url.path == "/health":
        return None
    if request.url.path.startswith("/file/") or request.url.path.startswith("/pdf/"):
        return None
    if "/thumbnail" in request.url.path:
        return None
    if not API_KEY:
        # If no API key configured, allow all requests (development mode)
        return None
    if not api_key or not secrets.compare_digest(api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


# Disable docs in production (when API_KEY is set)
app = FastAPI(
    title="Humanitarian Evaluation Search API",
    dependencies=[Depends(verify_api_key)],
    docs_url=None if API_KEY else "/docs",
    redoc_url=None if API_KEY else "/redoc",
    openapi_url=None if API_KEY else "/openapi.json",
)

# Add rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.highlight_cache = highlight_routes._highlight_cache


# Custom exception handler for validation errors (e.g., invalid data_source)
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Convert ValueError to HTTP 400 Bad Request."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.on_event("startup")
async def startup_event():
    """Preload embedding models and pipeline data on API startup."""
    logger.info("API startup (pid=%s)", os.getpid())
    logger.info("Max concurrent searches: %s", MAX_CONCURRENT_SEARCHES)
    if not PRELOAD_EMBEDDING_MODELS:
        logger.info("⏩ Skipping model preload (PRELOAD_EMBEDDING_MODELS=false)")
    elif USE_EMBEDDING_SERVER:
        logger.info("⏩ Skipping embedding model preload (USE_EMBEDDING_SERVER=true)")
    else:
        logger.info("🚀 API starting up - preloading embedding models...")
        get_models()  # This will load and cache the models
        logger.info("✅ Embedding models preloaded and ready")
    # Preload reranker model if configured
    if RERANK_MODEL:
        logger.info("🔄 Preloading reranker model...")
        get_rerank_model()
        logger.info("✅ Reranker model preloaded and ready")
    # Warm pipeline data cache in background thread
    import threading

    threading.Thread(
        target=stats_routes.warm_pipeline_cache, args=("uneg",), daemon=True
    ).start()


@app.on_event("shutdown")
async def shutdown_event():
    logger.warning("API shutdown (pid=%s)", os.getpid())


def root(request: Request):
    return config_routes.root(request)


def health():
    return config_routes.health()


async def get_datasources_config():
    return await config_routes.get_datasources_config()


async def generate_summary(request: Request, body):
    return await summary_routes.generate_summary(request, body)


async def stream_summary(request: Request, body):
    return await summary_routes.stream_summary(request, body)


async def translate(request: Request, body):
    return await summary_routes.translate(request, body)


def infer_paragraphs_from_bboxes(text: str, bboxes: List[tuple]) -> str:
    return highlight_routes.infer_paragraphs_from_bboxes(text, bboxes)


def find_semantic_matches_sync(
    phrases: List[str],
    clean_text: str,
    original_text: str,
    index_map: List[int],
):
    return highlight_routes.find_semantic_matches_sync(
        phrases=phrases,
        clean_text=clean_text,
        original_text=original_text,
        index_map=index_map,
    )


async def highlight_text(request):
    return await highlight_routes.highlight_text(request)


def get_config_models():
    config_routes.DB_VECTORS = DB_VECTORS
    config_routes.DENSE_VECTOR_NAME = DENSE_VECTOR_NAME
    return config_routes.get_config_models()


def get_config_llms():
    config_routes.SUPPORTED_LLMS = SUPPORTED_LLMS
    return config_routes.get_config_llms()


def get_config_model_combos():
    config_routes.DB_VECTORS = DB_VECTORS
    config_routes.UI_MODEL_COMBOS = UI_MODEL_COMBOS
    config_routes.SUPPORTED_RERANK_MODELS = SUPPORTED_RERANK_MODELS
    config_routes.SUPPORTED_LLMS = SUPPORTED_LLMS
    return config_routes.get_config_model_combos()


def get_stats(
    data_source: Optional[str] = None,
):
    stats_routes.get_db_for_source = get_db_for_source
    stats_routes.get_pg_for_source = get_pg_for_source
    return _get_stats(data_source=data_source)


async def get_documents(
    organization: Optional[str] = None,
    document_type: Optional[str] = None,
    published_year: Optional[str] = None,
    language: Optional[str] = None,
    file_format: Optional[str] = None,
    status: Optional[str] = None,
    title: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    data_source: Optional[str] = None,
    target_language: Optional[str] = None,
    toc_approved: Optional[bool] = None,
    sdg: Optional[str] = None,
    cross_cutting_theme: Optional[str] = None,
    sort_by: str = "year",
    order: str = "desc",
):
    documents_routes.get_db_for_source = get_db_for_source
    documents_routes.get_pg_for_source = get_pg_for_source
    return await _get_documents(
        organization=organization,
        document_type=document_type,
        published_year=published_year,
        language=language,
        file_format=file_format,
        status=status,
        title=title,
        search=search,
        page=page,
        page_size=page_size,
        data_source=data_source,
        target_language=target_language,
        toc_approved=toc_approved,
        sdg=sdg,
        cross_cutting_theme=cross_cutting_theme,
        sort_by=sort_by,
        order=order,
    )


async def perform_title_search(
    request: Request,
    q: str,
    limit: int = 50,
    dense_weight: Optional[float] = None,
    data_source: Optional[str] = "uneg",
    model: Optional[str] = None,
    organization: Optional[str] = None,
    published_year: Optional[str] = None,
    country: Optional[str] = None,
):
    search_routes.get_db_for_source = get_db_for_source
    search_routes.search_titles = search_titles
    return await _perform_title_search(
        request=request,
        q=q,
        limit=limit,
        dense_weight=dense_weight,
        data_source=data_source,
        model=model,
        organization=organization,
        published_year=published_year,
        country=country,
    )


async def search(
    request: Request,
    q: str,
    limit: int = 50,
    organization: Optional[str] = None,
    title: Optional[str] = None,
    published_year: Optional[str] = None,
    document_type: Optional[str] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    dense_weight: Optional[float] = None,
    rerank: bool = False,
    recency_boost: bool = False,
    recency_weight: float = 0.15,
    recency_scale_days: int = 365,
    section_types: Optional[str] = None,
    keyword_boost_short_queries: bool = True,
    data_source: Optional[str] = None,
    min_chunk_size: int = 0,
    model: Optional[str] = None,
    rerank_model: Optional[str] = None,
    rerank_model_page_size: Optional[int] = None,
    auto_min_score: bool = False,
    deduplicate: bool = True,
    field_boost: bool = True,
    field_boost_fields: Optional[str] = None,
):
    search_routes.get_db_for_source = get_db_for_source
    search_routes.get_pg_for_source = get_pg_for_source
    search_routes.search_chunks = search_chunks
    return await _search(
        request=request,
        q=q,
        limit=limit,
        organization=organization,
        title=title,
        published_year=published_year,
        document_type=document_type,
        country=country,
        language=language,
        dense_weight=dense_weight,
        rerank=rerank,
        recency_boost=recency_boost,
        recency_weight=recency_weight,
        recency_scale_days=recency_scale_days,
        section_types=section_types,
        keyword_boost_short_queries=keyword_boost_short_queries,
        data_source=data_source,
        min_chunk_size=min_chunk_size,
        model=model,
        rerank_model=rerank_model,
        rerank_model_page_size=rerank_model_page_size,
        auto_min_score=auto_min_score,
        deduplicate=deduplicate,
        field_boost=field_boost,
        field_boost_fields=field_boost_fields,
    )


async def search_facet_values_endpoint(
    request: Request,
    field: str,
    q: str,
    limit: int = 100,
    data_source: Optional[str] = None,
    dense_weight: Optional[float] = None,
):
    search_routes.get_db_for_source = get_db_for_source
    search_routes.search_facet_values = search_facet_values
    return await _search_facet_values_endpoint(
        request=request,
        field=field,
        q=q,
        limit=limit,
        data_source=data_source,
        dense_weight=dense_weight,
    )


async def get_facets(
    request: Request,
    organization: Optional[str] = None,
    title: Optional[str] = None,
    published_year: Optional[str] = None,
    document_type: Optional[str] = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    data_source: Optional[str] = None,
    q: Optional[str] = None,
):
    search_routes.get_db_for_source = get_db_for_source
    search_routes.get_filter_fields = get_filter_fields
    return await _get_facets(
        request=request,
        organization=organization,
        title=title,
        published_year=published_year,
        document_type=document_type,
        country=country,
        language=language,
        data_source=data_source,
        q=q,
    )


async def get_document(doc_id: str, data_source: Optional[str] = None):
    documents_routes.get_db_for_source = get_db_for_source
    documents_routes.get_pg_for_source = get_pg_for_source
    return await _get_document(doc_id=doc_id, data_source=data_source)


async def get_document_logs(doc_id: str, data_source: Optional[str] = None):
    documents_routes.get_db_for_source = get_db_for_source
    return await _get_document_logs(doc_id=doc_id, data_source=data_source)


async def update_document_toc(
    doc_id: str, body: TocUpdate, data_source: Optional[str] = None
):
    documents_routes.get_db_for_source = get_db_for_source
    return await _update_document_toc(
        doc_id=doc_id, toc_update=body, data_source=data_source
    )


async def update_document_metadata(
    doc_id: str, body: DocumentMetadataUpdate, data_source: Optional[str] = None
):
    documents_routes.get_db_for_source = get_db_for_source
    documents_routes.get_pg_for_source = get_pg_for_source
    return await _update_document_metadata(
        doc_id=doc_id, update=body, data_source=data_source
    )


async def get_document_chunks(
    doc_id: str,
    data_source: Optional[str] = None,
    target_language: Optional[str] = None,
):
    documents_routes.get_db_for_source = get_db_for_source
    documents_routes.get_pg_for_source = get_pg_for_source
    return await _get_document_chunks(
        doc_id=doc_id, data_source=data_source, target_language=target_language
    )


async def get_queue_status():
    documents_routes.get_db_for_source = get_db_for_source
    documents_routes.celery_app = celery_app
    return await _get_queue_status()


async def reprocess_document(doc_id: str, data_source: Optional[str] = None):
    documents_routes.get_db_for_source = get_db_for_source
    return await _reprocess_document(doc_id=doc_id, data_source=data_source)


async def reprocess_document_toc(doc_id: str, data_source: Optional[str] = None):
    documents_routes.get_db_for_source = get_db_for_source
    return await _reprocess_document_toc(doc_id=doc_id, data_source=data_source)


async def serve_pdf(doc_id: str, data_source: Optional[str] = None):
    documents_routes.get_db_for_source = get_db_for_source
    return await _serve_pdf(doc_id=doc_id, data_source=data_source)


async def serve_file(file_path: str):
    return await _serve_file(file_path=file_path)


async def get_chunk_highlights(chunk_id: str, data_source: Optional[str] = None):
    highlight_routes.get_db_for_source = get_db_for_source
    highlight_routes.get_pg_for_source = get_pg_for_source
    return await highlight_routes.get_chunk_highlights(
        chunk_id=chunk_id, data_source=data_source
    )


async def get_highlights(
    doc_id: str,
    page: Optional[int] = None,
    text: Optional[str] = None,
    data_source: Optional[str] = None,
):
    highlight_routes.get_db_for_source = get_db_for_source
    highlight_routes.get_pg_for_source = get_pg_for_source
    return await highlight_routes.get_highlights(
        doc_id=doc_id, page=page, text=text, data_source=data_source
    )


# CORS configuration - read allowed origins from environment
CORS_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
if not CORS_ORIGINS or CORS_ORIGINS == [""]:
    # Development fallback - localhost only
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Models
class SearchResult(BaseModel):
    id: Optional[str] = None  # Chunk ID (for UI compatibility)
    chunk_id: str
    doc_id: str
    document_title: Optional[str] = None  # Document title (for UI compatibility)
    data_source: Optional[str] = None  # Data source (for UI filtering)
    text: str
    page_num: int
    chunk_elements: Optional[List[Dict[str, Any]]] = (
        None  # Unified array with all elements (text, images, tables)
    )
    headings: List[str]
    section_type: Optional[str] = None
    score: float
    # Visual content metadata
    item_types: Optional[List[str]] = None  # e.g., ['TableItem', 'PictureItem']
    # Backward compatibility fields
    bbox: Optional[List] = None  # Legacy field
    elements: Optional[List[Dict[str, Any]]] = None  # Legacy field
    table_data: Optional[Dict[str, Any]] = None  # Legacy field
    tables: Optional[List[Dict[str, Any]]] = None  # Legacy field
    images: Optional[List[Dict[str, Any]]] = None  # Legacy field
    # Core fields for backward compatibility
    title: str
    organization: Optional[str] = None
    year: Optional[str] = None
    file_format: Optional[str] = None
    # ALL document metadata as flexible JSON - any field can appear here
    metadata: Dict[str, Any] = {}
    sys_parsed_folder: Optional[str] = None
    sys_filepath: Optional[str] = None
    sys_full_summary: Optional[str] = None

    class Config:
        extra = "allow"  # Allow additional fields not explicitly defined


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
    organization: Optional[str] = None  # For title facets - associated org
    published_year: Optional[str] = None  # For title facets - associated year


class Facets(BaseModel):
    """Dynamic facets response using core field names."""

    facets: Dict[str, List[FacetValue]]  # core_field_name -> list of facet values
    filter_fields: Dict[str, str]  # core_field_name -> display label (from config)


class HighlightBox(BaseModel):
    page: int
    bbox: Dict[str, float]  # {l, r, t, b}
    text: str


class HighlightResponse(BaseModel):
    highlights: List[HighlightBox]
    total: int


class HighlightMatch(BaseModel):
    start: int
    end: int
    text: str
    match_type: str  # "exact_phrase", "word", "semantic"
    word: Optional[str] = None  # For word matches
    similarity: Optional[float] = None  # For semantic matches


class SummaryModelConfig(BaseModel):
    model: str
    max_tokens: int
    temperature: float
    chunk_overlap: int
    chunk_tokens_ratio: float


class UnifiedHighlightRequest(BaseModel):
    query: str
    text: str
    highlight_type: str = "both"  # "keyword", "semantic", or "both"
    semantic_threshold: float = 0.4
    min_sentence_length_ratio: float = 1.5
    semantic_model_config: Optional[SummaryModelConfig] = None


class UnifiedHighlightResponse(BaseModel):
    highlighted_text: str  # Text with <em> tags inserted
    matches: List[HighlightMatch]  # For backward compatibility
    total: int
    types_returned: List[str]  # Which types were actually returned


class AISummaryRequest(BaseModel):
    query: str
    results: List[SearchResult]
    max_results: int = 20
    summary_model: Optional[str] = None
    summary_model_config: Optional[SummaryModelConfig] = None


class TranslateRequest(BaseModel):
    text: str
    target_language: str
    source_language: Optional[str] = None


class AISummaryResponse(BaseModel):
    summary: str
    query: str
    results_count: int
    prompt: str = ""


app.include_router(config_routes.router)
app.include_router(summary_routes.router)
app.include_router(highlight_routes.router)
app.include_router(stats_routes.router)
app.include_router(search_routes.router)
app.include_router(documents_routes.router)

if __name__ == "__main__":
    # Host configurable for security - 0.0.0.0 for Docker, 127.0.0.1 for local dev
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
