import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SourceReference, SummaryModelConfig } from '../../types/api';
import { extractCitedNumbers } from '../citations/CitedContent';
import {
  BriefActivityEvent,
  BriefSourceSample,
  requestBriefOutline,
  researchBriefSection,
  runDeepResearch,
} from '../../utils/briefStream';
import {
  BRIEF_HISTORY_KEY,
  BriefReference,
  BriefSection,
  BriefStage,
  SavedBrief,
} from './briefTypes';

let _uid = 0;
const uid = (): string => `b${++_uid}_${Date.now()}`;

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
  // Identifier for the logged-in user; saved briefs are scoped to it. When
  // absent (anonymous), the shared default bucket is used.
  userKey?: string | null;
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
    if (s.status !== 'done') return;
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
  userKey,
}: UseBriefOptions) => {
  const historyKey = userKey ? `${BRIEF_HISTORY_KEY}_u_${userKey}` : BRIEF_HISTORY_KEY;
  const [stage, setStage] = useState<BriefStage>('seed');
  const [briefTitle, setBriefTitle] = useState('Evidence Brief');
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

  const briefIdRef = useRef<string | null>(null);
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

  useEffect(() => setHistory(loadHistory(historyKey)), [historyKey]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const updateSection = useCallback((id: string, patch: Partial<BriefSection>) => {
    setSections((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }, []);

  const pushActivity = useCallback((id: string, ev: BriefActivityEvent) => {
    setSections((prev) =>
      prev.map((s) =>
        s.id === id ? { ...s, activity: [ev, ...s.activity].slice(0, 4) } : s,
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
    (id: string) => persist(history.filter((e) => e.id !== id)),
    [history, persist],
  );

  const saveCurrent = useCallback(() => {
    const id = briefIdRef.current;
    const snap = sectionsRef.current;
    if (!id || !snap.length) return;
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
        const done = s.status === 'done';
        return {
          title: s.title,
          level: s.level,
          status: done ? 'done' : 'pending',
          content: done ? s.content : '',
          sources: done ? s.sources : [],
        };
      }),
      outlineLog: outlineLogRef.current,
      numberHeadings: numberHeadingsRef.current,
    };
    persist([entry, ...historyRef.current.filter((e) => e.id !== id)].slice(0, 10));
  }, [persist]);

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
  const generateOutline = useCallback(async () => {
    const topic = query.trim();
    if (!topic) return;
    setError(null);
    setOutlineLoading(true);
    setGeneratingActivity([]);
    const controller = new AbortController();
    abortRef.current = controller;
    const guidance = instructions.trim();
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
        numHeadings,
        model: assistantModelConfig?.model ?? null,
        sources: gathered,
        signal: controller.signal,
      });
      briefIdRef.current = uid();
      setBriefTitle(topic);
      setSections(outline.headings.filter((h) => h.title).map((h) => makeSection(h.title, h.level)));
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
    setBriefTitle('Evidence Brief');
    setSections(
      // Placeholder samples: research stays disabled until the user edits them.
      ['Background & definitions', 'Key findings', 'Recommendations'].map((t) =>
        makeSection(t, 1, true),
      ),
    );
    setStage('outline');
  }, []);

  // ---- outline editing ----
  const addSection = useCallback(() => {
    const t = newHeading.trim();
    if (!t) return;
    setSections((prev) => [...prev, makeSection(t)]);
    setNewHeading('');
  }, [newHeading]);

  // Append a new top-level heading (sample until the user names it, so its
  // per-section research stays disabled until edited).
  const addHeading = useCallback(() => {
    setSections((prev) => [...prev, makeSection('New heading', 1, true)]);
  }, []);

  // Insert a new sub-heading after the given heading and its existing children.
  const addSubHeading = useCallback((parentId: string) => {
    setSections((prev) => {
      const idx = prev.findIndex((s) => s.id === parentId);
      if (idx < 0) return prev;
      let insertAt = idx + 1;
      while (insertAt < prev.length && prev[insertAt].level === 2) insertAt++;
      const next = [...prev];
      next.splice(insertAt, 0, makeSection('New sub-heading', 2, true));
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
    (id: string, context: string | null, signal: AbortSignal): Promise<void> => {
      const list = sectionsRef.current;
      const idx = list.findIndex((s) => s.id === id);
      const section = list[idx];
      if (!section) return Promise.resolve();
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
      updateSection(id, {
        status: 'researching',
        progress: 4,
        content: '',
        sources: [],
        activity: [],
      });
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
        signal,
        handlers: {
          onActivity: (ev) => pushActivity(id, ev),
          onProgress: (p) => updateSection(id, { progress: p }),
          onToken: (t) => updateSection(id, { content: t }),
          onSources: (s) => updateSection(id, { sources: s }),
          onDone: ({ content, sources }) =>
            updateSection(id, { status: 'done', progress: 100, content, sources }),
          onError: (m) => {
            updateSection(id, { status: 'pending', progress: 0 });
            setError(m);
          },
        },
      }).catch(() => updateSection(id, { status: 'pending', progress: 0 }));
    },
    [apiBaseUrl, dataSource, assistantModelConfig, updateSection, pushActivity],
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

  // ---- history ----
  const loadBrief = useCallback((entry: SavedBrief) => {
    abortRef.current?.abort();
    briefIdRef.current = entry.id;
    setBriefTitle(entry.title);
    setQuery(entry.query);
    setSections(
      entry.sections.map((h) => ({
        ...makeSection(h.title, h.level),
        status: h.status === 'done' ? 'done' : 'pending',
        progress: h.status === 'done' ? 100 : 0,
        content: h.status === 'done' ? h.content : '',
        sources: h.status === 'done' ? h.sources || [] : [],
      })),
    );
    setGeneratingActivity(entry.outlineLog || []);
    setNumberHeadings(entry.numberHeadings ?? false);
    setStage('done');
    setHistoryOpen(false);
  }, []);

  // Duplicate a saved brief under a new id and open the copy.
  const cloneBrief = useCallback(
    (entry: SavedBrief) => {
      const copy: SavedBrief = {
        ...entry,
        id: uid(),
        title: `${entry.title} (copy)`,
        date: Date.now(),
      };
      persist([copy, ...historyRef.current].slice(0, 10));
      loadBrief(copy);
    },
    [persist, loadBrief],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    briefIdRef.current = null;
    setStage('seed');
    setSections([]);
    setRegenFor(null);
    setError(null);
    setQuery('');
    setNumberHeadings(false);
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
    generateOutline,
    startManual,
    addSection,
    addHeading,
    addSubHeading,
    removeSection,
    reorderSiblings,
    indentSection,
    editTitle,
    editContent,
    startResearch,
    regenerate,
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
