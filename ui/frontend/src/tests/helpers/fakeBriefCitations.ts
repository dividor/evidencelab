import type {
  CitationOp,
  CitationOpResult,
  HighlightsPayload,
  RunPayload,
  StoredBrief,
} from '../../components/brief/briefCitationsApi';
import type {
  BriefContentRead,
  BriefReference,
  BriefSectionRead,
  ReferenceGrouping,
  RemoteBrief,
  SavedBrief,
  SectionRunDetail,
  SectionRunSummary,
} from '../../components/brief/briefTypes';
import type { SourceReference } from '../../types/api';

/**
 * A stand-in for the brief citation API (briefCitationsApi) for tests that
 * drive research through useBrief or BriefTab.
 *
 * It keeps each brief's stored form in memory and answers every operation
 * with a read model, like the real API — but it does NOT renumber: a run's
 * text and sources come back exactly as sent, with the agent's numbers as
 * the display numbers. Tests therefore assert that the UI shows what the API
 * returns, never a numbering of the browser's own. Tests of the real
 * numbering live in the backend suite (tests/unit/test_brief_citations.py).
 *
 * Use it as the module mock:
 *   jest.mock('../components/brief/briefCitationsApi', () =>
 *     require('./helpers/fakeBriefCitations').fakeCitationsApi(),
 *   );
 */

interface FakeSection {
  id: string;
  title: string;
  level: number;
  status: string;
  guidance?: string;
  voiceId?: string | null;
  targetWords?: number | null;
  introHeadingWarning?: number;
  lastResearchedAt?: number;
  runs: Array<SectionRunSummary & { content: string; sources: SourceReference[] }>;
  currentRunId: string | null;
  audit: Array<{ id: string; kind: string; at: number; runId: string; sourceCount: number; addedSourceCount: number; before?: string; after?: string; instruction?: string; question?: string; note?: string }>;
  display: { content: string; sources: SourceReference[] };
}

interface FakeBrief {
  [key: string]: unknown;
  id: string;
  title: string;
  citationsVersion: number;
  referenceGrouping: ReferenceGrouping;
  sections: FakeSection[];
}

let runCounter = 0;
let stamp = 0;

const sourceId = (src: SourceReference): string => `s-${src.chunkId || src.docId || 'none'}`;

const withIds = (sources: SourceReference[]): SourceReference[] =>
  sources.map((src) => ({ ...src, sourceId: sourceId(src), agentIndices: src.index != null ? [src.index] : [] }));

const newSection = (id: string, title = '', level = 1): FakeSection => ({
  id,
  title,
  level,
  status: 'pending',
  runs: [],
  currentRunId: null,
  audit: [],
  display: { content: '', sources: [] },
});

const emptyBrief = (id: string): FakeBrief => ({
  id,
  title: '',
  citationsVersion: 2,
  referenceGrouping: 'passage',
  sections: [],
});

const applyStructure = (brief: FakeBrief, saved: SavedBrief): FakeBrief => {
  const stored = new Map(brief.sections.map((s) => [s.id, s]));
  const sections: FakeSection[] = (saved.sections || []).map((cs, i) => {
    const id = cs.id || `sec${i + 1}`;
    const sec = stored.get(id) ?? newSection(id);
    sec.title = cs.title;
    sec.level = cs.level;
    sec.guidance = cs.guidance;
    sec.voiceId = cs.voiceId;
    sec.targetWords = cs.targetWords;
    sec.introHeadingWarning = cs.introHeadingWarning;
    sec.lastResearchedAt = cs.lastResearchedAt;
    if (cs.content && !sec.runs.length) {
      recordRunOn(sec, { mode: 'manual', content: cs.content, sources: [] });
    }
    // Like the API: a section is done exactly when it has a current run.
    sec.status = sec.currentRunId ? 'done' : 'pending';
    return sec;
  });
  const { sections: _old, ...rest } = saved as SavedBrief & { sections: unknown };
  return { ...brief, ...rest, sections };
};

const recordRunOn = (sec: FakeSection, run: RunPayload): void => {
  runCounter += 1;
  const id = `r${runCounter}`;
  const sources = run.sources ?? sec.display.sources.map((s) => ({ ...s }));
  const previous = sec.runs.find((r) => r.id === sec.currentRunId);
  const summary: SectionRunSummary & { content: string; sources: SourceReference[] } = {
    id,
    mode: run.mode,
    at: Date.now(),
    runId: run.runId,
    question: run.question,
    instruction: run.instruction,
    status: 'current',
    sourcesRetained: 'exact',
    mapping: Object.fromEntries(sources.filter((s) => s.index != null).map((s) => [String(s.index), sourceId(s)])),
    unresolved: [],
    rejected: [],
    sourceCount: sources.length,
    citedCount: 0,
    content: run.content,
    sources,
  };
  if (previous) previous.status = 'superseded';
  sec.runs.push(summary);
  sec.currentRunId = id;
  sec.status = 'done';
  sec.display = { content: run.content, sources: withIds(sources) };
  sec.audit.push({
    id: `a-${id}`,
    kind: run.mode,
    at: summary.at,
    runId: id,
    sourceCount: sources.length,
    addedSourceCount: previous ? 0 : sources.length,
    question: run.question,
    instruction: run.instruction,
    note: run.note,
    before: previous && run.mode !== 'generate' ? previous.content : undefined,
    after: previous && run.mode !== 'generate' ? run.content : undefined,
  });
};

const rejectOn = (sec: FakeSection, runId: string): void => {
  const run = sec.runs.find((r) => r.id === runId);
  if (!run || sec.currentRunId !== runId) throw new Error('Only the current run can be rejected');
  run.status = 'rejected';
  sec.audit = sec.audit.filter((a) => a.runId !== runId);
  const earlier = sec.runs.slice(0, sec.runs.indexOf(run)).filter((r) => r.status !== 'rejected');
  const back = earlier[earlier.length - 1];
  if (back) {
    back.status = 'current';
    sec.currentRunId = back.id;
    sec.display = { content: back.content, sources: withIds(back.sources) };
  } else {
    sec.currentRunId = null;
    sec.status = 'pending';
    sec.display = { content: '', sources: [] };
  }
};

const readOf = (brief: FakeBrief): BriefContentRead => {
  stamp += 1;
  const references: BriefReference[] = [];
  const sections: BriefSectionRead[] = brief.sections.map((sec) => {
    const done = sec.status === 'done' && !!sec.currentRunId;
    if (done) {
      sec.display.sources.forEach((src) => {
        if (src.index != null && !references.some((r) => r.n === src.index)) {
          references.push({ n: src.index, sourceId: src.sourceId || '', title: src.title, page: src.page ?? null, docId: src.docId, source: src });
        }
      });
    }
    return {
      id: sec.id,
      title: sec.title,
      level: sec.level,
      status: done ? 'done' : 'pending',
      guidance: sec.guidance,
      voiceId: sec.voiceId,
      targetWords: sec.targetWords,
      introHeadingWarning: sec.introHeadingWarning,
      lastResearchedAt: sec.lastResearchedAt,
      audit: sec.audit as BriefSectionRead['audit'],
      runs: sec.runs.map(({ content: _c, sources: _s, ...summary }) => summary),
      currentRunId: sec.currentRunId,
      renumbered: {
        content: done ? sec.display.content : '',
        sources: done ? sec.display.sources : [],
        unresolved: [],
        grouping: brief.referenceGrouping,
        computedAt: stamp,
      },
    };
  });
  references.sort((a, b) => a.n - b.n);
  const { sections: _s, ...rest } = brief;
  return {
    query: '',
    date: Date.now(),
    ...(rest as Omit<SavedBrief, 'sections'>),
    id: brief.id,
    title: brief.title,
    sectionCount: sections.length,
    sourceCount: references.length,
    citationsVersion: 2,
    sections,
    referenceGrouping: brief.referenceGrouping,
    references,
    referenceGroups: [],
    renumberedAt: stamp,
  };
};

const applyOp = (brief: FakeBrief, op: CitationOp): FakeBrief => {
  switch (op.type) {
    case 'structure':
      return applyStructure(brief, op.brief);
    case 'run': {
      // A signed-in test may create the brief through a separately mocked
      // Brief Central API, so a section unknown here is created on demand.
      let sec = brief.sections.find((s) => s.id === op.sectionId);
      if (!sec) {
        sec = newSection(op.sectionId);
        brief.sections.push(sec);
      }
      recordRunOn(sec, op.run);
      return brief;
    }
    case 'reject': {
      const sec = brief.sections.find((s) => s.id === op.sectionId);
      if (!sec) throw new Error(`Unknown section: ${op.sectionId}`);
      rejectOn(sec, op.runId);
      return brief;
    }
    case 'grouping':
      return { ...brief, referenceGrouping: op.grouping };
    case 'highlights': {
      const highlights: HighlightsPayload = op.highlights;
      brief.sections.forEach((sec) => {
        sec.display.sources = sec.display.sources.map((src) =>
          src.sourceId && highlights[src.sourceId] ? { ...src, claimMatches: highlights[src.sourceId] } : src,
        );
      });
      return brief;
    }
    case 'read':
      if (brief.citationsVersion !== 2) throw new Error('Brief predates citation format 2');
      return brief;
    case 'convert': {
      // A legacy brief: each section's content/sources become its one run.
      const legacy = brief as unknown as SavedBrief & { sections: Array<SavedBrief['sections'][number] & { sources?: SourceReference[] }> };
      const converted = emptyBrief(legacy.id);
      Object.assign(converted, legacy, { citationsVersion: 2, referenceGrouping: 'passage', sections: [] });
      converted.sections = (legacy.sections || []).map((cs, i) => {
        const sec = newSection(cs.id || `sec${i + 1}`, cs.title, cs.level);
        sec.status = cs.status;
        if (cs.status === 'done' && cs.content) {
          recordRunOn(sec, { mode: 'generate', content: cs.content, sources: cs.sources || [] });
        }
        return sec;
      });
      return converted;
    }
    default:
      throw new Error(`Unknown operation: ${(op as { type: string }).type}`);
  }
};

/** Build the mocked module. Call it inside a jest.mock factory. */
export const fakeCitationsApi = () => {
  const briefs = new Map<string, FakeBrief>();
  const briefFor = (id: string): FakeBrief => {
    const found = briefs.get(id);
    if (found) return found;
    const created = emptyBrief(id);
    briefs.set(id, created);
    return created;
  };
  const remote = (id: string, op: CitationOp): RemoteBrief => {
    const brief = applyOp(briefFor(id), op);
    briefs.set(id, brief);
    const content = readOf(brief);
    return {
      id,
      user_id: 'u-1',
      title: content.title,
      query: content.query || null,
      data_source: 'wfp',
      voice_profile_id: null,
      content,
      owner_name: null,
      can_edit: true,
      shared_with: [],
      created_at: '2026-10-19T00:00:00Z',
      updated_at: '2026-10-19T00:00:00Z',
    };
  };
  const detailOf = (brief: FakeBrief, sectionId: string, runId: string): SectionRunDetail => {
    const sec = brief.sections.find((s) => s.id === sectionId);
    const run = sec?.runs.find((r) => r.id === runId);
    if (!sec || !run) throw new Error('Run not found');
    const display: Record<string, number> = {};
    if (sec.currentRunId === runId) run.sources.forEach((s) => { if (s.index != null) display[String(s.index)] = s.index; });
    return { ...run, sectionId, displayNumbers: display };
  };
  // Plain functions, not jest.fn: CRA's jest config resets every mock's
  // implementation before each test, which would turn these into stubs that
  // return undefined. Calls are logged here for tests to inspect instead.
  const calls = {
    recordRun: [] as Array<[string, string, RunPayload]>,
    applyCitationOp: [] as Array<[StoredBrief | Record<string, unknown>, CitationOp]>,
  };
  return {
    __esModule: true,
    /** The stored brief by id (tests inspect it). */
    briefs,
    /** What the double was called with. */
    calls,
    /** Lets a test seed a signed-in brief's stored form (from a saved structure). */
    seed: (id: string, saved: SavedBrief) => briefs.set(id, applyStructure(emptyBrief(id), saved)),
    recordRun: async (id: string, sectionId: string, run: RunPayload) => {
      calls.recordRun.push([id, sectionId, run]);
      return remote(id, { type: 'run', sectionId, run });
    },
    rejectRun: async (id: string, sectionId: string, runId: string) =>
      remote(id, { type: 'reject', sectionId, runId }),
    setReferenceGrouping: async (id: string, grouping: ReferenceGrouping) =>
      remote(id, { type: 'grouping', grouping }),
    setHighlights: async (id: string, highlights: HighlightsPayload) =>
      remote(id, { type: 'highlights', highlights }),
    getRunDetail: async (id: string, sectionId: string, runId: string) =>
      detailOf(briefFor(id), sectionId, runId),
    applyCitationOp: async (
      content: StoredBrief | Record<string, unknown>,
      op: CitationOp,
    ): Promise<CitationOpResult> => {
      calls.applyCitationOp.push([content, op]);
      const brief = applyOp(JSON.parse(JSON.stringify(content)) as FakeBrief, op);
      return { content: brief as unknown as StoredBrief, read: readOf(brief) };
    },
    getLocalRunDetail: async (content: StoredBrief, sectionId: string, runId: string) =>
      detailOf(content as unknown as FakeBrief, sectionId, runId),
  };
};
