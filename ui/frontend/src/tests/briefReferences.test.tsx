import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { BriefReferences } from '../components/brief/BriefReferences';
import { GlobalRef } from '../components/brief/briefCitations';
import { SourceReference } from '../types/api';

const MULTIPLE = 'Group by document (multiple per document)';
const SINGLE = 'Group by document (single per document)';

const src = (docId: string, title: string, page: number): SourceReference => ({
  chunkId: `${docId}-${page}`,
  docId,
  title,
  text: '',
  score: 0,
  page,
});

// Per-passage numbering: Doc One cited from p.32 and p.56, Doc Two from p.4.
const PER_PASSAGE: GlobalRef[] = [
  { n: 1, title: 'Doc One', page: 32, source: src('d1', 'Doc One', 32) },
  { n: 2, title: 'Doc Two', page: 4, source: src('d2', 'Doc Two', 4) },
  { n: 3, title: 'Doc One', page: 56, source: src('d1', 'Doc One', 56) },
];

// Per-document numbering: no pages on the references.
const PER_DOCUMENT: GlobalRef[] = [
  { n: 1, title: 'Doc One', source: src('d1', 'Doc One', 32) },
  { n: 2, title: 'Doc Two', source: src('d2', 'Doc Two', 4) },
];

describe('BriefReferences', () => {
  test('offers both grouping checkboxes, unticked by default', () => {
    render(
      <BriefReferences references={PER_PASSAGE} grouping="passage" onGroupingChange={jest.fn()} onSourceClick={jest.fn()} />,
    );
    expect(screen.getByRole('checkbox', { name: MULTIPLE })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: SINGLE })).not.toBeChecked();
  });

  test('renders nothing when there are no references', () => {
    const view = render(
      <BriefReferences references={[]} grouping="passage" onGroupingChange={jest.fn()} onSourceClick={jest.fn()} />,
    );
    expect(view.container).toBeEmptyDOMElement();
  });

  test('ticking a checkbox selects that grouping; unticking returns to per passage', () => {
    const onChange = jest.fn();
    const view = render(
      <BriefReferences references={PER_PASSAGE} grouping="passage" onGroupingChange={onChange} onSourceClick={jest.fn()} />,
    );
    fireEvent.click(screen.getByRole('checkbox', { name: SINGLE }));
    expect(onChange).toHaveBeenLastCalledWith('document-single');

    view.rerender(
      <BriefReferences references={PER_DOCUMENT} grouping="document-single" onGroupingChange={onChange} onSourceClick={jest.fn()} />,
    );
    expect(screen.getByRole('checkbox', { name: SINGLE })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: MULTIPLE })).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: SINGLE }));
    expect(onChange).toHaveBeenLastCalledWith('passage');
  });

  test('the two groupings are exclusive: ticking one replaces the other', () => {
    const onChange = jest.fn();
    render(
      <BriefReferences references={PER_DOCUMENT} grouping="document-single" onGroupingChange={onChange} onSourceClick={jest.fn()} />,
    );
    fireEvent.click(screen.getByRole('checkbox', { name: MULTIPLE }));
    expect(onChange).toHaveBeenLastCalledWith('document-multiple');
  });

  test('per passage: one row per citation with its page', () => {
    render(
      <BriefReferences references={PER_PASSAGE} grouping="passage" onGroupingChange={jest.fn()} onSourceClick={jest.fn()} />,
    );
    const rows = document.querySelectorAll('.brief-footnote-row');
    expect(Array.from(rows).map((r) => r.textContent)).toEqual([
      '1Doc One, p.32',
      '2Doc Two, p.4',
      '3Doc One, p.56',
    ]);
  });

  test('multiple per document: one row per document with each number and page', () => {
    render(
      <BriefReferences references={PER_PASSAGE} grouping="document-multiple" onGroupingChange={jest.fn()} onSourceClick={jest.fn()} />,
    );
    const rows = document.querySelectorAll('.brief-footnote-group');
    expect(Array.from(rows).map((r) => r.textContent)).toEqual([
      'Doc One1 p. 323 p. 56',
      'Doc Two2 p. 4',
    ]);
  });

  test('single per document: one row per document, numbered, with no page numbers', () => {
    render(
      <BriefReferences references={PER_DOCUMENT} grouping="document-single" onGroupingChange={jest.fn()} onSourceClick={jest.fn()} />,
    );
    const rows = document.querySelectorAll('.brief-footnote-row');
    expect(Array.from(rows).map((r) => r.textContent)).toEqual(['1Doc One', '2Doc Two']);
    expect(document.body.textContent).not.toMatch(/p\.\s*\d/);
  });

  test('clicking a document-level reference opens its first cited passage', () => {
    const onSourceClick = jest.fn();
    render(
      <BriefReferences references={PER_DOCUMENT} grouping="document-single" onGroupingChange={jest.fn()} onSourceClick={onSourceClick} />,
    );
    fireEvent.click(screen.getByText('Doc One'));
    expect(onSourceClick).toHaveBeenCalledWith(expect.objectContaining({ docId: 'd1', page: 32 }));
  });
});
