import { reorderSiblingSections } from '../components/brief/useBrief';
import { BriefSection } from '../components/brief/briefTypes';

const sec = (id: string, level: number): BriefSection => ({
  id,
  title: id,
  level,
  status: 'pending',
  progress: 0,
  content: '',
  sources: [],
  activity: [],
});

const ids = (list: BriefSection[]): string => list.map((s) => s.id).join(',');

describe('reorderSiblingSections (drag-and-drop)', () => {
  // A(1) B(1) B1(2) C(1)
  const base = (): BriefSection[] => [sec('A', 1), sec('B', 1), sec('B1', 2), sec('C', 1)];

  test('dragging a heading down lands it after the target and its children', () => {
    expect(ids(reorderSiblingSections(base(), 'A', 'B'))).toBe('B,B1,A,C');
    expect(ids(reorderSiblingSections(base(), 'A', 'C'))).toBe('B,B1,C,A');
  });

  test('dragging a heading up lands it before the target, carrying its children', () => {
    expect(ids(reorderSiblingSections(base(), 'B', 'A'))).toBe('B,B1,A,C');
    expect(ids(reorderSiblingSections(base(), 'C', 'A'))).toBe('C,A,B,B1');
  });

  test('sub-headings reorder among themselves under the same parent', () => {
    const list = [sec('A', 1), sec('A1', 2), sec('A2', 2), sec('B', 1)];
    expect(ids(reorderSiblingSections(list, 'A1', 'A2'))).toBe('A,A2,A1,B');
    expect(ids(reorderSiblingSections(list, 'A2', 'A1'))).toBe('A,A2,A1,B');
  });

  test('a sub-heading cannot move under a different parent', () => {
    const list = [sec('A', 1), sec('A1', 2), sec('B', 1), sec('B1', 2)];
    expect(ids(reorderSiblingSections(list, 'A1', 'B1'))).toBe('A,A1,B,B1');
  });

  test('cross-level drops and self-drops are no-ops', () => {
    expect(ids(reorderSiblingSections(base(), 'B1', 'A'))).toBe('A,B,B1,C'); // level 2 → level 1
    expect(ids(reorderSiblingSections(base(), 'A', 'A'))).toBe('A,B,B1,C');
  });
});
