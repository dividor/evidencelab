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

// AI Summary feature flag (defaults to false)
export const AI_SUMMARY_ON = config.application.ai_summary.enabled;

// Search results page size (defaults to 50)
export const SEARCH_RESULTS_PAGE_SIZE = String(config.application.search.page_size);

// Heatmap per-cell result limit (defaults to 1000)
export const HEATMAP_CELL_LIMIT = process.env.REACT_APP_HEATMAP_LIMIT || '1000';

// Google Analytics Measurement ID (optional, set via REACT_APP_GA_MEASUREMENT_ID)
export const GA_MEASUREMENT_ID: string | undefined =
  process.env.REACT_APP_GA_MEASUREMENT_ID || undefined;

export default API_BASE_URL;
