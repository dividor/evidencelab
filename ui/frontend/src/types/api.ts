export interface TableCell {
  text: string;
  is_header?: boolean;
  col_span?: number;
  row_span?: number;
}

export interface TableData {
  num_rows: number;
  num_cols: number;
  rows: TableCell[][];
  page?: number;
  bbox?: number[];
  position_hint?: number;
  image_path?: string;
  image_size?: number[];
}

export interface ImageData {
  path: string;
  page?: number;
  bbox?: number[];
  position_hint?: number;
}

export interface ElementData {
  type: string;  // e.g., "TextItem", "picture", "TableItem"
  label: string; // e.g., "section_header", "text", "picture"
  text: string;  // Text content (for TextItem)
  page: number;
  bbox: number[];
  position_hint: number;
}

// Unified element in a chunk - can be text, image, or table
// All elements are sorted by document order (page, then position_hint)
export interface ChunkElement {
  element_type: 'text' | 'image' | 'table';
  key?: string;
  // Text element fields
  text?: string;  // Actual text content for text elements
  label?: string;
  is_reference?: boolean; // True if this is a footnote/endnote
  inline_references?: Array<{  // Inline reference markers within text
    number: number;
    position: number;
    pattern: string;
  }>;
  // Image element fields
  path?: string;
  // Table element fields
  num_rows?: number;
  num_cols?: number;
  rows?: TableCell[][];
  image_path?: string;
  image_size?: number[];
  // Common fields for all elements
  page: number;
  bbox?: number[];
  position_hint: number;
}

export interface SearchResult {
  chunk_id: string;
  doc_id: string;
  text: string;
  page_num: number;
  chunk_elements?: ChunkElement[]; // Unified array with all elements (text, images, tables)
  headings: string[];
  score: number;
  // Backward compatibility fields
  bbox?: any;
  elements?: ElementData[];
  item_types?: string[];
  table_data?: TableData;
  tables?: TableData[];
  images?: ImageData[];
  semanticMatches?: Array<{
    start: number;
    end: number;
    matchedText: string;
    similarity?: number;
  }>;
  // Translation fields
  translated_snippet?: string;
  translated_title?: string;
  translated_headings_display?: string;
  translated_language?: string;
  translatedSemanticMatches?: Array<{
    start: number;
    end: number;
    matchedText: string;
    similarity?: number;
  }>;
  // Core fields for backward compatibility
  title: string;
  organization?: string;
  year?: string;
  // System fields
  sys_parsed_folder?: string;
  sys_filepath?: string;
  // ALL document metadata as flexible JSON - any field can appear here
  metadata: Record<string, any>;
  // Allow any additional fields to be passed through
  [key: string]: any;
}

export interface ModelConfig {
  name: string;
  description: string;
  is_default: boolean;
}

export interface ModelComboConfig {
  embedding_model: string;
  embedding_model_id?: string;
  embedding_model_location?: string;
  sparse_model?: string;
  sparse_model_location?: string;
  summarization_model: SummaryModelConfig;
  semantic_highlighting_model: SummaryModelConfig;
  reranker_model: string;
  summarization_model_location?: string;
  semantic_highlighting_location?: string;
  reranker_model_location?: string;
}

export interface SummaryModelConfig {
  model: string;
  max_tokens: number;
  temperature: number;
  chunk_overlap: number;
  chunk_tokens_ratio: number;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
  filters?: Record<string, string[]>;
}

export interface FacetValue {
  value: string;
  count: number;
  organization?: string;  // For title facets - associated org
  published_year?: string;  // For title facets - associated year
}

export interface Facets {
  facets: Record<string, FacetValue[]>;  // core_field_name -> facet values
  filter_fields: Record<string, string>;  // core_field_name -> display label
}

export interface HighlightBox {
  page: number;
  bbox: {
    l: number;
    r: number;
    t: number;
    b: number;
  };
  text: string;
  isTextMatch?: boolean; // true for local text search matches (bright highlight)
  semanticMatches?: Array<{
    start: number;
    end: number;
    matchedText: string;
    similarity?: number;
  }>;
  highlightedText?: string; // HTML with <em> tags from unified highlight API
}

export interface HighlightResponse {
  highlights: HighlightBox[];
  total: number;
}

// Dynamic search filters using core field names
export interface SearchFilters {
  [coreField: string]: string | undefined;
}
