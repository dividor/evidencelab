import React from 'react';
import { render } from '@testing-library/react';
import {
  BriefDiff,
  diffBlocks,
  diffWords,
  normalizeQuotes,
  MARK_ADD_OPEN,
  MARK_DEL_OPEN,
} from '../components/brief/BriefDiff';

describe('diffWords', () => {
  test('marks added and removed words, keeping shared text', () => {
    const segs = diffWords('the quick fox', 'the quick brown fox');
    expect(segs.map((s) => s.type)).toContain('add');
    expect(segs.find((s) => s.type === 'add')?.text).toContain('brown');
    expect(segs.filter((s) => s.type === 'del')).toHaveLength(0);
  });
});

describe('diffBlocks', () => {
  test('classifies unchanged, changed, added and removed blocks', () => {
    const oldText = 'Same paragraph.\n\nOld wording here.\n\nDropped paragraph.';
    const newText = 'Same paragraph.\n\nNew wording here.\n\nAppended paragraph.';
    const blocks = diffBlocks(oldText, newText);
    const types = blocks.map((b) => b.type);
    expect(types).toContain('same');
    expect(types).toContain('changed');
    const changed = blocks.find((b) => b.type === 'changed');
    expect(changed?.markdown).toContain(MARK_ADD_OPEN);
    expect(changed?.markdown).toContain(MARK_DEL_OPEN);
  });

  test('a paragraph removed with no replacement becomes a del block', () => {
    const blocks = diffBlocks('Kept.\n\nRemoved paragraph.', 'Kept.');
    expect(blocks.some((b) => b.type === 'del' && b.markdown.includes('Removed'))).toBe(true);
  });
});

describe('BriefDiff rendering', () => {
  test('renders markdown (not raw markers) with ins/del wrapping', () => {
    const oldText = 'Intro text.\n\nThe **quick** fox jumped.';
    const newText = 'Intro text.\n\nThe **quick** brown fox jumped.\n\nA new paragraph.';
    const { container } = render(<BriefDiff oldText={oldText} newText={newText} />);

    // Markdown is rendered: bold becomes <strong>, no literal ** remains.
    expect(container.querySelector('strong')?.textContent).toBe('quick');
    expect(container.textContent).not.toContain('**');

    // The inserted word and the whole-new paragraph are both marked as additions.
    const ins = Array.from(container.querySelectorAll('ins.brief-diff-add'));
    const addedText = ins.map((el) => el.textContent).join(' ');
    expect(addedText).toContain('brown');
    expect(container.textContent).toContain('A new paragraph.');
    expect(addedText).toContain('A new paragraph.');

    // No sentinel characters leak into the visible text.
    expect(container.textContent).not.toMatch(/[\uE000-\uE003]/);
  });

  test('renders removed paragraphs as struck-through del blocks', () => {
    const { container } = render(
      <BriefDiff oldText={'Kept.\n\nRemoved paragraph.'} newText={'Kept.'} />,
    );
    const delBlock = container.querySelector('.brief-diff-block-del');
    expect(delBlock?.textContent).toContain('Removed paragraph.');
  });

  test('renders a changed markdown heading as a heading', () => {
    const { container } = render(
      <BriefDiff oldText={'## Old title\n\nBody.'} newText={'## New title\n\nBody.'} />,
    );
    const h2 = container.querySelector('h2');
    expect(h2).not.toBeNull();
    expect(h2?.textContent).toContain('New title');
    expect(h2?.querySelector('ins.brief-diff-add')?.textContent).toContain('New');
    expect(h2?.querySelector('del.brief-diff-del')?.textContent).toContain('Old');
  });
});

describe('normalizeQuotes', () => {
  test('collapses entity, curly, and straight quotes to one form', () => {
    expect(normalizeQuotes('&#34;free&#34;')).toBe('"free"');
    expect(normalizeQuotes('&quot;a&quot;')).toBe('"a"');
    expect(normalizeQuotes('the government&#39;s plan')).toBe("the government's plan");
    expect(normalizeQuotes('“curly” and ‘curly’')).toBe('"curly" and \'curly\'');
    expect(normalizeQuotes('a &amp; b')).toBe('a & b');
  });

  test('quote-encoding-only differences produce no diff', () => {
    // Old draft has entities, new draft has straight quotes — same text.
    const { container } = render(
      <BriefDiff
        oldText={'The Act declares it &#34;free&#34; [1].'}
        newText={'The Act declares it "free" [1].'}
      />,
    );
    expect(container.querySelector('ins.brief-diff-add')).toBeNull();
    expect(container.querySelector('del.brief-diff-del')).toBeNull();
  });
});
