import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SourceReference, SummaryModelConfig } from '../../types/api';
import { SearchSettings } from '../../types/auth';
import { useActivityLogging } from '../../hooks/useActivityLogging';
import { extractCitedNumbers } from '../citations/CitedContent';
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
  BRIEF_HISTORY_KEY,
  BriefReference,
  BriefSection,
  BriefStage,
  DEFAULT_BRIEF_TITLE,
  SavedBrief,
  SectionAuditEntry,
  VoiceProfile,
} from './briefTypes';
import {
  createBrief as createBriefRemote,
  deleteBriefRemote,
  getBrief as getBriefRemote,
  listMyBriefs,
  updateBrief as updateBriefRemote,
} from './briefCentralApi';
import { listItemToStub, migrateLocalBriefs, remoteToSaved } from './briefRemote';
import { highlightSectionSources } from './briefHighlights';
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
  sample,
});

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

// Compiled footnotes: the actually-cited sources across done sections, one
// entry per document (grouped/deduped), like the search summary's references.
const computeReferences = (sections: BriefSection[]): BriefReference[] => {
  const seen = new Set<string>();
  const refs: BriefReference[] = [];
  sections.forEach((s) => {
    // Sections mid-Edit/Update keep their (old) content on screen, so they
    // keep their footnotes too — no renumbering while a revise runs.
    if (s.status !== 'done' && !s.revising) return;
    const cited = new Set(extractCitedNumbers(s.content));
    s.sources.forEach((src: SourceReference) => {
      if (src.index == null || !cited.has(src.index)) return;
      const key = src.docId || src.title;
      if (seen.has(key)) return;
      seen.add(key);
      refs.push({
        n: refs.length + 1,
        title: src.title,
        page: src.page,
        section: s.title,
        source: src,
      });
    });
  });
  return refs;
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
  const { logBrief } = useActivityLogging();
  const [stage, setStage] = useState<BriefStage>('seed');
  const [briefTitle, setBriefTitle] = useState(DEFAULT_BRIEF_TITLE);
  const [sections, setSections] = useState<BriefSection[]>([]);
  const [query, setQuery] = useState(''); // the brief topic
  const [instructions, setInstructions] = useState('');
  const [numHeadings, setNumHeadings] = useState(6);
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

  const briefIdRef = useRef<string | null>(null);
  // Stable Activity-log id for the current brief (one row per brief).
  const briefActivityIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
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
  const remoteSavedRef = useRef(false);

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

  // After a section's research completes (references validated), run the LLM
  // semantic highlighter over each cited excerpt in the background — the hover
  // card then marks the claim-supporting span, falling back to the full
  // excerpt. `token` (the section's lastResearchedAt) stops a stale run from
  // clobbering a newer research pass.
  const enrichSectionHighlights = useCallback(
    (id: string, token: number) => {
      if (!SEARCH_SEMANTIC_HIGHLIGHTS) return;
      const section = sectionsRef.current.find((s) => s.id === id);
      if (!section || section.status !== 'done' || !section.content) return;
      const isStale = () => {
        const cur = sectionsRef.current.find((s) => s.id === id);
        return !cur || cur.lastResearchedAt !== token;
      };
      void highlightSectionSources({
        content: section.content,
        sources: section.sources,
        threshold: SEMANTIC_HIGHLIGHT_THRESHOLD,
        modelConfig: semanticModelConfigRef.current,
        isStale,
        // Apply snippets as each source resolves — a big section takes minutes
        // to fully enrich and the hover cards should improve as it goes.
        onPartial: (sources) => {
          if (!isStale()) updateSection(id, { sources });
        },
      })
        .then((sources) => {
          if (!isStale()) updateSection(id, { sources });
        })
        .catch(() => {
          /* highlighting is an enhancement; the plain excerpt remains */
        });
    },
    [updateSection],
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

  // Serialise remote saves: one in flight at a time; a save requested while one
  // runs re-runs once it finishes (latest state wins — entries are rebuilt).
  const remoteSaveBusyRef = useRef(false);
  const remoteSavePendingRef = useRef<SavedBrief | null>(null);

  const pushRemoteSave = useCallback(
    (entry: SavedBrief) => {
      if (remoteSaveBusyRef.current) {
        remoteSavePendingRef.current = entry;
        return;
      }
      remoteSaveBusyRef.current = true;
      const run = async (current: SavedBrief): Promise<void> => {
        if (remoteSavedRef.current && briefIdRef.current) {
          await updateBriefRemote(briefIdRef.current, {
            title: current.title,
            query: current.query || null,
            voiceProfileId: current.voiceId ?? null,
            content: current,
          });
        } else {
          const created = await createBriefRemote({
            title: current.title,
            query: current.query || null,
            dataSource: dataSource || null,
            voiceProfileId: current.voiceId ?? null,
            content: current,
          });
          // Adopt the server id so subsequent saves update the same row.
          briefIdRef.current = created.id;
          remoteSavedRef.current = true;
        }
        const pending = remoteSavePendingRef.current;
        remoteSavePendingRef.current = null;
        if (pending) return run({ ...pending, id: briefIdRef.current || pending.id });
      };
      run(entry)
        .then(() => refreshRemoteHistory())
        .catch((e) =>
          setError(e instanceof Error ? e.message : 'Could not save the brief.'),
        )
        .finally(() => {
          remoteSaveBusyRef.current = false;
        });
    },
    [dataSource, refreshRemoteHistory],
  );

  const saveCurrent = useCallback(() => {
    const id = briefIdRef.current;
    const snap = sectionsRef.current;
    if (!id || !snap.length) return;
    // Never write back a brief someone else owns (viewer-only).
    if (remote && !canEditRef.current) return;
    const entry: SavedBrief = {
      id,
      title: briefTitleRef.current,
      query: queryRef.current,
      date: Date.now(),
      sectionCount: snap.length,
      sourceCount: snap.reduce((a, s) => a + s.sources.length, 0),
      // Persist only completed sections' content; a section that was mid- or
      // un-researched reverts to its last stable (pending) state on reload —
      // never a stuck "Researching…".
      sections: snap.map((s) => {
        // A mid-revise section still holds its last good content — persist it
        // as done so an interrupted Edit/Update never loses the section.
        const done = s.status === 'done' || !!s.revising;
        return {
          title: s.title,
          level: s.level,
          status: done ? 'done' : 'pending',
          content: done ? s.content : '',
          sources: done ? s.sources : [],
          audit: s.audit && s.audit.length ? s.audit : undefined,
          lastResearchedAt: s.lastResearchedAt,
          voiceId: s.voiceId ?? undefined,
        };
      }),
      outlineLog: outlineLogRef.current,
      numberHeadings: numberHeadingsRef.current,
      activityId: briefActivityIdRef.current ?? undefined,
      voiceId: briefVoiceIdRef.current,
    };
    if (remote) {
      pushRemoteSave(entry);
    } else {
      persist([entry, ...historyRef.current.filter((e) => e.id !== id)].slice(0, 10));
    }

    // Mirror the brief into the Activity log as a "brief" row, upserted on each
    // save so there's one activity per brief reflecting its latest state.
    const activityId = briefActivityIdRef.current;
    if (activityId) {
      const markdown = snap
        .map((s) => {
          const body = s.content ? `\n\n${s.content}` : '';
          return `## ${s.title}${body}`;
        })
        .join('\n\n');
      const seen = new Set<string>();
      const sources = snap
        .flatMap((s) => s.sources)
        .filter((src) => {
          const key = src.chunkId || src.docId;
          if (!key || seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      logBrief(activityId, briefTitleRef.current, markdown, sources);
    }
  }, [remote, pushRemoteSave, persist, logBrief]);

  // Auto-save once a brief exists (outline generated or manual start) so it
  // appears in Saved Briefs right away and keeps tracking title/content edits.
  useEffect(() => {
    if (stage === 'seed' || !briefIdRef.current) return;
    const t = setTimeout(() => saveCurrent(), 500);
    return () => clearTimeout(t);
  }, [stage, briefTitle, sections, numberHeadings, saveCurrent]);

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
        signal: controller.signal,
      });
      briefIdRef.current = uid();
      briefActivityIdRef.current = newActivityId();
      remoteSavedRef.current = false;
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
  }, [apiBaseUrl, dataSource, query, instructions, numHeadings, assistantModelConfig]);

  const startManual = useCallback(() => {
    briefIdRef.current = uid();
    briefActivityIdRef.current = newActivityId();
    remoteSavedRef.current = false;
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
  }, []);

  // Start a brief from a template's headings (optionally with saved text).
  const startFromTemplate = useCallback(
    (
      title: string,
      headings: { title: string; sub: boolean; text?: string | null }[],
    ) => {
      briefIdRef.current = uid();
      briefActivityIdRef.current = newActivityId();
      remoteSavedRef.current = false;
      setCanEdit(true);
      setOwnerName(null);
      setBriefTitle(title.trim() || DEFAULT_BRIEF_TITLE);
      setSections(
        headings.map((h) => {
          const section = makeSection(h.title, h.sub ? 2 : 1, false);
          if (h.text) {
            return { ...section, status: 'done' as const, progress: 100, content: h.text };
          }
          return section;
        }),
      );
      setStage('outline');
    },
    [],
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

  const editContent = useCallback(
    (id: string, content: string) => updateSection(id, { content }),
    [updateSection],
  );

  // ---- research engine ----
  const researchOne = useCallback(
    (
      id: string,
      context: string | null,
      signal: AbortSignal,
      opts?: { mode?: SectionResearchMode; instruction?: string | null },
    ): Promise<void> => {
      const list = sectionsRef.current;
      const idx = list.findIndex((s) => s.id === id);
      const section = list[idx];
      if (!section) return Promise.resolve();
      const mode: SectionResearchMode = opts?.mode ?? 'generate';
      const isRevise = mode === 'edit' || mode === 'update';
      const instruction = (opts?.instruction || '').trim() || null;
      // Snapshot the pre-op state for the audit row + the "show changes" diff.
      const priorContent = section.content;
      const priorSources = section.sources;
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
      updateSection(
        id,
        isRevise
          ? { status: 'researching', progress: 4, activity: [], revising: true }
          : { status: 'researching', progress: 4, content: '', sources: [], activity: [] },
      );
      const briefTopic = queryRef.current.trim() || briefTitleRef.current;
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
        mode,
        existingContent: isRevise ? priorContent : null,
        instruction,
        publishedAfterIso,
        voiceInstructions: voiceInstructionsFor(section.voiceId),
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
          onDone: ({ content, sources }) => {
            // A run that read sources but answered with process narration
            // ("I'll go research that…") instead of the section is a failure —
            // surface it and keep the section pending rather than storing it.
            if (!isRevise && isLikelyNonAnswer(content, sources.length)) {
              updateSection(id, { status: 'pending', progress: 0 });
              setError(
                `The model did not return researched content for “${section.title}” — please try again.`,
              );
              return;
            }
            const priorKeys = new Set(priorSources.map((s) => s.docId));
            const added = sources.filter((s) => !priorKeys.has(s.docId)).length;
            const entry: SectionAuditEntry = {
              id: uid(),
              kind: mode,
              at: Date.now(),
              question: mode === 'generate' ? section.title : undefined,
              instruction:
                mode === 'generate' ? context || undefined : instruction || undefined,
              sourceCount: sources.length,
              addedSourceCount: added,
              // Keep the before/after for a revise so its diff stays viewable.
              before: isRevise ? priorContent : undefined,
              after: isRevise ? content : undefined,
            };
            const cur = sectionsRef.current.find((s) => s.id === id);
            const doneAt = Date.now();
            updateSection(id, {
              status: 'done',
              progress: 100,
              content,
              sources,
              audit: [...(cur?.audit || []), entry],
              lastResearchedAt: doneAt,
              revising: undefined,
              prevContent: isRevise ? priorContent : undefined,
              prevSources: isRevise ? priorSources : undefined,
              lastChangeKind: isRevise ? mode : undefined,
            });
            // Async: LLM-highlight the cited excerpts once the state lands.
            setTimeout(() => enrichSectionHighlights(id, doneAt), 0);
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
      }).catch(() =>
        updateSection(
          id,
          isRevise
            ? { status: 'done', progress: 100, revising: undefined }
            : { status: 'pending', progress: 0 },
        ),
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
    ],
  );

  const startResearch = useCallback(async () => {
    const ids = sectionsRef.current.map((s) => s.id);
    if (!ids.length) return;
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    setStage('research');
    for (const id of ids) {
      if (controller.signal.aborted) return;
      await researchOne(id, null, controller.signal);
    }
    if (!controller.signal.aborted) {
      setStage('done');
      saveCurrent();
    }
  }, [researchOne, saveCurrent]);

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
  // pre-op content is retained so the user can view the diff.
  const editSectionAI = useCallback(
    async (id: string, instruction: string) => {
      const section = sectionsRef.current.find((s) => s.id === id);
      if (!section || !instruction.trim()) return;
      const priorContent = section.content;
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
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        const cur = sectionsRef.current.find((s) => s.id === id);
        const entry: SectionAuditEntry = {
          id: uid(),
          kind: 'edit',
          at: Date.now(),
          instruction: instruction.trim(),
          sourceCount: section.sources.length,
          addedSourceCount: 0,
          before: priorContent,
          after: revised,
        };
        const doneAt = Date.now();
        updateSection(id, {
          status: 'done',
          progress: 100,
          content: revised,
          // Sources unchanged — a surgical edit preserves the [n] markers. The
          // claims moved though, so drop stale excerpt highlights to recompute.
          sources: section.sources.map(({ semanticMatches: _sm, ...rest }) => rest),
          audit: [...(cur?.audit || []), entry],
          lastResearchedAt: doneAt,
          revising: undefined,
          prevContent: priorContent,
          prevSources: section.sources,
          lastChangeKind: 'edit',
        });
        setTimeout(() => enrichSectionHighlights(id, doneAt), 0);
      } catch (e) {
        if (!controller.signal.aborted) {
          updateSection(id, { status: 'done', progress: 100, revising: undefined });
          setError(e instanceof Error ? e.message : 'Edit failed');
        }
      }
    },
    [apiBaseUrl, dataSource, updateSection, voiceInstructionsFor, enrichSectionHighlights],
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

  // Keep Edits: accept the revised content and drop the retained pre-op state.
  const dismissChanges = useCallback(
    (id: string) =>
      updateSection(id, {
        prevContent: undefined,
        prevSources: undefined,
        lastChangeKind: undefined,
      }),
    [updateSection],
  );

  // Reject Edits: restore the pre-op content and sources, drop the revision, and
  // remove its (now-undone) audit row so the log only shows applied changes.
  const rejectChanges = useCallback(
    (id: string) =>
      setSections((prev) =>
        prev.map((s) =>
          s.id === id && s.prevContent != null
            ? {
                ...s,
                content: s.prevContent,
                sources: s.prevSources ?? s.sources,
                prevContent: undefined,
                prevSources: undefined,
                lastChangeKind: undefined,
                audit: s.audit ? s.audit.slice(0, -1) : s.audit,
              }
            : s,
        ),
      ),
    [],
  );

  // ---- history ----
  // Materialise a SavedBrief into the working state. `access` marks whether the
  // user owns it (edit) or views a shared copy (read-only).
  const applyLoadedBrief = useCallback(
    (
      entry: SavedBrief,
      access: { canEdit: boolean; ownerName: string | null; saved: boolean },
    ) => {
      abortRef.current?.abort();
      briefIdRef.current = entry.id;
      remoteSavedRef.current = access.saved;
      briefActivityIdRef.current = entry.activityId || newActivityId();
      setBriefTitle(entry.title);
      setQuery(entry.query);
      setCanEdit(access.canEdit);
      setOwnerName(access.ownerName);
      setBriefVoiceId(entry.voiceId ?? null);
      setSections(
        entry.sections.map((h) => ({
          ...makeSection(h.title, h.level),
          status: h.status === 'done' ? 'done' : 'pending',
          progress: h.status === 'done' ? 100 : 0,
          content: h.status === 'done' ? h.content : '',
          sources: h.status === 'done' ? h.sources || [] : [],
          audit: h.audit || [],
          lastResearchedAt: h.lastResearchedAt,
          voiceId: h.voiceId ?? null,
        })),
      );
      setGeneratingActivity(entry.outlineLog || []);
      setNumberHeadings(entry.numberHeadings ?? false);
      setStage('done');
      setHistoryOpen(false);
    },
    [],
  );

  const loadBrief = useCallback(
    (entry: SavedBrief) => {
      if (remote) {
        // History rows are stubs — fetch the full brief (with access info).
        getBriefRemote(entry.id)
          .then((full) =>
            applyLoadedBrief(remoteToSaved(full), {
              canEdit: full.can_edit,
              ownerName: full.owner_name,
              saved: true,
            }),
          )
          .catch((e) =>
            setError(e instanceof Error ? e.message : 'Could not open the brief.'),
          );
        return;
      }
      applyLoadedBrief(entry, { canEdit: true, ownerName: null, saved: false });
    },
    [remote, applyLoadedBrief],
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
        getBriefRemote(entry.id)
          .then(async (full) => {
            const copyContent: SavedBrief = {
              ...full.content,
              title: `${full.title} (copy)`,
              date: Date.now(),
              activityId: newActivityId(),
            };
            const created = await createBriefRemote({
              title: copyContent.title,
              query: full.query,
              dataSource: full.data_source,
              voiceProfileId: full.voice_profile_id,
              content: copyContent,
            });
            await refreshRemoteHistory();
            applyLoadedBrief(remoteToSaved(created), {
              canEdit: true,
              ownerName: null,
              saved: true,
            });
          })
          .catch((e) =>
            setError(e instanceof Error ? e.message : 'Could not copy the brief.'),
          );
        return;
      }
      const copy: SavedBrief = {
        ...entry,
        id: uid(),
        title: `${entry.title} (copy)`,
        date: Date.now(),
        activityId: newActivityId(), // a clone is its own brief → its own activity row
      };
      persist([copy, ...historyRef.current].slice(0, 10));
      loadBrief(copy);
    },
    [remote, persist, loadBrief, applyLoadedBrief, refreshRemoteHistory],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    briefIdRef.current = null;
    briefActivityIdRef.current = null;
    remoteSavedRef.current = false;
    setStage('seed');
    setSections([]);
    setRegenFor(null);
    setError(null);
    setQuery('');
    setNumberHeadings(false);
    setBriefVoiceId(null);
    setCanEdit(true);
    setOwnerName(null);
  }, []);

  // Persist a title/content edit immediately (any non-seed stage).
  const commitEdits = useCallback(() => {
    if (stage !== 'seed' && briefIdRef.current) saveCurrent();
  }, [stage, saveCurrent]);

  // ---- derived ----
  const numbers = useMemo(() => computeNumbers(sections), [sections]);
  const references = useMemo(() => computeReferences(sections), [sections]);
  const doneCount = sections.filter((s) => s.status === 'done').length;
  const totalProgress = sections.length
    ? Math.round(
        sections.reduce((a, s) => a + (s.status === 'done' ? 100 : s.progress), 0) /
          sections.length,
      )
    : 0;
  const totalSources = sections.reduce((a, s) => a + s.sources.length, 0);

  return {
    // state
    stage,
    briefTitle,
    currentBriefId: briefIdRef.current,
    sections,
    numbers,
    references,
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
    briefVoiceId,
    canEdit,
    ownerName,
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
