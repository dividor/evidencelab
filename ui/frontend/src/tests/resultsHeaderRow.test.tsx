import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ResultsHeaderRow } from '../components/ResultsHeaderRow';
import type { SearchResult } from '../types/api';

jest.mock('../components/ExportResultsButton', () => ({
  ExportResultsButton: () => <button type="button">Export to Word</button>,
}));

const RESULTS: SearchResult[] = [
  { chunk_id: 'c1', doc_id: 'd1', text: 't', page_num: 1, headings: [], score: 0.9, title: 'Doc', metadata: {} },
];
const SORT_LABEL = 'Sort documents by';
const EXPORT_BUTTON = 'Export to Word';
const EXPAND_ALL = 'Expand all';

describe('ResultsHeaderRow group-by-document checkbox', () => {
  const CHECKBOX = 'Group by document';

  test('is shown in both modes, mirrors the setting, and reports a change', () => {
    const onToggle = jest.fn();
    const view = render(<ResultsHeaderRow results={RESULTS} query="q" groupByDocument={false} onGroupByDocumentToggle={onToggle} />);
    const box = screen.getByRole('checkbox', { name: CHECKBOX });
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(onToggle).toHaveBeenCalledWith(true);
    view.rerender(<ResultsHeaderRow results={RESULTS} query="q" groupByDocument onGroupByDocumentToggle={onToggle} />);
    expect(screen.getByRole('checkbox', { name: CHECKBOX })).toBeChecked();
  });

  test('reads Expand all, Sort by, Group by document, Export to Word from left to right', () => {
    render(<ResultsHeaderRow results={RESULTS} query="q" groupByDocument onGroupByDocumentToggle={jest.fn()} onToggleAllGroups={jest.fn()} onGroupSortByChange={jest.fn()} />);
    const order = [
      screen.getByRole('button', { name: EXPAND_ALL }),
      screen.getByLabelText(SORT_LABEL),
      screen.getByRole('checkbox', { name: CHECKBOX }),
      screen.getByRole('button', { name: EXPORT_BUTTON }),
    ];
    for (let i = 0; i < order.length - 1; i += 1) {
      expect(order[i].compareDocumentPosition(order[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });
});

describe('ResultsHeaderRow sort control', () => {
  test('is absent in the flat list', () => {
    render(<ResultsHeaderRow results={RESULTS} query="q" />);
    expect(screen.queryByLabelText(SORT_LABEL)).toBeNull();
    expect(screen.queryByRole('button', { name: EXPAND_ALL })).toBeNull();
    expect(screen.getByRole('button', { name: EXPORT_BUTTON })).toBeInTheDocument();
  });

  test('in group-by-document mode an expand-all button offers the opposite of the current state', () => {
    const onToggle = jest.fn();
    const view = render(<ResultsHeaderRow results={RESULTS} query="q" groupByDocument allGroupsExpanded={false} onToggleAllGroups={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: EXPAND_ALL }));
    expect(onToggle).toHaveBeenCalledWith(true);
    view.rerender(<ResultsHeaderRow results={RESULTS} query="q" groupByDocument allGroupsExpanded onToggleAllGroups={onToggle} />);
    fireEvent.click(screen.getByRole('button', { name: 'Collapse all' }));
    expect(onToggle).toHaveBeenLastCalledWith(false);
  });

  test('in group-by-document mode it sits before the export button with both options', () => {
    const onChange = jest.fn();
    render(<ResultsHeaderRow results={RESULTS} query="q" groupByDocument groupSortBy="relevance" onGroupSortByChange={onChange} />);
    const select = screen.getByLabelText(SORT_LABEL) as HTMLSelectElement;
    expect(select.value).toBe('relevance');
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual(['Relevance', 'Publication Date']);
    const exportButton = screen.getByRole('button', { name: EXPORT_BUTTON });
    expect(select.compareDocumentPosition(exportButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.change(select, { target: { value: 'date' } });
    expect(onChange).toHaveBeenCalledWith('date');
  });
});
