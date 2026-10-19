import axios from 'axios';
import API_BASE_URL from '../../config';
import { getSessionId } from '../../hooks/useActivityLogging';
import { SourceReference } from '../../types/api';
import {
  BriefContentRead,
  ReferenceGrouping,
  RemoteBrief,
  SavedBrief,
  SectionAuditKind,
  SectionRunDetail,
} from './briefTypes';

/**
 * The brief citation API. Every change to a section's text goes through it
 * as a run, and the API returns the brief renumbered: the browser renders
 * what comes back and never numbers, deduplicates or assembles references
 * itself (see CLAUDE.md, "No business logic in the UI").
 *
 * Signed-in briefs (Brief Central) use the per-brief endpoints. A brief the
 * browser keeps itself (no user module, or not signed in) uses the stateless
 * `/brief/citations` endpoint: the browser sends the brief's stored form with
 * one operation and stores the form the API sends back.
 */

/** A run of a section, as the browser streamed it from the research agent
 *  (`sources` present) or as text written against the numbers on screen
 *  (`sources` absent, `basedOn` naming that numbering). */
export interface RunPayload {
  mode: SectionAuditKind;
  content: string;
  sources?: SourceReference[];
  basedOn?: Record<string, string>;
  runId?: string;
  question?: string;
  instruction?: string;
  note?: string;
}

const runBody = (run: RunPayload) => ({
  mode: run.mode,
  content: run.content,
  sources: run.sources ?? null,
  based_on: run.basedOn ?? null,
  run_id: run.runId ?? null,
  question: run.question ?? null,
  instruction: run.instruction ?? null,
  note: run.note ?? null,
});

// ---- Brief Central (signed in) ----

export const recordRun = async (
  briefId: string,
  sectionId: string,
  run: RunPayload,
): Promise<RemoteBrief> => {
  const res = await axios.post(
    `${API_BASE_URL}/briefs/${briefId}/sections/${sectionId}/runs`,
    runBody(run),
  );
  return res.data as RemoteBrief;
};

export const rejectRun = async (
  briefId: string,
  sectionId: string,
  runId: string,
): Promise<RemoteBrief> => {
  const res = await axios.post(
    `${API_BASE_URL}/briefs/${briefId}/sections/${sectionId}/runs/${runId}/reject`,
  );
  return res.data as RemoteBrief;
};

export const setReferenceGrouping = async (
  briefId: string,
  grouping: ReferenceGrouping,
): Promise<RemoteBrief> => {
  const res = await axios.put(`${API_BASE_URL}/briefs/${briefId}/reference-grouping`, {
    grouping,
  });
  return res.data as RemoteBrief;
};

/** Claim highlight matches by brief source id. */
export type HighlightsPayload = Record<string, NonNullable<SourceReference['claimMatches']>>;

export const setHighlights = async (
  briefId: string,
  highlights: HighlightsPayload,
): Promise<RemoteBrief> => {
  const res = await axios.put(`${API_BASE_URL}/briefs/${briefId}/highlights`, { highlights });
  return res.data as RemoteBrief;
};

export const getRunDetail = async (
  briefId: string,
  sectionId: string,
  runId: string,
): Promise<SectionRunDetail> => {
  const res = await axios.get(
    `${API_BASE_URL}/briefs/${briefId}/sections/${sectionId}/runs/${runId}`,
  );
  return res.data as SectionRunDetail;
};

// ---- browser-held briefs ----

/** The brief's stored form: what the API keeps for a signed-in brief, and
 *  what the browser keeps in localStorage for its own. Opaque to the browser
 *  beyond the SavedBrief fields the history list shows. */
export type StoredBrief = SavedBrief & Record<string, unknown>;

export type CitationOp =
  | { type: 'run'; sectionId: string; run: RunPayload }
  | { type: 'reject'; sectionId: string; runId: string }
  | { type: 'grouping'; grouping: ReferenceGrouping }
  | { type: 'structure'; brief: SavedBrief }
  | { type: 'highlights'; highlights: HighlightsPayload }
  | { type: 'read' }
  | { type: 'convert' };

export interface CitationOpResult {
  content: StoredBrief;
  read: BriefContentRead;
}

const opBody = (op: CitationOp): Record<string, unknown> =>
  op.type === 'run' ? { ...op, run: runBody(op.run) } : op;

/** Apply one operation to a browser-held brief; the API returns the stored
 *  form to keep and the read model to render. */
export const applyCitationOp = async (
  content: StoredBrief | Record<string, unknown>,
  op: CitationOp,
): Promise<CitationOpResult> => {
  const res = await axios.post(`${API_BASE_URL}/brief/citations`, {
    content,
    op: opBody(op),
    session_id: getSessionId(),
  });
  return res.data as CitationOpResult;
};

/** One stored original of a browser-held brief. */
export const getLocalRunDetail = async (
  content: StoredBrief,
  sectionId: string,
  runId: string,
): Promise<SectionRunDetail> => {
  const res = await axios.post(`${API_BASE_URL}/brief/citations`, {
    content,
    op: { type: 'run_detail', sectionId, runId },
    session_id: getSessionId(),
  });
  return (res.data as { detail: SectionRunDetail }).detail;
};
