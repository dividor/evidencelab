import { moveSectionInLevel } from '../components/brief/useBrief';
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

describe('moveSectionInLevel', () => {
  // A(1) B(1) B1(2) C(1)
  const base = (): BriefSection[] => [sec('A', 1), sec('B', 1), sec('B1', 2), sec('C', 1)];

  test('moving a heading up carries its sub-headings as a block', () => {
    expect(ids(moveSectionInLevel(base(), 'B', -1))).toBe('B,B1,A,C');
  });

  test('moving a heading down swaps whole blocks', () => {
    expect(ids(moveSectionInLevel(base(), 'A', 1))).toBe('B,B1,A,C');
  });

  test('a sub-heading cannot move past its parent heading', () => {
    // B1 is the only sub under B; up hits B (a heading), down hits C (a heading).
    expect(ids(moveSectionInLevel(base(), 'B1', -1))).toBe('A,B,B1,C');
    expect(ids(moveSectionInLevel(base(), 'B1', 1))).toBe('A,B,B1,C');
  });

  test('sub-headings reorder among themselves under the same parent', () => {
    const list = [sec('A', 1), sec('A1', 2), sec('A2', 2), sec('B', 1)];
    expect(ids(moveSectionInLevel(list, 'A2', -1))).toBe('A,A2,A1,B');
    expect(ids(moveSectionInLevel(list, 'A1', 1))).toBe('A,A2,A1,B');
  });

  test('ends are no-ops', () => {
    expect(ids(moveSectionInLevel(base(), 'A', -1))).toBe('A,B,B1,C');
    expect(ids(moveSectionInLevel(base(), 'C', 1))).toBe('A,B,B1,C');
  });
});
