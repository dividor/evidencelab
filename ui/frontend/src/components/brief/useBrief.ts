import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { LinkTarget } from '../../utils/exportResultsToDocx';
import { SourceReference, SummaryModelConfig } from '../../types/api';
import { SearchSettings } from '../../types/auth';
import { buildCondenseInstruction, countWords, exceedsTarget } from './briefLength';
import {
  BriefActivityEvent,
  BriefSourceSample,
  buildOutlineContext,
  isLikelyNonAnswer,
  requestBriefOutline,
  requestBriefRevise,
  researchBriefSection,
  runDeepResearch,
  SectionResearchMode,
} from '../../utils/briefStream';
import {
  BRIEF_CITATIONS_VERSION,
  BRIEF_HISTORY_KEY,
  BriefContentRead,
  BriefReference,
  BriefReferenceGroup,
  BriefSection,
  BriefSectionRead,
  BriefTemplateHeading,
  BriefStage,
  DEFAULT_BRIEF_TITLE,
  ReferenceGrouping,
  RemoteBrief,
  SavedBrief,
  SectionRunDetail,
  VoiceProfile,
} from './briefTypes';
import {
  copyBrief as copyBriefRemote,
  createBrief as createBriefRemote,
  deleteBriefRemote,
  getBrief as getBriefRemote,
  listMyBriefs,
  updateBrief as updateBriefRemote,
} from './briefCentralApi';
import {
  applyCitationOp,
  CitationOp,
  getLocalRunDetail,
  getRunDetail,
  HighlightsPayload,
  recordRun,
  rejectRun as rejectRunRemote,
  RunPayload,
  setHighlights as setHighlightsRemote,
  setReferenceGrouping as setReferenceGroupingRemote,
  StoredBrief,
} from './briefCitationsApi';
import { listItemToStub, migrateLocalBriefs, remoteToRead } from './briefRemote';
import {
  BRIEF_INTRO,
  extraHeadingLines,
  researchOrder,
  sectionTargetWords,
  subSectionTitles,
} from './briefIntro';
import { highlightOneSource, highlightSectionSources } from './briefHighlights';
import {
  SEARCH_SEMANTIC_HIGHLIGHTS,
  SEMANTIC_HIGHLIGHT_THRESHOLD,
} from '../../config';

let _uid = 0;
const uid = (): string => `b${++_uid}_${Date.now()}`;

// A real UUID for the Activity-log search_id (one stable id per brief).
const newActivityId = (): string =>
  typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : uid();

// Capitalise the first letter of each word, leaving the rest as-is so existing
// capitalisation / acronyms (e.g. WFP) survive. Used on generated brief titles.
const toTitleCase = (s: string): string => s.replace(/\b[a-zA-Z]/g, (c) => c.toUpperCase());

const makeSection = (title: string, level = 1, sample = false): BriefSection => ({
  id: uid(),
  title,
  level: level === 2 ? 2 : 1,
  status: 'pending',
  progress: 0,
  content: '',
  sources: [],
  activity: [],
  runs: [],
  currentRunId: null,
  unresolved: [],
  sample,
});

// The display numbering a section's text was written against (number ->
// brief source id), sent with a run whose text was edited on screen so the
// API can refuse it if the section was renumbered in between.
const basedOnOf = (sources: SourceReference[]): Record<string, string> => {
  const out: Record<string, string> = {};
  sources.forEach((src) => {
    if (src.index != null && src.sourceId) out[String(src.index)] = src.sourceId;
  });
  return out;
};

// Claim highlights the browser computed, keyed by brief source id, for the
// API to store on the brief-wide source list.
const highlightsOf = (sources: SourceReference[]): HighlightsPayload => {
  const out: HighlightsPayload = {};
  sources.forEach((src) => {
    if (src.sourceId && src.claimMatches !== undefined) out[src.sourceId] = src.claimMatches;
  });
  return out;
};

// An empty brief in its stored form, for a browser-held brief's first save.
const emptyStoredBrief = (): Record<string, unknown> => ({
  citationsVersion: BRIEF_CITATIONS_VERSION,
  referenceGrouping: 'passage',
  sources: [],
  sections: [],
});

// One citation operation on a signed-in brief, as the Brief Central API offers it.
const remoteCitationOp = (serverId: string, op: CitationOp): Promise<RemoteBrief> => {
  switch (op.type) {
    case 'run':
      return recordRun(serverId, op.sectionId, op.run);
    case 'reject':
      return rejectRunRemote(serverId, op.sectionId, op.runId);
    case 'grouping':
      return setReferenceGroupingRemote(serverId, op.grouping);
    case 'highlights':
      return setHighlightsRemote(serverId, op.highlights);
    case 'structure':
      return updateBriefRemote(serverId, {
        title: op.brief.title,
        query: op.brief.query || null,
        voiceProfileId: op.brief.voiceId ?? null,
        content: { ...op.brief, id: serverId },
      });
    case 'read':
      return getBriefRemote(serverId);
    default:
      return Promise.reject(new Error('A saved brief is converted by the server'));
  }
};

/**
 * A new section from a template heading: its prompt becomes the section's
 * research guidance, and its voice and length override the brief defaults.
 * Saved text, when the template has it, starts the section as done.
 */
export const sectionFromTemplateHeading = (h: BriefTemplateHeading): BriefSection => {
  const section: BriefSection = {
    ...makeSection(h.title, h.sub ? 2 : 1, false),
    guidance: h.prompt || undefined,
    voiceId: h.voice_profile_id ?? null,
    targetWords: h.target_words ?? null,
  };
  if (h.text) return { ...section, status: 'done', progress: 100, content: h.text };
  return section;
};

const headingCount = (n: number): string => `${n} heading${n === 1 ? '' : 's'}`;

/** The Log note for an introduction kept with headings after its re-runs. */
export const introHeadingNote = (headings: number, reruns: number): string =>
  `This introduction still has ${headingCount(headings)} of its own after ${reruns} re-run${
    reruns === 1 ? '' : 's'
  }. Edit them out, or use AI Regenerate.`;

/** Headings an introduction's text has of its own, for its warning; undefined
 *  for a section that is not an introduction or has none. An edit cannot be
 *  re-run like research, so its result is only flagged. */
const introWarningFor = (sections: BriefSection[], id: string, content: string): number | undefined =>
  subSectionTitles(sections, id).length ? extraHeadingLines(content).length || undefined : undefined;

const timesText = (n: number): string => (n === 1 ? 'once' : `${n} times`);

/** The Log note for an introduction that needed re-running to lose its headings. */
export const introRerunNote = (reruns: number): string =>
  `Re-run ${timesText(reruns)}: the earlier draft had headings of its own, which an introduction should not.`;

/**
 * What a finished draft means for an introduction: how many headings of its
 * own it has, and whether it should be re-run (re-runs left) rather than kept.
 * A section that is not an introduction never has either.
 */
const introOutcome = (
  subSectionCount: number,
  content: string,
  attempt: number,
): { headings: number; rerun: boolean } => {
  const headings = subSectionCount ? extraHeadingLines(content).length : 0;
  return { headings, rerun: headings > 0 && attempt < BRIEF_INTRO.heading_retries };
};

/** The Log note for a kept draft: headings left after re-runs, or re-runs that fixed it. */
const introAuditNote = (headings: number, attempt: number): string | undefined => {
  if (headings) return introHeadingNote(headings, attempt);
  return attempt > 0 ? introRerunNote(attempt) : undefined;
};

const rerunActivityText = (headings: number, attempt: number): string =>
  `The introduction came back with ${headingCount(headings)}; re-running (${attempt + 1} of ${
    BRIEF_INTRO.heading_retries
  })`;

/** The sub-headings a section introduces, for a revise request; null if none. */
const introSubSectionsOf = (sections: BriefSection[], id: string): string[] | null => {
  const subs = subSectionTitles(sections, id);
  return subs.length ? subs : null;
};

/** The working state of a brief that is saved (see toSavedBrief). */
export interface BriefSnapshot {
  id: string;
  title: string;
  query: string;
  sections: BriefSection[];
  outlineLog: BriefActivityEvent[];
  numberHeadings: boolean;
  activityId: string | null;
  voiceId: string | null;
  targetWords: number | null;
  instructions: string;
}

/** The saved form of a brief: its structure and settings, as sent to the
 *  API. Nothing about citations travels with it — the API holds every run,
 *  the source list and the renumbered text, and recomputes the numbering
 *  from the structure it receives. */
export const toSavedBrief = (b: BriefSnapshot): SavedBrief => ({
  id: b.id,
  title: b.title,
  query: b.query,
  date: Date.now(),
  citationsVersion: BRIEF_CITATIONS_VERSION,
  sectionCount: b.sections.length,
  sourceCount: 0,
  // A section that was mid- or un-researched reverts to its last stable
  // (pending) state on reload — never a stuck "Researching…".
  sections: b.sections.map((s) => {
    // A mid-revise section still holds its last good content — persist it
    // as done so an interrupted Edit/Update never loses the section.
    const done = s.status === 'done' || !!s.revising;
    // Text that has no run yet (a template's saved text) is sent once, for
    // the API to record as a manual run; researched text never travels.
    const unrecorded = done && !s.runs?.length && !!s.content;
    return {
      // Persist the id so comments anchored to this section survive a
      // reload; a fresh id each load would orphan every thread.
      id: s.id,
      title: s.title,
      level: s.level,
      status: done ? 'done' : 'pending',
      content: unrecorded ? s.content : undefined,
      lastResearchedAt: s.lastResearchedAt,
      voiceId: s.voiceId ?? undefined,
      guidance: s.guidance || undefined,
      targetWords: s.targetWords ?? undefined,
      introHeadingWarning: s.introHeadingWarning || undefined,
    };
  }),
  outlineLog: b.outlineLog,
  numberHeadings: b.numberHeadings,
  activityId: b.activityId ?? undefined,
  voiceId: b.voiceId,
  targetWords: b.targetWords ?? undefined,
  instructions: b.instructions.trim() || undefined,
});

/** Everything a save would write except its timestamp, to tell whether a
 *  save would change anything. */
export const savedSignature = (entry: SavedBrief): string => JSON.stringify({ ...entry, date: 0 });

export interface UseBriefOptions {
  apiBaseUrl: string;
  dataSource: string;
  // The configured chat / deep-research model (combo.assistant_model). Used for
  // both outline generation and per-section research so the Brief tab uses the
  // same LLM as the rest of the system.
  assistantModelConfig?: SummaryModelConfig | null;
  // Group search settings to apply to brief searches (reranker + search
  // settings). Passed only for logged-in users so briefs search like the rest
  // of the app; null for anonymous users (no rerank).
  rerankerModel?: string | null;
  searchSettings?: Partial<SearchSettings> | null;
  // Identifier for the logged-in user; saved briefs are scoped to it. When
  // absent (anonymous), the shared default bucket is used.
  userKey?: string | null;
  // Server-side persistence (Brief Central). When true, briefs are stored via
  // the /briefs API instead of localStorage, enabling sharing.
  remote?: boolean;
  // The user's voice & tone profiles, used to resolve the instructions applied
  // when a section is (re)written.
  voices?: VoiceProfile[] | null;
  // Model for the LLM semantic highlighter (combo.semantic_highlighting_model),
  // used to mark the claim-supporting span of each citation's excerpt.
  semanticModelConfig?: SummaryModelConfig | null;
}

const loadHistory = (key: string): SavedBrief[] => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as SavedBrief[]) : [];
  } catch {
    return [];
  }
};

// Index of the nearest preceding top-level heading (the parent), or -1.
const parentIndexOf = (sections: BriefSection[], i: number): number => {
  for (let k = i - 1; k >= 0; k--) {
    if (sections[k].level === 1) return k;
  }
  return -1;
};

// Reorder by drag-and-drop: move the dragged heading to the target heading's
// position, but only among true siblings (same level, and — for sub-headings —
// the same parent). A top-level heading carries its sub-headings as a block.
// Dropping while moving down lands the heading after the target (and its
// children); moving up lands it before. Invalid drops are no-ops.
export const reorderSiblingSections = (
  sections: BriefSection[],
  draggedId: string,
  targetId: string,
): BriefSection[] => {
  if (draggedId === targetId) return sections;
  const di = sections.findIndex((s) => s.id === draggedId);
  const ti = sections.findIndex((s) => s.id === targetId);
  if (di < 0 || ti < 0) return sections;
  const dragged = sections[di];
  const target = sections[ti];
  if (dragged.level !== target.level) return sections;
  if (dragged.level === 2 && parentIndexOf(sections, di) !== parentIndexOf(sections, ti)) {
    return sections;
  }

  let dEnd = di + 1;
  if (dragged.level === 1) {
    while (dEnd < sections.length && sections[dEnd].level === 2) dEnd++;
  }
  const block = sections.slice(di, dEnd);
  const rest = [...sections.slice(0, di), ...sections.slice(dEnd)];

  let insertIdx = rest.findIndex((s) => s.id === targetId);
  if (di < ti) {
    // Moving down: insert after the target (and, for a heading, its children).
    if (target.level === 1) {
      let tEnd = insertIdx + 1;
      while (tEnd < rest.length && rest[tEnd].level === 2) tEnd++;
      insertIdx = tEnd;
    } else {
      insertIdx += 1;
    }
  }
  const out = [...rest];
  out.splice(insertIdx, 0, ...block);
  return out;
};

// Hierarchical numbering: 1, 2, 2.1, 2.2, 3, …
const computeNumbers = (sections: BriefSection[]): string[] => {
  let major = 0;
  let minor = 0;
  return sections.map((s) => {
    if (s.level !== 2) {
      major += 1;
      minor = 0;
      return String(major);
    }
    minor += 1;
    return major === 0 ? String(minor) : `${major}.${minor}`;
  });
};

export const useBrief = ({
  apiBaseUrl,
  dataSource,
  assistantModelConfig,
  rerankerModel,
  searchSettings,
  userKey,
  remote = false,
  voices,
  semanticModelConfig,
}: UseBriefOptions) => {
  const historyKey = userKey ? `${BRIEF_HISTORY_KEY}_u_${userKey}` : BRIEF_HISTORY_KEY;
  const [stage, setStage] = useState<BriefStage>('seed');
  const [briefTitle, setBriefTitle] = useState(DEFAULT_BRIEF_TITLE);
  const [sections, setSections] = useState<BriefSection[]>([]);
  const [query, setQuery] = useState(''); // the brief topic
  const [instructions, setInstructions] = useState('');
  const [numHeadings, setNumHeadings] = useState(6);
  // How the References list is laid out and how citations are numbered (one
  // number per passage or per document) — see ReferenceGrouping. Drives the
  // inline [n] markers, the References list and the Word export together.
  const [referenceGrouping, setReferenceGroupingState] = useState<ReferenceGrouping>('passage');
  // The compiled References as the API computed them, rendered as returned.
  const [references, setReferences] = useState<BriefReference[]>([]);
  const [referenceGroups, setReferenceGroups] = useState<BriefReferenceGroup[]>([]);
  // Sources registered in the brief (every record the agent returned).
  const [sourceCount, setSourceCount] = useState(0);
  // Where the Word export's links point: the source documents (default) or
  // their copies in Evidence Lab.
  const [wordLinkTarget, setWordLinkTarget] = useState<LinkTarget>('source');
  // Section length target in words for this brief (sections may override);
  // null = no target, the model decides. Persisted with the brief. See
  // briefLength.ts for how it is enforced.
  const [targetWords, setTargetWordsState] = useState<number | null>(null);
  const [newHeading, setNewHeading] = useState('');
  const [regenFor, setRegenFor] = useState<string | null>(null);
  const [regenText, setRegenText] = useState('');
  const [history, setHistory] = useState<SavedBrief[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outlineLoading, setOutlineLoading] = useState(false);
  // Show "1.", "2.1" numbering before heading titles. Off by default; the user
  // toggles it from the outline rail. Persisted with the brief.
  const [numberHeadings, setNumberHeadings] = useState(false);
  // Live activity for the outline-generation deep-research survey.
  const [generatingActivity, setGeneratingActivity] = useState<BriefActivityEvent[]>([]);
  // Brief-level voice & tone profile (sections may override individually).
  const [briefVoiceId, setBriefVoiceId] = useState<string | null>(null);
  // False when the open brief was shared with (not owned by) this user.
  const [canEdit, setCanEdit] = useState(true);
  const [ownerName, setOwnerName] = useState<string | null>(null);
  // The data source a saved brief was researched in, from its server record.
  // Null for a new or local brief, whose sources are in the app's selected
  // data source. The Word export looks cited documents up in this source.
  const [briefDataSource, setBriefDataSource] = useState<string | null>(null);

  const briefIdRef = useRef<string | null>(null);
  // Stable Activity-log id for the current brief (one row per brief).
  const briefActivityIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Set to researchOne once it is defined; it re-runs itself for an
  // introduction that came back with headings.
  const researchOneRef = useRef<
    (
      id: string,
      context: string | null,
      signal: AbortSignal,
      opts?: { mode?: SectionResearchMode; instruction?: string | null; attempt?: number },
    ) => Promise<void>
  >(() => {
    throw new Error('researchOne used before it was defined');
  });
  const sectionsRef = useRef<BriefSection[]>(sections);
  sectionsRef.current = sections;
  const outlineLogRef = useRef<BriefActivityEvent[]>(generatingActivity);
  outlineLogRef.current = generatingActivity;
  // Refs so saveCurrent is a stable callback (safe to call from effects/timers).
  const briefTitleRef = useRef(briefTitle);
  briefTitleRef.current = briefTitle;
  const queryRef = useRef(query);
  queryRef.current = query;
  const instructionsRef = useRef(instructions);
  instructionsRef.current = instructions;
  const numberHeadingsRef = useRef(numberHeadings);
  numberHeadingsRef.current = numberHeadings;
  // Read by the research loop, so it is written together with the state.
  const targetWordsRef = useRef<number | null>(targetWords);
  const setTargetWords = useCallback((target: number | null) => {
    targetWordsRef.current = target;
    setTargetWordsState(target);
  }, []);
  const historyRef = useRef(history);
  historyRef.current = history;
  // Group search settings, read at research time so the research callbacks stay
  // stable as the (per-render) settings object changes.
  const rerankerModelRef = useRef(rerankerModel);
  rerankerModelRef.current = rerankerModel;
  const searchSettingsRef = useRef(searchSettings);
  searchSettingsRef.current = searchSettings;
  const briefVoiceIdRef = useRef(briefVoiceId);
  briefVoiceIdRef.current = briefVoiceId;
  const voicesRef = useRef(voices);
  voicesRef.current = voices;
  const canEditRef = useRef(canEdit);
  canEditRef.current = canEdit;
  // True once the current brief exists as a server row (remote mode).
  // The server id of every brief this session knows is on the server, keyed by
  // the id the brief had when saved (a local id before its first save, then
  // the server id). A brief opened from the server maps to itself.
  const serverIdsRef = useRef<Map<string, string>>(new Map());
  // The signature (see savedSignature) of each brief as last opened or saved,
  // keyed by server id, or local id before the first save.
  const lastSavedSigRef = useRef<Map<string, string>>(new Map());

  // The team's default section length applies to a brief that has not started
  // yet; once a brief is open its own (persisted) target stands.
  const groupTargetWords = searchSettings?.briefTargetWords;
  useEffect(() => {
    if (stage === 'seed') setTargetWords(groupTargetWords ?? null);
  }, [stage, groupTargetWords, setTargetWords]);

  // Resolve the style instructions for a section: its own profile wins, else
  // the brief default; null when neither is set (or the profile was deleted).
  const voiceInstructionsFor = useCallback((sectionVoiceId?: string | null): string | null => {
    const id = sectionVoiceId ?? briefVoiceIdRef.current;
    if (!id) return null;
    const profile = (voicesRef.current || []).find((v) => v.id === id);
    return profile ? profile.instructions : null;
  }, []);

  const refreshRemoteHistory = useCallback(async () => {
    const items = await listMyBriefs();
    setHistory(items.map(listItemToStub));
  }, []);

  useEffect(() => {
    if (!remote) {
      setHistory(loadHistory(historyKey));
      return;
    }
    // Remote mode: run the one-time localStorage migration, then load the
    // server-side history. Errors surface in the brief error banner.
    let cancelled = false;
    (async () => {
      try {
        if (userKey) await migrateLocalBriefs(userKey, dataSource || null);
        const items = await listMyBriefs();
        if (!cancelled) setHistory(items.map(listItemToStub));
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Could not load saved briefs.');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [remote, historyKey, userKey, dataSource]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const updateSection = useCallback((id: string, patch: Partial<BriefSection>) => {
    setSections((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }, []);

  const semanticModelConfigRef = useRef(semanticModelConfig);
  semanticModelConfigRef.current = semanticModelConfig;

  // Latest research-completion token per section id, written synchronously so
  // highlight enrichment can detect a superseded run without waiting on state.
  const researchTokenRef = useRef<Record<string, number>>({});
  // Sections with an enrichment pass in flight. The backfill skips these: it
  // must not start a second pass or overwrite the token of a running one,
  // which would make that run consider itself stale and stop.
  const enrichingRef = useRef<Set<string>>(new Set());
  // Sources with an on-demand (hover-triggered) highlight in flight.
  const onDemandRef = useRef<Set<string>>(new Set());
  // Brief id awaiting a highlight-enrichment resume after being opened.
  const resumeRef = useRef<string | null>(null);
  // Sections whose text was edited by hand and not yet recorded as a run.
  const manualDirtyRef = useRef<Set<string>>(new Set());

  // ---- citations: every change goes through the API ----
  // The brief's stored form, for a brief the browser keeps itself.
  const storedContentRef = useRef<StoredBrief | null>(null);
  // One API call at a time per open brief, saves included: a run never
  // overtakes the save that creates its brief, and a stale save never undoes
  // a run's result.
  const briefLockRef = useRef<Promise<unknown>>(Promise.resolve());
  const withBriefLock = useCallback(<T,>(fn: () => Promise<T>): Promise<T> => {
    const next = briefLockRef.current.then(fn, fn);
    briefLockRef.current = next.catch(() => undefined);
    return next;
  }, []);
  // When the newest brief the API returned was computed; an older response
  // never overwrites it.
  const readStampRef = useRef(0);
  // Set once citationsCall is defined below; the highlight enrichment
  // (defined first) stores its results through it.
  const citationsCallRef = useRef<(op: CitationOp) => Promise<BriefContentRead>>(() =>
    Promise.reject(new Error('citationsCall used before it was defined')),
  );

  // Take the brief the API returned into the working state: each section's
  // display text and sources, its runs and Log, and the compiled References.
  // A section mid-stream or mid-manual-edit keeps its live text; the run
  // that records it brings the API's version.
  const applyRead = useCallback((read: BriefContentRead): void => {
    const stamp = read.renumberedAt ?? 0;
    if (stamp && stamp < readStampRef.current) return;
    readStampRef.current = Math.max(readStampRef.current, stamp);
    setSections((prev) =>
      prev.map((s) => {
        const r = read.sections.find((x) => x.id === s.id);
        if (!r || s.status === 'researching' || manualDirtyRef.current.has(s.id)) return s;
        const done = r.status === 'done';
        return {
          ...s,
          status: done ? 'done' : 'pending',
          progress: done ? 100 : 0,
          content: r.renumbered?.content || '',
          sources: r.renumbered?.sources || [],
          unresolved: r.renumbered?.unresolved || [],
          runs: r.runs || [],
          currentRunId: r.currentRunId ?? null,
          audit: r.audit || [],
        };
      }),
    );
    setReferences(read.references || []);
    setReferenceGroups(read.referenceGroups || []);
    setReferenceGroupingState(read.referenceGrouping || 'passage');
    setSourceCount(read.sourceCount || 0);
  }, []);

  // Store the highlights the browser computed on the brief's source list.
  // The API's reply is not applied: the live sources already carry them.
  const pushHighlights = useCallback((sources: SourceReference[]): void => {
    const highlights = highlightsOf(sources);
    if (!Object.keys(highlights).length) return;
    citationsCallRef.current({ type: 'highlights', highlights }).catch((e) =>
      setError(e instanceof Error ? e.message : 'Could not save the highlights.'),
    );
  }, []);

  // After a section's research completes (references validated), run the LLM
  // semantic highlighter over each cited excerpt in the background — the hover
  // card then marks the claim-supporting span, falling back to the full
  // excerpt. `token` (the section's lastResearchedAt) stops a stale run from
  // clobbering a newer research pass.
  const enrichSectionHighlights = useCallback(
    (
      id: string,
      token: number,
      content: string,
      sources: SourceReference[],
    ): Promise<void> => {
      if (!SEARCH_SEMANTIC_HIGHLIGHTS || !content || !sources.length) {
        return Promise.resolve();
      }
      // No highlight model yet (the combo config is applied after mount) —
      // leave the section un-enriched so the resume pass retries once it lands.
      if (!semanticModelConfigRef.current?.model) {
        return Promise.resolve();
      }
      // Staleness is tracked in a ref written synchronously at completion —
      // reading it from section state would race React's commit, since this
      // runs from a timeout that can fire before the re-render lands.
      const isStale = () => researchTokenRef.current[id] !== token;
      if (isStale()) return Promise.resolve();
      enrichingRef.current.add(id);
      return highlightSectionSources({
        content,
        sources,
        threshold: SEMANTIC_HIGHLIGHT_THRESHOLD,
        modelConfig: semanticModelConfigRef.current,
        isStale,
        // Apply snippets as each source resolves — a big section takes minutes
        // to fully enrich and the hover cards should improve as it goes.
        onPartial: (sources) => {
          if (isStale()) return;
          updateSection(id, { sources });
          // Store progress as it lands: a long section takes minutes and a
          // reload mid-run would otherwise discard everything done so far.
          pushHighlights(sources);
        },
      })
        .then((sources) => {
          if (isStale()) return;
          updateSection(id, { sources });
          pushHighlights(sources);
        })
        .catch(() => {
          /* highlighting is an enhancement; the plain excerpt remains */
        })
        .finally(() => enrichingRef.current.delete(id));
    },
    [updateSection, pushHighlights],
  );

  // Enrich one source now, because a hover card opened on a citation whose
  // excerpt has no highlights yet. The card re-renders from section state, so
  // it fills in while the user is still hovering.
  const requestSourceHighlight = useCallback(
    (sectionId: string, chunkId: string) => {
      if (!SEARCH_SEMANTIC_HIGHLIGHTS || !semanticModelConfigRef.current?.model) return;
      const key = `${sectionId}:${chunkId}`;
      if (onDemandRef.current.has(key)) return;
      const section = sectionsRef.current.find((sec) => sec.id === sectionId);
      // Matched by chunk, not index: the card shows the *display* source, whose
      // index is the global citation number, while section state keeps the
      // local research indices. Matching on index found nothing, so the card
      // sat on "Highlighting…" for ever.
      const source = section?.sources.find((src) => src.chunkId === chunkId);
      if (!section || !source || !source.text || source.claimMatches !== undefined) return;
      onDemandRef.current.add(key);
      const applyToSection = (enriched: SourceReference): void => {
        const cur = sectionsRef.current.find((sec) => sec.id === sectionId);
        if (!cur) return;
        updateSection(sectionId, {
          sources: cur.sources.map((src) => (src.chunkId === chunkId ? enriched : src)),
        });
      };
      void highlightOneSource({
        source,
        content: section.content,
        threshold: SEMANTIC_HIGHLIGHT_THRESHOLD,
        modelConfig: semanticModelConfigRef.current,
        // Paint each claim as it lands so the open card stops saying
        // "Highlighting…" after the first result, not the last.
        onProgress: applyToSection,
      })
        .then((enriched) => {
          applyToSection(enriched);
          pushHighlights([enriched]);
        })
        .catch(() => {
          /* the full excerpt remains as the fallback */
        })
        .finally(() => onDemandRef.current.delete(key));
    },
    [updateSection, pushHighlights],
  );

  const pushActivity = useCallback((id: string, ev: BriefActivityEvent) => {
    // Retain a deep log; the status box shows ~5 rows and scrolls for the rest.
    setSections((prev) =>
      prev.map((s) =>
        s.id === id ? { ...s, activity: [ev, ...s.activity].slice(0, 40) } : s,
      ),
    );
  }, []);

  const persist = useCallback(
    (next: SavedBrief[]) => {
      setHistory(next);
      try {
        localStorage.setItem(historyKey, JSON.stringify(next));
      } catch {
        /* storage may be unavailable; non-fatal */
      }
    },
    [historyKey],
  );

  const deleteBrief = useCallback(
    (id: string) => {
      if (remote) {
        deleteBriefRemote(id)
          .then(() => setHistory((prev) => prev.filter((e) => e.id !== id)))
          .catch((e) =>
            setError(e instanceof Error ? e.message : 'Could not delete the brief.'),
          );
        return;
      }
      persist(history.filter((e) => e.id !== id));
    },
    [remote, history, persist],
  );

  // Serialise remote saves: one in flight at a time. A save requested while one
  // runs is parked, one per brief (latest state wins — entries are rebuilt),
  // and sent as soon as the running one finishes. The queue only goes idle once
  // nothing is parked, so no save is left behind; refreshing the saved-brief
  // list happens after that, outside the queue.
  //
  // Each save carries its own brief: whether it updates or creates is decided
  // from that brief's id, never from which brief is open when it is sent. So a
  // save still queued when its brief is closed, or when another is opened,
  // still reaches its own brief — it can neither create a duplicate nor write
  // into the brief now open.
  const remoteSaveBusyRef = useRef(false);
  const remoteSavePendingRef = useRef<Map<string, SavedBrief>>(new Map());

  // Not locked itself: the save queue and citationsCall take the brief lock
  // around it.
  const saveRemoteOnce = useCallback(
    async (entry: SavedBrief): Promise<void> => {
      const serverId = serverIdsRef.current.get(entry.id);
      if (serverId) {
        const saved = await remoteCitationOp(serverId, { type: 'structure', brief: entry });
        lastSavedSigRef.current.set(serverId, savedSignature(entry));
        // The API renumbered for the structure it received (sections moved,
        // removed or added); show its numbering.
        if (briefIdRef.current === entry.id || briefIdRef.current === serverId) {
          applyRead(remoteToRead(saved));
        }
        return;
      }
      const created = await createBriefRemote({
        title: entry.title,
        query: entry.query || null,
        dataSource: dataSource || null,
        voiceProfileId: entry.voiceId ?? null,
        content: entry,
      });
      // Later saves of this brief, under its local id or its new server id,
      // update the row just created.
      serverIdsRef.current.set(entry.id, created.id);
      serverIdsRef.current.set(created.id, created.id);
      lastSavedSigRef.current.set(created.id, savedSignature(entry));
      // If the brief is still open, it now goes by its server id (URL, saves).
      if (briefIdRef.current === entry.id) {
        briefIdRef.current = created.id;
        applyRead(remoteToRead(created));
      }
    },
    [dataSource, applyRead],
  );
  const saveRemoteOnceRef = useRef(saveRemoteOnce);
  saveRemoteOnceRef.current = saveRemoteOnce;

  /** The brief as it would be saved right now. */
  const snapshotSaved = useCallback(
    (id: string): SavedBrief =>
      toSavedBrief({
        id,
        title: briefTitleRef.current,
        query: queryRef.current,
        sections: sectionsRef.current,
        outlineLog: outlineLogRef.current,
        numberHeadings: numberHeadingsRef.current,
        activityId: briefActivityIdRef.current,
        voiceId: briefVoiceIdRef.current,
        targetWords: targetWordsRef.current,
        instructions: instructionsRef.current,
      }),
    [],
  );

  // A browser-held brief's stored form, kept in the saved-briefs history.
  const persistStored = useCallback(
    (content: StoredBrief) => {
      persist(
        [content as SavedBrief, ...historyRef.current.filter((e) => e.id !== content.id)].slice(
          0,
          10,
        ),
      );
    },
    [persist],
  );

  /**
   * Apply one citation operation to the open brief and return the brief as
   * the API computed it. A signed-in brief is saved first if it has no
   * server row yet (a section can finish before the first autosave); a
   * browser-held brief sends its stored form and keeps what comes back.
   */
  const citationsCall = useCallback(
    (op: CitationOp, briefId: string | null = briefIdRef.current): Promise<BriefContentRead> =>
      withBriefLock(async () => {
        if (!briefId) throw new Error('No brief is open');
        if (remote) {
          if (!serverIdsRef.current.get(briefId)) {
            await saveRemoteOnceRef.current(snapshotSaved(briefId));
          }
          const serverId = serverIdsRef.current.get(briefId);
          if (!serverId) throw new Error('The brief could not be saved');
          return remoteToRead(await remoteCitationOp(serverId, op));
        }
        let stored = storedContentRef.current;
        if (!stored) {
          stored = (
            await applyCitationOp(emptyStoredBrief(), {
              type: 'structure',
              brief: snapshotSaved(briefId),
            })
          ).content;
        }
        const { content, read } = await applyCitationOp(stored, op);
        storedContentRef.current = content;
        persistStored(content);
        return read;
      }),
    [remote, withBriefLock, snapshotSaved, persistStored],
  );
  citationsCallRef.current = citationsCall;

  /** One stored original of the open brief, for the Log. */
  const getSectionRunDetail = useCallback(
    async (sectionId: string, runId: string): Promise<SectionRunDetail> => {
      const id = briefIdRef.current;
      if (!id) throw new Error('No brief is open');
      if (remote) {
        const serverId = serverIdsRef.current.get(id);
        if (!serverId) throw new Error('The brief is not saved yet');
        return getRunDetail(serverId, sectionId, runId);
      }
      const stored = storedContentRef.current;
      if (!stored) throw new Error('The brief is not saved yet');
      return getLocalRunDetail(stored, sectionId, runId);
    },
    [remote],
  );

  const pushRemoteSave = useCallback(
    (entry: SavedBrief) => {
      const pending = remoteSavePendingRef.current;
      pending.set(serverIdsRef.current.get(entry.id) ?? entry.id, entry);
      if (remoteSaveBusyRef.current) return;
      const drain = async (): Promise<void> => {
        for (let next = pending.entries().next(); !next.done; next = pending.entries().next()) {
          const [key, queued] = next.value;
          pending.delete(key);
          await withBriefLock(() => saveRemoteOnce(queued));
        }
      };
      const run = () => {
        remoteSaveBusyRef.current = true;
        drain()
          .catch((e) => setError(e instanceof Error ? e.message : 'Could not save the brief.'))
          .finally(() => {
            remoteSaveBusyRef.current = false;
            // A save parked after the loop's last check (or while a save
            // failed) still goes out before the queue goes idle.
            if (pending.size) {
              run();
              return;
            }
            refreshRemoteHistory().catch((e) =>
              setError(e instanceof Error ? e.message : 'Could not load your briefs.'),
            );
          });
      };
      run();
    },
    [saveRemoteOnce, refreshRemoteHistory, withBriefLock],
  );

  // Save the brief's structure and settings; the API renumbers for them and
  // writes the brief's Activity row from what it stored. Nothing is sent when
  // nothing changed since the brief was opened or last saved.
  const saveCurrent = useCallback(() => {
    const id = briefIdRef.current;
    if (!id || !sectionsRef.current.length) return;
    // Never write back a brief someone else owns (viewer-only).
    if (remote && !canEditRef.current) return;
    const entry = snapshotSaved(id);
    const key = serverIdsRef.current.get(id) ?? id;
    if (lastSavedSigRef.current.get(key) === savedSignature(entry)) return;
    if (remote) {
      pushRemoteSave(entry);
      return;
    }
    lastSavedSigRef.current.set(key, savedSignature(entry));
    citationsCall({ type: 'structure', brief: entry }, id)
      .then((read) => {
        if (briefIdRef.current === id) applyRead(read);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not save the brief.'));
  }, [remote, pushRemoteSave, snapshotSaved, citationsCall, applyRead]);

  // A new brief starts with no citation state of its own.
  const resetCitationState = useCallback(() => {
    storedContentRef.current = null;
    readStampRef.current = 0;
    manualDirtyRef.current.clear();
    setReferences([]);
    setReferenceGroups([]);
    setReferenceGroupingState('passage');
    setSourceCount(0);
  }, []);

  // Auto-save once a brief exists (outline generated or manual start) so it
  // appears in Saved Briefs right away and keeps tracking title/content edits.
  useEffect(() => {
    if (stage === 'seed' || !briefIdRef.current) return;
    const t = setTimeout(() => saveCurrent(), 500);
    return () => clearTimeout(t);
  }, [stage, briefTitle, sections, numberHeadings, instructions, saveCurrent]);

  // ---- outline ----
  // Generate headings by first running a deep-research survey of the document
  // library for the topic (streaming the same SCAN/READ activity as section
  // research), then asking the model for headings grounded in what it found.
  const generateOutline = useCallback(async (overrides?: {
    topic?: string;
    instructions?: string;
    numHeadings?: number;
  }) => {
    // Overrides let callers (the New-brief modal) pass values set in the same
    // tick — the state updates land after this closure captured the old values.
    const topic = (overrides?.topic ?? query).trim();
    if (!topic) return;
    setError(null);
    setOutlineLoading(true);
    setGeneratingActivity([]);
    const controller = new AbortController();
    abortRef.current = controller;
    const guidance = (overrides?.instructions ?? instructions).trim();
    let gathered: BriefSourceSample[] = [];
    // Allocate the new brief's activity id up front so the survey and outline
    // LLM calls record their token usage onto it server-side (tokens are
    // spent even when outline generation is aborted midway). Kept LOCAL until
    // the outline succeeds, so a failed attempt never re-points a currently
    // loaded brief's activity row.
    const activityId = newActivityId();
    try {
      const surveyQuery = guidance
        ? `Research the document library to inform an evidence brief on "${topic}". Follow these author instructions closely and let them drive what you search for — focus your queries on the specific angles, sectors, regions, populations and outcomes the instructions call for, not just generic restatements of the topic: ${guidance}`
        : `Research the document library to inform an evidence brief on "${topic}".`;
      await runDeepResearch({
        apiBaseUrl,
        dataSource,
        query: surveyQuery,
        doneLabel: 'Document library surveyed',
        assistantModelConfig,
        rerankerModel: rerankerModelRef.current,
        searchSettings: searchSettingsRef.current,
        activityId,
        signal: controller.signal,
        handlers: {
          onActivity: (ev) => setGeneratingActivity((prev) => [ev, ...prev].slice(0, 40)),
          onProgress: () => {},
          onToken: () => {},
          onSources: (srcs) => {
            gathered = srcs.map((s) => ({
              title: s.title,
              snippet: (s.text || '').slice(0, 240),
            }));
          },
          onDone: () => {},
          onError: (m) => setError(m),
        },
      });
      if (controller.signal.aborted) return;
      setGeneratingActivity((prev) =>
        [{ tag: 'DRAFT' as const, text: 'Drafting outline' }, ...prev].slice(0, 40),
      );
      const outline = await requestBriefOutline({
        apiBaseUrl,
        dataSource,
        topic,
        instructions: guidance || null,
        numHeadings: overrides?.numHeadings ?? numHeadings,
        model: assistantModelConfig?.model ?? null,
        sources: gathered,
        activityId,
        signal: controller.signal,
      });
      briefIdRef.current = uid();
      briefActivityIdRef.current = activityId;
      resetCitationState();
      setBriefDataSource(null);
      setCanEdit(true);
      setOwnerName(null);
      setBriefTitle(toTitleCase(topic));
      setSections(
        outline.headings
          .filter((h) => h.title)
          .map((h) => makeSection(toTitleCase(h.title), h.level)),
      );
      setStage('outline');
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : 'Could not generate an outline.');
      }
    } finally {
      setOutlineLoading(false);
    }
  }, [apiBaseUrl, dataSource, query, instructions, numHeadings, assistantModelConfig, resetCitationState]);

  const startManual = useCallback(() => {
    briefIdRef.current = uid();
    briefActivityIdRef.current = newActivityId();
    resetCitationState();
    setBriefDataSource(null);
    setCanEdit(true);
    setOwnerName(null);
    setBriefTitle(DEFAULT_BRIEF_TITLE);
    setSections(
      // Placeholder samples: research stays disabled until the user edits them.
      ['Background & definitions', 'Key findings', 'Recommendations'].map((t) =>
        makeSection(t, 1, true),
      ),
    );
    setStage('outline');
  }, [resetCitationState]);

  // Start a brief from a template's headings, with each heading's saved text,
  // prompt, voice and length.
  const startFromTemplate = useCallback(
    (title: string, headings: BriefTemplateHeading[]) => {
      briefIdRef.current = uid();
      briefActivityIdRef.current = newActivityId();
      resetCitationState();
      setBriefDataSource(null);
      setCanEdit(true);
      setOwnerName(null);
      setBriefTitle(title.trim() || DEFAULT_BRIEF_TITLE);
      setSections(headings.map(sectionFromTemplateHeading));
      setStage('outline');
    },
    [resetCitationState],
  );

  // ---- outline editing ----
  const addSection = useCallback(() => {
    const t = newHeading.trim();
    if (!t) return;
    setSections((prev) => [...prev, makeSection(t)]);
    setNewHeading('');
  }, [newHeading]);

  // Append a named top-level heading (the TOC prompts for the name first).
  const addHeading = useCallback((title: string) => {
    const name = title.trim();
    if (!name) return;
    setSections((prev) => [...prev, makeSection(name, 1, false)]);
  }, []);

  // Insert a named sub-heading after the given heading and its existing children.
  const addSubHeading = useCallback((parentId: string, title: string) => {
    const name = title.trim();
    if (!name) return;
    setSections((prev) => {
      const idx = prev.findIndex((s) => s.id === parentId);
      if (idx < 0) return prev;
      let insertAt = idx + 1;
      while (insertAt < prev.length && prev[insertAt].level === 2) insertAt++;
      const next = [...prev];
      next.splice(insertAt, 0, makeSection(name, 2, false));
      return next;
    });
  }, []);

  const removeSection = useCallback((id: string) => {
    setSections((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const reorderSiblings = useCallback((draggedId: string, targetId: string) => {
    setSections((prev) => reorderSiblingSections(prev, draggedId, targetId));
  }, []);

  const indentSection = useCallback((id: string) => {
    setSections((prev) => {
      const i = prev.findIndex((s) => s.id === id);
      if (i <= 0) return prev; // first item must stay top-level
      return prev.map((s) => (s.id === id ? { ...s, level: s.level === 2 ? 1 : 2 } : s));
    });
  }, []);

  // Editing a heading clears its "sample" flag (it's now the user's own).
  const editTitle = useCallback(
    (id: string, title: string) => updateSection(id, { title, sample: false }),
    [updateSection],
  );

  // A manual edit changes the display text on screen; it is recorded as a
  // run (see commitManualEdit) when the editor is left.
  const editContent = useCallback(
    (id: string, content: string) => {
      manualDirtyRef.current.add(id);
      updateSection(id, { content });
    },
    [updateSection],
  );

  // ---- research engine ----
  // Condense a finished section that overshot its length target: one AI edit
  // of the current draft (sources and [n] markers unchanged), recorded in the
  // section's log. The long draft stays on screen, greyed, until the condensed
  // text arrives; on failure the long draft is kept and the error surfaced.
  const condenseSection = useCallback(
    async (
      id: string,
      // The just-recorded section as the API returned it: its display text
      // and the numbering that text carries. Passed explicitly: the state
      // update that stored them may not have rendered into sectionsRef yet.
      priorContent: string,
      priorSources: SourceReference[],
      target: number,
      words: number,
      signal: AbortSignal,
    ): Promise<void> => {
      const section = sectionsRef.current.find((s) => s.id === id);
      if (!section || signal.aborted) return;
      updateSection(id, { status: 'researching', progress: 95, revising: true });
      pushActivity(id, { tag: 'DRAFT', text: `Condensing to about ${target} words (was ${words})` });
      const instruction = buildCondenseInstruction(target, words);
      try {
        const revised = await requestBriefRevise({
          apiBaseUrl,
          dataSource,
          content: priorContent,
          instruction,
          voiceInstructions: voiceInstructionsFor(section.voiceId),
          introducesSubSections: introSubSectionsOf(sectionsRef.current, id),
          activityId: briefActivityIdRef.current,
          signal,
        });
        if (signal.aborted) return;
        // Recorded as a run of the section, written against the numbers the
        // draft carried; the API numbers it and writes the Log row.
        const read = await citationsCall({
          type: 'run',
          sectionId: id,
          run: { mode: 'condense', content: revised, instruction, basedOn: basedOnOf(priorSources) },
        });
        if (signal.aborted) return;
        const shown = read.sections.find((s) => s.id === id);
        const shownContent = shown?.renumbered.content || '';
        const doneAt = Date.now();
        updateSection(id, {
          status: 'done',
          progress: 100,
          introHeadingWarning: introWarningFor(sectionsRef.current, id, revised),
          revising: undefined,
        });
        applyRead(read);
        pushActivity(id, { tag: 'DONE', text: `Condensed to ${countWords(shownContent)} words` });
        researchTokenRef.current[id] = doneAt;
        setTimeout(
          () => enrichSectionHighlights(id, doneAt, shownContent, shown?.renumbered.sources || []),
          0,
        );
      } catch (e) {
        if (signal.aborted) return;
        updateSection(id, { status: 'done', progress: 100, revising: undefined });
        setError(
          `“${section.title}” came back at ${words} words against a target of ${target} and could not be condensed: ${
            e instanceof Error ? e.message : 'condense failed'
          }`,
        );
      }
    },
    [
      apiBaseUrl,
      dataSource,
      updateSection,
      pushActivity,
      voiceInstructionsFor,
      enrichSectionHighlights,
      citationsCall,
      applyRead,
    ],
  );

  const researchOne = useCallback(
    (
      id: string,
      context: string | null,
      signal: AbortSignal,
      // `attempt` counts re-runs of an introduction that came back with headings.
      opts?: { mode?: SectionResearchMode; instruction?: string | null; attempt?: number },
    ): Promise<void> => {
      const list = sectionsRef.current;
      const idx = list.findIndex((s) => s.id === id);
      const section = list[idx];
      if (!section) return Promise.resolve();
      const mode: SectionResearchMode = opts?.mode ?? 'generate';
      const isRevise = mode === 'edit' || mode === 'update';
      const instruction = (opts?.instruction || '').trim() || null;
      const attempt = opts?.attempt ?? 0;
      // The current display text, for a revise to work from.
      const priorContent = section.content;
      // Update: only surface sources newer than the last time this section ran.
      const publishedAfterIso =
        mode === 'update' && section.lastResearchedAt
          ? new Date(section.lastResearchedAt).toISOString()
          : null;
      // For a sub-section (level 2), find the nearest preceding level-1 heading
      // so its research stays scoped to the right parent.
      let parentTitle: string | null = null;
      if (section.level === 2) {
        for (let i = idx - 1; i >= 0; i--) {
          if (list[i].level === 1) {
            parentTitle = list[i].title;
            break;
          }
        }
      }
      // Generate clears the section; Edit/Update keep the current draft in place
      // (rendered greyed-out, still in the citation numbering) and swap
      // atomically on completion.
      // A re-run keeps the activity so far, including why it re-ran.
      const activityReset = attempt > 0 ? {} : { activity: [] };
      updateSection(
        id,
        isRevise
          ? { status: 'researching', progress: 4, ...activityReset, revising: true }
          : { status: 'researching', progress: 4, content: '', sources: [], ...activityReset },
      );
      const briefTopic = queryRef.current.trim() || briefTitleRef.current;
      // A top-level heading with sub-headings is their introduction: the
      // backend writes it without headings or their detail, at the shorter
      // introduction length unless the section has its own (see briefIntro.ts).
      const subSections = subSectionTitles(list, id);
      const sectionTarget = sectionTargetWords(section.targetWords, subSections, targetWordsRef.current);
      // Set by onDone when the finished section overshoots its target; the
      // research promise waits for it so a document-wide run stays sequential.
      let condensePass: Promise<void> = Promise.resolve();
      // Set by onDone when an introduction came back with headings and has
      // re-runs left; the promise then researches it again instead.
      let rerun = false;
      // Set by onDone: the API recording the run and returning the brief.
      let postRun: Promise<void> = Promise.resolve();
      return researchBriefSection({
        apiBaseUrl,
        dataSource,
        heading: section.title,
        context,
        briefTopic,
        briefInstructions: instructionsRef.current.trim() || null,
        parentTitle,
        assistantModelConfig,
        rerankerModel: rerankerModelRef.current,
        searchSettings: searchSettingsRef.current,
        activityId: briefActivityIdRef.current,
        mode,
        existingContent: isRevise ? priorContent : null,
        instruction,
        publishedAfterIso,
        voiceInstructions: voiceInstructionsFor(section.voiceId),
        targetWords: sectionTarget,
        introducesSubSections: subSections.length ? subSections : null,
        // The whole document structure (plus a gist of written sections), so
        // this section stays in scope and doesn't duplicate the others.
        outlineContext: buildOutlineContext(
          list.map((s) => ({
            id: s.id,
            title: s.title,
            level: s.level,
            content: s.status === 'done' ? s.content : undefined,
          })),
          id,
        ),
        signal,
        handlers: {
          onActivity: (ev) => pushActivity(id, ev),
          onProgress: (p) => updateSection(id, { progress: p }),
          // Keep the old draft visible during a revise; swap only at onDone.
          onToken: (t) => {
            if (!isRevise) updateSection(id, { content: t });
          },
          onSources: (s) => {
            if (!isRevise) updateSection(id, { sources: s });
          },
          onDone: ({ content, sources, runId }) => {
            // A run that read sources but answered with process narration
            // ("I'll go research that…") instead of the section is a failure —
            // surface it and keep the section pending rather than storing it.
            if (!isRevise && isLikelyNonAnswer(content, sources.length, sectionTarget)) {
              updateSection(id, { status: 'pending', progress: 0 });
              setError(
                `The model did not return researched content for “${section.title}” — please try again.`,
              );
              return;
            }
            // An introduction must not have headings of its own: re-run it
            // while re-runs are left, then keep it with a visible warning.
            const intro = introOutcome(subSections.length, content, attempt);
            if (intro.rerun) {
              rerun = true;
              pushActivity(id, { tag: 'DRAFT', text: rerunActivityText(intro.headings, attempt) });
              return;
            }
            // Record the agent's output with the API exactly as streamed. The
            // API maps its sources into the brief, renumbers every section,
            // writes the Log row and returns the brief to show.
            const run: RunPayload = {
              mode,
              content,
              sources,
              runId,
              question: mode === 'generate' ? section.title : undefined,
              instruction: mode === 'generate' ? context || undefined : instruction || undefined,
              note: introAuditNote(intro.headings, attempt),
            };
            postRun = citationsCall({ type: 'run', sectionId: id, run })
              .then((read) => {
                if (signal.aborted) return;
                const shown = read.sections.find((s) => s.id === id);
                const doneAt = Date.now();
                updateSection(id, {
                  status: 'done',
                  progress: 100,
                  introHeadingWarning: intro.headings || undefined,
                  lastResearchedAt: doneAt,
                  revising: undefined,
                  pendingRunId: isRevise ? shown?.currentRunId ?? undefined : undefined,
                  lastChangeKind: isRevise ? mode : undefined,
                });
                applyRead(read);
                const shownContent = shown?.renumbered.content || '';
                const shownSources = shown?.renumbered.sources || [];
                // Async: LLM-highlight the cited excerpts. The token is recorded
                // synchronously so the deferred run can tell if it was superseded.
                researchTokenRef.current[id] = doneAt;
                setTimeout(() => enrichSectionHighlights(id, doneAt, shownContent, shownSources), 0);
                // A model only approximates a word count: a section that overshoots
                // its target by more than the tolerance is condensed to it.
                const words = countWords(shownContent);
                if (sectionTarget && exceedsTarget(words, sectionTarget)) {
                  condensePass = condenseSection(
                    id,
                    shownContent,
                    shownSources,
                    sectionTarget,
                    words,
                    signal,
                  );
                }
              })
              .catch((e) => {
                if (signal.aborted) return;
                // The research is lost unless the API recorded it: say so.
                updateSection(
                  id,
                  isRevise
                    ? { status: 'done', progress: 100, revising: undefined }
                    : { status: 'pending', progress: 0 },
                );
                setError(
                  `“${section.title}” was researched but could not be saved: ${
                    e instanceof Error ? e.message : 'the citation service failed'
                  }`,
                );
              });
          },
          onError: (m) => {
            // A revise keeps its previous good content; a fresh research reverts.
            updateSection(
              id,
              isRevise
                ? { status: 'done', progress: 100, revising: undefined }
                : { status: 'pending', progress: 0 },
            );
            setError(m);
          },
        },
      })
        .catch(() =>
          updateSection(
            id,
            isRevise
              ? { status: 'done', progress: 100, revising: undefined }
              : { status: 'pending', progress: 0 },
          ),
        )
        .then(() => postRun)
        .then(() =>
          rerun
            ? researchOneRef.current(id, context, signal, { ...opts, attempt: attempt + 1 })
            : condensePass,
        );
    },
    [
      apiBaseUrl,
      dataSource,
      assistantModelConfig,
      updateSection,
      pushActivity,
      voiceInstructionsFor,
      enrichSectionHighlights,
      condenseSection,
      citationsCall,
      applyRead,
    ],
  );
  // researchOne re-runs itself for an introduction that came back with
  // headings; the ref gives it the current function without a self-reference.
  researchOneRef.current = researchOne;

  // `overrides` come from the Regenerate-all modal. They are written to the
  // refs as well as to state, because the research loop below reads the refs
  // and React will not have committed the setState by the time it runs.
  const startResearch = useCallback(
    async (overrides?: {
      instructions?: string;
      voiceId?: string | null;
      targetWords?: number | null;
    }) => {
      if (overrides?.instructions !== undefined) {
        instructionsRef.current = overrides.instructions;
        setInstructions(overrides.instructions);
      }
      if (overrides?.voiceId !== undefined) {
        briefVoiceIdRef.current = overrides.voiceId;
        setBriefVoiceId(overrides.voiceId);
      }
      if (overrides?.targetWords !== undefined) setTargetWords(overrides.targetWords);
      // Sub-sections before their introduction, so it can see what they say.
      const ids = researchOrder(sectionsRef.current);
      if (!ids.length) return;
      setError(null);
      const controller = new AbortController();
      abortRef.current = controller;
      setStage('research');
      for (const id of ids) {
        if (controller.signal.aborted) return;
        // Each section carries its own author instructions (set in its Research
        // panel), so a document-wide run honours what the user typed per section.
        const guidance = sectionsRef.current.find((s) => s.id === id)?.guidance?.trim() || null;
        await researchOne(id, guidance, controller.signal);
      }
      if (!controller.signal.aborted) {
        setStage('done');
        saveCurrent();
      }
    },
    [researchOne, saveCurrent, setTargetWords],
  );

  // Run "Get Updates" (fold in sources newer than each section's last run) on
  // every already-researched section, sequentially — the doc-wide counterpart to
  // the per-section AI Get Updates.
  const updateAll = useCallback(async () => {
    const ids = sectionsRef.current
      .filter((s) => s.status === 'done' && !!s.content)
      .map((s) => s.id);
    if (!ids.length) return;
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    setStage('research');
    for (const id of ids) {
      if (controller.signal.aborted) return;
      await researchOne(id, null, controller.signal, { mode: 'update' });
    }
    if (!controller.signal.aborted) {
      setStage('done');
      saveCurrent();
    }
  }, [researchOne, saveCurrent]);

  // Abort all in-flight research and return to a stable, editable state: any
  // section mid-research reverts to pending; completed sections are kept.
  const stopResearch = useCallback(() => {
    abortRef.current?.abort();
    setSections((prev) =>
      prev.map((s) =>
        s.status === 'researching'
          ? { ...s, status: 'pending', progress: 0, activity: [] }
          : s,
      ),
    );
    setStage('outline');
  }, []);

  const finishIfComplete = useCallback(() => {
    const all = sectionsRef.current.length > 0 && sectionsRef.current.every((s) => s.status === 'done');
    if (all) {
      setStage('done');
      saveCurrent();
    }
  }, [saveCurrent]);

  // Research (or re-research) a single section with optional guidance. Used for
  // both pending sections (build one at a time) and done sections (regenerate).
  const regenerate = useCallback(
    async (id: string, context: string | null) => {
      setRegenFor(null);
      setRegenText('');
      setError(null);
      if (stage === 'outline') setStage('research');
      let controller = abortRef.current;
      if (!controller || controller.signal.aborted) controller = new AbortController();
      abortRef.current = controller;
      await researchOne(id, context, controller.signal);
      finishIfComplete();
    },
    [stage, researchOne, finishIfComplete],
  );

  // Edit (surgical): a single backend LLM copy-edit of the CURRENT draft — no
  // deep research — so the section keeps its wording + inline [n] citations
  // (sources unchanged) and only the smallest necessary changes are made. The
  // result is recorded as a run; the previous run stays for Reject.
  const editSectionAI = useCallback(
    async (id: string, instruction: string) => {
      const section = sectionsRef.current.find((s) => s.id === id);
      if (!section || !instruction.trim()) return;
      const priorContent = section.content;
      const basedOn = basedOnOf(section.sources);
      setError(null);
      const controller = new AbortController();
      abortRef.current = controller;
      updateSection(id, {
        status: 'researching',
        progress: 35,
        activity: [{ tag: 'DRAFT', text: 'Editing this section…' }],
        revising: true,
      });
      try {
        const revised = await requestBriefRevise({
          apiBaseUrl,
          dataSource,
          content: priorContent,
          instruction: instruction.trim(),
          voiceInstructions: voiceInstructionsFor(section.voiceId),
          introducesSubSections: introSubSectionsOf(sectionsRef.current, id),
          activityId: briefActivityIdRef.current,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        // Recorded as a run written against the numbers on screen; the API
        // keeps the model's text as returned, numbers it and writes the Log row.
        const read = await citationsCall({
          type: 'run',
          sectionId: id,
          run: { mode: 'edit', content: revised, instruction: instruction.trim(), basedOn },
        });
        if (controller.signal.aborted) return;
        const shown = read.sections.find((s) => s.id === id);
        const doneAt = Date.now();
        updateSection(id, {
          status: 'done',
          progress: 100,
          introHeadingWarning: introWarningFor(sectionsRef.current, id, revised),
          lastResearchedAt: doneAt,
          revising: undefined,
          pendingRunId: shown?.currentRunId ?? undefined,
          lastChangeKind: 'edit',
        });
        applyRead(read);
        researchTokenRef.current[id] = doneAt;
        setTimeout(
          () =>
            enrichSectionHighlights(
              id,
              doneAt,
              shown?.renumbered.content || '',
              shown?.renumbered.sources || [],
            ),
          0,
        );
      } catch (e) {
        if (!controller.signal.aborted) {
          updateSection(id, { status: 'done', progress: 100, revising: undefined });
          setError(e instanceof Error ? e.message : 'Edit failed');
        }
      }
    },
    [
      apiBaseUrl,
      dataSource,
      updateSection,
      voiceInstructionsFor,
      enrichSectionHighlights,
      citationsCall,
      applyRead,
    ],
  );

  // Dispatch the two AI actions on a DONE section: Edit → surgical revise;
  // Update → deep research constrained to sources newer than the last run.
  const reviseSection = useCallback(
    async (id: string, mode: 'edit' | 'update', instruction: string | null) => {
      setRegenFor(null);
      setRegenText('');
      setError(null);
      if (stage === 'outline') setStage('research');
      if (mode === 'edit') {
        await editSectionAI(id, (instruction || '').trim());
        finishIfComplete();
        return;
      }
      let controller = abortRef.current;
      if (!controller || controller.signal.aborted) controller = new AbortController();
      abortRef.current = controller;
      await researchOne(id, null, controller.signal, { mode, instruction });
      finishIfComplete();
    },
    [stage, editSectionAI, researchOne, finishIfComplete],
  );

  // Keep Edits: accept the revised run; it stays current.
  const dismissChanges = useCallback(
    (id: string) => updateSection(id, { pendingRunId: undefined, lastChangeKind: undefined }),
    [updateSection],
  );

  // Reject Edits: the API makes the run before the revision current again
  // (its Log row goes with it) and renumbers the brief.
  const rejectChanges = useCallback(
    async (id: string) => {
      const runId = sectionsRef.current.find((s) => s.id === id)?.pendingRunId;
      if (!runId) return;
      updateSection(id, { pendingRunId: undefined, lastChangeKind: undefined });
      try {
        applyRead(await citationsCall({ type: 'reject', sectionId: id, runId }));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not reject the edits.');
      }
    },
    [updateSection, citationsCall, applyRead],
  );

  // A manual edit, once the editor is left, is recorded as a run of the
  // section so the stored brief holds what the reader sees.
  const commitManualEdit = useCallback(
    async (id: string) => {
      if (!manualDirtyRef.current.has(id)) return;
      manualDirtyRef.current.delete(id);
      const section = sectionsRef.current.find((s) => s.id === id);
      if (!section) return;
      try {
        const read = await citationsCall({
          type: 'run',
          sectionId: id,
          run: { mode: 'manual', content: section.content, basedOn: basedOnOf(section.sources) },
        });
        applyRead(read);
        const shown = read.sections.find((s) => s.id === id);
        const doneAt = Date.now();
        researchTokenRef.current[id] = doneAt;
        setTimeout(
          () =>
            enrichSectionHighlights(
              id,
              doneAt,
              shown?.renumbered.content || '',
              shown?.renumbered.sources || [],
            ),
          0,
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not save the edit.');
      }
    },
    [citationsCall, applyRead, enrichSectionHighlights],
  );

  // ---- history ----
  // Materialise a SavedBrief into the working state. `access` marks whether the
  // user owns it (edit) or views a shared copy (read-only).
  const applyLoadedBrief = useCallback(
    (
      entry: BriefContentRead,
      access: {
        canEdit: boolean;
        ownerName: string | null;
        saved: boolean;
        dataSource: string | null;
      },
    ) => {
      abortRef.current?.abort();
      briefIdRef.current = entry.id;
      if (access.saved) serverIdsRef.current.set(entry.id, entry.id);
      readStampRef.current = 0;
      manualDirtyRef.current.clear();
      setBriefDataSource(access.dataSource);
      briefActivityIdRef.current = entry.activityId || newActivityId();
      setBriefTitle(entry.title);
      setQuery(entry.query);
      setCanEdit(access.canEdit);
      setOwnerName(access.ownerName);
      setBriefVoiceId(entry.voiceId ?? null);
      setTargetWords(entry.targetWords ?? null);
      // Briefs saved before instructions were kept have none.
      setInstructions(entry.instructions ?? '');
      const sections: BriefSection[] = entry.sections.map((h: BriefSectionRead) => ({
        ...makeSection(h.title, h.level),
        // Keep the saved id: comments anchor to it, and a fresh id each load
        // would orphan every thread.
        ...(h.id ? { id: h.id } : {}),
        status: h.status === 'done' ? 'done' : 'pending',
        progress: h.status === 'done' ? 100 : 0,
        // Shown as the API returned it: the renumbered text and the display
        // sources behind its numbers.
        content: h.status === 'done' ? h.renumbered?.content || '' : '',
        sources: h.status === 'done' ? h.renumbered?.sources || [] : [],
        unresolved: h.renumbered?.unresolved || [],
        runs: h.runs || [],
        currentRunId: h.currentRunId ?? null,
        audit: h.audit || [],
        lastResearchedAt: h.lastResearchedAt,
        voiceId: h.voiceId ?? null,
        guidance: h.guidance || '',
        targetWords: h.targetWords ?? null,
        introHeadingWarning: h.introHeadingWarning || undefined,
      }));
      setSections(sections);
      setReferences(entry.references || []);
      setReferenceGroups(entry.referenceGroups || []);
      setReferenceGroupingState(entry.referenceGrouping || 'passage');
      setSourceCount(entry.sourceCount || 0);
      // Record the brief as opened, so the autosave sends nothing until
      // something actually changes (opening never writes a brief back).
      lastSavedSigRef.current.set(
        entry.id,
        savedSignature(
          toSavedBrief({
            id: entry.id,
            title: entry.title,
            query: entry.query,
            sections,
            outlineLog: entry.outlineLog || [],
            numberHeadings: entry.numberHeadings ?? false,
            activityId: briefActivityIdRef.current,
            voiceId: entry.voiceId ?? null,
            targetWords: entry.targetWords ?? null,
            instructions: entry.instructions ?? '',
          }),
        ),
      );
      setGeneratingActivity(entry.outlineLog || []);
      setNumberHeadings(entry.numberHeadings ?? false);
      setStage('done');
      setHistoryOpen(false);
      resumeRef.current = entry.id;
    },
    [setTargetWords],
  );

  // Whether this tab is in the foreground; the opportunistic highlight backfill
  // only runs here (see below).
  const [tabVisible, setTabVisible] = useState(
    () => typeof document === 'undefined' || document.visibilityState !== 'hidden',
  );
  useEffect(() => {
    const onVisibility = (): void => setTabVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  // Highlight enrichment runs in the browser after a section completes, so
  // reloading or navigating away mid-run leaves cited sources unenriched for
  // good. Opening a brief resumes those gaps, one section at a time.
  useEffect(() => {
    const briefId = resumeRef.current;
    if (!briefId || !SEARCH_SEMANTIC_HIGHLIGHTS) return;
    // The highlight model comes from the model combo, which App applies after
    // mount. Starting first sends model=null and every call fails, so wait —
    // this effect re-runs on the render that delivers the config.
    if (!semanticModelConfigRef.current?.model) return;
    // Backfill only from the visible tab. Every open tab showing a brief would
    // otherwise run the same backfill, multiplying API load and exhausting the
    // browser's per-origin connections (which stalls page loads).
    if (!tabVisible) return;
    resumeRef.current = null;
    void (async () => {
      // Most recently researched first: that is the section the user is
      // looking at, and enriching in document order left it until last.
      const order = sectionsRef.current
        .map((sec) => ({ id: sec.id, at: sec.lastResearchedAt ?? 0 }))
        .sort((a, b) => b.at - a.at);
      for (const { id } of order) {
        if (briefIdRef.current !== briefId) return;
        // A pass started by research owns this section; starting a second one
        // here would overwrite its token and make it stop mid-run.
        if (enrichingRef.current.has(id)) continue;
        // Re-read: research finishing during the backfill replaces a section's
        // content and sources, and the snapshot would enrich the old set.
        const section = sectionsRef.current.find((s) => s.id === id);
        if (!section || section.status !== 'done' || !section.content) continue;
        const pending = section.sources.some((src) => !!src.text && src.claimMatches === undefined);
        if (!pending) continue;
        // Keep any token already recorded so a run started by research retains
        // ownership; only invent one when the section has none.
        const token = researchTokenRef.current[id] ?? section.lastResearchedAt ?? Date.now();
        researchTokenRef.current[id] = token;
        await enrichSectionHighlights(id, token, section.content, section.sources);
      }
    })();
  });

  const loadBrief = useCallback(
    (entry: SavedBrief) => {
      if (remote) {
        // History rows are stubs — fetch the full brief (with access info).
        getBriefRemote(entry.id)
          .then((full) =>
            applyLoadedBrief(remoteToRead(full), {
              canEdit: full.can_edit,
              ownerName: full.owner_name,
              saved: true,
              dataSource: full.data_source,
            }),
          )
          .catch((e) =>
            setError(e instanceof Error ? e.message : 'Could not open the brief.'),
          );
        return;
      }
      // A browser-held brief: the API renders its stored form. One saved
      // before citation format 2 is converted first — explicitly, never read
      // as it is.
      const stored = (historyRef.current.find((e) => e.id === entry.id) ?? entry) as StoredBrief;
      const op: CitationOp =
        stored.citationsVersion === BRIEF_CITATIONS_VERSION ? { type: 'read' } : { type: 'convert' };
      applyCitationOp(stored, op)
        .then(({ content, read }) => {
          applyLoadedBrief(read, { canEdit: true, ownerName: null, saved: false, dataSource: null });
          storedContentRef.current = content;
          if (op.type === 'convert') persistStored(content);
        })
        .catch((e) => setError(e instanceof Error ? e.message : 'Could not open the brief.'));
    },
    [remote, applyLoadedBrief, persistStored],
  );

  // Open a server brief by id (Brief Central cards and /brief/<id> URLs).
  const openBriefById = useCallback(
    (id: string) => loadBrief({ id } as SavedBrief),
    [loadBrief],
  );

  // Duplicate a saved brief under a new id and open the copy.
  const cloneBrief = useCallback(
    (entry: SavedBrief) => {
      if (remote) {
        // The server copies the brief whole (runs, sources, numbering) and
        // gives the copy its own activity record.
        copyBriefRemote(entry.id)
          .then(async (created) => {
            await refreshRemoteHistory();
            applyLoadedBrief(remoteToRead(created), {
              canEdit: true,
              ownerName: null,
              saved: true,
              dataSource: created.data_source,
            });
          })
          .catch((e) =>
            setError(e instanceof Error ? e.message : 'Could not copy the brief.'),
          );
        return;
      }
      const stored = (historyRef.current.find((e) => e.id === entry.id) ?? entry) as StoredBrief;
      const copy = {
        ...stored,
        id: uid(),
        title: `${entry.title} (copy)`,
        date: Date.now(),
        activityId: newActivityId(), // a clone is its own brief → its own activity row
      } as SavedBrief;
      persist([copy, ...historyRef.current].slice(0, 10));
      loadBrief(copy);
    },
    [remote, persist, loadBrief, applyLoadedBrief, refreshRemoteHistory],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    briefIdRef.current = null;
    briefActivityIdRef.current = null;
    resetCitationState();
    setBriefDataSource(null);
    setStage('seed');
    setSections([]);
    setRegenFor(null);
    setError(null);
    setQuery('');
    setInstructions('');
    setNumberHeadings(false);
    setBriefVoiceId(null);
    setCanEdit(true);
    setOwnerName(null);
  }, [resetCitationState]);

  // Persist a title/content edit immediately (any non-seed stage).
  const commitEdits = useCallback(() => {
    if (stage !== 'seed' && briefIdRef.current) saveCurrent();
  }, [stage, saveCurrent]);

  // The grouping is a property of the brief: the API renumbers for it and
  // saves it, and the brief is then shown as returned.
  const setReferenceGrouping = useCallback(
    (grouping: ReferenceGrouping) => {
      if (!briefIdRef.current || !sectionsRef.current.length) {
        setReferenceGroupingState(grouping);
        return;
      }
      citationsCall({ type: 'grouping', grouping })
        .then(applyRead)
        .catch((e) =>
          setError(e instanceof Error ? e.message : 'Could not change the grouping.'),
        );
    },
    [citationsCall, applyRead],
  );

  // ---- derived ----
  const numbers = useMemo(() => computeNumbers(sections), [sections]);
  const doneCount = sections.filter((s) => s.status === 'done').length;
  const totalProgress = sections.length
    ? Math.round(
        sections.reduce((a, s) => a + (s.status === 'done' ? 100 : s.progress), 0) /
          sections.length,
      )
    : 0;
  const totalSources = sourceCount;
  const totalWords = useMemo(
    () => sections.reduce((a, s) => a + (s.status === 'done' ? countWords(s.content) : 0), 0),
    [sections],
  );

  return {
    // state
    stage,
    briefTitle,
    currentBriefId: briefIdRef.current,
    sections,
    numbers,
    query,
    instructions,
    numHeadings,
    numberHeadings,
    generatingActivity,
    newHeading,
    regenFor,
    regenText,
    history,
    historyOpen,
    error,
    outlineLoading,
    doneCount,
    totalProgress,
    totalSources,
    totalWords,
    targetWords,
    briefVoiceId,
    canEdit,
    ownerName,
    briefDataSource,
    remote,
    voices: voices || [],
    // setters / actions
    setQuery,
    setInstructions,
    setNumHeadings,
    setNumberHeadings,
    setNewHeading,
    setBriefTitle,
    setRegenText,
    setError,
    setHistoryOpen,
    setBriefVoiceId,
    referenceGrouping,
    setReferenceGrouping,
    wordLinkTarget,
    setWordLinkTarget,
    setTargetWords,
    setSectionTargetWords: (id: string, target: number | null) =>
      updateSection(id, { targetWords: target }),
    requestSourceHighlight,
    setSectionGuidance: (id: string, guidance: string) => updateSection(id, { guidance }),
    setSectionVoiceId: (id: string, voiceId: string | null) =>
      updateSection(id, { voiceId }),
    generateOutline,
    startManual,
    startFromTemplate,
    openBriefById,
    addSection,
    addHeading,
    addSubHeading,
    removeSection,
    reorderSiblings,
    indentSection,
    editTitle,
    editContent,
    startResearch,
    updateAll,
    stopResearch,
    regenerate,
    reviseSection,
    dismissChanges,
    rejectChanges,
    commitManualEdit,
    references,
    referenceGroups,
    getSectionRunDetail,
    openRegen: (id: string) => {
      setRegenFor(id);
      setRegenText('');
    },
    closeRegen: () => {
      setRegenFor(null);
      setRegenText('');
    },
    loadBrief,
    cloneBrief,
    deleteBrief,
    reset,
    commitEdits,
  };
};

export type UseBriefReturn = ReturnType<typeof useBrief>;
