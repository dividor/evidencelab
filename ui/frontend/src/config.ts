import config from './config.json';

// Use same-origin API path to avoid local network prompts.
// Allow override via build-time env for multi-route deployments.
const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || '/api';

const normalizeBasePath = (rawPath?: string): string => {
  if (!rawPath) return '';
  const trimmed = rawPath.trim();
  if (!trimmed || trimmed === '/') return '';
  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  return withLeadingSlash.replace(/\/+$/, '');
};

// Base path for deployments behind a URL prefix (e.g., /evidencelab)
export const APP_BASE_PATH = normalizeBasePath(process.env.REACT_APP_BASE_PATH);

// PDF semantic highlighting feature flag (defaults to false)
export const PDF_SEMANTIC_HIGHLIGHTS = config.application.features.pdf_highlights;

// Search results semantic highlighting feature flag (defaults to false)
// When true, uses semantic matching API to highlight similar phrases in search results
export const SEARCH_SEMANTIC_HIGHLIGHTS = config.application.features.semantic_highlights;

// Semantic highlighting threshold (0.0 to 1.0, higher = more strict)
// Default 0.4 = 40% similarity required for highlighting
export const SEMANTIC_HIGHLIGHT_THRESHOLD = config.application.search.highlight_threshold;

// In-doc PDF search relevance cutoff. Chunks with retrieval score below this
// value are dropped from in-doc search results UNLESS they contain the query
// as a verbatim substring (those exact-match chunks are always kept).
// Tune per ranker — typical values 0.3–0.5 for the WFP Vertex/Gemini stack.
// Default 0.4 if env var unset.
const _PDF_SEARCH_SEMANTIC_CUTOFF_RAW = parseFloat(
  process.env.REACT_APP_PDF_SEARCH_SEMANTIC_CUTOFF || '0.4'
);
export const PDF_SEARCH_SEMANTIC_CUTOFF: number = Number.isFinite(
  _PDF_SEARCH_SEMANTIC_CUTOFF_RAW
)
  ? _PDF_SEARCH_SEMANTIC_CUTOFF_RAW
  : 0.4;

// AI Summary feature flag (defaults to false)
export const AI_SUMMARY_ON = config.application.ai_summary.enabled;

// Research Assistant feature flag (defaults to false)
export const ASSISTANT_ENABLED = (config.application as any).assistant?.enabled ?? false;

// Research Assistant config
export const ASSISTANT_MAX_SEARCH_RESULTS = (config.application as any).assistant?.max_search_results ?? 20;
export const ASSISTANT_MAX_ITERATIONS = (config.application as any).assistant?.max_iterations ?? 3;

// Search results page size (defaults to 50)
export const SEARCH_RESULTS_PAGE_SIZE = String(config.application.search.page_size);

// Heatmap per-cell result limit (defaults to 1000)
export const HEATMAP_CELL_LIMIT = process.env.REACT_APP_HEATMAP_LIMIT || '1000';

// User feedback mode — enables document reprocessing and TOC editing controls
// Set REACT_APP_USER_FEEDBACK=1 in .env to enable (default: off)
export const USER_FEEDBACK = process.env.REACT_APP_USER_FEEDBACK === '1';

// Google Analytics Measurement ID (optional, set via REACT_APP_GA_MEASUREMENT_ID)
export const GA_MEASUREMENT_ID: string | undefined =
  process.env.REACT_APP_GA_MEASUREMENT_ID || undefined;

// User module — enables authentication, user profiles, and permissions
// Modes: off | on_passive | on_active
//   off        — no auth UI
//   on_passive — auth UI available, login optional (anonymous access allowed)
//   on_active  — auth UI required, all access requires login
// Backwards compatible: 'true' → on_active, 'false'/unset → off
const _USER_MODULE_RAW = (process.env.REACT_APP_USER_MODULE || 'off').toLowerCase();
export type UserModuleMode = 'off' | 'on_passive' | 'on_active';
export const USER_MODULE_MODE: UserModuleMode =
  _USER_MODULE_RAW === 'true' || _USER_MODULE_RAW === 'on_active'
    ? 'on_active'
    : _USER_MODULE_RAW === 'on_passive'
      ? 'on_passive'
      : 'off';
// Auth module is enabled (true for both on_passive and on_active)
export const USER_MODULE = USER_MODULE_MODE !== 'off';

// API key for authenticating UI requests to the backend.
// Set via REACT_APP_API_KEY in .env — required for the app to function.
export const API_KEY: string | undefined =
  process.env.REACT_APP_API_KEY || undefined;

export default API_BASE_URL;
