import { buildThreads } from '../components/brief/useBriefComments';
import { fromRemote } from '../components/brief/briefCommentsApi';
import type { BriefComment } from '../components/brief/briefCommentsApi';

const comment = (over: Partial<BriefComment> = {}): BriefComment => ({
  id: 'c1',
  briefId: 'b1',
  parentId: null,
  sectionId: 'sec-1',
  quote: null,
  quotePrefix: null,
  quoteSuffix: null,
  body: 'text',
  resolved: false,
  authorName: 'Ada',
  authorEmail: 'ada@x.org',
  isMine: false,
  createdAt: '2026-08-12T10:00:00Z',
  updatedAt: '2026-08-12T10:00:00Z',
  ...over,
});

describe('fromRemote', () => {
  it('maps the API payload to camelCase', () => {
    const mapped = fromRemote({
      id: 'c1',
      brief_id: 'b1',
      parent_id: 'p1',
      section_id: 'sec-2',
      quote: 'cash transfers',
      quote_prefix: 'on ',
      quote_suffix: ' improved',
      body: 'Please cite',
      resolved: true,
      author_name: 'Ada Lovelace',
      author_email: 'ada@x.org',
      is_mine: true,
      created_at: '2026-08-12T10:00:00Z',
      updated_at: '2026-08-12T11:00:00Z',
    });
    expect(mapped.briefId).toBe('b1');
    expect(mapped.parentId).toBe('p1');
    expect(mapped.quotePrefix).toBe('on ');
    expect(mapped.isMine).toBe(true);
    expect(mapped.authorName).toBe('Ada Lovelace');
  });
});

describe('buildThreads', () => {
  it('nests replies under the comment that opened the thread', () => {
    const root = comment({ id: 'r1' });
    const reply = comment({ id: 'x1', parentId: 'r1', body: 'agreed' });
    const threads = buildThreads([root, reply]);
    expect(threads).toHaveLength(1);
    expect(threads[0].root.id).toBe('r1');
    expect(threads[0].replies.map((r) => r.id)).toEqual(['x1']);
  });

  it('keeps threads separate and preserves order', () => {
    const threads = buildThreads([
      comment({ id: 'r1' }),
      comment({ id: 'r2' }),
      comment({ id: 'x1', parentId: 'r2' }),
    ]);
    expect(threads.map((t) => t.root.id)).toEqual(['r1', 'r2']);
    expect(threads[0].replies).toHaveLength(0);
    expect(threads[1].replies).toHaveLength(1);
  });

  it('ignores replies whose parent is absent', () => {
    const threads = buildThreads([comment({ id: 'x1', parentId: 'missing' })]);
    expect(threads).toHaveLength(0);
  });

  it('returns nothing for an empty list', () => {
    expect(buildThreads([])).toEqual([]);
  });

  it('carries the resolved flag through to the thread root', () => {
    const threads = buildThreads([comment({ id: 'r1', resolved: true })]);
    expect(threads[0].root.resolved).toBe(true);
  });
});
