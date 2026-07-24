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
}

export interface BriefReference {
  n: number;
  title: string;
  page?: number;
  section: string;
  source: SourceReference; // for click-through to the document preview
}

export interface SavedBriefSection {
  title: string;
  level: number;
  status: SectionStatus;
  content: string;
  sources: SourceReference[];
  audit?: SectionAuditEntry[];
  lastResearchedAt?: number;
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
}

export const BRIEF_HISTORY_KEY = 'evidencelab_brief_history_v1';
