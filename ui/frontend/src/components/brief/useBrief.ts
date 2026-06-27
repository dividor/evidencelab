import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SourceReference, SummaryModelConfig } from '../../types/api';
import { SearchSettings } from '../../types/auth';
import {
  BriefActivityEvent,
  requestBriefOutline,
  researchBriefSection,
  searchCorpusForOutline,
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

const makeSection = (title: string, level = 1): BriefSection => ({
  id: uid(),
  title,
  level: level === 2 ? 2 : 1,
  status: 'pending',
  progress: 0,
  content: '',
  sources: [],
  activity: [],
});

export interface UseBriefOptions {
  apiBaseUrl: string;
  dataSource: string;
  // The configured chat / deep-research model (combo.assistant_model). Used for
  // both outline generation and per-section research so the Brief tab uses the
  // same LLM as the rest of the system.
  assistantModelConfig?: SummaryModelConfig | null;
  rerankerModel?: string | null;
  searchSettings?: Partial<SearchSettings> | null;
}

const loadHistory = (): SavedBrief[] => {
  try {
    const raw = localStorage.getItem(BRIEF_HISTORY_KEY);
    return raw ? (JSON.parse(raw) as SavedBrief[]) : [];
  } catch {
    return [];
  }
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

const computeReferences = (sections: BriefSection[]): BriefReference[] => {
  const seen = new Set<string>();
  const refs: BriefReference[] = [];
  sections.forEach((s) => {
    if (s.status !== 'done') return;
    s.sources.forEach((src: SourceReference) => {
      const key = `${src.docId}|${src.title}`;
      if (seen.has(key)) return;
      seen.add(key);
      refs.push({ n: refs.length + 1, title: src.title, page: src.page, section: s.title });
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
}: UseBriefOptions) => {
  const [stage, setStage] = useState<BriefStage>('seed');
  const [briefTitle, setBriefTitle] = useState('Evidence Brief');
  const [sections, setSections] = useState<BriefSection[]>([]);
  const [query, setQuery] = useState('');
  const [newHeading, setNewHeading] = useState('');
  const [regenFor, setRegenFor] = useState<string | null>(null);
  const [regenText, setRegenText] = useState('');
  const [history, setHistory] = useState<SavedBrief[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outlineLoading, setOutlineLoading] = useState(false);

  const briefIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sectionsRef = useRef<BriefSection[]>(sections);
  sectionsRef.current = sections;

  useEffect(() => setHistory(loadHistory()), []);
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

  const persist = useCallback((next: SavedBrief[]) => {
    setHistory(next);
    try {
      localStorage.setItem(BRIEF_HISTORY_KEY, JSON.stringify(next));
    } catch {
      /* storage may be unavailable; non-fatal */
    }
  }, []);

  const saveCurrent = useCallback(() => {
    const id = briefIdRef.current;
    const snap = sectionsRef.current;
    if (!id || !snap.length) return;
    const entry: SavedBrief = {
      id,
      title: briefTitle,
      query,
      date: Date.now(),
      sectionCount: snap.length,
      sourceCount: snap.reduce((a, s) => a + s.sources.length, 0),
      sections: snap.map((s) => ({
        title: s.title,
        level: s.level,
        status: s.status,
        content: s.content,
        sources: s.sources,
      })),
    };
    persist([entry, ...history.filter((e) => e.id !== id)].slice(0, 10));
  }, [briefTitle, query, history, persist]);

  // ---- outline ----
  const generateOutline = useCallback(async () => {
    setError(null);
    setOutlineLoading(true);
    try {
      // Ground the outline in what the corpus actually contains.
      const sources = await searchCorpusForOutline({ apiBaseUrl, dataSource, question: query });
      const outline = await requestBriefOutline({
        apiBaseUrl,
        dataSource,
        question: query,
        model: assistantModelConfig?.model ?? null,
        sources,
      });
      briefIdRef.current = uid();
      setBriefTitle(outline.title);
      setSections(outline.headings.filter((h) => h.title).map((h) => makeSection(h.title, h.level)));
      setStage('outline');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not generate an outline.');
    } finally {
      setOutlineLoading(false);
    }
  }, [apiBaseUrl, dataSource, query, assistantModelConfig]);

  const startManual = useCallback(() => {
    briefIdRef.current = uid();
    setBriefTitle('Evidence Brief');
    setSections(
      ['Background & definitions', 'Key findings', 'Recommendations'].map((t) =>
        makeSection(t),
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

  const removeSection = useCallback((id: string) => {
    setSections((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const moveSection = useCallback((id: string, dir: -1 | 1) => {
    setSections((prev) => {
      const arr = [...prev];
      const i = arr.findIndex((s) => s.id === id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= arr.length) return prev;
      [arr[i], arr[j]] = [arr[j], arr[i]];
      return arr;
    });
  }, []);

  const indentSection = useCallback((id: string) => {
    setSections((prev) => {
      const i = prev.findIndex((s) => s.id === id);
      if (i <= 0) return prev; // first item must stay top-level
      return prev.map((s) => (s.id === id ? { ...s, level: s.level === 2 ? 1 : 2 } : s));
    });
  }, []);

  const editTitle = useCallback(
    (id: string, title: string) => updateSection(id, { title }),
    [updateSection],
  );

  // ---- research engine ----
  const researchOne = useCallback(
    (id: string, context: string | null, signal: AbortSignal): Promise<void> => {
      const section = sectionsRef.current.find((s) => s.id === id);
      if (!section) return Promise.resolve();
      updateSection(id, {
        status: 'researching',
        progress: 4,
        content: '',
        sources: [],
        activity: [],
      });
      return researchBriefSection({
        apiBaseUrl,
        dataSource,
        heading: section.title,
        context,
        assistantModelConfig,
        rerankerModel,
        searchSettings,
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
    [
      apiBaseUrl,
      dataSource,
      assistantModelConfig,
      rerankerModel,
      searchSettings,
      updateSection,
      pushActivity,
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

  const finishIfComplete = useCallback(() => {
    const all = sectionsRef.current.length > 0 && sectionsRef.current.every((s) => s.status === 'done');
    if (all) {
      setStage('done');
      saveCurrent();
    }
  }, [saveCurrent]);

  const regenerate = useCallback(
    async (id: string, context: string | null) => {
      setRegenFor(null);
      setRegenText('');
      if (stage === 'outline') setStage('research');
      const controller = abortRef.current ?? new AbortController();
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
        status: h.status || 'done',
        progress: h.status === 'done' ? 100 : 0,
        content: h.content,
        sources: h.sources || [],
      })),
    );
    setStage('done');
    setHistoryOpen(false);
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    briefIdRef.current = null;
    setStage('seed');
    setSections([]);
    setRegenFor(null);
    setError(null);
    setQuery('');
  }, []);

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
    sections,
    numbers,
    references,
    query,
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
    setNewHeading,
    setBriefTitle,
    setRegenText,
    setError,
    setHistoryOpen,
    generateOutline,
    startManual,
    addSection,
    removeSection,
    moveSection,
    indentSection,
    editTitle,
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
    reset,
  };
};

export type UseBriefReturn = ReturnType<typeof useBrief>;
