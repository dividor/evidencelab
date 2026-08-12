import {
  BUBBLE_CLASS,
  clearCommentMarks,
  MARK_CLASS,
  paintCommentMarks,
} from '../components/brief/briefCommentMarks';

const render = (html: string): HTMLElement => {
  const el = document.createElement('div');
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
};

afterEach(() => {
  document.body.innerHTML = '';
});

describe('paintCommentMarks', () => {
  it('wraps the quoted passage and follows it with a bubble', () => {
    const el = render('<p>School meals raised attendance in Turkana county.</p>');
    const orphans = paintCommentMarks(el, [
      { threadId: 't1', quote: 'raised attendance', resolved: false, count: 1 },
    ]);

    const mark = el.querySelector(`.${MARK_CLASS}`);
    expect(orphans).toEqual([]);
    expect(mark?.textContent).toBe('raised attendance');
    expect(mark?.getAttribute('data-thread-id')).toBe('t1');
    expect(el.querySelector(`.${BUBBLE_CLASS}`)?.getAttribute('data-thread-id')).toBe('t1');
    // The surrounding prose is untouched.
    expect(el.textContent).toContain('School meals raised attendance in Turkana county.');
  });

  it('shows the reply count on the bubble only when a thread has replies', () => {
    const el = render('<p>One two three four.</p>');
    paintCommentMarks(el, [{ threadId: 't1', quote: 'two three', resolved: false, count: 3 }]);
    expect(el.querySelector(`.${BUBBLE_CLASS}`)?.textContent).toBe('3');

    const solo = render('<p>One two three four.</p>');
    paintCommentMarks(solo, [{ threadId: 't2', quote: 'two three', resolved: false, count: 1 }]);
    expect(solo.querySelector(`.${BUBBLE_CLASS}`)?.textContent).toBe('');
  });

  it('marks a resolved thread so it can be dimmed', () => {
    const el = render('<p>Coverage reached 80 percent.</p>');
    paintCommentMarks(el, [{ threadId: 't1', quote: 'reached 80', resolved: true, count: 1 }]);
    expect(el.querySelector(`.${MARK_CLASS}`)?.className).toContain('brief-comment-mark-resolved');
  });

  it('matches a quote whose whitespace differs from the rendered prose', () => {
    // Markdown wraps lines, so the stored quote often has different spacing.
    const el = render('<p>School meals\n   raised attendance sharply.</p>');
    const orphans = paintCommentMarks(el, [
      { threadId: 't1', quote: 'School meals raised attendance', resolved: false, count: 1 },
    ]);
    expect(orphans).toEqual([]);
    expect(el.querySelector(`.${MARK_CLASS}`)).not.toBeNull();
  });

  it('spans a passage that crosses inline markup', () => {
    const el = render('<p>Attendance <strong>rose sharply</strong> after the pilot.</p>');
    const orphans = paintCommentMarks(el, [
      { threadId: 't1', quote: 'rose sharply after', resolved: false, count: 1 },
    ]);
    expect(orphans).toEqual([]);
    expect(el.querySelectorAll(`.${MARK_CLASS}`).length).toBeGreaterThan(0);
  });

  it('reports a thread whose passage is gone instead of dropping it', () => {
    const el = render('<p>The section was rewritten entirely.</p>');
    const orphans = paintCommentMarks(el, [
      { threadId: 'gone', quote: 'a sentence that no longer exists', resolved: false, count: 1 },
    ]);
    expect(orphans).toEqual(['gone']);
    expect(el.querySelector(`.${MARK_CLASS}`)).toBeNull();
  });

  it('marks several passages independently', () => {
    const el = render('<p>Alpha beta gamma delta epsilon.</p>');
    paintCommentMarks(el, [
      { threadId: 'a', quote: 'Alpha beta', resolved: false, count: 1 },
      { threadId: 'b', quote: 'delta epsilon', resolved: false, count: 2 },
    ]);
    const ids = Array.from(el.querySelectorAll(`.${MARK_CLASS}`)).map((m) =>
      m.getAttribute('data-thread-id'),
    );
    expect(ids).toEqual(['a', 'b']);
  });

  it('repainting replaces marks rather than nesting them', () => {
    const el = render('<p>Repeated painting should be idempotent.</p>');
    const marks = [{ threadId: 't1', quote: 'should be', resolved: false, count: 1 }];
    paintCommentMarks(el, marks);
    paintCommentMarks(el, marks);
    expect(el.querySelectorAll(`.${MARK_CLASS}`).length).toBe(1);
    expect(el.querySelectorAll(`.${BUBBLE_CLASS}`).length).toBe(1);
  });
});

describe('clearCommentMarks', () => {
  it('restores the original text', () => {
    const original = '<p>Nothing should be lost when marks are removed.</p>';
    const el = render(original);
    const before = el.textContent;
    paintCommentMarks(el, [{ threadId: 't1', quote: 'should be lost', resolved: false, count: 1 }]);
    clearCommentMarks(el);
    expect(el.querySelector(`.${MARK_CLASS}`)).toBeNull();
    expect(el.querySelector(`.${BUBBLE_CLASS}`)).toBeNull();
    expect(el.textContent).toBe(before);
  });
});
