import { SourceReference } from '../../types/api';
import { BriefActivityEvent } from '../../utils/briefStream';

export type BriefStage = 'seed' | 'outline' | 'research' | 'done';

// How the compiled References list is laid out — and, because the list and the
// inline `[n]` markers share one numbering, how citations are numbered:
//   'passage'           one number per cited passage; one row per number.
//   'document-multiple' one number per cited passage; rows collapsed to one per
//                       document, each number shown with its page.
//   'document-single'   one number per document, no page numbers: every passage
//                       of a document cites the same `[n]`.
export type ReferenceGrouping = 'passage' | 'document-multiple' | 'document-single';
export type SectionStatus = 'pending' | 'researching' | 'done';

// What kind of operation produced a version (a "run") of a section. `generate`
// is the initial (re-)research; `edit` revises the existing draft per an
// instruction; `update` folds in new sources published since the last run;
// `condense` shortens an overshooting draft; `manual` is the author's own edit.
export type SectionAuditKind = 'generate' | 'edit' | 'update' | 'condense' | 'manual';

// A `[n]` marker in a run's text that resolved to no source: the agent cited a
// number it never returned, or the record it returned carries no chunk id. The
// API keeps it visible as `[?n]`; it is never dropped.
export interface UnresolvedMarker {
  n: number;
  reason: 'no-source' | 'no-chunk-id';
}

// One run of a section as the API summarises it: the agent's original text
// and sources are fetched on demand (see SectionRunDetail); the mapping from
// the agent's own numbers to brief source ids and the unresolved markers come
// inline so the Log can show them.
export interface SectionRunSummary {
  id: string;
  mode: SectionAuditKind;
  at: number;
  runId?: string; // the assistant run id from the stream, for tracing
  question?: string;
  instruction?: string;
  status: 'current' | 'superseded' | 'rejected';
  sourcesRetained: 'exact' | 'cited-without-excerpt';
  mapping: Record<string, string>;
  unresolved: UnresolvedMarker[];
  rejected: Array<{ index: number | null; reason: string }>;
  sourceCount: number;
  citedCount: number;
}

// A stored original: the agent's text with its own `[n]` markers, its source
// records as returned, and (for the current run) the agent -> display table.
export interface SectionRunDetail extends SectionRunSummary {
  sectionId: string;
  content: string;
  sources: SourceReference[];
  displayNumbers: Record<string, number>;
}

// A section's renumbered version as the API computed it: the display text,
// the display sources (`index` = the number on screen, with the brief source
// id and the agent's numbers behind it) and the unresolved markers.
export interface RenumberedSection {
  content: string;
  sources: SourceReference[];
  unresolved: UnresolvedMarker[];
  grouping: ReferenceGrouping;
  computedAt: number;
}

// One row of the compiled References list; `source` is the display record of
// the cited passage (clicking the reference opens the document there).
export interface BriefReference {
  n: number;
  sourceId: string;
  title: string;
  page?: number | null;
  docId: string;
  source?: SourceReference | null;
}

// The References list grouped by document, as "Group by document (multiple
// per document)" shows it: each document once with its numbers and pages.
export interface BriefReferenceGroup {
  docId: string;
  title: string;
  cites: Array<{ n: number; page?: number | null; sourceId: string }>;
}

// One row in a section's research/audit log — surfaced in the per-section Log
// modal so the full provenance of a section (every generate/edit/update, its
// question/instruction, and what it drew in) is auditable.
export interface SectionAuditEntry {
  id: string;
  kind: SectionAuditKind;
  at: number; // epoch ms
  // The research question (generate) and/or the user's edit/update instruction.
  question?: string;
  instruction?: string;
  // Sources cited after this operation, and how many were newly added by it.
  sourceCount?: number;
  addedSourceCount?: number;
  // Something the user should know about this run, shown in the Log (e.g. an
  // introduction that still had headings after its re-runs).
  note?: string;
  // For edit/update: the section content immediately before and after this
  // operation, so its diff stays viewable from the Log even after it's kept and
  // even on a reloaded (saved) brief. Absent for generate.
  before?: string;
  after?: string;
  // The stored original this entry describes (see SectionRunSummary).
  runId?: string;
  unresolvedCount?: number;
}

export interface BriefSection {
  id: string;
  title: string;
  level: number; // 1 = section, 2 = sub-section
  status: SectionStatus;
  progress: number; // 0-100
  // The section's display text: while it streams, the agent's text with its
  // own numbers; once the API has recorded the run, the renumbered text it
  // returned (markers numbered across the brief, `[?n]` where unresolved).
  content: string;
  // The display sources the API returned (`index` = the number on screen).
  sources: SourceReference[];
  activity: BriefActivityEvent[]; // most-recent-first, capped
  // The section's runs as the API summarises them, and which one is current.
  runs?: SectionRunSummary[];
  currentRunId?: string | null;
  // Markers of the current run that resolved to no source.
  unresolved?: UnresolvedMarker[];
  // True for unedited placeholder headings from "write my own headings"; the
  // per-section research action stays disabled until the user edits them.
  sample?: boolean;
  // Provenance for the Log modal — every generate/edit/update on this section.
  audit?: SectionAuditEntry[];
  // Epoch ms the section was last (re-)researched; drives Update's "sources
  // published since" date filter.
  lastResearchedAt?: number;
  // True while an Edit/Update (revise) is running: the section is researching
  // but its current content stays in place (rendered greyed-out) and keeps its
  // slot in the global citation numbering.
  revising?: boolean;
  // The run of the most recent AI edit/update, while it awaits Keep or Reject.
  // Keep clears it; Reject asks the API to make the previous run current again.
  pendingRunId?: string;
  // The kind of the most recent AI op that changed content, for the changes UI.
  lastChangeKind?: SectionAuditKind;
  // Author instructions for researching this section, kept per section so they
  // survive and are applied by a document-wide "Regenerate all".
  guidance?: string;
  // Voice & tone profile override for this section (null/absent = brief default).
  voiceId?: string | null;
  // Length target override for this section, in words (null/absent = the
  // brief's target). See briefLength.ts.
  targetWords?: number | null;
  // An introduction (a top-level heading with sub-headings) that still has
  // this many headings of its own after its re-runs; shown as a warning.
  introHeadingWarning?: number;
}

// A section as the browser saves it: structure and settings only. Everything
// about citations (the originals, the source list, the renumbered text) is
// computed and kept by the API; a save never carries it. `content` is sent
// only for a section that has text but no run yet (a template's saved text),
// which the API records as a manual run.
export interface SavedBriefSection {
  // Stable across saves/loads: comments (and any future per-section anchor)
  // reference this, so regenerating it would orphan them.
  id?: string;
  title: string;
  level: number;
  status: SectionStatus;
  content?: string;
  lastResearchedAt?: number;
  voiceId?: string | null;
  guidance?: string;
  targetWords?: number | null;
  introHeadingWarning?: number;
}

// A section as the API returns it: the saved structure plus the Log, the run
// summaries and the renumbered version.
export interface BriefSectionRead extends SavedBriefSection {
  id: string;
  audit?: SectionAuditEntry[];
  runs: SectionRunSummary[];
  currentRunId: string | null;
  renumbered: RenumberedSection;
}

export interface SavedBrief {
  id: string;
  title: string;
  query: string;
  date: number;
  sectionCount: number;
  sourceCount: number;
  sections: SavedBriefSection[];
  // The citation format of the stored brief; the API refuses anything else.
  citationsVersion?: number;
  // How citations are numbered and the References list laid out; saved with
  // the brief and changed through the API, which renumbers.
  referenceGrouping?: ReferenceGrouping;
  // The outline-generation activity log (queries run, sources read).
  outlineLog?: BriefActivityEvent[];
  // Whether heading numbers ("1.", "2.1") are shown (default off).
  numberHeadings?: boolean;
  // Stable UUID used as the Activity-log search_id, so each save updates the
  // same activity row instead of creating duplicates.
  activityId?: string;
  // Brief-level voice & tone profile id (sections may override individually).
  voiceId?: string | null;
  // Brief-level section length target in words (sections may override).
  // Absent/null = no target: the model decides.
  targetWords?: number | null;
  // Brief-wide research instructions ("Brief prompt"), applied to every
  // section alongside the section's own guidance. Absent = none.
  instructions?: string;
}

export const BRIEF_HISTORY_KEY = 'evidencelab_brief_history_v1';

// Default title for a brief before the user names it.
export const DEFAULT_BRIEF_TITLE = 'Evidence Brief';

// Set once the localStorage briefs bucket has been uploaded to the server
// (per user), so the one-time migration never repeats.
export const BRIEF_MIGRATED_KEY = 'evidencelab_brief_migrated_v1';

// ---------------------------------------------------------------------------
// Brief Central: templates, voice & tone profiles, sharing
// ---------------------------------------------------------------------------

// Library items (templates and voice & tone profiles) are owned by their
// creator and may be shared with other users or groups. `can_edit` is true for
// the owner; a shared item is use-only and names its owner. `share_count` is
// only filled in for the owner.
interface LibraryItemAccess {
  owner_name: string | null;
  can_edit: boolean;
  share_count: number;
}

export interface VoiceProfile extends LibraryItemAccess {
  id: string;
  name: string;
  description: string | null;
  instructions: string;
  created_at: string;
  updated_at: string;
}

// One heading of a template. `prompt` is the section's research instructions;
// `voice_profile_id` and `target_words` override the brief defaults for that
// section. Absent or null means "use the brief default".
export interface BriefTemplateHeading {
  title: string;
  sub: boolean;
  text?: string | null;
  prompt?: string | null;
  voice_profile_id?: string | null;
  target_words?: number | null;
}

export interface BriefTemplate extends LibraryItemAccess {
  id: string;
  name: string;
  description: string | null;
  headings: BriefTemplateHeading[];
  with_text: boolean;
  // Brief-wide defaults: research instructions for every section, the default
  // voice & tone profile and the default section length.
  prompt: string | null;
  voice_profile_id: string | null;
  target_words: number | null;
  use_count: number;
  created_at: string;
  updated_at: string;
}

export interface BriefShareTarget {
  id: string;
  name: string;
  kind: string; // the user's email, or "Group · N members"
  is_group: boolean;
}

// Compact card for the Brief Central grids (no section content).
export interface BriefListItem {
  id: string;
  title: string;
  query: string | null;
  data_source: string | null;
  voice_profile_id: string | null;
  section_count: number;
  source_count: number;
  owner_name: string | null;
  // Filled in for the admin "All Briefs" list, so it can be searched by user.
  owner_email?: string | null;
  share_count: number;
  created_at: string;
  updated_at: string;
}

// A brief as the API returns it: the saved settings, every section with its
// renumbered version, and the compiled References.
export interface BriefContentRead extends Omit<SavedBrief, 'sections'> {
  sections: BriefSectionRead[];
  referenceGrouping: ReferenceGrouping;
  references: BriefReference[];
  referenceGroups: BriefReferenceGroup[];
  renumberedAt?: number;
}

// The current citation format; a saved brief carries it, and the API converts
// anything older only when asked to (see migrateLocalBriefs).
export const BRIEF_CITATIONS_VERSION = 2;

// Full server brief; `content` is the brief as the API returns it.
export interface RemoteBrief {
  id: string;
  user_id: string;
  title: string;
  query: string | null;
  data_source: string | null;
  voice_profile_id: string | null;
  content: BriefContentRead;
  owner_name: string | null;
  can_edit: boolean;
  shared_with: BriefShareTarget[];
  created_at: string;
  updated_at: string;
}
