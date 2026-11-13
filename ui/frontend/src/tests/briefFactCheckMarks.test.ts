import { FACT_ID_ATTR, FACT_MARK_CLASS, clearFactMarks, paintFactMarks } from '../components/brief/briefFactCheckMarks';
import { normaliseText, rangeForText } from '../components/brief/briefTextRange';
import type { BriefFactCheckMark } from '../types/testing';

const render = (html: string): HTMLElement => {
  const el = document.createElement('div');
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
};

afterEach(() => {
  document.body.innerHTML = '';
});

// A passage is one span per text node it covers; its text is their text joined.
const markText = (root: HTMLElement, id: number): string =>
  Array.from(root.querySelectorAll(`[${FACT_ID_ATTR}="${id}"]`))
    .map((s) => s.textContent)
    .join('');
const markIds = (root: HTMLElement): string[] =>
  Array.from(new Set(Array.from(root.querySelectorAll(`.${FACT_MARK_CLASS}`)).map((m) => m.getAttribute(FACT_ID_ATTR) || '')));

const mark = (over: Partial<BriefFactCheckMark> = {}): BriefFactCheckMark => ({
  passage_id: 1,
  section_id: 's1',
  section_title: 'Findings',
  passage: 'School meals raised attendance.',
  verdict: 'unsupported',
  verdict_label: 'Unsupported',
  explanation: 'The excerpt reports no change in attendance.',
  problems: ['Contradicted by the source'],
  confidence: 0.9,
  citations: '1',
  quote_not_in_source: false,
  ...over,
});

// A sentence as CitedMarkdown renders it: the `[1]` marker becomes a badge
// whose text is just the number, leaving a space before the full stop.
const CITED = '<p>School meals raised attendance <span class="citation-group"><a class="ai-summary-citation">1</a></span>. Costs rose.</p>';

describe('normaliseText', () => {
  it('collapses whitespace and drops the space before punctuation, mapping back to the source', () => {
    const { text, map } = normaliseText('A fact \n  .  Next');
    expect(text).toBe('A fact. Next');
    // "." sits at index 10 of the raw string, "N" at 13.
    expect(map[text.indexOf('.')]).toBe(10);
    expect(map[text.indexOf('N')]).toBe(13);
  });
});

describe('paintFactMarks', () => {
  it('finds the stored prose although the rendered sentence carries a citation badge', () => {
    const el = render(CITED);
    const missing = paintFactMarks(el, [mark()]);
    expect(missing).toEqual([]);
    const painted = el.querySelector(`.${FACT_MARK_CLASS}`);
    expect(painted?.getAttribute(FACT_ID_ATTR)).toBe('1');
    expect(painted?.className).toContain(`${FACT_MARK_CLASS}-unsupported`);
    // The mark covers the sentence up to its full stop. The badge itself is
    // left untouched (it is React's), so the passage is two spans around it.
    expect(markText(el, 1)).toBe('School meals raised attendance .');
    expect(el.querySelector('.ai-summary-citation')?.closest(`.${FACT_MARK_CLASS}`)).toBeNull();
    expect(el.textContent).toBe('School meals raised attendance 1. Costs rose.');
  });

  it('names the verdict on the mark so it can be read without the pointer', () => {
    const el = render(CITED);
    paintFactMarks(el, [mark({ verdict: 'partially_supported', verdict_label: 'Partially supported' })]);
    const painted = el.querySelector(`.${FACT_MARK_CLASS}`);
    expect(painted?.className).toContain(`${FACT_MARK_CLASS}-partially_supported`);
    expect(painted?.getAttribute('aria-label')).toBe(
      'Partially supported: The excerpt reports no change in attendance.',
    );
  });

  it('reports a passage the prose no longer contains', () => {
    const el = render('<p>The section was rewritten entirely.</p>');
    expect(paintFactMarks(el, [mark({ passage_id: 7 })])).toEqual([7]);
    expect(el.querySelector(`.${FACT_MARK_CLASS}`)).toBeNull();
  });

  it('marks a sentence that appears twice once per judged passage', () => {
    const el = render('<p>Costs rose. Later: Costs rose.</p>');
    paintFactMarks(el, [
      mark({ passage_id: 1, passage: 'Costs rose.' }),
      mark({ passage_id: 2, passage: 'Costs rose.' }),
    ]);
    expect(markIds(el)).toEqual(['1', '2']);
  });

  it('repaints and clears without losing text', () => {
    const el = render(CITED);
    const before = el.textContent;
    paintFactMarks(el, [mark()]);
    paintFactMarks(el, [mark()]);
    expect(markIds(el)).toEqual(['1']);
    expect(markText(el, 1)).toBe('School meals raised attendance .');
    clearFactMarks(el);
    expect(el.querySelector(`.${FACT_MARK_CLASS}`)).toBeNull();
    expect(el.textContent).toBe(before);
  });

  it('leaves a commented passage markable: comment marks are prose, bubbles are not', () => {
    const el = render(
      '<p>School meals <span class="brief-comment-mark">raised attendance</span><button class="brief-comment-bubble">2</button>.</p>',
    );
    expect(paintFactMarks(el, [mark()])).toEqual([]);
    expect(markText(el, 1)).toBe('School meals raised attendance.');
  });
});

describe('rangeForText', () => {
  it('keeps a match inside its paragraph: the last sentence ends in its own block', () => {
    const el = render('<p>First point <span class="citation-group">1</span>.</p><p>Second point.</p>');
    const range = rangeForText(el, 'First point.', { skip: '.citation-group' });
    expect(range?.endContainer.parentElement).toBe(el.querySelector('p'));
    // No sentence runs across a paragraph break.
    expect(rangeForText(el, 'point. Second')).toBeNull();
  });

  it('wraps one text node at a time and never moves an element', () => {
    const el = render('<p>Attendance <strong>rose sharply</strong> after the pilot.</p>');
    const strong = el.querySelector('strong');
    expect(paintFactMarks(el, [mark({ passage: 'rose sharply after' })])).toEqual([]);
    // The <strong> React rendered is still the same node, in the same place.
    expect(el.querySelector('strong')).toBe(strong);
    expect(strong?.parentElement).toBe(el.querySelector('p'));
    expect(markText(el, 1)).toBe('rose sharply after');
    expect(el.textContent).toBe('Attendance rose sharply after the pilot.');
  });

  it('returns null for an empty or absent quote', () => {
    const el = render('<p>Some prose.</p>');
    expect(rangeForText(el, '   ')).toBeNull();
    expect(rangeForText(el, 'missing')).toBeNull();
  });
});
