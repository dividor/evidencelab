import axios from 'axios';
import API_BASE_URL from '../../../config';
import type { SummaryModelConfig } from '../../../types/api';
import { jsonRequestHeaders } from '../../../utils/requestHeaders';
import type {
  DocumentSections,
  SaveMethod,
  SummaryConfigDefaults,
  SummaryMode,
  SummarySettings,
} from './summarySettings';

const BASE = `${API_BASE_URL}/document-summaries`;
const GENERIC_ERROR = 'The summary could not be generated.';

export const fetchSummaryDefaults = async (dataSource?: string): Promise<SummaryConfigDefaults> => {
  const query = dataSource ? `?data_source=${encodeURIComponent(dataSource)}` : '';
  const response = await axios.get<SummaryConfigDefaults>(`${BASE}/settings${query}`);
  return response.data;
};

export const fetchDocumentSections = async (
  dataSource: string,
  docId: string,
  model: SummaryModelConfig,
): Promise<DocumentSections> => {
  const response = await axios.get<DocumentSections>(
    `${BASE}/${encodeURIComponent(docId)}/sections`,
    { params: { data_source: dataSource, model: model.model, max_tokens: model.max_tokens } },
  );
  return response.data;
};

/** One progress step while a summary is generated. */
export type SummaryProgress =
  | { stage: 'single' }
  | { stage: 'map'; done: number; total: number }
  | { stage: 'reduce'; depth: number };

export interface GeneratedSummary {
  summary: string;
  mode: SummaryMode;
  method: SaveMethod;
  input_chars: number;
  calls: number;
}

export interface GenerateOptions {
  dataSource: string;
  docId: string;
  settings: SummarySettings;
  model: SummaryModelConfig;
  onProgress?: (progress: SummaryProgress) => void;
  onMeta?: (meta: { has_section_types: boolean }) => void;
  signal?: AbortSignal;
}

export class SummaryGenerationError extends Error {}

const responseError = async (response: Response): Promise<string> => {
  try {
    const body = await response.json();
    return typeof body?.detail === 'string' ? body.detail : GENERIC_ERROR;
  } catch {
    return GENERIC_ERROR;
  }
};

type Frame = Record<string, any> & { type: string };

const parseFrames = (buffer: string): { frames: Frame[]; rest: string } => {
  const parts = buffer.split('\n\n');
  const rest = parts.pop() ?? '';
  const frames = parts
    .map((part) => part.trim())
    .filter((part) => part.startsWith('data: '))
    .map((part) => JSON.parse(part.slice(6)) as Frame);
  return { frames, rest };
};

const handleFrame = (frame: Frame, options: GenerateOptions): GeneratedSummary | null => {
  if (frame.type === 'meta') options.onMeta?.({ has_section_types: Boolean(frame.has_section_types) });
  if (frame.type === 'progress') {
    const { type: _type, ...progress } = frame;
    options.onProgress?.(progress as SummaryProgress);
  }
  if (frame.type === 'error') throw new SummaryGenerationError(frame.error || GENERIC_ERROR);
  if (frame.type === 'done') return frame as unknown as GeneratedSummary;
  return null;
};

/** Generate a summary (nothing is saved). Resolves with the summary, or
 *  rejects with a SummaryGenerationError carrying a message to show. */
export const generateDocumentSummary = async (options: GenerateOptions): Promise<GeneratedSummary> => {
  const { dataSource, docId, settings, model, signal } = options;
  const response = await fetch(`${BASE}/${encodeURIComponent(docId)}/generate`, {
    method: 'POST',
    headers: jsonRequestHeaders(),
    credentials: 'include',
    signal,
    body: JSON.stringify({
      data_source: dataSource,
      mode: settings.mode,
      section_types: settings.sectionTypes,
      prompt: settings.prompt,
      summary_model: { model: model.model, max_tokens: model.max_tokens, temperature: model.temperature },
    }),
  });
  if (!response.ok || !response.body) {
    throw new SummaryGenerationError(await responseError(response));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseFrames(buffer + decoder.decode(value, { stream: true }));
    buffer = parsed.rest;
    for (const frame of parsed.frames) {
      const result = handleFrame(frame, options);
      if (result) return result;
    }
  }
  throw new SummaryGenerationError(GENERIC_ERROR);
};

export interface SavedSummary {
  doc_id: string;
  full_summary: string;
  summarization_method: SaveMethod;
  summary_user_set: boolean;
  summary_updated_by: string;
  summary_updated_at: string;
}

export const saveDocumentSummary = async (
  dataSource: string,
  docId: string,
  summary: string,
  method: SaveMethod,
): Promise<SavedSummary> => {
  const response = await axios.put<SavedSummary>(`${BASE}/${encodeURIComponent(docId)}`, {
    data_source: dataSource,
    summary,
    method,
  });
  return response.data;
};
