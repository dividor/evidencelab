import { numberHeadings } from '../components/brief/BriefCentralModals';
import { listItemToStub, remoteToSaved } from '../components/brief/briefRemote';
import { BriefListItem, RemoteBrief, SavedBrief } from '../components/brief/briefTypes';

describe('numberHeadings', () => {
  it('numbers top-level headings sequentially', () => {
    const out = numberHeadings([
      { title: 'A', sub: false },
      { title: 'B', sub: false },
    ]);
    expect(out.map((h) => h.num)).toEqual(['1', '2']);
  });

  it('numbers sub-headings under their parent', () => {
    const out = numberHeadings([
      { title: 'A', sub: false },
      { title: 'A1', sub: true },
      { title: 'A2', sub: true },
      { title: 'B', sub: false },
      { title: 'B1', sub: true },
    ]);
    expect(out.map((h) => h.num)).toEqual(['1', '1.1', '1.2', '2', '2.1']);
  });

  it('promotes a leading sub-heading to top level', () => {
    const out = numberHeadings([
      { title: 'Orphan', sub: true },
      { title: 'B', sub: false },
    ]);
    expect(out[0].num).toBe('1');
    expect(out[0].sub).toBe(false);
    expect(out[1].num).toBe('2');
  });
});

describe('briefRemote mappings', () => {
  const listItem: BriefListItem = {
    id: 'a4f6e6a0-1111-2222-3333-444455556666',
    title: 'Cash transfers',
    query: 'Effectiveness of cash',
    data_source: 'wfp',
    voice_profile_id: 'v-1',
    section_count: 5,
    source_count: 41,
    owner_name: null,
    share_count: 2,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-06T10:24:00Z',
  };

  it('listItemToStub keeps counts and parses the updated date', () => {
    const stub = listItemToStub(listItem);
    expect(stub.id).toBe(listItem.id);
    expect(stub.sectionCount).toBe(5);
    expect(stub.sourceCount).toBe(41);
    expect(stub.sections).toEqual([]);
    expect(stub.voiceId).toBe('v-1');
    expect(stub.date).toBe(Date.parse('2026-08-06T10:24:00Z'));
  });

  it('remoteToSaved re-stamps the server id and title over the content payload', () => {
    const content: SavedBrief = {
      id: 'local-1',
      title: 'Stale local title',
      query: 'old query',
      date: 123,
      sectionCount: 1,
      sourceCount: 2,
      sections: [
        { title: 'S1', level: 1, status: 'done', content: 'Text', sources: [] },
      ],
    };
    const remote: RemoteBrief = {
      id: listItem.id,
      user_id: 'u-1',
      title: 'Server title',
      query: 'server query',
      data_source: 'wfp',
      voice_profile_id: 'v-2',
      content,
      owner_name: 'Priya Raman',
      can_edit: false,
      shared_with: [],
      created_at: listItem.created_at,
      updated_at: listItem.updated_at,
    };
    const saved = remoteToSaved(remote);
    expect(saved.id).toBe(listItem.id);
    expect(saved.title).toBe('Server title');
    expect(saved.query).toBe('server query');
    expect(saved.voiceId).toBe('v-2');
    expect(saved.sections).toHaveLength(1);
  });
});
