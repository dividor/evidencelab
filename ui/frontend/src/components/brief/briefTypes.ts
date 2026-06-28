import { SourceReference } from '../../types/api';
import { BriefActivityEvent } from '../../utils/briefStream';

export type BriefStage = 'seed' | 'outline' | 'research' | 'done';
export type SectionStatus = 'pending' | 'researching' | 'done';

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
}

export const BRIEF_HISTORY_KEY = 'evidencelab_brief_history_v1';
