import { SourceReference } from '../../types/api';
import { BriefActivityEvent } from '../../utils/briefStream';

export type BriefStage = 'seed' | 'outline' | 'research' | 'done';
export type SectionStatus = 'pending' | 'researching' | 'done';

// What kind of AI operation produced a version of a section. `generate` is the
// initial (re-)research; `edit` revises the existing draft per an instruction;
// `update` folds in new sources published since the last run.
export type SectionAuditKind = 'generate' | 'edit' | 'update';

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
  // For edit/update: the section content immediately before and after this
  // operation, so its diff stays viewable from the Log even after it's kept and
  // even on a reloaded (saved) brief. Absent for generate.
  before?: string;
  after?: string;
}

export interface BriefSection {
  id: string;
  title: string;
  level: number; // 1 = section, 2 = sub-section
  status: SectionStatus;
  progress: number; // 0-100
  content: string; // markdown (may contain [n] citation markers)
  sources: SourceReference[];
  activity: BriefActivityEvent[]; // most-recent-first, capped
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
  // The content/sources immediately before the most recent edit/update, kept so
  // the user can view the diff and Keep or Reject the edits. Cleared on Keep;
  // restored on Reject.
  prevContent?: string;
  prevSources?: SourceReference[];
  // The kind of the most recent AI op that changed content, for the changes UI.
  lastChangeKind?: SectionAuditKind;
  // Author instructions for researching this section, kept per section so they
  // survive and are applied by a document-wide "Regenerate all".
  guidance?: string;
  // Voice & tone profile override for this section (null/absent = brief default).
  voiceId?: string | null;
}

export interface BriefReference {
  n: number;
  title: string;
  page?: number;
  section: string;
  source: SourceReference; // for click-through to the document preview
}

export interface SavedBriefSection {
  // Stable across saves/loads: comments (and any future per-section anchor)
  // reference this, so regenerating it would orphan them.
  id?: string;
  title: string;
  level: number;
  status: SectionStatus;
  content: string;
  sources: SourceReference[];
  audit?: SectionAuditEntry[];
  lastResearchedAt?: number;
  voiceId?: string | null;
  guidance?: string;
}

export interface SavedBrief {
  id: string;
  title: string;
  query: string;
  date: number;
  sectionCount: number;
  sourceCount: number;
  sections: SavedBriefSection[];
  // The outline-generation activity log (queries run, sources read).
  outlineLog?: BriefActivityEvent[];
  // Whether heading numbers ("1.", "2.1") are shown (default off).
  numberHeadings?: boolean;
  // Stable UUID used as the Activity-log search_id, so each save updates the
  // same activity row instead of creating duplicates.
  activityId?: string;
  // Brief-level voice & tone profile id (sections may override individually).
  voiceId?: string | null;
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

export interface VoiceProfile {
  id: string;
  name: string;
  description: string | null;
  instructions: string;
  created_at: string;
  updated_at: string;
}

export interface BriefTemplateHeading {
  title: string;
  sub: boolean;
  // Optional saved section text ("include section text" templates).
  text?: string | null;
}

export interface BriefTemplate {
  id: string;
  name: string;
  description: string | null;
  headings: BriefTemplateHeading[];
  with_text: boolean;
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
  share_count: number;
  created_at: string;
  updated_at: string;
}

// Full server brief; `content` is the SavedBrief payload.
export interface RemoteBrief {
  id: string;
  user_id: string;
  title: string;
  query: string | null;
  data_source: string | null;
  voice_profile_id: string | null;
  content: SavedBrief;
  owner_name: string | null;
  can_edit: boolean;
  shared_with: BriefShareTarget[];
  created_at: string;
  updated_at: string;
}
